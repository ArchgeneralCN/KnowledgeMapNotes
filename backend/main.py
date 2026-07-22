import asyncio
from openai import OpenAI
from pydantic import BaseModel
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import shutil
import logging
from typing import Dict, List, Optional, AsyncGenerator
from urllib.parse import quote
from OmniStore.storeManager import storeManager
from OmniText.PDFProcessor import PDFProcessor
from OmniText.MDProcessor import MDProcessor
from concurrent.futures import ThreadPoolExecutor
import threading
import json
import uuid
from collections import deque
from dotenv import load_dotenv
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

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


class rag_item(BaseModel):
    request: str
    model: str
    flow: bool = False
    top_k: int = 1
    weight_threshold: float = 0.3  # 添加权重阈值参数
    max_relations: int = 20  # 添加最大关系数量参数
    filename: Optional[str] = None
    messages: Optional[List[Dict[str, str]]] = None  # 确保消息格式正确
    session_id: Optional[str] = None  # 会话ID，用于跟踪特定文件的对话


app = FastAPI(title="图谱笔记", description="大模型知识图谱笔记软件")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
TXT_FOLDER = os.getenv("TXT_FOLDER")
RESULT_FOLDER = os.getenv("RESULT_FOLDER")

PROCESS_STATUS: Dict[str, str] = {}

# 确保目录存在
for folder in [UPLOAD_FOLDER, TXT_FOLDER, RESULT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# 初始化知识图谱组件
from OmniStore.chromadb_store import StoreTool
from sentence_transformers import SentenceTransformer
from KnowledgeGraphManager.KGManager import KgManager



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

client = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL")
)

# 多模态模型
vl_client = OpenAI(
    # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
    api_key=os.getenv("VL_API_KEY"),
    base_url=os.getenv("VL_BASE_URL")
)
from LLM.Openai_Agent import OpenaiAgent
# 创建两个独立的agent
rag_agent = OpenaiAgent(client)
kg_agent = OpenaiAgent(client)

# 创建两个独立的splitter
simple_files = os.getenv("SIMPLE", "").split(",")
semantic_files = os.getenv("SEMANTIC", "").split(",")
character_files = os.getenv("CHARACTER", "").split(",")

# 初始化默认分割器
kg_splitter = None

# 创建默认分割器
if len(simple_files) > 0:
    from TextSlicer.SimpleTextSplitter import SimpleTextSplitter
    kg_splitter = SimpleTextSplitter(2048, 1024)
elif len(semantic_files) > 0:
    from TextSlicer.SemanticTextSplitter import SemanticTextSplitter
    kg_splitter = SemanticTextSplitter(2048, 1024)
elif len(character_files) > 0:
    from TextSlicer.CharacterTextSplitter import CharacterTextSplitter
    kg_splitter = CharacterTextSplitter(separator="</end>", keep_separator=False, max_tokens=2048, min_tokens=1024)

# 创建两个独立的kg_manager
kg_manager = KgManager(agent=kg_agent, splitter=kg_splitter, embedding_model=embeddings, store=chromadb_store)

FILE_PROCESSORS = {
    '.pdf': PDFProcessor,
    '.md': MDProcessor,
    # 可扩展，不想写了。。。
}
# 添加CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加线程池
executor = ThreadPoolExecutor(max_workers=16)  # 增加线程池大小以处理更多并发请求
# 添加专用于RAG的线程池
rag_executor = ThreadPoolExecutor(max_workers=16)  # RAG专用线程池
# 添加文件处理锁
file_locks = {}
# 添加RAG问答锁
rag_locks = {}

# 消息队列系统
# 存储结构: {session_id: deque([消息1, 消息2, ...]), ...}
message_queues = {}
# 每个会话的事件: {session_id: Event(), ...}
session_events = {}
# 每个会话的响应状态: {session_id: {"status": "processing/completed/error", "response": [..]}, ...}
session_responses = {}


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
    session_id = str(uuid.uuid4())
    message_queues[session_id] = deque()
    session_events[session_id] = asyncio.Event()
    session_responses[session_id] = {"status": "idle", "response": None}
    return {"session_id": session_id}


