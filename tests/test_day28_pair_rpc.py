"""Day 28: a paired Mac's key must let the lead reach the GGUF rpc-server tunnel.

Before this fix the pairing key allowed only 127.0.0.1:8194, so a GGUF split on a
freshly paired Mac failed with "Couldn't reach <Mac> for the split". Scratch homes
only; the live OpenSSH check runs a throwaway sshd on loopback when one exists.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'proxy')); sys.path.insert(0, str(ROOT/'agent')); sys.path.insert(0, str(ROOT/'tests'))
import pairing_store as S
from pairing_store import Store
import gguf_split as G
from test_pairing import KEY, Scratch

PEER = 'ab' * 16
OLD = ('restrict,port-forwarding,permitopen="127.0.0.1:8194",permitlisten="127.0.0.1:8194",'
       'from="' + ','.join(S.PRIVATE_CIDRS) + '"')


class KeyOptions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)/'home'
        self.store = Store(self.home, repo=self.home/'src'); self.auth = self.home/'.ssh/authorized_keys'
    def tearDown(self): self.tmp.cleanup()

    def test_new_pair_allows_model_port_and_rpc_port_only(self):
        self.store.authorize(PEER, KEY)
        line = self.auth.read_text().strip()
        self.assertIn('permitopen="127.0.0.1:8194"', line)
        self.assertIn(f'permitopen="127.0.0.1:{G.RPC_PORT}"', line)
        self.assertEqual(line.count('permitopen='), 2)
        self.assertEqual(line.count('permitlisten='), 1); self.assertIn('permitlisten="127.0.0.1:8194"', line)
        self.assertTrue(line.startswith('restrict,port-forwarding,')); self.assertTrue(line.endswith('# caravan-pair:' + PEER))

    def test_rpc_port_follows_the_split_setting(self):
        with mock.patch.dict(os.environ, {'CARAVAN_GGUF_RPC_PORT': '50999'}):
            self.store.authorize(PEER, KEY)
        self.assertIn('permitopen="127.0.0.1:50999"', self.auth.read_text())
        with mock.patch.dict(os.environ, {'CARAVAN_GGUF_RPC_PORT': 'nonsense'}):
            self.assertIn('permitopen="127.0.0.1:50052"', S.key_options())

    def test_refresh_upgrades_only_older_caravan_lines(self):
        self.auth.parent.mkdir(parents=True)
        mine = KEY + ' my-laptop\n'
        custom = 'restrict,permitopen="127.0.0.1:9" ' + KEY + ' # caravan-pair:' + 'cd' * 16 + '\n'
        self.auth.write_text('# unrelated\n' + mine + OLD + ' ' + KEY + ' # caravan-pair:' + PEER + '\n' + custom)
        self.assertEqual(self.store.refresh_authorizations(), 1)
        text = self.auth.read_text()
        self.assertIn(S.key_options() + ' ' + KEY + ' # caravan-pair:' + PEER + '\n', text)
        self.assertTrue(text.startswith('# unrelated\n' + mine)); self.assertTrue(text.endswith(custom))
        self.assertNotIn(OLD, text)
        before = text; self.assertEqual(self.store.refresh_authorizations(), 0); self.assertEqual(self.auth.read_text(), before)

    def test_refresh_leaves_missing_or_linked_file_alone(self):
        self.assertEqual(self.store.refresh_authorizations(), 0); self.assertFalse(self.auth.exists())
        self.auth.parent.mkdir(parents=True); target = self.home/'elsewhere'
        target.write_text(OLD + ' ' + KEY + ' # caravan-pair:' + PEER + '\n'); self.auth.symlink_to(target)
        self.assertEqual(self.store.refresh_authorizations(), 0); self.assertIn(OLD, target.read_text())


class StartupUpgrade(Scratch):
    def test_helper_start_upgrades_an_existing_pair(self):
        home = self.root/'helper home'; auth = home/'.ssh/authorized_keys'; auth.parent.mkdir(parents=True)
        auth.write_text(OLD + ' ' + KEY + ' # caravan-pair:' + PEER + '\n')
        self.manager('helper home')
        self.assertIn(f'permitopen="127.0.0.1:{G.RPC_PORT}"', auth.read_text())

    def test_fresh_pair_through_the_protocol_allows_the_rpc_port(self):
        lead, helper, offer = self.pair()
        lead.pair(helper.id, offer['code'][:4] + '-' + offer['code'][4:])
        text = (helper.store.home/'.ssh/authorized_keys').read_text()
        self.assertIn(f'permitopen="127.0.0.1:{G.RPC_PORT}"', text); self.assertIn('caravan-pair:' + lead.id, text)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def echo_server(port):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(('127.0.0.1', port)); srv.listen(4)
    def run():
        while True:
            try: c, _ = srv.accept()
            except OSError: return
            with c: c.sendall(b'RPC-OK:' + c.recv(64))
    threading.Thread(target=run, daemon=True).start(); return srv


SSHD = next((p for p in ('/usr/sbin/sshd', '/usr/bin/sshd') if os.path.exists(p)), None)


@unittest.skipUnless(SSHD and shutil.which('ssh') and shutil.which('ssh-keygen'), 'needs OpenSSH')
class LiveOpenSSH(unittest.TestCase):
    """The real sshd honours the written options: rpc port opens, other ports do not."""
    def test_tunnel_reaches_rpc_port_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); rpc, other, sport = free_port(), free_port(), free_port()
            for n in ('host', 'client'):
                subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(tmp/n)], check=True)
            home = tmp/'helper'; store = Store(home, repo=tmp/'src')
            with mock.patch.dict(os.environ, {'CARAVAN_GGUF_RPC_PORT': str(rpc)}):
                store.authorize(PEER, (tmp/'client.pub').read_text())
            conf = tmp/'sshd.conf'
            conf.write_text('\n'.join([f'Port {sport}', 'ListenAddress 127.0.0.1', f'HostKey {tmp/"host"}',
                f'PidFile {tmp/"sshd.pid"}', f'AuthorizedKeysFile {home/".ssh/authorized_keys"}',
                'PasswordAuthentication no', 'KbdInteractiveAuthentication no', 'PubkeyAuthentication yes',
                'UsePAM no', 'StrictModes no', 'AllowTcpForwarding yes', 'LogLevel ERROR']) + '\n')
            servers = [echo_server(rpc), echo_server(other)]
            sshd = subprocess.Popen([SSHD, '-D', '-e', '-f', str(conf)], stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 10
                while True:
                    try: socket.create_connection(('127.0.0.1', sport), 0.5).close(); break
                    except OSError:
                        if time.time() > deadline or sshd.poll() is not None: self.skipTest('scratch sshd did not start')
                        time.sleep(.1)
                base = ['ssh', '-i', str(tmp/'client'), '-p', str(sport), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                        '-o', 'StrictHostKeyChecking=no', '-o', f'UserKnownHostsFile={tmp/"kh"}', '-o', 'LogLevel=ERROR']
                user = f'{os.environ.get("USER") or os.getlogin()}@127.0.0.1'
                def through(port):
                    return subprocess.run(base + ['-W', f'127.0.0.1:{port}', user], input=b'ping', capture_output=True, timeout=20)
                ok = through(rpc)
                if b'Permission denied' in ok.stderr: self.skipTest('scratch sshd refused this account')
                self.assertEqual(ok.stdout, b'RPC-OK:ping', ok.stderr)
                self.assertNotEqual(through(other).stdout, b'RPC-OK:ping')
            finally:
                sshd.terminate(); sshd.wait(5)
                for s in servers: s.close()


if __name__ == '__main__':
    unittest.main()
