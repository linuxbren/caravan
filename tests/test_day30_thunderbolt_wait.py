"""Day 30 rerun: after a power loss the restore picked Wi-Fi because the
Thunderbolt link-local addresses were not up yet. Boot loads now wait up to
a minute for Thunderbolt when it worked before, re-reading the addresses on
each try; a split stuck on Wi-Fi gets a plain note once Thunderbolt answers.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))

import peer_route as PR  # noqa: E402
import link_upgrade as LU  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

WIFI_L = {"dev": "en1", "kind": "wifi", "ip": "192.168.1.79", "prefix": 24}
WIFI_R = {"dev": "en1", "kind": "wifi", "ip": "192.168.1.38", "prefix": 24}


def tb(ip):
    return {"dev": "en2", "kind": "thunderbolt", "ip": ip, "prefix": 16}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Net:
    """Both Macs' interfaces as the reboot brings them up, try by try."""

    def __init__(self, plan):
        self.plan = list(plan)   # [(local, remote), ...]; last entry repeats
        self.reads = 0

    def now(self):
        return self.plan[min(self.reads, len(self.plan) - 1)]

    def local(self, run=None):
        return list(self.now()[0])

    def remote(self, stdout):
        rows = list(self.now()[1])
        self.reads += 1
        return rows

    def run(self, argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "x" + PR.MARK + "y", "")


class WaitForThunderbolt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"CARAVAN_PEER_ROUTES": str(Path(self.tmp.name) / "routes.json")})
        self.env.start()
        self.addCleanup(self.env.stop)
        PR._mem.clear()
        self.addCleanup(PR._mem.clear)
        self.clock = Clock()

    def go(self, net, **kw):
        with mock.patch.object(PR, "local_inventory", net.local), \
             mock.patch.object(PR, "parse_inventory", net.remote), \
             mock.patch.object(PR, "host_opts", lambda *a, **k: []):
            return PR.pick_waiting("peer", label="2nd Mac", run=net.run, sleep=self.clock.sleep,
                                   now=self.clock, rtt=lambda a, i=None, l=None: 0.4,
                                   identity=lambda t, a: (True, "peer"), **kw)

    def remember_thunderbolt(self):
        PR._save("peer", {"kind": "thunderbolt", "address": "169.254.65.112", "checked_at": self.clock.t - 3600})
        PR._mem.clear()

    def test_late_thunderbolt_is_found_with_new_addresses(self):
        self.remember_thunderbolt()
        before = (([WIFI_L], [WIFI_R]))
        after = ([tb("169.254.17.245"), WIFI_L], [tb("169.254.6.11"), WIFI_R])
        net = Net([before, before, before, after])
        notes = []
        r = self.go(net, on_wait=lambda w, lim: notes.append(w))
        self.assertEqual(r["kind"], "thunderbolt")
        self.assertEqual(r["address"], "169.254.6.11")          # the address after reboot
        self.assertEqual(r["thunderbolt_wait"]["tries"], 4)
        self.assertTrue(r["thunderbolt_wait"]["found"])
        self.assertEqual(len(notes), 3)
        self.assertIsNone(r.get("warning"))
        self.assertEqual(json.loads(Path(os.environ["CARAVAN_PEER_ROUTES"]).read_text())["peer"]["kind"],
                         "thunderbolt")

    def test_gives_up_after_the_limit_with_plain_warning(self):
        self.remember_thunderbolt()
        net = Net([([WIFI_L], [WIFI_R])])
        r = self.go(net, wait_s=60)
        self.assertEqual(r["kind"], "wifi")
        self.assertFalse(r["thunderbolt_wait"]["found"])
        self.assertLessEqual(r["thunderbolt_wait"]["waited_s"], 65)
        self.assertIn("did not answer within 60s; using Wi-Fi", r["warning"])
        self.assertIn("2nd Mac", r["warning"])
        self.assertTrue(PR.recorded("peer").get("thunderbolt_seen_at"))   # still remembered

    def test_no_wait_when_thunderbolt_never_worked(self):
        net = Net([([WIFI_L], [WIFI_R])])
        r = self.go(net)
        self.assertEqual(r["kind"], "wifi")
        self.assertNotIn("thunderbolt_wait", r)
        self.assertEqual(net.reads, 1)

    def test_no_wait_when_thunderbolt_is_up_at_once(self):
        self.remember_thunderbolt()
        net = Net([([tb("169.254.1.1"), WIFI_L], [tb("169.254.1.2"), WIFI_R])])
        r = self.go(net)
        self.assertEqual((r["kind"], net.reads, r["thunderbolt_wait"]["tries"]), ("thunderbolt", 1, 1))

    def test_old_memory_does_not_wait(self):
        PR._save("peer", {"kind": "thunderbolt", "checked_at": self.clock.t - PR.TB_REMEMBER_S - 10})
        PR._mem.clear()
        net = Net([([WIFI_L], [WIFI_R])])
        self.assertNotIn("thunderbolt_wait", self.go(net))

    def test_cancel_during_wait(self):
        self.remember_thunderbolt()
        net = Net([([WIFI_L], [WIFI_R])])

        def stop(w, lim):
            raise RuntimeError("load stopped")
        with self.assertRaises(RuntimeError):
            self.go(net, on_wait=stop)

    def test_wifi_pick_keeps_thunderbolt_memory(self):
        self.remember_thunderbolt()
        PR._save("peer", {"kind": "wifi", "checked_at": self.clock.t})
        self.assertTrue(PR.thunderbolt_seen_at("peer"))

    def test_worker_uses_the_wait(self):
        src = english_source(REPO / "proxy" / "web_workers.py")
        self.assertIn("wait_thunderbolt=True, on_wait=_tb_wait", src)
        self.assertIn("Waiting for the Thunderbolt link to", src)


