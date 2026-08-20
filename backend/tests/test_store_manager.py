import unittest

import networkx as nx

from OmniStore.storeManager import storeManager


class FakeStore:
    def __init__(self, state, vector_result=None):
        self.state = state
        self.vector_result = vector_result or {
            "ids": [], "documents": [], "metadatas": [], "distances": [],
        }

    def load_state(self, _filename):
        return self.state

    def select_vectors(self, **_kwargs):
        return self.vector_result


class StoreManagerTests(unittest.TestCase):
    def test_primary_entities_are_names_sorted_by_degree(self):
        graph = nx.Graph()
        graph.add_edges_from([
            ("主节点", "甲"),
            ("主节点", "乙"),
            ("主节点", "丙"),
        ])
        manager = storeManager(FakeStore({"current_G": graph}), agent=None)

        self.assertEqual(manager.edge_max_node("demo", 2), ["主节点", "甲"])

    def test_missing_graph_returns_empty_entity_list(self):
        manager = storeManager(FakeStore(None), agent=None)

        self.assertEqual(manager.edge_max_node("missing", 5), [])

    def test_vector_context_preserves_source_block_ids(self):
        result = {
            "ids": ["block-7"],
            "documents": ["可定位的原文"],
            "metadatas": [{}],
            "distances": [0.12],
        }
        manager = storeManager(FakeStore(None, result), agent=None)

        self.assertEqual(manager.select_vector_context("问题", "demo", 1), result)
        self.assertEqual(manager.select_vectors("问题", "demo", 1), ["可定位的原文"])


if __name__ == "__main__":
    unittest.main()
