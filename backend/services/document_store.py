"""Document drafts, rich previews, and revision history persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class DocumentStore:
    """Keep document file paths and revision serialization in one service."""

    def __init__(self, text_folder: Path, history_folder: Path, logger: logging.Logger):
        self.text_folder = text_folder
        self.history_folder = history_folder
        self.logger = logger

    def source_path(self, base_name: str) -> Path:
        return self.text_folder / f"{base_name}.source.txt"

    def draft_path(self, base_name: str) -> Path:
        return self.text_folder / f"{base_name}.draft.txt"

    def rich_path(self, base_name: str) -> Path:
        return self.text_folder / f"{base_name}.rich.html"

    def history_path(self, base_name: str) -> Path:
        return self.history_folder / f"{base_name}.document.json"

    def read_history(self, base_name: str) -> dict[str, Any]:
        path = self.history_path(base_name)
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
            self.logger.warning("读取文档历史失败，将创建新历史: %s", exc)
            return {"schema": 1, "next_revision": 1, "versions": []}

    def write_history(self, base_name: str, data: dict[str, Any]) -> None:
        path = self.history_path(base_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".document.json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def snapshot(
        self,
        base_name: str,
        content: Optional[str] = None,
        rich_content: Optional[str] = None,
    ) -> dict[str, Any]:
        draft_path = self.draft_path(base_name)
        if content is None:
            content_path = draft_path
            if not content_path.is_file():
                content_path = self.text_folder / f"{base_name}.txt"
            content = content_path.read_text(encoding="utf-8") if content_path.is_file() else ""
        if rich_content is None:
            rich_path = self.rich_path(base_name)
            rich_content = rich_path.read_text(encoding="utf-8") if rich_path.is_file() else ""
        return {
            "content": str(content),
            "rich_content": str(rich_content or ""),
            "draft": draft_path.is_file(),
        }

    def restore_snapshot(self, base_name: str, snapshot: Optional[dict[str, Any]]) -> None:
        """Restore the document files represented by a combined graph snapshot."""
        if not snapshot:
            return
        content = str(snapshot.get("content") or "")
        rich_content = str(snapshot.get("rich_content") or "")
        if snapshot.get("draft"):
            self.draft_path(base_name).write_text(content, encoding="utf-8")
        else:
            (self.text_folder / f"{base_name}.txt").write_text(content, encoding="utf-8")
            self.source_path(base_name).write_text(content, encoding="utf-8")
            self.draft_path(base_name).unlink(missing_ok=True)
        if rich_content:
            self.rich_path(base_name).write_text(rich_content, encoding="utf-8")
        else:
            self.rich_path(base_name).unlink(missing_ok=True)

    def append_version(self, base_name: str, snapshot: dict[str, Any], operation: str) -> int:
        data = self.read_history(base_name)
        revision = int(data.get("next_revision") or 1)
        data["versions"].append({
            "revision": revision,
            "operation": operation,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **snapshot,
        })
        data["next_revision"] = revision + 1
        self.write_history(base_name, data)
        return revision

    @staticmethod
    def operation_label(operation: str) -> str:
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
