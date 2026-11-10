"""Read-only trusted-node Thunderbolt inventory and candidate graph.

Passive by default; explicit bounded validation never changes routes/models.
Only configured SSH identities with existing host keys are queried. Route
observations are candidates, NOT authenticated/usable model-data connections.
"""
from __future__ import annotations
import concurrent.futures
import copy
import getpass
import math
import uuid
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
    return {'hostname': socket.gethostname(), 'username':getpass.getuser(), 'interfaces': interfaces, 'routes': routes}


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
    return dict(hostname=str(data.get('hostname') or ''), username=str(data.get('username') or ''), interfaces=interfaces, routes=routes)


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
                        candidates = [a for i in source.get('interfaces',[]) if i['interface']==routes[address]
                                      for a in i['addresses'] if a not in ambiguous and private_ipv4(a)]
                        candidates.sort(key=lambda a:(ipaddress.ip_address(a).is_link_local != ipaddress.ip_address(address).is_link_local,a))
                        if not candidates: continue
                        edges.append({'source': source['id'], 'target': target['id'], 'address': address,
                                      'source_address':candidates[0],
                                      'source_interface': routes[address], 'target_interface': interface['interface'],
                                      'evidence': 'trusted inventory + source route', 'status': 'unverified',
                                      'reason':'Not actively validated', 'usable_for_routing': False})
    return {'node_ids': [n['id'] for n in nodes], 'edges': edges,
            'directed': True, 'automatic_routing': False, 'ambiguous_addresses': ambiguous,
            'warning': 'Unverified candidates until explicit validation. No route changes; model protocol/throughput and cable adjacency are not tested.'}


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
            return fresh_snapshot(dict(self.cached, cache_ttl_s=30))


    def validate(self, configured):
        """Explicit operation; single-flight and cached to bound repeated clicks."""
        key=json.dumps(configured,sort_keys=True)
        with self.lock:
            if (self.cached is not None and self.key==key and time.monotonic()<self.until
                    and self.cached.get('validation_id')):
                return fresh_snapshot(dict(self.cached,cache_ttl_s=30))
            self.cached=validate_graph(discover(configured),configured)
            self.key=key;self.until=time.monotonic()+30
            return fresh_snapshot(dict(self.cached,cache_ttl_s=30))

    def plan(self, configured, *, opt_in, validation_id):
        # No discovery, probes or writes here; only a fresh explicit validation.
        with self.lock:
            if (opt_in is not True or self.cached is None or self.key!=json.dumps(configured,sort_keys=True)
                    or time.monotonic()>=self.until or not validation_id
                    or validation_id!=self.cached.get('validation_id')):
                raise ValueError('Opt in and validate the current trusted graph first; stale/missing graph is rejected')
            return suggested_plan(configured,self.cached)


MAX_PROBES=64
VERIFIED_TTL=30


def fresh_snapshot(snapshot, *, now=None):
    out=copy.deepcopy(snapshot);now=time.time() if now is None else now
    edges=out.get('graph',{}).get('edges',[])
    for edge in edges:
        checked=edge.get('checked_at')
        if edge.get('status')=='verified' and (not isinstance(checked,(int,float)) or not 0<=now-checked<=VERIFIED_TTL):
            edge.update(status='unverified',reason='Validation expired or clock mismatch; validate again before preview',identity_verified=False)
    if 'graph' in out:
        out['graph']['validation_counts']={state:sum(e.get('status')==state for e in edges) for state in ('verified','unverified','failed')}
    return out


