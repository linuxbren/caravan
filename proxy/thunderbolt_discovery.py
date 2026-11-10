"""Read-only trusted-node Thunderbolt inventory and candidate graph.

No probes, peer enrollment, route changes, model controls or data-plane claims.
Only configured SSH identities with existing host keys are queried. Route
observations are candidates, NOT authenticated/usable model-data connections.
"""
from __future__ import annotations
import concurrent.futures
import ipaddress
import json
import re
import shlex
import socket
import subprocess
import threading
import time

TARGET = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
DEVICE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}\Z")
NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16'))


def private_ipv4(value):
    try:
        ip = ipaddress.IPv4Address(value)
        return str(ip) if any(ip in n for n in NETWORKS) and not (ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_reserved) else None
    except (ValueError, TypeError):
        return None


def parse_interfaces(ports, config):
    """Physical TB ports plus bridges proven to contain only TB members."""
    devices = set()
    name = None
    for line in ports.splitlines():
        if line.startswith('Hardware Port: '):
            name = line.split(': ', 1)[1].strip()
        elif line.startswith('Device: ') and name:
            dev = line.split(': ', 1)[1].strip()
            if re.fullmatch(r'Thunderbolt \d+', name, re.I) and DEVICE.fullmatch(dev):
                devices.add(dev)
            name = None
    blocks = {}
    for block in re.split(r'(?=^[A-Za-z][A-Za-z0-9_]*: flags=)', config, flags=re.M):
        first = re.match(r'([A-Za-z][A-Za-z0-9_]*): flags=', block)
        if first:
            blocks[first[1]] = block
    out = []
    for dev, block in blocks.items():
        members = re.findall(r'\bmember: ([A-Za-z][A-Za-z0-9_]*)', block)
        bridge = bool(members) and set(members).issubset(devices)
        if dev not in devices and not bridge:
            continue
        if 'status: active' not in block:
            continue
        addresses = sorted(set(filter(None, (private_ipv4(v) for v in re.findall(r'\binet (\d+\.\d+\.\d+\.\d+)', block)))))
        # Scoped IPv6 and mixed/unknown bridges intentionally not accepted yet.
        if addresses:
            out.append({'interface': dev, 'kind': 'tb-only-bridge' if bridge else 'thunderbolt',
                        'members': members if bridge else [], 'addresses': addresses})
    return sorted(out, key=lambda x: x['interface'])


def collect_local(destinations=(), *, run=subprocess.run):
    """Inspect local interfaces/routes; no network sockets or config writes."""
    def read(argv):
        r = run(argv, capture_output=True, text=True, timeout=5)
        if r.returncode:
            raise RuntimeError('System interface/route inspection failed')
        return r.stdout
    ports = read(['/usr/sbin/networksetup', '-listallhardwareports'])
    config = read(['/sbin/ifconfig', '-a'])
    interfaces = parse_interfaces(ports, config)
    routes = []
    for address in sorted(set(filter(None, (private_ipv4(v) for v in destinations)))):
        try:
            text = read(['/sbin/route', '-n', 'get', address])
            found = re.search(r'^\s*interface:\s*(\S+)', text, re.M)
            routes.append({'address': address, 'interface': found[1] if found and DEVICE.fullmatch(found[1]) else None})
        except (OSError, subprocess.SubprocessError, RuntimeError):
            routes.append({'address': address, 'interface': None})
    return {'hostname': socket.gethostname(), 'interfaces': interfaces, 'routes': routes}


def normalized_inventory(data):
    if not isinstance(data, dict) or not isinstance(data.get('interfaces'), list) or not isinstance(data.get('routes'), list):
        raise ValueError('Invalid trusted-node inventory')
    interfaces = []
    for entry in data['interfaces']:
        if (not isinstance(entry, dict) or not DEVICE.fullmatch(str(entry.get('interface') or ''))
                or entry.get('kind') not in ('thunderbolt', 'tb-only-bridge')
                or not isinstance(entry.get('addresses'), list)):
            raise ValueError('Invalid interface inventory')
        addresses = sorted(set(filter(None, (private_ipv4(v) for v in entry['addresses']))))
        if addresses:
            interfaces.append(dict(interface=entry['interface'], kind=entry['kind'],
                                   members=entry.get('members') or [], addresses=addresses))
    routes = []
    for route in data['routes']:
        if not isinstance(route, dict):
            raise ValueError('Invalid route inventory')
        address = private_ipv4(route.get('address'))
        interface = route.get('interface')
        if address:
            routes.append(dict(address=address, interface=interface if isinstance(interface, str) and DEVICE.fullmatch(interface) else None))
    return dict(hostname=str(data.get('hostname') or ''), interfaces=interfaces, routes=routes)


