"""Portable export/import packages for completed knowledge graph files."""

from __future__ import annotations

import io
import inspect
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional

import networkx as nx


PACKAGE_SCHEMA = "knowledge-map-notes.transfer"
PACKAGE_VERSION = 1
PACKAGE_SUFFIX = ".kmn.zip"
MAX_PACKAGE_FILES = 2_000
MAX_UNCOMPRESSED_SIZE = 250 * 1024 * 1024


@dataclass(frozen=True)
class ImportedTransferPackage:
    base_name: str
    original_filename: str
    state: Dict[str, Any]
    processing_status: Dict[str, Any]
    original_content: bytes
    source_text: str
    processed_text: str
    graph_pages: Dict[str, bytes]
    rag_history: Optional[list]


def _node_link_edge_keyword(function: Any) -> str:
    """Return the edge-key keyword supported by this NetworkX version."""
    return "edges" if "edges" in inspect.signature(function).parameters else "link"


def graph_to_node_link_data(graph: nx.Graph) -> Dict[str, Any]:
    """Serialize a graph with an explicit, version-independent edge key."""
    keyword = _node_link_edge_keyword(nx.node_link_data)
    return nx.node_link_data(graph, **{keyword: "edges"})


def graph_from_node_link_data(data: Mapping[str, Any]) -> nx.Graph:
    """Restore NetworkX node-link data written with either edge key format."""
    if "edges" in data:
        edge_key = "edges"
    elif "links" in data:
        edge_key = "links"
    else:
        raise ValueError("图谱状态缺少 edges 或 links")

    # NetworkX renamed the keyword from ``link`` to ``edges``. Selecting it
    # explicitly also avoids relying on a default that changes in NetworkX 3.6.
    keyword = _node_link_edge_keyword(nx.node_link_graph)
    return nx.node_link_graph(data, **{keyword: edge_key})


def is_transfer_package_filename(filename: str) -> bool:
    return filename.lower().endswith(PACKAGE_SUFFIX)


def _safe_leaf_name(value: str, field: str) -> str:
    if not value or value != Path(value).name or "\\" in value or value in {".", ".."}:
        raise ValueError(f"{field}不合法")
    return value


def _safe_member_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("迁移包中包含不安全路径")
    return value


def _serialize_state(state: Mapping[str, Any]) -> Dict[str, Any]:
    graph = state.get("current_G")
    if graph is None:
        raise ValueError("图谱状态缺少 current_G")
    graph_data = graph_to_node_link_data(graph) if hasattr(graph, "nodes") else graph
    mapping = state.get("bidirectional_mapping") or {}
    return {
        "file": state.get("file"),
        "kg_triplet": state.get("kg_triplet") or [],
        "bidirectional_mapping": {
            "entity_to_label": dict(mapping.get("entity_to_label") or {}),
            "label_to_entities": dict(mapping.get("label_to_entities") or {}),
        },
        "current_G": graph_data,
        "Bolts": state.get("Bolts") or [],
        "original_file_type": state.get("original_file_type"),
        "community_min_size_mode": state.get("community_min_size_mode"),
        "community_min_size": state.get("community_min_size"),
        "community_auto_percent": state.get("community_auto_percent"),
    }


