"""Build a bundled example package from an existing local completed file."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from transfer_package import build_transfer_package  # noqa: E402


def load_state(database_path: Path, base_name: str) -> dict:
    """Read one Chroma metadata record without loading embedding models."""
    connection = sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro",
        uri=True,
    )
    try:
        rows = connection.execute(
            """
            SELECT metadata.key, metadata.string_value
            FROM embeddings
            JOIN segments ON segments.id = embeddings.segment_id
            JOIN collections ON collections.id = segments.collection
            JOIN embedding_metadata AS metadata ON metadata.id = embeddings.id
            WHERE collections.name = 'kg_states'
              AND embeddings.embedding_id = ?
            """,
            (base_name,),
        ).fetchall()
    finally:
        connection.close()

    metadata = {key: value for key, value in rows}
    required = {
        "file",
        "kg_triplet",
        "bidirectional_mapping",
        "current_G",
        "Bolts",
        "original_file_type",
    }
    missing = required.difference(metadata)
    if missing:
        raise RuntimeError(f"Chroma 状态不完整，缺少: {', '.join(sorted(missing))}")

    return {
        "file": metadata["file"],
        "kg_triplet": json.loads(metadata["kg_triplet"]),
        "bidirectional_mapping": json.loads(metadata["bidirectional_mapping"]),
        "current_G": json.loads(metadata["current_G"]),
        "Bolts": json.loads(metadata["Bolts"]),
        "original_file_type": metadata["original_file_type"],
    }


def build_example(base_name: str, output_path: Path) -> None:
    state = load_state(BACKEND_ROOT / "chroma_data" / "chroma.sqlite3", base_name)
    original_filename = state["original_file_type"]
    status = json.loads(
        (BACKEND_ROOT / "processing_states" / f"{base_name}.json").read_text(
            encoding="utf-8"
        )
    )
    graph_folder = BACKEND_ROOT / "results" / base_name
    graph_pages = {
        page.name: page.read_bytes()
        for page in sorted(graph_folder.glob("*.html"))
    }
    payload = build_transfer_package(
        base_name=base_name,
        original_filename=original_filename,
        state=state,
        processing_status=status,
        original_content=(BACKEND_ROOT / "uploads" / original_filename).read_bytes(),
        source_text=(BACKEND_ROOT / "txt_files" / f"{base_name}.source.txt").read_text(
            encoding="utf-8"
        ),
        processed_text=(BACKEND_ROOT / "txt_files" / f"{base_name}.txt").read_text(
            encoding="utf-8"
        ),
        graph_pages=graph_pages,
        # Personal conversations are intentionally excluded from a public example.
        rag_history=None,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    try:
        display_path = output_path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        display_path = output_path.resolve()
    print(f"已生成 {display_path} ({len(payload):,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_name", nargs="?", default="本软件使用说明")
    parser.add_argument(
        "--output",
        type=Path,
        help="输出路径，默认写入 backend/default_examples/<文件名>.kmn.zip",
    )
    args = parser.parse_args()
    output = args.output or (
        BACKEND_ROOT / "default_examples" / f"{args.base_name}.kmn.zip"
    )
    build_example(args.base_name, output)


if __name__ == "__main__":
    main()
