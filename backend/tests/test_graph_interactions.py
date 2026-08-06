import json
import re
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
