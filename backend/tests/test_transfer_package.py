import io
import json
import unittest
import zipfile
from pathlib import Path

import networkx as nx

from transfer_package import build_transfer_package, read_transfer_package


class TransferPackageTests(unittest.TestCase):
    def build_package(self):
        graph = nx.DiGraph()
        graph.add_node("刘备", group="人物")
        graph.add_node("蜀汉", group="政权")
        graph.add_edge("刘备", "蜀汉", label="建立", weight=0.8)
        return build_transfer_package(
            base_name="三国",
            original_filename="三国.txt",
            state={
                "file": "三国",
                "kg_triplet": [{"bid": "b1", "relation": []}],
                "bidirectional_mapping": {
                    "entity_to_label": {"刘备": "人物"},
                    "label_to_entities": {"人物": ["刘备"]},
                },
                "current_G": graph,
                "Bolts": [["b1", "原文内容"]],
                "original_file_type": "三国.txt",
            },
            processing_status={"status": "completed", "total_chunks": 1},
            original_content="原始文档".encode(),
            source_text="原文内容",
            processed_text="原文内容",
            graph_pages={"三国.html": b"<html>graph</html>"},
            rag_history=[{"role": "user", "content": "问题"}],
        )

    def test_round_trip_contains_original_graph_and_state(self):
        imported = read_transfer_package(self.build_package())

        self.assertEqual(imported.base_name, "三国")
        self.assertEqual(imported.original_content.decode(), "原始文档")
        self.assertEqual(imported.source_text, "原文内容")
        self.assertIn("三国.html", imported.graph_pages)
        restored_graph = nx.node_link_graph(imported.state["current_G"])
        self.assertTrue(restored_graph.has_edge("刘备", "蜀汉"))
        self.assertEqual(imported.rag_history[0]["content"], "问题")

    def test_rejects_unsafe_zip_member(self):
        source = zipfile.ZipFile(io.BytesIO(self.build_package()))
        output = io.BytesIO()
        with source, zipfile.ZipFile(output, "w") as archive:
            for info in source.infolist():
                archive.writestr(info.filename, source.read(info.filename))
            archive.writestr("../outside.txt", "unsafe")

        with self.assertRaisesRegex(ValueError, "不安全路径"):
            read_transfer_package(output.getvalue())

    def test_manifest_is_user_readable(self):
        with zipfile.ZipFile(io.BytesIO(self.build_package())) as archive:
            manifest = json.loads(archive.read("manifest.json"))

        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["files"]["original"], "original/三国.txt")
        self.assertEqual(manifest["files"]["graph_pages"], ["graph/三国.html"])

    def test_bundled_three_kingdoms_example_is_complete(self):
        package_path = (
            Path(__file__).resolve().parents[1]
            / "default_examples"
            / "三国志.kmn.zip"
        )
        self.assertTrue(package_path.is_file())

        imported = read_transfer_package(package_path.read_bytes())
        self.assertEqual(imported.base_name, "三国志")
        self.assertEqual(imported.original_filename, "三国志.txt")
        self.assertEqual(imported.processing_status.get("status"), "completed")
        self.assertGreater(len(imported.state["Bolts"]), 0)
        self.assertIn("三国志.html", imported.graph_pages)


if __name__ == "__main__":
    unittest.main()
