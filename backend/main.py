import asyncio
import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncGenerator, Deque, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
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
    get_local_vis_asset_path,
    prepare_legacy_graph_html,
)
from KnowledgeGraphManager.graph_editing import (
    GraphEditError,
    GraphHistory,
    apply_graph_mutation,
    graph_payload,
    state_from_snapshot,
    state_snapshot,
)

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

load_dotenv(dotenv_path="./.env")

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


class RAGRequest(BaseModel):
    """A request to answer a question against a processed knowledge graph."""

    request: str
    model: Optional[str] = None
    flow: bool = False
    top_k: int = 1
    weight_threshold: float = 0.3
    max_relations: int = 20
    filename: Optional[str] = None
    messages: Optional[List[Dict[str, str]]] = None
    session_id: Optional[str] = None


class AISettingsUpdate(BaseModel):
    """Runtime settings for the OpenAI-compatible text model."""

    base_url: str
    api_key: Optional[str] = None
    model_name: str
    temperature: float = Field(ge=0, le=2)
    enable_thinking: bool = False
    fallback_enabled: bool = False
    fallback_base_url: Optional[str] = None
    fallback_api_key: Optional[str] = None
    fallback_model_name: Optional[str] = None


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
MAX_TRANSFER_PACKAGE_SIZE = 100 * 1024 * 1024
DEFAULT_EXAMPLE_FOLDER = Path(__file__).resolve().parent / "default_examples"
DEFAULT_EXAMPLE_PACKAGE = DEFAULT_EXAMPLE_FOLDER / f"本软件使用说明{PACKAGE_SUFFIX}"
try:
    CHECKPOINT_INTERVAL = max(1, int(os.getenv("CHECKPOINT_INTERVAL", "10")))
except (TypeError, ValueError):
    CHECKPOINT_INTERVAL = 10

PROCESS_STATUS: Dict[str, Dict[str, Any]] = {}
process_status_lock = Lock()


def persist_process_status(base_name: str, status: Dict[str, Any]) -> None:
    """Atomically persist recovery metadata so a service restart is resumable."""
    status_path = STATUS_FOLDER / f"{base_name}.json"
    temporary_path = status_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(status_path)


def set_process_status(base_name: str, status: str, **updates: Any) -> None:
    """Atomically update the status and chunk-level progress for one file."""
    with process_status_lock:
        current = PROCESS_STATUS.get(base_name, {})
        next_status = {
            **current,
            **updates,
            "status": status,
            "updated_at": time.time(),
        }
        PROCESS_STATUS[base_name] = next_status
        persist_process_status(base_name, next_status)


def get_process_status(base_name: str) -> Optional[Dict[str, Any]]:
    """Return a copy so responses cannot observe a partially changed status."""
    with process_status_lock:
        status = PROCESS_STATUS.get(base_name)
        return status.copy() if status else None


def create_chunk_progress_callback(base_name: str, status: str = "processing"):
    """Record a completed chunk and estimate remaining work from its duration."""
    def update_progress(completed_chunks: int, total_chunks: int, chunk_seconds: float) -> None:
        remaining_chunks = max(total_chunks - completed_chunks, 0)
        current = get_process_status(base_name) or {}
        effective_status = "pausing" if current.get("pause_requested") else status
        set_process_status(
            base_name,
            effective_status,
            completed_chunks=completed_chunks,
            total_chunks=total_chunks,
            percentage=round(completed_chunks * 100 / total_chunks) if total_chunks else 0,
            latest_chunk_seconds=round(chunk_seconds, 1),
            estimated_remaining_seconds=(
                max(1, round(remaining_chunks * chunk_seconds)) if remaining_chunks else 0
            ),
        )

    return update_progress

# Ensure configured runtime directories exist before accepting requests.
for folder in [UPLOAD_FOLDER, TXT_FOLDER, RESULT_FOLDER, STATUS_FOLDER, GRAPH_HISTORY_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)


def restore_process_statuses() -> None:
    """Restore file states and mark abandoned in-flight work as interrupted."""
    active_statuses = {"uploading", "processing", "updating", "resuming", "pausing"}
    for status_path in STATUS_FOLDER.glob("*.json"):
        try:
            restored = json.loads(status_path.read_text(encoding="utf-8"))
            base_name = status_path.stem
            if restored.get("status") == "redrawing":
                has_existing_graph = (RESULT_FOLDER / base_name / f"{base_name}.html").is_file()
                restored["status"] = "completed" if has_existing_graph else "error"
                restored["error_message"] = (
                    "重新绘制被服务中断，已保留原图"
                    if has_existing_graph else "重新绘制被服务中断，图谱页面不存在"
                )
                restored["pause_requested"] = False
                persist_process_status(base_name, restored)
            elif restored.get("status") in active_statuses:
                completed = int(restored.get("completed_chunks") or 0)
                was_pausing = restored.get("status") == "pausing" or restored.get("pause_requested")
                restored["status"] = "paused" if was_pausing else (
                    "interrupted" if completed else "error"
                )
                restored["error_message"] = (
                    None if was_pausing else "服务中断，等待继续处理"
                )
                restored["pause_requested"] = False
                source_path = Path(
                    restored.get("source_text_path") or TXT_FOLDER / f"{base_name}.source.txt"
                )
                original_filename = restored.get("original_filename")
                restored["resumable"] = source_path.is_file() or bool(
                    original_filename and (UPLOAD_FOLDER / original_filename).is_file()
                )
                persist_process_status(base_name, restored)
            PROCESS_STATUS[base_name] = restored
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.warning("忽略损坏的处理状态文件: %s", status_path, exc_info=True)


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

