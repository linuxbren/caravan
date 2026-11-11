"""Portable bootstrap/doctor/command safety checks, without Mac or network."""
import contextlib
import io
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import caravan_doctor as doctor
import caravan as cli


class BootstrapTests(unittest.TestCase):
    def test_shell_syntax(self):
        for file in ("install", "scripts/install.sh", "scripts/package.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", str(ROOT/file)], capture_output=True).returncode, 0)

    def test_help_writes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(["bash", str(ROOT/"install"), "--help"], env={**os.environ, "HOME": home}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_invalid_options_fail_before_network(self):
        for args in (("--role", "other"), ("--port", "0"), ("--port", "999999"), ("--port", "x"), ("--role",), ("--unknown",)):
            with tempfile.TemporaryDirectory() as home:
                result = subprocess.run(["bash", str(ROOT/"install"), *args], env={**os.environ, "HOME": home}, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(Path(home).iterdir()), [])

    def test_non_mac_refused_without_mutation(self):
        if sys.platform == "darwin": self.skipTest("Linux-only refusal check")
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(["bash", str(ROOT/"install")], env={**os.environ, "HOME": home}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needs a Mac", result.stderr)
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_security_contract(self):
        text = (ROOT/"install").read_text()
        self.assertIn('"$ACTUAL" = "$SHA"', text)
        self.assertIn('--proto', text)
        self.assertIn('3f61099e261e449527141dbf125629fab33ad696468c8c90cebbac40185a306c', text)
        self.assertIn('install.lock', text)
        self.assertNotIn('sudo ', text.replace('# Mac bootstrap. Read this file before running it. No sudo, Git or Homebrew.', ''))
        self.assertNotIn('xattr ', text)
        self.assertNotIn('git clone', text)

    def test_current_user_guides_leave_paused_hermes_out(self):
        for file in ('README.md', 'INSTALL.md', 'docs/CONFIGURATION.md',
                     'docs/SERVICES.md', 'docs/WEB.md', 'docs/FILES.md', 'docs/PACKAGING.md',
                     'tools/caravan_doctor.py', 'install', 'scripts/install.sh'):
            self.assertNotIn('hermes', (ROOT/file).read_text().lower(), file)

    def test_readme_is_plain_mac_guide(self):
        text = (ROOT/"README.md").read_text()
        top = text.split('## For developers / details')[0]
        for jargon in ('shards', 'KV', 'GGUF', 'MLX', 'layers', 'ports'):
            self.assertIsNone(re.search(r"\b" + re.escape(jargon) + r"\b", top))
        for size in ('8 GB memory', '16 GB', '24 GB', '32 GB'):
            self.assertNotIn(size, text)
        self.assertIn('Terminal', top)
        self.assertIn('Return', top)


class DoctorTests(unittest.TestCase):
    def test_readonly_without_environment(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(doctor.platform, 'system', return_value='Linux'), mock.patch.object(doctor.platform, 'machine', return_value='x86_64'):
            rows = doctor.checks(home=home)
            self.assertTrue(any(level == 'ERROR' for level, _ in rows))
            self.assertTrue(any('not installed' in msg for _, msg in rows))
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_low_disk_reports_fix(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(doctor.shutil, 'disk_usage', return_value=mock.Mock(free=1)):
            rows = doctor.checks(home=home)
            self.assertTrue(any(level == 'ERROR' and 'Free disk' in msg for level, msg in rows))

    def test_busy_port_is_warning_not_kill(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(doctor.socket, 'create_connection'):
            rows = doctor.checks(home=home)
            self.assertTrue(any(level == 'WARN' and 'Do not kill' in msg for level, msg in rows))


class CommandTests(unittest.TestCase):
    def test_add_mini_opens_private_handoff_not_manual_ssh(self):
        with mock.patch.object(cli.service,'stored',return_value={'port':8190}), mock.patch.object(cli.service,'assert_owned'), mock.patch('caravan_pairing.launch_file',return_value=Path('/private/handoff.html')), mock.patch.object(cli.subprocess,'run',return_value=mock.Mock(returncode=0)) as run, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(['add-mini']),0)
            run.assert_called_once_with(['open','/private/handoff.html'])
            self.assertIn('Add this Mac',out.getvalue())
            self.assertNotIn('fingerprint',out.getvalue())

    def test_update_refuses_developer_checkout(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(cli, 'ROOT', Path(root)), mock.patch.object(cli.urllib.request, 'urlopen') as network, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['update']), 2)
            network.assert_not_called()

    def test_uninstall_uses_owned_service_only(self):
        with mock.patch.object(cli.service, 'stored', return_value={}), mock.patch.object(cli.service, 'assert_owned') as owned, mock.patch.object(cli.service, 'main', return_value=0) as control, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['uninstall']), 0)
            owned.assert_called_once_with({}, require=True)
            control.assert_called_once_with(['uninstall', '--name', 'web'])

    def test_unverified_service_refuses_action(self):
        with mock.patch.object(cli.service, 'stored', side_effect=ValueError('not owned')), mock.patch.object(cli.service, 'run_launchctl') as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['stop']), 2)
            run.assert_not_called()


