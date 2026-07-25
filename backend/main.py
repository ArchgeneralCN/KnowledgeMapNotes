import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, AsyncGenerator, Deque, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from urllib.parse import quote

from OmniStore.storeManager import storeManager
from OmniText.MDProcessor import MDProcessor
from OmniText.PDFProcessor import PDFProcessor

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

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


app = FastAPI(title="图谱笔记", description="大模型知识图谱笔记软件")


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

PROCESS_STATUS: Dict[str, Dict[str, Any]] = {}
process_status_lock = Lock()


def set_process_status(base_name: str, status: str, **updates: Any) -> None:
    """Atomically update the status and chunk-level progress for one file."""
    with process_status_lock:
        current = PROCESS_STATUS.get(base_name, {})
        next_status = {**current, **updates, "status": status}
        PROCESS_STATUS[base_name] = next_status


def get_process_status(base_name: str) -> Optional[Dict[str, Any]]:
    """Return a copy so responses cannot observe a partially changed status."""
    with process_status_lock:
        status = PROCESS_STATUS.get(base_name)
        return status.copy() if status else None


def create_chunk_progress_callback(base_name: str, status: str = "processing"):
    """Record a completed chunk and estimate remaining work from its duration."""
    def update_progress(completed_chunks: int, total_chunks: int, chunk_seconds: float) -> None:
        remaining_chunks = max(total_chunks - completed_chunks, 0)
        set_process_status(
            base_name,
            status,
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
for folder in [UPLOAD_FOLDER, TXT_FOLDER, RESULT_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)


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
from KnowledgeGraphManager.KGManager import KgManager, PROCESSING_PROMPT_FILES



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

MAX_CUSTOM_PROMPT_LENGTH = 30_000


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
)
kg_agent = OpenaiAgent(
    client,
    model_name=AI_SETTINGS["model_name"],
    temperature=AI_SETTINGS["temperature"],
    enable_thinking=AI_SETTINGS["enable_thinking"],
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
    }


def require_ai_settings() -> None:
    """Reject model-dependent requests until runtime settings are complete."""
    with ai_settings_lock:
        is_configured = (
            client is not None
            and bool(AI_SETTINGS["base_url"])
            and bool(AI_SETTINGS["api_key"])
            and bool(AI_SETTINGS["model_name"])
        )
    if not is_configured:
        raise HTTPException(status_code=503, detail="请先在前端完成 AI 配置")


def request_ai_validation_completion(ai_client: OpenAI, settings: Dict[str, Any]) -> None:
    """Send the smallest useful request for validating an OpenAI-compatible service."""
    ai_client.with_options(timeout=20.0, max_retries=0).chat.completions.create(
        model=settings["model_name"],
        messages=[{"role": "user", "content": "Reply with OK."}],
        temperature=settings["temperature"],
        max_tokens=8,
        extra_body={
            "thinking": {
                "type": "enabled" if settings["enable_thinking"] else "disabled"
            }
        },
    )


async def validate_current_ai_settings() -> None:
    """Verify the active model configuration before starting file processing."""
    require_ai_settings()
    with ai_settings_lock:
        current_client = client
        settings = AI_SETTINGS.copy()

    try:
        await asyncio.wait_for(
            asyncio.to_thread(request_ai_validation_completion, current_client, settings),
            timeout=25.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="AI 配置校验超时，请检查服务地址或网络") from exc
    except Exception as exc:
        logger.warning(
            "上传前 AI 配置校验失败: base_url=%s model=%s error=%s",
            settings["base_url"],
            settings["model_name"],
            exc,
        )
        raise HTTPException(status_code=502, detail=f"AI 配置校验失败，请检查配置: {exc}") from exc