# 初始化知识图谱组件
from OmniStore.chromadb_store import StoreTool
from sentence_transformers import SentenceTransformer
from KnowledgeGraphManager.KGManager import KgManager, PROCESSING_PROMPT_FILES, ProcessingPaused



device = os.getenv("DEVICE")


if os.getenv("IS_USE_LOCAL") == "True":
    embeddings = SentenceTransformer(
        os.getenv("EMBEDDINGS_PATH")
    ).to(device)
else:
    # 初始化模型和组件
    embeddings = SentenceTransformer(os.getenv("EMBEDDINGS")).to(device)


# 创建两个独立的存储工具
chromadb_store = StoreTool(storage_path= os.getenv("CHROMADB_PATH"), embedding_function=embeddings)
graph_history = GraphHistory(GRAPH_HISTORY_FOLDER)
graph_edit_lock = Lock()

MAX_CUSTOM_PROMPT_LENGTH = 30_000


def _graph_manager_state(manager: KgManager) -> Dict[str, Any]:
    base_name = str(manager.file or "")
    return {
        "file": manager.file,
        "kg_triplet": manager.kg_triplet,
        "bidirectional_mapping": manager.bidirectional_mapping,
        "current_G": manager.current_G,
        "Bolts": manager.Bolts,
        "original_file_type": manager.original_file_type,
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
async def redraw_graph(filename: str):
    """Redraw one file's complete graph from its saved state."""
    filename = get_safe_filename(filename)
    base_name = get_base_name(filename)
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
        estimated_remaining_seconds=None,
        error_message=None,
    )
    try:
        history_revision = await asyncio.to_thread(redraw_graph_from_store, base_name)
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
        "message": "图谱已根据当前保存的图谱状态重新绘制",
        "history_revision": history_revision,
    }


@app.get("/graph-history/{filename}")
async def get_graph_history(filename: str):
    base_name = get_base_name(filename)
    return {"versions": graph_history.list_versions(base_name)}


@app.get("/graph-sources/{filename}")
async def get_graph_sources(filename: str):
    """Return completed text blocks used to locate graph evidence in the reader."""
    base_name = get_base_name(filename)
    manager = _load_editable_graph(base_name)
    return {
        "blocks": [
            {"bid": str(bid), "text": str(text), "index": index}
            for index, (bid, text) in enumerate(manager.Bolts)
        ]
    }


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