@app.post("/hybridrag")
async def hybridrag(item: rag_item):
    """
    处理混合RAG请求。
    
    用途：
        结合知识图谱和RAG检索，生成问答结果。
    
    参数：
        item (rag_item): 包含请求内容、模型、会话ID、历史消息等。
    
    返回：
        JSONResponse: {"result": {"answer": str, "material": str}} 或错误信息。
    
    异常：
        处理失败时返回500。
    """
    try:
        # 如果没有提供session_id则创建新的
        if not item.session_id:
            item.session_id = str(uuid.uuid4())
            message_queues[item.session_id] = deque()
            session_events[item.session_id] = asyncio.Event()
            session_responses[item.session_id] = {"status": "idle", "response": None}

        # 确保会话存在
        if item.session_id not in message_queues:
            message_queues[item.session_id] = deque()
            session_events[item.session_id] = asyncio.Event()
            session_responses[item.session_id] = {"status": "idle", "response": None}

        # 将请求放入队列
        message_queues[item.session_id].append(item)

        # 如果当前没有进行中的处理，启动处理任务
        if session_responses[item.session_id]["status"] == "idle":
            # 启动后台任务处理这个会话的消息
            asyncio.create_task(process_session_queue(item.session_id))

        # 设置状态为处理中
        session_responses[item.session_id]["status"] = "processing"

        # 等待处理完成
        await session_events[item.session_id].wait()
        session_events[item.session_id].clear()

        # 检查处理结果
        response_data = session_responses[item.session_id]["response"]

        # 如果状态为错误，返回错误信息
        if session_responses[item.session_id]["status"] == "error":
            return JSONResponse(
                status_code=500,
                content={"error": response_data or "处理失败"}
            )

        # 返回结果
        return JSONResponse({"result": response_data})

    except Exception as e:
        logger.error(f"处理出错: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/hybridrag/stream")
