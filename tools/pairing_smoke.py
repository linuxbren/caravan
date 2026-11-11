#!/usr/bin/env python3
"""Opt-in real-Mac pairing proof, confined to a fresh sibling scratch HOME.

Run helper on one Mac; pipe its offer command over existing SSH into the other
Mac's client command. Offers contain ephemeral test secrets: never tee/log them.
No model or production SSH/config files are read or changed by this harness.
"""
from __future__ import annotations
import argparse
from http.cookies import SimpleCookie
import getpass
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'proxy'),str(ROOT/'tools')]
import pairing as P
from pairing_store import Store,atomic,read_json
import web_pairing as W


def scratch(value):
    home=Path(value).resolve();real=Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    if home.parent!=real or not home.name.startswith('.caravan-pairing-smoke-'):
        raise ValueError('Choose a fresh .caravan-pairing-smoke-* sibling folder inside your home, never your actual HOME or .caravan.')
    if home.is_symlink():raise ValueError('Linked scratch folders are refused.')
    home.mkdir(mode=0o700,exist_ok=True);home.chmod(0o700)
    marker=home/'.pairing-smoke-owned'
    if not marker.exists():
        # A fresh easy-package install is also allowed, but not arbitrary data.
        unrelated=[p.name for p in home.iterdir() if p.name not in ('.caravan','Library')]
        if unrelated:raise ValueError('This is not an empty or easy-package scratch folder.')
        atomic(marker,'Caravan isolated pairing acceptance\n',backup=False)
    return home


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


class Control:
    def __init__(self,home,port):
        self.port=port;self.cookie='';self.token=''
        capability=read_json(home/'.caravan/pairing/control.json')['capability']
        self.call('/api/pairing/session',{'capability':capability})
        self.token=self.call('/api/pairing/state')['token']
    def call(self,path,body=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=90)
        headers={'Origin':f'http://127.0.0.1:{self.port}','Cookie':self.cookie,'X-Caravan-Pairing':self.token,'Content-Type':'application/json'}
        try:
            c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),headers)
            r=c.getresponse();raw=r.read();cookie=r.getheader('Set-Cookie')
            if cookie:self.cookie=cookie.split(';')[0]
            if r.status!=200:raise ValueError('Scratch UI request failed: '+raw.decode()[:400])
            return json.loads(raw)
        finally:c.close()


def ui(manager):
    app=SimpleNamespace(pairing=manager,_nodes_cache=None)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def handle_api(self):
            if not W.dispatch(self,app):W.respond(self,404,{'error':'Not found.'})
        do_GET=handle_api;do_POST=handle_api
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start();return server


def helper(home):
    if sys.platform!='darwin':raise ValueError('The live helper proof must run on macOS.')
    store=Store(home,repo=ROOT);store.identity();store.private_dir(home/'.ssh')
    host=store.root/'smoke-sshd-host'
    if not host.exists():subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(host)],check=True)
    ssh_port=free_port();sshd_config=store.root/'smoke-sshd.conf'
    atomic(sshd_config,'\n'.join([f'Port {ssh_port}','ListenAddress 0.0.0.0',f'HostKey "{host}"',
          f'PidFile "{store.root / "sshd.pid"}"',f'AuthorizedKeysFile "{home / ".ssh/authorized_keys"}"',
          'PasswordAuthentication no','KbdInteractiveAuthentication no','PubkeyAuthentication yes','UsePAM no',
          'StrictModes yes','GatewayPorts no','AllowTcpForwarding local','LogLevel ERROR'])+'\n',backup=False)
    log=(store.root/'smoke-sshd.log').open('a')
    sshd=subprocess.Popen(['/usr/sbin/sshd','-D','-e','-f',str(sshd_config)],stdout=log,stderr=log)
    manager=None;server=None;stop=threading.Event()
    try:
        deadline=time.time()+10
        while not P.remote_login(ssh_port):
            if sshd.poll() is not None:raise ValueError('Scratch sshd did not start. Review only its scratch log.')
            if time.time()>deadline:raise ValueError('Scratch sshd readiness timed out.')
            time.sleep(.1)
        manager=P.Pairing(store,port=0,ssh_port=ssh_port,host_key_path=host.with_suffix('.pub'),active=lambda:False).serve()
        P.prepare_offer(store,renew=True)
        server=ui(manager)
        local_name=subprocess.check_output(['/usr/sbin/scutil','--get','LocalHostName'],text=True).strip()+'.local'
        state={'home':str(home),'pid':os.getpid(),'id':manager.id,'host':local_name,'pair_port':manager.port,'ui_port':server.server_port,'ssh_port':ssh_port,
               'system_remote_login':P.remote_login(22),'code_available':bool(manager.local_state()['code'])}
        atomic(home/'smoke-public.json',json.dumps(state),backup=False)
        print(json.dumps(state),flush=True)
        signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
        stop.wait()
    finally:
        if server:server.shutdown();server.server_close()
        if manager:manager.close()
        sshd.terminate()
        try:sshd.wait(timeout=5)
        except subprocess.TimeoutExpired:sshd.kill();sshd.wait()
        log.close()


