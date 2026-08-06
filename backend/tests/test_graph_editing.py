import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

import networkx as nx

from KnowledgeGraphManager.graph_editing import (
    GraphEditError,
    GraphHistory,
    apply_graph_mutation,
    graph_payload,
    state_from_snapshot,
    state_snapshot,
)


def sample_state():
    graph = nx.DiGraph()
    graph.add_node("甲", group="人物", title="人物")
    graph.add_node("乙", group="地点", title="地点")
    graph.add_edge("甲", "乙", label="到达", title="原始关系", weight=0.8)
    return {
        "file": "test",
        "kg_triplet": [{
            "bid": "block-1",
            "relation": [{
                "source": "甲", "target": "乙", "relation": "到达",
                "context": "原始关系", "weight": 0.8,
            }],
        }],
        "bidirectional_mapping": {
            "entity_to_label": {"甲": "人物", "乙": "地点"},
            "label_to_entities": defaultdict(list, {"人物": ["甲"], "地点": ["乙"]}),
        },
        "current_G": graph,
        "Bolts": [("block-1", "原文")],
        "original_file_type": "test.txt",
    }


class GraphEditingTests(unittest.TestCase):
    def test_multiple_edges_keep_independent_ids(self):
        state = sample_state()
        apply_graph_mutation(state, {"operation": "add_edge", "source": "甲", "target": "乙", "relation": "认识", "context": "另一条关系"})
        payload = graph_payload(state)
        self.assertEqual(len(payload["links"]), 2)
        self.assertEqual(len({link["id"] for link in payload["links"]}), 2)

    def test_node_rename_updates_all_relations(self):
        state = sample_state()
        apply_graph_mutation(state, {"operation": "update_node", "node_id": "甲", "name": "丙", "entity_type": "人物"})
        relation = state["kg_triplet"][0]["relation"][0]
        self.assertEqual(relation["source"], "丙")
        self.assertNotIn("甲", state["bidirectional_mapping"]["entity_to_label"])
        self.assertIn("丙", state["bidirectional_mapping"]["entity_to_label"])

    def test_delete_node_cascades_edges_and_invalid_edge_is_rejected(self):
        state = sample_state()
        apply_graph_mutation(state, {"operation": "delete_node", "node_id": "乙"})
        self.assertEqual(state["kg_triplet"][0]["relation"], [])
        with self.assertRaises(GraphEditError):
            apply_graph_mutation(state, {"operation": "add_edge", "source": "甲", "target": "乙", "relation": "x"})

    def test_history_round_trip_and_atomic_file(self):
        with tempfile.TemporaryDirectory() as directory:
            history = GraphHistory(Path(directory))
            before = sample_state()
            after = sample_state()
            apply_graph_mutation(after, {"operation": "add_node", "name": "丙", "entity_type": "概念"})
            revision = history.commit("test", state_snapshot(before), state_snapshot(after), "add_node")
            self.assertEqual(revision, 2)
            restored = history.get_version("test", 1)
            self.assertIsNotNone(restored)
            self.assertNotIn("丙", restored["bidirectional_mapping"]["entity_to_label"])
            versions = history.list_versions("test")
            self.assertEqual(len(versions), 2)
            self.assertEqual(versions[0]["description"], "修改前快照：新增节点")
            self.assertEqual(versions[1]["description"], "新增节点")
            self.assertIsNotNone(state_from_snapshot(state_snapshot(after))["current_G"])


if __name__ == "__main__":
    unittest.main()