async def hybridrag_stream(item: rag_item):
    """
    处理混合RAG请求并以流式方式返回结果。
    
    用途：
        支持大模型流式输出，适合前端实时展示生成内容。
    
    参数：
        item (rag_item): 包含请求内容、模型、会话ID、历史消息等。
    
    返回：
        StreamingResponse: SSE流式返回生成内容。
    
    异常：
        处理失败时流中返回error类型消息。
    """
    # 生成唯一的请求ID
    request_id = str(uuid.uuid4())

    # 如果没有提供session_id则创建新的
    if not item.session_id:
        item.session_id = str(uuid.uuid4())
        message_queues[item.session_id] = deque()
        session_events[item.session_id] = asyncio.Event()
        session_responses[item.session_id] = {"status": "idle", "response": None}

    async def stream_generator() -> AsyncGenerator[str, None]:
        try:
            loop = asyncio.get_event_loop()
            if item.filename:
                base_name = os.path.splitext(item.filename)[0]

                # 不再检查文件状态，直接尝试获取RAG锁
                if base_name not in rag_locks:
                    rag_locks[base_name] = asyncio.Lock()

                # 获取锁但不阻塞，如果锁被占用则生成一个等待消息
                if not rag_locks[base_name].locked():
                    async with rag_locks[base_name]:
                        logger.info(f"开始处理知识图谱查询: {item.filename}")

                        # 流式输出准备
                        yield "data: " + json.dumps(
                            {"type": "status", "content": "开始处理", "request_id": request_id}) + "\n\n"

                        # 为每次查询创建新的storeManager实例
                        store_manager = storeManager(store=chromadb_store, agent=kg_agent)

                        # 执行RAG流程 - 实体识别，使用RAG专用线程池
                        rag_entity = await loop.run_in_executor(rag_executor, store_manager.text2entity, item.request,
                                                                base_name)
                        if not rag_entity:  # 如果返回空列表
                            logger.warning(f"未能识别实体: {item.filename}")
                            rag_entity = []  # 确保是空列表而不是None
                        yield "data: " + json.dumps(
                            {"type": "status", "content": "实体识别完成", "request_id": request_id}) + "\n\n"

                        # 执行RAG流程 - 社区检测，使用RAG专用线程池
                        community_info = await loop.run_in_executor(rag_executor, store_manager.community_louvain_G,
                                                                    base_name, rag_entity, item.weight_threshold, 
                                                                    item.max_relations)
                        if not community_info:  # 如果返回空列表
                            logger.warning(f"未能进行社区检测: {item.filename}")
                            community_info = []  # 确保是空列表而不是None
                        yield "data: " + json.dumps(
                            {"type": "status", "content": "社区检测完成", "request_id": request_id}) + "\n\n"

                        # 执行RAG流程 - 向量选择，使用RAG专用线程池
                        results = await loop.run_in_executor(rag_executor, store_manager.select_vectors, item.request,
                                                             base_name,
                                                             item.top_k)
                        if not results:  # 如果返回空列表
                            logger.warning(f"未能选择向量: {item.filename}")
                            results = []  # 确保是空列表而不是None
                        yield "data: " + json.dumps(
                            {"type": "status", "content": "生成中...", "request_id": request_id}) + "\n\n"

                        # 准备流式输出
                        logger.info(f"使用流式输出模式: {item.request}")

                        # 创建响应流 - 使用hybrid_rag_stream函数，使用RAG专用线程池
                        try:
                            response_stream = await loop.run_in_executor(
                                rag_executor,
                                rag_agent.hybrid_rag_stream,
                                item.request,
                                community_info,
                                results,
                                item.messages
                            )

                            # 确保response_stream不为None
                            if response_stream is None:
                                raise ValueError("响应流生成失败")

                            # 处理流式响应
                            full_text = ""
                            for chunk in response_stream:
                                # 检查chunk是否为None
                                if chunk is None:
                                    continue

                                content = rag_agent.process_hybrid_rag_stream_chunk(chunk)
                                if content:
                                    full_text += content
                                    yield "data: " + json.dumps({
                                        "type": "content",
                                        "chunk": content,
                                        "full": full_text,
                                        "request_id": request_id
                                    }) + "\n\n"
                            # 处理最终结果
                            answer, material = rag_agent.extract_material_from_text(full_text)
                            # 发送最终结果
                            yield "data: " + json.dumps({
                                "type": "final",
                                "answer": answer,
                                "material": material,
                                "request_id": request_id
                            }) + "\n\n"
                        except Exception as e:
                            logger.error(f"处理响应流时出错: {str(e)}")
                            yield "data: " + json.dumps({
                                "type": "error",
                                "content": f"处理响应失败: {str(e)}",
                                "request_id": request_id
                            }) + "\n\n"
                else:
                    # 如果锁被占用，将请求入队
                    if item.session_id not in message_queues:
                        message_queues[item.session_id] = deque()

                    message_queues[item.session_id].append(item)

                    # 通知前端请求已入队
                    yield "data: " + json.dumps({
                        "type": "status",
                        "content": "请求已入队，等待处理",
                        "request_id": request_id
                    }) + "\n\n"

                    # 等待其他请求处理完成
                    yield "data: " + json.dumps({
                        "type": "queued",
                        "session_id": item.session_id,
                        "request_id": request_id
                    }) + "\n\n"

        except Exception as e:
            logger.error(f"流式处理出错: {str(e)}", exc_info=True)  # 添加详细错误堆栈
            yield "data: " + json.dumps({
                "type": "error",
                "content": str(e),
                "request_id": request_id
            }) + "\n\n"
        finally:
            yield "data: " + json.dumps({
                "type": "done",
                "request_id": request_id
            }) + "\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


