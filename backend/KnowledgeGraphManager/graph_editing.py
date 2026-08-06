"""Validated, versioned mutations for the PyVis graph editor.

The legacy PyVis renderer still consumes the same KgManager state.  This module
only adds a small edit protocol around that state; it never reads or writes the
generated HTML pages.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from transfer_package import graph_from_node_link_data, graph_to_node_link_data


MANUAL_BID = "__manual_graph_edits__"
HISTORY_SCHEMA = 1
HISTORY_OPERATION_LABELS = {
    "add_node": "新增节点",
    "update_node": "修改节点",
    "delete_node": "删除节点",
    "add_edge": "新增关系",
    "update_edge": "修改关系",
    "delete_edge": "删除关系",
    "redraw_graph": "重新绘制图谱",
}


def describe_history_operation(operation: str) -> str:
    """Convert internal operation names into labels suitable for the UI."""
    operation = str(operation or "")
    if operation.startswith("before:"):
        return f"修改前快照：{describe_history_operation(operation[7:])}"
    if operation.startswith("restore:"):
        return f"从历史版本 {operation[8:]} 还原"
    return HISTORY_OPERATION_LABELS.get(operation, "图谱修改")


class GraphEditError(ValueError):
    """A user mutation failed validation."""


def _mapping(state: Dict[str, Any]) -> Dict[str, Any]:
    mapping = state.setdefault("bidirectional_mapping", {})
    mapping.setdefault("entity_to_label", {})
    mapping.setdefault("label_to_entities", {})
    return mapping


def _blocks(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    blocks = state.setdefault("kg_triplet", [])
    return [block for block in blocks if isinstance(block, dict)]


def _iter_edges(state: Dict[str, Any]) -> Iterable[tuple[Dict[str, Any], int, Dict[str, Any]]]:
    for block in _blocks(state):
        relations = block.get("relation") or []
        if not isinstance(relations, list):
            continue
        for index, relation in enumerate(relations):
            if isinstance(relation, dict):
                yield block, index, relation


def _edge_id(block: Mapping[str, Any], index: int, relation: Mapping[str, Any]) -> str:
    explicit = relation.get("edit_id")
    if explicit:
        return str(explicit)
    raw = json.dumps(
        {
            "bid": block.get("bid"),
            "index": index,
            "source": relation.get("source"),
            "target": relation.get("target"),
            "relation": relation.get("relation"),
            "context": relation.get("context"),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return "edge-" + hashlib.sha1(raw).hexdigest()[:20]


def _new_id(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"{prefix}-" + hashlib.sha1(raw).hexdigest()[:20]


def _require_text(value: Any, field: str, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphEditError(f"{field}不能为空")
    value = value.strip()
    if len(value) > max_length:
        raise GraphEditError(f"{field}长度不能超过{max_length}个字符")
    return value


def _find_edge(state: Dict[str, Any], edge_id: str) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
    for block, index, relation in _iter_edges(state):
        if _edge_id(block, index, relation) == edge_id:
            return block, index, relation
    raise GraphEditError("关系不存在，可能已被其他操作修改")


def _set_label(mapping: Dict[str, Any], name: str, label: str) -> None:
    entities = mapping["label_to_entities"]
    old_label = mapping["entity_to_label"].get(name)
    if old_label and old_label in entities:
        entities[old_label] = [item for item in entities[old_label] if item != name]
    mapping["entity_to_label"][name] = label
    entities.setdefault(label, [])
    if name not in entities[label]:
        entities[label].append(name)


def _remove_label(mapping: Dict[str, Any], name: str) -> None:
    old_label = mapping["entity_to_label"].pop(name, None)
    if old_label in mapping["label_to_entities"]:
        mapping["label_to_entities"][old_label] = [
            item for item in mapping["label_to_entities"][old_label] if item != name
        ]


def apply_graph_mutation(state: Dict[str, Any], mutation: Mapping[str, Any]) -> str:
    """Apply one validated mutation in memory and return its operation name."""
    operation = _require_text(mutation.get("operation"), "operation", 40)
    mapping = _mapping(state)
    entity_to_label = mapping["entity_to_label"]

    if operation == "add_node":
        name = _require_text(mutation.get("name"), "节点名称")
        if name in entity_to_label:
            raise GraphEditError("节点已存在")
        label = _require_text(mutation.get("entity_type") or "未知标签", "节点类型", 100)
        _set_label(mapping, name, label)
        return operation

    if operation == "update_node":
        old_name = _require_text(mutation.get("node_id"), "节点")
        if old_name not in entity_to_label:
            raise GraphEditError("节点不存在")
        new_name = _require_text(mutation.get("name") or old_name, "节点名称")
        if new_name != old_name and new_name in entity_to_label:
            raise GraphEditError("修改后的节点名称已存在")
        label = _require_text(
            mutation.get("entity_type") or entity_to_label[old_name], "节点类型", 100
        )
        if new_name != old_name:
            old_label = entity_to_label[old_name]
            _remove_label(mapping, old_name)
            _set_label(mapping, new_name, label)
            for block, _, relation in _iter_edges(state):
                if relation.get("source") == old_name:
                    relation["source"] = new_name
                if relation.get("target") == old_name:
                    relation["target"] = new_name
            del old_label
        else:
            _set_label(mapping, old_name, label)
        return operation

    if operation == "delete_node":
        name = _require_text(mutation.get("node_id"), "节点")
        if name not in entity_to_label:
            raise GraphEditError("节点不存在")
        _remove_label(mapping, name)
        for block in _blocks(state):
            relations = block.get("relation") or []
            block["relation"] = [
                relation for relation in relations
                if relation.get("source") != name and relation.get("target") != name
            ]
        return operation

    if operation == "add_edge":
        source = _require_text(mutation.get("source"), "起点节点")
        target = _require_text(mutation.get("target"), "终点节点")
        if source not in entity_to_label or target not in entity_to_label:
            raise GraphEditError("起点和终点节点必须已存在")
        relation_text = _require_text(mutation.get("relation"), "关系名称", 200)
        context = _require_text(mutation.get("context") or relation_text, "关系说明", 5000)
        try:
            weight = float(mutation.get("weight", 0.5))
        except (TypeError, ValueError) as exc:
            raise GraphEditError("关系权重必须是数字") from exc
        if not 0 <= weight <= 1:
            raise GraphEditError("关系权重必须在0到1之间")
        manual = next((block for block in _blocks(state) if block.get("bid") == MANUAL_BID), None)
        if manual is None:
            manual = {"bid": MANUAL_BID, "relation": []}
            state.setdefault("kg_triplet", []).append(manual)
        manual.setdefault("relation", []).append({
            "source": source,
            "target": target,
            "relation": relation_text,
            "context": context,
            "weight": weight,
            "origin": "manual",
            "edit_id": _new_id("edge", {
                "source": source, "target": target, "relation": relation_text,
                "context": context, "count": len(manual["relation"]),
            }),
        })
        return operation

    if operation in {"update_edge", "delete_edge"}:
        edge_id = _require_text(mutation.get("edge_id"), "关系", 100)
        block, index, relation = _find_edge(state, edge_id)
        if operation == "delete_edge":
            block["relation"].pop(index)
            return operation
        source = _require_text(mutation.get("source") or relation.get("source"), "起点节点")
        target = _require_text(mutation.get("target") or relation.get("target"), "终点节点")
        if source not in entity_to_label or target not in entity_to_label:
            raise GraphEditError("起点和终点节点必须已存在")
        relation["source"] = source
        relation["target"] = target
        relation["relation"] = _require_text(
            mutation.get("relation") or relation.get("relation"), "关系名称", 200
        )
        relation["context"] = _require_text(
            mutation.get("context") or relation.get("context"), "关系说明", 5000
        )
        try:
            relation["weight"] = float(mutation.get("weight", relation.get("weight", 0.5)))
        except (TypeError, ValueError) as exc:
            raise GraphEditError("关系权重必须是数字") from exc
        if not 0 <= relation["weight"] <= 1:
            raise GraphEditError("关系权重必须在0到1之间")
        # Preserve the identifier even when an extracted relation's contents
        # change; the next browser request can continue to address this edge.
        relation["edit_id"] = edge_id
        return operation

    raise GraphEditError(f"不支持的图谱操作: {operation}")


def state_snapshot(state: Mapping[str, Any]) -> Dict[str, Any]:
    graph = state.get("current_G")
    graph_data = graph_to_node_link_data(graph) if hasattr(graph, "nodes") else graph
    mapping = state.get("bidirectional_mapping") or {}
    snapshot = {
        "schema": HISTORY_SCHEMA,
        "file": state.get("file"),
        "kg_triplet": copy.deepcopy(state.get("kg_triplet") or []),
        "bidirectional_mapping": {
            "entity_to_label": dict(mapping.get("entity_to_label") or {}),
            "label_to_entities": {
                key: list(value) for key, value in (mapping.get("label_to_entities") or {}).items()
            },
        },
        "current_G": graph_data,
        "Bolts": copy.deepcopy(state.get("Bolts") or []),
        "original_file_type": state.get("original_file_type"),
    }
    # Document content is optional for backwards compatibility with older
    # graph history files. New combined snapshots carry both graph and source
    # document state so either side can be restored atomically.
    if "document" in state:
        snapshot["document"] = copy.deepcopy(state.get("document"))
    return snapshot


def state_from_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    restored = copy.deepcopy(dict(snapshot))
    restored["current_G"] = graph_from_node_link_data(restored["current_G"])
    return restored


def graph_payload(state: Mapping[str, Any], revision: int = 0) -> Dict[str, Any]:
    mapping = state.get("bidirectional_mapping") or {}
    labels = mapping.get("entity_to_label") or {}
    edge_items = list(_iter_edges(dict(state)))
    node_blocks: dict[str, list[str]] = defaultdict(list)
    edge_blocks: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for block, index, relation in edge_items:
        source = relation.get("source")
        target = relation.get("target")
        if not source or not target:
            continue
        bid = str(block.get("bid", ""))
        for node in (source, target):
            if bid and bid not in node_blocks[node]:
                node_blocks[node].append(bid)
        group_key = "|".join([
            str(source), str(target), str(relation.get("relation", "")),
        ])
        occurrence = {
            "source_block": bid,
            "evidence": relation.get("context", ""),
            "score": relation.get("weight", 0.5),
            "edge_id": _edge_id(block, index, relation),
        }
        if occurrence not in edge_blocks[group_key]:
            edge_blocks[group_key].append(occurrence)

    nodes = [{
        "id": name,
        "name": name,
        "entityType": label or "未知标签",
        "source_blocks": node_blocks.get(name, []),
    } for name, label in labels.items()]
    known = set(labels)
    links = []
    for block, index, relation in edge_items:
        source = relation.get("source")
        target = relation.get("target")
        if not source or not target:
            continue
        for endpoint in (source, target):
            if endpoint not in known:
                nodes.append({
                    "id": endpoint,
                    "name": endpoint,
                    "entityType": "未知标签",
                    "source_blocks": node_blocks.get(endpoint, []),
                })
                known.add(endpoint)
        links.append({
            "id": _edge_id(block, index, relation),
            "source": source,
            "target": target,
            "relation": relation.get("relation", ""),
            "context": relation.get("context", ""),
            "evidence": relation.get("context", ""),
            "source_block": block.get("bid", ""),
            "evidence_blocks": edge_blocks.get("|".join([
                str(source), str(target), str(relation.get("relation", "")),
            ]), []),
            "weight": relation.get("weight", 0.5),
            "score": relation.get("weight", 0.5),
            "origin": relation.get("origin", "extracted"),
        })
    return {"revision": revision, "nodes": nodes, "links": links}


class GraphHistory:
    """Small atomic JSON history store; independent of the legacy Chroma state."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, base_name: str) -> Path:
        return self.root / f"{base_name}.json"

    def _read(self, base_name: str) -> Dict[str, Any]:
        path = self._path(base_name)
        if not path.is_file():
            return {"schema": HISTORY_SCHEMA, "next_revision": 1, "versions": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphEditError("图谱历史记录损坏，已停止修改") from exc
        if data.get("schema") != HISTORY_SCHEMA:
            raise GraphEditError("不支持的图谱历史记录版本")
        return data

    def _write(self, base_name: str, data: Dict[str, Any]) -> None:
        path = self._path(base_name)
        fd, temporary = tempfile.mkstemp(prefix=f".{base_name}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def commit(self, base_name: str, before: Mapping[str, Any], after: Mapping[str, Any], operation: str) -> int:
        data = self._read(base_name)
        next_revision = int(data.get("next_revision") or 1)
        before_revision = next_revision
        after_revision = next_revision + 1
        now = datetime.now(timezone.utc).isoformat()
        data["versions"].append({
            "revision": before_revision,
            "operation": f"before:{operation}",
            "created_at": now,
            "snapshot": state_snapshot(before),
        })
        data["versions"].append({
            "revision": after_revision,
            "operation": operation,
            "created_at": now,
            "snapshot": state_snapshot(after),
        })
        data["next_revision"] = after_revision + 1
        self._write(base_name, data)
        return after_revision

    def commit_snapshot(self, base_name: str, state: Mapping[str, Any], operation: str) -> int:
        """Persist one recoverable state before an operation changes presentation."""
        data = self._read(base_name)
        revision = int(data.get("next_revision") or 1)
        data["versions"].append({
            "revision": revision,
            "operation": f"before:{operation}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": state_snapshot(state),
        })
        data["next_revision"] = revision + 1
        self._write(base_name, data)
        return revision

    def list_versions(self, base_name: str) -> list[Dict[str, Any]]:
        return [
            {
                **{key: value for key, value in item.items() if key != "snapshot"},
                "description": describe_history_operation(item.get("operation", "")),
            }
            for item in self._read(base_name).get("versions", [])
        ]

    def get_version(self, base_name: str, revision: int) -> Dict[str, Any] | None:
        for item in self._read(base_name).get("versions", []):
            if int(item.get("revision", -1)) == revision:
                return state_from_snapshot(item["snapshot"])
        return None