def inspect_node(node, destinations=(), *, run=subprocess.run):
    """No request-supplied hosts: node is a server-configured trust entry."""
    import web_nodes
    if web_nodes.is_local(node):
        return collect_local(destinations, run=run)
    target = str(node.get('ssh') or node.get('host') or '')
    if not TARGET.fullmatch(target):
        raise ValueError('Configured SSH target is invalid')
    repo = str(node.get('repo') or '~/cv3')
    # JSON-encoded data is passed as Python literals, then shell-quoted once.
    code = ('import sys,json;from pathlib import Path;'
            f'sys.path.insert(0,str(Path({repo!r}).expanduser()/"proxy"));'
            'from thunderbolt_discovery import collect_local;'
            f'print(json.dumps(collect_local({list(destinations)!r})))')
    command = '/usr/bin/python3 -c ' + shlex.quote(code)
    result = run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                  '-o', 'ConnectTimeout=5', target, command],
                 capture_output=True, text=True, timeout=max(15, 12 + len(destinations)*5))
    if result.returncode:
        raise RuntimeError('Trusted SSH inspection failed; no trust/address fallback')
    return normalized_inventory(json.loads(result.stdout))


def candidate_graph(nodes):
    """N-node directed route observations; never mark an edge load-ready."""
    edges = []
    owners = {}
    for node in nodes:
        for interface in node.get('interfaces', []):
            for address in interface.get('addresses', []):
                owners.setdefault(address, set()).add(node['id'])
    ambiguous = sorted(a for a, ids in owners.items() if len(ids) > 1)
    for source in nodes:
        interfaces = {i['interface'] for i in source.get('interfaces', [])}
        routes = {r.get('address'): r.get('interface') for r in source.get('routes', [])}
        for target in nodes:
            if source['id'] == target['id']:
                continue
            for interface in target.get('interfaces', []):
                for address in interface.get('addresses', []):
                    if private_ipv4(address) and address not in ambiguous and routes.get(address) in interfaces:
                        edges.append({'source': source['id'], 'target': target['id'], 'address': address,
                                      'source_interface': routes[address], 'target_interface': interface['interface'],
                                      'evidence': 'trusted inventory + source route', 'status': 'candidate',
                                      'usable_for_routing': False})
    return {'node_ids': [n['id'] for n in nodes], 'edges': edges,
            'directed': True, 'automatic_routing': False, 'ambiguous_addresses': ambiguous,
            'warning': 'Candidate routes only. Data-service identity/reachability and adjacency are not verified.'}


def discover(configured, *, inspect=inspect_node):
    """Two bounded-concurrency read-only passes: inventory, then source routes."""
    ids = [str(n.get('id') or '') for n in configured]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', nid) for nid in ids):
        raise ValueError('Configured Mini IDs must be unique and valid')
    def parallel(fn):
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, max(1, len(configured)))) as pool:
            return list(pool.map(fn, configured))
    def inventory(node):
        out = {'id': node['id'], 'label': node.get('label') or node['id'], 'interfaces': [], 'routes': []}
        try:
            out.update(inspect(node, [])); out['offline'] = False
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError, KeyError):
            out.update(offline=True, error='Trusted inventory unavailable; no fallback')
        # The remote output cannot redefine a configured identity.
        out.update(id=node['id'], label=node.get('label') or node['id'])
        return out
    snapshots = parallel(inventory)
    by_id = {n['id']: n for n in snapshots}
    def routes(node):
        out = by_id[node['id']]
        if out['offline']:
            return out
        addresses = [a for n in snapshots if n['id'] != node['id'] for i in n['interfaces'] for a in i['addresses'] if private_ipv4(a)]
        try:
            observed = inspect(node, addresses)
            # Use the second fresh interface snapshot too; links may change between passes.
            out.update(interfaces=observed['interfaces'], routes=observed['routes'])
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError, KeyError):
            out.update(routes=[], error='Source route inspection unavailable')
        return out
    snapshots = parallel(routes)
    return {'observed_at': time.time(), 'read_only': True, 'nodes': snapshots, 'graph': candidate_graph(snapshots),
            'scope': 'Configured trusted Minis only; no scanning, probes, route changes or automatic loads.'}


class Controller:
    """30-second cache and single inspection at a time; not a polling service."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = None
        self.key = None
        self.until = 0

    def snapshot(self, configured):
        key = json.dumps(configured, sort_keys=True)
        with self.lock:
            if self.cached is None or self.key != key or time.monotonic() >= self.until:
                self.cached = discover(configured)
                self.key = key
                self.until = time.monotonic() + 30
            return dict(self.cached, cache_ttl_s=30)