# 处理会话队列的后台任务
async def process_session_queue(session_id: str):
    """处理特定会话的消息队列"""
    loop = asyncio.get_event_loop()

    try:
        # 只要队列不为空，就继续处理
        while message_queues[session_id]:
            # 获取下一个待处理的请求
            item = message_queues[session_id].popleft()

            if item.filename:
                base_name = os.path.splitext(item.filename)[0]

                # 确保锁存在
                if base_name not in rag_locks:
                    rag_locks[base_name] = asyncio.Lock()

                async with rag_locks[base_name]:
                    logger.info(f"开始处理队列中的知识图谱查询: {item.filename}")

                    # 为每次查询创建新的storeManager实例
                    store_manager = storeManager(store=chromadb_store, agent=kg_agent)

                    # 执行RAG流程，使用RAG专用线程池
                    flow = item.flow
                    rag_entity = await loop.run_in_executor(rag_executor, store_manager.text2entity, item.request,
                                                            base_name)
                    community_info = await loop.run_in_executor(rag_executor, store_manager.community_louvain_G,
                                                                base_name, rag_entity, item.weight_threshold, 
                                                                item.max_relations)
                    results = await loop.run_in_executor(rag_executor, store_manager.select_vectors, item.request,
                                                         base_name, item.top_k)

                    try:
                        # 使用hybrid_rag函数，使用RAG专用线程池
                        result = await loop.run_in_executor(
                            rag_executor,
                            rag_agent.hybrid_rag,
                            item.request,
                            community_info,
                            results,
                            item.messages,
                            flow
                        )

                        # 确保结果有效
                        if not result or result == -1:
                            session_responses[session_id]["status"] = "error"
                            session_responses[session_id]["response"] = "生成回答失败"
                        else:
                            session_responses[session_id]["status"] = "completed"
                            session_responses[session_id]["response"] = {
                                "answer": result.get('answer', ''),
                                "material": result.get('material', '')
                            }
                    except Exception as e:
                        logger.error(f"处理队列中的响应时出错: {str(e)}", exc_info=True)
                        session_responses[session_id]["status"] = "error"
                        session_responses[session_id]["response"] = f"处理失败: {str(e)}"

            # 通知等待的请求处理已完成
            session_events[session_id].set()

        # 队列处理完毕，将状态设为空闲
        session_responses[session_id]["status"] = "idle"

    except Exception as e:
        logger.error(f"处理会话队列出错: {str(e)}", exc_info=True)
        session_responses[session_id]["status"] = "error"
        session_responses[session_id]["response"] = str(e)
        session_events[session_id].set()


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
        删除指定session_id的所有队列、事件和响应数据。
    
    参数：
        session_id (str): 会话ID。
    
    返回：
        dict: {"message": str}
    
    异常：
        无
    """
    if session_id in message_queues:
        del message_queues[session_id]

    if session_id in session_events:
        del session_events[session_id]

    if session_id in session_responses:
        del session_responses[session_id]

    return {"message": f"会话 {session_id} 已清除"}


def process_knowledge_graph(base_name: str, text_content: str, original_filename: str, noteType: str = "general"):
    """处理文本内容生成知识图谱"""
    try:
        # 获取文件处理锁
        if base_name not in file_locks:
            file_locks[base_name] = threading.Lock()

        with file_locks[base_name]:
            logger.info(f"开始处理文件 {base_name} 的知识图谱...")
            start_time = time.time()

            # 更新状态为处理中
            PROCESS_STATUS[base_name] = "processing"

            # 新建独立的KgManager实例
            kg_manager = KgManager(agent=kg_agent, splitter=kg_splitter, embedding_model=embeddings, store=chromadb_store)

            # 设置笔记类型
            kg_manager.noteType = noteType
            logger.info(f"设置笔记类型为: {noteType}")

            # 知识图谱构建过程
            r = kg_manager.知识图谱的构建(text_content)
            kg_manager.知识融合(r)
            logger.info(f"知识图谱构建完成，耗时: {time.time() - start_time:.2f}秒")

            # 转换为有向图
            kg_manager.三元组转有向图nx(r)

            # 绘制知识图谱
            start_time = time.time()
            kg_manager.绘制知识图谱(base_name)
            kg_manager.original_file_type = original_filename  # 使用原始文件名

            kg_manager.save_store()
            logger.info(f"知识图谱绘制完成，耗时: {time.time() - start_time:.2f}秒")

            # 保存并移动结果文件
            result_file = f"{base_name}.html"
            if os.path.exists(result_file):
                shutil.move(result_file, os.path.join(RESULT_FOLDER, result_file))
            else:
                raise FileNotFoundError("未生成结果HTML文件")

            # 更新处理状态为已完成
            PROCESS_STATUS[base_name] = "completed"
            logger.info(f"知识图谱处理完成: {base_name}")

    except Exception as e:
        error_msg = str(e)
        PROCESS_STATUS[base_name] = "error"
        logger.error(f"处理文件 {base_name} 出错: {error_msg}", exc_info=True)
        raise


def process_uploaded_file(original_path: str, filename: str, noteType: str = "general", use_img2txt: bool = False):
    """后台处理任务（包含文件转换）"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
        txt_filename = f"{os.path.splitext(filename)[0]}.txt"
        txt_path = os.path.join(TXT_FOLDER, txt_filename)

        # 在开始处理前将状态设置为processing
        PROCESS_STATUS[base_name] = "processing"
        logger.info(f"开始处理文件: {filename}, 状态已设置为processing")

        # 新建独立的KgManager实例
        kg_manager = KgManager(agent=kg_agent, splitter=kg_splitter, embedding_model=embeddings, store=chromadb_store)

        # 设置原始文件名
        kg_manager.original_file_type = filename  # 使用完整文件名

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

        # 根据文件类型选择不同的文本分块器
        if len(simple_files) > 0 and file_ext in simple_files:
            from TextSlicer.SimpleTextSplitter import SimpleTextSplitter
            kg_manager.splitter = SimpleTextSplitter(2045, 1024)
        elif len(semantic_files) > 0 and file_ext in semantic_files:
            from TextSlicer.SemanticTextSplitter import SemanticTextSplitter
            kg_manager.splitter = SemanticTextSplitter(2045, 1024)
        elif len(character_files) > 0 and file_ext in character_files:
            from TextSlicer.CharacterTextSplitter import CharacterTextSplitter
            kg_manager.splitter = CharacterTextSplitter(separator="</end>", keep_separator=False, max_tokens=2045, min_tokens=1024)

        # 处理知识图谱（传入独立kg_manager）
        process_knowledge_graph(base_name, text_content, filename, noteType)

        # 处理完成后更新状态
        PROCESS_STATUS[base_name] = "completed"
        logger.info(f"文件 {filename} 处理完成，状态已设置为completed")

    except Exception as e:
        error_msg = f"文件处理失败: {str(e)}"
        if 'base_name' in locals():  # 确保base_name已定义
            PROCESS_STATUS[base_name] = "error"
        logger.error(error_msg, exc_info=True)


