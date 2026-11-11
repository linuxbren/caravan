"""Owned pairing files: atomic writes, backups, no replacement of unrelated SSH data."""
from __future__ import annotations
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time

LOCK = threading.RLock()
ID = re.compile(r'^[a-f0-9]{32}$')


def valid_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value): raise ValueError('Invalid Mac identity.')
    return value


def public_key(value):
    """Accept only a real Ed25519 OpenSSH public-key encoding, never key options."""
    if not isinstance(value, str) or len(value) > 256: raise ValueError('Invalid public key.')
    fields = value.strip().split()
    if len(fields) < 2 or fields[0] != 'ssh-ed25519': raise ValueError('Only Ed25519 public keys are accepted.')
    try: raw = base64.b64decode(fields[1], validate=True)
    except Exception: raise ValueError('Invalid public key.') from None
    if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20': raise ValueError('Invalid public key.')
    return 'ssh-ed25519 ' + fields[1]


def atomic(path, data, *, backup=True, mode=0o600):
    path = Path(path)
    if path.is_symlink(): raise ValueError(f'Refusing to replace a linked file: {path.name}. Existing files kept.')
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
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default


class Store:
    def __init__(self, home=None, repo=None, config=None):
        self.home = Path(home or Path.home()).resolve()
        self.root = self.home/'.caravan/pairing'
        self.repo = Path(repo or Path(__file__).resolve().parents[1]).absolute()
        self.config = Path(config or self.home/'.caravan/config.toml')

    def private_dir(self,path):
        path=Path(path)
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p==self.home or p.is_relative_to(self.home)):
            raise ValueError('A linked Caravan or SSH folder needs review. Existing files kept.')
        path.mkdir(parents=True,exist_ok=True);path.chmod(0o700)

    @contextlib.contextmanager
    def locked(self):
        import fcntl
        with LOCK:
            self.private_dir(self.root)
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
        if path.is_symlink() or path.with_suffix('.pub').is_symlink(): raise ValueError('Linked pairing key was kept for review.')
        if not path.exists():
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','caravan-pair-'+peer,'-f',str(path)], check=True, capture_output=True)
            path.chmod(0o600)
        return path, public_key(path.with_suffix('.pub').read_text())

    @staticmethod
    def marker(peer): return '# caravan-pair:' + valid_id(peer)

    def authorize(self, peer, key):
        key = public_key(key); marker = self.marker(peer)
        path = self.home/'.ssh/authorized_keys'
        if path.is_symlink(): raise ValueError('Linked authorized_keys needs a separate migration; nothing changed.')
        old = path.read_text() if path.exists() else ''
        lines = [line for line in old.splitlines(keepends=True) if not line.rstrip().endswith(marker)]
        # Per-pair identity; private-network sources only; no PTY/agent/X11/user rc,
        # both forwarding directions are limited to the model HTTP loopback port.
        networks = '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,100.64.0.0/10,::1,fe80::/10,fc00::/7'
        options = f'restrict,port-forwarding,permitopen="127.0.0.1:8194",permitlisten="127.0.0.1:8194",from="{networks}"'
        text = ''.join(lines)
        if text and not text.endswith('\n'): text += '\n'
        text += options + ' ' + key + ' ' + marker + '\n'
        self.private_dir(path.parent)
        atomic(path, text); return key

    def unauthorize(self, peer):
        path = self.home/'.ssh/authorized_keys'; marker = self.marker(peer)
        if not path.exists(): return
        if path.is_symlink(): raise ValueError('Linked authorized_keys was kept unchanged.')
        old = path.read_text()
        atomic(path, ''.join(line for line in old.splitlines(keepends=True) if not line.rstrip().endswith(marker)))

    def block(self, peer, content):
        return f'# BEGIN caravan-pair:{valid_id(peer)}\n{content.rstrip()}\n# END caravan-pair:{peer}\n'

    def replace_block(self, path, peer, content=None):
        path = Path(path)
        if path.is_symlink(): raise ValueError(f'Linked {path.name} was kept unchanged.')
        old = path.read_text() if path.exists() else ''
        pattern = re.compile(r'^# BEGIN caravan-pair:'+valid_id(peer)+r'\n.*?^# END caravan-pair:'+peer+r'\n?', re.M|re.S)
        matches = list(pattern.finditer(old))
        if len(matches) > 1: raise ValueError('Duplicate pairing blocks; files kept for review.')
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
            if not path.is_relative_to(self.home): raise ValueError('Pairing needs its config inside this account’s home folder. Use the developer guide for external configs.')
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p==self.home or p.is_relative_to(self.home)):
                raise ValueError('A linked pairing/config path needs review. Existing files kept.')
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
            if not path.is_relative_to(self.home) or path.is_symlink(): raise ValueError('Pairing recovery needs review; files kept.')
            current=path.read_bytes() if path.exists() else None
            old=None if row['old'] is None else base64.b64decode(row['old'])
            if current!=old and (current is None or hashlib.sha256(current).hexdigest()!=row['new_hash']):
                raise ValueError('A pairing file changed outside Caravan. Review its backup before trying again.')
        for row in reversed(rows):
            path=Path(row['path'])
            if row['old'] is None:
                if path.exists(): path.unlink()
            else: atomic(path,base64.b64decode(row['old']),backup=False)
        journal.unlink()

    def block_text(self,path,peer,content=None,*,prepend=False):
        path=Path(path)
        if path.is_symlink(): raise ValueError(f'Linked {path.name} was kept unchanged.')
        old=path.read_text() if path.exists() else ''
        pattern=re.compile(r'^# BEGIN caravan-pair:'+valid_id(peer)+r'\n.*?^# END caravan-pair:'+peer+r'\n?',re.M|re.S)
        if len(list(pattern.finditer(old)))>1: raise ValueError('Duplicate pairing blocks; files kept for review.')
        text=pattern.sub('',old)
        if content is not None:
            if prepend: text=self.block(peer,content)+text
            else: text+=(('\n' if text and not text.endswith('\n') else '')+self.block(peer,content))
        return text

    def enroll(self, peer, metadata, endpoint, key_path, *, baseline=()):
        try: import tomllib
        except ImportError: import tomli as tomllib
        valid_id(peer); alias='caravan-'+peer
        if not re.fullmatch(r'[A-Za-z0-9_.:%-]+',endpoint): raise ValueError('Invalid private endpoint.')
        user=metadata['user'];repo=metadata['repo']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',user): raise ValueError('Unsupported Mac account name.')
        if not isinstance(repo,str) or not repo.startswith('/') or any(x in repo for x in '\r\n\x00'): raise ValueError('Invalid source path.')
        key=public_key(metadata['host_key']);ssh_port=int(metadata.get('ssh_port',22))
        if not 1<=ssh_port<=65535: raise ValueError('Invalid SSH port.')
        raw=self.config.read_text() if self.config.exists() else ''
        cfg=tomllib.loads(raw) if raw else {};nodes=cfg.get('web',{}).get('nodes',{})
        if not nodes:
            initial=list(baseline) or [{'id':'local','label':'My Mac','host':'local','role':'lead','order':0}]
            for i,node in enumerate(initial):
                ident=node.get('id','existing'+str(i))
                if not re.fullmatch(r'[A-Za-z0-9_-]+',ident): raise ValueError('Existing inventory needs review; nothing guessed.')
                raw+='\n[web.nodes.'+ident+']\n'
                for name in ('label','host','role','ssh','repo','peer','listen','upstream','order'):
                    if node.get(name) is not None: raw+=name+' = '+json.dumps(node[name])+'\n'
            nodes=tomllib.loads(raw)['web']['nodes']
        ident='paired_'+peer
        order=max([int(n.get('order',0)) for n in nodes.values()]+[0])+1
        label=str(metadata.get('name') or 'Mac '+str(order+1))[:80]
        iface=metadata.get('tb_interface');data_host=metadata.get('data_host') or endpoint
        if not isinstance(data_host,str) or not re.fullmatch(r'[A-Za-z0-9_.:%-]+',data_host): raise ValueError('Invalid data endpoint.')
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
            if any(c in text for c in '\r\n\x00'): raise ValueError('Invalid SSH path.')
            return '"'+text.replace('\\','\\\\').replace('"','\\"')+'"'
        ssh='\n'.join([f'Host {alias}',f'    HostName {endpoint}',f'    Port {ssh_port}',f'    User {user}',
                       f'    IdentityFile {quote(key_path)}','    IdentitiesOnly yes','    IdentityAgent none',
                       f'    HostKeyAlias {alias}',f'    UserKnownHostsFile {quote(known)}','    GlobalKnownHostsFile /dev/null',
                       '    HostKeyAlgorithms ssh-ed25519','    StrictHostKeyChecking yes','    CheckHostIP no',
                       '    BatchMode yes','    PasswordAuthentication no','    KbdInteractiveAuthentication no',
                       '    ConnectTimeout 5','    ProxyCommand none','    ProxyJump none','    ForwardAgent no',
                       '    ForwardX11 no','    PermitLocalCommand no','Host *'])
        ssh_path=self.home/'.ssh/config'
        self.private_dir(ssh_path.parent)
        ssh_text=self.block_text(ssh_path,peer,ssh,prepend=True)
        self._transaction([(known,alias+' '+key+'\n'),(ssh_path,ssh_text),(self.config,config_text)])
        return {'node_id':ident,'alias':alias,'name':label,'order':order,'peer':data}

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
        paths=(self.root/'known_hosts'/peer,self.root/'keys'/peer,(self.root/'keys'/peer).with_suffix('.pub'))
        if any(path.is_symlink() for path in paths): raise ValueError('Linked pairing key was kept for review.')
        self._transaction(changes)
        for path in paths:
            if path.exists(): path.unlink()
        record=self.record_path(peer)
        if record.exists(): record.unlink()
