"""N-Mac peer updates, failure help, Tailscale apply, and Try again."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))

import caravan_update_check as UC  # noqa: E402
import caravan_update_peers as P  # noqa: E402
import caravan as cli  # noqa: E402

from test_day26_update_check import (  # noqa: E402
    NEW, OLD, opener_for, write_package,
)


def Result(code=0, stdout="", stderr=""):
    m = mock.Mock()
    m.returncode = code
    m.stdout = stdout
    m.stderr = stderr
    return m


def peer(i, name=None, ssh=None):
    label = P.ordinal_mac(i)
    return {
        "id": name or f"mac-{i}",
        "label": label,
        "ssh": ssh or f"caravan-mac-{i}",
        "host": ssh or f"caravan-mac-{i}",
        "role": "packer",
        "repo": "~/.caravan/src/caravan",
        "index": i,
    }


class ScriptedSSH:
    """Answer SSH by target and by a short kind: probe, update, or ref."""

    def __init__(self, plan):
        # plan[target] = {"probe": Result, "update": Result, "ref": "hex" or Result or None}
        self.plan = plan
        self.calls = []

    def _kind(self, command):
        command = command or ""
        if command.strip() == "true":
            return "probe"
        if "caravan" in command and "update" in command:
            return "update"
        if ".caravan-package" in command or "cat " in command:
            return "ref"
        return "other"

    def __call__(self, argv, capture_output=True, text=True, timeout=None):
        self.calls.append(argv)
        # ssh [opts] target command
        i = 1
        target = None
        command = ""
        while i < len(argv):
            if argv[i] in ("-o", "-F", "-p", "-l", "-i"):
                i += 2
                continue
            if argv[i].startswith("-"):
                i += 1
                continue
            target = argv[i]
            command = argv[i + 1] if i + 1 < len(argv) else ""
            break
        rec = self.plan.get(target) or {}
        kind = self._kind(command)
        val = rec.get(kind, rec.get("default"))
        if val is None:
            return Result(1, "", "unreachable")
        if isinstance(val, Exception):
            raise val
        if isinstance(val, str):
            return Result(0, val + "\n")
        return val


class OrdinalAndDiscoverTests(unittest.TestCase):
    def test_ordinal_names_are_friendly(self):
        self.assertEqual(P.ordinal_mac(0), "1st Mac")
        self.assertEqual(P.ordinal_mac(1), "2nd Mac")
        self.assertEqual(P.ordinal_mac(2), "3rd Mac")
        self.assertEqual(P.ordinal_mac(3), "4th Mac")
        self.assertEqual(P.ordinal_mac(10), "11th Mac")
        self.assertEqual(P.ordinal_mac(20), "21st Mac")
        self.assertEqual(P.ordinal_mac(21), "22nd Mac")
        self.assertEqual(P.ordinal_mac(22), "23rd Mac")

    def test_discover_labels_2nd_3rd_4th_without_hostnames(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            nodes = [
                {"id": "lead", "host": "local", "role": "lead", "label": "My Mac"},
                {"id": "a", "host": "alpha", "ssh": "caravan-alpha", "role": "packer"},
                {"id": "b", "host": "beta", "ssh": "caravan-beta", "role": "packer"},
                {"id": "c", "host": "gamma", "ssh": "caravan-gamma", "role": "packer"},
            ]
            peers = P.discover_peers(home, nodes)
            self.assertEqual([p["label"] for p in peers], ["2nd Mac", "3rd Mac", "4th Mac"])
            for item in peers:
                self.assertNotIn("alpha", item["label"])
                self.assertNotIn("beta", item["label"])
                self.assertNotIn("gamma", item["label"])
                self.assertFalse(item["label"].startswith("caravan-"))
            # Public rows (what the page shows) never include a hostname.
            rows = [P._row(item, phase="waiting", can_retry=False) for item in peers]
            blob = json.dumps(rows)
            self.assertNotIn("alpha", blob)
            self.assertNotIn("caravan-", blob)
            self.assertNotIn("host", blob)

    def test_discover_dedupes_and_skips_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ui = home / ".caravan" / "web-ui"
            ui.mkdir(parents=True)
            (ui / "remote-worker.json").write_text(json.dumps({
                "ssh": "caravan-alpha", "host": "alpha",
            }))
            nodes = [
                {"host": "local"},
                {"ssh": "caravan-alpha", "host": "alpha", "id": "a"},
                {"ssh": "caravan-alpha", "host": "alpha", "id": "dup"},
                {"ssh": "caravan-beta", "host": "beta", "id": "b"},
            ]
            peers = P.discover_peers(home, nodes)
            self.assertEqual(len(peers), 2)
            self.assertEqual([p["label"] for p in peers], ["2nd Mac", "3rd Mac"])

    def test_peer_command_uses_env_not_local_only_flag(self):
        cmd = P.peer_update_command()
        self.assertIn("CARAVAN_UPDATE_LOCAL=1", cmd)
        self.assertNotIn("--local-only", cmd)
        self.assertIn("caravan", cmd)
        self.assertIn("update", cmd)


class FailureHelpTests(unittest.TestCase):
    def test_four_kinds_use_friendly_name_and_plain_steps(self):
        for kind in ("offline", "failed", "still_old", "no_model"):
            steps = P.failure_help(kind, "2nd Mac")
            self.assertGreaterEqual(len(steps), 3, kind)
            blob = " ".join(steps)
            self.assertIn("2nd Mac", blob)
            self.assertNotIn("hostname", blob.lower())
            self.assertNotIn("ssh", blob.lower())
            self.assertNotIn("127.0.0.1", blob)
            self.assertNotIn("caravan-", blob)
            if kind != "no_model":
                self.assertTrue(any("Try again" in s for s in steps), kind)
                self.assertTrue(any("caravan update" in s for s in steps), kind)
                self.assertTrue(any("on and awake" in s for s in steps), kind)
                self.assertTrue(any("Tailscale" in s for s in steps), kind)
            else:
                self.assertTrue(any("model didn't come back" in s for s in steps))
                self.assertTrue(any("load your model" in s for s in steps))
                self.assertTrue(any("caravan update" in s for s in steps))

    def test_row_attaches_help_and_try_again(self):
        node = peer(1)
        for kind, phase in (
            ("offline", "offline"),
            ("failed", "failed"),
            ("still_old", "still_old"),
            ("no_model", "no_model"),
        ):
            row = P._row(node, phase=phase, kind=kind)
            self.assertEqual(row["label"], "2nd Mac")
            self.assertTrue(row["can_retry"])
            self.assertEqual(row["help"], P.failure_help(kind, "2nd Mac"))
            self.assertNotIn(NEW, json.dumps(row))
            self.assertNotIn("caravan-mac", row["label"])

    def test_update_peer_offline(self):
        node = peer(1)
        runner = ScriptedSSH({node["ssh"]: {"probe": Result(1)}})
        row = P.update_peer(node, expected=NEW, runner=runner)
        self.assertEqual(row["phase"], "offline")
        self.assertEqual(row["status"], "couldn't be reached")
        self.assertTrue(row["can_retry"])
        self.assertIn("on and awake", " ".join(row["help"]))

    def test_update_peer_failed(self):
        node = peer(1)
        runner = ScriptedSSH({
            node["ssh"]: {"probe": Result(0), "update": Result(2, "", "boom")},
        })
        row = P.update_peer(node, expected=NEW, runner=runner)
        self.assertEqual(row["phase"], "failed")
        self.assertEqual(row["status"], "update failed")
        self.assertTrue(row["can_retry"])
        self.assertIn("didn't finish", " ".join(row["help"]))

    def test_update_peer_still_old(self):
        node = peer(1)
        runner = ScriptedSSH({
            node["ssh"]: {
                "probe": Result(0),
                "update": Result(0),
                "ref": OLD,
            },
        })
        row = P.update_peer(node, expected=NEW, runner=runner)
        self.assertEqual(row["phase"], "still_old")
        self.assertEqual(row["status"], "still on the previous version")
        self.assertTrue(row["can_retry"])
        self.assertIn("previous version", " ".join(row["help"]))

    def test_update_peer_done(self):
        node = peer(1)
        runner = ScriptedSSH({
            node["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW},
        })
        row = P.update_peer(node, expected=NEW, runner=runner)
        self.assertEqual(row["phase"], "done")
        self.assertFalse(row["can_retry"])
        self.assertEqual(row["help"], [])


class CheckPeersAndFanOutTests(unittest.TestCase):
    def test_check_peers_marks_behind_offline_and_current(self):
        peers = [peer(1), peer(2), peer(3)]
        runner = ScriptedSSH({
            peers[0]["ssh"]: {"ref": OLD},
            peers[1]["ssh"]: {"ref": Result(1)},
            peers[2]["ssh"]: {"ref": NEW},
        })
        rows = P.check_peers(peers, NEW, runner=runner)
        self.assertEqual(rows[0]["phase"], "behind")
        self.assertTrue(rows[0]["behind"])
        self.assertTrue(rows[0]["help"])
        self.assertEqual(rows[1]["phase"], "offline")
        self.assertFalse(rows[1].get("behind"))
        self.assertEqual(rows[2]["phase"], "current")
        self.assertFalse(rows[2]["behind"])
        self.assertTrue(P.any_behind(rows))

    def test_n_macs_update_continues_after_failures(self):
        peers = [peer(1), peer(2), peer(3)]
        runner = ScriptedSSH({
            peers[0]["ssh"]: {"probe": Result(1)},  # offline
            peers[1]["ssh"]: {"probe": Result(0), "update": Result(2)},  # failed
            peers[2]["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW},
        })
        seen = []
        rows = P.update_other_macs(
            Path("/tmp"), peers, expected=NEW, runner=runner,
            on_progress=lambda r: seen.append(r["phase"]),
        )
        self.assertEqual([r["phase"] for r in rows], ["offline", "failed", "done"])
        self.assertEqual([r["label"] for r in rows], ["2nd Mac", "3rd Mac", "4th Mac"])
        self.assertTrue(rows[0]["help"] and rows[1]["help"])
        self.assertFalse(rows[2]["help"])
        self.assertEqual(len(rows), 3)

    def test_apply_job_updates_peers_first_then_local_and_keeps_going(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = write_package(Path(tmp) / "repo", ref=OLD)
            home.mkdir()
            UC.save_progress(home, {"expected": NEW, "old": OLD, "phase": "updating"})
            peers = [peer(1), peer(2)]
            runner = ScriptedSSH({
                peers[0]["ssh"]: {"probe": Result(1)},
                peers[1]["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW},
            })

            def local_ok(repo, **kwargs):
                self.assertTrue(kwargs.get("local_only", True))
                write_package(repo, ref=NEW)
                return 0

            with mock.patch.object(UC, "_run_cli_update", side_effect=local_ok):
                code = UC.apply_job(home, repo, peers=peers, runner=runner)
            self.assertEqual(code, 0)
            progress = UC.load_progress(home)
            self.assertEqual(progress["phase"], "done")
            self.assertIn("need attention", progress["message"])
            by_id = {m["id"]: m for m in progress["macs"]}
            self.assertEqual(by_id[peers[0]["id"]]["phase"], "offline")
            self.assertTrue(by_id[peers[0]["id"]]["help"])
            self.assertTrue(by_id[peers[0]["id"]]["can_retry"])
            self.assertEqual(by_id[peers[1]["id"]]["phase"], "done")
            self.assertEqual(by_id["local"]["phase"], "done")
            self.assertEqual(by_id["local"]["label"], "1st Mac")
            self.assertIn("2nd Mac", by_id[peers[0]["id"]]["label"])

    def test_apply_job_reports_model_did_not_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = write_package(Path(tmp) / "repo", ref=OLD)
            home.mkdir()
            ui = home / ".caravan" / "web-ui"
            ui.mkdir(parents=True)
            (ui / "last-model.json").write_text(json.dumps({"id": "a-model"}))
            UC.save_progress(home, {"expected": NEW, "old": OLD, "phase": "updating"})

            def local_ok(repo, **kwargs):
                write_package(repo, ref=NEW)
                return 0

            with mock.patch.object(UC, "_run_cli_update", side_effect=local_ok):
                code = UC.apply_job(
                    home, repo, peers=[], runner=lambda *a, **k: Result(0),
                    status_fn=lambda: {"status": "stopped"},
                )
            self.assertEqual(code, 0)
            progress = UC.load_progress(home)
            self.assertEqual(progress["phase"], "done")
            self.assertIn("model didn't come back", progress["message"])
            local = next(m for m in progress["macs"] if m.get("mine"))
            self.assertEqual(local["phase"], "no_model")
            self.assertTrue(local["help"])
            self.assertIn("load your model", " ".join(local["help"]))

    def test_retry_peer_does_not_update_this_mac(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            node = peer(1)
            UC.save_progress(home, {
                "phase": "done",
                "expected": NEW,
                "macs": [P.local_row(phase="done"), P._row(node, phase="offline", kind="offline")],
            })
            runner = ScriptedSSH({
                node["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW},
            })
            called = []
            with mock.patch.object(UC, "_run_cli_update", side_effect=lambda *a, **k: called.append(1) or 0):
                row = UC.retry_peer(home, node["id"], expected=NEW, peers=[node], runner=runner)
            self.assertEqual(row["phase"], "done")
            self.assertFalse(called)
            macs = UC.load_progress(home)["macs"]
            self.assertEqual(next(m for m in macs if m["id"] == node["id"])["phase"], "done")

    def test_daily_check_surfaces_a_behind_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = write_package(Path(tmp) / "repo", ref=NEW)  # this Mac is current
            home.mkdir()
            ui = home / ".caravan" / "web-ui"
            ui.mkdir(parents=True)
            (ui / "remote-worker.json").write_text(json.dumps({"ssh": "caravan-two", "id": "two"}))
            runner = ScriptedSSH({"caravan-two": {"ref": OLD}})
            result = UC.check(
                home, repo, force=True, opener=opener_for(),
                ssh_runner=runner,
            )
            self.assertFalse(result["newer"])
            self.assertTrue(result["peers_behind"])
            self.assertEqual(result["macs"][0]["label"], "2nd Mac")
            self.assertEqual(result["macs"][0]["phase"], "behind")
            payload = UC.public_status(result, packaged=True, local=True)
            self.assertTrue(payload["peers_behind"])
            self.assertTrue(payload["can_apply"])
            self.assertIn("2nd Mac", payload["message"])
            self.assertIn("older version", payload["message"])
            self.assertNotIn(NEW, json.dumps(payload))
            self.assertNotIn(OLD, json.dumps(payload))
            self.assertTrue(payload["macs"][0]["help"])

    def test_cli_local_only_does_not_fan_out(self):
        with tempfile.TemporaryDirectory() as root:
            package = write_package(Path(root) / "pkg")
            script = io.BytesIO(b"#!/bin/bash\n")
            result_mock = mock.Mock(returncode=0)
            plan = {"port": 8190, "kind": "web"}
            with mock.patch.object(cli, "ROOT", package), \
                 mock.patch.object(cli, "_update_other_macs", return_value=["should-not"]) as fan, \
                 mock.patch.object(cli.urllib.request, "urlopen", return_value=contextlib.closing(script)), \
                 mock.patch.object(cli.service, "stored", return_value=plan), \
                 mock.patch.object(cli.subprocess, "run", return_value=result_mock), \
                 mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(cli.main(["update", "--local-only"]), 0)
                fan.assert_not_called()

    def test_cli_default_fans_out_then_updates_this_mac(self):
        with tempfile.TemporaryDirectory() as root:
            package = write_package(Path(root) / "pkg")
            script = io.BytesIO(b"#!/bin/bash\n")
            result_mock = mock.Mock(returncode=0)
            plan = {"port": 8190, "kind": "web"}
            with mock.patch.object(cli, "ROOT", package), \
                 mock.patch.object(cli, "_update_other_macs", return_value=[peer(1)]) as fan, \
                 mock.patch.object(cli.urllib.request, "urlopen", return_value=contextlib.closing(script)), \
                 mock.patch.object(cli.service, "stored", return_value=plan), \
                 mock.patch.object(cli.subprocess, "run", return_value=result_mock) as run, \
                 mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(cli.main(["update"]), 0)
                fan.assert_called()
                cmd = run.call_args[0][0]
                self.assertEqual(cmd[0], "bash")
                self.assertIn("--update", cmd)

    def test_env_flag_skips_fan_out(self):
        with tempfile.TemporaryDirectory() as root:
            package = write_package(Path(root) / "pkg")
            script = io.BytesIO(b"#!/bin/bash\n")
            result_mock = mock.Mock(returncode=0)
            plan = {"port": 8190, "kind": "web"}
            with mock.patch.object(cli, "ROOT", package), \
                 mock.patch.object(cli, "_update_other_macs") as fan, \
                 mock.patch.object(cli.urllib.request, "urlopen", return_value=contextlib.closing(script)), \
                 mock.patch.object(cli.service, "stored", return_value=plan), \
                 mock.patch.object(cli.subprocess, "run", return_value=result_mock), \
                 mock.patch.dict("os.environ", {"CARAVAN_UPDATE_LOCAL": "1"}), \
                 mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(cli.main(["update"]), 0)
                fan.assert_not_called()



class PageFollowUpTests(unittest.TestCase):
    def test_page_lists_help_and_try_again(self):
        page = (ROOT / "proxy" / "web" / "index.html").read_text()
        self.assertIn("Try again", page)
        self.assertIn("updateMacs", page)
        self.assertIn("m.help", page)
        self.assertIn("can_retry", page)
        self.assertIn("via_tailscale", page)
        self.assertIn("peers_behind", page)
        self.assertIn("caravan update", page)
        self.assertIn("settings=1", page)
        # One backslash before b, as in settings=1\b
        idx = page.find("settings=1")
        self.assertEqual(page[idx + len("settings=1")], "\\")


class DocsFollowUpTests(unittest.TestCase):
    def test_guides_describe_n_macs_tailscale_and_help(self):
        texts = [
            (ROOT / "docs" / "DAY26.md").read_text(),
            (ROOT / "docs" / "WEB.md").read_text(),
            (ROOT / "INSTALL.md").read_text(),
            (ROOT / "docs" / "SECURITY.md").read_text(),
        ]
        for text in texts:
            self.assertIn("Update now", text)
            self.assertIn("Tailscale", text)
            self.assertIn("local network", text)
        day26 = texts[0]
        self.assertIn("other Macs", day26)
        self.assertIn("Try again", day26)
        self.assertIn("caravan update", day26)
        self.assertIn("2nd Mac", day26)
        self.assertIn("3rd Mac", day26)
        self.assertNotIn("prf-hays", day26)
        self.assertNotIn("/home/brenden", day26)
        self.assertIn("Try again", day26)
        self.assertIn("Macs are updated first", day26)
        self.assertIn("on and awake", day26)


if __name__ == "__main__":
    unittest.main()