def build_transfer_package(
    *,
    base_name: str,
    original_filename: str,
    state: Mapping[str, Any],
    processing_status: Mapping[str, Any],
    original_content: bytes,
    source_text: str,
    processed_text: str,
    graph_pages: Mapping[str, bytes],
    rag_history: Optional[list] = None,
) -> bytes:
    """Build a user-readable ZIP that can also restore all server-side state."""
    base_name = _safe_leaf_name(base_name, "文件标识")
    original_filename = _safe_leaf_name(original_filename, "原始文件名")
    if not graph_pages:
        raise ValueError("图谱页面不存在")

    original_member = f"original/{original_filename}"
    graph_members = []
    for page_name in graph_pages:
        safe_page = _safe_leaf_name(page_name, "图谱页面名")
        if not safe_page.lower().endswith(".html"):
            raise ValueError("迁移包只允许包含 HTML 图谱页面")
        graph_members.append(f"graph/{safe_page}")

    manifest = {
        "schema": PACKAGE_SCHEMA,
        "version": PACKAGE_VERSION,
        "exported_at": time.time(),
        "base_name": base_name,
        "original_filename": original_filename,
        "files": {
            "original": original_member,
            "source_text": "text/source.txt",
            "processed_text": "text/processed.txt",
            "graph_pages": graph_members,
        },
        "state": _serialize_state(state),
        "processing_status": dict(processing_status),
        "rag_history": rag_history,
    }

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        archive.writestr(original_member, original_content)
        archive.writestr("text/source.txt", source_text.encode("utf-8"))
        archive.writestr("text/processed.txt", processed_text.encode("utf-8"))
        for page_name, content in graph_pages.items():
            archive.writestr(f"graph/{page_name}", content)
    return output.getvalue()


def read_transfer_package(payload: bytes) -> ImportedTransferPackage:
    """Validate and decode an uploaded package without extracting arbitrary paths."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("上传的文件不是有效的图谱迁移包") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_PACKAGE_FILES:
            raise ValueError("迁移包文件数量过多")
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_SIZE:
            raise ValueError("迁移包解压后过大")
        names = {info.filename for info in infos if not info.is_dir()}
        for name in names:
            _safe_member_name(name)
        if "manifest.json" not in names:
            raise ValueError("迁移包缺少 manifest.json")

        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise ValueError("迁移包清单损坏") from exc

        if manifest.get("schema") != PACKAGE_SCHEMA or manifest.get("version") != PACKAGE_VERSION:
            raise ValueError("不支持的图谱迁移包版本")

        base_name = _safe_leaf_name(str(manifest.get("base_name") or ""), "文件标识")
        original_filename = _safe_leaf_name(
            str(manifest.get("original_filename") or ""),
            "原始文件名",
        )
        files = manifest.get("files") or {}
        original_member = _safe_member_name(str(files.get("original") or ""))
        source_member = _safe_member_name(str(files.get("source_text") or ""))
        processed_member = _safe_member_name(str(files.get("processed_text") or ""))
        graph_members = files.get("graph_pages") or []
        if not isinstance(graph_members, list) or not all(
            isinstance(member, str) for member in graph_members
        ):
            raise ValueError("迁移包图谱页面清单损坏")
        required_members = {original_member, source_member, processed_member, *graph_members}
        if not required_members.issubset(names):
            raise ValueError("迁移包缺少原文或图谱文件")

        state = manifest.get("state")
        if not isinstance(state, dict) or not all(
            key in state
            for key in ("kg_triplet", "bidirectional_mapping", "current_G", "Bolts")
        ):
            raise ValueError("迁移包缺少可恢复的图谱状态")

        pages: Dict[str, bytes] = {}
        for member in graph_members:
            member = _safe_member_name(str(member))
            if not member.startswith("graph/"):
                raise ValueError("图谱页面路径不合法")
            page_name = _safe_leaf_name(PurePosixPath(member).name, "图谱页面名")
            if not page_name.lower().endswith(".html"):
                raise ValueError("图谱页面格式不合法")
            pages[page_name] = archive.read(member)
        if f"{base_name}.html" not in pages:
            raise ValueError("迁移包缺少图谱主页")

        try:
            source_text = archive.read(source_member).decode("utf-8")
            processed_text = archive.read(processed_member).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("迁移包文本编码损坏") from exc

        processing_status = manifest.get("processing_status") or {}
        rag_history = manifest.get("rag_history")
        if not isinstance(processing_status, dict):
            raise ValueError("迁移包处理状态损坏")
        if rag_history is not None and not isinstance(rag_history, list):
            raise ValueError("迁移包 RAG 历史损坏")

        return ImportedTransferPackage(
            base_name=base_name,
            original_filename=original_filename,
            state=state,
            processing_status=processing_status,
            original_content=archive.read(original_member),
            source_text=source_text,
            processed_text=processed_text,
            graph_pages=pages,
            rag_history=rag_history,
        )
