import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

import gguf_split as G  # noqa: E402

N = lambda i, role, gb, peer="": {"id": i, "label": i.upper(), "role": role,
                                   "host": "local" if role == "lead" else "b@" + peer,
                                   "ssh": "" if role == "lead" else "b@" + peer,
                                   "peer": peer + ":5560" if peer else "", "ram": {"total_gb": gb}}


class Placement(unittest.TestCase):
    def test_small_model_defaults_to_one_mini(self):
        p = G.placement_options(5, [N("exo1", "lead", 24), N("exo2", "packer", 24, "169.254.1.2")])
        self.assertEqual(p["default_id"], "one:exo1")
        self.assertEqual([o["mode"] for o in p["options"]], ["one", "split"])

    def test_big_model_defaults_to_smallest_split_any_n(self):
        nodes = [N("a", "lead", 24)] + [N(f"p{i}", "packer", 24, f"169.254.0.{i}") for i in range(1, 4)]
        p = G.placement_options(40, nodes)
        self.assertEqual(p["default_id"], "split:a,p1,p2")
        self.assertFalse(p["options"][0]["enabled"])
        self.assertEqual(len(p["options"]), 4)  # one + split 2,3,4

    def test_offline_skipped(self):
        n2 = N("exo2", "packer", 24, "169.254.1.2"); n2["offline"] = True
        p = G.placement_options(5, [N("exo1", "lead", 24), n2])
        self.assertEqual(len(p["options"]), 1)


