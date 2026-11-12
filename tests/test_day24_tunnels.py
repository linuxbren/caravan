"""Worker SSH tunnels: reuse our leftover, never kill a foreign process, plain errors."""
from __future__ import annotations

import io
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "agent"))

import web_tunnels as T  # noqa: E402
import web_remote_adopt as A  # noqa: E402
import caravan_update as U  # noqa: E402
from web_workers import WorkerManager  # noqa: E402

OURS = (
    "ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 "
    "-N -L 8194:127.0.0.1:8194 caravan-dcbb9f1b9cd8cab4dcfa61388dffe4ec"
)
TARGET = "caravan-dcbb9f1b9cd8cab4dcfa61388dffe4ec"
BRENDEN_ERR = (
    "starting single-Mini worker on prf-hays-exo02 "
    "(/Users/brenden/.caravan/mlx-models/mlx-community--Qwen2.5-Coder-1.5B-Instruct-4bit) "
    "error: ssh tunnel to caravan-dcbb9f1b9cd8cab4dcfa61388dffe4ec failed: "
    "bind [127.0.0.1]:8194: Address already in use "
    "channel_setup_fwd_listener_tcpip: cannot listen to port: 8194 "
    "Could not request local forwarding."
)


class FakeProc:
    def __init__(self, pid=99, rc=None, err=b""):
        self.pid = pid
        self._rc = rc
        self.stderr = io.BytesIO(err)

    def poll(self):
        return self._rc


class Match(unittest.TestCase):
    def test_matches_the_live_command_line(self):
        self.assertTrue(T.tunnel_matches(OURS, TARGET, 8194))
        self.assertTrue(A.tunnel_matches(OURS, TARGET, 8194))
        self.assertTrue(U._is_our_tunnel(OURS, TARGET, 8194))

    def test_rejects_other_host_port_or_program(self):
        self.assertFalse(T.tunnel_matches(OURS, "other-host", 8194))
        self.assertFalse(T.tunnel_matches(OURS, TARGET, 8294))
        self.assertFalse(T.tunnel_matches(
            "python /opt/other --port 8194", TARGET, 8194))
        self.assertFalse(T.tunnel_matches(
            "ssh -N -L 8194:127.0.0.1:8194 someone-else", TARGET, 8194))
        self.assertFalse(U._is_our_tunnel(
            "ssh -N -L 8194:127.0.0.1:8194 someone-else", TARGET, 8194))


class Ensure(unittest.TestCase):
    def test_reuses_our_working_forward(self):
        sent = []
        spawned = []

        def inspect(pid):
            return OURS if pid == 84557 else ""

        got = T.ensure_forward(
            TARGET, 8194,
            inspect=inspect,
            lsof=lambda port: [84557],
            probe=lambda: True,
            popen=lambda *a, **k: spawned.append(a) or FakeProc(),
            send=lambda pid, sig: sent.append((pid, sig)),
            pause=lambda s: None,
            spawn_wait=0,
        )
        self.assertTrue(got["reused"])
        self.assertEqual(got["pid"], 84557)
        self.assertIsNone(got["proc"])
        self.assertEqual(spawned, [])
        self.assertEqual(sent, [])

    def test_replaces_our_broken_forward(self):
        sent = []
        alive = {"84557": OURS}

        def inspect(pid):
            return alive.get(str(pid), "")

        def send(pid, sig):
            sent.append((pid, sig))
            if pid == 84557:
                alive.pop("84557", None)

        got = T.ensure_forward(
            TARGET, 8194,
            inspect=inspect,
            lsof=lambda port: [84557] if "84557" in alive else [],
            probe=lambda: False,
            popen=lambda *a, **k: FakeProc(pid=9001, rc=None),
            send=send,
            pause=lambda s: None,
            spawn_wait=0,
        )
        self.assertFalse(got["reused"])
        self.assertEqual(got["pid"], 9001)
        self.assertTrue(sent)
        self.assertEqual(sent[0][0], 84557)
        self.assertIn(sent[0][1], (signal.SIGTERM, signal.SIGKILL))

    def test_never_kills_a_foreign_listener(self):
        sent = []

        def inspect(pid):
            return "nginx -c /etc/nginx.conf" if pid == 77 else ""

        with self.assertRaises(T.TunnelError) as ctx:
            T.ensure_forward(
                TARGET, 8194,
                inspect=inspect,
                lsof=lambda port: [77],
                probe=lambda: False,
                popen=lambda *a, **k: FakeProc(),
                send=lambda pid, sig: sent.append((pid, sig)),
                pause=lambda s: None,
                spawn_wait=0,
            )
        self.assertEqual(sent, [])
        plain = str(ctx.exception)
        self.assertIn("Couldn't start the model", plain)
        self.assertNotIn("nginx", plain)
        self.assertNotIn(TARGET, plain)
        self.assertNotIn("prf-hays", plain)

    def test_bind_failure_is_a_plain_line(self):
        raw = (
            b"bind [127.0.0.1]:8194: Address already in use\n"
            b"channel_setup_fwd_listener_tcpip: cannot listen to port: 8194\n"
            b"Could not request local forwarding.\n"
        )
        with self.assertRaises(T.TunnelError) as ctx:
            T.ensure_forward(
                TARGET, 8194,
                inspect=lambda pid: "",
                lsof=lambda port: [],
                probe=lambda: False,
                popen=lambda *a, **k: FakeProc(pid=3, rc=1, err=raw),
                send=lambda *a: None,
                pause=lambda s: None,
                spawn_wait=0,
            )
        plain = str(ctx.exception)
        self.assertEqual(
            plain,
            "Couldn't start the model on the other Mac. Try loading again.",
        )
        self.assertNotIn("8194", plain)
        self.assertNotIn(TARGET, plain)
        self.assertNotIn("Address already in use", plain)
        self.assertIn("Address already in use", ctx.exception.detail)


