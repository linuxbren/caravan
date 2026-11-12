"""Remove this Mac's owned Caravan jobs; never contact another Mac."""
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proxy"))

SCRIPTS = ('proxy/web_server.py', 'proxy/slot_pin_proxy.py', 'agent/caravan_agent.py',
           'agent/mlx_worker.py', 'tools/aux_worker.py')
MARKER = 'Caravan managed service v3'


def owned_plist(path, home):
    if path.is_symlink():
        return None
    try:
        p = plistlib.loads(path.read_bytes())
        if p.get('Label') != path.stem or not path.stem.startswith('com.caravan.v3.'):
            return None
        args = p.get('ProgramArguments') or []
        repo = Path(p.get('WorkingDirectory') or '/invalid')
        known = {str(repo / name) for name in SCRIPTS}
        # Legacy installer files have no Comment; verify repository + command.
        if (not (repo / 'agent/config.py').is_file() or len(args) < 2
                or not Path(args[0]).name.lower().startswith('python') or args[1] not in known):
            return None
        if p.get('EnvironmentVariables', {}).get('HOME', str(home)) != str(home):
            return None
        return p
    except (OSError, ValueError, TypeError):
        return None


def command_of(pid):
    from worker_ownership import command_of as inspect
    return inspect(pid)


def stop_exact(pid, expected, *, inspect=command_of, send=os.kill, pause=time.sleep):
    """Check twice, including before escalation; PID reuse fails closed."""
    if pid <= 1 or not expected or inspect(pid) != expected:
        return False
    try:
        send(pid, signal.SIGTERM)
        for _ in range(40):
            if inspect(pid) != expected:
                return True
            pause(.1)
        if inspect(pid) == expected:
            send(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return True


def workers(home, repos, *, listing=None, inspect=command_of):
    """Only exact repo worker scripts, or recorded engine/tunnel PIDs."""
    if listing is None:
        listing = subprocess.check_output(['ps', '-u', str(os.getuid()), '-o', 'pid=,command='], text=True)
    found = {}
    scripts = {str(repo / name) for repo in repos for name in SCRIPTS}
    for line in listing.splitlines():
        try:
            pid, command = line.strip().split(None, 1)
            args = shlex.split(command)
            if args and Path(args[0]).name.lower().startswith('python') and any(a in scripts for a in args[1:]):
                found[int(pid)] = command
        except ValueError:
            continue
    state = home / '.caravan/web-ui'
    tracked = []
    for marker in ('lead.pid', 'rpc-server.pid', 'remote-lead.pid', 'packer.pid'):
        p = state / marker
        if p.is_symlink():
            continue
        try:
            tracked.append(int(p.read_text().strip()))
        except (OSError, ValueError):
            pass
    p = state / 'gguf.json'
    if p.is_file() and not p.is_symlink():
        try:
            meta = json.loads(p.read_text())
            if meta.get('lead_pid'): tracked.append(int(meta['lead_pid']))
            tracked.extend(int(t['pid']) for t in meta.get('tunnels', []) if isinstance(t, dict))
        except (OSError, ValueError, TypeError, KeyError):
            pass
    for pid in tracked:
        command = inspect(pid)
        try:
            args = shlex.split(command)
        except ValueError:
            continue
        if not args:
            continue
        engine = Path(args[0]).name in ('llama-server', 'ggml-rpc-server')
        if engine:
            # An exact recorded executable in this user's managed runtime or
            # a known developer build; never stop an unrelated engine by name.
            exe = Path(args[0]).expanduser()
            engine = exe.is_relative_to(home / '.caravan') or any(exe.is_relative_to(r) for r in repos)
        tunnel = Path(args[0]).name == 'ssh' and '-N' in args and '-L' in args and any(a.startswith('127.0.0.1:') for a in args)
        if engine or tunnel:
            found[pid] = command
    return found


def marked_ssh_edits(home):
    """Preview all changes first; only exact pairing markers may be removed."""
    changes = []
    folder = home / '.ssh'
    if folder.is_symlink():
        raise ValueError('SSH folder is a link; review its marked Caravan entries manually before uninstalling.')
    block = re.compile(r'^# BEGIN caravan-pair:([a-f0-9]{32})\n.*?^# END caravan-pair:\1\n?', re.M | re.S)
    line = re.compile(r'^.* # caravan-pair:[a-f0-9]{32}\n?$', re.M)
    for name in ('config', 'known_hosts', 'authorized_keys'):
        path = folder / name
        if path.is_symlink():
            raise ValueError('SSH file is a link; review it manually before uninstalling: ' + name)
        if not path.exists():
            continue
        old = path.read_text()
        new = line.sub('', block.sub('', old))
        if '# BEGIN caravan-pair:' in new or '# END caravan-pair:' in new:
            raise ValueError('Incomplete Caravan SSH marker; inspect ' + name + ' before uninstalling.')
        if old != new:
            changes.append((path, new))
    return changes


def total_bytes(root):
    total = 0
    if root.exists():
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in files:
                total += (Path(directory) / name).lstat().st_size
    return total


def uninstall(home=None, *, yes=False, confirm=input, run=None, inspect=command_of, send=os.kill, remote_off=None):
    import caravan_service as service
    from caravan_path import configure
    home = Path(home or Path.home())
    root = home / '.caravan'
    if root.is_symlink():
        raise ValueError('Caravan folder is a link; inspect it manually. Nothing removed.')
    run = run or service.run_launchctl
    service.check_platform()
    jobs = []
    unverified = []
    repos = {Path(__file__).resolve().parents[1]}
    for path in sorted((home / 'Library/LaunchAgents').glob('com.caravan.v3.*.plist')):
        plan = owned_plist(path, home)
        if plan is None:
            unverified.append(path.name)
            continue
        jobs.append((path, plan))
        repos.add(Path(plan['WorkingDirectory']))
    # Preview marked edits before stopping anything. No unrelated SSH entries move.
    edits = marked_ssh_edits(home)
    for name in ('.zprofile', '.bash_profile'):
        profile = home / name
        if profile.is_symlink():
            raise ValueError('Shell profile is a link; remove its Caravan block manually first.')
        text = profile.read_text() if profile.exists() else ''
        if text.count('# >>> caravan >>>') != text.count('# <<< caravan <<<'):
            raise ValueError('Incomplete Caravan PATH block; inspect ' + name + ' first.')
    size = total_bytes(root) + sum(p.stat().st_size for p, _ in jobs)
    prompt = (f'Remove paired Macs first. Delete all Caravan services, models, settings, runtimes, '
              f'pairing keys and ~/.caravan ({size / 1e9:.2f} GB total), plus marked SSH/PATH entries? [y/N] ')
    if not yes and confirm(prompt).strip().lower() not in ('y', 'yes'):
        return 'Cancelled. Caravan files were kept.'
    # Drop only Caravan's Tailscale serve entry before files disappear.
    try:
        if remote_off is None:
            from caravan_remote import turn_off
            turn_off(home=home, missing_ok=True, quiet=True)
        else:
            remote_off()
    except Exception:
        pass
    # Collect worker identities before bootout; the web may exit independently.
    tracked = workers(home, repos, inspect=inspect)
    for path, plan in jobs:
        target = service.domain() + '/' + plan['Label']
        if run(['print', target]).returncode == 0:
            result = run(['bootout', target])
            if result.returncode:
                raise ValueError('Could not stop ' + plan['Label'] + '; files kept. Run caravan doctor.')
        path.unlink()
    for pid, command in tracked.items():
        stop_exact(pid, command, inspect=inspect, send=send)
    for path, text in edits:
        path.write_text(text)
    configure('remove', home)
    if root.exists():
        shutil.rmtree(root)
    suffix = ' Unverified startup files left untouched.' if unverified else ''
    return 'Caravan uninstalled; all Caravan data removed.' + suffix
