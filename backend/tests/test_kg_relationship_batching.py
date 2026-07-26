import json
import re
import unittest

from KnowledgeGraphManager.KGManager import KgManager
from LLM.Openai_Agent import AIResponseTruncatedError


class TruncatingRelationshipAgent:
    def __init__(self):
        self.calls = []

    def agent_safe_generate_response(self, _prompt, input_parameter, **_kwargs):
        candidates_match = re.search(r"实体列表：(\[[^\n]*\])", input_parameter)
        sources_match = re.search(
            r"本批允许作为 source 的实体列表：(\[[^\n]*\])",
            input_parameter,
        )
        candidates = json.loads(candidates_match.group(1))
        sources = json.loads(sources_match.group(1))
        self.calls.append(list(sources))

        if len(sources) > 1:
            raise AIResponseTruncatedError("simulated token limit")

        source = sources[0]
        target = next(name for name in candidates if name != source)
        return {"relations": [{
            "source": source,
            "target": target,
            "relation": "关联",
            "context": f"{source}与{target}有关。",
            "weight": 2,
        }]}


class RelationshipBatchingTests(unittest.TestCase):
    def _manager(self, agent):
        manager = KgManager(
            agent=agent,
            splitter=None,
            embedding_model=None,
            store=None,
        )
        manager.relationship_text_batch_chars = 10000
        manager.relationship_source_batch_size = 100
        manager._processing_prompt = lambda _stage: "extract relations"
        return manager

    def test_truncated_batch_is_bisected_and_merged(self):
        agent = TruncatingRelationshipAgent()
        manager = self._manager(agent)

        relations = manager.关系提取(
            "甲与乙有关。乙与丙有关。丙与甲有关。",
            ["甲", "乙", "丙"],
        )

        self.assertEqual(len(relations), 3)
        self.assertEqual(agent.calls, [
            ["甲", "乙", "丙"],
            ["甲"],
            ["乙", "丙"],
            ["乙"],
            ["丙"],
        ])
        self.assertTrue(all(relation["weight"] == 1.0 for relation in relations))

    def test_relations_outside_candidate_list_are_discarded(self):
        class HallucinatingAgent:
            def agent_safe_generate_response(self, *_args, **_kwargs):
                return {"relations": [{
                    "source": "甲",
                    "target": "不存在",
                    "relation": "关联",
                    "context": "错误关系",
                    "weight": 0.8,
                }]}

        manager = self._manager(HallucinatingAgent())

        relations = manager.关系提取("甲与乙有关。", ["甲", "乙"])

        self.assertEqual(relations, [])


if __name__ == "__main__":
    unittest.main()
