"""Persistent multi-stage progress tracking for file processing jobs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional


STAGE_CONFIG = {
    "entity_extraction": {"unit": "文本块"},
    "relationship_extraction": {"unit": "文本块"},
    "knowledge_fusion": {"unit": "实体对"},
}


class ProcessingProgressStore:
    """Thread-safe in-memory state with atomic JSON recovery snapshots."""

    def __init__(self, status_folder: Path):
        self.status_folder = status_folder
        self.statuses: dict[str, dict[str, Any]] = {}
        self.lock = Lock()

    def persist(self, base_name: str, status: dict[str, Any]) -> None:
        path = self.status_folder / f"{base_name}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def set(self, base_name: str, status: str, **updates: Any) -> None:
        with self.lock:
            next_status = {
                **self.statuses.get(base_name, {}),
                **updates,
                "status": status,
                "updated_at": time.time(),
            }
            self.statuses[base_name] = next_status
            self.persist(base_name, next_status)

    def get(self, base_name: str) -> Optional[dict[str, Any]]:
        with self.lock:
            status = self.statuses.get(base_name)
            return status.copy() if status else None

    @staticmethod
    def new_stage(
        stage: str,
        completed: int = 0,
        total: int = 0,
        total_known: bool = False,
        previous: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        previous = previous or {}
        completed = max(0, int(completed or 0))
        total = max(0, int(total or 0))
        if total_known:
            completed = min(completed, total)
        cumulative = max(0.0, float(previous.get("cumulative_seconds") or 0))
        samples = max(0, int(previous.get("sample_count") or 0))
        average = cumulative / samples if samples else None
        percentage = (
            100.0 if total_known and total == 0
            else completed * 100.0 / total if total_known and total else 0.0
        )
        return {
            "completed": completed,
            "total": total,
            "remaining": max(total - completed, 0) if total_known else None,
            "percentage": round(percentage, 1),
            "latest_item_seconds": previous.get("latest_item_seconds"),
            "average_item_seconds": round(average, 2) if average is not None else None,
            "cumulative_seconds": round(cumulative, 3),
            "sample_count": samples,
            "items_per_minute": round(samples * 60 / cumulative, 2)
            if cumulative > 0 and samples else None,
            "estimated_remaining_seconds": round(max(total - completed, 0) * average)
            if average is not None and total_known else None,
            "unit": STAGE_CONFIG[stage]["unit"],
            "total_known": bool(total_known),
        }

    @staticmethod
    def overall(stage_progress: dict[str, dict[str, Any]]) -> dict[str, Any]:
        stages = [stage_progress[key] for key in STAGE_CONFIG]
        percentage = sum(float(stage.get("percentage") or 0) for stage in stages) / len(stages)
        cumulative = sum(float(stage.get("cumulative_seconds") or 0) for stage in stages)
        averages = [float(stage["average_item_seconds"]) for stage in stages
                    if stage.get("average_item_seconds") is not None]
        fallback = sum(averages) / len(averages) if averages else None
        remaining_seconds = 0.0
        eta_known = True
        for stage in stages:
            if not stage.get("total_known"):
                eta_known = False
                break
            remaining = int(stage.get("remaining") or 0)
            if not remaining:
                continue
            average = stage.get("average_item_seconds") or fallback
            if average is None:
                eta_known = False
                break
            remaining_seconds += remaining * float(average)
        return {
            "overall_percentage": round(percentage, 1),
            "overall_speed_percent_per_minute": round(percentage * 60 / cumulative, 2)
            if cumulative > 0 and percentage > 0 else None,
            "estimated_total_remaining_seconds": max(0, round(remaining_seconds))
            if eta_known else None,
        }

    def initialize(
        self,
        base_name: str,
        status: str,
        total_chunks: Optional[int],
        completed_chunks: int = 0,
        preserve_timings: bool = False,
    ) -> None:
        current = self.get(base_name) or {}
        previous = current.get("stage_progress") or {} if preserve_timings else {}
        total_known = total_chunks is not None
        total = int(total_chunks or 0)
        stages = {
            "entity_extraction": self.new_stage(
                "entity_extraction", completed_chunks, total, total_known,
                previous.get("entity_extraction"),
            ),
            "relationship_extraction": self.new_stage(
                "relationship_extraction", completed_chunks, total, total_known,
                previous.get("relationship_extraction"),
            ),
            "knowledge_fusion": self.new_stage(
                "knowledge_fusion", 0, 0, False, previous.get("knowledge_fusion"),
            ),
        }
        overall = self.overall(stages)
        self.set(
            base_name,
            status,
            completed_chunks=completed_chunks,
            total_chunks=total,
            stage_progress=stages,
            processing_stage="entity_extraction",
            percentage=overall["overall_percentage"],
            **overall,
            estimated_remaining_seconds=overall["estimated_total_remaining_seconds"],
        )

    def stage_callback(self, base_name: str, status: str = "processing"):
        def update(stage: str, completed: int, total: int, item_seconds: float) -> None:
            if stage not in STAGE_CONFIG:
                raise ValueError(f"未知文件处理阶段: {stage}")
            current = self.get(base_name) or {}
            stages = {
                key: dict((current.get("stage_progress") or {}).get(key) or self.new_stage(key))
                for key in STAGE_CONFIG
            }
            previous = stages[stage]
            completed_value = max(0, min(int(completed or 0), max(int(total or 0), 0)))
            total_value = max(0, int(total or 0))
            seconds = max(0.0, float(item_seconds or 0))
            if stage == "entity_extraction" and not stages["relationship_extraction"].get("total_known"):
                stages["relationship_extraction"] = self.new_stage(
                    "relationship_extraction", max(completed_value - 1, 0),
                    total_value, True, stages["relationship_extraction"],
                )
            cumulative = float(previous.get("cumulative_seconds") or 0)
            samples = int(previous.get("sample_count") or 0)
            if seconds > 0 and completed_value > int(previous.get("completed") or 0):
                cumulative += seconds
                samples += 1
            average = cumulative / samples if samples else None
            remaining = max(total_value - completed_value, 0)
            stages[stage] = {
                "completed": completed_value,
                "total": total_value,
                "remaining": remaining,
                "percentage": round(completed_value * 100 / total_value, 1) if total_value else 100.0,
                "latest_item_seconds": round(seconds, 2) if seconds > 0 else previous.get("latest_item_seconds"),
                "average_item_seconds": round(average, 2) if average is not None else None,
                "cumulative_seconds": round(cumulative, 3),
                "sample_count": samples,
                "items_per_minute": round(samples * 60 / cumulative, 2)
                if cumulative > 0 and samples else None,
                "estimated_remaining_seconds": round(remaining * average)
                if average is not None else (0 if remaining == 0 else None),
                "unit": STAGE_CONFIG[stage]["unit"],
                "total_known": True,
            }
            overall = self.overall(stages)
            effective_status = "pausing" if current.get("pause_requested") else status
            updates = {
                "stage_progress": stages,
                "processing_stage": stage,
                "percentage": overall["overall_percentage"],
                **overall,
                "estimated_remaining_seconds": overall["estimated_total_remaining_seconds"],
            }
            if stage == "relationship_extraction":
                updates.update({
                    "completed_chunks": completed_value,
                    "total_chunks": total_value,
                    "latest_chunk_seconds": round(seconds, 2) if seconds > 0 else None,
                })
            self.set(base_name, effective_status, **updates)
        return update

    def fusion_callback(self, base_name: str, status: str = "processing"):
        callback = self.stage_callback(base_name, status)

        def update(completed: int, total: int, item_seconds: float) -> None:
            callback("knowledge_fusion", completed, total, item_seconds)

        return update

    def restore(
        self,
        upload_folder: Path,
        text_folder: Path,
        result_folder: Path,
    ) -> list[Path]:
        """Restore persisted statuses and mark abandoned jobs as interrupted."""
        damaged: list[Path] = []
        active = {"uploading", "importing", "processing", "updating", "resuming", "pausing"}
        for status_path in self.status_folder.glob("*.json"):
            try:
                restored = json.loads(status_path.read_text(encoding="utf-8"))
                base_name = status_path.stem
                if restored.get("status") == "redrawing":
                    has_graph = (result_folder / base_name / f"{base_name}.html").is_file()
                    restored["status"] = "completed" if has_graph else "error"
                    restored["error_message"] = (
                        "重新绘制被服务中断，已保留原图" if has_graph
                        else "重新绘制被服务中断，图谱页面不存在"
                    )
                    restored["pause_requested"] = False
                    self.persist(base_name, restored)
                elif restored.get("status") in active:
                    completed = int(restored.get("completed_chunks") or 0)
                    was_pausing = restored.get("status") == "pausing" or restored.get("pause_requested")
                    restored["status"] = "paused" if was_pausing else ("interrupted" if completed else "error")
                    restored["error_message"] = None if was_pausing else "服务中断，等待继续处理"
                    restored["pause_requested"] = False
                    source = Path(
                        restored.get("source_text_path")
                        or text_folder / f"{base_name}.source.txt"
                    )
                    filename = restored.get("original_filename")
                    restored["resumable"] = source.is_file() or bool(
                        filename and (upload_folder / filename).is_file()
                    )
                    self.persist(base_name, restored)
                self.statuses[base_name] = restored
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                damaged.append(status_path)
        return damaged
