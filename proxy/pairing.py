"""Local-network, one-time PAKE pairing. No passwords or keys enter request logs.

SPAKE2 provides password-authenticated key exchange; AES-GCM confirms the key
and encrypts enrollment/revocation data. Discovery is never a trust decision.
"""
from __future__ import annotations
import base64
from concurrent.futures import ThreadPoolExecutor
import getpass
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

from pairing_store import Store, atomic, read_json, valid_id, public_key, NETWORKS, private
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PORT = 8197
TTL = 300
MAX_ATTEMPTS = 5
MAX_BODY = 16384
SETTINGS_URL = 'x-apple.systempreferences:com.apple.preferences.sharing?Services_RemoteLogin'


def addresses(host):
    if not isinstance(host,str) or not host or len(host)>253 or any(c in host for c in '/\\@\r\n\x00'): raise ValueError(T("server.pairing.invalid_mac_address"))
    rows = socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(row[4][0] for row in rows))
    # Ignore public DNS results; connect only to validated literals, never a
    # second DNS lookup. Dual-stack home Macs may also advertise global IPv6.
    ips=[ip for ip in ips if private(ip)]
    if not ips: raise ValueError(T("server.pairing.pairing_is_limited_to_your_local"))
    return sorted(ips,key=lambda ip:(0 if ipaddress.ip_address(ip.split("%")[0]).version==4 else 1,ip))



def request(endpoint, path, body=None, *, timeout=5):
    host,port = endpoint
    ips=addresses(host)[:16]
    data=None if body is None else json.dumps(body).encode()
    last=None
    for ip in ips:
        conn=http.client.HTTPConnection(ip,int(port),timeout=timeout)
        try:
            conn.request('GET' if body is None else 'POST',path,body=data,headers={'Content-Type':'application/json','Connection':'close'})
            result=conn.getresponse();raw=result.read(MAX_BODY+1)
            if len(raw)>MAX_BODY:raise ValueError(T("server.pairing.pairing_reply_was_too_large"))
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError(T("server.pairing.invalid_pairing_reply"))
            if result.status!=200:raise ValueError(value.get('error',T("server.pairing.other_mac_could_not_finish")))
            return value
        except (OSError,http.client.HTTPException) as error:last=error
        finally:conn.close()
    raise OSError(T("server.pairing.that_mac_is_not_reachable_at")) from last


def b64(value): return base64.b64encode(value).decode('ascii')
def un64(value, maximum=8192):
    if not isinstance(value,str) or len(value)>maximum*2: raise ValueError(T("server.pairing.invalid_pairing_message"))
    try: result=base64.b64decode(value,validate=True)
    except Exception: raise ValueError(T("server.pairing.invalid_pairing_message")) from None
    if len(result)>maximum: raise ValueError(T("server.pairing.invalid_pairing_message"))
    return result


def seal(key, value, context):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce=secrets.token_bytes(12)
    return b64(nonce+AESGCM(key).encrypt(nonce,json.dumps(value,sort_keys=True).encode(),context.encode()))


def unseal(key, value, context):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw=un64(value)
    try: return json.loads(AESGCM(key).decrypt(raw[:12],raw[12:],context.encode()))
    except Exception: raise ValueError(T("server.pairing.the_code_did_not_match_or")) from None


def prepare_offer(store, *, now=None, renew=False):
    now=time.time() if now is None else now
    with store.locked():
        path=store.root/'offer.json'; value=read_json(path)
        if renew or value is None or value.get('expires',0)<=now:
            value={'id':secrets.token_hex(16),'code':f'{secrets.randbelow(100000000):08d}',
                   'expires':now+TTL,'attempts':0,'used':False}
            atomic(path,json.dumps(value),backup=False)
        return value


def display_code(offer):
    code=offer['code']; return code[:4]+'-'+code[4:]


def remote_login(port=22):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.5): return True
    except OSError: return False


def host_key(path=None):
    path=Path(path or '/etc/ssh/ssh_host_ed25519_key.pub')
    try: return public_key(path.read_text())
    except (OSError,ValueError): raise ValueError(T("server.pairing.turn_on_remote_login_on_this")) from None


