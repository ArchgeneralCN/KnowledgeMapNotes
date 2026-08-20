import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import networkx as nx
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from urllib.parse import quote

from OmniStore.storeManager import storeManager
from OmniText.MDProcessor import MDProcessor
from OmniText.PDFProcessor import PDFProcessor
from text_encoding import read_text_file
from transfer_package import (
    PACKAGE_SUFFIX,
    build_transfer_package,
    graph_from_node_link_data,
    is_transfer_package_filename,
    read_transfer_package,
)
from KnowledgeGraphManager.graph_interactions import (
    GRAPH_EDITOR_VERSION,
    get_local_vis_asset_path,
    prepare_legacy_graph_html,
)
from KnowledgeGraphManager.sigma_static import (
    SIGMA_STATIC_PAGE_VERSION,
    write_sigma_graph_pages,
)
from KnowledgeGraphManager.graph_editing import (
    GraphEditError,
    GraphHistory,
    apply_graph_mutation,
    graph_payload,
    state_from_snapshot,
    state_snapshot,
)
from services.ai_runtime import (
    AIRuntime,
    create_ai_settings_router,
    create_openai_client,
    parse_boolean,
)
from services.document_store import DocumentStore
from services.processing_progress import ProcessingProgressStore, STAGE_CONFIG
from services.rag_service import RAGRequest, RAGService, create_rag_router

load_dotenv(dotenv_path="./.env")
# Do not force a third-party mirror here.  Mirrors commonly redirect or omit
# Hugging Face metadata headers, which makes huggingface_hub raise
# FileMetadataError.  Users behind a restricted network can opt in with
# HF_ENDPOINT in .env or the process environment.
os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("文件处理服务")


class GraphMutationRequest(BaseModel):
    """One atomic edit sent by the PyVis graph editor."""

    operation: str
    revision: Optional[int] = None
    node_id: Optional[str] = None
    name: Optional[str] = None
    entity_type: Optional[str] = None
    edge_id: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    relation: Optional[str] = None
    context: Optional[str] = None
    weight: Optional[float] = None


class DocumentContentUpdate(BaseModel):
    """Rich document draft submitted by the document editor."""

    content: str = Field(min_length=1, max_length=10_000_000)
    rich_content: Optional[str] = Field(default=None, max_length=20_000_000)


app = FastAPI(title="图谱笔记", description="大模型知识图谱笔记软件")
app.add_middleware(GZipMiddleware, minimum_size=1_000, compresslevel=5)


class SPAStaticFiles(StaticFiles):
    """Serve static assets and fall back to index.html for frontend routes."""

    async def get_response(self, path, scope):
        if scope.get("frontend_api_request"):
            raise StarletteHTTPException(status_code=404)

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (
                exc.status_code != 404
                or scope.get("method") not in {"GET", "HEAD"}
                or Path(path).suffix
            ):
                raise
            return await super().get_response("index.html", scope)


@app.middleware("http")
async def support_frontend_api_prefix(request: Request, call_next):
    """Allow the bundled frontend's /api requests to reach the API routes.

    The Vite development server strips this prefix through its proxy. When the
    built frontend is served directly by FastAPI, the same compatibility is
    provided here so one build works in both environments.
    """
    path = request.scope.get("path", "")
    if path == "/api" or path.startswith("/api/"):
        request.scope["frontend_api_request"] = True
        request.scope["path"] = path[4:] or "/"
    return await call_next(request)

UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", "uploads"))
TXT_FOLDER = Path(os.getenv("TXT_FOLDER", "txt_files"))
RESULT_FOLDER = Path(os.getenv("RESULT_FOLDER", "results"))
STATUS_FOLDER = Path(os.getenv("STATUS_FOLDER", "processing_states"))
GRAPH_HISTORY_FOLDER = Path(os.getenv("GRAPH_HISTORY_FOLDER", "graph_history"))
document_store = DocumentStore(TXT_FOLDER, GRAPH_HISTORY_FOLDER, logger)
get_source_text_path = document_store.source_path
get_document_draft_path = document_store.draft_path
get_document_rich_path = document_store.rich_path
get_document_history_path = document_store.history_path
_read_document_history = document_store.read_history
_write_document_history = document_store.write_history
_document_snapshot = document_store.snapshot
_restore_document_snapshot = document_store.restore_snapshot
_append_document_version = document_store.append_version
_document_operation_label = document_store.operation_label
MAX_TRANSFER_PACKAGE_SIZE = 100 * 1024 * 1024
DEFAULT_EXAMPLE_FOLDER = Path(__file__).resolve().parent / "default_examples"
DEFAULT_EXAMPLE_PACKAGE = DEFAULT_EXAMPLE_FOLDER / f"本软件使用说明{PACKAGE_SUFFIX}"
try:
    CHECKPOINT_INTERVAL = max(1, int(os.getenv("CHECKPOINT_INTERVAL", "10")))
except (TypeError, ValueError):
    CHECKPOINT_INTERVAL = 10

processing_progress = ProcessingProgressStore(STATUS_FOLDER)
PROCESS_STATUS = processing_progress.statuses
process_status_lock = processing_progress.lock
PROCESSING_STAGE_CONFIG = STAGE_CONFIG


def _sync_progress_store() -> None:
    """Keep the service compatible with tests that replace STATUS_FOLDER."""
    processing_progress.status_folder = STATUS_FOLDER


def persist_process_status(base_name: str, status: Dict[str, Any]) -> None:
    _sync_progress_store()
    processing_progress.persist(base_name, status)


def set_process_status(base_name: str, status: str, **updates: Any) -> None:
    _sync_progress_store()
    processing_progress.set(base_name, status, **updates)


def get_process_status(base_name: str) -> Optional[Dict[str, Any]]:
    return processing_progress.get(base_name)