def prepare_ai_settings(settings: AISettingsUpdate) -> tuple[OpenAI, Dict[str, Any]]:
    """Validate settings and build a client without changing runtime state."""
    base_url = settings.base_url.strip().rstrip("/")
    model_name = settings.model_name.strip()
    submitted_api_key = (settings.api_key or "").strip()

    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Base URL 必须以 http:// 或 https:// 开头")
    if not model_name:
        raise HTTPException(status_code=422, detail="模型名称不能为空")

    with ai_settings_lock:
        api_key = submitted_api_key or AI_SETTINGS["api_key"]
    if not api_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空")

    try:
        next_client = create_openai_client(api_key=api_key, base_url=base_url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"AI 配置无效: {exc}") from exc
    if next_client is None:
        raise HTTPException(status_code=422, detail="Base URL 和 API Key 不能为空")

    return next_client, {
        "base_url": base_url,
        "api_key": api_key,
        "model_name": model_name,
        "temperature": settings.temperature,
        "enable_thinking": settings.enable_thinking,
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
    global client

    next_client, next_settings = prepare_ai_settings(settings)

    with ai_settings_lock:
        rag_agent.configure(
            next_client,
            model_name=next_settings["model_name"],
            temperature=next_settings["temperature"],
            enable_thinking=next_settings["enable_thinking"],
        )
        kg_agent.configure(
            next_client,
            model_name=next_settings["model_name"],
            temperature=next_settings["temperature"],
            enable_thinking=next_settings["enable_thinking"],
        )
        client = next_client
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
    test_client, test_settings = prepare_ai_settings(settings)

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

    latency_ms = round((time.monotonic() - started_at) * 1000)
    return {"message": "AI 连接测试成功", "latency_ms": latency_ms}


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


def process_knowledge_graph(
    base_name: str,
    text_content: str,
    original_filename: str,
    note_type: str = "general",
    splitter=None,
    custom_prompts: Optional[Dict[str, str]] = None,
):
    """处理文本内容生成知识图谱"""
    try:
        # 获取文件处理锁
        if base_name not in file_locks:
            file_locks[base_name] = Lock()

        with file_locks[base_name]:
            logger.info(f"开始处理文件 {base_name} 的知识图谱...")
            start_time = time.time()

            # 更新状态为处理中
            set_process_status(
                base_name,
                "processing",
                completed_chunks=0,
                total_chunks=0,
                percentage=0,
                latest_chunk_seconds=None,
                estimated_remaining_seconds=None,
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

            # 知识图谱构建过程
            r = kg_manager.知识图谱的构建(
                text_content,
                progress_callback=create_chunk_progress_callback(base_name),
            )
            kg_manager.知识融合(r)
            logger.info(f"知识图谱构建完成，耗时: {time.time() - start_time:.2f}秒")

            # 转换为有向图
            kg_manager.三元组转有向图nx(r)

            # 绘制知识图谱
            start_time = time.time()
            kg_manager.绘制知识图谱(
                base_name,
                输出目录=RESULT_FOLDER,
            )
            kg_manager.original_file_type = original_filename  # 使用原始文件名

            kg_manager.save_store()
            logger.info(f"知识图谱绘制完成，耗时: {time.time() - start_time:.2f}秒")

            # 图谱首页和所有社区子页由 KgManager 直接写入同一个结果目录。
            result_file = RESULT_FOLDER / base_name / f"{base_name}.html"
            if not result_file.exists():
                raise FileNotFoundError("未生成结果HTML文件")

            # 更新处理状态为已完成
            set_process_status(base_name, "completed", percentage=100, estimated_remaining_seconds=0)
            logger.info(f"知识图谱处理完成: {base_name}")

    except Exception as e:
        error_msg = str(e)
        set_process_status(base_name, "error", estimated_remaining_seconds=None)
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
        set_process_status(
            base_name,
            "processing",
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

        # 读取转换后的文本内容
        with open(txt_path, "r", encoding="utf-8") as f:
            text_content = f.read()

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
        set_process_status(base_name, "completed", percentage=100, estimated_remaining_seconds=0)
        logger.info(f"文件 {filename} 处理完成，状态已设置为completed")

    except Exception as e:
        error_msg = f"文件处理失败: {str(e)}"
        if 'base_name' in locals():  # 确保base_name已定义
            set_process_status(base_name, "error", estimated_remaining_seconds=None)
        logger.error(error_msg, exc_info=True)


def process_update_file(
    original_path: str,
    filename: str,
    txt_path: str,
    use_img2txt: bool = False,
    note_type: str = "general",
    custom_prompts: Optional[Dict[str, str]] = None,
):
    """处理文件增量更新"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
        new_txt_filename = f"{base_name}_new.txt"
        new_txt_path = os.path.join(TXT_FOLDER, new_txt_filename)

        # 在开始处理前将状态设置为updating
        set_process_status(
            base_name,
            "updating",
            completed_chunks=0,
            total_chunks=0,
            percentage=0,
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
            if file_ext in FILE_PROCESSORS:
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

        # 读取新的文本内容
        with open(new_txt_path, "r", encoding="utf-8") as f:
            new_text_content = f.read()

        # 读取原始文本内容
        with open(txt_path, "r", encoding="utf-8") as f:
            original_text_content = f.read()

        logger.info(f"文件 {filename} 转换完成，开始比较内容差异")

        # 检查文件内容是否完全相同
        if new_text_content == original_text_content:
            logger.info(f"文件内容完全相同，无需更新: {base_name}")

            # 删除临时文件
            os.remove(new_txt_path)

            # 更新处理状态为已完成
            set_process_status(base_name, "completed", percentage=100, estimated_remaining_seconds=0)
            return

        # 增量更新前，先加载原有知识图谱
        if not kg_manager.load_store(base_name):
            raise ValueError(f"无法加载原有知识图谱: {base_name}")

        # 执行增量更新
        logger.info(f"开始执行增量更新: {base_name}")
        start_time = time.time()

        # 执行增量更新
        new_kg_triplet = kg_manager.增量更新(
            new_text_content,
            progress_callback=create_chunk_progress_callback(base_name, status="updating"),
        )
        new_kg_triplet = kg_manager.知识融合(new_kg_triplet)

        # 检查更新结果是否为空
        if not new_kg_triplet or len(new_kg_triplet) == 0:
            logger.info(f"无新增内容，知识图谱保持不变: {base_name}")

            # 更新完成后，用新文件替换旧文件
            shutil.copy(new_txt_path, txt_path)
            os.remove(new_txt_path)  # 删除临时文件

            # 更新处理状态为已完成
            set_process_status(base_name, "completed", percentage=100, estimated_remaining_seconds=0)
            return

        # 转换为有向图
        kg_manager.三元组转有向图nx(new_kg_triplet)

        # 绘制更新后的知识图谱
        kg_manager.绘制知识图谱(
            base_name,
            输出目录=RESULT_FOLDER,
        )

        # 更新完成后，用新文件替换旧文件
        shutil.copy(new_txt_path, txt_path)
        os.remove(new_txt_path)  # 删除临时文件

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

        # 更新处理状态为已完成
        set_process_status(base_name, "completed", percentage=100, estimated_remaining_seconds=0)
        logger.info(f"知识图谱增量更新完成: {base_name}")

    except Exception as e:
        error_msg = f"文件增量更新失败: {str(e)}"
        if 'base_name' in locals():  # 确保base_name已定义
            set_process_status(base_name, "error", estimated_remaining_seconds=None)
        logger.error(error_msg, exc_info=True)

        # 清理临时文件
        if 'new_txt_path' in locals() and os.path.exists(new_txt_path):
            try:
                os.remove(new_txt_path)
            except OSError:
                logger.warning("清理临时文件失败: %s", new_txt_path, exc_info=True)


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
    # Validate the active credentials/model before touching the uploaded file or
    # changing any existing graph state. A failed check leaves no processing task.
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
        filename = get_safe_filename(file.filename or "")
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
            # A failed run may leave a partial graph and converted text behind.
            # Discard them so this upload is rebuilt from the source file.
            if file_exists:
                kg_manager.delete_store([base_name])
            shutil.rmtree(RESULT_FOLDER / base_name, ignore_errors=True)
            txt_path.unlink(missing_ok=True)
            file_exists = False
            existing_txt = False
            logger.info("文件 %s 上次处理失败，本次将重新完整处理", filename)

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
            set_process_status(
                base_name,
                "updating",
                completed_chunks=0,
                total_chunks=0,
                percentage=0,
                latest_chunk_seconds=None,
                estimated_remaining_seconds=None,
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
        "completed": "已完成",
        "error": "失败"
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

    if os.path.exists(txt_path):
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read()
            return JSONResponse({"content": content})
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


def get_graph_html_response(result_path: Path, graph_name: str, page_name: str) -> HTMLResponse:
    """Serve graph HTML with a stable base for relative page navigation."""
    html_content = result_path.read_text(encoding="utf-8")
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
        processing_statuses = ["uploading", "processing", "updating"]
        with process_status_lock:
            processing_files = {
                base_name: progress.copy()
                for base_name, progress in PROCESS_STATUS.items()
                if progress["status"] in processing_statuses
            }

        # 状态映射，用于前端展示
        status_map = {
            "uploading": "上传中",
            "processing": "处理中",
            "updating": "增量更新中",
            "completed": "已完成",
            "error": "失败"
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

            processed_files.append({
                "filename": original_filename,
                "status": status,
                "display_status": display_status,
                "percentage": progress.get("percentage", 0),
                "completed_chunks": progress.get("completed_chunks", 0),
                "total_chunks": progress.get("total_chunks", 0),
                "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
            })

        # 再添加仅在PROCESS_STATUS中的文件（正在处理但尚未添加到数据库的文件）
        db_base_names = [os.path.splitext(file_id)[0] for file_id in db_file_ids]
        for base_name, progress in processing_files.items():
            if base_name not in db_base_names:
                status = progress["status"]
                display_status = status_map.get(status, status)
                processed_files.append({
                    "filename": f"{base_name}.txt",  # 默认使用txt扩展名
                    "status": status,
                    "display_status": display_status,
                    "percentage": progress.get("percentage", 0),
                    "completed_chunks": progress.get("completed_chunks", 0),
                    "total_chunks": progress.get("total_chunks", 0),
                    "estimated_remaining_seconds": progress.get("estimated_remaining_seconds"),
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
        kg_manager.delete_store([base_name])
        shutil.rmtree(RESULT_FOLDER / base_name, ignore_errors=True)
        for file_path in (
            UPLOAD_FOLDER / filename,
            TXT_FOLDER / f"{base_name}.txt",
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
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
