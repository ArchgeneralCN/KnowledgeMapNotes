"""Session-oriented knowledge-graph RAG endpoints and execution state."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Deque, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from OmniStore.storeManager import storeManager


class RAGRequest(BaseModel):
    """A question and retrieval options for one processed document."""

    request: str
    model: Optional[str] = None
    flow: bool = False
    top_k: int = 1
    weight_threshold: float = 0.3
    max_relations: int = 20
    filename: Optional[str] = None
    messages: Optional[List[Dict[str, str]]] = None
    session_id: Optional[str] = None


@dataclass
class PendingRAGRequest:
    """One queued request and the future resolved by the session worker."""

    request: RAGRequest
    completion: asyncio.Future[Dict[str, Any]]


class RAGService:
    """Own RAG queues, per-document locks, citations and query execution."""

    def __init__(
        self,
        *,
        vector_store: Any,
        kg_agent: Any,
        rag_agent: Any,
        require_ai_settings: Callable[[], None],
        safe_filename: Callable[[str], str],
        base_name: Callable[[str], str],
        graph_payload_loader: Callable[[str], Dict[str, Any]],
        logger: Any,
    ) -> None:
        self.vector_store = vector_store
        self.kg_agent = kg_agent
        self.rag_agent = rag_agent
        self.require_ai_settings = require_ai_settings
        self.safe_filename = safe_filename
        self.base_name = base_name
        self.graph_payload_loader = graph_payload_loader
        self.logger = logger
        self.executor = ThreadPoolExecutor(
            max_workers=int(os.getenv("RAG_WORKER_COUNT", "4")),
            thread_name_prefix="rag",
        )
        self.document_locks: Dict[str, asyncio.Lock] = {}
        self.message_queues: Dict[str, Deque[PendingRAGRequest]] = {}
        self.session_responses: Dict[str, Dict[str, object]] = {}

    def initialize_session(self, session_id: Optional[str] = None) -> str:
        """Return an existing session or initialize a new in-memory queue."""
        session_id = session_id or str(uuid.uuid4())
        if session_id not in self.message_queues:
            self.message_queues[session_id] = deque()
            self.session_responses[session_id] = {"status": "idle"}
        return session_id

    def build_citations(
        self,
        document_name: str,
        retrieval: Dict[str, Any],
        rag_entities: List[Any],
    ) -> List[Dict[str, Any]]:
        """Build stable source-block and graph-element links for an answer."""
        citations: List[Dict[str, Any]] = []
        documents = list(retrieval.get("documents") or [])
        block_ids = list(retrieval.get("ids") or [])
        for index, document in enumerate(documents[:4]):
            block_id = str(block_ids[index]) if index < len(block_ids) else ""
            if not block_id:
                continue
            citations.append({
                "id": f"source-{block_id}",
                "type": "source",
                "label": f"原文片段 {index + 1}",
                "preview": " ".join(str(document or "").split())[:180],
                "sourceBlocks": [block_id],
                "entityTerms": [],
                "relationTerms": [],
            })

        entity_names = {
            str(entity) for entity in (rag_entities or []) if str(entity).strip()
        }
        if not entity_names:
            return citations

        try:
            payload = self.graph_payload_loader(document_name)
        except Exception:
            self.logger.warning(
                "RAG 引用无法加载图谱目标: %s", document_name, exc_info=True
            )
            return citations

        nodes = [
            node
            for node in payload.get("nodes", [])
            if str(node.get("id")) in entity_names
            or str(node.get("name")) in entity_names
        ]
        for node in nodes[:2]:
            node_id = str(node.get("id", ""))
            citations.append({
                "id": f"graph-node-{node_id}",
                "type": "graph",
                "graphKind": "node",
                "graphId": node_id,
                "label": node.get("name") or node_id,
                "preview": f"图谱实体 · {node.get('entityType') or '未分类'}",
                "sourceBlocks": node.get("source_blocks") or [],
                "entityTerms": [node.get("name") or node_id],
                "relationTerms": [],
            })

        related_links = [
            link
            for link in payload.get("links", [])
            if str(link.get("source")) in entity_names
            or str(link.get("target")) in entity_names
        ]
        related_links.sort(
            key=lambda link: float(link.get("weight") or 0), reverse=True
        )
        for link in related_links[:2]:
            relation = str(link.get("relation") or "关联")
            source = str(link.get("source") or "")
            target = str(link.get("target") or "")
            citations.append({
                "id": f"graph-edge-{link.get('id')}",
                "type": "graph",
                "graphKind": "edge",
                "graphId": str(link.get("id") or ""),
                "label": f"{source} · {relation} · {target}",
                "preview": " ".join(str(link.get("context") or "").split())[:180],
                "sourceBlocks": link.get("evidence_blocks") or [],
                "entityTerms": [source, target],
                "relationTerms": [relation],
            })
        return citations

    async def submit(self, item: RAGRequest) -> JSONResponse:
        """Queue a non-streaming request and wait for its session worker."""
        self.require_ai_settings()
        if not item.filename:
            raise HTTPException(status_code=422, detail="filename 为必填项")

        item.filename = self.safe_filename(item.filename)
        session_id = self.initialize_session(item.session_id)
        item.session_id = session_id
        completion = asyncio.get_running_loop().create_future()
        self.message_queues[session_id].append(PendingRAGRequest(item, completion))

        if self.session_responses[session_id]["status"] == "idle":
            asyncio.create_task(self.process_session_queue(session_id))
        self.session_responses[session_id]["status"] = "processing"

        try:
            return JSONResponse({"result": await completion})
        except Exception as exc:
            self.logger.exception(
                "处理知识图谱查询失败: session_id=%s", session_id
            )
            return JSONResponse(status_code=500, content={"error": str(exc)})

    async def stream(self, item: RAGRequest) -> StreamingResponse:
        """Run one RAG request and return status, text and citations as SSE."""
        self.require_ai_settings()
        if not item.filename:
            raise HTTPException(status_code=422, detail="filename 为必填项")

        item.filename = self.safe_filename(item.filename)
        item.session_id = self.initialize_session(item.session_id)
        request_id = str(uuid.uuid4())

        async def stream_generator() -> AsyncGenerator[str, None]:
            try:
                loop = asyncio.get_running_loop()
                document_name = self.base_name(item.filename or "")
                lock = self.document_locks.setdefault(
                    document_name, asyncio.Lock()
                )

                async with lock:
                    self.logger.info(
                        "开始流式知识图谱查询: filename=%s request_id=%s",
                        item.filename,
                        request_id,
                    )
                    yield self._event("status", request_id, content="开始处理")

                    manager = self._store_manager()
                    rag_entities = await loop.run_in_executor(
                        self.executor,
                        manager.text2entity,
                        item.request,
                        document_name,
                    ) or []
                    yield self._event("status", request_id, content="实体识别完成")

                    community_info = await loop.run_in_executor(
                        self.executor,
                        manager.community_louvain_G,
                        document_name,
                        rag_entities,
                        item.weight_threshold,
                        item.max_relations,
                    ) or []
                    yield self._event("status", request_id, content="社区检测完成")

                    retrieval = await loop.run_in_executor(
                        self.executor,
                        manager.select_vector_context,
                        item.request,
                        document_name,
                        item.top_k,
                    ) or {}
                    results = retrieval.get("documents") or []
                    citations = self.build_citations(
                        document_name, retrieval, rag_entities
                    )
                    yield self._event("status", request_id, content="生成中...")

                    response_stream = await loop.run_in_executor(
                        self.executor,
                        self.rag_agent.hybrid_rag_stream,
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
                        content = self.rag_agent.process_hybrid_rag_stream_chunk(
                            chunk
                        )
                        if content:
                            full_text += content
                            yield self._event(
                                "content",
                                request_id,
                                chunk=content,
                                full=full_text,
                            )

                    answer, material = self.rag_agent.extract_material_from_text(
                        full_text
                    )
                    yield self._event(
                        "final",
                        request_id,
                        answer=answer,
                        material=material,
                        citations=citations,
                    )
            except Exception as exc:
                self.logger.exception(
                    "流式知识图谱查询失败: request_id=%s", request_id
                )
                yield self._event("error", request_id, content=str(exc))
            finally:
                yield self._event("done", request_id)

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def process_session_queue(self, session_id: str) -> None:
        """Run queued requests sequentially so one conversation stays ordered."""
        loop = asyncio.get_running_loop()
        try:
            while self.message_queues.get(session_id):
                pending = self.message_queues[session_id].popleft()
                item = pending.request
                document_name = self.base_name(item.filename or "")
                lock = self.document_locks.setdefault(
                    document_name, asyncio.Lock()
                )

                try:
                    async with lock:
                        self.logger.info(
                            "开始处理知识图谱查询: filename=%s session_id=%s",
                            item.filename,
                            session_id,
                        )
                        manager = self._store_manager()
                        rag_entities = await loop.run_in_executor(
                            self.executor,
                            manager.text2entity,
                            item.request,
                            document_name,
                        )
                        community_info = await loop.run_in_executor(
                            self.executor,
                            manager.community_louvain_G,
                            document_name,
                            rag_entities,
                            item.weight_threshold,
                            item.max_relations,
                        )
                        retrieval = await loop.run_in_executor(
                            self.executor,
                            manager.select_vector_context,
                            item.request,
                            document_name,
                            item.top_k,
                        ) or {}
                        result = await loop.run_in_executor(
                            self.executor,
                            self.rag_agent.hybrid_rag,
                            item.request,
                            community_info,
                            retrieval.get("documents") or [],
                            item.messages,
                            item.flow,
                        )

                    if not result or result == -1:
                        raise RuntimeError("生成回答失败")
                    response_data = {
                        "answer": result.get("answer", ""),
                        "material": result.get("material", ""),
                        "citations": self.build_citations(
                            document_name, retrieval, rag_entities
                        ),
                    }
                    if not pending.completion.done():
                        pending.completion.set_result(response_data)
                except Exception as exc:
                    self.logger.exception(
                        "处理队列中的知识图谱查询失败: session_id=%s",
                        session_id,
                    )
                    if not pending.completion.done():
                        pending.completion.set_exception(exc)

            if session_id in self.session_responses:
                self.session_responses[session_id]["status"] = "idle"
        except Exception:
            self.logger.exception("处理会话队列失败: session_id=%s", session_id)
            if session_id in self.session_responses:
                self.session_responses[session_id]["status"] = "error"

    def session_status(self, session_id: str) -> Dict[str, object] | JSONResponse:
        """Return queue length and current state for a known session."""
        if session_id not in self.session_responses:
            return JSONResponse(status_code=404, content={"error": "会话不存在"})
        return {
            "status": self.session_responses[session_id]["status"],
            "queue_length": len(self.message_queues.get(session_id, deque())),
        }

    def delete_session(self, session_id: str) -> Dict[str, str]:
        """Remove an idle session and its queued state."""
        if self.session_responses.get(session_id, {}).get("status") == "processing":
            raise HTTPException(status_code=409, detail="会话仍在处理中，暂不能删除")
        self.message_queues.pop(session_id, None)
        self.session_responses.pop(session_id, None)
        return {"message": f"会话 {session_id} 已清除"}

    def _store_manager(self) -> storeManager:
        return storeManager(store=self.vector_store, agent=self.kg_agent)

    @staticmethod
    def _event(event_type: str, request_id: str, **payload: Any) -> str:
        data = {"type": event_type, **payload, "request_id": request_id}
        return "data: " + json.dumps(data) + "\n\n"


def create_rag_router(service: RAGService) -> APIRouter:
    """Create API routes backed by one shared RAG service instance."""
    router = APIRouter()

    @router.post("/create_session")
    async def create_session() -> Dict[str, str]:
        return {"session_id": service.initialize_session()}

    @router.post("/hybridrag")
    async def hybridrag(item: RAGRequest) -> JSONResponse:
        return await service.submit(item)

    @router.post("/hybridrag/stream")
    async def hybridrag_stream(item: RAGRequest) -> StreamingResponse:
        return await service.stream(item)

    @router.get("/session_status/{session_id}", response_model=None)
    async def get_session_status(session_id: str) -> Any:
        return service.session_status(session_id)

    @router.delete("/session/{session_id}")
    async def delete_session(session_id: str) -> Dict[str, str]:
        return service.delete_session(session_id)

    return router