class FakeMgr:
    def __init__(self, meta_path):
        self._lock = threading.Lock()
        self.state = {"status": "ready", "split": True, "model_id": "gguf/m", "progress": []}
        self.meta_path = meta_path
        self.notes = []

    def snapshot(self):
        with self._lock:
            return dict(self.state)

    def _gguf_meta_path(self):
        return self.meta_path

    def _note(self, m):
        self.notes.append(m)


class LateThunderboltNote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.meta = Path(self.tmp.name) / "gguf.json"
        self.meta.write_text(json.dumps({"lead_pid": 11, "tunnels": [
            {"pid": 1, "port": 50062, "ssh": "peer", "id": "paired_x", "route": "wifi"}]}))
        self.mgr = FakeMgr(self.meta)
        self.up = False
        self.mon = LU.Monitor(self.mgr, probe=lambda t: self.up, name_for=lambda t: "the 2nd Mac")
        self.mon._friendly = lambda t: "the 2nd Mac"

    def test_note_once_when_thunderbolt_answers(self):
        self.assertEqual(self.mon.tick(), [])
        self.up = True
        notes = self.mon.tick()
        self.assertEqual(len(notes), 1)
        self.assertIn("Thunderbolt to the 2nd Mac is working now", notes[0])
        self.assertIn("still using Wi-Fi", notes[0])
        self.assertIn("Unload and Load", notes[0])
        self.assertEqual(self.mgr.state["link_note"], notes[0])
        self.assertEqual(self.mon.tick(), [])        # once per load
        self.assertEqual(len(self.mgr.notes), 1)

    def test_never_reloads(self):
        self.up = True
        self.mgr.load = mock.Mock()
        self.mgr.stop = mock.Mock()
        self.mon.tick()
        self.mgr.load.assert_not_called()
        self.mgr.stop.assert_not_called()

    def test_thunderbolt_split_is_left_alone(self):
        self.meta.write_text(json.dumps({"lead_pid": 11, "tunnels": [{"ssh": "peer", "route": "thunderbolt"}]}))
        probe = mock.Mock(return_value=True)
        self.mon.probe = probe
        self.assertEqual(self.mon.tick(), [])
        probe.assert_not_called()

    def test_not_ready_is_left_alone(self):
        self.up = True
        self.mgr.state["status"] = "starting_lead"
        self.assertEqual(self.mon.tick(), [])

    def test_note_cleared_after_a_new_load(self):
        self.up = True
        self.mon.tick()
        self.meta.write_text(json.dumps({"lead_pid": 12, "tunnels": [{"ssh": "peer", "route": "thunderbolt"}]}))
        self.mon.tick()
        self.assertIsNone(self.mgr.state["link_note"])

    def test_server_starts_the_monitor(self):
        self.assertIn("_LU.Monitor(app.mgr)", english_source(REPO / "proxy" / "web_server.py"))


if __name__ == "__main__":
    unittest.main()
