"""Owned pairing files: atomic writes, backups, no replacement of unrelated SSH data."""
from __future__ import annotations
import base64
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

LOCK = threading.RLock()
ID = re.compile(r'^[a-f0-9]{32}$')
PRIVATE_CIDRS=('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16','100.64.0.0/10','::1/128','fe80::/10','fc00::/7')
NETWORKS=tuple(ipaddress.ip_network(x) for x in PRIVATE_CIDRS)


def rpc_port():
    """Loopback port a GGUF split reaches on this Mac (proxy/gguf_split.RPC_PORT)."""
    try: port = int(os.environ.get('CARAVAN_GGUF_RPC_PORT', '50052'))
    except ValueError: port = 50052
    return port if 0 < port < 65536 else 50052


def key_options():
    # Per-pair identity; private-network sources only; no PTY/agent/X11/user rc.
    # The lead may open the model HTTP port and the GGUF rpc-server port on this
    # Mac's loopback (the split's SSH tunnel), and may listen only on the model
    # HTTP port. Nothing else is forwarded.
    networks = ','.join(PRIVATE_CIDRS)
    return (f'restrict,port-forwarding,permitopen="127.0.0.1:8194",permitopen="127.0.0.1:{rpc_port()}",'
            f'permitlisten="127.0.0.1:8194",from="{networks}"')


# Options written by earlier releases; refresh_authorizations upgrades only these.
LEGACY_OPTIONS = frozenset({
    'restrict,port-forwarding,permitopen="127.0.0.1:8194",permitlisten="127.0.0.1:8194",from="' + ','.join(PRIVATE_CIDRS) + '"',
})
OWNED_LINE = re.compile(r'^(?P<options>restrict,\S+) (?P<rest>ssh-ed25519 [A-Za-z0-9+/=]+ # caravan-pair:[a-f0-9]{32})\s*$')


def private(value):
    try:
        addr=ipaddress.ip_address(str(value).split('%')[0])
        if getattr(addr,'ipv4_mapped',None):addr=addr.ipv4_mapped
        return any(addr.version==net.version and addr in net for net in NETWORKS)
    except ValueError:return False


def valid_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value): raise ValueError(T("server.pairing_store.invalid_mac_identity"))
    return value


def public_key(value):
    """Accept only a real Ed25519 OpenSSH public-key encoding, never key options."""
    if not isinstance(value, str) or len(value) > 256: raise ValueError(T("server.pairing_store.invalid_public_key"))
    fields = value.strip().split()
    if len(fields) < 2 or fields[0] != 'ssh-ed25519': raise ValueError(T("server.pairing_store.only_ed25519_public_keys_are_accepted"))
    try: raw = base64.b64decode(fields[1], validate=True)
    except Exception: raise ValueError(T("server.pairing_store.invalid_public_key")) from None
    if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20': raise ValueError(T("server.pairing_store.invalid_public_key"))
    return 'ssh-ed25519 ' + fields[1]


def atomic(path, data, *, backup=True, mode=0o600):
    path = Path(path)
    if path.is_symlink(): raise ValueError(T("server.pairing_store.refusing_to_replace_a_linked_file", name=path.name))
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_bytes() if path.exists() else None
    data = data.encode() if isinstance(data, str) else data
    if old == data: return
    if backup and old is not None:
        atomic(path.with_name(path.name + '.bak-' + secrets.token_hex(6)), old, backup=False, mode=mode)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def read_json(path, default=None):
    if Path(path).is_symlink(): raise ValueError(T("server.pairing_store.linked_pairing_state_was_kept_unchanged"))
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default


