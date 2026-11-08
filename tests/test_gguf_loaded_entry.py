"""GGUF loads must record _loaded_entry so GGUF Optimize now can start (found live Day 18)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gguf_split as G
import web_workers as W


class GgufLoadedEntryTest(unittest.TestCase):
    def test_single_mini_load_sets_loaded_entry(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "llama-server").write_text("")
            model = d / "m.gguf"
            model.write_bytes(b"x")
            m = W.WorkerManager.__new__(W.WorkerManager)
            m.lead_port = 18194
            m.state_dir = d
            m._set = lambda **kw: None
            m._note = lambda msg: None
            for name in ("_kill_gguf", "_kill_lead", "_kill_packer", "_write_gguf_meta",
                         "_wait_lead_ready", "_start_gguf_watch"):
                setattr(m, name, mock.Mock())
            m._gguf_nodes = lambda place: [{"id": "exo1", "label": "EXO1", "role": "lead"}]
            m._node_is_local = lambda n: True
            m._lead_log = lambda: d / "lead.log"
            entry = {"id": "gguf/m", "name": "m", "source": "gguf", "backend": "llama",
                     "lead_path": str(model), "tune_override": {"flash_attn": "off"}}
            with mock.patch.object(G, "LLAMA_BIN", str(d)), \
                    mock.patch.object(W.subprocess, "Popen") as popen, \
                    mock.patch.object(W.time, "sleep"):
                popen.return_value.pid = 4242
                m._load_gguf_inner(entry, {})
                args = popen.call_args[0][0]
            self.assertEqual(m._loaded_entry["source"], "gguf")
            self.assertEqual(m._loaded_entry["id"], "gguf/m")
            self.assertNotIn("tune_override", m._loaded_entry)
            self.assertIn("off", args)  # tune_override still reached the launcher


if __name__ == "__main__":
    unittest.main()
