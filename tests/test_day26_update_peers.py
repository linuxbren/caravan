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
            self.assertEqual(row["status"], "failed")
            self.assertEqual(len(row["help"]), 1)
            if kind == "no_model":
                self.assertEqual(row["help"], ["Load your model again in Models."])
            else:
                self.assertEqual(row["help"], ["On the 2nd Mac, run caravan update in Terminal."])
            self.assertNotIn(NEW, json.dumps(row))
            self.assertNotIn("caravan-mac", row["label"])

    def test_update_peer_offline(self):
        node = peer(1)
        runner = ScriptedSSH({node["ssh"]: {"probe": Result(1)}})
        row = P.update_peer(node, expected=NEW, runner=runner)
        self.assertEqual(row["phase"], "offline")
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["can_retry"])
        self.assertEqual(row["help"], ["On the 2nd Mac, run caravan update in Terminal."])

    def test_update_peer_failed(self):
        node = peer(1)
        runner = ScriptedSSH({
            node["ssh"]: {"probe": Result(0), "update": Result(2, "", "boom")},
        })
        row = P.update_peer(node, expected=NEW, runner=runner)
        self.assertEqual(row["phase"], "failed")
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["can_retry"])
        # The other Mac's own error text is kept, with its exit code.
        self.assertEqual(row["detail"], "exit 2: boom")

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
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["can_retry"])
        self.assertIn("previous version", row["detail"])

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
        self.assertEqual(rows[0]["status"], "update needed")
        self.assertEqual(rows[0]["help"], [])
        self.assertFalse(rows[0]["can_retry"])
        self.assertEqual(rows[1]["status"], "failed")
        self.assertEqual(rows[2]["status"], "current")
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
            self.assertNotIn("Some Macs failed", progress["message"])
            self.assertNotIn("This Mac is updated", progress["message"])
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
            self.assertEqual(local["help"], ["Load your model again in Models."])

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
            lines = [(m["label"], m["status"]) for m in payload["macs"]]
            self.assertEqual(lines, [("1st Mac", "current"), ("2nd Mac", "update needed")])
            self.assertNotIn(NEW, json.dumps(payload))
            self.assertNotIn(OLD, json.dumps(payload))
            self.assertEqual(payload["macs"][1]["help"], [])

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
    def test_page_is_minimal(self):
        page = (ROOT / "proxy" / "web" / "index.html").read_text()
        card = page.split('id="updatesCard"', 1)[1].split('id="topoBarsCard"', 1)[0]
        self.assertIn("hidden>", card.split("\n", 1)[0])  # hidden until the server says to show it
        self.assertIn('id="btnUpdateCheck"', card)
        self.assertIn('id="updateDailySwitch"', card)
        self.assertIn('id="updateChanges"', card)
        self.assertIn('id="updateMacs"', card)
        self.assertIn('id="btnUpdateNow"', card)
        self.assertIn('id="btnUpdateRetry"', card)
        for gone in ("updateModelNote", "updateHelperNote", "updateLocalNote", "updateDone", "<ol"):
            self.assertNotIn(gone, card)
        self.assertIn("j.show === false", page)
        self.assertIn("j.can_retry", page)
        self.assertIn("Details", page)
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
        self.assertIn("parse error", day26)


