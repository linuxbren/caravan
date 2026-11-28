"""A failed `caravan update` must say why, and a slow page must not undo a good one.

No Macs, no network: fake launchd, fake installer, fake page.
"""
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ("agent", "proxy", "tools", "tests"):
    sys.path.insert(0, str(ROOT / folder))

import caravan_update as U
import caravan_update_check as UC
import gguf_runtime as R
import test_caravan_update as base

WEB_ONLY_NEW = base.WEB_ONLY_NEW
WEB_ONLY_OLD = base.WEB_ONLY_OLD


class _Page:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.StringIO(json.dumps(self.payload))

    def __exit__(self, *a):
        return False


class WaitForWebTests(unittest.TestCase):
    def test_idle_page_with_no_model_counts_as_up(self):
        opener = lambda url, timeout=2: _Page({"worker": {"status": "idle"}})
        self.assertTrue(U.wait_for_web(8190, opener=opener, pause=lambda s: None))

    def test_default_wait_is_longer_than_the_old_30_seconds(self):
        self.assertGreater(U.WEB_WAIT_SECONDS, 30)
        self.assertGreater(U.WEB_WAIT_SAVED_MODEL_SECONDS, U.WEB_WAIT_SECONDS)

    def test_saved_model_gets_the_longer_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(U.web_wait_timeout(home), U.WEB_WAIT_SECONDS)
            path = U.last_model_path(home)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"schema": 1, "request": {"model_id": "m"}}))
            self.assertEqual(U.web_wait_timeout(home), U.WEB_WAIT_SAVED_MODEL_SECONDS)

    def test_page_that_comes_up_after_40_seconds_is_accepted(self):
        """The old fixed 30 s limit discarded this; a late page now still passes."""
        clock = {"t": 1000.0}
        calls = {"n": 0}

        def opener(url, timeout=2):
            calls["n"] += 1
            if clock["t"] < 1040.0:
                raise OSError("connection refused")
            return _Page({"worker": {}})

        def pause(seconds):
            clock["t"] += 1.0

        with patch.object(U.time, "monotonic", lambda: clock["t"]):
            self.assertTrue(U.wait_for_web(8190, opener=opener, pause=pause))
        self.assertGreater(calls["n"], 30)

    def test_timeout_error_names_the_last_problem(self):
        clock = {"t": 0.0}
        opener = lambda url, timeout=2: (_ for _ in ()).throw(OSError("connection refused"))
        with patch.object(U.time, "monotonic", lambda: clock["t"]):
            with self.assertRaises(ValueError) as caught:
                U.wait_for_web(8190, timeout=3, opener=opener, pause=lambda s: clock.__setitem__("t", clock["t"] + 1))
        self.assertIn("connection refused", str(caught.exception))

    def test_a_page_that_is_not_caravans_is_named_in_the_error(self):
        clock = {"t": 0.0}
        opener = lambda url, timeout=2: _Page({"hello": 1})
        with patch.object(U.time, "monotonic", lambda: clock["t"]):
            with self.assertRaises(ValueError) as caught:
                U.wait_for_web(8190, timeout=2, opener=opener, pause=lambda s: clock.__setitem__("t", clock["t"] + 1))
        self.assertIn("not as Caravan", str(caught.exception))