def parse_boolean(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes", "on", "enabled"}


ai_settings_lock = Lock()
AI_SETTINGS: Dict[str, Any] = {
    "base_url": os.getenv("BASE_URL", "").strip(),
    "api_key": os.getenv("API_KEY", "").strip(),
    "model_name": os.getenv("MODEL_NAME", "").strip(),
    "temperature": float(os.getenv("TEMPERATURE", "0")),
    "enable_thinking": parse_boolean(os.getenv("ENABLE_THINKING")),
    "fallback_enabled": parse_boolean(os.getenv("FALLBACK_ENABLED")),
    "fallback_base_url": os.getenv("FALLBACK_BASE_URL", "").strip(),
    "fallback_api_key": os.getenv("FALLBACK_API_KEY", "").strip(),
    "fallback_model_name": os.getenv("FALLBACK_MODEL_NAME", "").strip(),
}


def create_openai_client(api_key: str, base_url: str) -> Optional[OpenAI]:
    """Create a client only after the user has supplied both required values."""
    if not api_key or not base_url:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


client = create_openai_client(
    api_key=AI_SETTINGS["api_key"],
    base_url=AI_SETTINGS["base_url"],
)
fallback_client = create_openai_client(
    api_key=AI_SETTINGS["fallback_api_key"],
    base_url=AI_SETTINGS["fallback_base_url"],
) if AI_SETTINGS["fallback_enabled"] else None
if client is None:
    logger.info("未在环境变量中配置 AI 服务，等待用户在前端完成设置")

# 多模态模型
vl_client = create_openai_client(
    api_key=os.getenv("VL_API_KEY", "").strip(),
    base_url=os.getenv("VL_BASE_URL", "").strip(),
)
from LLM.Openai_Agent import OpenaiAgent
# 创建两个独立的agent
rag_agent = OpenaiAgent(
    client,
    model_name=AI_SETTINGS["model_name"],
    temperature=AI_SETTINGS["temperature"],
    enable_thinking=AI_SETTINGS["enable_thinking"],
    fallback_client=fallback_client,
    fallback_model_name=AI_SETTINGS["fallback_model_name"],
)
kg_agent = OpenaiAgent(
    client,
    model_name=AI_SETTINGS["model_name"],
    temperature=AI_SETTINGS["temperature"],
    enable_thinking=AI_SETTINGS["enable_thinking"],
    fallback_client=fallback_client,
    fallback_model_name=AI_SETTINGS["fallback_model_name"],
)


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 7:
        return "****"
    return f"{api_key[:3]}...{api_key[-4:]}"


def get_public_ai_settings() -> Dict[str, Any]:
    with ai_settings_lock:
        settings = AI_SETTINGS.copy()
    return {
        "base_url": settings["base_url"],
        "model_name": settings["model_name"],
        "temperature": settings["temperature"],
        "enable_thinking": settings["enable_thinking"],
        "api_key_configured": bool(settings["api_key"]),
        "api_key_hint": mask_api_key(settings["api_key"]),
        "fallback_enabled": settings["fallback_enabled"],
        "fallback_base_url": settings["fallback_base_url"],
        "fallback_model_name": settings["fallback_model_name"],
        "fallback_api_key_configured": bool(settings["fallback_api_key"]),
        "fallback_api_key_hint": mask_api_key(settings["fallback_api_key"]),
    }


def require_ai_settings() -> None:
    """Reject model-dependent requests until runtime settings are complete."""
    with ai_settings_lock:
        primary_configured = client is not None and bool(AI_SETTINGS["model_name"])
        fallback_configured = (
            AI_SETTINGS["fallback_enabled"]
            and fallback_client is not None
            and bool(AI_SETTINGS["fallback_model_name"])
        )
        is_configured = primary_configured or fallback_configured
    if not is_configured:
        raise HTTPException(status_code=503, detail="请先在前端完成 AI 配置")


def request_ai_validation_completion(ai_client: OpenAI, settings: Dict[str, Any]) -> None:
    """Send the smallest useful request for validating an OpenAI-compatible service."""
    response = ai_client.with_options(timeout=20.0, max_retries=0).chat.completions.create(
        model=settings["model_name"],
        messages=[{"role": "user", "content": "Reply with OK."}],
        temperature=settings["temperature"],
        max_tokens=32,
        extra_body={
            "thinking": {
                "type": "enabled" if settings["enable_thinking"] else "disabled"
            }
        },
    )
    # A gateway can return HTTP 200 with an HTML landing page or raw text.
    # Validate the actual OpenAI-compatible response before accepting settings.
    OpenaiAgent._extract_chat_completion(response)


async def validate_current_ai_settings() -> None:
    """Verify the active model configuration before starting file processing."""
    require_ai_settings()
    with ai_settings_lock:
        current_client = client
        current_fallback_client = fallback_client
        settings = AI_SETTINGS.copy()

    primary_error: Optional[Exception] = None
    try:
        await asyncio.wait_for(
            asyncio.to_thread(request_ai_validation_completion, current_client, settings),
            timeout=25.0,
        )
        return
    except Exception as primary_exc:
        primary_error = primary_exc
        logger.warning(
            "上传前 AI 配置校验失败: base_url=%s model=%s error=%s",
            settings["base_url"],
            settings["model_name"],
            primary_exc,
        )

    if settings["fallback_enabled"] and current_fallback_client is not None:
        fallback_settings = {
            **settings,
            "base_url": settings["fallback_base_url"],
            "api_key": settings["fallback_api_key"],
            "model_name": settings["fallback_model_name"],
        }
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    request_ai_validation_completion,
                    current_fallback_client,
                    fallback_settings,
                ),
                timeout=25.0,
            )
            logger.info("主 AI 校验失败，备用 AI 可用，允许继续处理")
            return
        except Exception as fallback_exc:
            logger.warning("备用 AI 配置校验失败: %s", fallback_exc)
            raise HTTPException(
                status_code=502,
                detail=f"主 AI 和备用 AI 均不可用: {fallback_exc}",
            ) from fallback_exc

    raise HTTPException(
        status_code=502,
        detail=f"主 AI 不可用且未配置备用 AI: {primary_error}",
    ) from primary_error