class Commands(unittest.TestCase):
    def test_llama_args_split(self):
        a = G.llama_args("/m.gguf", port=8194, peers=["169.254.1.2:50052", "169.254.1.3:50052"], shares=[1, 1, 1])
        self.assertIn("--rpc", a)
        self.assertEqual(a[a.index("--device") + 1], "MTL0,RPC0,RPC1")
        self.assertEqual(a[a.index("--host") + 1], "127.0.0.1")

    def test_llama_args_single_has_no_rpc(self):
        self.assertNotIn("--rpc", G.llama_args("/m.gguf", port=1, peers=[], shares=[1]))

    def test_rpc_start_loopback_only(self):
        c = G.rpc_start_command()
        self.assertIn("-H 127.0.0.1 -p 50052", c)
        self.assertNotIn("0.0.0.0", c)
        self.assertNotIn("169.254", c)

    def test_tunnel_args(self):
        a = G.ssh_tunnel_args("b@169.254.1.2", 50062)
        self.assertIn("127.0.0.1:50062:127.0.0.1:50052", a)
        self.assertIn("BatchMode=yes", a)

    def test_stop_only_tracked_rpc_server(self):
        c = G.rpc_stop_command()
        self.assertIn("grep -q ggml-rpc-server", c)
        self.assertNotIn("pkill", c)

    def test_friendly_error(self):
        import web_workers as W
        m = W.gguf_friendly(RuntimeError("lead exited early (rc=-6): ggml-rpc.cpp:547: Failed to connect to x"), ["EXO2"])
        self.assertEqual(m, "Couldn't reach EXO2 for the split. Try again.")
        self.assertNotIn("backtrace", W.gguf_friendly(RuntimeError("weird\n0 libggml backtrace"), []))

    def test_rpc_host_prefers_link_peer(self):
        self.assertEqual(G.rpc_host(N("exo2", "packer", 24, "169.254.103.191")), "169.254.103.191")

    def test_usage_from_timings(self):
        u = G.usage_from_timings({"prompt_tokens": 10}, {"prompt_n": 10, "prompt_ms": 200,
                                                         "predicted_n": 50, "predicted_ms": 1000})
        self.assertEqual(u["caravan"]["ttft_s"], 0.2)
        self.assertEqual(u["caravan"]["total_s"], 1.2)
        self.assertEqual(u["completion_tokens"], 50)

    def test_native_rates_preserved_for_cold_and_cached_prompts(self):
        from web_timing import reply_stats
        for cached,prompt_n,pms,read,write in [(0,38,146.569,259.2635,38.74617),(37,1,24.482,40.8463,42.46735)]:
            with self.subTest(cached=cached):
                usage={"prompt_tokens":38,"completion_tokens":7,"prompt_tokens_details":{"cached_tokens":cached}}
                timings={"prompt_n":prompt_n,"prompt_ms":pms,"prompt_per_second":read,"predicted_n":7,"predicted_ms":154.854,"predicted_per_second":write}
                stats=reply_stats(G.usage_from_timings(usage,timings))
                self.assertEqual(stats["read_tok_s"],round(read,2));self.assertEqual(stats["write_tok_s"],round(write,2))
                self.assertEqual(stats["prompt_tokens"],38);self.assertEqual(stats["cached_tokens"],cached)

    def test_invalid_native_rates_use_existing_timing_fallback(self):
        from web_timing import reply_stats
        for bad in [float("nan"),float("inf"),-1,True,"fast"]:
            with self.subTest(rate=bad):
                usage=G.usage_from_timings({"prompt_tokens":10},{"prompt_n":10,"prompt_ms":200,"predicted_n":50,"predicted_ms":1000,"prompt_per_second":bad,"predicted_per_second":bad})
                stats=reply_stats(usage);self.assertEqual(stats["read_tok_s"],50);self.assertEqual(stats["write_tok_s"],50)
                usage["caravan"].update(read_tok_s=bad,write_tok_s=bad)
                self.assertEqual(reply_stats(usage)["write_tok_s"],50)

    def test_scan_skips_shards_and_mmproj(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("a.gguf", "mmproj-a.gguf", "b-00002-of-00003.gguf", "b-00001-of-00003.gguf"):
                with open(os.path.join(d, n), "wb") as f:
                    f.truncate(60_000_000)
            ids = [g["id"] for g in G.scan_local([Path(d)])]
        self.assertEqual(sorted(ids), ["gguf/a", "gguf/b-00001-of-00003"])


class FreeRam(unittest.TestCase):
    def test_parse_and_shares(self):
        self.assertEqual(G.parse_free_gb("16384\n1003681\n"), 16.44)
        self.assertIsNone(G.parse_free_gb("garbage"))
        self.assertEqual(G.shares_from_free([16.4, 8.2]), [16.4, 8.2])
        self.assertEqual(G.shares_from_free([16.4, None, 3]), [1, 1, 1])

    def test_tunnel_cmd_check(self):
        self.assertTrue(G.is_tunnel_cmd("ssh -o BatchMode=yes -N -L 127.0.0.1:50062:127.0.0.1:50052 b@h"))
        self.assertFalse(G.is_tunnel_cmd("/usr/bin/python3 web_server.py"))


class Supervisor(unittest.TestCase):
    def test_tail_loopback_only(self):
        import supervisor
        cmd = supervisor.build_tail_command()
        self.assertEqual(cmd[cmd.index("-H") + 1], "127.0.0.1")
        self.assertNotIn("0.0.0.0", cmd)

    def test_tunnel_plan_any_n(self):
        import supervisor
        plan = supervisor.rpc_tunnel_plan(["169.254.1.2:50052", "169.254.1.3:50052"], user="b")
        self.assertEqual([a for _, a in plan], ["127.0.0.1:50062", "127.0.0.1:50063"])
        self.assertIn("127.0.0.1:50063:127.0.0.1:50052", plan[1][0])
        self.assertEqual(plan[1][0][-1], "b@169.254.1.3")


class Cli(unittest.TestCase):
    def test_stop_without_state(self):
        os.environ["CARAVAN_CLI_GGUF_STATE"] = "/tmp/nonexistent-cli-gguf.json"
        import importlib
        import gguf_split_cli
        importlib.reload(gguf_split_cli)
        self.assertEqual(gguf_split_cli.main(["stop"]), 0)


if __name__ == "__main__":
    unittest.main()


class GgufFetch(unittest.TestCase):
    def test_fetch_has_gguf_flag(self):
        src = (ROOT / "agent" / "mlx_split_fetch.py").read_text()
        self.assertIn("--gguf-file", src)
        self.assertIn("def _fetch_gguf", src)
