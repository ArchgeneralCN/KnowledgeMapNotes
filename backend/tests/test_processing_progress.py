import tempfile
import unittest
from pathlib import Path

import main


class ProcessingProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_status_folder = main.STATUS_FOLDER
        main.STATUS_FOLDER = Path(self.temp_dir.name)
        with main.process_status_lock:
            main.PROCESS_STATUS.pop("progress-test", None)

    def tearDown(self):
        with main.process_status_lock:
            main.PROCESS_STATUS.pop("progress-test", None)
        main.STATUS_FOLDER = self.previous_status_folder
        self.temp_dir.cleanup()

    def test_three_stages_publish_individual_and_overall_estimates(self):
        main.initialize_stage_progress("progress-test", "processing", 2)
        callback = main.create_stage_progress_callback("progress-test")

        callback("entity_extraction", 1, 2, 2)
        callback("entity_extraction", 2, 2, 2)
        callback("relationship_extraction", 1, 2, 1)
        callback("relationship_extraction", 2, 2, 1)
        callback("knowledge_fusion", 0, 2, 0)

        status = main.get_process_status("progress-test")
        self.assertEqual(status["percentage"], 66.7)
        self.assertEqual(status["stage_progress"]["entity_extraction"]["items_per_minute"], 30.0)
        self.assertEqual(status["stage_progress"]["relationship_extraction"]["average_item_seconds"], 1.0)
        self.assertEqual(status["stage_progress"]["knowledge_fusion"]["remaining"], 2)
        self.assertEqual(status["estimated_total_remaining_seconds"], 3)

        callback("knowledge_fusion", 1, 2, 3)
        status = main.get_process_status("progress-test")
        self.assertEqual(status["percentage"], 83.3)
        self.assertEqual(status["stage_progress"]["knowledge_fusion"]["remaining"], 1)
        self.assertEqual(status["stage_progress"]["knowledge_fusion"]["estimated_remaining_seconds"], 3)
        self.assertEqual(status["estimated_total_remaining_seconds"], 3)
        self.assertGreater(status["overall_speed_percent_per_minute"], 0)

        callback("knowledge_fusion", 2, 2, 3)
        status = main.get_process_status("progress-test")
        self.assertEqual(status["percentage"], 100.0)
        self.assertEqual(status["estimated_total_remaining_seconds"], 0)

    def test_fusion_callback_adapts_three_argument_signature(self):
        main.initialize_stage_progress("progress-test", "processing", 1)
        stage_callback = main.create_stage_progress_callback("progress-test")
        stage_callback("entity_extraction", 1, 1, 1)
        stage_callback("relationship_extraction", 1, 1, 1)
        fusion_callback = main.create_fusion_progress_callback("progress-test")

        fusion_callback(0, 2, 0)
        fusion_callback(1, 2, 3)

        status = main.get_process_status("progress-test")
        self.assertEqual(status["processing_stage"], "knowledge_fusion")
        self.assertEqual(status["stage_progress"]["knowledge_fusion"]["completed"], 1)
        self.assertEqual(status["stage_progress"]["knowledge_fusion"]["remaining"], 1)


if __name__ == "__main__":
    unittest.main()
