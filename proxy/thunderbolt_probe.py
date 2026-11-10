"""Bound, non-disruptive Thunderbolt TCP22 identity probes. Never touch MLX sockets.

Darwin IP_BOUND_IF pins every transport byte to the observed interface. SSH
uses existing host-key trust, no config/mux/proxy fallback and no key updates.
The only remote command echoes a fresh nonce, hostname and SSH_CONNECTION.
"""
from __future__ import annotations
import getpass
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import select
import secrets
import shlex
import socket
import subprocess
import sys
import time

META = 'CARAVAN_TB_TRANSPORT '
MAX_BYTES = 262144


def transport(interface, source, target, *, sock_factory=socket.socket, platform=None):
    """SSH ProxyCommand: strictly bound socket, 6-second/256KiB total budget."""
    import thunderbolt_discovery as D
    if (platform or sys.platform) != 'darwin':
        raise ValueError('Strict interface binding is supported on Darwin only')
    if not D.DEVICE.fullmatch(interface) or not D.private_ipv4(source) or not D.private_ipv4(target):
        raise ValueError('Invalid private link transport')
    index = socket.if_nametoindex(interface)
    with sock_factory(socket.AF_INET, socket.SOCK_STREAM) as sock:
        option = getattr(socket, 'IP_BOUND_IF', 25)  # Darwin netinet/in.h; never used on another OS.
        sock.setsockopt(socket.IPPROTO_IP, option, index)
        if sock.getsockopt(socket.IPPROTO_IP, option) != index:
            raise ValueError('Kernel did not confirm strict interface binding')
        sock.bind((source, 0)); sock.settimeout(2)
        start = time.monotonic(); sock.connect((target, 22))
        if sock.getsockname()[0] != source or sock.getpeername()[0] != target:
            raise ValueError('Bound endpoint mismatch')
        print(META + json.dumps({'source': source, 'target': target, 'interface': interface,
                                'bound_ifindex': index, 'tcp_connect_ms': (time.monotonic()-start)*1000}),
              file=sys.stderr, flush=True)
        deadline = start + 6; count = 0; inputs = [sock, 0]
        while inputs:
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError('Transport budget expired')
            ready, _, _ = select.select(inputs, [], [], remaining)
            if not ready: raise TimeoutError('Transport budget expired')
            for item in ready:
                data = sock.recv(16384) if item is sock else os.read(0, 16384)
                if not data:
                    if item is sock: return
                    inputs.remove(0); sock.shutdown(socket.SHUT_WR); continue
                count += len(data)
                if count > MAX_BYTES: raise ValueError('Transport byte budget exceeded')
                if item is sock:
                    # SSH reads continuously; its parent has an independent 8s deadline.
                    view = memoryview(data)
                    while view:
                        view = view[os.write(1, view):]
                else: sock.sendall(data)


def identity_for(node, inventory):
    """Existing configured SSH host is the host-key anchor, never a new TB key."""
    import thunderbolt_discovery as D
    import web_nodes
    target = str(node.get('ssh') or node.get('host') or '')
    if web_nodes.is_local(node):
        alias = str(inventory.get('hostname') or '')
        user = str(inventory.get('username') or getpass.getuser())
    else:
        if not D.TARGET.fullmatch(target): raise ValueError('Invalid configured SSH identity')
        if '@' in target: user, alias = target.split('@', 1)
        else: alias, user = target, str(inventory.get('username') or getpass.getuser())
    if not D.TARGET.fullmatch(alias) or '@' in alias or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user):
        raise ValueError('No usable existing SSH trust anchor')
    hostname = str(inventory.get('hostname') or '')
    if not hostname or len(hostname)>255: raise ValueError('Trusted hostname unavailable')
    return {'alias': alias, 'user': user, 'hostname': hostname}


def ssh_argv(interface, source, target, identity, nonce):
    import thunderbolt_discovery as D
    if not D.DEVICE.fullmatch(interface) or not D.private_ipv4(source) or not D.private_ipv4(target):
        raise ValueError('Invalid private link')
    if (not D.TARGET.fullmatch(identity['alias']) or '@' in identity['alias']
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', identity['user'])
            or not re.fullmatch(r'[a-f0-9]{32}', nonce)):
        raise ValueError('Invalid probe identity/nonce')
    broker = shlex.join([sys.executable, str(Path(__file__).resolve()), '--transport', interface, source, target]).replace('%', '%%')
    code = ('import json,os,socket;print(json.dumps({'
            + '"nonce":'+repr(nonce)+',"hostname":socket.gethostname(),'
            + '"connection":os.environ.get("SSH_CONNECTION","")}))')
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'UpdateHostKeys=no',
               'CheckHostIP=no', 'ControlMaster=no', 'ControlPath=none', 'ControlPersist=no',
               'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no', 'PermitLocalCommand=no',
               'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no', 'NumberOfPasswordPrompts=0',
               'ConnectionAttempts=1', 'ConnectTimeout=2', 'ServerAliveInterval=1', 'ServerAliveCountMax=1',
               'HostKeyAlias='+identity['alias'], 'ProxyCommand='+broker]
    argv = ['/usr/bin/ssh', '-F', '/dev/null', '-T']
    for option in options: argv += ['-o', option]
    return argv + ['-l', identity['user'], target, '/usr/bin/python3 -c '+shlex.quote(code)]


