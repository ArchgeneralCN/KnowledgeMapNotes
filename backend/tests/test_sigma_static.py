import json
import math
import re
import tempfile
import unittest

import networkx as nx

from KnowledgeGraphManager.sigma_static import (
    SIGMA_STATIC_PAGE_VERSION,
    _centrality_scores,
    _node_sizes,
    _separate_overview_hubs,
    build_sigma_page,
    obsidian_layout,
    sigma_layout,
    write_sigma_graph_pages,
)


class SigmaStaticPageTests(unittest.TestCase):
    def build_graph(self):
        graph = nx.MultiDiGraph()
        for index in range(12):
            graph.add_node(
                f"node-{index}",
                label=f"实体 {index}",
                entity_type="人物" if index < 8 else "组织",
                source_blocks=[f"block-{index}"],
            )
        for index in range(11):
            graph.add_edge(
                f"node-{index}",
                f"node-{index + 1}",
                edit_id=f"edge-{index}",
                label="关联",
                evidence_blocks=[{"source_block": f"block-{index}"}],
            )
        return graph

    def test_layout_is_deterministic_and_finite(self):
        graph = self.build_graph()
        first = sigma_layout(graph)
        second = sigma_layout(graph)
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(graph.nodes))
        self.assertGreater(len({round(x, 3) for x, _ in first.values()}), 4)
        self.assertGreater(len({round(y, 3) for _, y in first.values()}), 4)

    def test_layout_keeps_isolated_community_coordinates_finite(self):
        graph = nx.Graph()
        graph.add_nodes_from(f"isolated-{index}" for index in range(24))

        positions = sigma_layout(graph, {node: 0 for node in graph.nodes})

        self.assertEqual(set(positions), set(graph.nodes))
        self.assertTrue(all(
            math.isfinite(x) and math.isfinite(y)
            for x, y in positions.values()
        ))

    def test_obsidian_layout_is_fast_deterministic_and_finite(self):
        graph = self.build_graph()
        partition = {node: index // 4 for index, node in enumerate(graph.nodes)}
        sizes = {node: 3.0 for node in graph.nodes}

        first = obsidian_layout(graph, partition, sizes)
        second = obsidian_layout(graph, partition, sizes)

        self.assertEqual(first, second)
        self.assertEqual(set(first), set(graph.nodes))
        self.assertTrue(all(math.isfinite(x) and math.isfinite(y) for x, y in first.values()))

    def test_overview_hubs_are_separated_after_layout(self):
        graph = nx.Graph()
        hubs = [f"hub-{index}" for index in range(4)]
        for hub_index, hub in enumerate(hubs):
            for leaf_index in range(8):
                graph.add_edge(hub, f"leaf-{hub_index}-{leaf_index}")
        positions = {
            node: (float(index % 3), float(index % 2))
            for index, node in enumerate(graph.nodes)
        }
        sizes = {node: 30.0 if node in hubs else 3.0 for node in graph.nodes}

        separated = _separate_overview_hubs(graph, positions, sizes)
        hub_distances = [
            math.dist(separated[source], separated[target])
            for index, source in enumerate(hubs)
            for target in hubs[index + 1:]
        ]

        self.assertGreater(min(hub_distances), 70.0)
        self.assertTrue(all(math.isfinite(x) and math.isfinite(y) for x, y in separated.values()))

    def test_page_embeds_layout_data_and_local_assets(self):
        page = build_sigma_page(self.build_graph(), "测试 </script> 图谱")
        self.assertIn(
            f"const SIGMA_STATIC_PAGE_VERSION = {SIGMA_STATIC_PAGE_VERSION};",
            page,
        )
        self.assertIn('/api/graph-assets/sigma.min.js', page)
        self.assertIn('/api/graph-assets/graphology.umd.min.js', page)
        self.assertIn('/svgs/person.svg', page)
        self.assertIn('id="sigma-types" hidden', page)
        self.assertIn('/graph-data/', page)
        self.assertIn("graph-context-menu", page)
        self.assertIn("function applyDefaultImmersivePanels", page)
        self.assertIn("window.network = network", page)
        self.assertIn("stabilize: () => emit('stabilized', {})", page)
        self.assertIn("defaultNodeType:isFullGraph?'circle':'image'", page)
        self.assertIn("defaultEdgeType:isFullGraph?'line':'arrow'", page)
        self.assertIn("hideEdgesOnMove:isFullGraph", page)
        self.assertIn("minEdgeThickness:isFullGraph?1:1.7", page)
        self.assertIn("SigmaClass.rendering.createNodeImageProgram", page)
        self.assertIn("type:isFullGraph?'circle':'image'", page)
        self.assertIn("renderer.graphToViewport(cluster)", page)
        self.assertIn("id='sigma-clusters-layer'", page)
        self.assertNotIn("renderer.on('downNode'", page)
        match = re.search(
            r'<script id="sigma-data" type="application/json">(.*?)</script>',
            page,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertEqual(len(payload["nodes"]), 12)
        self.assertEqual(len(payload["edges"]), 11)
        self.assertEqual(payload["nodes"][0]["source_blocks"], ["block-0"])
        self.assertTrue(all(3 <= node["size"] <= 30 for node in payload["nodes"]))

    def test_node_sizes_use_official_demo_linear_range(self):
        scores = {"minimum": 0.0, "middle": 0.5, "maximum": 1.0}
        sizes = _node_sizes(scores)
        self.assertEqual(sizes["minimum"], 3)
        self.assertEqual(sizes["middle"], 16.5)
        self.assertEqual(sizes["maximum"], 30)

    def test_centrality_scores_do_not_mix_in_degree(self):
        graph = nx.Graph()
        graph.add_edges_from([
            ("center", "leaf-1"),
            ("center", "leaf-2"),
            ("center", "bridge"),
            ("bridge", "right-1"),
            ("bridge", "right-2"),
        ])
        scores = _centrality_scores(graph)
        expected = nx.betweenness_centrality(graph, normalized=True, weight=None)
        self.assertEqual(scores, expected)

    def test_writes_full_overview_and_community_detail_pages(self):
        graph = nx.MultiDiGraph()
        for node, entity_type, source_block in (
            ("甲主节点", "人物", "block-a-main"),
            ("甲成员", "人物", "block-a-member"),
            ("乙主节点", "地点", "block-b-main"),
            ("乙成员", "地点", "block-b-member"),
        ):
            graph.add_node(
                node,
                entity_type=entity_type,
                source_blocks=[source_block],
            )
        graph.add_edge("甲主节点", "甲成员", label="包含", weight=0.8)
        graph.add_edge("乙主节点", "乙成员", label="包含", weight=0.8)
        graph.add_edge(
            "甲成员",
            "乙成员",
            edit_id="cross-edge",
            label="跨社区关系",
            weight=0.9,
            source_block="block-cross",
            evidence_blocks=[{"source_block": "block-cross", "evidence": "跨社区依据"}],
        )
        partition = {
            "甲主节点": 10,
            "甲成员": 10,
            "乙主节点": 20,
            "乙成员": 20,
        }

        with tempfile.TemporaryDirectory() as output_dir:
            written = write_sigma_graph_pages(
                graph,
                output_dir,
                "社区测试",
                partition,
                community_min_size=1,
            )
            pages = {path.name: path.read_text(encoding="utf-8") for path in written}

        self.assertEqual(set(pages), {
            "社区测试.sigma.html",
            "社区测试.sigma-communities.html",
            "社区测试.sigma-community-10.html",
            "社区测试.sigma-community-20.html",
        })
        full = self._payload(pages["社区测试.sigma.html"])
        overview = self._payload(pages["社区测试.sigma-communities.html"])
        detail = self._payload(pages["社区测试.sigma-community-10.html"])
        self.assertEqual(len(full["nodes"]), 4)
        self.assertEqual(full["navigation"]["mode"], "full")
        self.assertEqual(full["navigation"]["entries"], [])
        self.assertEqual(len(full["clusters"]), 2)
        self.assertEqual({node["community"] for node in full["nodes"]}, {"10", "20"})
        self.assertTrue(all("image" not in node for node in full["nodes"]))
        first_colors = {
            node["id"]: node["color"]
            for node in full["nodes"]
        }
        self.assertEqual(first_colors["甲主节点"], first_colors["甲成员"])
        self.assertNotEqual(first_colors["甲主节点"], first_colors["乙主节点"])
        self.assertNotIn("window.network = network", pages["社区测试.sigma.html"])
        self.assertNotIn("graph-floating-panel", pages["社区测试.sigma.html"])
        self.assertIn("enableEdgeEvents:!isFullGraph", pages["社区测试.sigma.html"])
        self.assertIn("body.sigma-obsidian", pages["社区测试.sigma.html"])
        self.assertEqual(len(overview["nodes"]), 2)
        self.assertEqual(len(overview["edges"]), 1)
        self.assertEqual(
            {node["entityType"]: node["image"] for node in overview["nodes"]},
            {"人物": "/svgs/person.svg", "地点": "/svgs/unknown.svg"},
        )
        self.assertEqual(overview["edges"][0]["evidence_source"], "甲成员")
        self.assertEqual(overview["edges"][0]["evidence_target"], "乙成员")
        self.assertEqual(overview["edges"][0]["color"], "#8d97a8")
        self.assertEqual({node["id"] for node in detail["nodes"]}, {"甲主节点", "甲成员"})
        self.assertTrue(all(node["image"] == "/svgs/person.svg" for node in detail["nodes"]))
        self.assertEqual(detail["navigation"]["currentCommunity"]["name"], "甲成员")
        self.assertIn("sigma-community-search", pages["社区测试.sigma.html"])
        self.assertIn("knowledge-graph-evidence", pages["社区测试.sigma-communities.html"])
        self.assertIn("entries.length && navigation.mode !== 'detail'", pages["社区测试.sigma-community-10.html"])
        self.assertIn("← 返回社区总览", pages["社区测试.sigma-community-10.html"])

    def test_overview_only_contains_communities_with_detail_cards(self):
        graph = nx.MultiDiGraph()
        graph.add_edges_from([
            ("大社区主节点", "大社区成员一"),
            ("大社区主节点", "大社区成员二"),
            ("大社区成员一", "孤立小社区"),
        ])
        for node in graph.nodes:
            graph.nodes[node]["entity_type"] = "概念"
        partition = {
            "大社区主节点": 10,
            "大社区成员一": 10,
            "大社区成员二": 10,
            "孤立小社区": 20,
        }

        with tempfile.TemporaryDirectory() as output_dir:
            written = write_sigma_graph_pages(
                graph,
                output_dir,
                "总览过滤测试",
                partition,
                community_min_size=2,
            )
            pages = {path.name: path.read_text(encoding="utf-8") for path in written}

        overview = self._payload(pages["总览过滤测试.sigma-communities.html"])
        self.assertEqual(len(overview["nodes"]), 1)
        self.assertIn(overview["nodes"][0]["id"], {
            "大社区主节点", "大社区成员一", "大社区成员二",
        })
        self.assertNotEqual(overview["nodes"][0]["id"], "孤立小社区")
        self.assertEqual(len(overview["navigation"]["entries"]), 1)
        self.assertEqual(overview["navigation"]["entries"][0]["communityName"], "社区10")
        self.assertIn(
            "[item.communityName,item.name].filter(Boolean).join(' · ')",
            pages["总览过滤测试.sigma-communities.html"],
        )

    def test_requested_page_generation_is_lazy(self):
        graph = self.build_graph()
        partition = {node: index // 4 for index, node in enumerate(graph.nodes)}

        with tempfile.TemporaryDirectory() as output_dir:
            written = write_sigma_graph_pages(
                graph,
                output_dir,
                "惰性测试",
                partition,
                community_min_size=1,
                requested_page="惰性测试.sigma.html",
            )

        self.assertEqual([path.name for path in written], ["惰性测试.sigma.html"])

    def test_initial_generation_can_skip_detail_pages(self):
        graph = self.build_graph()
        partition = {node: index // 4 for index, node in enumerate(graph.nodes)}

        with tempfile.TemporaryDirectory() as output_dir:
            written = write_sigma_graph_pages(
                graph,
                output_dir,
                "预生成测试",
                partition,
                community_min_size=1,
                include_detail_pages=False,
            )

        self.assertEqual([path.name for path in written], [
            "预生成测试.sigma.html",
            "预生成测试.sigma-communities.html",
        ])

    def test_community_pages_respect_minimum_size(self):
        graph = nx.Graph()
        graph.add_edge("甲一", "甲二")
        graph.add_node("乙一")
        partition = {"甲一": 0, "甲二": 0, "乙一": 1}

        with tempfile.TemporaryDirectory() as output_dir:
            written = write_sigma_graph_pages(
                graph,
                output_dir,
                "阈值测试",
                partition,
                community_min_size=3,
            )

        self.assertEqual([path.name for path in written], [
            "阈值测试.sigma.html",
            "阈值测试.sigma-communities.html",
        ])

    @staticmethod
    def _payload(page):
        match = re.search(
            r'<script id="sigma-data" type="application/json">(.*?)</script>',
            page,
            re.DOTALL,
        )
        if match is None:
            raise AssertionError("Sigma payload not found")
        return json.loads(match.group(1))


if __name__ == "__main__":
    unittest.main()
