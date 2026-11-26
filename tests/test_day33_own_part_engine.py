"""CAR-10: install and update set up the own-part engine. No Macs or network."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ("agent", "proxy", "tools"):
    sys.path.insert(0, str(ROOT / folder))

import gguf_runtime as R
import caravan_update_peers as Peers
from i18n_check import english_source


def _write_engine_tree(root, *, marker=None, binaries=True, dylib=True):
    root = Path(root)
    (root / "build" / "bin").mkdir(parents=True, exist_ok=True)
    (root / "caravan-shards-version").write_text((marker if marker is not None else R.MARKER) + "\n")
    if binaries:
        for name in ("llama-server", "ggml-rpc-server"):
            p = root / "build" / "bin" / name
            p.write_bytes(b"FAKE-ENGINE")
            p.chmod(0o755)
    if dylib:
        (root / "build" / "bin" / "libggml-rpc.dylib").write_bytes(b"FAKE-DYLIB")
    return root


def _archive_from_tree(tree, dest, *, unsafe=False, missing=False, wrong_marker=False):
    tree = Path(tree)
    if wrong_marker:
        (tree / "caravan-shards-version").write_text("wrong\n")
    if missing:
        (tree / "build" / "bin" / "ggml-rpc-server").unlink()
    dest = Path(dest)
    with tarfile.open(dest, "w:gz") as tar:
        for path in tree.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(tree)
            arcname = f"{R.ARCHIVE_DIR}/{rel}"
            if unsafe and path.name == "llama-server":
                arcname = "../../escape"
            info = tarfile.TarInfo(arcname)
            data = path.read_bytes()
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    return dest


class PrebuiltInstallTests(unittest.TestCase):
    def fixture(self, *, unsafe=False, missing=False, bad_hash=False, wrong_marker=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        tree = _write_engine_tree(home / "src-tree")
        archive = _archive_from_tree(tree, home / "engine.tgz", unsafe=unsafe, missing=missing, wrong_marker=wrong_marker)
        pin = {
            "pin": R.PIN,
            "url": "https://example.invalid/caravan-gguf-shards-76a67730-macos-arm64.tar.gz",
            "sha256": "0" * 64 if bad_hash else hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
        return home, archive, pin

    def test_hash_verified_before_extracting(self):
        home, archive, pin = self.fixture(bad_hash=True)
        with self.assertRaisesRegex(ValueError, "safety check"):
            R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertFalse(R.location(home).exists())

    def test_valid_install_is_idempotent_and_preferred(self):
        home, archive, pin = self.fixture()
        dest = R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertTrue(R.ready(home))
        self.assertEqual(dest, R.location(home) / "build" / "bin")
        self.assertEqual((R.location(home) / "caravan-shards-version").read_text().strip(), R.MARKER)
        self.assertEqual(
            R.ensure(home, Mock(side_effect=AssertionError("redownload")), pin=pin),
            dest,
        )

    def test_unsafe_archive_refused(self):
        home, archive, pin = self.fixture(unsafe=True)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertFalse(R.location(home).exists())

    def test_servers_required(self):
        home, archive, pin = self.fixture(missing=True)
        with self.assertRaisesRegex(ValueError, "missing"):
            R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertFalse(R.location(home).exists())

    def test_wrong_marker_refused(self):
        home, archive, pin = self.fixture(wrong_marker=True)
        with self.assertRaisesRegex(ValueError, "missing"):
            R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertFalse(R.location(home).exists())

    def test_existing_incomplete_engine_not_destroyed(self):
        home, archive, pin = self.fixture()
        root = R.location(home)
        root.mkdir(parents=True)
        (root / "keep").write_text("keep")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertEqual((root / "keep").read_text(), "keep")

    def test_prebuilt_skips_source_build(self):
        home, archive, pin = self.fixture()
        with patch.object(R.subprocess, "run", side_effect=AssertionError("source build")):
            R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        self.assertTrue(R.ready(home))

    def test_pack_script_archive_is_installable(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        tree = _write_engine_tree(home / "built")
        dest = home / "packed.tgz"
        sys.path.insert(0, str(ROOT / "scripts"))
        # Load by path; the file name has a hyphen.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "package_gguf_shards", ROOT / "scripts" / "package-gguf-shards.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        digest = mod.pack(tree, dest)
        self.assertEqual(digest, hashlib.sha256(dest.read_bytes()).hexdigest())
        pin = {
            "pin": R.PIN,
            "url": "https://example.invalid/packed.tgz",
            "sha256": digest,
        }
        R.ensure(home, lambda u, p: shutil.copyfile(dest, p), pin=pin)
        self.assertTrue(R.ready(home))
        self.assertTrue((R.location(home) / "build" / "bin" / "libggml-rpc.dylib").is_file())


class SourceFallbackTests(unittest.TestCase):
    def test_missing_cmake_is_plain_and_does_not_fetch(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        pin = {"pin": R.PIN, "url": "", "sha256": ""}
        env = {"PATH": "/usr/bin"}
        with patch.object(R.os, "environ", env), patch.object(R.shutil, "which", return_value=None), patch.object(
            R.subprocess, "run", side_effect=AssertionError("no network or cmake")
        ), patch.object(R.sys, "platform", "linux"):
            with self.assertRaisesRegex(FileNotFoundError, "cmake"):
                R.ensure(home, pin=pin)
        self.assertFalse(R.ready(home))
        # No source tree started.
        self.assertFalse((home / ".caravan/runtimes/gguf-shards" / R.PIN).exists())

    def test_missing_clt_on_mac_is_plain_and_prompts(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        pin = {"pin": R.PIN, "url": "", "sha256": ""}
        calls = []

        def run(argv, **kwargs):
            calls.append(list(argv))
            result = Mock()
            result.returncode = 1
            return result

        with patch.object(R.sys, "platform", "darwin"), patch.object(R.subprocess, "run", side_effect=run):
            with self.assertRaisesRegex(FileNotFoundError, "Command Line Tools"):
                R.ensure(home, pin=pin)
        self.assertIn(["xcode-select", "-p"], calls)
        self.assertIn(["xcode-select", "--install"], calls)
        self.assertFalse(R.ready(home))

    def test_configured_env_is_not_overwritten(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        missing = Path(tmp.name) / "missing" / "build" / "bin"
        with patch.dict(os.environ, {"CARAVAN_GGUF_SHARD_BIN": str(missing)}):
            with self.assertRaises(FileNotFoundError):
                R.ensure(Path(tmp.name), pin={"url": "https://example.invalid/x", "sha256": "ab" * 32})
        self.assertFalse((Path(tmp.name) / ".caravan/runtimes/gguf-shards" / R.PIN).exists())


class PinAndHookTests(unittest.TestCase):
    def test_release_json_matches_source_pin(self):
        pin = R.release_pin()
        self.assertEqual(pin["pin"], R.PIN)
        self.assertEqual(R.PIN, "76a67730ffc7d650dffa4db04d96be84a59e7ef3")
        if R.prebuilt_configured(pin):
            self.assertTrue(pin["url"].startswith("https://"))
            self.assertRegex(pin["sha256"], r"^[a-f0-9]{64}$")
            self.assertIn("macos-arm64.tar.gz", pin["url"])
        else:
            self.assertFalse((pin.get("url") or "").strip())
            self.assertFalse((pin.get("sha256") or "").strip())

    def test_prebuilt_configured_rejects_partial_pins(self):
        self.assertFalse(R.prebuilt_configured({"url": "", "sha256": ""}))
        self.assertFalse(R.prebuilt_configured({"url": "https://example.invalid/x", "sha256": ""}))
        self.assertFalse(R.prebuilt_configured({"url": "http://insecure.example/x", "sha256": "ab" * 32}))
        self.assertFalse(R.prebuilt_configured({"url": "https://example.invalid/x", "sha256": "xyz"}))
        self.assertTrue(R.prebuilt_configured({"url": "https://example.invalid/x", "sha256": "ab" * 32}))

    def test_every_role_installs_own_part_engine_after_official_engine(self):
        script = english_source(ROOT / "scripts/install.sh")
        self.assertIn('run "$VENV/bin/python" "$REPO/agent/llama_runtime.py"', script)
        self.assertIn('run "$VENV/bin/python" "$REPO/agent/gguf_runtime.py"', script)
        self.assertIn("Preparing the own-part GGUF engine on this Mac", script)
        self.assertLess(script.index("llama_runtime.py"), script.index("gguf_runtime.py"))
        self.assertLess(script.index("gguf_runtime.py"), script.index('if [ "$ROLE" = lead ]; then\n  KIND=web'))

    def test_update_reuses_installer(self):
        self.assertIn('"--update", "--role", role', english_source(ROOT / "tools/caravan.py"))

    def test_peer_update_timeout_is_short_with_prebuilt_and_long_without(self):
        with patch.object(R, "prebuilt_configured", return_value=True):
            # Import path: peer_update_timeout imports gguf_runtime itself.
            with patch("gguf_runtime.prebuilt_configured", return_value=True):
                self.assertEqual(Peers.peer_update_timeout(), 600)
        with patch("gguf_runtime.prebuilt_configured", return_value=False):
            self.assertEqual(Peers.peer_update_timeout(), 2400)
        # And the live pin file (empty url today) should take the long path.
        if not R.prebuilt_configured():
            self.assertEqual(Peers.peer_update_timeout(), 2400)

    def test_engine_status_sees_a_prebuilt_install(self):
        import gguf_split as G
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        tree = _write_engine_tree(home / "src-tree")
        archive = _archive_from_tree(tree, home / "engine.tgz")
        pin = {
            "pin": R.PIN,
            "url": "https://example.invalid/x",
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
        R.ensure(home, lambda u, p: shutil.copyfile(archive, p), pin=pin)
        with patch.object(R.Path, "home", return_value=home):
            # engine_status uses Path.home() via the probe script.
            status = None
            # Re-implement the same layout check the probe uses, against this home.
            from gguf_split import ENGINE_CHECK_CODE, _engine_pin
            import json as _json
            code = ENGINE_CHECK_CODE.replace("PIN", repr(_engine_pin()), 1)
            # Run the probe with HOME pointed at the temp home.
            env = dict(os.environ)
            env["HOME"] = str(home)
            import subprocess
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            status = _json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(status["ready"])
        self.assertEqual(status["missing"], [])


class DoctorAndLocaleTests(unittest.TestCase):
    def test_doctor_reports_own_part_engine(self):
        src = english_source(ROOT / "tools/caravan_doctor.py")
        self.assertIn("Own-part engine:", src)
        self.assertIn("gguf_runtime", src)
        self.assertLess(src.index("llama_runtime"), src.index("gguf_runtime"))

    def test_install_still_names_no_toolchain_for_beginners(self):
        # Beginner install promise (Day 23) stays: the prebuilt path needs no tools.
        text = (ROOT / "INSTALL.md").read_text()
        self.assertIn("No Git", text)
        self.assertIn("developer tools", text.lower())


class InstallStepFailsSoftTests(unittest.TestCase):
    """The install/update hook must not abort when the engine can't be set up."""

    def _run_script(self, home, *, env_extra=None, pin_empty=True):
        env = dict(os.environ)
        env["HOME"] = str(home)
        # No git or cmake on PATH; invoke Python by absolute path.
        empty_path = home / "empty-bin"
        empty_path.mkdir(parents=True, exist_ok=True)
        env["PATH"] = str(empty_path)
        env["PYTHONPATH"] = os.pathsep.join(str(ROOT / n) for n in ("agent", "tools", "proxy"))
        env.pop("CARAVAN_GGUF_SHARD_BIN", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(ROOT / "agent" / "gguf_runtime.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )

    def test_script_exits_zero_with_no_toolchain_and_no_prebuilt(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        result = self._run_script(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hey, I'm sorry", result.stdout)
        self.assertRegex(result.stdout, r"git|cmake")
        self.assertFalse(R.ready(home))
        # No engine tree was started under the fake HOME.
        self.assertFalse((home / ".caravan/runtimes/gguf-shards" / R.PIN).exists())

    def test_install_sh_keeps_going_after_the_engine_step(self):
        """Closest practical stand-in for scripts/install.sh: set -euo pipefail,
        the same run hook, then a following command. A missing engine must
        not fire the ERR trap or stop the rest of setup."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        empty_path = home / "empty-bin"
        empty_path.mkdir()
        script = r"""
set -euo pipefail
trap 'echo TRAPPED >&2; exit 1' ERR
run() { "$@"; }
run "$PYTHON" "$REPO/agent/gguf_runtime.py"
echo KEEP_GOING
"""
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["PATH"] = str(empty_path)
        env["PYTHON"] = sys.executable
        env["REPO"] = str(ROOT)
        env["PYTHONPATH"] = os.pathsep.join(str(ROOT / n) for n in ("agent", "tools", "proxy"))
        env.pop("CARAVAN_GGUF_SHARD_BIN", None)
        bash = shutil.which("bash") or "/bin/bash"
        result = subprocess.run(
            [bash, "-s"],
            input=script,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KEEP_GOING", result.stdout)
        self.assertIn("Hey, I'm sorry", result.stdout)
        self.assertNotIn("TRAPPED", result.stdout + result.stderr)

    def test_checksum_refusal_is_visible_but_nonfatal_and_doctor_still_missing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        tree = _write_engine_tree(home / "src-tree")
        archive = _archive_from_tree(tree, home / "engine.tgz")
        pin = {
            "pin": R.PIN,
            "url": "https://example.invalid/x",
            "sha256": "0" * 64,
        }
        buf = io.StringIO()
        code = R.main(home, lambda u, p: shutil.copyfile(archive, p), pin=pin, out=buf)
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("Hey, I'm sorry", out)
        self.assertIn("safety check", out)
        self.assertFalse(R.ready(home))
        self.assertFalse(R.location(home).exists())

    def test_remote_update_still_succeeds_when_the_engine_step_notes_not_ready(self):
        """caravan update on another Mac runs install.sh, which runs this
        script. A soft-fail (exit 0, not-ready note) must not mark that Mac
        as failed."""
        node = {"id": "peer", "label": "2nd Mac", "ssh": "other-mac"}
        note = "Hey, I'm sorry. ... (For whoever helps you: needs cmake)"

        def runner(argv, **kwargs):
            text = " ".join(str(a) for a in argv)
            result = Mock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            if "true" in text:
                return result
            # The actual update command. Install continued; the note is in the log.
            result.stdout = note
            return result

        row = Peers.update_peer(node, expected=None, runner=runner)
        self.assertEqual(row["phase"], "done")
        self.assertFalse(row.get("can_retry"))
        self.assertNotEqual(row.get("phase"), "failed")


if __name__ == "__main__":
    unittest.main()