def prepare_ai_settings(
    settings: AISettingsUpdate,
) -> tuple[OpenAI, Optional[OpenAI], Dict[str, Any]]:
    """Validate settings and build a client without changing runtime state."""
    base_url = settings.base_url.strip().rstrip("/")
    model_name = settings.model_name.strip()
    submitted_api_key = (settings.api_key or "").strip()
    fallback_base_url = (settings.fallback_base_url or "").strip().rstrip("/")
    fallback_model_name = (settings.fallback_model_name or "").strip()
    submitted_fallback_api_key = (settings.fallback_api_key or "").strip()

    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Base URL 必须以 http:// 或 https:// 开头")
    if not model_name:
        raise HTTPException(status_code=422, detail="模型名称不能为空")

    with ai_settings_lock:
        api_key = submitted_api_key or AI_SETTINGS["api_key"]
        fallback_api_key = (
            submitted_fallback_api_key or AI_SETTINGS["fallback_api_key"]
        )
    if not api_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空")

    try:
        next_client = create_openai_client(api_key=api_key, base_url=base_url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"AI 配置无效: {exc}") from exc
    if next_client is None:
        raise HTTPException(status_code=422, detail="Base URL 和 API Key 不能为空")

    next_fallback_client = None
    if settings.fallback_enabled:
        if not fallback_base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="备用 Base URL 必须以 http:// 或 https:// 开头")
        if not fallback_model_name:
            raise HTTPException(status_code=422, detail="备用模型名称不能为空")
        if not fallback_api_key:
            raise HTTPException(status_code=422, detail="备用 API Key 不能为空")
        try:
            next_fallback_client = create_openai_client(
                api_key=fallback_api_key,
                base_url=fallback_base_url,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"备用 AI 配置无效: {exc}") from exc

    return next_client, next_fallback_client, {
        "base_url": base_url,
        "api_key": api_key,
        "model_name": model_name,
        "temperature": settings.temperature,
        "enable_thinking": settings.enable_thinking,
        "fallback_enabled": settings.fallback_enabled,
        "fallback_base_url": fallback_base_url,
        "fallback_api_key": fallback_api_key,
        "fallback_model_name": fallback_model_name,
    }


@app.get("/ai-settings")
async def get_ai_settings():
    """Return runtime model settings without exposing the API key."""
    return get_public_ai_settings()


@app.post("/ai-settings/validate")
async def validate_ai_settings():
    """Validate the active model configuration without changing it."""
    await validate_current_ai_settings()
    return {"message": "AI 配置校验成功"}


@app.put("/ai-settings")
async def update_ai_settings(settings: AISettingsUpdate):
    """Apply model settings to subsequent graph extraction and RAG calls."""
    global client, fallback_client

    next_client, next_fallback_client, next_settings = prepare_ai_settings(settings)

    with ai_settings_lock:
        rag_agent.configure(
            next_client,
            model_name=next_settings["model_name"],
            temperature=next_settings["temperature"],
            enable_thinking=next_settings["enable_thinking"],
            fallback_client=next_fallback_client,
            fallback_model_name=next_settings["fallback_model_name"],
        )
        kg_agent.configure(
            next_client,
            model_name=next_settings["model_name"],
            temperature=next_settings["temperature"],
            enable_thinking=next_settings["enable_thinking"],
            fallback_client=next_fallback_client,
            fallback_model_name=next_settings["fallback_model_name"],
        )
        client = next_client
        fallback_client = next_fallback_client
        AI_SETTINGS.update(next_settings)

    logger.info(
        "AI 配置已更新: base_url=%s model=%s temperature=%s thinking=%s",
        next_settings["base_url"],
        next_settings["model_name"],
        settings.temperature,
        settings.enable_thinking,
    )
    return {"message": "AI 配置已更新", **get_public_ai_settings()}


@app.post("/ai-settings/test")
async def test_ai_settings(settings: AISettingsUpdate):
    """Test submitted settings with a minimal request without saving them."""
    test_client, test_fallback_client, test_settings = prepare_ai_settings(settings)

    started_at = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(request_ai_validation_completion, test_client, test_settings),
            timeout=25.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="AI 连接测试超时，请检查服务地址或网络") from exc
    except Exception as exc:
        logger.warning(
            "AI 连接测试失败: base_url=%s model=%s error=%s",
            test_settings["base_url"],
            test_settings["model_name"],
            exc,
        )
        raise HTTPException(status_code=502, detail=f"AI 连接测试失败: {exc}") from exc

    if test_settings["fallback_enabled"] and test_fallback_client is not None:
        fallback_test_settings = {
            **test_settings,
            "base_url": test_settings["fallback_base_url"],
            "api_key": test_settings["fallback_api_key"],
            "model_name": test_settings["fallback_model_name"],
        }
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    request_ai_validation_completion,
                    test_fallback_client,
                    fallback_test_settings,
                ),
                timeout=25.0,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"备用 AI 连接测试失败: {exc}") from exc

    latency_ms = round((time.monotonic() - started_at) * 1000)
    return {
        "message": "主 AI 和备用 AI 连接测试成功"
        if test_settings["fallback_enabled"] else "AI 连接测试成功",
        "latency_ms": latency_ms,
    }


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

# 初始化默认分割器
kg_splitter = None

# 创建默认分割器
if simple_files:
    from TextSlicer.SimpleTextSplitter import SimpleTextSplitter
    kg_splitter = SimpleTextSplitter(2048, 1024)
elif semantic_files:
    from TextSlicer.SemanticTextSplitter import SemanticTextSplitter
    kg_splitter = SemanticTextSplitter(2048, 1024)
elif character_files:
    from TextSlicer.CharacterTextSplitter import CharacterTextSplitter
    kg_splitter = CharacterTextSplitter(separator="</end>", keep_separator=False, max_tokens=2048, min_tokens=1024)