class PeerCommandRootCauseTests(unittest.TestCase):
    """Day 26 bug: "VAR=1 if …" is a parse error in zsh and bash, so the
    2nd Mac never ran its update (exit 1, "parse error near `if'")."""

    def test_command_parses_in_sh_and_bash(self):
        import shutil
        import subprocess
        cmd = P.peer_update_command()
        self.assertFalse(cmd.lstrip().startswith("CARAVAN_UPDATE_LOCAL="))
        for shell in ("sh", "bash", "zsh"):
            path = shutil.which(shell)
            if not path:
                continue
            r = subprocess.run([path, "-n", "-c", cmd], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (shell, r.stderr))

    def test_old_form_was_a_parse_error(self):
        import subprocess
        old = 'CARAVAN_UPDATE_LOCAL=1 if [ -x "$HOME/x" ]; then echo y; else exit 127; fi'
        r = subprocess.run(["bash", "-n", "-c", old], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_runs_wrapper_with_the_flag_set(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as home:
            bin_dir = Path(home) / ".caravan" / "bin"
            bin_dir.mkdir(parents=True)
            wrapper = bin_dir / "caravan"
            wrapper.write_text('#!/bin/sh\necho "flag=$CARAVAN_UPDATE_LOCAL args=$*"\n')
            wrapper.chmod(0o755)
            r = subprocess.run(["bash", "-c", P.peer_update_command()], capture_output=True,
                               text=True, env={**os.environ, "HOME": home})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "flag=1 args=update")
        with tempfile.TemporaryDirectory() as home:
            r = subprocess.run(["bash", "-c", P.peer_update_command()], capture_output=True,
                               text=True, env={**os.environ, "HOME": home})
            self.assertEqual(r.returncode, 127)
            self.assertIn("not installed", r.stderr)

    def test_last_error_is_stored(self):
        with tempfile.TemporaryDirectory() as home:
            node = peer(1, ssh="caravan-secret-alias")
            runner = ScriptedSSH({node["ssh"]: {"probe": Result(0), "update": Result(
                1, "", "caravan-secret-alias: zsh:1: parse error near `if'")}})
            rows = P.update_other_macs(Path(home), [node], expected=NEW, runner=runner)
            self.assertEqual(rows[0]["status"], "failed")
            self.assertIn("parse error", rows[0]["detail"])
            self.assertNotIn("caravan-secret-alias", rows[0]["detail"])
            saved = json.loads(P.peer_errors_path(home).read_text())
            self.assertIn("parse error", saved[node["id"]]["detail"])
            # A later success clears it.
            ok = ScriptedSSH({node["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW}})
            P.update_other_macs(Path(home), [node], expected=NEW, runner=ok)
            self.assertNotIn(node["id"], json.loads(P.peer_errors_path(home).read_text()))


class MinimalStatusTests(unittest.TestCase):
    def test_try_again_only_when_a_mac_failed(self):
        base = {"newer": False, "available": NEW, "installed": NEW, "checked_at": 1}
        ok = UC.public_status(dict(base, macs=[P._row(peer(1), phase="current", can_retry=False)]),
                              packaged=True, local=True)
        self.assertFalse(ok["can_retry"])
        self.assertFalse(ok["can_apply"])
        self.assertEqual([m["status"] for m in ok["macs"]], ["current", "current"])
        failed = {"phase": "done", "expected": NEW, "macs": [
            P.local_row(phase="done"), P._row(peer(1), phase="failed", kind="failed")]}
        bad = UC.public_status(base, packaged=True, local=True, progress=failed)
        self.assertTrue(bad["can_retry"])
        self.assertEqual([m["status"] for m in bad["macs"]], ["current", "failed"])
        lan = UC.public_status(base, packaged=True, local=False, progress=failed)
        self.assertFalse(lan["show"])
        self.assertFalse(lan["can_retry"])

    def test_old_run_rows_give_way_to_a_newer_check(self):
        old_run = {"phase": "done", "expected": OLD, "macs": [
            P.local_row(phase="done"), P._row(peer(1), phase="failed", kind="failed")]}
        result = {"newer": True, "available": NEW, "installed": OLD, "checked_at": 1,
                  "macs": [P._row(peer(1), phase="behind", can_retry=False)]}
        out = UC.public_status(result, packaged=True, local=True, progress=old_run)
        self.assertEqual([m["status"] for m in out["macs"]], ["update needed", "update needed"])
        self.assertFalse(out["can_retry"])


class CurrentRealityTests(unittest.TestCase):
    """Rows say where each Mac is now, not how the last run went."""

    NEWER = "c" * 40

    def test_newer_version_after_a_completed_run_shows_update_available(self):
        run = {"phase": "done", "expected": NEW, "message": "This Mac is updated. Some Macs failed.",
               "macs": [P.local_row(phase="done"), P._row(peer(1), phase="done", can_retry=False),
                        P._row(peer(2), phase="done", can_retry=False)]}
        result = {"newer": True, "available": self.NEWER, "installed": NEW, "checked_at": 1,
                  "macs": [P._row(peer(1), phase="behind", can_retry=False),
                           P._row(peer(2), phase="behind", can_retry=False)]}
        for p in result["macs"]:
            p["behind"] = True
        out = UC.public_status(result, packaged=True, local=True, progress=run, installed=NEW)
        self.assertEqual([(m["label"], m["status"]) for m in out["macs"]],
                         [("1st Mac", "update needed"), ("2nd Mac", "update needed"),
                          ("3rd Mac", "update needed")])
        self.assertNotIn("done", json.dumps([m["status"] for m in out["macs"]]))
        self.assertTrue(out["can_apply"])
        self.assertFalse(out["can_retry"])
        self.assertNotIn("This Mac is updated", json.dumps(out))
        self.assertNotIn("attention", json.dumps(out))

    def test_failed_peer_then_newer_version_reads_update_available(self):
        with tempfile.TemporaryDirectory() as home:
            run = {"phase": "done", "expected": NEW, "macs": [
                P.local_row(phase="done"), P._row(peer(1), phase="failed", kind="failed", detail="exit 1")]}
            UC.save_progress(home, run)
            result = {"newer": True, "available": self.NEWER, "installed": NEW, "checked_at": 1,
                      "macs": [dict(P._row(peer(1), phase="behind", can_retry=False), behind=True)]}
            UC.save_cache(home, result)
            out = UC.public_status(result, packaged=True, local=True, progress=run, installed=NEW)
            self.assertEqual([m["status"] for m in out["macs"]], ["update needed", "update needed"])
            self.assertFalse(out["can_retry"])
            self.assertEqual(out["macs"][1]["help"], [])
            self.assertEqual(UC.failed_mac_ids(home), [])

    def test_failed_at_the_current_target_stays_failed_without_update_now(self):
        run = {"phase": "done", "expected": NEW, "macs": [
            P.local_row(phase="done"), P._row(peer(1), phase="failed", kind="failed")]}
        result = {"newer": True, "available": NEW, "installed": OLD, "checked_at": 1,
                  "macs": [dict(P._row(peer(1), phase="behind", can_retry=False), behind=True)]}
        # The saved check is from before this Mac updated itself.
        out = UC.public_status(result, packaged=True, local=True, progress=run, installed=NEW)
        self.assertEqual([m["status"] for m in out["macs"]], ["current", "failed"])
        self.assertTrue(out["can_retry"])
        self.assertFalse(out["can_apply"])
        self.assertFalse(out["newer"])

    def test_done_is_never_a_row_status(self):
        run = {"phase": "done", "expected": NEW, "macs": [
            P.local_row(phase="done"), P._row(peer(1), phase="done", can_retry=False)]}
        result = {"newer": False, "available": NEW, "installed": NEW, "checked_at": 1,
                  "macs": [dict(P._row(peer(1), phase="behind", can_retry=False), behind=True)]}
        out = UC.public_status(result, packaged=True, local=True, progress=run, installed=NEW)
        self.assertEqual([m["status"] for m in out["macs"]], ["current", "current"])
        self.assertFalse(out["can_apply"])

    def test_page_has_no_summary_sentences(self):
        page = (ROOT / "proxy" / "web" / "index.html").read_text()
        self.assertNotIn("j.progress && j.progress.message", page)
        self.assertNotIn("Other Macs need attention", page)
        self.assertNotIn("Some other Macs need attention", page)


class StaleCheckAfterOwnUpdateTests(unittest.TestCase):
    """Brenden's 1st Mac on Nov 13: the saved check was from before its own update.

    Real values from that Mac: it had checked on 8e77bc9 and seen 6a1c6db,
    updated both Macs to 6a1c6db (run marked done), and then the page read
    the old check: "newer" was still true (What's new, Update now) while
    the Mac lines came from the finished run and said "current".
    """

    BEFORE = "8e77bc9958bbb16c84598b0e9ebab2238f1a7ed3"
    NOW = "6a1c6db9d2089ca62bae77170406e4f20fb75606"
    LATEST = "1b8bd421371485655d8d319e2fea7305b265b8de"
    LATEST_SHA = "4c43b83e5281675b8464d05140daf0d5cb250bc8d77e1f06d801879d97356e07"
    NOW_SHA = "69dbf0630bdd69bf77acff71add818430bba667aba6580148e245f9afbbad6c4"
    PEER_ID = "paired_dcbb9f1b9cd8cab4dcfa61388dffe4ec"

    def _home(self, tmp):
        home = Path(tmp) / "home"
        repo = write_package(Path(tmp) / "repo", ref=self.NOW)
        node = dict(peer(1), id=self.PEER_ID)
        UC.save_cache(home, {
            "installed": self.BEFORE, "available": self.NOW, "newer": True,
            "available_label": "November 13", "current_label": "an earlier November 13 version",
            "changes": ["Day 26: Update progress in the page"], "reload_model": False,
            "checked_at": 1794621000.0, "error": None, "check_daily": True, "helper": True,
            "macs": [dict(P._row(node, phase="behind", can_retry=False), behind=True)],
            "peers_behind": True,
        })
        UC.save_progress(home, {
            "phase": "done", "expected": self.NOW, "old": self.BEFORE, "new": self.NOW,
            "message": "Done.", "started_at": 1794621565.3, "finished_at": 1794621606.7,
            "macs": [P.local_row(phase="done"), P._row(node, phase="done", can_retry=False)],
        })
        return home, repo, node

    def _opener(self, published, published_sha):
        from test_day26_update_check import FakeOpener, compare_payload, commit_payload
        return FakeOpener({
            "packaging-version": f"{published} {published_sha}\n",
            "compare/": compare_payload(["Day 26: Update lines show where each Mac is now"], ["proxy/web/index.html"]),
            f"commits/{self.NOW}": commit_payload("2026-11-13T19:59:00Z"),
            f"commits/{published}": commit_payload("2026-11-14T02:06:00Z"),
        })

    def _serve(self, home, repo, node, opener, ssh):
        from test_day26_update_check import WorkerManager, web_server
        from http.server import ThreadingHTTPServer
        import threading
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        app = web_server.App(WorkerManager(
            lead_port=8194, packer_peer="127.0.0.1:5560", packer_ssh="nobody@127.0.0.1",
            state_dir=Path(state.name), repo=ROOT))
        app.nodes = lambda: {"nodes": []}
        app.configured_nodes = lambda: [node]
        app.update_home, app.update_repo = home, repo
        app.update_opener, app.update_ssh = opener, ssh
        app.update_inspect = lambda: {}

        class _S(ThreadingHTTPServer):
            def server_bind(self):
                import socketserver
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = self.server_address[:2]
        httpd = _S(("127.0.0.1", 0), web_server.make_handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        with urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/update", timeout=10) as r:
            return json.loads(r.read().decode())

    def test_newer_release_after_own_update_marks_every_mac_update_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo, node = self._home(tmp)
            ssh = ScriptedSSH({node["ssh"]: {"ref": self.NOW}})  # the 2nd Mac is on 6a1c6db too
            j = self._serve(home, repo, node, self._opener(self.LATEST, self.LATEST_SHA), ssh)
            self.assertTrue(j["newer"])
            self.assertTrue(j["can_apply"])
            self.assertEqual([(m["label"], m["status"]) for m in j["macs"]],
                             [("1st Mac", "update needed"), ("2nd Mac", "update needed")])
            self.assertEqual(j["changes"], ["Day 26: Update lines show where each Mac is now"])
            self.assertIsNone(j["keep_model_text"])
            self.assertTrue(j["page"])  # page tag for the auto-reload
            self.assertEqual(UC.load_cache(home)["installed"], self.NOW)

    def test_no_newer_release_after_own_update_reads_current_without_update_now(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo, node = self._home(tmp)
            ssh = ScriptedSSH({node["ssh"]: {"ref": self.NOW}})
            j = self._serve(home, repo, node, self._opener(self.NOW, self.NOW_SHA), ssh)
            self.assertFalse(j["newer"])
            self.assertFalse(j["can_apply"])
            self.assertFalse(j["peers_behind"])
            self.assertEqual([m["status"] for m in j["macs"]], ["current", "current"])

    def test_stale_check_alone_never_shows_update_now_with_current_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo, node = self._home(tmp)
            out = UC.public_status(UC.load_cache(home), packaged=True, local=True,
                                   progress=UC.load_progress(home), installed=self.NOW)
            needs = out["newer"] or out["peers_behind"]
            lines = [m["status"] for m in out["macs"]]
            # Either an update is needed and the lines say so, or nothing is offered.
            self.assertFalse(needs and "update needed" not in lines)
            self.assertEqual(lines, ["current", "current"])
            self.assertFalse(out["can_apply"])


class AutoReloadAfterUpdateTests(unittest.TestCase):
    """Open pages reload themselves once Caravan is updated underneath them."""

    def setUp(self):
        self.page = (ROOT / "proxy" / "web" / "index.html").read_text()
        self.server = (ROOT / "proxy" / "web_server.py").read_text()

    def test_page_tag_follows_the_page_file_not_the_version(self):
        import web_server
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "index.html"
            f.write_text("<p>one</p>")
            one = web_server.page_tag(f)
            self.assertEqual(one, web_server.page_tag(f))
            self.assertEqual(len(one), 10)
            f.write_text("<p>two, a bit longer</p>")
            self.assertNotEqual(one, web_server.page_tag(f))
            self.assertIsNone(web_server.page_tag(Path(tmp) / "missing.html"))
        self.assertTrue(web_server.page_tag())

    def test_comment_only_update_changes_the_tag(self):
        """24b9986 changed one comment and no page file: the tag must still change."""
        import web_server
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "index.html"
            page.write_text("<p>same page in both versions</p>")
            pkg = Path(tmp) / ".caravan-package"
            pkg.write_text("93cfd7bb623ac5eaafdfbca67000bb6f1cf8f7b4\n")
            before = web_server.page_tag(page, pkg)
            pkg.write_text("703d5809d7e7bf34debec990178b9fd6a65c4909\n")
            after = web_server.page_tag(page, pkg)
            self.assertNotEqual(before, after)
            self.assertNotIn("703d580", after)
            self.assertEqual(after, web_server.page_tag(page, pkg))

    def test_the_tab_that_ran_the_update_reloads_when_the_run_finishes(self):
        render = self.page.split("function renderUpdate(j) {", 1)[1].split("const updating = ", 1)[0]
        self.assertIn('if (pending && _updateWasBusy && phase === "done" && reloadAfterRun(j.progress)) return;', render)
        run = self.page.split("function reloadAfterRun(progress)", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn('"caravan.update.reloadedRun"', run)
        self.assertIn("if (tried === key) return false;", run)
        self.assertIn("location.reload()", run)

    def test_status_and_update_answers_carry_the_tag(self):
        self.assertIn('"page": page_tag(),', self.server.split("def _api_status", 1)[1].split("def ", 1)[0])
        self.assertIn('out["page"] = page_tag()', self.server)

    def test_every_tab_checks_the_tag_and_waits_for_idle(self):
        status = self.page.split("async function refreshStatus()", 1)[1][:400]
        self.assertIn("checkPageTag(j && j.page)", status)
        self.assertIn("if (pageIsStale(j)) return;", self.page)
        check = self.page.split("function checkPageTag(tag)", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn("if (!updatePending() && !pageUserIdle()) return false;", check)
        self.assertIn('sessionStorage.setItem("caravan.update.reloaded", tag)', check)
        self.assertIn("if (tried === tag) return false;", check)
        self.assertIn("location.reload()", check)
        idle = self.page.split("function pageUserIdle()", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn('$("input")', idle)
        self.assertIn("state.streaming", idle)
        self.assertIn("_tuneRunning", idle)

    def test_busy_state_shows_before_the_server_answers(self):
        click = self.page.split('$("btnUpdateNow").addEventListener("click"', 1)[1]
        click = click.split('action: "apply"', 1)[0]
        self.assertIn('startUpdateStep("Updating…", 0, false)', click)
        self.assertIn('classList.add("is-tuning")', click)
        self.assertIn('textContent = "Updating…"', click)

    def test_a_stuck_request_turns_into_restarting(self):
        refresh = self.page.split("async function refreshUpdate(opts)", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn("setTimeout(() => ctl.abort(), 5000)", refresh)
        self.assertIn('"… restarting"', refresh)
        self.assertIn("_updatePollBusy", self.page)


class UpdateAnimationTests(unittest.TestCase):
    def test_step_line_has_text_and_server_elapsed(self):
        import time as _t
        progress = {"phase": "updating", "expected": NEW, "started_at": _t.time() - 90,
                    "step": {"text": "Updating the 2nd Mac…", "since": _t.time() - 42},
                    "macs": [P.local_row(phase="waiting"), P._row(peer(1), phase="updating", can_retry=False)]}
        out = UC.public_status({"newer": True, "available": NEW}, packaged=True, local=True, progress=progress)
        self.assertTrue(out["updating"])
        self.assertEqual(out["step"]["text"], "Updating the 2nd Mac…")
        self.assertTrue(41 <= out["step"]["elapsed_s"] <= 44)
        self.assertEqual([m["status"] for m in out["macs"]], ["update needed", "updating…"])
        self.assertFalse(out["can_retry"])
        idle = UC.public_status({"newer": False, "available": NEW, "checked_at": 1}, packaged=True, local=True)
        self.assertIsNone(idle["step"])

    def test_apply_job_steps_through_each_mac(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = write_package(Path(tmp) / "repo", ref=OLD)
            home.mkdir()
            UC.save_progress(home, {"expected": NEW, "old": OLD, "phase": "updating"})
            peers = [peer(1), peer(2)]
            seen = []
            real_save = UC.save_progress

            def spy(h, data):
                step = (data.get("step") or {}).get("text")
                if step and (not seen or seen[-1] != step):
                    seen.append(step)
                return real_save(h, data)

            runner = ScriptedSSH({p["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW} for p in peers})

            def local_ok(repo, **kwargs):
                write_package(repo, ref=NEW)
                return 0

            with mock.patch.object(UC, "save_progress", side_effect=spy), \
                 mock.patch.object(UC, "_run_cli_update", side_effect=local_ok):
                UC.apply_job(home, repo, peers=peers, runner=runner)
            self.assertEqual(seen, ["Updating the 2nd Mac…", "Updating the 3rd Mac…", "Updating the 1st Mac…"])

    def test_try_again_shows_a_step_then_clears_it(self):
        with tempfile.TemporaryDirectory() as home:
            node = peer(1)
            UC.save_progress(home, {"phase": "done", "expected": NEW, "macs": [
                P.local_row(phase="done"), P._row(node, phase="failed", kind="failed")]})
            self.assertEqual(UC.mark_retrying(home, [node["id"]], peers=[node]), [node["id"]])
            mid = UC.load_progress(home)
            self.assertEqual(mid["step"]["text"], "Updating the 2nd Mac…")
            out = UC.public_status({"available": NEW, "checked_at": 1}, packaged=True, local=True, progress=mid)
            self.assertTrue(out["updating"])
            runner = ScriptedSSH({node["ssh"]: {"probe": Result(0), "update": Result(0), "ref": NEW}})
            with mock.patch("sys.stdout", io.StringIO()):
                UC.retry_peer(home, node["id"], expected=NEW, peers=[node], runner=runner)
            done = UC.load_progress(home)
            self.assertNotIn("step", done)
            out = UC.public_status({"available": NEW, "checked_at": 1}, packaged=True, local=True, progress=done)
            self.assertFalse(out["updating"])
            self.assertEqual([m["status"] for m in out["macs"]], ["current", "current"])

    def test_page_has_campfire_step_and_survives_restart(self):
        page = (ROOT / "proxy" / "web" / "index.html").read_text()
        self.assertIn("function startUpdateStep", page)
        self.assertIn("fmtElapsed", page)
        self.assertIn('"… restarting"', page)
        self.assertIn('flashUpdateDone("Done.")', page)
        self.assertIn('btnNow.classList.toggle("is-tuning", updating)', page)
        self.assertIn('textContent = updating ? "Updating…" : "Update now"', page)
        self.assertIn("caravan.update.pending", page)
        # Over the local network nothing is drawn at all.
        self.assertIn("j.show === false", page)


if __name__ == "__main__":
    unittest.main()
