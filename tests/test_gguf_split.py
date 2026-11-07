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
import rpc_gate  # noqa: E402

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

    def test_scan_skips_shards_and_mmproj(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("a.gguf", "mmproj-a.gguf", "b-00002-of-00003.gguf", "b-00001-of-00003.gguf"):
                with open(os.path.join(d, n), "wb") as f:
                    f.truncate(60_000_000)
            ids = [g["id"] for g in G.scan_local([Path(d)])]
        self.assertEqual(sorted(ids), ["gguf/a", "gguf/b-00001-of-00003"])


class Gate(unittest.TestCase):
    def test_allowlist(self):
        self.assertTrue(rpc_gate.allowed("169.254.1.1", {"169.254.1.1"}))
        self.assertTrue(rpc_gate.allowed("::ffff:169.254.1.1", {"169.254.1.1"}))
        self.assertFalse(rpc_gate.allowed("192.168.1.79", {"169.254.1.1"}))

    def test_refuses_any_and_host_flag(self):
        self.assertEqual(rpc_gate.main(["--listen", "0.0.0.0:1", "--allow", "x", "--", "true"]), 2)
        self.assertEqual(rpc_gate.main(["--listen", "127.0.0.1:1", "--allow", "x", "--", "true", "-H", "0.0.0.0"]), 2)
        self.assertEqual(rpc_gate.main(["--listen", "127.0.0.1:1", "--allow", "", "--", "true"]), 2)

    def test_end_to_end_allow_and_refuse(self):
        """Gate on 127.0.0.1 forwards for an allowed IP; refuses others."""
        def free():
            s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
        gp, cp = free(), free()
        echo = ("import socket,sys;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
                "s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-p')+1])));s.listen(5)\n"
                "while 1:\n c,_=s.accept();c.sendall(c.recv(100));c.close()")
        tf = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
        tf.write(echo); tf.close()
        for allow, expect in (("127.0.0.1", b"hi"), ("10.9.9.9", b"")):
            p = subprocess.Popen([sys.executable, str(ROOT / "agent" / "rpc_gate.py"), "--listen",
                                  f"127.0.0.1:{gp}", "--allow", allow, "--", sys.executable, tf.name, "-p", str(cp)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                c = None
                for _ in range(50):
                    try:
                        c = socket.create_connection(("127.0.0.1", gp), timeout=1); break
                    except OSError:
                        time.sleep(0.1)
                time.sleep(0.3)
                try:
                    c.sendall(b"hi"); c.settimeout(3); got = c.recv(10)
                except OSError:
                    got = b""
                self.assertEqual(got, expect)
            finally:
                p.terminate(); p.wait(5)


class Supervisor(unittest.TestCase):
    def test_link_address(self):
        import supervisor
        self.assertEqual(supervisor.link_address("inet 127.0.0.1\n inet 169.254.103.191 netmask"), "169.254.103.191")
        self.assertIsNone(supervisor.link_address("inet 192.168.1.38"))

    def test_fail_closed(self):
        import supervisor
        with self.assertRaises(RuntimeError):
            supervisor.rpc_bind_and_allow("0.0.0.0", ["1.2.3.4"], log=lambda m: None)
        os.environ.pop("CARAVAN_RPC_ALLOW", None)
        with self.assertRaises(RuntimeError):
            supervisor.rpc_bind_and_allow("169.254.1.2", [], log=lambda m: None)
        cmd = supervisor.build_tail_command("169.254.1.2", ["169.254.1.1"])
        self.assertNotIn("0.0.0.0", cmd)
        self.assertIn("169.254.1.2:50052", cmd)


if __name__ == "__main__":
    unittest.main()
