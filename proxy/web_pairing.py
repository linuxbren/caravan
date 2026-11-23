"""Loopback-only pairing management; separate from the existing public web API."""
from __future__ import annotations
from http.cookies import SimpleCookie
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import urlsplit
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

LOCK=threading.Lock()
WEB=Path(__file__).resolve().parent/'web'


def active(app):
    snap=app.mgr.snapshot()
    if snap.get('status') not in ('idle','error') or snap.get('model_id'): return True
    # A helper may have been started over SSH by the first Mac, outside its own
    # UI manager. Refuse removal while either model/data listener still exists.
    if sys.platform=='darwin':
        try:
            p=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:5560','-iTCP:8194','-sTCP:LISTEN','-t'],capture_output=True,timeout=3)
            if p.returncode==0 and p.stdout.strip(): return True
        except (OSError,subprocess.SubprocessError): return True
    return False


def start(app):
    if hasattr(app,'pairing'): return app.pairing
    with LOCK:
        if hasattr(app,'pairing'): return app.pairing
        app.pairing=None;app.pairing_error=T("server.web_pairing.mac_pairing_needs_the_current_managed")
        if sys.platform!='darwin' and os.environ.get('CARAVAN_PAIRING_ENABLED')!='1': return None
        if os.environ.get('CARAVAN_PAIRING_ENABLED')=='0':
            app.pairing_error=T("server.web_pairing.mac_pairing_is_turned_off_for");return None
        try:
            import spake2
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from pairing import Pairing
            from pairing_store import Store
            import web_settings
            app.pairing=Pairing(Store(repo=app.mgr.repo,config=web_settings.CONFIG_PATH),
                                port=int(os.environ.get('CARAVAN_PAIRING_PORT','8197')),
                                active=lambda:active(app),baseline=app.configured_nodes).serve()
            app.pairing_error=None
        except (ImportError,OSError,ValueError):
            app.pairing_error=T("server.web_pairing.mac_pairing_could_not_start_run")
        return app.pairing


def allowed(handler,*,post=False):
    try:
        addr=ipaddress.ip_address(handler.client_address[0])
        if getattr(addr,'ipv4_mapped',None): addr=addr.ipv4_mapped
        if not addr.is_loopback: return False
        host=handler.headers.get('Host','')
        parsed=urlsplit('http://'+host)
        if parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.port!=handler.server.server_port: return False
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment: return False
        origin=handler.headers.get('Origin')
        if origin is not None and origin!='http://'+host: return False
        if post and origin!='http://'+host: return False
        return True
    except (ValueError,KeyError): return False


def respond(handler,code,value,ctype='application/json',cookie=None):
    raw=json.dumps(value).encode() if ctype=='application/json' else value
    handler.send_response(code);handler.send_header('Content-Type',ctype)
    handler.send_header('Content-Length',str(len(raw)));handler.send_header('Cache-Control','no-store')
    handler.send_header('X-Content-Type-Options','nosniff');handler.send_header('Referrer-Policy','no-referrer')
    handler.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    if cookie: handler.send_header('Set-Cookie',cookie)
    handler.send_header('Connection','close');handler.end_headers();handler.wfile.write(raw)


def dispatch(handler,app):
    path=handler.path.split('?',1)[0]
    if path not in ('/pairing','/pairing.js','/pairing.css') and not path.startswith('/api/pairing/'): return False
    if not allowed(handler,post=handler.command=='POST'):
        respond(handler,403,{'error':T("server.web_pairing.for_your_security_open_caravan_on")});return True
    manager=start(app)
    if not manager:
        respond(handler,503,{'error':app.pairing_error});return True
    cookie_name='caravan_pair_'+str(handler.server.server_port)
    try:
        cookies=SimpleCookie(handler.headers.get('Cookie',''))
        authenticated=cookie_name in cookies and secrets.compare_digest(cookies[cookie_name].value,manager.capability)
    except Exception: authenticated=False
    is_session=path=='/api/pairing/session' and handler.command=='POST'
    if path.startswith('/api/pairing/') and not authenticated and not is_session:
        respond(handler,403,{'error':T("server.web_pairing.open_topology_add_a_mac_from")});return True
    if handler.command=='GET':
        files={'/pairing':('pairing.html','text/html; charset=utf-8'),'/pairing.js':('pairing.js','text/javascript; charset=utf-8'),'/pairing.css':('pairing.css','text/css; charset=utf-8')}
        if path in files:
            name,ctype=files[path];data=(WEB/name).read_bytes()
            if name.endswith('.html'):
                import caravan_i18n
                data=caravan_i18n.render_page(data.decode('utf-8')).encode('utf-8')
            respond(handler,200,data,ctype)
        elif path=='/api/pairing/state': respond(handler,200,{**manager.local_state(),'token':manager.local_token})
        else: respond(handler,404,{'error':T("server.pairing.not_found")})
        return True
    if handler.command!='POST':
        respond(handler,405,{'error':T("server.web_pairing.use_the_caravan_page")});return True
    # This route deliberately bypasses the older permissive _body/_cors helpers.
    try:
        size=int(handler.headers.get('Content-Length','0'))
        if not 0<size<=4096: raise ValueError(T("server.pairing.invalid_pairing_request_size"))
        if handler.headers.get('Content-Type')!='application/json': raise ValueError(T("server.web_pairing.use_the_caravan_page"))
        if not is_session and not secrets.compare_digest(handler.headers.get('X-Caravan-Pairing',''),manager.local_token):
            respond(handler,403,{'error':T("server.web_pairing.refresh_the_caravan_page_before_continuing")});return True
        body=json.loads(handler.rfile.read(size))
        if not isinstance(body,dict): raise ValueError(T("server.pairing.invalid_pairing_request"))
        if is_session:
            if not secrets.compare_digest(str(body.get('capability','')),manager.capability):
                respond(handler,403,{'error':T("server.web_pairing.open_topology_add_a_mac_from_2")});return True
            respond(handler,200,{'connected':True},cookie=cookie_name+'='+manager.capability+'; HttpOnly; SameSite=Strict; Path=/')
            return True
        if path=='/api/pairing/code':
            from pairing import prepare_offer
            prepare_offer(manager.store,renew=True);result=manager.local_state()
        elif path=='/api/pairing/discover': result={'nodes':manager.discover()}
        elif path=='/api/pairing/add': result=manager.pair(body.get('id'),body.get('code'))
        elif path=='/api/pairing/remove': result=manager.remove(body.get('id'))
        elif path=='/api/pairing/remote-login':
            from pairing import SETTINGS_URL
            if sys.platform!='darwin': raise ValueError(T("server.web_pairing.open_system_settings_on_the_new"))
            subprocess.run(['/usr/bin/open',SETTINGS_URL],check=True,capture_output=True,timeout=5)
            result={'opened':True}
        else:
            respond(handler,404,{'error':T("server.pairing.not_found")});return True
        if hasattr(app,'_nodes_cache'): app._nodes_cache=None
        respond(handler,200,result)
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
        # Do not accidentally return PAKE payloads or credential/file contents.
        respond(handler,400,{'error':T("server.web_pairing.could_not_finish_check_the_code")})
    return True
