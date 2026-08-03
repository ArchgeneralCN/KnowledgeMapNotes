import unittest
from types import SimpleNamespace

import networkx as nx

from OmniStore.chromadb_store import StoreTool


class RecordingCollection:
    def __init__(self):
        self.calls = []

    def upsert(self, **kwargs):
        self.calls.append(kwargs)


class StoreCheckpointTests(unittest.TestCase):
    def test_save_state_embeds_only_new_bolts(self):
        store = StoreTool.__new__(StoreTool)
        store.vector_collection = RecordingCollection()
        store.collection = RecordingCollection()
        store.embedding_func = lambda texts: [[float(len(text))] for text in texts]

        manager = SimpleNamespace(
            Bolts=[("b1", "第一块"), ("b2", "第二块")],
            file="测试",
            original_file_type="测试.txt",
            current_G=nx.DiGraph(),
            kg_triplet=[],
            bidirectional_mapping={
                "entity_to_label": {},
                "label_to_entities": {},
            },
            _persisted_bolt_count=0,
            _persisted_bolt_file=None,
        )

        store.save_state(manager)
        manager.Bolts.append(("b3", "第三块"))
        store.save_state(manager)

        self.assertEqual(
            [len(call["ids"]) for call in store.vector_collection.calls],
            [2, 1],
        )


if __name__ == "__main__":
    unittest.main()