class PlainWording(unittest.TestCase):
    def test_status_drops_hostname_and_path(self):
        out = T.plain_load_status(BRENDEN_ERR, mac="2nd Mac")
        self.assertEqual(out, "starting single-Mini worker on 2nd Mac")
        self.assertNotIn("prf-hays", out)
        self.assertNotIn("/Users/", out)
        self.assertNotIn("caravan-dcbb", out)

    def test_tunnel_error_uses_friendly_mac(self):
        raw = "ssh tunnel to caravan-dcbb9f1b9cd8cab4dcfa61388dffe4ec failed: Address already in use"
        out = T.plain_tunnel_error(raw, mac="2nd Mac")
        self.assertEqual(out, "Couldn't start the model on the 2nd Mac. Try loading again.")
        self.assertNotIn("caravan-", out)
        self.assertNotIn("prf-hays", out)


class WorkerManagerTunnel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mgr = WorkerManager(state_dir=Path(self.tmp.name), lead_port=8194)
        self.node = dict(
            id="n2", role="packer",
            label="prf-hays-exo02",
            ssh=TARGET, host="prf-hays-exo02.local",
            repo="~/cv3",
        )

    def test_ensure_reuses_and_records_pid(self):
        got = {"pid": 84557, "proc": None, "reused": True}
        with mock.patch("web_tunnels.ensure_forward", return_value=got) as ens:
            self.mgr._ensure_tunnel(self.node)
        ens.assert_called_once()
        self.assertEqual(ens.call_args[0][0], TARGET)
        self.assertEqual(ens.call_args[0][1], 8194)
        self.assertIsNone(self.mgr._tunnel_proc)
        self.assertEqual(self.mgr._adopted_tunnel, (84557, TARGET, 8194))

    def test_note_is_friendly_and_has_no_path(self):
        with mock.patch("web_nodes.nodes_from_config", return_value=[
            dict(id="n1", role="lead", label="1st Mac"),
            self.node,
        ]):
            self.mgr._worker_node = self.node
            self.mgr._note(
                f"starting single-Mini worker on {self.node['label']} "
                f"(/Users/brenden/.caravan/mlx-models/qwen)"
            )
        msg = self.mgr.snapshot()["progress"][-1]["msg"]
        self.assertEqual(msg, "starting single-Mini worker on 2nd Mac")
        self.assertNotIn("prf-hays", msg)
        self.assertNotIn("/Users/", msg)
        self.assertNotIn("EXO", msg)

    def test_load_error_is_plain_one_liner(self):
        with mock.patch("web_nodes.nodes_from_config", return_value=[
            dict(id="n1", role="lead", label="1st Mac"),
            self.node,
        ]):
            self.mgr._worker_node = self.node
            # Simulate the switch() except path by calling the same helpers.
            plain = T.plain_tunnel_error(BRENDEN_ERR, mac=self.mgr._mac_name(self.node))
            self.mgr._set(status="error", error=plain)
            self.mgr._note("error: " + plain)
        snap = self.mgr.snapshot()
        self.assertEqual(
            snap["error"],
            "Couldn't start the model on the 2nd Mac. Try loading again.",
        )
        self.assertNotIn("prf-hays", snap["progress"][-1]["msg"])
        self.assertNotIn(TARGET, snap["progress"][-1]["msg"])
        self.assertNotIn("/Users/", json.dumps(snap["progress"]))

    def test_stop_does_not_kill_a_foreign_pid(self):
        sent = []
        self.mgr._adopted_tunnel = (77, TARGET, 8194)
        with mock.patch("web_tunnels.command_of", return_value="nginx"), \
             mock.patch("web_tunnels.listeners_on_port", return_value=[77]), \
             mock.patch("os.kill", side_effect=lambda pid, sig: sent.append((pid, sig))):
            self.mgr._stop_tunnel()
        self.assertEqual(sent, [])
        self.assertIsNone(self.mgr._adopted_tunnel)


    def test_switch_surfaces_plain_error_without_detail(self):
        sent = T.TunnelError(
            "Couldn't start the model on the 2nd Mac. Try loading again.",
            detail="ssh tunnel to caravan-dcbb9f1b9cd8cab4dcfa61388dffe4ec failed: Address already in use",
        )
        entry = dict(
            id="qwen-tiny", name="Qwen tiny", source="mlx",
            lead_path="/tmp/fake-model", available_lead=True, usable=True,
            placement={"mode": "one"},
        )
        self.mgr._worker_node = self.node
        with mock.patch.object(self.mgr, "_do_switch", side_effect=sent), \
             mock.patch.object(self.mgr, "_deny_managed_service", return_value=None), \
             mock.patch("web_nodes.nodes_from_config", return_value=[
                 dict(id="n1", role="lead", label="1st Mac"),
                 self.node,
             ]):
            snap = self.mgr.switch("qwen-tiny", wait=True, entry=entry)
        self.assertEqual(
            snap["error"],
            "Couldn't start the model on the 2nd Mac. Try loading again.",
        )
        self.assertFalse(snap.get("error_detail"))
        self.assertNotIn(TARGET, json.dumps(snap))
        self.assertNotIn("Address already in use", json.dumps(snap))
        self.assertNotIn("prf-hays", json.dumps(snap["progress"]))