def local_probe(edge, identity, *, run=subprocess.run, collect=None, platform=None):
    import thunderbolt_discovery as D
    collect = collect or D.collect_local
    start = time.monotonic()
    out = {'status':'unverified', 'identity_verified':False, 'reachable':None, 'latency_ms':None,
           'checked_at':time.time(), 'method':'interface-bound TCP22 + strict SSH nonce hello',
           'latency_kind':'authenticated SSH hello wall time; not ping RTT or MLX throughput',
           'source_address':edge['source_address'], 'identity_alias':identity['alias'], 'port':22}
    if (platform or sys.platform) != 'darwin':
        return dict(out, reason='Strict interface binding unavailable; no unbound fallback')
    def check():
        data = collect([edge['address']])
        valid = any(i['interface']==edge['source_interface'] and edge['source_address'] in i['addresses']
                    for i in data['interfaces'])
        route = any(r['address']==edge['address'] and r['interface']==edge['source_interface'] for r in data['routes'])
        if not valid or not route: raise ValueError('Private Thunderbolt interface/source route changed; no fallback')
    try:
        check()
        nonce = secrets.token_hex(16)
        argv = ssh_argv(edge['source_interface'], edge['source_address'], edge['address'], identity, nonce)
        hello_start = time.monotonic()
        result = run(argv, capture_output=True, text=True, timeout=8)
        elapsed = (time.monotonic()-hello_start)*1000
        metadata = [line[len(META):] for line in result.stderr.splitlines() if line.startswith(META)]
        link = json.loads(metadata[-1]) if metadata else None
        if link:
            if (link.get('source')!=edge['source_address'] or link.get('target')!=edge['address']
                    or link.get('interface')!=edge['source_interface'] or not isinstance(link.get('bound_ifindex'),int)
                    or isinstance(link.get('bound_ifindex'),bool) or link['bound_ifindex']<=0
                    or not isinstance(link.get('tcp_connect_ms'),(int,float)) or not math.isfinite(link['tcp_connect_ms'])
                    or link['tcp_connect_ms']<0): raise ValueError('Bound transport evidence mismatch')
            out.update(reachable=True, transport_bound=True, bound_ifindex=link['bound_ifindex'], tcp_connect_ms=round(link['tcp_connect_ms'],3))
        check()  # Reject route/interface drift even after an authenticated response.
        if result.returncode:
            error = result.stderr.lower()
            if 'host key is known' in error or 'permission denied' in error:
                return dict(out, reason='Existing SSH trust or noninteractive login unavailable; no enrollment/fallback')
            return dict(out, status='failed', reachable=bool(link), reason='Bound SSH hello failed (link, host-key mismatch or deadline); no fallback')
        if not link: raise ValueError('Strict bound transport evidence missing')
        hello = json.loads(result.stdout)
        connection = str(hello.get('connection') or '').split()
        if (hello.get('nonce')!=nonce or hello.get('hostname')!=identity['hostname'] or len(connection)!=4
                or connection[0]!=edge['source_address'] or connection[2]!=edge['address'] or connection[3]!='22'):
            raise ValueError('Peer identity/nonce/link endpoint mismatch')
        out.update(status='verified', identity_verified=True, reachable=True, latency_ms=round(elapsed,3),
                   peer_hostname=hello['hostname'], reason='Existing host key + nonce + hostname + bound endpoints verified')
    except subprocess.TimeoutExpired:
        out.update(status='failed', reason='Bound probe deadline exceeded; no fallback')
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as e:
        out.update(status='failed', reason=str(e) if isinstance(e,ValueError) else 'Bound probe unavailable; no fallback')
    out['checked_at'] = time.time()
    out['elapsed_ms'] = round((time.monotonic()-start)*1000,3)
    return out


def probe_edge(source_node, edge, identity, *, run=subprocess.run):
    """Management SSH only executes the bound probe on its source Mini."""
    import thunderbolt_discovery as D
    import web_nodes
    if web_nodes.is_local(source_node): return local_probe(edge, identity, run=run)
    target = str(source_node.get('ssh') or source_node.get('host') or '')
    if not D.TARGET.fullmatch(target): raise ValueError('Invalid configured probe source')
    repo = str(source_node.get('repo') or '~/cv3')
    code = ('import sys,json;from pathlib import Path;'
            f'sys.path.insert(0,str(Path({repo!r}).expanduser()/"proxy"));'
            'from thunderbolt_probe import local_probe;'
            f'print(json.dumps(local_probe({edge!r},{identity!r})))')
    r = run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=3',
             target,'/usr/bin/python3 -c '+shlex.quote(code)],capture_output=True,text=True,timeout=42)
    if r.returncode: raise RuntimeError('Trusted source inspection unavailable; no fallback')
    result=json.loads(r.stdout)
    if not isinstance(result,dict) or result.get('status') not in ('verified','unverified','failed'):
        raise ValueError('Invalid trusted probe result')
    return result


if __name__ == '__main__':
    if len(sys.argv)!=5 or sys.argv[1]!='--transport': raise SystemExit(2)
    try: transport(*sys.argv[2:])
    except (OSError,ValueError,TimeoutError) as error:
        print('Strict TB transport failed: '+str(error),file=sys.stderr);raise SystemExit(2)
