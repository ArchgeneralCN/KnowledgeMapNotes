import unittest

from KnowledgeGraphManager.KGManager import KgManager, ProcessingPaused


class StaticSplitter:
    def __init__(self, blocks):
        self.blocks = blocks

    def split_text(self, _text):
        return list(self.blocks)


class FakeEmbeddings:
    def encode(self, text):
        return [float(len(text))]


class CheckpointKgManager(KgManager):
    def __init__(self, blocks, fail_relation_for=None):
        super().__init__(
            agent=None,
            splitter=StaticSplitter(blocks),
            embedding_model=FakeEmbeddings(),
            store=None,
        )
        self.fail_relation_for = fail_relation_for
        self.relation_inputs = []
        self.processing_workers = 1

    def 实体提取(self, input_parameter):
        return [(f"实体-{input_parameter}", "测试")]

    def 关系提取(self, input_parameter, entity):
        self.relation_inputs.append(input_parameter)
        if input_parameter == self.fail_relation_for:
            raise ConnectionError("simulated network interruption")
        return [{
            "source": entity[0],
            "target": f"目标-{input_parameter}",
            "relation": "关联",
            "context": input_parameter,
            "weight": 0.5,
        }]


class KnowledgeGraphCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            ("block-1", "第一块"),
            ("block-2", "第二块"),
            ("block-3", "第三块"),
        ]

    def test_interruption_keeps_only_completed_blocks(self):
        manager = CheckpointKgManager(self.blocks, fail_relation_for="第二块")
        checkpoints = []

        with self.assertRaises(ConnectionError):
            manager.知识图谱的构建(
                "full text",
                checkpoint_callback=lambda state, completed, total: checkpoints.append(
                    (completed, total, list(state.Bolts), list(state.kg_triplet))
                ),
            )

        self.assertEqual([item[0] for item in manager.Bolts], ["block-1"])
        self.assertEqual([item["bid"] for item in manager.kg_triplet], ["block-1"])
        self.assertEqual(manager.kg_triplet[0]["entities"], [
            {"name": "实体-第一块", "type": "测试"},
        ])
        self.assertEqual([(item[0], item[1]) for item in checkpoints], [(1, 3)])

    def test_resume_processes_only_remaining_blocks(self):
        manager = CheckpointKgManager(self.blocks)
        manager.Bolts = [self.blocks[0]]
        manager.kg_triplet = [{"bid": "block-1", "relation": []}]
        manager.bidirectional_mapping = manager._build_bidirectional_mapping(
            [("实体-第一块", "测试")]
        )
        progress = []

        result = manager.知识图谱的构建(
            self.blocks[1:],
            append=True,
            completed_offset=1,
            total_chunks=3,
            progress_callback=lambda completed, total, _seconds: progress.append(
                (completed, total)
            ),
        )

        self.assertEqual(manager.relation_inputs, ["第二块", "第三块"])
        self.assertEqual([item[0] for item in manager.Bolts], [
            "block-1", "block-2", "block-3"
        ])
        self.assertEqual([item["bid"] for item in result], [
            "block-1", "block-2", "block-3"
        ])
        self.assertEqual(progress, [(2, 3), (3, 3)])

    def test_stage_progress_runs_entity_pass_before_relationship_pass(self):
        manager = CheckpointKgManager(self.blocks)
        stages = []

        manager.知识图谱的构建(
            self.blocks,
            stage_progress_callback=lambda stage, completed, total, _seconds: stages.append(
                (stage, completed, total)
            ),
        )

        self.assertEqual(stages, [
            ("entity_extraction", 1, 3),
            ("entity_extraction", 2, 3),
            ("entity_extraction", 3, 3),
            ("relationship_extraction", 1, 3),
            ("relationship_extraction", 2, 3),
            ("relationship_extraction", 3, 3),
        ])

    def test_pause_stops_after_current_checkpoint(self):
        manager = CheckpointKgManager(self.blocks)
        pause_requested = [False]

        def checkpoint(_manager, _completed, _total):
            pause_requested[0] = True

        with self.assertRaises(ProcessingPaused):
            manager.知识图谱的构建(
                self.blocks,
                checkpoint_callback=checkpoint,
                pause_callback=lambda: pause_requested[0],
            )

        self.assertEqual(manager.relation_inputs, ["第一块"])
        self.assertEqual([item[0] for item in manager.Bolts], ["block-1"])
        self.assertEqual([item["bid"] for item in manager.kg_triplet], ["block-1"])


if __name__ == "__main__":
    unittest.main()