class MockMacBootstrapTests(unittest.TestCase):
    """Exercise failure branches using harmless fake macOS commands on Linux."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root/'bin'; self.bin.mkdir()
        self.home = self.root/'home with spaces'; self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': str(self.bin)+':'+os.environ['PATH']}
        self.command('uname', 'if [ "$1" = -s ]; then echo Darwin; else echo arm64; fi')
        self.command('id', 'echo 501')
        self.command('sw_vers', 'echo 15.0')
        self.command('sysctl', 'echo 34359738368')
        self.command('df', "printf 'Filesystem blocks Used Available Capacity Mounted\\nfake 99999999 0 99999999 0 /\\n'")
        self.command('lsof', 'exit 1')
        self.command('curl', 'echo Network_unavailable >&2; exit 7')

    def tearDown(self): self.tmp.cleanup()

    def command(self, name, body):
        path = self.bin/name; path.write_text('#!/bin/bash\n'+body+'\n'); path.chmod(0o755)

    def run_bootstrap(self, *args):
        return subprocess.run(['bash', str(ROOT/'install'), *args], env=self.env, capture_output=True, text=True)

    def test_check_needs_no_python_or_network_and_writes_nothing(self):
        result = self.run_bootstrap('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('nothing changed', result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_intel_old_os_root_and_low_resources_fail_before_download(self):
        cases = [('uname', 'if [ "$1" = -s ]; then echo Darwin; else echo x86_64; fi', 'Apple Silicon'),
                 ('sw_vers', 'echo 13.0', 'Update macOS'), ('id', 'echo 0', 'without sudo'),
                 ('sysctl', 'echo 1024', 'too little memory'),
                 ('df', "printf 'a b c d\\nfake 100 99 1\\n'", 'Free at least')]
        for name, body, message in cases:
            old = (self.bin/name).read_text(); self.command(name, body)
            result = self.run_bootstrap()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual(list(self.home.iterdir()), [])
            (self.bin/name).write_text(old)

    def test_offline_retains_settings_and_releases_lock(self):
        settings = self.home/'.caravan/config.toml'; settings.parent.mkdir(); settings.write_text('keep me')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Check Wi-Fi', result.stderr)
        self.assertEqual(settings.read_text(), 'keep me')
        self.assertFalse((settings.parent/'install.lock').exists())

    def test_invalid_manifest_never_extracts_source(self):
        self.command('curl', '''while [ "$1" != -o ]; do shift; done; printf 'not-a-commit bad-hash\\n' > "$2"''')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid package manifest', result.stderr)
        self.assertFalse((self.home/'.caravan/src').exists())

    def test_checksum_mismatch_never_activates_source(self):
        self.command('curl', '''url=""; out=""; while [ "$#" -gt 0 ]; do case "$1" in https:*) url=$1 ;; -o) shift; out=$1 ;; esac; shift; done
case "$url" in */packaging-version*) printf '%040d %064d\\n' 0 0 > "$out" ;; *) printf 'wrong archive' > "$out" ;; esac''')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse((self.home/'.caravan/src/caravan').exists())

    def test_existing_unmanaged_source_is_never_replaced(self):
        repo = self.home/'.caravan/src/caravan'; repo.mkdir(parents=True); (repo/'mine').write_text('keep')
        self.command('curl', '''while [ "$1" != -o ]; do shift; done; printf '%040d %064d\\n' 0 0 > "$2"''')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('existing source install', result.stderr)
        self.assertEqual((repo/'mine').read_text(), 'keep')

    def test_stale_lock_is_not_removed(self):
        lock = self.home/'.caravan/install.lock'; lock.mkdir(parents=True)
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(lock.exists())

if __name__ == '__main__': unittest.main()