def process_update_file(original_path: str, filename: str, txt_path: str, use_img2txt: bool = False):
    """处理文件增量更新"""
    try:
        # 获取文件信息
        base_name = os.path.splitext(filename)[0]
        file_ext = os.path.splitext(filename)[1].lower()
        new_txt_filename = f"{base_name}_new.txt"
        new_txt_path = os.path.join(TXT_FOLDER, new_txt_filename)

        # 在开始处理前将状态设置为updating
        PROCESS_STATUS[base_name] = "updating"
        logger.info(f"开始处理文件更新: {filename}, 状态已设置为updating")

        # 新建独立的KgManager实例
        kg_manager = KgManager(agent=kg_agent, splitter=kg_splitter, embedding_model=embeddings, store=chromadb_store)

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
            PROCESS_STATUS[base_name] = "completed"
            return

        # 增量更新前，先加载原有知识图谱
        if not kg_manager.load_store(base_name):
            raise ValueError(f"无法加载原有知识图谱: {base_name}")

        # 执行增量更新
        logger.info(f"开始执行增量更新: {base_name}")
        start_time = time.time()

        # 执行增量更新
        new_kg_triplet = kg_manager.增量更新(new_text_content)
        new_kg_triplet = kg_manager.知识融合(new_kg_triplet)

        # 检查更新结果是否为空
        if not new_kg_triplet or len(new_kg_triplet) == 0:
            logger.info(f"无新增内容，知识图谱保持不变: {base_name}")

            # 更新完成后，用新文件替换旧文件
            shutil.copy(new_txt_path, txt_path)
            os.remove(new_txt_path)  # 删除临时文件

            # 更新处理状态为已完成
            PROCESS_STATUS[base_name] = "completed"
            return

        # 转换为有向图
        kg_manager.三元组转有向图nx(new_kg_triplet)

        # 绘制更新后的知识图谱
        kg_manager.绘制知识图谱(base_name)

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

        # 保存并移动结果文件
        result_file = f"{base_name}.html"
        if os.path.exists(result_file):
            shutil.move(result_file, os.path.join(RESULT_FOLDER, result_file))
        else:
            raise FileNotFoundError("未生成结果HTML文件")

        # 更新处理状态为已完成
        PROCESS_STATUS[base_name] = "completed"
        logger.info(f"知识图谱增量更新完成: {base_name}")

    except Exception as e:
        error_msg = f"文件增量更新失败: {str(e)}"
        if 'base_name' in locals():  # 确保base_name已定义
            PROCESS_STATUS[base_name] = "error"
        logger.error(error_msg, exc_info=True)

        # 清理临时文件
        if 'new_txt_path' in locals() and os.path.exists(new_txt_path):
            try:
                os.remove(new_txt_path)
            except:
                pass


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    noteType: str = Form("general"),
    use_img2txt: str = Form("true"),
    background_tasks: BackgroundTasks = None
):
    """
    支持多种格式的文件上传接口，支持增量更新。
    
    用途：
        上传pdf、md、txt等文件，自动转换为文本并生成知识图谱。
        若文件已存在则自动进行增量更新。
    
    参数：
        file (UploadFile): 上传的文件。
        noteType (str): 笔记类型，默认为general。
        use_img2txt (str): 是否启用图片转文本，"true"/"false"。
        background_tasks (BackgroundTasks): FastAPI后台任务对象。
    
    返回：
        JSONResponse: 包含处理状态、文件名等信息。
    
    异常：
        上传或处理失败时返回500。
    """
    try:
        # 将字符串类型的use_img2txt参数转换为布尔值
        use_img2txt_bool = use_img2txt == "true"

        logger.info(f"收到图片文本识别参数: {use_img2txt} -> {use_img2txt_bool}")

        # 保存原始文件
        filename = file.filename
        base_name = os.path.splitext(filename)[0]
        original_path = os.path.join(UPLOAD_FOLDER, filename)
        txt_filename = f"{base_name}.txt"
        txt_path = os.path.join(TXT_FOLDER, txt_filename)

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

        # 保存上传的文件
        with open(original_path, "wb") as f:
            contents = await file.read()
            f.write(contents)

        logger.info(f"文件 {filename} 上传成功，存储为 {original_path}")
        logger.info(f"使用图片文本识别参数: {use_img2txt} -> {use_img2txt_bool}")

        # 设置状态和后台处理任务
        if file_exists and existing_txt:
            # 文件在数据库中已存在，执行增量更新
            PROCESS_STATUS[base_name] = "updating"
            logger.info(f"文件 {filename} 已存在，将进行增量更新")
            background_tasks.add_task(process_update_file, original_path, filename, txt_path, use_img2txt_bool)

            return JSONResponse({
                "status": "updating",
                "message": "文件已上传，正在进行增量更新",
                "filename": filename,
                "is_update": True
            })
        else:
            # 新文件上传，执行常规处理
            PROCESS_STATUS[base_name] = "uploading"
            background_tasks.add_task(process_uploaded_file, original_path, filename, noteType, use_img2txt_bool)

            return JSONResponse({
                "status": "uploading",
                "message": "文件已上传，正在转换处理中",
                "filename": filename,
                "noteType": noteType
            })

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
    base_name = os.path.splitext(filename)[0]
    status = PROCESS_STATUS.get(base_name)

    # 状态映射，用于前端展示
    status_map = {
        "uploading": "上传中",
        "processing": "处理中",
        "updating": "增量更新中",
        "completed": "已完成",
        "error": "失败"
    }

    if status:
        result_exists = os.path.exists(os.path.join(RESULT_FOLDER, f'{base_name}.html'))
        display_status = status_map.get(status, status)

        return JSONResponse({
            "status": status,
            "display_status": display_status,
            "result_exists": result_exists,
            "filename": filename
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
    txt_filename = f"{os.path.splitext(filename)[0]}.txt"
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


@app.get("/result/{filename}")
async def get_result(filename: str):
    """
    获取处理结果的HTML文件。
    
    用途：
        下载或预览知识图谱HTML结果。
    
    参数：
        filename (str): 文件名。
    
    返回：
        FileResponse: HTML文件。
        JSONResponse: 错误时返回错误信息。
    
    异常：
        结果文件不存在时返回404。
    """
    base_name = os.path.splitext(filename)[0]
    result_file = f"{base_name}.html"
    result_path = os.path.join(RESULT_FOLDER, result_file)

    if os.path.exists(result_path):
        safe_filename = quote(result_file, safe='')
        return FileResponse(
            result_path,
            media_type="text/html",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Disposition": f"inline; filename*=utf-8''{safe_filename}"
            }
        )
    else:
        status = PROCESS_STATUS.get(base_name, "unknown")
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
        processing_statuses = ["uploading", "processing"]
        processing_files = {base_name: status for base_name, status in PROCESS_STATUS.items()
                            if status in processing_statuses}

        # 状态映射，用于前端展示
        status_map = {
            "uploading": "上传中",
            "processing": "处理中",
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
            status = PROCESS_STATUS.get(base_name, "completed")
            display_status = status_map.get(status, status)

            processed_files.append({
                "filename": original_filename,
                "status": status,
                "display_status": display_status
            })

        # 再添加仅在PROCESS_STATUS中的文件（正在处理但尚未添加到数据库的文件）
        db_base_names = [os.path.splitext(file_id)[0] for file_id in db_file_ids]
        for base_name, status in processing_files.items():
            if base_name not in db_base_names:
                display_status = status_map.get(status, status)
                processed_files.append({
                    "filename": f"{base_name}.txt",  # 默认使用txt扩展名
                    "status": status,
                    "display_status": display_status
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
        base_name = os.path.splitext(filename)[0]
        kg_manager.delete_store([base_name])
        return JSONResponse({"message": f"文件 {filename} 已成功删除"})
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
        base_name = os.path.splitext(filename)[0]
        # 使用chromadb_store删除RAG历史
        chromadb_store.delete_rag_history([base_name])
        return JSONResponse({
            "message": f"文件 {filename} 的RAG历史记录已成功删除"
        })
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
        base_name = os.path.splitext(filename)[0]

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
    except Exception as e:
        logger.error(f"获取文件实体失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"获取文件实体失败: {str(e)}"}
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)