class Store:
    def __init__(self, home=None, repo=None, config=None):
        self.home = Path(home or Path.home()).resolve()
        self.root = self.home/'.caravan/pairing'
        self.repo = Path(repo or Path(__file__).resolve().parents[1]).absolute()
        self.config = Path(config or self.home/'.caravan/config.toml').absolute()
        # macOS /tmp and /var are system aliases. Canonicalize the parent only,
        # retaining the leaf so a linked config itself is still refused.
        if not self.config.is_relative_to(self.home):
            self.config=self.config.parent.resolve()/self.config.name

    def private_dir(self,path):
        path=Path(path)
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p==self.home or p.is_relative_to(self.home)):
            raise ValueError(T("server.pairing_store.a_linked_caravan_or_ssh_folder"))
        path.mkdir(parents=True,exist_ok=True);path.chmod(0o700)

    @contextlib.contextmanager
    def locked(self):
        import fcntl
        with LOCK:
            self.private_dir(self.root)
            if (self.root/'lock').is_symlink(): raise ValueError(T("server.pairing_store.linked_pairing_lock_was_kept_unchanged"))
            with (self.root/'lock').open('a') as file:
                os.chmod(file.name, 0o600); fcntl.flock(file, fcntl.LOCK_EX)
                try:
                    self.recover()
                    yield
                finally: fcntl.flock(file, fcntl.LOCK_UN)

    def identity(self):
        with self.locked():
            path = self.root/'identity.json'
            value = read_json(path)
            if value is None:
                value = {'id': secrets.token_hex(16)}; atomic(path, json.dumps(value), backup=False)
            valid_id(value['id']); return value['id']

    def record_path(self, peer): return self.root/'peers'/(valid_id(peer)+'.json')
    def records(self):
        return [read_json(p) for p in (self.root/'peers').glob('*.json')]
    def record(self, peer): return read_json(self.record_path(peer))
    def save(self, peer, record): atomic(self.record_path(peer), json.dumps(record, sort_keys=True), backup=False)

    def make_key(self, peer):
        path = self.root/'keys'/valid_id(peer)
        self.private_dir(path.parent)
        if path.is_symlink() or path.with_suffix('.pub').is_symlink(): raise ValueError(T("server.pairing_store.linked_pairing_key_was_kept_for"))
        if not path.exists():
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','caravan-pair-'+peer,'-f',str(path)], check=True, capture_output=True)
            path.chmod(0o600)
        if not path.with_suffix('.pub').exists():
            derived=subprocess.run(['ssh-keygen','-y','-f',str(path)],check=True,capture_output=True,text=True)
            atomic(path.with_suffix('.pub'),public_key(derived.stdout)+'\n',backup=False)
        return path, public_key(path.with_suffix('.pub').read_text())

    @staticmethod
    def marker(peer): return '# caravan-pair:' + valid_id(peer)

    def authorize(self, peer, key):
        key = public_key(key); marker = self.marker(peer)
        path = self.home/'.ssh/authorized_keys'
        if path.is_symlink(): raise ValueError(T("server.pairing_store.linked_authorized_keys_needs_a_separate"))
        old = path.read_text() if path.exists() else ''
        lines = [line for line in old.splitlines(keepends=True) if not line.rstrip().endswith(marker)]
        text = ''.join(lines)
        if text and not text.endswith('\n'): text += '\n'
        text += key_options() + ' ' + key + ' ' + marker + '\n'
        self.private_dir(path.parent)
        atomic(path, text); return key

    def refresh_authorizations(self):
        """Bring this Mac's own pairing keys up to the current options.

        Pairs made before Day 28 allowed only the model HTTP port, so a GGUF
        split could not reach this Mac's rpc-server tunnel. Only lines that end
        with a Caravan pairing marker and carry Caravan's own older options are
        rewritten; the key and marker are kept, every other line is untouched.
        Returns the number of lines changed."""
        path = self.home/'.ssh/authorized_keys'
        if not path.exists() or path.is_symlink(): return 0
        old = path.read_text(); want = key_options(); changed = 0; out = []
        for line in old.splitlines(keepends=True):
            m = OWNED_LINE.match(line.rstrip('\n'))
            if m and m.group('options') != want and m.group('options') in LEGACY_OPTIONS:
                line = want + ' ' + m.group('rest') + '\n'; changed += 1
            out.append(line)
        if changed: atomic(path, ''.join(out))
        return changed

    def unauthorize(self, peer):
        path = self.home/'.ssh/authorized_keys'; marker = self.marker(peer)
        if not path.exists(): return
        if path.is_symlink(): raise ValueError(T("server.pairing_store.linked_authorized_keys_was_kept_unchanged"))
        old = path.read_text()
        atomic(path, ''.join(line for line in old.splitlines(keepends=True) if not line.rstrip().endswith(marker)))

    def block(self, peer, content):
        return f'# BEGIN caravan-pair:{valid_id(peer)}\n{content.rstrip()}\n# END caravan-pair:{peer}\n'

    def replace_block(self, path, peer, content=None):
        path = Path(path)
        if path.is_symlink(): raise ValueError(T("server.pairing_store.linked_name_was_kept_unchanged", name=path.name))
        old = path.read_text() if path.exists() else ''
        pattern = re.compile(r'^# BEGIN caravan-pair:'+valid_id(peer)+r'\n.*?^# END caravan-pair:'+peer+r'\n?', re.M|re.S)
        matches = list(pattern.finditer(old))
        if len(matches) > 1: raise ValueError(T("server.pairing_store.duplicate_pairing_blocks_files_kept_for"))
        new = pattern.sub('', old)
        if content is not None:
            if new and not new.endswith('\n'): new += '\n'
            new += self.block(peer, content)
        atomic(path, new)

    def _transaction(self, changes):
        """Recoverable multi-file edit. Individual files are atomic and backed up."""
        rows=[]
        for path,data in changes:
            path=Path(path)
            if not path.is_relative_to(self.home): raise ValueError(T("server.pairing_store.pairing_needs_its_config_inside_this"))
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p==self.home or p.is_relative_to(self.home)):
                raise ValueError(T("server.pairing_store.a_linked_pairing_config_path_needs"))
            old=path.read_bytes() if path.exists() else None
            encoded=data.encode() if isinstance(data,str) else data
            rows.append({'path':str(path),'old':None if old is None else base64.b64encode(old).decode(),
                         'new_hash':hashlib.sha256(encoded).hexdigest()})
        journal=self.root/'transaction.json'
        atomic(journal,json.dumps(rows),backup=False)
        try:
            for path,data in changes: atomic(path,data)
        except BaseException:
            self.recover()
            raise
        journal.unlink()

    def recover(self):
        journal=self.root/'transaction.json'; rows=read_json(journal)
        if rows is None: return
        for row in rows:
            path=Path(row['path'])
            if not path.is_relative_to(self.home) or path.is_symlink(): raise ValueError(T("server.pairing_store.pairing_recovery_needs_review_files_kept"))
            current=path.read_bytes() if path.exists() else None
            old=None if row['old'] is None else base64.b64decode(row['old'])
            if current!=old and (current is None or hashlib.sha256(current).hexdigest()!=row['new_hash']):
                raise ValueError(T("server.pairing_store.a_pairing_file_changed_outside_caravan"))
        for row in reversed(rows):
            path=Path(row['path'])
            if row['old'] is None:
                if path.exists(): path.unlink()
            else: atomic(path,base64.b64decode(row['old']),backup=False)
        journal.unlink()

    def block_text(self,path,peer,content=None,*,prepend=False):
        path=Path(path)
        if path.is_symlink(): raise ValueError(T("server.pairing_store.linked_name_was_kept_unchanged", name=path.name))
        old=path.read_text() if path.exists() else ''
        pattern=re.compile(r'^# BEGIN caravan-pair:'+valid_id(peer)+r'\n.*?^# END caravan-pair:'+peer+r'\n?',re.M|re.S)
        if len(list(pattern.finditer(old)))>1: raise ValueError(T("server.pairing_store.duplicate_pairing_blocks_files_kept_for"))
        text=pattern.sub('',old)
        if content is not None:
            if prepend: text=self.block(peer,content)+text
            else: text+=(('\n' if text and not text.endswith('\n') else '')+self.block(peer,content))
        return text

    def enroll(self, peer, metadata, endpoint, key_path, *, baseline=()):
        try: import tomllib
        except ImportError: import tomli as tomllib
        valid_id(peer); alias='caravan-'+peer
        if not re.fullmatch(r'[A-Za-z0-9_.:%-]+',endpoint): raise ValueError(T("server.pairing_store.invalid_private_endpoint"))
        if not private(endpoint) and not endpoint.endswith('.local'): raise ValueError(T("server.pairing_store.use_a_private_address_or_the"))
        user=metadata['user'];repo=metadata['repo']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',user): raise ValueError(T("server.pairing_store.unsupported_mac_account_name"))
        if not isinstance(repo,str) or not repo.startswith('/') or any(x in repo for x in '\r\n\x00'): raise ValueError(T("server.pairing_store.invalid_source_path"))
        key=public_key(metadata['host_key']);ssh_port=int(metadata.get('ssh_port',22))
        if not 1<=ssh_port<=65535: raise ValueError(T("server.pairing_store.invalid_ssh_port"))
        raw=self.config.read_text() if self.config.exists() else ''
        cfg=tomllib.loads(raw) if raw else {};nodes=cfg.get('web',{}).get('nodes',{})
        if not nodes:
            initial=list(baseline) or [{'id':'local','label':T("server.pairing_store.my_mac"),'host':'local','role':'lead','order':0}]
            for i,node in enumerate(initial):
                ident=node.get('id','existing'+str(i))
                if not re.fullmatch(r'[A-Za-z0-9_-]+',ident): raise ValueError(T("server.pairing_store.existing_inventory_needs_review_nothing_guessed"))
                raw+='\n[web.nodes.'+ident+']\n'
                for name in ('label','host','role','ssh','repo','peer','listen','upstream','order'):
                    if node.get(name) is not None: raw+=name+' = '+json.dumps(node[name])+'\n'
            nodes=tomllib.loads(raw)['web']['nodes']
        ident='paired_'+peer
        order=max([int(n.get('order',0)) for n in nodes.values()]+[0])+1
        label=str(metadata.get('name') or T("server.pairing_store.mac_v", v=str(order+1)))[:80]
        iface=metadata.get('tb_interface');data_host=metadata.get('data_host') or endpoint
        if not isinstance(data_host,str) or not private(data_host): raise ValueError(T("server.pairing_store.the_model_connection_must_stay_on"))
        if iface and isinstance(iface,str) and re.fullmatch(r'en\d+',iface):
            data='ssh+tb://'+alias+'/'+iface+':5560';listen='tb://'+iface+':5560'
        else:
            data=('['+data_host+']' if ':' in data_host else data_host)+':5560';listen=data
        node=dict(label=label,role='packer',host=alias,ssh=alias,repo=repo,peer=data,listen=listen,order=order)
        content='[web.nodes.'+ident+']\n'+'\n'.join(k+' = '+json.dumps(v) for k,v in node.items())
        config_text=raw+('\n' if raw and not raw.endswith('\n') else '')+self.block(peer,content)
        tomllib.loads(config_text)  # validate everything BEFORE any trust/config edit
        known=self.root/'known_hosts'/peer
        def quote(path):
            text=str(path)
            if any(c in text for c in '\r\n\x00'): raise ValueError(T("server.pairing_store.invalid_ssh_path"))
            return '"'+text.replace('\\','\\\\').replace('"','\\"')+'"'
        ssh='\n'.join([f'Host {alias}',f'    HostName {endpoint}','    AddressFamily inet',f'    Port {ssh_port}',f'    User {user}',
                       f'    IdentityFile {quote(key_path)}','    IdentitiesOnly yes','    IdentityAgent none',
                       f'    HostKeyAlias {alias}',f'    UserKnownHostsFile {quote(known)}','    GlobalKnownHostsFile /dev/null',
                       '    HostKeyAlgorithms ssh-ed25519','    StrictHostKeyChecking yes','    CheckHostIP no',
                       '    BatchMode yes','    PasswordAuthentication no','    KbdInteractiveAuthentication no',
                       '    ConnectTimeout 5','    ProxyCommand none','    ProxyJump none','    ForwardAgent no',
                       '    ForwardX11 no','    PermitLocalCommand no','Host *'])
        ssh_path=self.home/'.ssh/config'
        self.private_dir(ssh_path.parent)
        ssh_text=self.block_text(ssh_path,peer,ssh,prepend=True)
        isolated_ssh=self.root/'ssh'/peer
        self._transaction([(known,alias+' '+key+'\n'),(isolated_ssh,ssh+'\n'),(ssh_path,ssh_text),(self.config,config_text)])
        return {'ssh_config':str(isolated_ssh),'node_id':ident,'alias':alias,'name':label,'order':order,'peer':data}

    def forget_local(self, peer):
        valid_id(peer)
        changes=[]
        for path in (self.config,self.home/'.ssh/config'):
            if path.exists(): changes.append((path,self.block_text(path,peer)))
        # Validate before removing trust; a hand-edited TOML mistake should not be
        # silently turned into an unrecoverable partially removed node.
        try: import tomllib
        except ImportError: import tomli as tomllib
        for path,text in changes:
            if path==self.config: tomllib.loads(text)
        paths=(self.root/'known_hosts'/peer,self.root/'ssh'/peer,self.root/'keys'/peer,(self.root/'keys'/peer).with_suffix('.pub'))
        if any(path.is_symlink() for path in paths): raise ValueError(T("server.pairing_store.linked_pairing_key_was_kept_for"))
        self._transaction(changes)
        for path in paths:
            if path.exists(): path.unlink()
        record=self.record_path(peer)
        if record.exists(): record.unlink()