def _new_stage_progress(
    stage: str,
    completed: int = 0,
    total: int = 0,
    total_known: bool = False,
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return processing_progress.new_stage(stage, completed, total, total_known, previous)


def _overall_stage_metrics(stage_progress: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return processing_progress.overall(stage_progress)


def initialize_stage_progress(
    base_name: str,
    status: str,
    total_chunks: Optional[int],
    completed_chunks: int = 0,
    preserve_timings: bool = False,
) -> None:
    _sync_progress_store()
    processing_progress.initialize(
        base_name, status, total_chunks, completed_chunks, preserve_timings
    )


def create_stage_progress_callback(base_name: str, status: str = "processing"):
    _sync_progress_store()
    return processing_progress.stage_callback(base_name, status)


def create_fusion_progress_callback(base_name: str, status: str = "processing"):
    _sync_progress_store()
    return processing_progress.fusion_callback(base_name, status)


# Create runtime directories before restoring interrupted processing state.
for folder in [UPLOAD_FOLDER, TXT_FOLDER, RESULT_FOLDER, STATUS_FOLDER, GRAPH_HISTORY_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)


def restore_process_statuses() -> None:
    _sync_progress_store()
    damaged = processing_progress.restore(UPLOAD_FOLDER, TXT_FOLDER, RESULT_FOLDER)
    for path in damaged:
        logger.warning("忽略损坏的处理状态文件: %s", path)


restore_process_statuses()


def parse_file_extensions(value: str) -> set[str]:
    """Normalize comma-separated extensions from environment configuration."""
    configured_extensions = value.strip().strip("[]")
    if not configured_extensions:
        return set()
    return {
        f".{extension.strip().lstrip('.').lower()}"
        for extension in configured_extensions.split(",")
        if extension.strip()
    }


def get_safe_filename(filename: str) -> str:
    """Reject path-like upload names before they are used to build local paths."""
    if not filename or filename != Path(filename).name or "\\" in filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    if filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="文件名不合法")
    return filename


def get_base_name(filename: str) -> str:
    base_name = Path(get_safe_filename(filename)).stem
    if not base_name:
        raise HTTPException(status_code=400, detail="文件名不合法")
    return base_name


def get_transfer_import_path(base_name: str) -> Path:
    """Return the private staging path for one fully uploaded transfer package."""
    return UPLOAD_FOLDER / f".{get_base_name(f'{base_name}.txt')}.importing{PACKAGE_SUFFIX}"

# 初始化知识图谱组件
from OmniStore.chromadb_store import StoreTool
from sentence_transformers import SentenceTransformer
from KnowledgeGraphManager.KGManager import (
    KgManager,
    PROCESSING_PROMPT_FILES,
    ProcessingPaused,
    normalize_community_pagination_settings,
)



device = os.getenv("DEVICE") or "cpu"


def _load_embedding_model() -> SentenceTransformer:
    """Load embeddings without contacting the hub for a configured local path."""
    use_local = os.getenv("IS_USE_LOCAL", "False").strip().lower() in {"1", "true", "yes", "on"}
    model_name = os.getenv("EMBEDDINGS_PATH" if use_local else "EMBEDDINGS")
    if not model_name:
        setting = "EMBEDDINGS_PATH" if use_local else "EMBEDDINGS"
        raise RuntimeError(f"{setting} is required to load the embedding model")

    if use_local:
        model_path = Path(model_name).expanduser()
        if not model_path.is_dir():
            raise RuntimeError(
                f"Local embedding model directory does not exist: {model_path}. "
                "Run start.py to download models or set IS_USE_LOCAL=False."
            )
        return SentenceTransformer(
            str(model_path), device=device, local_files_only=True
        )

    return SentenceTransformer(model_name, device=device)


embeddings = _load_embedding_model()


# 创建两个独立的存储工具
chromadb_store = StoreTool(storage_path= os.getenv("CHROMADB_PATH"), embedding_function=embeddings)
graph_history = GraphHistory(GRAPH_HISTORY_FOLDER)
graph_edit_lock = Lock()

MAX_CUSTOM_PROMPT_LENGTH = 30_000
(
    DEFAULT_COMMUNITY_MIN_SIZE_MODE,
    DEFAULT_COMMUNITY_MIN_SIZE,
    DEFAULT_COMMUNITY_AUTO_PERCENT,
) = normalize_community_pagination_settings()


def _graph_manager_state(manager: KgManager) -> Dict[str, Any]:
    base_name = str(manager.file or "")
    return {
        "file": manager.file,
        "kg_triplet": manager.kg_triplet,
        "bidirectional_mapping": manager.bidirectional_mapping,
        "current_G": manager.current_G,
        "Bolts": manager.Bolts,
        "original_file_type": manager.original_file_type,
        "community_min_size_mode": manager.community_min_size_mode,
        "community_min_size": manager.community_min_size,
        "community_auto_percent": manager.community_auto_percent,
        "document": _document_snapshot(base_name) if base_name else {},
    }


def _load_editable_graph(base_name: str) -> KgManager:
    manager = KgManager(
        agent=kg_agent,
        splitter=kg_splitter,
        embedding_model=embeddings,
        store=chromadb_store,
    )
    if not manager.load_store(base_name):
        raise HTTPException(status_code=404, detail="图谱状态不存在")
    return manager


def _restore_manager_state(manager: KgManager, state: Dict[str, Any]) -> None:
    manager.file = state.get("file") or manager.file
    manager.kg_triplet = state.get("kg_triplet") or []
    manager.bidirectional_mapping = state.get("bidirectional_mapping") or {
        "entity_to_label": {}, "label_to_entities": defaultdict(list)
    }
    manager.current_G = state.get("current_G") or nx.DiGraph()
    manager.Bolts = state.get("Bolts") or []
    manager.original_file_type = state.get("original_file_type") or ".txt"
    manager.configure_community_pagination(
        state.get("community_min_size_mode"),
        state.get("community_min_size"),
        state.get("community_auto_percent"),
    )


def _current_graph_revision(base_name: str) -> int:
    versions = graph_history.list_versions(base_name)
    return int(versions[-1]["revision"]) if versions else 0


def _ensure_graph_editable(base_name: str) -> None:
    status = (get_process_status(base_name) or {}).get("status")
    if status in {"uploading", "processing", "updating", "resuming", "pausing", "redrawing"}:
        raise HTTPException(status_code=409, detail="文件正在处理，暂不能编辑图谱")


def _rebuild_editable_graph(manager: KgManager) -> None:
    """Rebuild the legacy NetworkX projection, including isolated edited nodes."""
    manager.三元组转有向图nx(manager.kg_triplet)
    labels = manager.bidirectional_mapping.get("entity_to_label", {})
    for name, label in labels.items():
        if name not in manager.current_G:
            manager.current_G.add_node(name, title=label, group=label)


@app.get("/graph-data/{filename}")
async def get_editable_graph(filename: str):
    """Return graph JSON for the PyVis editor.

    The legacy PyVis result endpoints remain unchanged and continue to serve
    the original graph renderer.
    """
    base_name = get_base_name(filename)
    manager = _load_editable_graph(base_name)
    return {
        **graph_payload(_graph_manager_state(manager), _current_graph_revision(base_name)),
        "legacy_url": f"/api/result/{quote(base_name + '.html', safe='')}"
    }


@app.post("/redraw-graph/{filename}")
async def redraw_graph(
    filename: str,
    renderer: str = "all",
    community_min_size_mode: str = DEFAULT_COMMUNITY_MIN_SIZE_MODE,
    community_min_size: int = DEFAULT_COMMUNITY_MIN_SIZE,
    community_auto_percent: float = DEFAULT_COMMUNITY_AUTO_PERCENT,
):
    """Redraw one file's complete graph from its saved state."""
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    renderer = str(renderer or "all").strip().lower()
    if renderer not in {"all", "pyvis", "sigma"}:
        raise HTTPException(status_code=422, detail="renderer 必须是 pyvis 或 sigma")
    try:
        community_settings = normalize_community_pagination_settings(
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    progress = get_process_status(base_name) or {}
    status = progress.get("status", "completed")
    if status in {"uploading", "processing", "updating", "resuming", "pausing", "redrawing"}:
        raise HTTPException(status_code=409, detail="文件正在处理，暂不能重新绘制图谱")
    if status != "completed":
        raise HTTPException(status_code=409, detail="只有已完成的文件才能重新绘制图谱")
    if chromadb_store.load_state(base_name) is None:
        raise HTTPException(status_code=404, detail="图谱状态不存在，无法重新绘制")

    set_process_status(
        base_name,
        "redrawing",
        percentage=100,
        community_min_size_mode=community_settings[0],
        community_min_size=community_settings[1],
        community_auto_percent=community_settings[2],
        estimated_remaining_seconds=None,
        error_message=None,
    )
    try:
        history_revision = await asyncio.to_thread(
            redraw_graph_from_store,
            base_name,
            renderer,
            *community_settings,
        )
    except HTTPException:
        set_process_status(
            base_name,
            "completed",
            percentage=100,
            estimated_remaining_seconds=0,
            error_message="图谱重新绘制失败",
        )
        raise
    except Exception as exc:
        logger.error("重新绘制图谱失败: %s", base_name, exc_info=True)
        set_process_status(
            base_name,
            "completed",
            percentage=100,
            estimated_remaining_seconds=0,
            error_message=f"图谱重新绘制失败: {exc}",
        )
        raise HTTPException(status_code=500, detail="图谱重新绘制失败，原图谱仍然保留") from exc

    mark_file_processing_completed(base_name)
    return {
        "status": "completed",
        "filename": filename,
        "message": f"{renderer.upper() if renderer != 'all' else '全部'} 图谱已根据当前保存状态重新绘制",
        "renderer": renderer,
        "history_revision": history_revision,
    }


@app.get("/graph-history/{filename}")
async def get_graph_history(filename: str):
    base_name = get_base_name(filename)
    return {"versions": graph_history.list_versions(base_name)}


@app.get("/graph-sources/{filename}")
async def get_graph_sources(filename: str):
    """Return the static, per-block source highlight index generated with the graph."""
    base_name = get_base_name(filename)
    highlight_index = RESULT_FOLDER / base_name / f"{base_name}.highlights.json"
    current_index = {}
    if highlight_index.is_file():
        try:
            current_index = json.loads(highlight_index.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            current_index = {}
        try:
            current_schema = int(current_index.get("schema") or 0)
        except (TypeError, ValueError):
            current_schema = 0
        if current_schema >= 2:
            return FileResponse(
                highlight_index,
                media_type="application/json",
                headers={"Cache-Control": "no-cache"},
            )

    # Compatibility for graph pages created before static highlight indexes:
    # migrate once on first access, then every later request is a file response.
    manager = _load_editable_graph(base_name)
    highlight_index.parent.mkdir(parents=True, exist_ok=True)
    manager._写入静态高亮索引(
        highlight_index,
        current_index if isinstance(current_index, dict) else None,
    )
    return FileResponse(
        highlight_index,
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/graph-mutation/{filename}")
async def mutate_editable_graph(filename: str, request: GraphMutationRequest):
    base_name = get_base_name(filename)
    _ensure_graph_editable(base_name)
    with graph_edit_lock:
        manager = _load_editable_graph(base_name)
        current_revision = _current_graph_revision(base_name)
        if request.revision is not None and request.revision != current_revision:
            raise HTTPException(
                status_code=409,
                detail=f"图谱版本已变化，请先重新加载（当前版本 {current_revision}）",
            )
        before = state_snapshot(_graph_manager_state(manager))
        mutation = request.model_dump(exclude_none=True)
        try:
            operation = apply_graph_mutation(_graph_manager_state(manager), mutation)
            _rebuild_editable_graph(manager)
            manager.save_store()
            revision = graph_history.commit(
                base_name,
                before,
                _graph_manager_state(manager),
                operation,
            )
            # Keep the old renderer useful as a fallback after an edit.
            try:
                render_graph_atomically(manager, base_name)
            except Exception:
                # The persisted graph state is authoritative for this new
                # feature; an old HTML fallback can be regenerated later.
                logger.exception("编辑后更新传统图谱页面失败: %s", base_name)
        except GraphEditError as exc:
            _restore_manager_state(manager, state_from_snapshot(before))
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            logger.exception("图谱编辑失败: %s", base_name)
            try:
                _restore_manager_state(manager, state_from_snapshot(before))
                manager.save_store()
            except Exception:
                logger.exception("图谱编辑失败后的状态恢复失败: %s", base_name)
            raise HTTPException(status_code=500, detail="图谱编辑失败，原图谱已尽量恢复")
        return {
            **graph_payload(_graph_manager_state(manager), revision),
            "message": "图谱修改已保存",
        }


@app.post("/graph-restore/{filename}/{revision}")
async def restore_editable_graph(filename: str, revision: int, request: GraphMutationRequest | None = None):
    base_name = get_base_name(filename)
    _ensure_graph_editable(base_name)
    with graph_edit_lock:
        manager = _load_editable_graph(base_name)
        current_revision = _current_graph_revision(base_name)
        requested_revision = request.revision if request and request.revision is not None else current_revision
        if requested_revision != current_revision:
            raise HTTPException(status_code=409, detail="图谱版本已变化，请先重新加载")
        restored = graph_history.get_version(base_name, revision)
        if restored is None:
            raise HTTPException(status_code=404, detail="历史版本不存在")
        before = state_snapshot(_graph_manager_state(manager))
        _restore_manager_state(manager, restored)
        try:
            _restore_document_snapshot(base_name, restored.get("document"))
            _rebuild_editable_graph(manager)
            manager.save_store()
            new_revision = graph_history.commit(
                base_name,
                before,
                _graph_manager_state(manager),
                f"restore:{revision}",
            )
            try:
                render_graph_atomically(manager, base_name)
            except Exception:
                logger.exception("还原后更新传统图谱页面失败: %s", base_name)
        except Exception:
            logger.exception("图谱还原失败: %s", base_name)
            _restore_manager_state(manager, state_from_snapshot(before))
            _restore_document_snapshot(base_name, before.get("document"))
            manager.save_store()
            raise HTTPException(status_code=500, detail="图谱还原失败，原图谱已恢复")
        return {
            **graph_payload(_graph_manager_state(manager), new_revision),
            "message": f"已还原到版本 {revision}，并创建新版本 {new_revision}",
        }


def get_default_processing_prompts() -> Dict[str, str]:
    """Load the general processing prompts for the active prompt version."""
    prompt_folder = Path("prompt") / os.getenv("PROMPTVISION", "v1")
    return {
        stage: (prompt_folder / filename).read_text(encoding="utf-8")
        for stage, filename in PROCESSING_PROMPT_FILES.items()
    }


def normalize_processing_prompts(
    note_type: str,
    entity_prompt: Optional[str],
    relationship_prompt: Optional[str],
    fusion_prompt: Optional[str],
) -> Dict[str, str]:
    if note_type not in {"general", "story", "custom"}:
        raise HTTPException(status_code=422, detail="不支持的笔记类型")
    if note_type != "custom":
        return {}

    submitted_prompts = {
        "entity_extraction": entity_prompt,
        "relationship_extraction": relationship_prompt,
        "knowledge_fusion": fusion_prompt,
    }
    normalized_prompts = {}
    for stage, value in submitted_prompts.items():
        prompt = (value or "").strip()
        if len(prompt) > MAX_CUSTOM_PROMPT_LENGTH:
            raise HTTPException(status_code=422, detail="单个自定义提示词不能超过 30000 个字符")
        if prompt:
            normalized_prompts[stage] = prompt
    return normalized_prompts

ai_runtime = AIRuntime(logger)
client = ai_runtime.client
fallback_client = ai_runtime.fallback_client
if client is None:
    logger.info("未在环境变量中配置 AI 服务，等待用户在前端完成设置")

# The vision client is independent from the text-model runtime.
vl_client = create_openai_client(
    api_key=os.getenv("VL_API_KEY", "").strip(),
    base_url=os.getenv("VL_BASE_URL", "").strip(),
)

from LLM.Openai_Agent import OpenaiAgent

rag_agent = OpenaiAgent(
    client,
    model_name=ai_runtime.settings["model_name"],
    temperature=ai_runtime.settings["temperature"],
    enable_thinking=ai_runtime.settings["enable_thinking"],
    stream=ai_runtime.settings["stream"],
    fallback_client=fallback_client,
    fallback_model_name=ai_runtime.settings["fallback_model_name"],
    fallback_stream=ai_runtime.settings["fallback_stream"],
)
kg_agent = OpenaiAgent(
    client,
    model_name=ai_runtime.settings["model_name"],
    temperature=ai_runtime.settings["temperature"],
    enable_thinking=ai_runtime.settings["enable_thinking"],
    stream=ai_runtime.settings["stream"],
    fallback_client=fallback_client,
    fallback_model_name=ai_runtime.settings["fallback_model_name"],
    fallback_stream=ai_runtime.settings["fallback_stream"],
)
app.include_router(create_ai_settings_router(ai_runtime, rag_agent, kg_agent))


def require_ai_settings() -> None:
    """Compatibility facade used by processing and RAG endpoints."""
    ai_runtime.require_settings()


async def validate_current_ai_settings() -> None:
    """Validate the active runtime before starting a long-running job."""
    await ai_runtime.validate_current()


@app.get("/processing-prompts/defaults")
async def get_processing_prompt_defaults():
    """Return the general templates used to initialize custom processing prompts."""
    try:
        return get_default_processing_prompts()
    except OSError as exc:
        logger.exception("读取通用处理提示词失败")
        raise HTTPException(status_code=500, detail="读取通用处理提示词失败") from exc

# File extensions are configured as `[txt,pdf]` in the example environment file.
simple_files = parse_file_extensions(os.getenv("SIMPLE", ""))
semantic_files = parse_file_extensions(os.getenv("SEMANTIC", ""))
character_files = parse_file_extensions(os.getenv("CHARACTER", ""))


def _chunk_token_setting(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


chunk_max_tokens = _chunk_token_setting("KG_CHUNK_MAX_TOKENS", 1024, 128)
chunk_min_tokens = min(
    chunk_max_tokens - 1,
    _chunk_token_setting("KG_CHUNK_MIN_TOKENS", 384, 1),
)
CHUNK_MAX_TOKENS_LIMIT = 32_768
CHUNK_MIN_TOKENS_LIMIT = 128


def normalize_chunk_token_settings(
    max_tokens: Optional[int] = None,
    min_tokens: Optional[int] = None,
) -> tuple[int, int]:
    """Validate the per-file splitter settings captured when a job starts."""
    resolved_max = chunk_max_tokens if max_tokens is None else int(max_tokens)
    resolved_min = chunk_min_tokens if min_tokens is None else int(min_tokens)
    if not CHUNK_MIN_TOKENS_LIMIT <= resolved_max <= CHUNK_MAX_TOKENS_LIMIT:
        raise ValueError(
            f"每块最大 Token 必须在 {CHUNK_MIN_TOKENS_LIMIT} 到 {CHUNK_MAX_TOKENS_LIMIT} 之间"
        )
    if resolved_min < 1 or resolved_min >= resolved_max:
        raise ValueError("每块最小 Token 必须大于 0 且小于最大 Token")
    return resolved_max, resolved_min

# 初始化默认分割器
kg_splitter = None

# 创建默认分割器
if simple_files:
    from TextSlicer.SimpleTextSplitter import SimpleTextSplitter
    kg_splitter = SimpleTextSplitter(chunk_max_tokens, chunk_min_tokens)
elif semantic_files:
    from TextSlicer.SemanticTextSplitter import SemanticTextSplitter
    kg_splitter = SemanticTextSplitter(chunk_max_tokens, chunk_min_tokens)
elif character_files:
    from TextSlicer.CharacterTextSplitter import CharacterTextSplitter
    kg_splitter = CharacterTextSplitter(
        separator="</end>",
        keep_separator=False,
        max_tokens=chunk_max_tokens,
        min_tokens=chunk_min_tokens,
    )


def get_splitter_for_extension(
    file_extension: str,
    max_tokens: Optional[int] = None,
    min_tokens: Optional[int] = None,
):
    """Build the configured splitter for a file type, with a default fallback."""
    resolved_max, resolved_min = normalize_chunk_token_settings(max_tokens, min_tokens)
    if file_extension in simple_files:
        return SimpleTextSplitter(resolved_max, resolved_min)
    if file_extension in semantic_files:
        return SemanticTextSplitter(resolved_max, resolved_min)
    if file_extension in character_files:
        return CharacterTextSplitter(
            separator="</end>",
            keep_separator=False,
            max_tokens=resolved_max,
            min_tokens=resolved_min,
        )
    if kg_splitter is None:
        return None
    if kg_splitter.__class__.__name__ == "CharacterTextSplitter":
        return kg_splitter.__class__(
            separator="</end>",
            keep_separator=False,
            max_tokens=resolved_max,
            min_tokens=resolved_min,
        )
    return kg_splitter.__class__(resolved_max, resolved_min)


# 创建两个独立的kg_manager
kg_manager = KgManager(agent=kg_agent, splitter=kg_splitter, embedding_model=embeddings, store=chromadb_store)

FILE_PROCESSORS = {
    ".pdf": PDFProcessor,
    ".md": MDProcessor,
}

cors_origins = [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    # Wildcard origins cannot be used with credentials by browsers. This API does
    # not use cookie-based authentication, so leave credentials disabled.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

file_locks: Dict[str, Lock] = {}


def _load_rag_graph_payload(base_name: str) -> Dict[str, Any]:
    """Load the current editable graph snapshot used to build RAG citations."""
    manager = _load_editable_graph(base_name)
    return graph_payload(
        _graph_manager_state(manager),
        _current_graph_revision(base_name),
    )


rag_service = RAGService(
    vector_store=chromadb_store,
    kg_agent=kg_agent,
    rag_agent=rag_agent,
    require_ai_settings=require_ai_settings,
    safe_filename=get_safe_filename,
    base_name=get_base_name,
    graph_payload_loader=_load_rag_graph_payload,
    logger=logger,
)
app.include_router(create_rag_router(rag_service))

# Compatibility aliases for tests and integrations that imported these from main.
rag_executor = rag_service.executor
rag_locks = rag_service.document_locks
message_queues = rag_service.message_queues
session_responses = rag_service.session_responses
initialize_session = rag_service.initialize_session
build_rag_citations = rag_service.build_citations
process_session_queue = rag_service.process_session_queue


def export_file_transfer_package(base_name: str) -> tuple[bytes, str]:
    """Collect one completed file into a portable, re-importable ZIP package."""
    progress = get_process_status(base_name) or {}
    if progress.get("status", "completed") != "completed":
        raise ValueError("只能下载已处理完成的文件")

    state = chromadb_store.load_state(base_name)
    if not state:
        raise FileNotFoundError("找不到可导出的图谱状态")

    original_filename = get_safe_filename(
        str(state.get("original_file_type") or progress.get("original_filename") or f"{base_name}.txt")
    )
    processed_path = TXT_FOLDER / f"{base_name}.txt"
    source_path = get_source_text_path(base_name)
    graph_directory = RESULT_FOLDER / base_name
    if not processed_path.is_file() or not graph_directory.is_dir():
        raise FileNotFoundError("原文或图谱页面不完整，无法导出")

    processed_text, _ = read_text_file(processed_path)
    if source_path.is_file():
        source_text, _ = read_text_file(source_path)
    else:
        source_text = processed_text

    original_path = UPLOAD_FOLDER / original_filename
    if original_path.is_file():
        original_content = original_path.read_bytes()
    else:
        # Older completed records may predate preservation of the binary upload.
        # Keep the package complete by exporting the normalized source as TXT.
        original_filename = f"{base_name}.txt"
        original_content = source_text.encode("utf-8")

    graph_pages = {
        page.name: prepare_legacy_graph_html(
            page.read_text(encoding="utf-8")
        ).encode("utf-8")
        for page in sorted(graph_directory.glob("*.html"))
        if page.is_file()
    }
    rag_history = chromadb_store.get_rag_history(base_name)
    package = build_transfer_package(
        base_name=base_name,
        original_filename=original_filename,
        state=state,
        processing_status=progress,
        original_content=original_content,
        source_text=source_text,
        processed_text=processed_text,
        graph_pages=graph_pages,
        rag_history=rag_history,
    )
    return package, f"{base_name}{PACKAGE_SUFFIX}"


def import_file_transfer_package(payload: bytes) -> Dict[str, Any]:
    """Restore a package directly into storage without invoking an AI model."""
    imported = read_transfer_package(payload)
    base_name = get_base_name(f"{imported.base_name}.txt")
    original_filename = get_safe_filename(imported.original_filename)
    if chromadb_store.load_state(base_name) is not None or (RESULT_FOLDER / base_name).exists():
        raise FileExistsError(f"文件 {original_filename} 已存在，请先删除后再导入")
    if (UPLOAD_FOLDER / original_filename).exists():
        raise FileExistsError(f"原始文件 {original_filename} 已存在")

    state = imported.state
    mapping = state.get("bidirectional_mapping") or {}
    manager = KgManager(
        agent=kg_agent,
        splitter=kg_splitter,
        embedding_model=embeddings,
        store=chromadb_store,
    )
    manager.file = base_name
    manager.kg_triplet = state.get("kg_triplet") or []
    manager.bidirectional_mapping = {
        "entity_to_label": dict(mapping.get("entity_to_label") or {}),
        "label_to_entities": defaultdict(
            list,
            mapping.get("label_to_entities") or {},
        ),
    }
    manager.current_G = graph_from_node_link_data(state["current_G"])
    manager.Bolts = [tuple(block) for block in (state.get("Bolts") or [])]
    manager.original_file_type = original_filename
    manager.configure_community_pagination(
        state.get("community_min_size_mode"),
        state.get("community_min_size"),
        state.get("community_auto_percent"),
    )

    result_directory = RESULT_FOLDER / base_name
    created_paths = [
        UPLOAD_FOLDER / original_filename,
        get_source_text_path(base_name),
        TXT_FOLDER / f"{base_name}.txt",
        result_directory,
    ]
    try:
        manager.save_store()
        created_paths[0].write_bytes(imported.original_content)
        created_paths[1].write_text(imported.source_text, encoding="utf-8")
        created_paths[2].write_text(imported.processed_text, encoding="utf-8")
        result_directory.mkdir(parents=True, exist_ok=False)
        for page_name, content in imported.graph_pages.items():
            (result_directory / page_name).write_bytes(content)
        if imported.rag_history:
            chromadb_store.save_rag_history(base_name, imported.rag_history)

        completed_chunks = len(manager.Bolts)
        restored_status = {
            **{
                key: value
                for key, value in imported.processing_status.items()
                if key not in {"status", "updated_at"}
            },
            "original_filename": original_filename,
            "source_text_path": str(get_source_text_path(base_name)),
            "completed_chunks": completed_chunks,
            "total_chunks": max(
                completed_chunks,
                int(imported.processing_status.get("total_chunks") or 0),
            ),
            "imported_from_package": True,
            "percentage": 100,
            "partial_available": False,
            "resumable": False,
            "pause_requested": False,
            "error_message": None,
        }
        set_process_status(base_name, "completed", **restored_status)
    except Exception:
        try:
            chromadb_store.delete_rag_history([base_name])
            chromadb_store.delete_states([base_name])
        except Exception:
            logger.warning("回滚失败的迁移包导入时清理数据库失败", exc_info=True)
        for path in created_paths[:3]:
            if path.is_file():
                path.unlink()
        if result_directory.is_dir():
            shutil.rmtree(result_directory)
        raise

    return {
        "status": "completed",
        "message": "图谱迁移包已导入，无需重新调用 AI 处理",
        "filename": original_filename,
        "base_name": base_name,
        "imported": True,
        "percentage": 100,
    }


def process_transfer_package_import(base_name: str, package_path: Path) -> None:
    """Import a fully staged package independently of the browser request."""
    try:
        import_file_transfer_package(package_path.read_bytes())
    except Exception as exc:
        logger.error("后台导入图谱迁移包失败: %s", exc, exc_info=True)
        current = get_process_status(base_name) or {}
        set_process_status(
            base_name,
            "error",
            original_filename=current.get("original_filename") or f"{base_name}.txt",
            percentage=0,
            partial_available=False,
            resumable=False,
            pause_requested=False,
            error_message=f"图谱迁移包导入失败: {exc}",
        )
    finally:
        package_path.unlink(missing_ok=True)


def default_example_exists(base_name: str) -> bool:
    """Avoid replacing either complete or partially created user data."""
    local_paths_exist = (
        base_name in PROCESS_STATUS
        or (RESULT_FOLDER / base_name).exists()
        or (TXT_FOLDER / f"{base_name}.txt").exists()
        or get_source_text_path(base_name).exists()
        or any(UPLOAD_FOLDER.glob(f"{base_name}.*"))
    )
    return local_paths_exist or chromadb_store.load_state(base_name) is not None


def install_default_examples() -> None:
    """Install the bundled user guide once, without invoking an AI model."""
    if not parse_boolean(os.getenv("DEFAULT_EXAMPLES_ENABLED"), default=True):
        logger.info("已通过 DEFAULT_EXAMPLES_ENABLED 关闭默认示例")
        return
    if not DEFAULT_EXAMPLE_PACKAGE.is_file():
        logger.warning("默认使用说明迁移包不存在: %s", DEFAULT_EXAMPLE_PACKAGE)
        return

    # Deployment tooling can accidentally leave a Git/LFS pointer or a
    # truncated artifact in place of the bundled ZIP. Keep startup available
    # and make that packaging problem obvious in the log.
    try:
        package_size = DEFAULT_EXAMPLE_PACKAGE.stat().st_size
        if not zipfile.is_zipfile(DEFAULT_EXAMPLE_PACKAGE):
            with DEFAULT_EXAMPLE_PACKAGE.open("rb") as package_file:
                header = package_file.read(32)
            logger.warning(
                "默认使用说明迁移包不是有效 ZIP，已跳过导入: %s (大小=%d 字节, 文件头=%r)",
                DEFAULT_EXAMPLE_PACKAGE,
                package_size,
                header,
            )
            return
    except OSError:
        logger.warning(
            "无法读取默认使用说明迁移包，已跳过导入: %s",
            DEFAULT_EXAMPLE_PACKAGE,
            exc_info=True,
        )
        return

    base_name = DEFAULT_EXAMPLE_PACKAGE.name[:-len(PACKAGE_SUFFIX)]
    try:
        if default_example_exists(base_name):
            logger.info("默认使用说明已存在，跳过导入: %s", base_name)
            return
        result = import_file_transfer_package(DEFAULT_EXAMPLE_PACKAGE.read_bytes())
        logger.info("默认使用说明安装完成: %s", result["filename"])
    except ValueError as exc:
        logger.warning(
            "默认使用说明迁移包内容无效，已跳过导入: %s (%s)",
            DEFAULT_EXAMPLE_PACKAGE,
            exc,
        )
    except Exception:
        # A damaged optional guide must not make the whole service unavailable.
        logger.exception("默认使用说明安装失败: %s", DEFAULT_EXAMPLE_PACKAGE)


install_default_examples()


def write_processed_text(base_name: str, bolts: List[Any]) -> None:
    """Expose only the source blocks that have a completed graph checkpoint."""
    text_path = TXT_FOLDER / f"{base_name}.txt"
    temporary_path = text_path.with_suffix(".txt.tmp")
    temporary_path.write_text(
        "\n\n".join(text for _, text in bolts),
        encoding="utf-8",
    )
    temporary_path.replace(text_path)


def render_graph_atomically(manager: KgManager, base_name: str, renderer: str = "all") -> None:
    """Render beside the live result and publish the main page only when complete."""
    if renderer not in {"all", "pyvis", "sigma"}:
        raise ValueError(f"Unsupported graph renderer: {renderer}")
    temporary_root = RESULT_FOLDER / f".{base_name}.{uuid.uuid4().hex}.tmp"
    target_directory = RESULT_FOLDER / base_name
    previous_highlight_index = None
    previous_index_path = target_directory / f"{base_name}.highlights.json"
    if previous_index_path.is_file():
        try:
            previous_highlight_index = json.loads(previous_index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("旧高亮索引无法读取，将完整重建: %s", base_name)
    try:
        manager.绘制知识图谱(
            base_name,
            输出目录=temporary_root,
            高亮索引缓存=previous_highlight_index,
            绘图引擎=renderer,
        )
        generated_directory = temporary_root / base_name
        target_directory.mkdir(parents=True, exist_ok=True)
        generated_files = list(generated_directory.iterdir())
        main_page = f"{base_name}.html"
        generated_files.sort(key=lambda path: path.name == main_page)
        for generated_file in generated_files:
            generated_file.replace(target_directory / generated_file.name)
        generated_names = {path.name for path in generated_files}
        def belongs_to_selected_renderer(page_name: str) -> bool:
            if renderer == "all":
                return True
            if renderer == "sigma":
                return page_name.startswith(f"{base_name}.sigma")
            return (
                page_name == f"{base_name}.html"
                or page_name.startswith(f"{base_name}_community_")
            )

        for stale_page in target_directory.glob("*.html"):
            if (
                belongs_to_selected_renderer(stale_page.name)
                and stale_page.name not in generated_names
            ):
                stale_page.unlink()
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def redraw_graph_from_store(
    base_name: str,
    renderer: str = "all",
    community_min_size_mode: Optional[str] = None,
    community_min_size: Optional[int] = None,
    community_auto_percent: Optional[float] = None,
) -> int:
    """Render the persisted graph again without re-running document extraction."""
    with graph_edit_lock:
        manager = _load_editable_graph(base_name)
        if community_min_size_mode is not None:
            manager.configure_community_pagination(
                community_min_size_mode,
                community_min_size,
                community_auto_percent,
            )
        revision = graph_history.commit_snapshot(
            base_name,
            _graph_manager_state(manager),
            "redraw_graph",
        )
        render_graph_atomically(manager, base_name, renderer)
        manager.save_store()
        return revision


def persist_graph_checkpoint(
    manager: KgManager,
    base_name: str,
    original_filename: str,
    completed_chunks: int,
    total_chunks: int,
    processing_status: str,
) -> None:
    """Persist a complete, viewable partial result after one block succeeds."""
    manager.file = base_name
    manager.original_file_type = original_filename
    manager.三元组转有向图nx(manager.kg_triplet)
    render_graph_atomically(manager, base_name)
    manager.save_store()
    write_processed_text(base_name, manager.Bolts)
    current = get_process_status(base_name) or {}
    effective_status = "pausing" if current.get("pause_requested") else processing_status
    percentage = (
        current.get("overall_percentage")
        if current.get("stage_progress") else
        (round(completed_chunks * 100 / total_chunks) if total_chunks else 0)
    )
    set_process_status(
        base_name,
        effective_status,
        completed_chunks=completed_chunks,
        total_chunks=total_chunks,
        percentage=percentage,
        partial_available=True,
        resumable=True,
    )


def persist_graph_checkpoint_if_due(
    manager: KgManager,
    base_name: str,
    original_filename: str,
    completed_chunks: int,
    total_chunks: int,
    processing_status: str,
) -> None:
    """Throttle expensive graph rendering while preserving pause/final checkpoints."""
    is_final = completed_chunks >= total_chunks
    if (
        not is_final
        and completed_chunks % CHECKPOINT_INTERVAL
        and not should_pause_file_processing(base_name)
    ):
        return
    persist_graph_checkpoint(
        manager,
        base_name,
        original_filename,
        completed_chunks,
        total_chunks,
        processing_status,
    )


def should_pause_file_processing(base_name: str) -> bool:
    return bool((get_process_status(base_name) or {}).get("pause_requested"))


def mark_file_processing_paused(base_name: str) -> None:
    """Publish a stable paused state without discarding the latest checkpoint."""
    progress = get_process_status(base_name) or {}
    completed_chunks = int(progress.get("completed_chunks") or 0)
    result_exists = (
        RESULT_FOLDER / base_name / f"{base_name}.html"
    ).is_file()
    original_filename = progress.get("original_filename")
    source_path = get_source_text_path(base_name)
    resumable = source_path.is_file() or bool(
        original_filename and (UPLOAD_FOLDER / original_filename).is_file()
    )
    set_process_status(
        base_name,
        "paused",
        pause_requested=False,
        partial_available=bool(completed_chunks and result_exists),
        resumable=resumable,
        estimated_remaining_seconds=None,
        error_message=None,
    )


def mark_file_processing_completed(base_name: str) -> None:
    set_process_status(
        base_name,
        "completed",
        percentage=100,
        estimated_remaining_seconds=0,
        partial_available=False,
        resumable=False,
        pause_requested=False,
        error_message=None,
    )


def mark_file_processing_failed(base_name: str, error: Exception) -> None:
    """Keep completed checkpoints and expose an explicit resumable file state."""
    progress = get_process_status(base_name) or {}
    completed_chunks = int(progress.get("completed_chunks") or 0)
    if completed_chunks == 0:
        try:
            stored_state = chromadb_store.load_state(base_name)
            completed_chunks = len(stored_state.get("Bolts", [])) if stored_state else 0
        except Exception:
            logger.warning("读取失败文件的检查点数量失败: %s", base_name, exc_info=True)
    source_path = get_source_text_path(base_name)
    partial_available = completed_chunks > 0 and (
        RESULT_FOLDER / base_name / f"{base_name}.html"
    ).is_file()
    original_filename = progress.get("original_filename")
    resumable = source_path.is_file() or bool(
        original_filename and (UPLOAD_FOLDER / original_filename).is_file()
    )
    set_process_status(
        base_name,
        "interrupted" if partial_available else "error",
        completed_chunks=completed_chunks,
        total_chunks=max(int(progress.get("total_chunks") or 0), completed_chunks),
        percentage=(
            progress.get("overall_percentage")
            if progress.get("stage_progress") else
            (
                round(completed_chunks * 100 / max(int(progress.get("total_chunks") or 0), completed_chunks))
                if completed_chunks else 0
            )
        ),
        estimated_remaining_seconds=None,
        partial_available=partial_available,
        resumable=resumable,
        error_message=str(error),
    )


def process_knowledge_graph(
    base_name: str,
    text_content: str,
    original_filename: str,
    note_type: str = "general",
    splitter=None,
    custom_prompts: Optional[Dict[str, str]] = None,
    resume: bool = False,
    community_min_size_mode: Optional[str] = None,
    community_min_size: Optional[int] = None,
    community_auto_percent: Optional[float] = None,
):
    """处理文本内容生成知识图谱"""
    try:
        # 获取文件处理锁
        if base_name not in file_locks:
            file_locks[base_name] = Lock()

        with file_locks[base_name]:
            logger.info(f"开始处理文件 {base_name} 的知识图谱...")
            start_time = time.time()

            requested_status = "resuming" if resume else "processing"
            processing_status = (
                "pausing" if should_pause_file_processing(base_name) else requested_status
            )

            # 更新状态为处理中
            set_process_status(
                base_name,
                processing_status,
                completed_chunks=(get_process_status(base_name) or {}).get("completed_chunks", 0) if resume else 0,
                percentage=(get_process_status(base_name) or {}).get("percentage", 0) if resume else 0,
                latest_chunk_seconds=None,
                estimated_remaining_seconds=None,
                error_message=None,
            )

            # 新建独立的KgManager实例
            kg_manager = KgManager(
                agent=kg_agent,
                splitter=splitter or kg_splitter,
                embedding_model=embeddings,
                store=chromadb_store,
            )
            kg_manager.configure_community_pagination(
                community_min_size_mode,
                community_min_size,
                community_auto_percent,
            )

            # 设置笔记类型以及本次文件专用的处理提示词
            kg_manager.configure_processing_prompts(note_type, custom_prompts)
            logger.info("设置笔记类型为: %s", note_type)

            all_blocks = kg_manager.splitter.split_text(text_content)
            completed_offset = 0
            blocks_to_process = all_blocks
            if resume:
                if not kg_manager.load_store(base_name):
                    raise ValueError("找不到可恢复的分块检查点")
                completed_offset = len(kg_manager.Bolts)
                completed_texts = [text for _, text in kg_manager.Bolts]
                source_prefix = [text for _, text in all_blocks[:completed_offset]]
                if completed_offset > len(all_blocks) or completed_texts != source_prefix:
                    raise ValueError("恢复源文件与已完成检查点不一致，请重新上传文件")
                blocks_to_process = all_blocks[completed_offset:]
                # The current processing request is authoritative when a user
                # changes pagination settings before resuming a file.
                kg_manager.configure_community_pagination(
                    community_min_size_mode,
                    community_min_size,
                    community_auto_percent,
                )

            set_process_status(
                base_name,
                processing_status,
                completed_chunks=completed_offset,
                total_chunks=len(all_blocks),
                percentage=round(completed_offset * 100 / len(all_blocks)) if all_blocks else 0,
            )
            initialize_stage_progress(
                base_name,
                processing_status,
                len(all_blocks),
                completed_offset,
                preserve_timings=resume,
            )

            checkpoint_callback = lambda manager, completed, total: persist_graph_checkpoint_if_due(
                manager,
                base_name,
                original_filename,
                completed,
                total,
                processing_status,
            )

            # 知识图谱构建过程；每个完成块都会形成可查看、可恢复的检查点。
            r = kg_manager.知识图谱的构建(
                blocks_to_process,
                stage_progress_callback=create_stage_progress_callback(base_name, processing_status),
                checkpoint_callback=checkpoint_callback,
                append=resume,
                completed_offset=completed_offset,
                total_chunks=len(all_blocks),
                pause_callback=lambda: should_pause_file_processing(base_name),
            )
            r = kg_manager.知识融合(
                r,
                progress_callback=create_fusion_progress_callback(base_name, processing_status),
                pause_callback=lambda: should_pause_file_processing(base_name),
            )
            if should_pause_file_processing(base_name):
                raise ProcessingPaused("用户已暂停文件处理")
            logger.info(f"知识图谱构建完成，耗时: {time.time() - start_time:.2f}秒")

            # 转换为有向图
            kg_manager.三元组转有向图nx(r)

            # 绘制知识图谱
            start_time = time.time()
            render_graph_atomically(kg_manager, base_name)
            kg_manager.original_file_type = original_filename  # 使用原始文件名

            kg_manager.save_store()
            (TXT_FOLDER / f"{base_name}.txt").write_text(text_content, encoding="utf-8")
            logger.info(f"知识图谱绘制完成，耗时: {time.time() - start_time:.2f}秒")

            # 图谱首页和所有社区子页由 KgManager 直接写入同一个结果目录。
            result_file = RESULT_FOLDER / base_name / f"{base_name}.html"
            if not result_file.exists():
                raise FileNotFoundError("未生成结果HTML文件")

            # 更新处理状态为已完成
            mark_file_processing_completed(base_name)
            logger.info(f"知识图谱处理完成: {base_name}")

    except ProcessingPaused:
        mark_file_processing_paused(base_name)
        logger.info("文件 %s 已在安全检查点暂停", base_name)
        raise
    except Exception as e:
        error_msg = str(e)
        mark_file_processing_failed(base_name, e)
        logger.error(f"处理文件 {base_name} 出错: {error_msg}", exc_info=True)
        raise


def process_uploaded_file(
    original_path: str,
    filename: str,
    note_type: str = "general",
    use_img2txt: bool = False,
    custom_prompts: Optional[Dict[str, str]] = None,
    max_chunk_tokens: Optional[int] = None,
    min_chunk_tokens: Optional[int] = None,
    community_min_size_mode: Optional[str] = None,
    community_min_size: Optional[int] = None,
    community_auto_percent: Optional[float] = None,
):
    """后台处理任务（包含文件转换）"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
        max_chunk_tokens, min_chunk_tokens = normalize_chunk_token_settings(
            max_chunk_tokens,
            min_chunk_tokens,
        )
        (
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        ) = normalize_community_pagination_settings(
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        )
        txt_filename = f"{os.path.splitext(filename)[0]}.txt"
        txt_path = os.path.join(TXT_FOLDER, txt_filename)

        # 在开始处理前将状态设置为processing
        initial_status = "pausing" if should_pause_file_processing(base_name) else "processing"
        set_process_status(
            base_name,
            initial_status,
            completed_chunks=0,
            total_chunks=0,
            percentage=0,
            processing_stage=None,
            stage_progress={},
            overall_percentage=0,
            overall_speed_percent_per_minute=None,
            estimated_total_remaining_seconds=None,
            latest_chunk_seconds=None,
            estimated_remaining_seconds=None,
        )
        logger.info(f"开始处理文件: {filename}, 状态已设置为processing")

        # 文件转换处理
        conversion_success = False
        try:
            if file_ext in FILE_PROCESSORS:
                # 使用专用处理器转换
                processor = FILE_PROCESSORS[file_ext](output_dir=TXT_FOLDER, vl_client=vl_client)
                processor.process([original_path], use_img2txt)
                processor.save_as_txt(combine=False, output_path=txt_filename)
                conversion_success = True
            elif file_ext == '.txt':
                # 直接复制文本文件
                shutil.copy(original_path, txt_path)
                conversion_success = True
            else:
                raise ValueError(f"不支持的文件类型: {file_ext}")
        except Exception as e:
            logger.error(f"文件转换处理失败: {str(e)}")
            raise ValueError(f"文件转换处理失败: {str(e)}")

        # 确认文本文件是否存在
        if not conversion_success or not os.path.exists(txt_path):
            logger.error(f"文件转换失败，未生成文本文件: {txt_path}")
            raise ValueError("文件转换失败，未能生成文本内容")

        # 读取并规范化转换后的文本；上传的 TXT 可能使用 GBK/GB18030/Big5。
        text_content, detected_encoding = read_text_file(txt_path)
        Path(txt_path).write_text(text_content, encoding="utf-8")
        logger.info("文件 %s 使用 %s 编码，已规范化为 UTF-8", filename, detected_encoding)

        source_text_path = get_source_text_path(base_name)
        source_text_path.write_text(text_content, encoding="utf-8")
        get_document_draft_path(base_name).unlink(missing_ok=True)
        get_document_rich_path(base_name).unlink(missing_ok=True)
        Path(txt_path).write_text("", encoding="utf-8")
        set_process_status(
            base_name,
            "pausing" if should_pause_file_processing(base_name) else "processing",
            original_filename=filename,
            source_text_path=str(source_text_path),
            note_type=note_type,
            custom_prompts=custom_prompts or {},
            use_img2txt=use_img2txt,
            chunk_max_tokens=max_chunk_tokens,
            chunk_min_tokens=min_chunk_tokens,
            community_min_size_mode=community_min_size_mode,
            community_min_size=community_min_size,
            community_auto_percent=community_auto_percent,
            resume_mode="initial",
            resumable=True,
            partial_available=False,
        )

        logger.info(f"文件 {filename} 转换完成，开始处理知识图谱")

        process_knowledge_graph(
            base_name,
            text_content,
            filename,
            note_type,
            get_splitter_for_extension(file_ext, max_chunk_tokens, min_chunk_tokens),
            custom_prompts,
            community_min_size_mode=community_min_size_mode,
            community_min_size=community_min_size,
            community_auto_percent=community_auto_percent,
        )

        # 处理完成后更新状态
        mark_file_processing_completed(base_name)
        logger.info(f"文件 {filename} 处理完成，状态已设置为completed")

    except ProcessingPaused:
        mark_file_processing_paused(base_name)
        logger.info("文件 %s 已暂停", base_name)
    except Exception as e:
        error_msg = f"文件处理失败: {str(e)}"
        if 'base_name' in locals():  # 确保base_name已定义
            mark_file_processing_failed(base_name, e)
        logger.error(error_msg, exc_info=True)


def process_update_file(
    original_path: str,
    filename: str,
    txt_path: str,
    use_img2txt: bool = False,
    note_type: str = "general",
    custom_prompts: Optional[Dict[str, str]] = None,
    max_chunk_tokens: Optional[int] = None,
    min_chunk_tokens: Optional[int] = None,
    community_min_size_mode: Optional[str] = None,
    community_min_size: Optional[int] = None,
    community_auto_percent: Optional[float] = None,
    edited_text: Optional[str] = None,
):
    """处理文件增量更新"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
        max_chunk_tokens, min_chunk_tokens = normalize_chunk_token_settings(
            max_chunk_tokens,
            min_chunk_tokens,
        )
        (
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        ) = normalize_community_pagination_settings(
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        )
        new_txt_filename = f"{base_name}_new.txt"
        new_txt_path = os.path.join(TXT_FOLDER, new_txt_filename)

        # 在开始处理前将状态设置为updating
        current_progress = get_process_status(base_name) or {}
        set_process_status(
            base_name,
            "pausing" if current_progress.get("pause_requested") else "updating",
            completed_chunks=int(current_progress.get("completed_chunks") or 0),
            total_chunks=int(current_progress.get("total_chunks") or 0),
            percentage=0,
            processing_stage=None,
            stage_progress={},
            overall_percentage=0,
            overall_speed_percent_per_minute=None,
            estimated_total_remaining_seconds=None,
            latest_chunk_seconds=None,
            estimated_remaining_seconds=None,
        )
        logger.info(f"开始处理文件更新: {filename}, 状态已设置为updating")

        # 新建独立的KgManager实例
        kg_manager = KgManager(
            agent=kg_agent,
            splitter=get_splitter_for_extension(file_ext, max_chunk_tokens, min_chunk_tokens),
            embedding_model=embeddings,
            store=chromadb_store,
        )
        kg_manager.configure_community_pagination(
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        )
        kg_manager.configure_processing_prompts(note_type, custom_prompts)

        # 设置原始文件名
        kg_manager.original_file_type = filename  # 使用完整文件名

        # 文件转换处理
        conversion_success = False
        try:
            if edited_text is not None:
                Path(new_txt_path).write_text(edited_text, encoding="utf-8")
                conversion_success = True
            elif file_ext in FILE_PROCESSORS:
                # 使用专用处理器转换
                processor = FILE_PROCESSORS[file_ext](output_dir=TXT_FOLDER, vl_client=vl_client)
                processor.process([original_path], use_img2txt)
                processor.save_as_txt(combine=False, output_path=new_txt_filename)
                conversion_success = True
            elif file_ext == '.txt':
                # 直接复制文本文件
                shutil.copy(original_path, new_txt_path)
                conversion_success = True
            else:
                raise ValueError(f"不支持的文件类型: {file_ext}")
        except Exception as e:
            logger.error(f"文件转换处理失败: {str(e)}")
            raise ValueError(f"文件转换处理失败: {str(e)}")

        # 确认临时文件是否存在
        if not conversion_success or not os.path.exists(new_txt_path):
            logger.error(f"文件转换失败，未生成临时文件: {new_txt_path}")
            raise ValueError("文件转换失败，未能生成文本内容")

        # 读取并规范化新文本，确保增量比较不受源文件编码影响。
        new_text_content, detected_encoding = read_text_file(new_txt_path)
        Path(new_txt_path).write_text(new_text_content, encoding="utf-8")
        logger.info("更新文件 %s 使用 %s 编码，已规范化为 UTF-8", filename, detected_encoding)

        source_text_path = get_source_text_path(base_name)
        source_text_path.write_text(new_text_content, encoding="utf-8")
        set_process_status(
            base_name,
            "pausing" if should_pause_file_processing(base_name) else "updating",
            original_filename=filename,
            source_text_path=str(source_text_path),
            note_type=note_type,
            custom_prompts=custom_prompts or {},
            use_img2txt=use_img2txt,
            chunk_max_tokens=max_chunk_tokens,
            chunk_min_tokens=min_chunk_tokens,
            community_min_size_mode=community_min_size_mode,
            community_min_size=community_min_size,
            community_auto_percent=community_auto_percent,
            resume_mode="update",
            resumable=True,
        )

        # 读取原始文本内容
        original_text_content, _ = read_text_file(txt_path)

        logger.info(f"文件 {filename} 转换完成，开始比较内容差异")

        # 检查文件内容是否完全相同
        if new_text_content == original_text_content:
            logger.info(f"文件内容完全相同，无需更新: {base_name}")

            # 删除临时文件
            os.remove(new_txt_path)

            # 文档草稿更新还要经过一次独立重绘，避免前端在重绘前看到
            # 短暂的 completed 状态而停止轮询。
            if edited_text is not None:
                set_process_status(base_name, "redrawing", percentage=100, error_message=None)
            else:
                if kg_manager.load_store(base_name):
                    before_history = state_snapshot(_graph_manager_state(kg_manager))
                    with graph_edit_lock:
                        revision = graph_history.commit(
                            base_name,
                            before_history,
                            _graph_manager_state(kg_manager),
                            "incremental_update",
                        )
                    logger.info("无内容变化，已记录增量更新历史 revision=%s: %s", revision, base_name)
                mark_file_processing_completed(base_name)
            return

        # 增量更新前，先加载原有知识图谱
        if not kg_manager.load_store(base_name):
            raise ValueError(f"无法加载原有知识图谱: {base_name}")
        kg_manager.configure_community_pagination(
            community_min_size_mode,
            community_min_size,
            community_auto_percent,
        )
        before_history = state_snapshot(_graph_manager_state(kg_manager))

        # 执行增量更新
        logger.info(f"开始执行增量更新: {base_name}")
        start_time = time.time()

        # 执行增量更新
        initialize_stage_progress(
            base_name,
            "updating",
            None,
            preserve_timings=False,
        )
        new_kg_triplet = kg_manager.增量更新(
            new_text_content,
            stage_progress_callback=create_stage_progress_callback(base_name, status="updating"),
            checkpoint_callback=lambda manager, completed, total: persist_graph_checkpoint_if_due(
                manager,
                base_name,
                filename,
                completed,
                total,
                "updating",
            ),
            pause_callback=lambda: should_pause_file_processing(base_name),
        )
        if should_pause_file_processing(base_name):
            raise ProcessingPaused("用户已暂停文件处理")
        new_kg_triplet = kg_manager.知识融合(
            new_kg_triplet,
            progress_callback=create_fusion_progress_callback(base_name, status="updating"),
            pause_callback=lambda: should_pause_file_processing(base_name),
        )
        if should_pause_file_processing(base_name):
            raise ProcessingPaused("用户已暂停文件处理")

        # 检查更新结果是否为空
        if not new_kg_triplet or len(new_kg_triplet) == 0:
            logger.info(f"无新增内容，知识图谱保持不变: {base_name}")

            # 更新完成后，用新文件替换旧文件
            shutil.copy(new_txt_path, txt_path)
            os.remove(new_txt_path)  # 删除临时文件
            if edited_text is None:
                get_document_rich_path(base_name).unlink(missing_ok=True)
                get_document_draft_path(base_name).unlink(missing_ok=True)

            if edited_text is not None:
                set_process_status(base_name, "redrawing", percentage=100, error_message=None)
            else:
                mark_file_processing_completed(base_name)
            return

        # 转换为有向图
        kg_manager.三元组转有向图nx(new_kg_triplet)

        # 绘制更新后的知识图谱
        render_graph_atomically(kg_manager, base_name)

        # 更新完成后，用新文件替换旧文件
        shutil.copy(new_txt_path, txt_path)
        os.remove(new_txt_path)  # 删除临时文件
        if edited_text is None:
            get_document_rich_path(base_name).unlink(missing_ok=True)
            get_document_draft_path(base_name).unlink(missing_ok=True)

        # 安全检查：确保Bolts不为空再保存
        if hasattr(kg_manager, 'Bolts') and kg_manager.Bolts:
            # 保存更新后的知识图谱
            try:
                kg_manager.save_store()
                logger.info(f"知识图谱增量更新完成，耗时: {time.time() - start_time:.2f}秒")
            except ValueError as ve:
                if "输入必须是非空字符串列表" in str(ve):
                    logger.warning(f"知识图谱增量更新过程中没有生成新的节点，跳过保存步骤")
                else:
                    raise
        else:
            logger.warning(f"知识图谱增量更新没有生成有效的节点，跳过保存步骤")

        # 图谱首页和所有社区子页由 KgManager 直接写入同一个结果目录。
        result_file = RESULT_FOLDER / base_name / f"{base_name}.html"
        if not result_file.exists():
            raise FileNotFoundError("未生成结果HTML文件")

        if edited_text is not None:
            set_process_status(base_name, "redrawing", percentage=100, error_message=None)
        else:
            with graph_edit_lock:
                revision = graph_history.commit(
                    base_name,
                    before_history,
                    _graph_manager_state(kg_manager),
                    "incremental_update",
                )
            logger.info("已记录增量更新联合历史 revision=%s: %s", revision, base_name)
            mark_file_processing_completed(base_name)
        logger.info(f"知识图谱增量更新完成: {base_name}")

    except ProcessingPaused:
        mark_file_processing_paused(base_name)
        logger.info("文件 %s 已暂停增量更新", base_name)
    except Exception as e:
        error_msg = f"文件增量更新失败: {str(e)}"
        if 'base_name' in locals():  # 确保base_name已定义
            mark_file_processing_failed(base_name, e)
        logger.error(error_msg, exc_info=True)

        # 清理临时文件
        if 'new_txt_path' in locals() and os.path.exists(new_txt_path):
            try:
                os.remove(new_txt_path)
            except OSError:
                logger.warning("清理临时文件失败: %s", new_txt_path, exc_info=True)


def process_edited_document_update(base_name: str, filename: str) -> None:
    """Apply a saved document draft through the normal incremental pipeline."""
    try:
        draft_path = get_document_draft_path(base_name)
        if not draft_path.is_file():
            raise FileNotFoundError("没有待应用的文档草稿")
        content = draft_path.read_text(encoding="utf-8")
        progress = get_process_status(base_name) or {}
        process_update_file(
            str(UPLOAD_FOLDER / filename),
            filename,
            str(TXT_FOLDER / f"{base_name}.txt"),
            bool(progress.get("use_img2txt")),
            progress.get("note_type", "general"),
            progress.get("custom_prompts") or {},
            progress.get("chunk_max_tokens"),
            progress.get("chunk_min_tokens"),
            progress.get("community_min_size_mode"),
            progress.get("community_min_size"),
            progress.get("community_auto_percent"),
            edited_text=content,
        )
        if (get_process_status(base_name) or {}).get("status") in {"completed", "redrawing"}:
            draft_path.unlink(missing_ok=True)
            # Publish a fresh render from the persisted post-update state so
            # both the legacy HTML and the editable graph reflect the update.
            set_process_status(base_name, "redrawing", percentage=100, error_message=None)
            redraw_graph_from_store(base_name)
            mark_file_processing_completed(base_name)
    except Exception as exc:
        mark_file_processing_failed(base_name, exc)
        logger.error("应用文档草稿失败: %s", base_name, exc_info=True)


def process_resume_file(base_name: str) -> None:
    """Continue an interrupted file from its last completed block."""
    progress = get_process_status(base_name) or {}
    source_path = Path(progress.get("source_text_path") or get_source_text_path(base_name))
    original_filename = progress.get("original_filename") or f"{base_name}.txt"
    try:
        if progress.get("resume_mode") == "update":
            original_path = UPLOAD_FOLDER / original_filename
            txt_path = TXT_FOLDER / f"{base_name}.txt"
            if not original_path.is_file() or not txt_path.is_file():
                raise FileNotFoundError("恢复增量更新所需的原文件或检查点文本不存在")
            process_update_file(
                str(original_path),
                original_filename,
                str(txt_path),
                bool(progress.get("use_img2txt")),
                progress.get("note_type", "general"),
                progress.get("custom_prompts") or {},
                progress.get("chunk_max_tokens"),
                progress.get("chunk_min_tokens"),
                progress.get("community_min_size_mode"),
                progress.get("community_min_size"),
                progress.get("community_auto_percent"),
            )
            return

        if not source_path.is_file():
            original_path = UPLOAD_FOLDER / original_filename
            if not original_path.is_file():
                raise FileNotFoundError("恢复所需的原文件和转换文本均不存在")
            process_uploaded_file(
                str(original_path),
                original_filename,
                progress.get("note_type", "general"),
                bool(progress.get("use_img2txt")),
                progress.get("custom_prompts") or {},
                progress.get("chunk_max_tokens"),
                progress.get("chunk_min_tokens"),
                progress.get("community_min_size_mode"),
                progress.get("community_min_size"),
                progress.get("community_auto_percent"),
            )
            return
        text_content, _ = read_text_file(source_path)
        file_ext = Path(original_filename).suffix.lower()
        stored_state = chromadb_store.load_state(base_name)
        checkpoint_count = len(stored_state.get("Bolts", [])) if stored_state else 0
        has_checkpoint = checkpoint_count > 0
        if checkpoint_count != int(progress.get("completed_chunks") or 0):
            set_process_status(
                base_name,
                "resuming",
                completed_chunks=checkpoint_count,
                partial_available=has_checkpoint,
            )
        process_knowledge_graph(
            base_name,
            text_content,
            original_filename,
            progress.get("note_type", "general"),
            get_splitter_for_extension(
                file_ext,
                progress.get("chunk_max_tokens"),
                progress.get("chunk_min_tokens"),
            ),
            progress.get("custom_prompts") or {},
            resume=has_checkpoint,
            community_min_size_mode=progress.get("community_min_size_mode"),
            community_min_size=progress.get("community_min_size"),
            community_auto_percent=progress.get("community_auto_percent"),
        )
    except ProcessingPaused:
        mark_file_processing_paused(base_name)
        logger.info("文件 %s 已暂停继续处理", base_name)
    except Exception as exc:
        mark_file_processing_failed(base_name, exc)
        logger.error("继续处理文件 %s 失败", base_name, exc_info=True)


@app.post("/pause-processing/{filename}")
async def pause_processing(filename: str):
    """Request a cooperative pause after the current block checkpoint."""
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    active_statuses = {"uploading", "processing", "updating", "resuming"}
    with process_status_lock:
        current = PROCESS_STATUS.get(base_name)
        if not current:
            raise HTTPException(status_code=404, detail="没有找到该文件的处理记录")
        if current.get("status") == "pausing":
            return JSONResponse({
                "status": "pausing",
                "message": "文件正在等待当前文本块完成后暂停",
                "filename": filename,
            })
        if current.get("status") not in active_statuses:
            raise HTTPException(status_code=409, detail="该文件当前不在处理中")
        next_status = {
            **current,
            "status": "pausing",
            "pause_requested": True,
            "updated_at": time.time(),
        }
        PROCESS_STATUS[base_name] = next_status
        persist_process_status(base_name, next_status)

    return JSONResponse({
        "status": "pausing",
        "message": "将在当前文本块完成并保存后暂停",
        "filename": filename,
    })


@app.post("/resume-processing/{filename}")
async def resume_processing(
    filename: str,
    background_tasks: BackgroundTasks,
):
    """Resume only the unprocessed blocks of an interrupted file."""
    await validate_current_ai_settings()
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    progress = get_process_status(base_name)
    if not progress:
        raise HTTPException(status_code=404, detail="没有找到该文件的处理记录")
    if progress.get("status") in {"uploading", "processing", "updating", "resuming", "pausing"}:
        raise HTTPException(status_code=409, detail="文件当前仍在处理中")
    if progress.get("status") not in {"paused", "interrupted", "error"}:
        raise HTTPException(status_code=409, detail="该文件当前不需要继续处理")
    source_path = Path(progress.get("source_text_path") or get_source_text_path(base_name))
    original_filename = progress.get("original_filename") or filename
    if not source_path.is_file() and not (UPLOAD_FOLDER / original_filename).is_file():
        raise HTTPException(status_code=409, detail="缺少恢复源文本，请重新上传原文件")

    completed = int(progress.get("completed_chunks") or 0)
    total = int(progress.get("total_chunks") or 0)
    set_process_status(
        base_name,
        "resuming",
        completed_chunks=completed,
        total_chunks=total,
        percentage=round(completed * 100 / total) if total else 0,
        error_message=None,
        resumable=True,
        pause_requested=False,
    )
    background_tasks.add_task(process_resume_file, base_name)
    return JSONResponse({
        "status": "resuming",
        "message": "已从上次完成的文本块继续处理",
        "filename": filename,
        "completed_chunks": completed,
        "total_chunks": total,
    })


@app.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    note_type: str = Form("general", alias="noteType"),
    use_img2txt: str = Form("true"),
    entity_prompt: Optional[str] = Form(None, alias="entityPrompt"),
    relationship_prompt: Optional[str] = Form(None, alias="relationshipPrompt"),
    fusion_prompt: Optional[str] = Form(None, alias="fusionPrompt"),
    max_chunk_tokens: int = Form(chunk_max_tokens, alias="chunkMaxTokens"),
    min_chunk_tokens: int = Form(chunk_min_tokens, alias="chunkMinTokens"),
    community_min_size_mode: str = Form(
        DEFAULT_COMMUNITY_MIN_SIZE_MODE,
        alias="communityMinSizeMode",
    ),
    community_min_size: int = Form(
        DEFAULT_COMMUNITY_MIN_SIZE,
        alias="communityMinSize",
    ),
    community_auto_percent: float = Form(
        DEFAULT_COMMUNITY_AUTO_PERCENT,
        alias="communityAutoPercent",
    ),
):
    """
    支持多种格式的文件上传接口，支持增量更新。
    
    用途：
        上传pdf、md、txt等文件，自动转换为文本并生成知识图谱。
        若文件已存在则自动进行增量更新。
    
    参数：
        file (UploadFile): 上传的文件。
        note_type (str): 笔记类型，默认为general。
        use_img2txt (str): 是否启用图片转文本，"true"/"false"。
        background_tasks (BackgroundTasks): FastAPI后台任务对象。
    
    返回：
        JSONResponse: 包含处理状态、文件名等信息。
    
    异常：
        上传或处理失败时返回500。
    """
    filename = get_safe_filename(file.filename or "")
    if is_transfer_package_filename(filename):
        package_content = bytearray()
        while chunk := await file.read(1024 * 1024):
            package_content.extend(chunk)
            if len(package_content) > MAX_TRANSFER_PACKAGE_SIZE:
                raise HTTPException(status_code=413, detail="图谱迁移包不能超过 100 MB")
        try:
            payload = bytes(package_content)
            package = await asyncio.to_thread(read_transfer_package, payload)
            base_name = get_base_name(f"{package.base_name}.txt")
            original_filename = get_safe_filename(package.original_filename)
            current = get_process_status(base_name) or {}
            if current.get("status") == "importing":
                raise FileExistsError(f"文件 {original_filename} 正在导入")
            if (
                chromadb_store.load_state(base_name) is not None
                or (RESULT_FOLDER / base_name).exists()
                or (UPLOAD_FOLDER / original_filename).exists()
            ):
                raise FileExistsError(f"文件 {original_filename} 已存在，请先删除后再导入")

            package_path = get_transfer_import_path(base_name)
            temporary_path = package_path.with_suffix(f"{package_path.suffix}.tmp")
            await asyncio.to_thread(temporary_path.write_bytes, payload)
            await asyncio.to_thread(temporary_path.replace, package_path)
            set_process_status(
                base_name,
                "importing",
                original_filename=original_filename,
                completed_chunks=0,
                total_chunks=0,
                percentage=95,
                partial_available=False,
                resumable=False,
                pause_requested=False,
                error_message=None,
            )
            background_tasks.add_task(process_transfer_package_import, base_name, package_path)
            return JSONResponse({
                "status": "importing",
                "message": "迁移包已完整上传，正在后台导入",
                "filename": original_filename,
                "percentage": 95,
            })
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("导入图谱迁移包失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"导入图谱迁移包失败: {exc}") from exc

    # Normal source files need a working primary or fallback AI. Transfer
    # packages take the branch above and never invoke model validation.
    await validate_current_ai_settings()
    try:
        use_img2txt_bool = use_img2txt.strip().lower() in {"true", "1", "yes", "open"}
        custom_prompts = normalize_processing_prompts(
            note_type,
            entity_prompt,
            relationship_prompt,
            fusion_prompt,
        )
        try:
            max_chunk_tokens, min_chunk_tokens = normalize_chunk_token_settings(
                max_chunk_tokens,
                min_chunk_tokens,
            )
            (
                community_min_size_mode,
                community_min_size,
                community_auto_percent,
            ) = normalize_community_pagination_settings(
                community_min_size_mode,
                community_min_size,
                community_auto_percent,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        logger.info(f"收到图片文本识别参数: {use_img2txt} -> {use_img2txt_bool}")

        # 保存原始文件
        base_name = get_base_name(filename)
        file_ext = Path(filename).suffix.lower()
        if file_ext not in FILE_PROCESSORS and file_ext != ".txt":
            raise HTTPException(status_code=415, detail=f"不支持的文件类型: {file_ext or '无扩展名'}")

        original_path = UPLOAD_FOLDER / filename
        txt_filename = f"{base_name}.txt"
        txt_path = TXT_FOLDER / txt_filename

        # 检查数据库中是否已有该文件
        file_exists = False
        existing_txt = False

        # 创建一个专用的storeManager实例来检查文件是否存在
        file_manager = storeManager(store=chromadb_store, agent=kg_agent)
        db_files = file_manager.list_files()
        db_file_ids = db_files.get('ids', [])

        # 检查文件是否存在于数据库中
        if base_name in [os.path.splitext(file_id)[0] for file_id in db_file_ids]:
            file_exists = True
            # 检查文本文件是否存在
            if os.path.exists(txt_path):
                existing_txt = True

        previous_progress = get_process_status(base_name)
        failed_retry = previous_progress is not None and previous_progress.get("status") == "error"
        result_file = RESULT_FOLDER / base_name / f"{base_name}.html"

        if failed_retry:
            logger.info("文件 %s 上次处理未完成，将保留检查点并执行增量处理", filename)

        can_incrementally_update = file_exists and existing_txt and result_file.is_file()

        # 保存上传的文件
        with original_path.open("wb") as output_file:
            while chunk := await file.read(1024 * 1024):
                output_file.write(chunk)

        logger.info(f"文件 {filename} 上传成功，存储为 {original_path}")
        logger.info(f"使用图片文本识别参数: {use_img2txt} -> {use_img2txt_bool}")

        # 设置状态和后台处理任务
        if can_incrementally_update:
            # 文件在数据库中已存在，执行增量更新
            existing_state = chromadb_store.load_state(base_name) or {}
            existing_chunk_count = len(existing_state.get("Bolts", []))
            set_process_status(
                base_name,
                "updating",
                completed_chunks=existing_chunk_count,
                total_chunks=max(
                    int((previous_progress or {}).get("total_chunks") or 0),
                    existing_chunk_count,
                ),
                percentage=int((previous_progress or {}).get("percentage") or 0),
                latest_chunk_seconds=None,
                estimated_remaining_seconds=None,
                original_filename=filename,
                note_type=note_type,
                custom_prompts=custom_prompts or {},
                use_img2txt=use_img2txt_bool,
                chunk_max_tokens=max_chunk_tokens,
                chunk_min_tokens=min_chunk_tokens,
                community_min_size_mode=community_min_size_mode,
                community_min_size=community_min_size,
                community_auto_percent=community_auto_percent,
                resume_mode="update",
                source_text_path=str(get_source_text_path(base_name)),
                partial_available=bool(existing_chunk_count and result_file.is_file()),
                resumable=True,
                pause_requested=False,
            )
            logger.info(f"文件 {filename} 已存在，将进行增量更新")
            background_tasks.add_task(
                process_update_file,
                original_path,
                filename,
                txt_path,
                use_img2txt_bool,
                note_type,
                custom_prompts,
                max_chunk_tokens,
                min_chunk_tokens,
                community_min_size_mode,
                community_min_size,
                community_auto_percent,
            )

            return JSONResponse({
                "status": "updating",
                "message": "文件已上传，正在进行增量更新",
                "filename": filename,
                "is_update": True
            })
        else:
            # 新文件上传，执行常规处理
            set_process_status(
                base_name,
                "uploading",
                completed_chunks=0,
                total_chunks=0,
                percentage=0,
                latest_chunk_seconds=None,
                estimated_remaining_seconds=None,
                original_filename=filename,
                note_type=note_type,
                custom_prompts=custom_prompts or {},
                use_img2txt=use_img2txt_bool,
                chunk_max_tokens=max_chunk_tokens,
                chunk_min_tokens=min_chunk_tokens,
                community_min_size_mode=community_min_size_mode,
                community_min_size=community_min_size,
                community_auto_percent=community_auto_percent,
                resume_mode="initial",
                resumable=False,
                partial_available=False,
                pause_requested=False,
            )
            background_tasks.add_task(
                process_uploaded_file,
                original_path,
                filename,
                note_type,
                use_img2txt_bool,
                custom_prompts,
                max_chunk_tokens,
                min_chunk_tokens,
                community_min_size_mode,
                community_min_size,
                community_auto_percent,
            )

            return JSONResponse({
                "status": "uploading",
                "message": "文件已上传，正在转换处理中",
                "filename": filename,
                "noteType": note_type,
                "is_update": False
            })

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"文件上传失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": error_msg}
        )


@app.get("/processing-status/{filename}")
async def get_processing_status(filename: str):
    """
    获取文件处理状态。
    
    用途：
        查询指定文件的处理进度和结果文件是否存在。
    
    参数：
        filename (str): 文件名。
    
    返回：
        JSONResponse: {"status": str, "display_status": str, "result_exists": bool, "filename": str}
    
    异常：
        文件不存在时返回404。
    """
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    progress = get_process_status(base_name)

    # 状态映射，用于前端展示
    status_map = {
        "uploading": "上传中",
        "importing": "迁移包导入中",
        "processing": "处理中",
        "updating": "增量更新中",
        "resuming": "继续处理中",
        "pausing": "暂停中",
        "redrawing": "重新绘制图谱中",
        "paused": "已暂停",
        "completed": "已完成",
        "interrupted": "部分完成，可继续",
        "error": "处理失败，可重试"
    }

    if progress:
        status = progress["status"]
        result_exists = (RESULT_FOLDER / base_name / f'{base_name}.html').exists()
        display_status = status_map.get(status, status)
        character_count, last_edited_at = get_file_library_metadata(base_name)
        document_history = _read_document_history(base_name)

        return JSONResponse({
            "status": status,
            "display_status": display_status,
            "result_exists": result_exists,
            "filename": filename,
            "completed_chunks": progress.get("completed_chunks", 0),
            "total_chunks": progress.get("total_chunks", 0),
            "percentage": progress.get("percentage", 0),
            "latest_chunk_seconds": progress.get("latest_chunk_seconds"),
            "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
            "processing_stage": progress.get("processing_stage"),
            "stage_progress": progress.get("stage_progress") or {},
            "overall_percentage": progress.get("overall_percentage", progress.get("percentage", 0)),
            "overall_speed_percent_per_minute": progress.get("overall_speed_percent_per_minute"),
            "estimated_total_remaining_seconds": progress.get(
                "estimated_total_remaining_seconds",
                progress.get("estimated_remaining_seconds"),
            ),
            "partial_available": bool(progress.get("partial_available")),
            "resumable": bool(progress.get("resumable")),
            "error_message": progress.get("error_message"),
            "document_modified": get_document_draft_path(base_name).is_file(),
            "document_revision": int(document_history.get("next_revision") or 1) - 1,
            "character_count": character_count,
            "last_edited_at": last_edited_at,
        })
    else:
        return JSONResponse(
            status_code=404,
            content={"error": "文件不存在或未开始处理"}
        )


@app.get("/file-content/{filename}")
async def get_file_content(filename: str):
    """
    获取转换后的文本内容。
    
    用途：
        获取指定文件转换后的纯文本内容。
    
    参数：
        filename (str): 文件名。
    
    返回：
        JSONResponse: {"content": str}
    
    异常：
        文件不存在或读取失败时返回404/500。
    """
    filename = get_safe_filename(filename)
    txt_filename = f"{get_base_name(filename)}.txt"
    txt_path = os.path.join(TXT_FOLDER, txt_filename)

    draft_path = get_document_draft_path(get_base_name(filename))
    content_path = draft_path if draft_path.is_file() else Path(txt_path)
    if content_path.exists():
        try:
            content, _ = read_text_file(content_path)
            rich_path = get_document_rich_path(get_base_name(filename))
            rich_content = rich_path.read_text(encoding="utf-8") if rich_path.is_file() else ""
            return JSONResponse({
                "content": content,
                "rich_content": rich_content,
                "draft": draft_path.is_file(),
                "document_revision": _read_document_history(get_base_name(filename)).get("next_revision", 1) - 1,
            })
        except Exception as e:
            error_msg = str(e)
            logger.error(f"读取文件内容失败: {error_msg}")
            return JSONResponse(
                status_code=500,
                content={"error": f"读取文件内容失败: {error_msg}"}
            )
    else:
        return JSONResponse(
            status_code=404,
            content={"error": "文件不存在或尚未完成转换"}
        )


@app.post("/file-content/{filename}")
async def save_file_content(filename: str, request: DocumentContentUpdate):
    """Save a recoverable rich-text draft without changing the graph yet."""
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    _ensure_graph_editable(base_name)
    if chromadb_store.load_state(base_name) is None:
        raise HTTPException(status_code=404, detail="图谱状态不存在，无法编辑文档")
    content = request.content.replace("\x00", "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="文档内容不能为空")
    rich_content = request.rich_content or ""
    with graph_edit_lock:
        manager = _load_editable_graph(base_name)
        before_graph = state_snapshot(_graph_manager_state(manager))
        before_revision = _append_document_version(
            base_name,
            _document_snapshot(base_name),
            "before:document_edit",
        )
        get_document_draft_path(base_name).write_text(content, encoding="utf-8")
        get_document_rich_path(base_name).write_text(rich_content, encoding="utf-8")
        revision = _append_document_version(
            base_name,
            {"content": content, "rich_content": rich_content, "draft": True},
            "document_edit",
        )
        graph_revision = graph_history.commit(
            base_name,
            before_graph,
            _graph_manager_state(manager),
            "document_edit",
        )
    return {
        "status": "draft",
        "filename": filename,
        "revision": revision,
        "before_revision": before_revision,
        "graph_revision": graph_revision,
        "message": "文档草稿已保存，请从文件列表执行增量更新以应用到图谱",
    }


@app.get("/document-history/{filename}")
async def get_document_history(filename: str):
    base_name = get_base_name(get_safe_filename(filename))
    data = _read_document_history(base_name)
    return {
        "versions": [
            {
                "revision": item.get("revision"),
                "operation": item.get("operation"),
                "created_at": item.get("created_at"),
                "description": _document_operation_label(item.get("operation", "")),
            }
            for item in data.get("versions", [])
        ]
    }


@app.post("/document-restore/{filename}/{revision}")
async def restore_document_content(filename: str, revision: int):
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    _ensure_graph_editable(base_name)
    data = _read_document_history(base_name)
    selected = next((item for item in data.get("versions", []) if int(item.get("revision", -1)) == revision), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="文档历史版本不存在")
    with graph_edit_lock:
        manager = _load_editable_graph(base_name)
        before_graph = state_snapshot(_graph_manager_state(manager))
        _append_document_version(base_name, _document_snapshot(base_name), f"before:document_restore:{revision}")
        get_document_draft_path(base_name).write_text(str(selected.get("content") or ""), encoding="utf-8")
        get_document_rich_path(base_name).write_text(str(selected.get("rich_content") or ""), encoding="utf-8")
        new_revision = _append_document_version(
            base_name,
            _document_snapshot(base_name),
            f"document_restore:{revision}",
        )
        graph_revision = graph_history.commit(
            base_name,
            before_graph,
            _graph_manager_state(manager),
            f"document_restore:{revision}",
        )
    return {
        "status": "draft",
        "filename": filename,
        "revision": new_revision,
        "graph_revision": graph_revision,
        "message": "文档已还原为草稿，请从文件列表执行增量更新以同步图谱",
    }


@app.post("/update-document/{filename}")
async def update_document_from_draft(filename: str, background_tasks: BackgroundTasks):
    """Apply the selected file's saved editor draft incrementally."""
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    progress = get_process_status(base_name) or {}
    if progress.get("status", "completed") != "completed":
        raise HTTPException(status_code=409, detail="文件当前正在处理，暂不能更新文档")
    if not get_document_draft_path(base_name).is_file():
        raise HTTPException(status_code=404, detail="没有待应用的文档修改")
    set_process_status(
        base_name,
        "updating",
        percentage=0,
        completed_chunks=0,
        total_chunks=0,
        error_message=None,
        original_filename=filename,
        resume_mode="update",
        resumable=True,
    )
    background_tasks.add_task(process_edited_document_update, base_name, filename)
    return {"status": "updating", "filename": filename, "message": "已开始增量更新文档"}


@app.get("/export-package/{filename}")
async def export_package(filename: str):
    """Download original content, graph pages, and restorable processing data."""
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    try:
        package, download_name = await asyncio.to_thread(
            export_file_transfer_package,
            base_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("导出图谱迁移包失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出图谱迁移包失败: {exc}") from exc

    return StreamingResponse(
        iter([package]),
        media_type="application/zip",
        headers={
            "Content-Length": str(len(package)),
            "Content-Disposition": (
                f"attachment; filename*=utf-8''{quote(download_name, safe='')}"
            ),
        },
    )


@app.get("/result-page/{graph_name}/{page_name}")
async def get_result_page(graph_name: str, page_name: str):
    """Serve the main graph page or one of its generated community pages."""
    graph_name = get_safe_filename(graph_name)
    page_name = get_safe_filename(page_name)
    main_page_name = f"{graph_name}.html"
    child_page_prefix = f"{graph_name}_community_"
    is_community_page = (
        page_name.startswith(child_page_prefix)
        and page_name.endswith(".html")
    )
    is_sigma_page = page_name == f"{graph_name}.sigma.html"
    is_sigma_community_page = (
        page_name == f"{graph_name}.sigma-communities.html"
        or (
            page_name.startswith(f"{graph_name}.sigma-community-")
            and page_name.endswith(".html")
        )
    )
    is_sigma_requested = is_sigma_page or is_sigma_community_page
    if (
        page_name != main_page_name
        and not is_community_page
        and not is_sigma_page
        and not is_sigma_community_page
    ):
        raise HTTPException(status_code=404, detail="图谱页面不存在")

    result_path = RESULT_FOLDER / graph_name / page_name
    sigma_page_is_current = False
    if is_sigma_requested and result_path.is_file():
        try:
            with result_path.open("rb") as sigma_page:
                sigma_page.seek(max(0, result_path.stat().st_size - 16_384))
                sigma_page_is_current = (
                    f"const SIGMA_STATIC_PAGE_VERSION = {SIGMA_STATIC_PAGE_VERSION};".encode()
                    in sigma_page.read()
                )
        except OSError:
            sigma_page_is_current = False
    if is_sigma_requested and not sigma_page_is_current:
        # Existing graphs created before Sigma persistence are migrated once on
        # first use. Subsequent views only serve the saved HTML file.
        try:
            manager = await asyncio.to_thread(_load_editable_graph, graph_name)
            payload = graph_payload(
                _graph_manager_state(manager),
                _current_graph_revision(graph_name),
            )
            sigma_graph = nx.MultiDiGraph()
            for node in payload["nodes"]:
                sigma_graph.add_node(
                    node["id"],
                    label=node.get("name") or node["id"],
                    entity_type=node.get("entityType") or "未分类",
                    source_blocks=node.get("source_blocks") or [],
                )
            for edge in payload["links"]:
                if edge["source"] not in sigma_graph or edge["target"] not in sigma_graph:
                    continue
                sigma_graph.add_edge(
                    edge["source"],
                    edge["target"],
                    edit_id=edge.get("id"),
                    label=edge.get("relation") or "",
                    title=edge.get("context") or edge.get("evidence") or "",
                    weight=edge.get("weight") or 1,
                    source_block=edge.get("source_block") or "",
                    evidence_blocks=edge.get("evidence_blocks") or [],
                    evidence_source=edge.get("source") or "",
                    evidence_target=edge.get("target") or "",
                    origin=edge.get("origin") or "extracted",
                )
            community_min_size = manager.resolve_community_min_size(
                sigma_graph.number_of_nodes(),
                sigma_graph.number_of_edges(),
            )
            sigma_partition = None
            if page_name.startswith(f"{graph_name}.sigma-community-"):
                overview_path = result_path.parent / f"{graph_name}.sigma-communities.html"
                if overview_path.is_file():
                    overview_html = overview_path.read_text(encoding="utf-8")
                    payload_match = re.search(
                        r'<script id="sigma-data" type="application/json">(.*?)</script>',
                        overview_html,
                        flags=re.DOTALL,
                    )
                    if payload_match:
                        overview_payload = json.loads(payload_match.group(1))
                        sigma_partition = {
                            str(node): str(entry.get("id", ""))
                            for entry in overview_payload.get("navigation", {}).get("entries", [])
                            for node in entry.get("members", [])
                        }
                        for node in sigma_graph.nodes:
                            sigma_partition.setdefault(str(node), f"unpaged:{node}")
            await asyncio.to_thread(
                write_sigma_graph_pages,
                sigma_graph,
                result_path.parent,
                graph_name,
                sigma_partition,
                community_min_size,
                page_name,
            )
        except Exception as exc:
            logger.error("生成 Sigma 静态图谱失败: %s", graph_name, exc_info=True)
            raise HTTPException(status_code=500, detail=f"生成 Sigma 静态图谱失败: {exc}") from exc
    if not result_path.is_file():
        raise HTTPException(status_code=404, detail="图谱页面不存在")

    return get_graph_html_response(result_path, graph_name, page_name)


@app.get("/graph-assets/{asset_name}")
async def get_graph_asset(asset_name: str):
    """Serve local PyVis and Sigma runtimes with long-lived browser caching."""
    if asset_name in {"sigma.min.js", "graphology.umd.min.js"}:
        candidates = (
            FRONTEND_DIST_FOLDER / "graph-assets" / asset_name,
            Path(__file__).resolve().parent.parent / "frontend" / "node_modules" /
            ("sigma/dist" if asset_name == "sigma.min.js" else "graphology/dist") / asset_name,
        )
        asset_path = next((path for path in candidates if path.is_file()), candidates[0])
    else:
        try:
            asset_path = get_local_vis_asset_path(asset_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="图谱资源不存在")
    media_type = "text/css" if asset_name.endswith(".css") else "text/javascript"
    return FileResponse(
        asset_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def get_graph_html_response(result_path: Path, graph_name: str, page_name: str):
    """Serve finalized graphs and upgrade older interaction layers in memory."""
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
        "Content-Disposition": f"inline; filename*=utf-8''{quote(page_name, safe='')}",
    }
    html_content = result_path.read_text(encoding="utf-8")
    if f"const SIGMA_STATIC_PAGE_VERSION = {SIGMA_STATIC_PAGE_VERSION};" in html_content:
        return FileResponse(
            result_path,
            media_type="text/html",
            headers=headers,
        )
    if f"const GRAPH_EDITOR_VERSION = {GRAPH_EDITOR_VERSION};" not in html_content:
        return HTMLResponse(
            prepare_legacy_graph_html(
                html_content,
                asset_base_url="/api/graph-assets",
                graph_name=graph_name,
            ),
            headers=headers,
        )
    return FileResponse(
        result_path,
        media_type="text/html",
        headers=headers,
    )


@app.get("/result/{filename}")
async def get_result(filename: str):
    """
    获取处理结果的HTML文件。
    
    用途：
        下载或预览知识图谱HTML结果。
    
    参数：
        filename (str): 文件名。
    
    返回：
        FileResponse: 已预生成的 HTML 文件。
        JSONResponse: 错误时返回错误信息。
    
    异常：
        结果文件不存在时返回404。
    """
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
    result_file = f"{base_name}.html"
    result_path = RESULT_FOLDER / base_name / result_file

    if result_path.exists():
        return get_graph_html_response(result_path, base_name, result_file)

    # Compatibility for graph pages opened from an older response whose empty
    # <base> resolves links beside /result/{upload-name}.
    graph_name, marker, community_suffix = filename.rpartition("_community_")
    if marker and community_suffix.endswith(".html"):
        community_path = RESULT_FOLDER / graph_name / filename
        if community_path.is_file():
            return get_graph_html_response(community_path, graph_name, filename)

    status = (get_process_status(base_name) or {"status": "unknown"})["status"]
    return JSONResponse(
        status_code=404,
        content={
            "error": "结果文件不存在",
            "status": status,
            "filename": filename
        }
    )


@app.get("/health")
async def health_check():
    """
    健康检查接口。
    
    用途：
        检查服务是否正常运行。
    
    参数：
        无
    
    返回：
        dict: {"status": "healthy", "timestamp": float}
    
    异常：
        无
    """
    return {"status": "healthy", "timestamp": time.time()}


_file_text_stat_cache: Dict[str, tuple[int, int, int]] = {}


def get_file_library_metadata(base_name: str) -> tuple[int, str]:
    """Return exact non-whitespace character count and latest persisted edit time."""
    text_path = get_document_draft_path(base_name)
    if not text_path.is_file():
        text_path = TXT_FOLDER / f"{base_name}.txt"

    character_count = 0
    if text_path.is_file():
        stat = text_path.stat()
        cache_key = str(text_path)
        cached = _file_text_stat_cache.get(cache_key)
        if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            character_count = cached[2]
        else:
            content, _ = read_text_file(text_path)
            character_count = len(re.sub(r"\s+", "", content))
            _file_text_stat_cache[cache_key] = (stat.st_mtime_ns, stat.st_size, character_count)

    edit_paths = [
        text_path,
        get_document_history_path(base_name),
        GRAPH_HISTORY_FOLDER / f"{base_name}.json",
        RESULT_FOLDER / base_name / f"{base_name}.highlights.json",
    ]
    edit_timestamps = [path.stat().st_mtime for path in edit_paths if path.is_file()]
    latest_timestamp = max(edit_timestamps) if edit_timestamps else 0
    latest_edit = (
        datetime.fromtimestamp(latest_timestamp, tz=timezone.utc).isoformat()
        if latest_timestamp else ""
    )
    return character_count, latest_edit


@app.get("/list-files")
async def list_files():
    """
    获取所有已处理文件列表。
    
    用途：
        查询所有已上传并处理过的文件及其状态。
    
    参数：
        无
    
    返回：
        JSONResponse: {"files": List[dict]}
    
    异常：
        获取失败时返回500。
    """
    try:
        # 创建一个专用的storeManager实例来获取文件列表
        file_manager = storeManager(store=chromadb_store, agent=kg_agent)

        # 获取数据库中的文件列表
        db_files = file_manager.list_files()
        db_file_ids = db_files.get('ids', [])
        db_metadatas = db_files.get('metadatas', [])

        # 获取当前正在处理的文件（从PROCESS_STATUS获取）
        tracked_statuses = {
            "uploading", "importing", "processing", "updating", "resuming", "pausing", "redrawing",
            "paused", "interrupted", "error",
        }
        with process_status_lock:
            processing_files = {
                base_name: progress.copy()
                for base_name, progress in PROCESS_STATUS.items()
                if progress["status"] in tracked_statuses
            }

        # 状态映射，用于前端展示
        status_map = {
            "uploading": "上传中",
            "importing": "迁移包导入中",
            "processing": "处理中",
            "updating": "增量更新中",
            "resuming": "继续处理中",
            "pausing": "暂停中",
            "redrawing": "重新绘制图谱中",
            "paused": "已暂停",
            "completed": "已完成",
            "interrupted": "部分完成，可继续",
            "error": "处理失败，可重试"
        }

        # 合并结果：先处理数据库中的文件
        processed_files = []
        for i, file_id in enumerate(db_file_ids):
            if i >= len(db_metadatas):
                continue  # 防止索引错误

            base_name = os.path.splitext(file_id)[0]
            original_filename = db_metadatas[i].get('original_file_type', file_id)

            # 获取状态：优先从PROCESS_STATUS获取
            progress = get_process_status(base_name) or {"status": "completed", "percentage": 100}
            status = progress["status"]
            display_status = status_map.get(status, status)
            document_history = _read_document_history(base_name)
            character_count, last_edited_at = get_file_library_metadata(base_name)

            processed_files.append({
                "filename": original_filename,
                "status": status,
                "display_status": display_status,
                "percentage": progress.get("percentage", 0),
                "completed_chunks": progress.get("completed_chunks", 0),
                "total_chunks": progress.get("total_chunks", 0),
                "latest_chunk_seconds": progress.get("latest_chunk_seconds"),
                "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
                "processing_stage": progress.get("processing_stage"),
                "stage_progress": progress.get("stage_progress") or {},
                "overall_percentage": progress.get("overall_percentage", progress.get("percentage", 0)),
                "overall_speed_percent_per_minute": progress.get("overall_speed_percent_per_minute"),
                "estimated_total_remaining_seconds": progress.get(
                    "estimated_total_remaining_seconds",
                    progress.get("estimated_remaining_seconds"),
                ),
                "partial_available": bool(progress.get("partial_available")),
                "resumable": bool(progress.get("resumable")),
                "error_message": progress.get("error_message"),
                "document_modified": get_document_draft_path(base_name).is_file(),
                "document_revision": int(document_history.get("next_revision") or 1) - 1,
                "character_count": character_count,
                "last_edited_at": last_edited_at,
            })

        # 再添加仅在PROCESS_STATUS中的文件（正在处理但尚未添加到数据库的文件）
        db_base_names = [os.path.splitext(file_id)[0] for file_id in db_file_ids]
        for base_name, progress in processing_files.items():
            if base_name not in db_base_names:
                status = progress["status"]
                display_status = status_map.get(status, status)
                document_history = _read_document_history(base_name)
                character_count, last_edited_at = get_file_library_metadata(base_name)
                processed_files.append({
                    "filename": progress.get("original_filename") or f"{base_name}.txt",
                    "status": status,
                    "display_status": display_status,
                    "percentage": progress.get("percentage", 0),
                    "completed_chunks": progress.get("completed_chunks", 0),
                    "total_chunks": progress.get("total_chunks", 0),
                    "latest_chunk_seconds": progress.get("latest_chunk_seconds"),
                    "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
                    "processing_stage": progress.get("processing_stage"),
                    "stage_progress": progress.get("stage_progress") or {},
                    "overall_percentage": progress.get("overall_percentage", progress.get("percentage", 0)),
                    "overall_speed_percent_per_minute": progress.get("overall_speed_percent_per_minute"),
                    "estimated_total_remaining_seconds": progress.get(
                        "estimated_total_remaining_seconds",
                        progress.get("estimated_remaining_seconds"),
                    ),
                    "partial_available": bool(progress.get("partial_available")),
                    "resumable": bool(progress.get("resumable")),
                    "error_message": progress.get("error_message"),
                    "document_modified": get_document_draft_path(base_name).is_file(),
                    "document_revision": int(document_history.get("next_revision") or 1) - 1,
                    "character_count": character_count,
                    "last_edited_at": last_edited_at,
                })

        return JSONResponse({"files": processed_files})
    except Exception as e:
        logger.error(f"获取文件列表失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"获取文件列表失败: {str(e)}"}
        )


@app.delete("/delete/{filename}")
async def delete_file(filename: str):
    """
    删除指定文件及其相关数据。
    
    用途：
        删除知识图谱、数据库记录等。
    
    参数：
        filename (str): 文件名。
    
    返回：
        JSONResponse: {"message": str}
    
    异常：
        删除失败时返回500。
    """
    try:
        filename = get_safe_filename(filename)
        base_name = get_base_name(filename)
        progress = get_process_status(base_name) or {}
        if progress.get("status") in {
            "uploading", "importing", "processing", "updating", "resuming", "pausing"
        }:
            raise HTTPException(status_code=409, detail="请先暂停文件处理，再执行删除")
        kg_manager.delete_store([base_name])
        shutil.rmtree(RESULT_FOLDER / base_name, ignore_errors=True)
        for file_path in (
            UPLOAD_FOLDER / filename,
            TXT_FOLDER / f"{base_name}.txt",
            get_source_text_path(base_name),
            TXT_FOLDER / f"{base_name}_new.txt",
            get_document_draft_path(base_name),
            get_document_rich_path(base_name),
            STATUS_FOLDER / f"{base_name}.json",
            get_transfer_import_path(base_name),
            GRAPH_HISTORY_FOLDER / f"{base_name}.json",
            get_document_history_path(base_name),
            # Clean up a flat result produced by earlier versions as well.
            RESULT_FOLDER / f"{base_name}.html",
        ):
            file_path.unlink(missing_ok=True)
        with process_status_lock:
            PROCESS_STATUS.pop(base_name, None)
        return JSONResponse({"message": f"文件 {filename} 已成功删除"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"删除文件失败: {str(e)}"}
        )


@app.delete("/rag-history/{filename}")
async def delete_rag_history(filename: str):
    """
    删除指定文件的RAG对话历史。
    
    用途：
        清除RAG历史记录，释放存储空间。
    
    参数：
        filename (str): 文件名。
    
    返回：
        JSONResponse: {"message": str}
    
    异常：
        删除失败时返回500。
    """
    try:
        filename = get_safe_filename(filename)
        base_name = get_base_name(filename)
        # 使用chromadb_store删除RAG历史
        chromadb_store.delete_rag_history([base_name])
        return JSONResponse({
            "message": f"文件 {filename} 的RAG历史记录已成功删除"
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除RAG历史记录失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"删除RAG历史记录失败: {str(e)}"}
        )


@app.get("/file-entities/{filename}")
async def get_file_entities(filename: str, count: int = 5):
    """
    获取文件的主要实体。
    
    用途：
        查询知识图谱中最重要的实体节点。
    
    参数：
        filename (str): 文件名。
        count (int): 返回实体数量，默认5。
    
    返回：
        JSONResponse: {"entities": List[str]}
    
    异常：
        获取失败时返回404/500。
    """
    try:
        filename = get_safe_filename(filename)
        base_name = get_base_name(filename)

        # 创建一个存储管理器实例
        manager = storeManager(store=chromadb_store, agent=kg_agent)

        # 获取文件中的主要实体
        # 按关联度最高的节点
        entities = manager.edge_max_node(base_name, count)
        # 随机节点
        # entities = manager.get_n_entity(base_name, count)

        if entities is None:
            return JSONResponse(
                status_code=404,
                content={"error": "无法获取文件实体"}
            )

        # 只返回实体列表
        return JSONResponse({
            "entities": entities
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件实体失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"获取文件实体失败: {str(e)}"}
        )


# Serve the production frontend from the same process when it has been built.
# API routes are declared above, so this catch-all mount does not shadow them.
FRONTEND_DIST_FOLDER = Path(
    os.getenv(
        "FRONTEND_DIST",
        str(Path(__file__).resolve().parent.parent / "frontend" / "dist"),
    )
).expanduser()
if FRONTEND_DIST_FOLDER.is_dir():
    app.mount(
        "/",
        SPAStaticFiles(directory=FRONTEND_DIST_FOLDER, html=True),
        name="frontend",
    )
    logger.info("已挂载前端打包目录: %s", FRONTEND_DIST_FOLDER)
else:
    logger.warning(
        "未找到前端打包目录: %s，后端仍将仅提供 API；请先运行 npm run build",
        FRONTEND_DIST_FOLDER,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "localhost"),
        port=int(os.getenv("PORT", "8002")),
    )
