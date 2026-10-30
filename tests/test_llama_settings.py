"""Unit tests for the llama-server tuning settings (agent/config.py),
the command they produce (agent/supervisor.py), and the rendered launchd
plist (agent/render_llama_plist.py). Temp dirs only; nothing is started.

    python3 -m unittest discover -s tests -v      # from the repo root
"""
import contextlib
import importlib
import io
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

ENV_KEYS = ("CARAVAN_N_SLOTS", "CARAVAN_CTX_PER_SLOT", "CARAVAN_FLASH_ATTN",
            "CARAVAN_CACHE_TYPE_K", "CARAVAN_CACHE_TYPE_V", "CARAVAN_CACHE_RAM_MIB",
            "CARAVAN_N_GPU_LAYERS", "CARAVAN_BATCH_SIZE", "CARAVAN_UBATCH_SIZE",
            "CARAVAN_RPC_ADDR", "CARAVAN_MODEL")


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


class LlamaSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config.json"
        env = {k: "" for k in ENV_KEYS}
        env["CARAVAN_CONFIG"] = str(self.cfg)
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        import config
        import supervisor
        self.config = importlib.reload(config)
        self.supervisor = importlib.reload(supervisor)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_defaults(self):
        s = self.config.resolve_llama_settings()
        self.assertEqual(s.n_slots, 4)
        self.assertEqual(s.total_ctx, 262144)
        self.assertEqual((s.flash_attn, s.cache_type_k, s.cache_type_v), ("on", "q8_0", "q8_0"))
        self.assertEqual((s.cache_ram_mib, s.n_gpu_layers, s.batch_size, s.ubatch_size),
                         (0, "999", 2048, 512))
        self.assertEqual(s.rpc, "169.254.104.38:50052")

    def test_precedence_flag_env_file(self):
        self.cfg.write_text(json.dumps({"llama_server": {"n_slots": 6, "ubatch_size": 256,
                                                         "cache_ram_mib": 1024}}))
        s = self.config.resolve_llama_settings()
        self.assertEqual((s.n_slots, s.ubatch_size, s.cache_ram_mib), (6, 256, 1024))
        with mock.patch.dict(os.environ, {"CARAVAN_N_SLOTS": "2", "CARAVAN_UBATCH_SIZE": "1024"}):
            s = self.config.resolve_llama_settings()
            self.assertEqual((s.n_slots, s.ubatch_size, s.total_ctx), (2, 1024, 131072))
            s = self.config.resolve_llama_settings({"n_slots": 3, "ubatch_size": None})
            self.assertEqual((s.n_slots, s.ubatch_size), (3, 1024))

    def test_validation(self):
        bad = [{"flash_attn": "maybe"}, {"cache_type_k": "q3"},
               {"flash_attn": "off"},                       # q8_0 V cache needs FA
               {"ubatch_size": 4096}, {"n_slots": 0}, {"n_gpu_layers": "lots"}]
        for o in bad:
            with self.subTest(o=o), self.assertRaises(ValueError):
                self.config.resolve_llama_settings(o)
        s = self.config.resolve_llama_settings({"flash_attn": "off", "cache_type_k": "f16",
                                                "cache_type_v": "f16"})
        self.assertEqual(s.flash_attn, "off")

    def test_head_command_flags(self):
        s = self.config.resolve_llama_settings({"n_slots": 2, "ctx_per_slot": 32768,
                                                "ubatch_size": 1024})
        cmd = self.supervisor.build_head_command("/m.gguf", ["10.0.0.2:50052"], s)
        self.assertEqual(_flag(cmd, "--parallel"), "2")
        self.assertEqual(_flag(cmd, "-c"), "65536")
        self.assertEqual(_flag(cmd, "-fa"), "on")
        self.assertEqual(_flag(cmd, "-ctk"), "q8_0")
        self.assertEqual(_flag(cmd, "-ctv"), "q8_0")
        self.assertEqual(_flag(cmd, "--cache-ram"), "0")
        self.assertEqual(_flag(cmd, "-ngl"), "999")
        self.assertEqual(_flag(cmd, "-b"), "2048")
        self.assertEqual(_flag(cmd, "-ub"), "1024")
        self.assertEqual(_flag(cmd, "--rpc"), "10.0.0.2:50052")
        self.assertIn("--no-kv-unified", cmd)

    def _plist_args_for_home(self, home: Path):
        repo_plist = plistlib.loads((REPO / "launchd" / "com.caravan.llama-server.plist").read_bytes())
        args = repo_plist["ProgramArguments"]
        # The committed plist is written for /Users/brenden; compare
        # against a command built for that home.
        return [a.replace("/Users/brenden", str(home)) for a in args]

    def test_repo_plist_matches_build_head_command(self):
        home = Path.home()
        args = self._plist_args_for_home(home)
        blob = _flag(args, "-m")
        cmd = self.supervisor.build_head_command(
            blob, [self.config.resolve_llama_settings().rpc])
        self.assertEqual(args, cmd)

    def test_render_plist(self):
        import render_llama_plist
        render = importlib.reload(render_llama_plist)
        out = Path(self.tmp.name) / "out.plist"
        with contextlib.redirect_stderr(io.StringIO()):
            rc = render.main(["--model-path", "/models/x.gguf", "--rpc", "10.1.2.3:50052",
                              "--n-slots", "3", "--ubatch-size", "1024", "--output", str(out)])
        self.assertEqual(rc, 0)
        p = plistlib.loads(out.read_bytes())
        self.assertEqual(p["Label"], "com.caravan.llama-server")
        args = p["ProgramArguments"]
        self.assertEqual(_flag(args, "-m"), "/models/x.gguf")
        self.assertEqual(_flag(args, "--rpc"), "10.1.2.3:50052")
        self.assertEqual(_flag(args, "--parallel"), "3")
        self.assertEqual(_flag(args, "-c"), str(3 * 65536))
        self.assertEqual(_flag(args, "-ub"), "1024")


if __name__ == "__main__":
    unittest.main()