class UpdateCleansLocalTunnel(unittest.TestCase):
    def test_stops_only_our_recorded_forward(self):
        sent = []
        cmds = {84557: OURS, 77: "nginx"}
        U._stop_owned_local_tunnels(
            {"ssh": TARGET, "tunnel_pid": 84557},
            8194,
            inspect=lambda pid: cmds.get(pid, ""),
            send=lambda pid, sig: sent.append((pid, sig)) or cmds.pop(pid, None),
            pause=lambda s: None,
        )
        self.assertEqual(sent[0][0], 84557)
        sent.clear()
        U._stop_owned_local_tunnels(
            {"ssh": TARGET, "tunnel_pid": 77},
            8194,
            inspect=lambda pid: cmds.get(pid, "nginx"),
            send=lambda pid, sig: sent.append((pid, sig)),
            pause=lambda s: None,
        )
        self.assertEqual(sent, [])

    def test_stop_model_workers_stops_local_tunnel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        (home / ".caravan" / "web-ui").mkdir(parents=True)
        (home / ".caravan" / "web-ui" / "remote-worker.json").write_text(json.dumps({
            "ssh": TARGET, "tunnel_pid": 84557, "pid": 123, "repo": "~/cv3",
        }))
        (home / ".caravan" / "web-ui" / "last-model.json").write_text("{}")
        sent = []
        U.stop_model_workers(
            str(home), "/repo",
            lead_port=8194,
            inspect=lambda pid: OURS if pid == 84557 else "",
            send=lambda pid, sig: sent.append((pid, sig)),
            pause=lambda s: None,
            run_ssh=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        self.assertTrue(any(pid == 84557 for pid, _sig in sent))
        # last-model.json is left alone
        self.assertTrue((home / ".caravan" / "web-ui" / "last-model.json").is_file())


class DocsMention(unittest.TestCase):
    def test_docs_cover_reuse_and_plain_error(self):
        day = (ROOT / "docs/DAY24.md").read_text()
        web = (ROOT / "docs/WEB.md").read_text()
        notes = (ROOT / "docs/release-notes/day24.md").read_text()
        phrase = "Couldn't start the model on the 2nd Mac. Try loading again."
        self.assertIn(phrase, day)
        self.assertIn(phrase, web)
        self.assertIn("2nd Mac", day)
        self.assertNotIn("prf-hays", day)
        self.assertNotIn("prf-hays", web)
        self.assertIn("reuse", day.lower())
        self.assertIn("reuse", notes.lower())
