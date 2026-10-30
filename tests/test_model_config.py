"""Unit tests for the configurable target model (agent/config.py) and
Ollama-store name resolution (agent/ollama_store.py). Temp dirs only.

    python3 -m unittest discover -s tests -v      # from the repo root
"""
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))


class TargetModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config.json"
        self.env = mock.patch.dict(os.environ, {"CARAVAN_CONFIG": str(self.cfg), "CARAVAN_MODEL": ""})
        self.env.start()
        import config
        self.config = importlib.reload(config)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_default_unchanged(self):
        self.assertEqual(self.config.resolve_target_model(), "muse-glimmer")
        self.assertEqual(self.config.TARGET_MODEL, "muse-glimmer")

    def test_precedence(self):
        self.cfg.write_text(json.dumps({"model": "from-file:q4"}))
        self.assertEqual(self.config.resolve_target_model(), "from-file:q4")
        with mock.patch.dict(os.environ, {"CARAVAN_MODEL": "from-env"}):
            self.assertEqual(self.config.resolve_target_model(), "from-env")
            self.assertEqual(self.config.resolve_target_model("from-flag"), "from-flag")

    def test_broken_config_file_falls_back(self):
        self.cfg.write_text("{not json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.config.resolve_target_model(), "muse-glimmer")


class OllamaStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = Path(self.tmp.name) / "models"
        self.env = mock.patch.dict(os.environ, {"OLLAMA_MODELS": str(self.models)})
        self.env.start()
        import ollama_store
        self.store = importlib.reload(ollama_store)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _pull(self, rel_manifest, hexdigest):
        m = self.models / "manifests" / rel_manifest
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({"layers": [
            {"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:aa"},
            {"mediaType": self.store.GGUF_LAYER_MEDIA_TYPE, "digest": f"sha256:{hexdigest}"},
        ]}))
        blobs = self.models / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        (blobs / f"sha256-{hexdigest}").write_bytes(b"GGUF")
        return blobs / f"sha256-{hexdigest}"

    def test_library_and_namespaced_names(self):
        b1 = self._pull("registry.ollama.ai/library/muse-glimmer/latest", "11")
        b2 = self._pull("registry.ollama.ai/library/qwen3/30b-a3b", "22")
        b3 = self._pull("registry.ollama.ai/someone/coder/q4", "33")
        b4 = self._pull("hf.co/unsloth/Some-GGUF/Q4_K_M", "44")
        self.assertEqual(self.store.resolve_blob_path("muse-glimmer"), b1)
        self.assertEqual(self.store.resolve_blob_path("muse-glimmer:latest"), b1)
        self.assertEqual(self.store.resolve_blob_path("qwen3:30b-a3b"), b2)
        self.assertEqual(self.store.resolve_blob_path("someone/coder:q4"), b3)
        self.assertEqual(self.store.resolve_blob_path("hf.co/unsloth/Some-GGUF:Q4_K_M"), b4)
        self.assertIsNone(self.store.resolve_blob_path("missing"))
        self.assertTrue(self.store.has_model("qwen3:30b-a3b"))
        self.assertEqual(sorted(self.store.list_local_models()), sorted([
            "muse-glimmer:latest", "qwen3:30b-a3b", "someone/coder:q4",
            "hf.co/unsloth/Some-GGUF:Q4_K_M"]))

    def test_cli(self):
        b = self._pull("registry.ollama.ai/library/qwen3/8b", "55")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.store.main(["qwen3:8b"]), 0)
        self.assertEqual(out.getvalue().strip(), str(b))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.store.main(["nope"]), 1)


if __name__ == "__main__":
    unittest.main()