def validate_graph(snapshot, configured, *, probe=None):
    import thunderbolt_probe as P
    probe=probe or P.probe_edge
    out=copy.deepcopy(snapshot);nodes={n['id']:n for n in out['nodes']};config={n['id']:n for n in configured}
    def validate(pair):
        number,edge=pair
        result=dict(edge,status='unverified',usable_for_routing=False)
        if number>=MAX_PROBES:
            return dict(result,reason='Per-inspection probe budget exhausted; not guessed')
        try:
            identity=P.identity_for(config[edge['target']],nodes[edge['target']])
            observed=probe(config[edge['source']],edge,identity)
            if observed.get('status') not in ('verified','unverified','failed'):raise ValueError('Invalid validation status')
            if observed['status']=='verified':
                latency=observed.get('latency_ms')
                if (observed.get('identity_verified') is not True or observed.get('reachable') is not True
                        or observed.get('transport_bound') is not True or not isinstance(observed.get('bound_ifindex'),int)
                        or isinstance(observed.get('bound_ifindex'),bool) or observed['bound_ifindex']<=0
                        or observed.get('source_address')!=edge['source_address'] or not isinstance(latency,(int,float))
                        or isinstance(latency,bool) or not math.isfinite(latency) or latency<0):
                    raise ValueError('Incomplete authenticated link evidence')
            # Probe output may add evidence, never redefine graph endpoints.
            allowed=('status','reason','identity_verified','reachable','latency_ms','tcp_connect_ms','checked_at',
                     'method','latency_kind','identity_alias','port','peer_hostname','elapsed_ms','transport_bound','bound_ifindex')
            result.update({k:observed[k] for k in allowed if k in observed})
        except (OSError,ValueError,TypeError,KeyError,RuntimeError,subprocess.SubprocessError):
            result.update(status='unverified',reason='Trusted bound validation unavailable; no fallback')
        return result
    # Spend the bounded budget on existing-order pipeline requirements first,
    # not an arbitrary all-to-all prefix that could omit a successor edge.
    from split_balance import pipeline_order
    order=pipeline_order(configured)
    required=set()
    if order and order[-1].get('role')=='lead':
        for i,node in enumerate(order[:-1]):
            required.update(((order[-1]['id'],node['id']),(order[i+1]['id'],node['id'])))
    candidates=sorted(out['graph']['edges'],key=lambda e:((e['source'],e['target']) not in required,e['source'],e['target'],e['address']))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        out['graph']['edges']=list(pool.map(validate,enumerate(candidates)))
    out.update(validated_at=time.time(),validation_id=uuid.uuid4().hex,validation_ttl_s=VERIFIED_TTL)
    out['graph']['warning']='Verified means existing SSH host key, nonce, hostname and TCP22 over a kernel-bound private TB interface; not MLX health/throughput or direct cable adjacency. No routing changes.'
    out['scope']='Explicit bounded trusted-link validation only. No scans, enrollment, model/socket interruption or automatic routes.'
    return out


def endpoint(value):
    if not isinstance(value,str) or value.count(':')!=1:raise ValueError('Existing private IPv4 peer:port required; no guessed port')
    address,port=value.split(':')
    if not private_ipv4(address) or not port.isdigit() or not 1<=int(port)<=65535:
        raise ValueError('Existing private IPv4 peer:port required; no guessed port')
    return address,int(port)


def configured_endpoint(value, node, inventory):
    """Resolve only existing endpoint syntax against this trusted snapshot.

    Unlike the runtime resolver this performs no SSH/network operation. Dynamic
    tb:// and ssh+tb:// retain their configured interface and identity anchor.
    """
    import service_endpoints as SE
    spec=SE.parse(value)
    if spec is None:return endpoint(value)
    target,interface,port=spec
    if target and target!=(node.get('ssh') or node.get('host')):
        raise ValueError('Endpoint SSH identity differs from configured Mini; no fallback')
    matches=[i for i in inventory['interfaces'] if i['interface']==interface]
    if len(matches)!=1 or len(matches[0]['addresses'])!=1:
        raise ValueError('Configured TB interface needs one current private address')
    address=private_ipv4(matches[0]['addresses'][0])
    if not address:raise ValueError('Configured TB interface address is not private')
    return address,port


