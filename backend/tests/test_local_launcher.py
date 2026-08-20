import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


LAUNCHER_PATH = Path(__file__).resolve().parents[2] / "start.py"
SPEC = importlib.util.spec_from_file_location("kmn_local_launcher", LAUNCHER_PATH)
launcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(launcher)


class LocalLauncherTests(unittest.TestCase):
    def test_find_available_port_skips_an_occupied_port(self):
        with patch.object(
            launcher,
            "_port_is_available",
            side_effect=lambda _host, port: port == 8002,
        ) as port_check:
            selected_port = launcher._find_available_port("127.0.0.1", 8000)

        self.assertEqual(8002, selected_port)
        self.assertEqual(
            [("127.0.0.1", 8000), ("127.0.0.1", 8001), ("127.0.0.1", 8002)],
            [call.args for call in port_check.call_args_list],
        )

    def test_access_url_uses_loopback_for_wildcard_host(self):
        self.assertEqual(launcher._access_url("0.0.0.0", 8001), "http://127.0.0.1:8001")

    def test_update_env_file_preserves_settings_and_replaces_model_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backend = root / "backend"
            backend.mkdir()
            (backend / ".env").write_text(
                "API_KEY=keep-me\n"
                "IS_USE_LOCAL=False\n"
                "EMBEDDINGS_PATH=/old/embedding\n"
                "RERANK_MODEL=/old/reranker\n",
                encoding="utf-8",
            )
            embedding = root / "models" / "embedding"
            reranker = root / "models" / "reranker"
            with (
                patch.object(launcher, "BACKEND_DIR", backend),
                patch.object(
                    launcher,
                    "MODEL_SPECS",
                    (("embedding", embedding), ("reranker", reranker)),
                ),
            ):
                launcher._update_env_file()

            content = (backend / ".env").read_text(encoding="utf-8")
            self.assertIn("API_KEY=keep-me", content)
            self.assertIn("IS_USE_LOCAL=True", content)
            self.assertIn(f'EMBEDDINGS_PATH="{embedding.as_posix()}"', content)
            self.assertIn(f'RERANK_MODEL="{reranker.as_posix()}"', content)
            self.assertNotIn("/old/", content)

    def test_model_completeness_requires_config_weights_and_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model = Path(temp_dir) / "model"
            model.mkdir()
            (model / "config.json").write_text("{}", encoding="utf-8")
            (model / "model.safetensors").write_bytes(b"weights")
            self.assertFalse(launcher._model_is_complete(model))

            (model / ".modelscope-complete").write_text("model\n", encoding="utf-8")
            self.assertTrue(launcher._model_is_complete(model))


if __name__ == "__main__":
    unittest.main()
