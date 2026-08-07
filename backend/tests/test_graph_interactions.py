import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import networkx as nx

from KnowledgeGraphManager.KGManager import KgManager
from KnowledgeGraphManager.graph_interactions import (
    build_graph_interaction_html,
    prepare_legacy_graph_html,
)


class GraphInteractionTests(unittest.TestCase):
    def test_legacy_graph_resources_are_inlined_for_delivery(self):
        legacy = """
        <html><head>
          <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.css">
          <script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"></script>
          <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head><body><script>var options = {"physics": {"stabilization": {"iterations": 300}}};</script>
        <div id="mynetwork"></div></body></html>
        """

        prepared = prepare_legacy_graph_html(legacy)

        self.assertNotIn("cdnjs.cloudflare.com", prepared)
        self.assertNotIn("cdn.jsdelivr.net/npm/bootstrap", prepared)
        self.assertIn("vis-network.min.js", prepared)
        self.assertIn("knowledge-graph-ready", prepared)
        self.assertIn('"iterations": 120', prepared)

        web_prepared = prepare_legacy_graph_html(
            legacy,
            asset_base_url="/api/graph-assets",
        )
        self.assertIn('/api/graph-assets/vis-network.min.js', web_prepared)
        self.assertNotIn("cdnjs.cloudflare.com", web_prepared)

    def test_interaction_template_contains_focus_and_collapsible_panels(self):
        html = build_graph_interaction_html(12, 18)

        self.assertIn("entityTypeOptions", html)
        self.assertIn("activeEntityTypes", html)
        self.assertIn("graph-panel-collapse", html)
        self.assertIn("沉浸模式", html)
        self.assertIn("knowledge-graph-ready", html)
        self.assertIn("network.once('stabilized'", html)
        self.assertIn("const NODE_COUNT = 12;", html)
        self.assertIn("const EDGE_COUNT = 18;", html)
        self.assertIn("graph-context-menu", html)
        self.assertIn("data-action=\"edit-node\"", html)
        self.assertIn("data-action=\"edit-edge\"", html)
        self.assertIn("network.on('oncontext'", html)
        self.assertIn("graphContainer.addEventListener('contextmenu'", html)
        self.assertIn("右键节点、关系或空白处", html)
        self.assertIn("const GRAPH_EDITOR_VERSION = 3;", html)
        self.assertIn("knowledge-graph-evidence", html)
        self.assertIn("出处文本块（只读）", html)
        self.assertIn("function showNodeDialog", html)
        self.assertIn("原文查找", html)
        self.assertIn("knowledge-graph-highlight", html)

    def test_old_graph_page_receives_editor_on_delivery(self):
        legacy = "<html><body><div id=\"mynetwork\"></div><script>var network = {};</script></body></html>"
        prepared = prepare_legacy_graph_html(legacy, graph_name="旧图谱")
        self.assertIn('const GRAPH_NAME = "旧图谱";', prepared)
        self.assertIn("graph-context-menu", prepared)

    def test_rendered_graph_exposes_entity_type_metadata(self):
        manager = KgManager(agent=None, splitter=None, embedding_model=None, store=None)
        manager.current_G = nx.DiGraph()
        manager.current_G.add_node("刘备", group="人物", title="人物")
        manager.current_G.add_node("蜀汉", group="政权", title="政权")
        manager.current_G.add_edge("刘备", "蜀汉", label="建立", title="建立蜀汉", weight=0.8)

        with tempfile.TemporaryDirectory() as output_dir:
            manager.绘制知识图谱("三国", 聚类算法=None, 输出目录=output_dir)
            result = Path(output_dir, "三国", "三国.html").read_text(encoding="utf-8")
            delivered_result = prepare_legacy_graph_html(
                result,
                asset_base_url="/api/graph-assets",
            )

        match = re.search(r"nodes = new vis\.DataSet\((\[.*?\])\);", result)
        self.assertIsNotNone(match)
        rendered_nodes = json.loads(match.group(1))
        rendered_types = {node["entityType"] for node in rendered_nodes}
        self.assertEqual(rendered_types, {"人物", "政权"})
        self.assertIn("id=\"entityTypeOptions\"", result)
        self.assertIn('const GRAPH_NAME = "三国";', result)
        self.assertIn("/api/graph-assets/vis-network.min.js", delivered_result)
        self.assertNotIn("cdnjs.cloudflare.com", delivered_result)
        self.assertNotIn("cdn.jsdelivr.net/npm/bootstrap", delivered_result)
        self.assertIn('"iterations": 120', result)

    def test_paginated_overview_contains_searchable_community_directory(self):
        manager = KgManager(agent=None, splitter=None, embedding_model=None, store=None)
        graph = nx.DiGraph()
        for prefix, entity_type in (("甲", "人物"), ("乙", "地点")):
            nodes = [f"{prefix}{index}" for index in range(20)]
            for node in nodes:
                graph.add_node(node, group=entity_type, title=entity_type)
            for source in nodes:
                for target in nodes:
                    if source != target:
                        graph.add_edge(source, target, label="关联", title="测试", weight=0.8)
        manager.current_G = graph

        with tempfile.TemporaryDirectory() as output_dir:
            manager.绘制知识图谱("社区测试", 输出目录=output_dir)
            graph_dir = Path(output_dir, "社区测试")
            overview = Path(graph_dir, "社区测试.html").read_text(encoding="utf-8")
            community_pages = list(graph_dir.glob("社区测试_community_*.html"))

        self.assertIn('id="communitySearchInput"', overview)
        self.assertIn('id="communityTypeFilter"', overview)
        self.assertIn('class="community-list-item"', overview)
        self.assertIn('class="community-source-link"', overview)
        self.assertIn('data-community-name="社区', overview)
        self.assertIn('data-member-names="', overview)
        self.assertNotIn('"entityType": "社区"', overview)
        self.assertGreaterEqual(len(community_pages), 2)

    def test_community_min_size_one_exposes_small_communities(self):
        manager = KgManager(agent=None, splitter=None, embedding_model=None, store=None)
        manager.current_G = nx.DiGraph()
        manager.current_G.add_nodes_from(["甲", "乙", "丙"])

        with tempfile.TemporaryDirectory() as output_dir:
            manager.绘制知识图谱(
                "小社区",
                输出目录=output_dir,
                社区最小规模=1,
            )
            graph_dir = Path(output_dir, "小社区")
            community_pages = list(graph_dir.glob("小社区_community_*.html"))

        self.assertEqual(len(community_pages), 3)

    def test_community_overview_uses_representative_entities_for_nodes_edges_and_sources(self):
        manager = KgManager(agent=None, splitter=None, embedding_model=None, store=None)
        graph = nx.DiGraph()
        graph.add_node("主节点甲", group="人物", source_blocks=["block-main-a"])
        graph.add_node("甲成员", group="人物")
        graph.add_node("主节点乙", group="地点", source_blocks=["block-main-b"])
        graph.add_node("乙成员", group="地点")
        graph.add_edges_from([
            ("主节点甲", "甲成员", {"label": "包含", "weight": 0.8}),
            ("甲成员", "主节点甲", {"label": "属于", "weight": 0.8}),
            ("主节点乙", "乙成员", {"label": "包含", "weight": 0.8}),
            ("乙成员", "主节点乙", {"label": "属于", "weight": 0.8}),
            ("主节点甲", "主节点乙", {"label": "跨社区关系", "weight": 0.9}),
        ])
        manager.current_G = graph
        partition = {"主节点甲": 10, "甲成员": 10, "主节点乙": 20, "乙成员": 20}

        with tempfile.TemporaryDirectory() as output_dir, patch(
            "community.best_partition", return_value=partition
        ) as best_partition:
            manager.绘制知识图谱("社区语义", 输出目录=output_dir, 社区最小规模=1)
            overview = Path(output_dir, "社区语义", "社区语义.html").read_text(encoding="utf-8")

        best_partition.assert_called_once()
        node_match = re.search(r"nodes = new vis\.DataSet\((\[.*?\])\);", overview)
        edge_match = re.search(r"edges = new vis\.DataSet\((\[.*?\])\);", overview)
        self.assertIsNotNone(node_match)
        self.assertIsNotNone(edge_match)
        nodes = {node["id"]: node for node in json.loads(node_match.group(1))}
        edges = json.loads(edge_match.group(1))

        self.assertEqual(set(nodes), {"主节点甲", "主节点乙"})
        self.assertEqual(nodes["主节点甲"]["source_blocks"], ["block-main-a"])
        self.assertEqual(nodes["主节点乙"]["source_blocks"], ["block-main-b"])
        self.assertEqual({edges[0]["from"], edges[0]["to"]}, {"主节点甲", "主节点乙"})
        self.assertNotIn(10, {edges[0]["from"], edges[0]["to"]})
        self.assertIn('data-representative-node="主节点甲"', overview)
        self.assertIn("item.dataset.representativeNode || item.dataset.name", overview)
        self.assertIn("communitySearchRank(item, term)", overview)
        self.assertIn("JSON.parse(item.dataset.memberNames || '[]')", overview)
        self.assertIn("rankedItems.forEach(({ item }) => list?.appendChild(item))", overview)

    def test_community_overview_edge_carries_original_relation_evidence(self):
        manager = KgManager(agent=None, splitter=None, embedding_model=None, store=None)
        graph = nx.DiGraph()
        graph.add_node("主节点甲", group="人物")
        graph.add_node("甲成员", group="人物")
        graph.add_node("主节点乙", group="地点")
        graph.add_node("乙成员", group="地点")
        graph.add_edges_from([
            ("主节点甲", "甲成员", {"label": "包含", "weight": 0.8}),
            ("甲成员", "主节点甲", {"label": "属于", "weight": 0.8}),
            ("主节点乙", "乙成员", {"label": "包含", "weight": 0.8}),
            ("乙成员", "主节点乙", {"label": "属于", "weight": 0.8}),
            ("主节点甲", "主节点乙", {
                "label": "跨社区关系", "title": "甲与乙的原文依据", "weight": 0.9,
            }),
        ])
        manager.current_G = graph
        manager.kg_triplet = [{
            "bid": "relation-block-1",
            "relation": [{
                "source": "主节点甲",
                "target": "主节点乙",
                "relation": "跨社区关系",
                "context": "甲与乙的原文依据",
                "weight": 0.9,
                "origin": "extracted",
            }],
        }]
        partition = {"主节点甲": 10, "甲成员": 10, "主节点乙": 20, "乙成员": 20}

        with tempfile.TemporaryDirectory() as output_dir, patch(
            "community.best_partition", return_value=partition
        ):
            manager.绘制知识图谱("社区关系出处", 输出目录=output_dir, 社区最小规模=1)
            overview = Path(
                output_dir, "社区关系出处", "社区关系出处.html"
            ).read_text(encoding="utf-8")

        edge_match = re.search(r"edges = new vis\.DataSet\((\[.*?\])\);", overview)
        self.assertIsNotNone(edge_match)
        edge = json.loads(edge_match.group(1))[0]
        self.assertEqual(edge["source_block"], "relation-block-1")
        self.assertEqual(edge["evidence_blocks"], [{
            "source_block": "relation-block-1",
            "evidence": "甲与乙的原文依据",
            "score": 0.9,
        }])
        self.assertEqual(edge["evidence_source"], "主节点甲")
        self.assertEqual(edge["evidence_target"], "主节点乙")
        self.assertIn("sourceBlocks = edge.evidence_blocks || []", overview)


if __name__ == "__main__":
    unittest.main()
