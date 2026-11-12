"""Single-step `caravan update`: keep workers, reload, roll back, already current."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import caravan_update as U
import caravan as cli


def hashes(mapping):
    """Build a shasum-style manifest from {relpath: content}."""
    lines = []
    for path, content in mapping.items():
        digest = hashlib.sha256(content.encode() if isinstance(content, str) else content).hexdigest()
        lines.append(f"{digest}  ./{path}")
    return "\n".join(lines) + "\n"


def write_package(folder, files, ref="old" * 10):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        dest = folder / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(content)
    (folder / ".caravan-package").write_text(ref + "\n")
    (folder / ".caravan-package-files").write_text(hashes(files))
    return folder


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


WEB_ONLY_OLD = {
    "agent/mlx_worker.py": "worker-v1",
    "runtime/llama-release.json": '{"v":1}',
    "requirements-mac.lock": "mlx==1",
    "requirements-mac.txt": "mlx",
    "proxy/web_server.py": "web-v1",
    "proxy/slot_pin_proxy.py": "proxy-v1",
    "tools/aux_worker.py": "aux-v1",
    "tools/caravan.py": "cli-v1",
    "scripts/install.sh": "#!/bin/bash\nexit 0\n",
}
WEB_ONLY_NEW = dict(WEB_ONLY_OLD)
WEB_ONLY_NEW["proxy/web_server.py"] = "web-v2"
WEB_ONLY_NEW["tools/caravan.py"] = "cli-v2"

WORKER_NEW = dict(WEB_ONLY_OLD)
WORKER_NEW["agent/mlx_worker.py"] = "worker-v2"


class FakeLaunchd:
    def __init__(self, loaded=None, fail_start=False):
        self.loaded = set(loaded or [])
        self.actions = []
        self.fail_start = fail_start

    def __call__(self, args, **kwargs):
        action = args[0]
        if action == "print":
            name = args[1].rsplit(".", 1)[-1]
            ok = name in self.loaded
            return subprocess.CompletedProcess(args, 0 if ok else 1, "loaded\n" if ok else "", "")
        if action == "bootout":
            name = args[1].rsplit(".", 1)[-1]
            self.loaded.discard(name)
            self.actions.append(("stop", name))
            return subprocess.CompletedProcess(args, 0, "", "")
        if action == "bootstrap":
            name = Path(args[-1]).stem.rsplit(".", 1)[-1]
            if self.fail_start:
                # Fail the first start (the new version); rollback starts succeed.
                self.fail_start = False
                return subprocess.CompletedProcess(args, 1, "", "bootstrap failed")
            self.loaded.add(name)
            self.actions.append(("start", name))
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 1, "", "unknown")


class PlanTests(unittest.TestCase):
    def manifests(self, old, new):
        with tempfile.TemporaryDirectory() as tmp:
            o = Path(tmp) / "old.txt"
            n = Path(tmp) / "new.txt"
            o.write_text(hashes(old))
            n.write_text(hashes(new))
            return U.load_hashes(o), U.load_hashes(n)

    def test_web_only_change_does_not_reload_workers(self):
        plan = U.plan_update(*self.manifests(WEB_ONLY_OLD, WEB_ONLY_NEW))
        self.assertFalse(plan["reload_workers"])
        self.assertFalse(plan["restart_proxy"])
        self.assertFalse(plan["restart_aux"])
        self.assertTrue(plan["restart_web"])
        self.assertEqual(plan["worker_changes"], [])

    def test_worker_code_change_reloads_and_restarts_aux(self):
        plan = U.plan_update(*self.manifests(WEB_ONLY_OLD, WORKER_NEW))
        self.assertTrue(plan["reload_workers"])
        self.assertIn("agent/mlx_worker.py", plan["worker_changes"])
        self.assertTrue(plan["restart_aux"])
        self.assertFalse(plan["restart_proxy"])

    def test_requirements_change_reloads_everything_using_the_venv(self):
        new = dict(WEB_ONLY_OLD)
        new["requirements-mac.lock"] = "mlx==2"
        plan = U.plan_update(*self.manifests(WEB_ONLY_OLD, new))
        self.assertTrue(plan["reload_workers"])
        self.assertTrue(plan["restart_proxy"])
        self.assertTrue(plan["restart_aux"])

    def test_proxy_only_change_restarts_proxy_not_workers(self):
        new = dict(WEB_ONLY_OLD)
        new["proxy/slot_pin_proxy.py"] = "proxy-v2"
        plan = U.plan_update(*self.manifests(WEB_ONLY_OLD, new))
        self.assertFalse(plan["reload_workers"])
        self.assertTrue(plan["restart_proxy"])
        self.assertFalse(plan["restart_aux"])

    def test_aux_only_change_restarts_aux_not_main_workers(self):
        new = dict(WEB_ONLY_OLD)
        new["tools/aux_worker.py"] = "aux-v2"
        plan = U.plan_update(*self.manifests(WEB_ONLY_OLD, new))
        self.assertFalse(plan["reload_workers"])
        self.assertTrue(plan["restart_aux"])

    def test_removed_worker_file_counts_as_a_change(self):
        old = {"agent/gone.py": "x", "proxy/web_server.py": "w"}
        new = {"proxy/web_server.py": "w"}
        plan = U.plan_update(*self.manifests(old, new))
        self.assertTrue(plan["reload_workers"])
        self.assertEqual(plan["worker_changes"], ["agent/gone.py"])

    def test_unreadable_manifest_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad"
            path.write_text("not a hash\n")
            with self.assertRaises(ValueError):
                U.load_hashes(path)

    def test_already_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / ".caravan-package").write_text("abc\n")
            self.assertTrue(U.already_current(repo, "abc"))
            self.assertFalse(U.already_current(repo, "def"))
            self.assertFalse(U.already_current(Path(tmp) / "missing", "abc"))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.src = self.home / ".caravan" / "src"
        self.repo = self.src / "caravan"
        self.new = self.src / "incoming"
        self.home.mkdir()
        (self.home / ".caravan" / "logs").mkdir(parents=True)
        (self.home / ".caravan" / "services").mkdir(parents=True)
        (self.home / ".caravan" / "web-ui").mkdir(parents=True)
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        self.workers = []
        self.installs = []

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, old_files, new_files, *, services=("web",), loaded=("web",), last_model=False):
        write_package(self.repo, old_files, ref="0" * 40)
        write_package(self.new, new_files, ref="1" * 40)
        for name in services:
            label = f"com.caravan.v3.{name}"
            (self.home / "Library" / "LaunchAgents" / f"{label}.plist").write_text(f"plist-{name}")
            plan = {
                "managed_by": "caravan-service-v1",
                "schema": 1,
                "kind": "web" if name == "web" else name,
                "name": name,
                "label": label,
                "port": 8190,
                "lead_port": 8194,
            }
            (self.home / ".caravan" / "services" / f"{name}.json").write_text(json.dumps(plan))
        if last_model:
            (self.home / ".caravan" / "web-ui" / "last-model.json").write_text(
                json.dumps({"schema": 1, "request": {"model_id": "demo"}})
            )
        self.launchd = FakeLaunchd(loaded=list(loaded))
        return self.launchd

    def installer(self, fail_on="never"):
        def run(repo, **kwargs):
            marker = Path(repo) / ".caravan-package"
            ref = marker.read_text().strip() if marker.exists() else ""
            self.installs.append(ref)
            if fail_on == "new" and ref == "1" * 40:
                raise ValueError("pip failed")
            (Path(repo) / "install-ran").write_text("ok")
            # Keep startup files present after a "reinstall".
            for name in ("web", "proxy", "aux", "worker"):
                plist = self.home / "Library" / "LaunchAgents" / f"com.caravan.v3.{name}.plist"
                if not plist.exists() and (self.home / ".caravan" / "services" / f"{name}.json").exists():
                    plist.write_text(f"plist-{name}")
        return run

    def stop_workers(self, home, repo, **kwargs):
        self.workers.append((home, repo, kwargs))
        return U.has_saved_model(home)

    def apply(self, *, start=True, installer=None, wait=None, status=None, fail_start=False):
        if fail_start:
            self.launchd.fail_start = True
        out = io.StringIO()
        result = U.apply_update(
            self.home,
            self.repo,
            self.new,
            python="/usr/bin/python3",
            start=start,
            run=self.launchd,
            installer=installer or self.installer(),
            stop_workers=self.stop_workers,
            wait=wait or (lambda port, **k: True),
            status=status or (lambda home, name, file=None: (print("Caravan is running", file=file), 0)[1]),
            clock=lambda: 12345,
            out=out,
        )
        return result, out.getvalue()

    def test_web_only_change_keeps_workers_and_restarts_web(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        result, text = self.apply()
        self.assertEqual(result, 0)
        self.assertIn(U.OPENING, text)
        self.assertNotIn(U.RELOADING, text)
        self.assertIn("Caravan is running", text)
        self.assertEqual(self.workers, [])
        self.assertEqual(self.launchd.actions, [("stop", "web"), ("start", "web")])
        self.assertEqual((self.repo / "proxy" / "web_server.py").read_text(), "web-v2")
        self.assertTrue((self.src / "caravan-backup-12345").exists())
        self.assertEqual(text.splitlines()[0], U.OPENING)
        self.assertEqual(text.strip().splitlines()[-1], "Caravan is running")

    def test_worker_change_reloads_and_keeps_saved_model(self):
        self.seed(WEB_ONLY_OLD, WORKER_NEW, last_model=True)
        saved = (self.home / ".caravan" / "web-ui" / "last-model.json").read_bytes()
        result, text = self.apply()
        self.assertEqual(result, 0)
        self.assertIn(U.RELOADING, text)
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(
            (self.home / ".caravan" / "web-ui" / "last-model.json").read_bytes(), saved
        )
        self.assertEqual((self.repo / "agent" / "mlx_worker.py").read_text(), "worker-v2")

    def test_install_failure_restores_old_source_and_restarts(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        result, text = self.apply(installer=self.installer(fail_on="new"))
        self.assertEqual(result, 1)
        self.assertIn(U.FAILED, text)
        self.assertNotIn("Caravan is running", text)
        self.assertEqual((self.repo / "proxy" / "web_server.py").read_text(), "web-v1")
        self.assertFalse((self.src / "caravan-backup-12345").exists())
        self.assertIn(("stop", "web"), self.launchd.actions)
        self.assertIn(("start", "web"), self.launchd.actions)
        self.assertIn("web", self.launchd.loaded)
        # First installer call is the new tree (fails); rollback runs the old tree.
        self.assertEqual(self.installs[0], "1" * 40)
        self.assertEqual(self.installs[-1], "0" * 40)
        self.assertEqual(text.strip().splitlines()[-1], U.FAILED)

    def test_start_failure_also_rolls_back(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        result, text = self.apply(fail_start=True)
        self.assertEqual(result, 1)
        self.assertIn(U.FAILED, text)
        self.assertEqual((self.repo / "proxy" / "web_server.py").read_text(), "web-v1")
        self.assertIn("web", self.launchd.loaded)

    def test_no_start_still_restarts_a_running_page(self):
        """Previous CLI always passed --no-start; a running page comes back."""
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        result, text = self.apply(start=False)
        self.assertEqual(result, 0)
        self.assertIn(("start", "web"), self.launchd.actions)
        self.assertIn("web", self.launchd.loaded)

    def test_no_start_leaves_a_stopped_page_stopped(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW, loaded=())
        result, text = self.apply(start=False)
        self.assertEqual(result, 0)
        self.assertNotIn(("start", "web"), self.launchd.actions)
        self.assertNotIn("web", self.launchd.loaded)

    def test_proxy_left_running_when_its_code_is_unchanged(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW, services=("web", "proxy"), loaded=("web", "proxy"))
        result, text = self.apply()
        self.assertEqual(result, 0)
        self.assertNotIn(("stop", "proxy"), self.launchd.actions)
        self.assertIn("proxy", self.launchd.loaded)

    def test_stop_model_workers_preserves_last_model(self):
        self.seed(WEB_ONLY_OLD, WORKER_NEW, last_model=True)
        (self.home / ".caravan" / "web-ui" / "lead.pid").write_text("4242")
        sent = []

        def inspect(pid):
            return "python agent/mlx_worker.py --port 8194" if pid == 4242 else ""

        def send(pid, sig):
            sent.append((pid, sig))

        kept = (self.home / ".caravan" / "web-ui" / "last-model.json").read_bytes()
        # Use ownership_stop so we do not import worker_ownership against a stub repo.
        called = {}

        def ownership_stop(worker, **kwargs):
            called["worker"] = worker
            called.update(kwargs)
            send(4242, 15)

        saw = U.stop_model_workers(
            self.home, self.repo, inspect=inspect, send=send, pause=lambda _s: None,
            run_ssh=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
            ownership_stop=ownership_stop,
        )
        self.assertTrue(saw)
        self.assertEqual(
            (self.home / ".caravan" / "web-ui" / "last-model.json").read_bytes(), kept
        )
        self.assertEqual(sent, [(4242, 15)])
        self.assertIn("mlx_worker.py", called["worker"])


class CommandTests(unittest.TestCase):
    def test_update_still_refuses_a_developer_checkout(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(cli, "ROOT", Path(root)), mock.patch.object(cli.urllib.request, "urlopen") as network, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["update"]), 2)
            network.assert_not_called()

    def test_update_does_not_ask_the_user_to_start_afterwards(self):
        text = (ROOT / "tools" / "caravan.py").read_text()
        self.assertIn('"--update", "--role", role', text)
        self.assertNotIn("run caravan start when ready", text)
        self.assertNotIn("--no-start", text.split("if args.action == \"update\":")[1].split("if args.action ==")[0])

    def test_cli_delegates_to_fetched_installer(self):
        with tempfile.TemporaryDirectory() as root:
            package = Path(root)
            (package / ".caravan-package").write_text("abc\n")
            (package / ".caravan-role").write_text("lead\n")
            script = io.BytesIO(b"#!/bin/bash\n")
            result_mock = mock.Mock(returncode=0)
            plan = {"port": 8190, "kind": "web"}
            with mock.patch.object(cli, "ROOT", package), mock.patch.object(cli.urllib.request, "urlopen", return_value=contextlib.closing(script)), mock.patch.object(cli.service, "stored", return_value=plan), mock.patch.object(cli.subprocess, "run", return_value=result_mock) as run, contextlib.redirect_stdout(io.StringIO()) as out:
                # urlopen is used both for the install script and maybe not for status (install prints it)
                self.assertEqual(cli.main(["update"]), 0)
                cmd = run.call_args[0][0]
                self.assertEqual(cmd[0], "bash")
                self.assertIn("--update", cmd)
                self.assertIn("--role", cmd)
                self.assertIn("lead", cmd)
                self.assertNotIn("--no-start", cmd)
                self.assertNotIn("run caravan start when ready", out.getvalue())


class BootstrapContractTests(unittest.TestCase):
    def test_shell_syntax(self):
        self.assertEqual(
            subprocess.run(["bash", "-n", str(ROOT / "install")], capture_output=True).returncode, 0
        )

    def test_services_loaded_path_no_longer_refuses(self):
        text = (ROOT / "install").read_text()
        self.assertNotIn("Stop the web first", text)
        self.assertNotIn("then run caravan update", text)
        self.assertIn("caravan_update.py", text)
        self.assertIn(U.UP_TO_DATE, text)
        self.assertIn('"$ACTUAL" = "$SHA"', text)

    def test_install_guide_is_one_command(self):
        guide = (ROOT / "INSTALL.md").read_text()
        self.assertIn("`caravan update`", guide)
        self.assertNotIn("caravan stop\ncaravan update\ncaravan start", guide)
        table = [line for line in guide.splitlines() if "caravan update" in line and line.startswith("|")]
        self.assertTrue(table)
        self.assertNotIn("after you stop it", table[0])


class MockMacUpdateTests(unittest.TestCase):
    """Exercise the bootstrap --update path with fake macOS commands on Linux."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "PATH": str(self.bin) + ":" + os.environ["PATH"]}
        self.command("uname", 'if [ "$1" = -s ]; then echo Darwin; else echo arm64; fi')
        self.command("id", "echo 501")
        self.command("sw_vers", "echo 15.0")
        self.command("sysctl", "echo 34359738368")
        self.command("df", "printf 'Filesystem blocks Used Available Capacity Mounted\\nfake 99999999 0 99999999 0 /\\n'")
        self.command("lsof", "exit 1")
        self.command("launchctl", "exit 1")
        self.command("curl", 'echo Network_unavailable >&2; exit 7')

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_bootstrap(self, *args):
        return subprocess.run(
            ["bash", str(ROOT / "install"), *args],
            env=self.env,
            capture_output=True,
            text=True,
        )

    def install_tree(self, files, ref="0" * 40):
        repo = self.home / ".caravan" / "src" / "caravan"
        write_package(repo, files, ref=ref)
        return repo

    def test_already_up_to_date_changes_nothing(self):
        repo = self.install_tree(WEB_ONLY_OLD, ref="a" * 40)
        marker = repo / "proxy" / "web_server.py"
        before = marker.read_text()
        mtime = marker.stat().st_mtime_ns
        self.command(
            "curl",
            '''out=""; while [ "$#" -gt 0 ]; do case "$1" in -o) shift; out=$1 ;; esac; shift; done
printf '%s %s\\n' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > "$out"''',
        )
        result = self.run_bootstrap("--update")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(U.UP_TO_DATE, result.stdout)
        self.assertNotIn(U.OPENING, result.stdout)
        self.assertEqual(marker.read_text(), before)
        self.assertEqual(marker.stat().st_mtime_ns, mtime)
        self.assertFalse((self.home / ".caravan" / "install.lock").exists())

    def test_loaded_web_does_not_refuse_an_update(self):
        self.install_tree(WEB_ONLY_OLD, ref="0" * 40)
        # Integrity is valid. launchctl print succeeds (service loaded).
        self.command("launchctl", "exit 0")
        self.command(
            "curl",
            '''out=""; url=""; while [ "$#" -gt 0 ]; do case "$1" in https:*) url=$1 ;; -o) shift; out=$1 ;; esac; shift; done
case "$url" in */packaging-version*) printf '%s %s\\n' '1111111111111111111111111111111111111111' 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc' > "$out" ;; *) printf 'archive' > "$out" ;; esac''',
        )
        result = self.run_bootstrap("--update")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Stop the web first", result.stderr)
        self.assertNotIn("Stop the web first", result.stdout)
        # It proceeds past the old refusal and fails on the checksum (intentional).
        self.assertIn("checksum mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