def get_splitter_for_extension(file_extension: str):
    """Build the configured splitter for a file type, with a default fallback."""
    if file_extension in simple_files:
        return SimpleTextSplitter(2048, 1024)
    if file_extension in semantic_files:
        return SemanticTextSplitter(2048, 1024)
    if file_extension in character_files:
        return CharacterTextSplitter(
            separator="</end>", keep_separator=False, max_tokens=2048, min_tokens=1024
        )
    return kg_splitter


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

rag_executor = ThreadPoolExecutor(max_workers=int(os.getenv("RAG_WORKER_COUNT", "4")))
file_locks: Dict[str, Lock] = {}
rag_locks: Dict[str, asyncio.Lock] = {}

# 消息队列系统
# 存储结构: {session_id: deque([消息1, 消息2, ...]), ...}
message_queues: Dict[str, Deque["PendingRAGRequest"]] = {}
# 每个会话的响应状态: {session_id: {"status": "processing/idle/error"}, ...}
session_responses: Dict[str, Dict[str, object]] = {}


@dataclass
class PendingRAGRequest:
    request: RAGRequest
    completion: asyncio.Future[Dict[str, str]]


def initialize_session(session_id: Optional[str] = None) -> str:
    """Return an existing session or initialize state for a new one."""
    session_id = session_id or str(uuid.uuid4())
    if session_id not in message_queues:
        message_queues[session_id] = deque()
        session_responses[session_id] = {"status": "idle"}
    return session_id


@app.post("/create_session")
async def create_session():
    """
    创建新的会话ID。
    
    用途：
        用于前端或客户端创建一个新的对话会话，后续RAG问答等操作可复用该session_id。
    
    参数：
        无
    
    返回：
        dict: {"session_id": str} 新生成的会话ID。
    
    异常：
        无
    """
    session_id = initialize_session()
    return {"session_id": session_id}