def offer(home):
    state=read_json(home/'smoke-public.json');control=Control(home,state['ui_port'])
    current=control.call('/api/pairing/state')
    if not current.get('code'):current=control.call('/api/pairing/code',{})
    assert current['code'] and current['remote_login']
    # This output goes ONLY to the client's stdin through an encrypted SSH pipe.
    print(json.dumps({**state,'code':current['code']}))


def client(home):
    supplied=json.load(sys.stdin)
    store=Store(home,repo=ROOT)
    manager=P.Pairing(store,port=0,active=lambda:False,baseline=lambda:[{'id':'local','host':'local','role':'lead','label':'My Mac','order':0}])
    server=ui(manager);control=Control(home,server.server_port)
    try:
        found=control.call('/api/pairing/discover',{})['nodes']
        peer=next((p for p in found if p['id']==supplied['id']),None)
        if not peer:raise ValueError('The scratch helper was not discovered by Bonjour; no direct-address substitute was used.')
        result=control.call('/api/pairing/add',{'id':peer['id'],'code':supplied['code']})
        row=store.record(peer['id']);incoming=P.request((peer['host'],peer['port']),'/v1/info')
        assert result['added'] and row['state']=='active' and not incoming['accepting']
        known=store.root/'known_hosts'/peer['id'];assert known.exists() and 'ssh-ed25519' in known.read_text()
        assert row['node_id'] in store.config.read_text()
        # A second real login proves the stored dedicated identity and pinned host.
        login=subprocess.run(['ssh','-F',row['ssh_config'],row['alias'],'printf CARAVAN_DEDICATED_KEY_OK'],capture_output=True,text=True,timeout=15)
        if login.returncode or login.stdout!='CARAVAN_DEDICATED_KEY_OK':raise ValueError('Dedicated-key proof failed; inspect the scratch configuration.')
        removed=control.call('/api/pairing/remove',{'id':peer['id']})
        assert removed['removed'] and not store.records() and not known.exists()
        assert row['node_id'] not in store.config.read_text()
        assert not Path(row['key_path']).exists() and not Path(row['ssh_config']).exists()
        print(json.dumps({'passed':True,'bonjour_discovered':True,'code_from_helper_page':True,'code_entered_through_lead_ui_api':True,
                          'dedicated_key_ssh':True,'host_key_pinned':True,'config_written':True,'remove_reversed_local_trust':True,
                          'system_remote_login':P.remote_login(22),'home':str(home)}),flush=True)
    finally:server.shutdown();server.server_close()


def verify_removed(home):
    store=Store(home,repo=ROOT);authorized=home/'.ssh/authorized_keys'
    assert not store.records()
    assert not authorized.exists() or '# caravan-pair:' not in authorized.read_text()
    print(json.dumps({'helper_keys_removed':True,'helper_records_removed':True,'production_paths_used':False}))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('helper','offer','client','verify-removed'));p.add_argument('--home',required=True)
    a=p.parse_args();home=scratch(a.home)
    {'helper':helper,'offer':offer,'client':client,'verify-removed':verify_removed}[a.action](home)


if __name__=='__main__':main()