def stale_adverts(name, port, ps_output, uid=None):
    """PIDs of this Mac's own leftover advertisers: `dns-sd -R <name>
    _caravan._tcp local <port>` owned by this user whose parent is gone
    (parent pid 1). Other names (another identity) are never matched."""
    uid = os.getuid() if uid is None else uid
    want = ['-R', str(name), '_caravan._tcp', 'local', str(port)]
    out = []
    for line in str(ps_output or '').splitlines():
        parts = line.split()
        if len(parts) < 4: continue
        try: pid, ppid, owner = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError: continue
        cmd = parts[3:]
        if ppid != 1 or owner != uid or pid == os.getpid(): continue
        if os.path.basename(cmd[0]) == 'dns-sd' and cmd[1:] == want:
            out.append(pid)
    return out


def stop_stale_adverts(name, port, *, run=subprocess.run, kill=os.kill):
    """Stop our own leftover dns-sd advertisers (see stale_adverts)."""
    import signal
    try:
        ps = run(['ps', '-axo', 'pid=,ppid=,uid=,command='], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    pids = stale_adverts(name, port, ps)
    for pid in pids:
        try: kill(pid, signal.SIGTERM)
        except OSError: pass
    return pids



def record_route(alias,label=None):
    """Link-order fix: right after pairing, check which link reaches the new
    Mac (Thunderbolt > wired > Wi-Fi > other) so Topology shows it. Best effort."""
    if not alias:return
    try:
        import threading,peer_route as PR
        threading.Thread(target=PR.route_for,args=(alias,),kwargs={'fresh':True,'label':label},daemon=True).start()
    except Exception:  # noqa: BLE001 - display only; loads re-check anyway
        pass

class Pairing:
    def __init__(self,store=None,*,port=PORT,ssh_port=22,host_key_path=None,clock=time.time,
                 active=lambda:False,baseline=lambda:(),metadata=None,verify_ssh=True):
        self.store=store or Store(); self.port=port;self.ssh_port=ssh_port
        self.host_key_path=host_key_path;self.clock=clock;self.active=active;self.baseline=baseline
        self.metadata_override=metadata;self.verify_ssh=verify_ssh
        self.id=self.store.identity();self.sessions={};self.lock=threading.RLock();self.httpd=None;self.advert=None
        self.candidates={};self.local_token=secrets.token_urlsafe(32)
        with self.store.locked():
            # Older pairs on this Mac could not carry a GGUF split; upgrade them in place.
            try: self.store.refresh_authorizations()
            except (OSError,ValueError): pass
            control=read_json(self.store.root/'control.json')
            if control is None:
                control={'capability':secrets.token_hex(32)}
                atomic(self.store.root/'control.json',json.dumps(control),backup=False)
            self.capability=control['capability']
        self._discovery_cache={'at':0,'nodes':[]}

    def info(self):
        offer=read_json(self.store.root/'offer.json',{})
        return {'protocol':'caravan-pair-v1','id':self.id,'name':socket.gethostname().split('.')[0][:80],
                'accepting':not offer.get('used',True) and offer.get('expires',0)>self.clock() and offer.get('attempts',MAX_ATTEMPTS)<MAX_ATTEMPTS,
                'offer_id':offer.get('id'),'remote_login':remote_login(self.ssh_port)}

    def local_state(self):
        with self.lock:
            offer=read_json(self.store.root/'offer.json',{})
            ready=self.info()
            return {**ready,'code':display_code(offer) if ready['accepting'] else None,
                    'expires_in':max(0,int(offer.get('expires',0)-self.clock())),
                    'busy':bool(self.active()),'port':self.port,
                    'peers':[{'id':r['id'],'name':r.get('name','Mac'),'direction':r.get('direction'),
                              'state':r.get('state'),'order':r.get('order'),'node_id':r.get('node_id')} for r in self.store.records()]}

    def metadata(self, local_address):
        if self.metadata_override is not None:
            return {**self.metadata_override,'id':self.id,'host_key':host_key(self.host_key_path),'ssh_port':self.ssh_port}
        iface=None
        try:
            import thunderbolt_discovery as tb
            inventory=tb.collect_local()
            for item in inventory['interfaces']:
                if local_address in item.get('addresses',[]): iface=item['interface'];break
        except Exception: pass
        return {'id':self.id,'name':socket.gethostname().split('.')[0][:80],
                'user':getpass.getuser(),'repo':str(self.store.repo),'host_key':host_key(self.host_key_path),
                'ssh_port':self.ssh_port,'tb_interface':iface,'data_host':local_address}

    def start(self,body,source):
        from spake2 import SPAKE2_B
        now=self.clock()
        with self.lock,self.store.locked():
            offer=read_json(self.store.root/'offer.json',{})
            if offer.get('used',True) or offer.get('expires',0)<=now or offer.get('id')!=body.get('offer_id'):
                raise ValueError(T("server.pairing.that_pairing_code_expired_or_was"))
            if offer.get('attempts',0)>=MAX_ATTEMPTS: raise ValueError(T("server.pairing.too_many_attempts_show_a_new"))
            # Durable global budget, shared across source IPs and service restarts.
            # Every PAKE execution costs one online guess, including abandoned ones.
            offer['attempts']=offer.get('attempts',0)+1
            atomic(self.store.root/'offer.json',json.dumps(offer),backup=False)
            if not remote_login(self.ssh_port): raise ValueError(T("server.pairing.on_the_new_mac_turn_on"))
            key=host_key(self.host_key_path)  # do not accept trust if SSH identity is unavailable
            incoming=un64(body.get('a'),64)
            q=SPAKE2_B(offer['code'].encode(),idA=b'caravan-lead-v1',idB=offer['id'].encode())
            outgoing=q.start()
            try: shared=q.finish(incoming)
            except Exception: raise ValueError(T("server.pairing.invalid_pairing_handshake")) from None
            sid=secrets.token_hex(16)
            self.sessions={k:v for k,v in self.sessions.items() if v['expires']>now}
            self.sessions[sid]={'key':shared,'source':source,'offer':offer['id'],'expires':min(now+45,offer['expires'])}
            return {'b':b64(outgoing),'session':sid,'id':self.id,
                    'confirm':seal(shared,{'id':self.id,'offer':offer['id'],'session':sid},'caravan-pair-v1/'+sid+'/confirm')}

    def finish(self,body,source,local_address):
        sid=valid_id(body.get('session'))
        with self.lock,self.store.locked():
            session=self.sessions.get(sid)
            if not session or session['expires']<=self.clock() or source!=session['source']: raise ValueError(T("server.pairing.pairing_session_expired"))
            data=unseal(session['key'],body.get('box'),'caravan-pair-v1/'+sid+'/enroll')
            peer=valid_id(data.get('id'));key=public_key(data.get('key'))
            revoke=un64(data.get('revoke'),32)
            if len(revoke)!=32 or peer==self.id: raise ValueError(T("server.pairing.invalid_pairing_identity"))
            offer=read_json(self.store.root/'offer.json',{})
            if offer.get('id')!=session['offer']: raise ValueError(T("server.pairing.that_code_was_replaced_try_the"))
            previous=self.store.record(peer)
            if offer.get('used'):
                if not session.get('done') or session['done']!=peer: raise ValueError(T("server.pairing.that_pairing_code_was_already_used"))
            else:
                if previous: raise ValueError(T("server.pairing.this_mac_is_already_paired_remove"))
                # Consume the code before authorizing a key. A lost response can
                # retry this same confirmed session, never enroll another identity.
                offer['used']=True;atomic(self.store.root/'offer.json',json.dumps(offer),backup=False)
                record={'id':peer,'direction':'incoming','name':str(data.get('name') or T("server.pairing.first_mac"))[:80],
                        'key':key,'revoke':b64(revoke),'state':'preparing'}
                self.store.save(peer,record)
                self.store.authorize(peer,key)
                record['state']='active';self.store.save(peer,record);session['done']=peer
            result=self.metadata(local_address)
            return {'box':seal(session['key'],result,'caravan-pair-v1/'+sid+'/reply')}

    def revoke(self,body,source):
        peer=valid_id(body.get('id'))
        with self.lock,self.store.locked():
            row=self.store.record(peer)
            receipt=read_json(self.store.root/'revoked'/(peer+'.json')) if not row else None
            saved=row or receipt
            if not saved or saved.get('direction')!='incoming': raise ValueError(T("server.pairing.pairing_identity_was_not_verified"))
            token=un64(saved['revoke'],32)
            context='caravan-pair-v1/revoke/'+peer+'/'+self.id
            request_data=unseal(token,body.get('box'),context)
            nonce=valid_id(request_data.get('nonce'))
            if request_data.get('target')!=self.id or request_data.get('op')!='remove': raise ValueError(T("server.pairing.invalid_removal_request"))
            if row:
                if self.active(): raise ValueError(T("server.pairing.this_mac_is_running_a_model"))
                self.store.unauthorize(peer)
                atomic(self.store.root/'revoked'/(peer+'.json'),json.dumps({'direction':'incoming','revoke':saved['revoke']}),backup=False)
                self.store.record_path(peer).unlink()
            return {'box':seal(token,{'removed':True,'nonce':nonce},context+'/reply')}

    def remote_remove(self,row):
        peer=valid_id(row['id']);token=un64(row['revoke'],32);nonce=secrets.token_hex(16)
        context='caravan-pair-v1/revoke/'+self.id+'/'+peer
        response=request(tuple(row['endpoint']),'/v1/revoke',{'id':self.id,
                         'box':seal(token,{'op':'remove','target':peer,'nonce':nonce},context)})
        value=unseal(token,response.get('box'),context+'/reply')
        if value.get('removed') is not True or value.get('nonce')!=nonce: raise ValueError(T("server.pairing.removal_was_not_confirmed_by_the"))

    def pair(self,peer,code):
        with self.lock: return self._pair(peer,code)

    def _pair(self,peer,code):
        from spake2 import SPAKE2_A
        peer=valid_id(peer)
        if not isinstance(code,str): raise ValueError(T("server.pairing.enter_the_code_shown_on_the"))
        code=code.replace('-','').replace(' ','')
        if len(code)!=8 or not code.isascii() or not code.isdigit(): raise ValueError(T("server.pairing.enter_the_eight_digit_code_shown"))
        candidate=self.candidates.get(peer)
        if not candidate or self.clock()-candidate['seen']>60: raise ValueError(T("server.pairing.find_nearby_macs_again_before_pairing"))
        if self.store.record(peer): raise ValueError(T("server.pairing.this_mac_already_has_a_pairing"))
        endpoint=(candidate.get('host') or candidate['address'],candidate['port'])
        offer=request(endpoint,'/v1/info')
        if offer.get('id')!=peer or not offer.get('accepting'): raise ValueError(T("server.pairing.that_mac_is_no_longer_showing"))
        s=SPAKE2_A(code.encode(),idA=b'caravan-lead-v1',idB=offer['offer_id'].encode())
        outgoing=s.start();reply=request(endpoint,'/v1/start',{'offer_id':offer['offer_id'],'a':b64(outgoing)})
        if reply.get('id')!=peer: raise ValueError(T("server.pairing.the_discovered_mac_identity_changed_find"))
        sid=valid_id(reply.get('session'))
        try: shared=s.finish(un64(reply.get('b'),64))
        except Exception: raise ValueError(T("server.pairing.pairing_identity_could_not_be_checked")) from None
        confirmation=unseal(shared,reply.get('confirm'),'caravan-pair-v1/'+sid+'/confirm')
        if confirmation!={'id':peer,'offer':offer['offer_id'],'session':sid}: raise ValueError(T("server.pairing.the_pairing_confirmation_did_not_match"))
        # No SSH key is sent before key confirmation succeeds. The encrypted
        # envelope also binds the discovered Mac ID, our ID, and this session.
        path,pub=self.store.make_key(peer)
        revoke=secrets.token_bytes(32)
        row={'id':peer,'direction':'outgoing','name':candidate['name'],'endpoint':list(endpoint),
             'revoke':b64(revoke),'key_path':str(path),'state':'preparing'}
        self.store.save(peer,row)
        payload={'id':self.id,'key':pub,'revoke':b64(revoke),'name':socket.gethostname().split('.')[0][:80]}
        try:
            reply=request(endpoint,'/v1/finish',{'session':sid,'box':seal(shared,payload,'caravan-pair-v1/'+sid+'/enroll')})
            meta=unseal(shared,reply.get('box'),'caravan-pair-v1/'+sid+'/reply')
            if meta.get('id')!=peer: raise ValueError(T("server.pairing.the_mac_identity_did_not_match"))
            with self.store.locked():
                result=self.store.enroll(peer,meta,endpoint[0],path,baseline=self.baseline())
                row.update(result);row['state']='verifying';self.store.save(peer,row)
            if self.verify_ssh:
                checked=subprocess.run(['ssh','-F',result['ssh_config'],result['alias'],'true'],capture_output=True,timeout=10)
                if checked.returncode: raise ValueError(T("server.pairing.pairing_was_checked_but_remote_login"))
            row['state']='active';self.store.save(peer,row)
            record_route(result.get('alias'),candidate.get('name'))
            return {'added':True,**result,'split':'auto'}
        except Exception:
            # Keep the durable revocation credential if the other Mac cannot be
            # reached; the UI offers removal/retry rather than hiding a partial trust.
            try:
                self.remote_remove(row)
                with self.store.locked(): self.store.forget_local(peer)
            except Exception:
                row['state']='needs-removal';self.store.save(peer,row)
            raise

    def remove(self,peer):
        with self.lock: return self._remove(peer)

    def _remove(self,peer):
        peer=valid_id(peer);row=self.store.record(peer)
        if not row or row.get('direction')!='outgoing': raise ValueError(T("server.pairing.remove_this_mac_from_the_first"))
        if self.active(): raise ValueError(T("server.pairing.unload_the_model_before_removing_a"))
        try: self.remote_remove(row)
        except Exception:
            row['state']='removal-pending';self.store.save(peer,row)
            return {'removed':False,'pending':True,'message':T("server.pairing.waiting_for_the_other_mac_its")}
        with self.store.locked(): self.store.forget_local(peer)
        return {'removed':True}

    def discover(self,extra=()):
        sys.path.insert(0,str(ROOT/'agent')) if str(ROOT/'agent') not in sys.path else None
        targets=[]
        try:
            from discovery import mdns
            for name in mdns.browse(duration=1.5)[:128]:
                found=mdns.resolve(name,duration=.4)
                if found: targets.append((found[0],found[1],T("server.pairing.lan_cable")))
        except Exception: pass
        try:
            from discovery import tailscale
            for peer in tailscale.get_peers(timeout=2):
                if peer.online: targets.append((peer.tailscale_ip,self.port,T("server.pairing.private_tailnet")))
        except Exception: pass
        targets.extend((h,p,T("server.pairing.test_saved_connection")) for h,p in extra)
        targets.extend((r['endpoint'][0],r['endpoint'][1],T("server.pairing.paired_mac")) for r in self.store.records() if r.get('direction')=='outgoing')
        def probe(target):
            host,port,kind=target
            try:
                for ip in addresses(host):
                    try:
                        value=request((ip,port),'/v1/info',timeout=1.5)
                        peer=valid_id(value.get('id'))
                        if value.get('protocol')!='caravan-pair-v1' or peer==self.id: continue
                        return {'id':peer,'name':str(value.get('name') or T("server.pairing.mac"))[:80],'address':ip,'port':int(port),
                                'host':host,'source':kind,'accepting':bool(value.get('accepting')),'remote_login':bool(value.get('remote_login')),'seen':self.clock()}
                    except Exception: continue
            except Exception: pass
            return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            found=[row for row in pool.map(probe,list(dict.fromkeys(targets))[:128]) if row]
        unique={}
        for row in found:
            # Prefer a direct cable/LAN route over a VPN when both reach the same
            # cryptographically verified identity. Discovery labels alone are untrusted.
            if row['id'] not in unique or unique[row['id']]['source']==T("server.pairing.private_tailnet"): unique[row['id']]=row
        self.candidates=unique
        self._discovery_cache={'at':self.clock(),'nodes':list(unique.values())}
        return list(unique.values())

    def serve(self,host='0.0.0.0',*,advertise=True):
        manager=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args): pass
            def respond(self,status,value):
                raw=json.dumps(value).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.send_header('Connection','close');self.end_headers();self.wfile.write(raw)
            def handle_pair(self):
                if not private(self.client_address[0]) or self.headers.get('Origin'):
                    return self.respond(403,{'error':T("server.pairing.pairing_accepts_only_the_local_network")})
                path=self.path
                try:
                    if self.command=='GET' and path=='/v1/info': return self.respond(200,manager.info())
                    if self.command!='POST': return self.respond(404,{'error':T("server.pairing.not_found")})
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=MAX_BODY: raise ValueError(T("server.pairing.invalid_pairing_request_size"))
                    body=json.loads(self.rfile.read(size))
                    if not isinstance(body,dict): raise ValueError(T("server.pairing.invalid_pairing_request"))
                    if path=='/v1/start': value=manager.start(body,self.client_address[0])
                    elif path=='/v1/finish': value=manager.finish(body,self.client_address[0],self.connection.getsockname()[0])
                    elif path=='/v1/revoke': value=manager.revoke(body,self.client_address[0])
                    else: return self.respond(404,{'error':T("server.pairing.not_found")})
                    return self.respond(200,value)
                except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
                    # Do not expose decrypted payloads, codes, filesystem paths or
                    # exception strings through the public pairing listener/logs.
                    return self.respond(400,{'error':T("server.pairing.pairing_could_not_finish_check_the")})
            do_GET=handle_pair
            do_POST=handle_pair
        class Server(ThreadingHTTPServer):
            slots=threading.BoundedSemaphore(16)
            def server_bind(self):
                import socketserver
                socketserver.TCPServer.server_bind(self)
                self.server_name=self.server_address[0];self.server_port=self.server_address[1]
            def get_request(self):
                sock,address=super().get_request();sock.settimeout(5);return sock,address
            def process_request(self,sock,address):
                if not self.slots.acquire(blocking=False): self.shutdown_request(sock);return
                try: super().process_request(sock,address)
                except BaseException: self.slots.release();raise
            def process_request_thread(self,sock,address):
                try: super().process_request_thread(sock,address)
                finally: self.slots.release()
        self.httpd=Server((host,self.port),Handler)
        self.httpd.daemon_threads=True;self.port=self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever,daemon=True).start()
        if advertise and sys.platform=='darwin':
            try:
                sys.path.insert(0,str(ROOT/'agent')) if str(ROOT/'agent') not in sys.path else None
                from discovery import mdns
                name='Caravan-'+self.id[:12]
                # A web server that was stopped (update, restart) could not
                # stop its dns-sd child; stop our own leftovers first.
                stop_stale_adverts(name,self.port)
                self.advert=mdns.advertise_start(name,self.port)
                self._watch_exit()
            except Exception: self.advert=None
        threading.Thread(target=self._retry_removals,daemon=True).start()
        return self

    def _retry_removals(self):
        while self.httpd is not None:
            time.sleep(30)
            for row in self.store.records():
                if row.get('state')=='removal-pending':
                    try: self.remove(row['id'])
                    except Exception: pass

    def _stop_advert(self):
        advert,self.advert=self.advert,None
        if not advert: return
        try:
            advert.terminate()
            try: advert.wait(timeout=2)
            except subprocess.TimeoutExpired: advert.kill()
        except OSError: pass

    def _watch_exit(self):
        """Stop the dns-sd child when this process ends, including SIGTERM
        (launchd's stop, used by updates). Otherwise every restart left one
        `dns-sd -R` running. Only adds the stop; the exit itself is unchanged."""
        import atexit, signal
        atexit.register(self._stop_advert)
        try:
            if signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL: return
            def on_term(signum, frame):
                try: self._stop_advert()
                finally:
                    signal.signal(signum, signal.SIG_DFL); os.kill(os.getpid(), signum)
            signal.signal(signal.SIGTERM, on_term)
        except (ValueError, OSError): pass  # not the main thread

    def close(self):
        if self.httpd: self.httpd.shutdown();self.httpd.server_close();self.httpd=None
        self._stop_advert()
