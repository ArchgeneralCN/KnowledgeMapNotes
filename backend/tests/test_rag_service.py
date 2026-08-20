import unittest
from unittest.mock import MagicMock

from services.rag_service import RAGService


class RAGServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = RAGService(
            vector_store=MagicMock(),
            kg_agent=MagicMock(),
            rag_agent=MagicMock(),
            require_ai_settings=MagicMock(),
            safe_filename=lambda value: value,
            base_name=lambda value: value.rsplit(".", 1)[0],
            graph_payload_loader=lambda _name: {
                "nodes": [
                    {
                        "id": "n1",
                        "name": "实体一",
                        "entityType": "概念",
                        "source_blocks": ["b1"],
                    }
                ],
                "links": [
                    {
                        "id": "e1",
                        "source": "实体一",
                        "target": "实体二",
                        "relation": "包含",
                        "weight": 0.8,
                        "context": "实体一包含实体二",
                        "evidence_blocks": ["b1"],
                    }
                ],
            },
            logger=MagicMock(),
        )

    def tearDown(self):
        self.service.executor.shutdown(wait=True)

    def test_session_lifecycle(self):
        session_id = self.service.initialize_session("session-1")

        self.assertEqual(session_id, "session-1")
        self.assertEqual(
            self.service.session_status(session_id),
            {"status": "idle", "queue_length": 0},
        )
        self.assertEqual(
            self.service.delete_session(session_id),
            {"message": "会话 session-1 已清除"},
        )

    def test_citations_include_source_node_and_edge(self):
        citations = self.service.build_citations(
            "document",
            {"ids": ["b1"], "documents": ["用于引用的原文片段"]},
            ["实体一"],
        )

        self.assertEqual([item["type"] for item in citations], ["source", "graph", "graph"])
        self.assertEqual(citations[0]["sourceBlocks"], ["b1"])
        self.assertEqual(citations[1]["graphId"], "n1")
        self.assertEqual(citations[2]["graphId"], "e1")

    def test_sse_event_contains_request_id(self):
        event = self.service._event("status", "request-1", content="开始处理")

        self.assertTrue(event.startswith("data: "))
        self.assertIn('"request_id": "request-1"', event)
        self.assertTrue(event.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
