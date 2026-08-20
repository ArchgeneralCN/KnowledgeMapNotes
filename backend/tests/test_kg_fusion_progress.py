import unittest

from KnowledgeGraphManager.KGManager import KgManager


class FusionAgent:
    def agent_safe_generate_response(self, *_args, **_kwargs):
        return {"relations": [{
            "source": "甲",
            "target": "乙",
            "relation": "融合关系",
            "context": "融合上下文",
            "weight": 0.8,
        }]}


class KnowledgeFusionProgressTests(unittest.TestCase):
    def _manager(self):
        manager = KgManager(
            agent=FusionAgent(),
            splitter=None,
            embedding_model=None,
            store=None,
        )
        manager._processing_prompt = lambda _stage: "{input_text}"
        return manager

    def test_reports_each_entity_pair(self):
        manager = self._manager()
        progress = []
        relations = [{
            "bid": "block-1",
            "relation": [
                {"source": "甲", "target": "乙", "relation": "关系一", "context": "上下文一", "weight": 0.5},
                {"source": "乙", "target": "甲", "relation": "关系二", "context": "上下文二", "weight": 0.6},
                {"source": "乙", "target": "丙", "relation": "关系三", "context": "上下文三", "weight": 0.7},
            ],
        }]

        manager.知识融合(
            relations,
            progress_callback=lambda completed, total, seconds: progress.append(
                (completed, total, seconds)
            ),
        )

        self.assertEqual([(completed, total) for completed, total, _ in progress], [
            (0, 2),
            (1, 2),
            (2, 2),
        ])
        self.assertTrue(all(seconds >= 0 for _, _, seconds in progress))

    def test_empty_relations_finish_as_zero_entity_pairs(self):
        manager = self._manager()
        progress = []

        result = manager.知识融合(
            [],
            progress_callback=lambda completed, total, _seconds: progress.append(
                (completed, total)
            ),
        )

        self.assertEqual(result, [])
        self.assertEqual(progress, [(0, 0)])


if __name__ == "__main__":
    unittest.main()