class FailureReasonTests(base.ApplyTests):
    def test_reason_is_truncated_and_one_line(self):
        reason = U.failure_reason(ValueError("line one\n\n   line two " + "x" * 600))
        self.assertNotIn("\n", reason)
        self.assertEqual(len(reason), U.REASON_LIMIT)

    def test_slow_page_failure_keeps_the_real_reason(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)

        def wait(port, **kwargs):
            raise ValueError("The page did not come back in time: connection refused")

        result, text = self.apply(wait=wait)
        self.assertEqual(result, 1)
        lines = text.strip().splitlines()
        self.assertEqual(lines[-1], U.FAILED)
        self.assertIn("connection refused", lines[-2])
        self.assertIn("Why the update failed", lines[-2])
        self.assertIn("connection refused", U.read_failure(self.home))

    def test_install_failure_keeps_the_real_reason(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        result, text = self.apply(installer=self.installer(fail_on="new"))
        self.assertEqual(result, 1)
        self.assertEqual(U.read_failure(self.home), "pip failed")
        self.assertIn("pip failed", text.strip().splitlines()[-2])

    def test_rollback_install_does_not_overwrite_the_failed_installs_log(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        logs = []

        def installer(repo, **kwargs):
            logs.append(Path(kwargs["log"]).name)
            if (Path(repo) / ".caravan-package").read_text().strip() == "1" * 40:
                raise ValueError("pip failed")

        self.apply(installer=installer)
        self.assertEqual(logs[0], "update.log")
        self.assertEqual(logs[-1], U.ROLLBACK_LOG_NAME)

    def test_success_clears_an_old_reason(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW)
        U.save_failure(self.home, "from an earlier try")
        result, _ = self.apply()
        self.assertEqual(result, 0)
        self.assertEqual(U.read_failure(self.home), "")

    def test_apply_waits_with_the_scaled_timeout(self):
        self.seed(WEB_ONLY_OLD, WEB_ONLY_NEW, last_model=True)
        seen = {}

        def wait(port, **kwargs):
            seen.update(kwargs)
            return True

        result, _ = self.apply(wait=wait)
        self.assertEqual(result, 0)
        self.assertEqual(seen["timeout"], U.WEB_WAIT_SAVED_MODEL_SECONDS)


class ProgressDetailTests(unittest.TestCase):
    def test_failed_local_update_shows_the_reason_in_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo = home / "repo"
            repo.mkdir()
            (repo / ".caravan-package").write_text("old\n")

            def fake_cli(repo_arg, **kw):
                U.save_failure(home, "The page did not come back in time: connection refused")
                return 1

            with patch.object(UC, "_run_cli_update", fake_cli):
                code = UC.apply_job(home, repo, peers=[])
            self.assertEqual(code, 1)
            progress = UC.load_progress(home)
            self.assertEqual(progress["phase"], "failed")
            self.assertIn("connection refused", progress["detail"])
            local = [m for m in progress["macs"] if m.get("mine")][0]
            self.assertIn("connection refused", local["detail"])

    def test_reason_written_by_a_child_process_is_read_back(self):
        """The real path: `caravan update` runs install -> caravan_update.py apply as a child."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo = home / "repo"
            repo.mkdir()
            (repo / ".caravan-package").write_text("old\n")

            def fake_cli(repo_arg, **kw):
                code = (
                    "import sys; sys.path.insert(0, %r); import caravan_update as U; "
                    "U.save_failure(%r, 'child said: connection refused'); sys.exit(1)"
                ) % (str(ROOT / "tools"), str(home))
                return subprocess.run([sys.executable, "-c", code]).returncode

            with patch.object(UC, "_run_cli_update", fake_cli):
                self.assertEqual(UC.apply_job(home, repo, peers=[]), 1)
            progress = UC.load_progress(home)
            self.assertEqual(progress["detail"], "child said: connection refused")

    def test_exception_path_also_reads_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo = home / "repo"
            repo.mkdir()
            (repo / ".caravan-package").write_text("old\n")

            def fake_cli(repo_arg, **kw):
                U.save_failure(home, "written before the raise")
                raise OSError("boom")

            with patch.object(UC, "_run_cli_update", fake_cli):
                self.assertEqual(UC.apply_job(home, repo, peers=[]), 1)
            progress = UC.load_progress(home)
            self.assertEqual(progress["detail"], "written before the raise")
            local = [m for m in progress["macs"] if m.get("mine")][0]
            self.assertEqual(local["detail"], "written before the raise")

    def test_old_reason_is_not_shown_for_a_new_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo = home / "repo"
            repo.mkdir()
            (repo / ".caravan-package").write_text("old\n")
            U.save_failure(home, "stale reason")
            with patch.object(UC, "_run_cli_update", lambda *a, **k: 1):
                UC.apply_job(home, repo, peers=[])
            self.assertEqual(UC.load_progress(home)["detail"], "")


class EngineStepFailureTests(unittest.TestCase):
    def _run_main(self, error):
        out = io.StringIO()
        with patch.object(R, "ensure", side_effect=error):
            code = R.main(out=out)
        return code, out.getvalue()

    def test_failed_git_step_is_soft(self):
        code, text = self._run_main(subprocess.CalledProcessError(128, ["git", "-C", "/x/source.git", "fetch", "--depth=1", "u", "p"]))
        self.assertEqual(code, 0)
        self.assertIn("git fetch step failed (exit code 128)", text)
        self.assertNotIn("/x/", text)

    def test_failed_cmake_build_is_soft(self):
        code, text = self._run_main(subprocess.CalledProcessError(2, ["cmake", "--build", "/x/build"]))
        self.assertEqual(code, 0)
        self.assertIn("cmake build step failed", text)

    def test_timed_out_build_is_soft(self):
        code, text = self._run_main(subprocess.TimeoutExpired(["cmake", "-S", "a", "-B", "b"], 300))
        self.assertEqual(code, 0)
        self.assertIn("cmake configure step took too long", text)

    def test_real_script_exits_zero_when_git_fails(self):
        """The reproduction: a failing git used to make install.sh (and the update) fail."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            (tmp / "home").mkdir()
            git = tmp / "bin" / "git"
            git.write_text("#!/bin/sh\necho 'fatal: simulated network failure' >&2\nexit 128\n")
            git.chmod(0o755)
            cmake = tmp / "bin" / "cmake"
            cmake.write_text("#!/bin/sh\nexit 0\n")
            cmake.chmod(0o755)
            env = {"HOME": str(tmp / "home"), "PATH": f"{tmp / 'bin'}:/usr/bin:/bin", "CARAVAN_UI_LANG": "en"}
            result = subprocess.run(
                [sys.executable, str(ROOT / "agent" / "gguf_runtime.py")],
                env=env, capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hey, I'm sorry", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