def suggested_plan(configured, snapshot, *, now=None):
    """Preserve configured order and ports. No alternate-network/order search.

    Existing runtime preflights every packer from the lead, so each selected
    peer must be verified from both lead and successor, using the SAME address.
    A topology requiring routed discovery/extra addresses is rejected, not guessed.
    """
    from split_balance import pipeline_order
    now=time.time() if now is None else now
    if (not snapshot.get('validation_id') or not isinstance(snapshot.get('validated_at'),(int,float))
            or not 0<=now-snapshot['validated_at']<=VERIFIED_TTL):
        raise ValueError('Validated graph expired or missing; no fallback')
    ids=[n['id'] for n in configured]
    if len(ids)<2 or len(set(ids))!=len(ids) or set(ids)!=set(snapshot['graph']['node_ids']):
        raise ValueError('Graph must cover the exact configured Minis')
    if len([n for n in configured if n.get('role')=='lead'])!=1 or any(n.get('role') not in ('lead','packer') for n in configured):
        raise ValueError('Exactly one configured lead and explicit packer roles required')
    if any(n.get('offline') or n.get('error') for n in snapshot['nodes']):
        raise ValueError('Every configured Mini needs current trusted inventory')
    inventory={n['id']:n for n in snapshot['nodes']}
    ordered=pipeline_order(configured);lead=ordered[-1];rows=[];used=[];same=True;previous=None
    edges=[e for e in snapshot['graph']['edges'] if e.get('status')=='verified'
           and e.get('identity_verified') is True and e.get('reachable') is True and e.get('transport_bound') is True
           and isinstance(e.get('bound_ifindex'),int) and not isinstance(e.get('bound_ifindex'),bool) and e['bound_ifindex']>0
           and isinstance(e.get('checked_at'),(int,float)) and 0<=now-e['checked_at']<=VERIFIED_TTL]
    for i,node in enumerate(ordered[:-1]):
        old_ip,port=configured_endpoint(node.get('peer'),node,inventory[node['id']])
        required={lead['id'],ordered[i+1]['id']}
        addresses=None
        for source in required:
            options={e['address'] for e in edges if e['source']==source and e['target']==node['id']}
            addresses=options if addresses is None else addresses & options
        if not addresses:raise ValueError('No fresh verified common TB peer address for '+node['id']+' from lead and successor; no fallback')
        if old_ip in addresses:chosen=old_ip
        elif len(addresses)==1:chosen=next(iter(addresses))
        else:raise ValueError('Ambiguous verified TB addresses for '+node['id']+'; no automatic selection')
        selected=[]
        for source in sorted(required):
            matches=[e for e in edges if e['source']==source and e['target']==node['id'] and e['address']==chosen]
            if len(matches)!=1:raise ValueError('Ambiguous directed link evidence; no automatic selection')
            selected.append(matches[0]);used.append(copy.deepcopy(matches[0]))
        interfaces={e['target_interface'] for e in selected}
        if len(interfaces)!=1:raise ValueError('Peer interface is ambiguous')
        peer=chosen+':'+str(port)
        row={'id':node['id'],'role':'packer','peer':peer,'listen':peer,'upstream_peer':previous,
             'interface':next(iter(interfaces))}
        old_listen=configured_endpoint(node.get('listen') or node.get('peer'),node,inventory[node['id']])
        same=same and (old_ip,port)==(chosen,port) and old_listen==(chosen,port)
        if node.get('upstream_peer'):
            if i==0:raise ValueError('First packer must not have an upstream peer')
            prior=ordered[i-1]
            upstream=configured_endpoint(node['upstream_peer'],prior,inventory[prior['id']])
            same=same and upstream==endpoint(previous)
        rows.append(row);previous=peer
    # Lead's peer is the effective last-packer connection, not a new HTTP bind.
    rows.append({'id':lead['id'],'role':'lead','peer':previous,'listen':None,'upstream_peer':None})
    return {'preview_only':True,'apply_supported':False,'automatic_routing':False,'fail_closed':True,
            'validation_id':snapshot['validation_id'],'expires_at':min(e['checked_at']+VERIFIED_TTL for e in used),
            'order':[n['id'] for n in ordered],'nodes':rows,'required_edges':used,
            'matches_current_config':bool(same),'matches_live':None,
            'warning':'Preview only. No apply endpoint. Preserve ports/order; no Wi-Fi/Tailscale fallback. SSH validation does not prove MLX ports or guarantee runtime interface pinning. Future apply needs explicit consent, fresh identity checks and strictly bound worker transports.'}
