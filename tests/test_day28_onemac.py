"""Day 28: one-Mac Topology hides Balance and Thunderbolt; a stopped
or stale Mac shows as offline instead of live."""
from __future__ import annotations

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
import web_nodes as N  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

HTML = english_source(ROOT / "proxy" / "web" / "index.html")
NODE = shutil.which("node")


class WebRunningTest(unittest.TestCase):
    def test_false_when_nothing_listens(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(N.web_is_running(home=td, timeout=0.2))

    def test_reads_port_from_plan_and_detects_up(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            httpd, port = _serve({"status": "ok"})
            self.addCleanup(httpd.shutdown)
            self.addCleanup(httpd.server_close)
            plan = home / ".caravan" / "services" / "web.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(json.dumps({"port": port}))
            self.assertTrue(N.web_is_running(home=home, timeout=1))

    def test_down_on_custom_port_is_off(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            plan = home / ".caravan" / "services" / "web.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(json.dumps({"port": 1}))  # privileged, nothing we own
            self.assertFalse(N.web_is_running(home=home, timeout=0.3))


class RemoteCommandTest(unittest.TestCase):
    def test_command_checks_status_before_node_stats(self):
        cmd = N.remote_stats_command("~/cv3")
        self.assertIn("/usr/bin/python3 -c ", cmd)
        self.assertIn("/api/status", cmd)
        self.assertIn("Caravan is off", cmd)
        self.assertIn("node_stats.py", cmd)
        self.assertIn("~/cv3", cmd)

    def test_script_reports_off_when_web_is_down(self):
        cmd = N.remote_stats_command(str(ROOT))
        env = {**os.environ, "HOME": tempfile.mkdtemp()}
        self.addCleanup(lambda: shutil.rmtree(env["HOME"], ignore_errors=True))
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(data["offline"])
        self.assertEqual(data["error"], "Caravan is off")
        self.assertNotIn("cpu_pct", data)

    def test_script_runs_node_stats_when_web_is_up(self):
        httpd, port = _serve({"status": "ok", "worker": {}})
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            repo = Path(td) / "repo"
            (repo / "proxy").mkdir(parents=True)
            (repo / "proxy" / "node_stats.py").write_text(
                "import json,sys\njson.dump({\"cpu_pct\": 2.5, \"temp_c\": 34}, sys.stdout)\n"
                "sys.stdout.write('\\n')\n"
            )
            plan = home / ".caravan" / "services" / "web.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(json.dumps({"port": port}))
            cmd = N.remote_stats_command(str(repo))
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                env={**os.environ, "HOME": str(home)}, timeout=10,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(data["cpu_pct"], 2.5)
            self.assertEqual(data["temp_c"], 34)
            self.assertFalse(data.get("offline"))


class GatherOfflineTest(unittest.TestCase):
    NODE = {"id": "exo2", "label": "the other Mac", "role": "packer",
            "host": "other", "ssh": "other", "repo": "~/cv3"}

    def test_caravan_off_json_is_offline_without_stats(self):
        def ssh_fn(node, cmd, timeout=25):
            self.assertIn("/api/status", cmd)
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"offline": True, "error": "Caravan is off", "cpu_pct": 1.8}) + "\n",
                stderr="",
            )
        out = N.gather_node_stats(self.NODE, ssh_fn=ssh_fn)
        self.assertTrue(out["offline"])
        self.assertEqual(out["error"], "Caravan is off")
        self.assertNotIn("cpu_pct", out)

    def test_live_stats_still_pass_through(self):
        def ssh_fn(node, cmd, timeout=25):
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"cpu_pct": 3.0, "temp_c": 40, "ram": {"total_gb": 64}}) + "\n",
                stderr="",
            )
        out = N.gather_node_stats(self.NODE, ssh_fn=ssh_fn)
        self.assertFalse(out["offline"])
        self.assertEqual(out["cpu_pct"], 3.0)

    def test_one_live_one_off_counts_as_one_online(self):
        nodes = [
            {"id": "exo1", "label": "This Mac", "role": "lead", "host": "local"},
            self.NODE,
        ]

        def local():
            return {"cpu_pct": 1, "ram": {"total_gb": 64, "used_gb": 8}}

        def ssh_fn(node, cmd, timeout=25):
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"offline": True, "error": "Caravan is off"}) + "\n",
                stderr="",
            )

        out = N.gather_all(nodes, ssh_fn=ssh_fn, local_gather=local)
        self.assertEqual(len(N.online_nodes(out)), 1)
        self.assertEqual(N.online_nodes(out)[0]["id"], "exo1")
        self.assertTrue(out[1]["offline"])


class PageContractTest(unittest.TestCase):
    def test_html_loads_helpers_and_hides_sections(self):
        self.assertIn('<script src="/topo_live.js"></script>', HTML)
        self.assertLess(HTML.index('<script src="/topo_live.js"></script>'),
                        HTML.index("function syncSplitSections"))
        self.assertIn('id="balancePanel"', HTML)
        self.assertIn('id="thunderboltPanel"', HTML)
        self.assertIn("el.hidden = !show", HTML)
        self.assertIn("applyNodePresence", HTML)
        self.assertEqual(N.STALE_AFTER_S * 1000, 15000)

    @unittest.skipUnless(NODE, "node not installed")
    def test_onemac_harness(self):
        r = subprocess.run(
            [NODE, str(ROOT / "tests/js/onemac_harness.js")],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok onemac", r.stdout)


def _serve(payload):
    body = json.dumps(payload).encode()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] != "/api/status":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


if __name__ == "__main__":
    unittest.main()