@app.post("/hybridrag")
async def hybridrag(item: RAGRequest):
    """
    处理混合RAG请求。
    
    用途：
        结合知识图谱和RAG检索，生成问答结果。
    
    参数：
        item (RAGRequest): 包含请求内容、模型、会话ID、历史消息等。
    
    返回：
        JSONResponse: {"result": {"answer": str, "material": str}} 或错误信息。
    
    异常：
        处理失败时返回500。
    """
    require_ai_settings()
    if not item.filename:
        raise HTTPException(status_code=422, detail="filename 为必填项")

    item.filename = get_safe_filename(item.filename)
    session_id = initialize_session(item.session_id)
    item.session_id = session_id
    completion = asyncio.get_running_loop().create_future()
    message_queues[session_id].append(PendingRAGRequest(item, completion))

    if session_responses[session_id]["status"] == "idle":
        asyncio.create_task(process_session_queue(session_id))
    session_responses[session_id]["status"] = "processing"

    try:
        return JSONResponse({"result": await completion})
    except Exception as exc:
        logger.exception("处理知识图谱查询失败: session_id=%s", session_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/hybridrag/stream")
async def hybridrag_stream(item: RAGRequest):
    """Process a RAG request and return server-sent events."""
    require_ai_settings()
    if not item.filename:
        raise HTTPException(status_code=422, detail="filename 为必填项")

    item.filename = get_safe_filename(item.filename)
    item.session_id = initialize_session(item.session_id)
    request_id = str(uuid.uuid4())

    async def stream_generator() -> AsyncGenerator[str, None]:
        try:
            loop = asyncio.get_running_loop()
            base_name = get_base_name(item.filename or "")
            rag_locks.setdefault(base_name, asyncio.Lock())

            async with rag_locks[base_name]:
                logger.info("开始流式知识图谱查询: filename=%s request_id=%s", item.filename, request_id)
                yield "data: " + json.dumps(
                    {"type": "status", "content": "开始处理", "request_id": request_id}
                ) + "\n\n"

                store_manager = storeManager(store=chromadb_store, agent=kg_agent)
                rag_entity = await loop.run_in_executor(
                    rag_executor, store_manager.text2entity, item.request, base_name
                ) or []
                yield "data: " + json.dumps(
                    {"type": "status", "content": "实体识别完成", "request_id": request_id}
                ) + "\n\n"

                community_info = await loop.run_in_executor(
                    rag_executor,
                    store_manager.community_louvain_G,
                    base_name,
                    rag_entity,
                    item.weight_threshold,
                    item.max_relations,
                ) or []
                yield "data: " + json.dumps(
                    {"type": "status", "content": "社区检测完成", "request_id": request_id}
                ) + "\n\n"

                results = await loop.run_in_executor(
                    rag_executor, store_manager.select_vectors, item.request, base_name, item.top_k
                ) or []
                yield "data: " + json.dumps(
                    {"type": "status", "content": "生成中...", "request_id": request_id}
                ) + "\n\n"

                response_stream = await loop.run_in_executor(
                    rag_executor,
                    rag_agent.hybrid_rag_stream,
                    item.request,
                    community_info,
                    results,
                    item.messages,
                )
                if response_stream is None:
                    raise RuntimeError("响应流生成失败")

                full_text = ""
                for chunk in response_stream:
                    if chunk is None:
                        continue
                    content = rag_agent.process_hybrid_rag_stream_chunk(chunk)
                    if content:
                        full_text += content
                        yield "data: " + json.dumps({
                            "type": "content",
                            "chunk": content,
                            "full": full_text,
                            "request_id": request_id,
                        }) + "\n\n"

                answer, material = rag_agent.extract_material_from_text(full_text)
                yield "data: " + json.dumps({
                    "type": "final",
                    "answer": answer,
                    "material": material,
                    "request_id": request_id,
                }) + "\n\n"
        except Exception as exc:
            logger.exception("流式知识图谱查询失败: request_id=%s", request_id)
            yield "data: " + json.dumps({
                "type": "error",
                "content": str(exc),
                "request_id": request_id,
            }) + "\n\n"
        finally:
            yield "data: " + json.dumps({
                "type": "done",
                "request_id": request_id,
            }) + "\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# 处理会话队列的后台任务
async def process_session_queue(session_id: str):
    """Process a session sequentially and resolve the matching HTTP request."""
    loop = asyncio.get_running_loop()

    try:
        while message_queues.get(session_id):
            pending_request = message_queues[session_id].popleft()
            item = pending_request.request
            base_name = get_base_name(item.filename or "")
            rag_locks.setdefault(base_name, asyncio.Lock())

            try:
                async with rag_locks[base_name]:
                    logger.info("开始处理知识图谱查询: filename=%s session_id=%s", item.filename, session_id)
                    store_manager = storeManager(store=chromadb_store, agent=kg_agent)
                    rag_entity = await loop.run_in_executor(
                        rag_executor, store_manager.text2entity, item.request, base_name
                    )
                    community_info = await loop.run_in_executor(
                        rag_executor,
                        store_manager.community_louvain_G,
                        base_name,
                        rag_entity,
                        item.weight_threshold,
                        item.max_relations,
                    )
                    results = await loop.run_in_executor(
                        rag_executor, store_manager.select_vectors, item.request, base_name, item.top_k
                    )
                    result = await loop.run_in_executor(
                        rag_executor,
                        rag_agent.hybrid_rag,
                        item.request,
                        community_info,
                        results,
                        item.messages,
                        item.flow,
                    )

                if not result or result == -1:
                    raise RuntimeError("生成回答失败")

                response_data = {
                    "answer": result.get("answer", ""),
                    "material": result.get("material", ""),
                }
                if not pending_request.completion.done():
                    pending_request.completion.set_result(response_data)
            except Exception as exc:
                logger.exception("处理队列中的知识图谱查询失败: session_id=%s", session_id)
                if not pending_request.completion.done():
                    pending_request.completion.set_exception(exc)

        if session_id in session_responses:
            session_responses[session_id]["status"] = "idle"
    except Exception:
        logger.exception("处理会话队列失败: session_id=%s", session_id)
        if session_id in session_responses:
            session_responses[session_id]["status"] = "error"


@app.get("/session_status/{session_id}")
async def get_session_status(session_id: str):
    """
    获取会话状态。
    
    用途：
        查询指定session_id的处理状态和队列长度。
    
    参数：
        session_id (str): 会话ID。
    
    返回：
        dict: {"status": str, "queue_length": int}
    
    异常：
        会话不存在时返回404。
    """
    if session_id not in session_responses:
        return JSONResponse(
            status_code=404,
            content={"error": "会话不存在"}
        )

    # 返回会话状态和消息队列长度
    queue_length = len(message_queues.get(session_id, deque()))
    return {
        "status": session_responses[session_id]["status"],
        "queue_length": queue_length
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    清除会话数据。
    
    用途：
        删除指定session_id的队列和状态数据。
    
    参数：
        session_id (str): 会话ID。
    
    返回：
        dict: {"message": str}
    
    异常：
        无
    """
    if session_responses.get(session_id, {}).get("status") == "processing":
        raise HTTPException(status_code=409, detail="会话仍在处理中，暂不能删除")

    message_queues.pop(session_id, None)
    session_responses.pop(session_id, None)

    return {"message": f"会话 {session_id} 已清除"}


def get_source_text_path(base_name: str) -> Path:
    """Return the private full-text source used for recovery and incremental work."""
    return TXT_FOLDER / f"{base_name}.source.txt"


def get_document_draft_path(base_name: str) -> Path:
    return TXT_FOLDER / f"{base_name}.draft.txt"


def get_document_rich_path(base_name: str) -> Path:
    return TXT_FOLDER / f"{base_name}.rich.html"


def get_document_history_path(base_name: str) -> Path:
    return GRAPH_HISTORY_FOLDER / f"{base_name}.document.json"


def _read_document_history(base_name: str) -> Dict[str, Any]:
    path = get_document_history_path(base_name)
    if not path.is_file():
        return {"schema": 1, "next_revision": 1, "versions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("文档历史格式无效")
        data.setdefault("schema", 1)
        data.setdefault("next_revision", 1)
        data.setdefault("versions", [])
        return data
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("读取文档历史失败，将创建新历史: %s", exc)
        return {"schema": 1, "next_revision": 1, "versions": []}


def _write_document_history(base_name: str, data: Dict[str, Any]) -> None:
    path = get_document_history_path(base_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".document.json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _document_snapshot(base_name: str, content: Optional[str] = None, rich_content: Optional[str] = None) -> Dict[str, Any]:
    draft_path = get_document_draft_path(base_name)
    if content is None:
        content_path = draft_path
        if not content_path.is_file():
            content_path = TXT_FOLDER / f"{base_name}.txt"
        content = content_path.read_text(encoding="utf-8") if content_path.is_file() else ""
    if rich_content is None:
        rich_path = get_document_rich_path(base_name)
        rich_content = rich_path.read_text(encoding="utf-8") if rich_path.is_file() else ""
    return {
        "content": str(content),
        "rich_content": str(rich_content or ""),
        "draft": draft_path.is_file(),
    }


def _restore_document_snapshot(base_name: str, snapshot: Optional[Dict[str, Any]]) -> None:
    """Restore the document files represented by a combined graph snapshot."""
    if not snapshot:
        return
    content = str(snapshot.get("content") or "")
    rich_content = str(snapshot.get("rich_content") or "")
    if snapshot.get("draft"):
        get_document_draft_path(base_name).write_text(content, encoding="utf-8")
    else:
        (TXT_FOLDER / f"{base_name}.txt").write_text(content, encoding="utf-8")
        get_source_text_path(base_name).write_text(content, encoding="utf-8")
        get_document_draft_path(base_name).unlink(missing_ok=True)
    if rich_content:
        get_document_rich_path(base_name).write_text(rich_content, encoding="utf-8")
    else:
        get_document_rich_path(base_name).unlink(missing_ok=True)


def _append_document_version(base_name: str, snapshot: Dict[str, Any], operation: str) -> int:
    data = _read_document_history(base_name)
    revision = int(data.get("next_revision") or 1)
    data["versions"].append({
        "revision": revision,
        "operation": operation,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **snapshot,
    })
    data["next_revision"] = revision + 1
    _write_document_history(base_name, data)
    return revision


def _document_operation_label(operation: str) -> str:
    operation = str(operation or "")
    if operation.startswith("before:document_edit"):
        return "文档修改前"
    if operation.startswith("document_edit"):
        return "文档修改后"
    if operation.startswith("before:document_restore"):
        return "文档还原前"
    if operation.startswith("document_restore:"):
        return f"还原文档版本 {operation.split(':', 1)[1]}"
    return "文档版本"


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


def render_graph_atomically(manager: KgManager, base_name: str) -> None:
    """Render beside the live result and publish the main page only when complete."""
    temporary_root = RESULT_FOLDER / f".{base_name}.{uuid.uuid4().hex}.tmp"
    try:
        manager.绘制知识图谱(base_name, 输出目录=temporary_root)
        generated_directory = temporary_root / base_name
        target_directory = RESULT_FOLDER / base_name
        target_directory.mkdir(parents=True, exist_ok=True)
        generated_files = list(generated_directory.iterdir())
        main_page = f"{base_name}.html"
        generated_files.sort(key=lambda path: path.name == main_page)
        for generated_file in generated_files:
            generated_file.replace(target_directory / generated_file.name)
        generated_names = {path.name for path in generated_files}
        for stale_page in target_directory.glob("*.html"):
            if stale_page.name not in generated_names:
                stale_page.unlink()
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def redraw_graph_from_store(base_name: str) -> int:
    """Render the persisted graph again without re-running document extraction."""
    with graph_edit_lock:
        manager = _load_editable_graph(base_name)
        revision = graph_history.commit_snapshot(
            base_name,
            _graph_manager_state(manager),
            "redraw_graph",
        )
        render_graph_atomically(manager, base_name)
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
    set_process_status(
        base_name,
        effective_status,
        completed_chunks=completed_chunks,
        total_chunks=total_chunks,
        percentage=round(completed_chunks * 100 / total_chunks) if total_chunks else 0,
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
            round(completed_chunks * 100 / max(int(progress.get("total_chunks") or 0), completed_chunks))
            if completed_chunks else 0
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

            set_process_status(
                base_name,
                processing_status,
                completed_chunks=completed_offset,
                total_chunks=len(all_blocks),
                percentage=round(completed_offset * 100 / len(all_blocks)) if all_blocks else 0,
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
                progress_callback=create_chunk_progress_callback(base_name, processing_status),
                checkpoint_callback=checkpoint_callback,
                append=resume,
                completed_offset=completed_offset,
                total_chunks=len(all_blocks),
                pause_callback=lambda: should_pause_file_processing(base_name),
            )
            kg_manager.知识融合(r)
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
):
    """后台处理任务（包含文件转换）"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
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
            get_splitter_for_extension(file_ext),
            custom_prompts,
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
    edited_text: Optional[str] = None,
):
    """处理文件增量更新"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
        new_txt_filename = f"{base_name}_new.txt"
        new_txt_path = os.path.join(TXT_FOLDER, new_txt_filename)

        # 在开始处理前将状态设置为updating
        current_progress = get_process_status(base_name) or {}
        set_process_status(
            base_name,
            "pausing" if current_progress.get("pause_requested") else "updating",
            completed_chunks=int(current_progress.get("completed_chunks") or 0),
            total_chunks=int(current_progress.get("total_chunks") or 0),
            percentage=int(current_progress.get("percentage") or 0),
            latest_chunk_seconds=None,
            estimated_remaining_seconds=None,
        )
        logger.info(f"开始处理文件更新: {filename}, 状态已设置为updating")

        # 新建独立的KgManager实例
        kg_manager = KgManager(
            agent=kg_agent,
            splitter=get_splitter_for_extension(file_ext),
            embedding_model=embeddings,
            store=chromadb_store,
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
        before_history = state_snapshot(_graph_manager_state(kg_manager))

        # 执行增量更新
        logger.info(f"开始执行增量更新: {base_name}")
        start_time = time.time()

        # 执行增量更新
        new_kg_triplet = kg_manager.增量更新(
            new_text_content,
            progress_callback=create_chunk_progress_callback(base_name, status="updating"),
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
        new_kg_triplet = kg_manager.知识融合(new_kg_triplet)
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
            get_splitter_for_extension(file_ext),
            progress.get("custom_prompts") or {},
            resume=has_checkpoint,
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
            imported = await asyncio.to_thread(
                import_file_transfer_package,
                bytes(package_content),
            )
            return JSONResponse(imported)
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
            "partial_available": bool(progress.get("partial_available")),
            "resumable": bool(progress.get("resumable")),
            "error_message": progress.get("error_message"),
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
    if page_name != main_page_name and not is_community_page:
        raise HTTPException(status_code=404, detail="图谱页面不存在")

    result_path = RESULT_FOLDER / graph_name / page_name
    if not result_path.is_file():
        raise HTTPException(status_code=404, detail="图谱页面不存在")

    return get_graph_html_response(result_path, graph_name, page_name)


@app.get("/graph-assets/{asset_name}")
async def get_graph_asset(asset_name: str):
    """Serve the installed PyVis runtime locally with long-lived browser caching."""
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


def get_graph_html_response(result_path: Path, graph_name: str, page_name: str) -> HTMLResponse:
    """Serve graph HTML with a stable base for relative page navigation."""
    html_content = result_path.read_text(encoding="utf-8")
    html_content = prepare_legacy_graph_html(
        html_content,
        asset_base_url="/api/graph-assets",
        graph_name=graph_name,
    )
    if "<head>" in html_content:
        html_content = html_content.replace(
            "<head>", '<head><base href="./">', 1
        )

    # Results produced by earlier versions may contain either of these absolute
    # prefixes. Convert only this graph's navigation links so the injected base
    # above also fixes old files without changing their on-disk contents.
    for legacy_prefix in (
        f'href="/api/result-page/{quote(graph_name, safe="")}/',
        f'href="/KnowledgeMapNotes/results/{graph_name}/',
        f'href="/KnowledgeMapNotes/results/{quote(graph_name, safe="")}/',
    ):
        html_content = html_content.replace(legacy_prefix, 'href="')

    return HTMLResponse(
        content=html_content,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": f"inline; filename*=utf-8''{quote(page_name, safe='')}",
        },
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
        HTMLResponse: HTML文件。
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
            "uploading", "processing", "updating", "resuming", "pausing", "redrawing",
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

            processed_files.append({
                "filename": original_filename,
                "status": status,
                "display_status": display_status,
                "percentage": progress.get("percentage", 0),
                "completed_chunks": progress.get("completed_chunks", 0),
                "total_chunks": progress.get("total_chunks", 0),
                "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
                "partial_available": bool(progress.get("partial_available")),
                "resumable": bool(progress.get("resumable")),
                "error_message": progress.get("error_message"),
                "document_modified": get_document_draft_path(base_name).is_file(),
                "document_revision": int(document_history.get("next_revision") or 1) - 1,
            })

        # 再添加仅在PROCESS_STATUS中的文件（正在处理但尚未添加到数据库的文件）
        db_base_names = [os.path.splitext(file_id)[0] for file_id in db_file_ids]
        for base_name, progress in processing_files.items():
            if base_name not in db_base_names:
                status = progress["status"]
                display_status = status_map.get(status, status)
                document_history = _read_document_history(base_name)
                processed_files.append({
                    "filename": progress.get("original_filename") or f"{base_name}.txt",
                    "status": status,
                    "display_status": display_status,
                    "percentage": progress.get("percentage", 0),
                    "completed_chunks": progress.get("completed_chunks", 0),
                    "total_chunks": progress.get("total_chunks", 0),
                    "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
                    "partial_available": bool(progress.get("partial_available")),
                    "resumable": bool(progress.get("resumable")),
                    "error_message": progress.get("error_message"),
                    "document_modified": get_document_draft_path(base_name).is_file(),
                    "document_revision": int(document_history.get("next_revision") or 1) - 1,
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
            "uploading", "processing", "updating", "resuming", "pausing"
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
        port=int(os.getenv("PORT", "8000")),
    )
