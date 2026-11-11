"""Pairing protocol and storage tests: scratch homes/keys, never the user's SSH."""
from __future__ import annotations
import base64
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'));sys.path.insert(0,str(ROOT/'proxy'));sys.path.insert(0,str(ROOT/'tools'))
import pairing as P
from pairing_store import Store,atomic,public_key
import web_pairing as W
from caravan_pairing import launch_file

KEY='ssh-ed25519 '+base64.b64encode(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'+b'k'*32).decode()

class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.host=self.root/'host.pub';self.host.write_text(KEY+' test-only\n')
        self.patch=mock.patch('pairing.remote_login',return_value=True);self.patch.start()
        self.servers=[]
    def tearDown(self):
        for s in self.servers:s.close()
        self.patch.stop();self.tmp.cleanup()
    def manager(self,name,**kw):
        return P.Pairing(Store(self.root/name,repo=self.root/(name+' source')),
                         host_key_path=self.host,verify_ssh=False,**kw)
    def pair(self):
        helper=self.manager('helper home',port=0).serve('127.0.0.1',advertise=False);self.servers.append(helper)
        lead=self.manager('lead home');offer=P.prepare_offer(helper.store)
        lead.candidates={helper.id:{'address':'127.0.0.1','port':helper.port,'name':'My helper','seen':lead.clock()}}
        return lead,helper,offer
    def handshake(self,helper,offer,*,password=None,source='127.0.0.1'):
        from spake2 import SPAKE2_A
        a=SPAKE2_A((password or offer['code']).encode(),idA=b'caravan-lead-v1',idB=offer['id'].encode())
        b=helper.start({'offer_id':offer['id'],'a':P.b64(a.start())},source)
        return b,a.finish(P.un64(b['b']))

class ProtocolTests(Scratch):
    def test_add_remove_preserves_other_keys(self):
        lead,helper,offer=self.pair()
        auth=helper.store.home/'.ssh/authorized_keys';auth.parent.mkdir();auth.write_text('# unrelated\n'+KEY+' my-key\n')
        out=lead.pair(helper.id,offer['code'][:4]+'-'+offer['code'][4:])
        self.assertEqual(out['order'],1);self.assertEqual(lead.store.record(helper.id)['state'],'active')
        self.assertIn('restrict,port-forwarding',auth.read_text());self.assertIn('permitlisten="127.0.0.1:8194"',auth.read_text())
        self.assertIn('caravan-pair:'+lead.id,auth.read_text());self.assertFalse(helper.info()['accepting'])
        self.assertTrue(lead.remove(helper.id)['removed']);self.assertEqual(auth.read_text(),'# unrelated\n'+KEY+' my-key\n')
        self.assertEqual(lead.store.records(),[]);self.assertEqual(helper.store.records(),[])
        self.assertNotIn('paired_',lead.store.config.read_text())
        self.assertFalse((lead.store.root/'keys'/helper.id).exists())
    def test_wrong_code_does_not_create_any_trust_or_local_record(self):
        lead,helper,offer=self.pair();wrong='99999999' if offer['code']!='99999999' else '11111111'
        with self.assertRaises(ValueError):lead.pair(helper.id,wrong)
        self.assertEqual(helper.store.records(),[]);self.assertEqual(lead.store.records(),[])
        self.assertFalse((helper.store.home/'.ssh/authorized_keys').exists());self.assertFalse(lead.store.config.exists())
    def test_public_info_and_http_replies_never_reveal_code(self):
        lead,helper,offer=self.pair();info=P.request(('127.0.0.1',helper.port),'/v1/info')
        self.assertNotIn(offer['code'],json.dumps(info));self.assertNotIn('user',info);self.assertNotIn('repo',info);self.assertNotIn('key',info)
    def test_code_is_consumed_and_replay_rejected(self):
        lead,helper,offer=self.pair();lead.pair(helper.id,offer['code'])
        with self.assertRaises(ValueError):self.handshake(helper,offer)
    def test_expired_code_rejected(self):
        helper=self.manager('helper',clock=lambda:2000);offer=P.prepare_offer(helper.store,now=1000)
        with self.assertRaises(ValueError):self.handshake(helper,offer)
    def test_attempt_budget_survives_restart_and_address_change(self):
        helper=self.manager('helper');offer=P.prepare_offer(helper.store)
        for i in range(P.MAX_ATTEMPTS):self.handshake(helper,offer,password='00000000',source=f'10.0.0.{i+1}')
        restarted=P.Pairing(helper.store,host_key_path=self.host,verify_ssh=False)
        with self.assertRaisesRegex(ValueError,'Too many'):self.handshake(restarted,offer)
        self.assertFalse(restarted.info()['accepting'])
    def test_renewal_invalidates_existing_sessions(self):
        helper=self.manager('helper');offer=P.prepare_offer(helper.store);reply,key=self.handshake(helper,offer)
        P.prepare_offer(helper.store,renew=True)
        payload={'id':secrets.token_hex(16),'key':KEY,'revoke':P.b64(secrets.token_bytes(32))}
        with self.assertRaises(ValueError):helper.finish({'session':reply['session'],'box':P.seal(key,payload,'caravan-pair-v1/'+reply['session']+'/enroll')},'127.0.0.1','127.0.0.1')
        self.assertEqual(helper.store.records(),[])
    def test_tampered_confirmation_is_rejected(self):
        key=secrets.token_bytes(32);box=P.seal(key,{'ok':True},'one')
        with self.assertRaises(ValueError):P.unseal(key,box,'two')
        with self.assertRaises(ValueError):P.unseal(secrets.token_bytes(32),box,'one')
    def test_finish_bound_to_source_and_expiry(self):
        helper=self.manager('helper');offer=P.prepare_offer(helper.store);reply,key=self.handshake(helper,offer)
        with self.assertRaises(ValueError):helper.finish({'session':reply['session'],'box':'a'},'10.0.0.2','127.0.0.1')
        helper.sessions[reply['session']]['expires']=0
        with self.assertRaises(ValueError):helper.finish({'session':reply['session'],'box':'a'},'127.0.0.1','127.0.0.1')
    def test_bad_ssh_rolls_back_both_sides(self):
        lead,helper,offer=self.pair();lead.verify_ssh=True
        # Key generation must be real, not mocked by the SSH failure stub.
        lead.store.make_key(helper.id)
        with mock.patch('pairing.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ValueError):lead.pair(helper.id,offer['code'])
        self.assertFalse(helper.store.records());self.assertFalse(lead.store.records())
    def test_active_model_prevents_remove(self):
        lead,helper,offer=self.pair();lead.pair(helper.id,offer['code']);lead.active=lambda:True
        with self.assertRaises(ValueError):lead.remove(helper.id)
        self.assertEqual(lead.store.record(helper.id)['state'],'active');self.assertTrue(helper.store.records())
    def test_helper_active_prevents_revoke_and_keeps_pending(self):
        lead,helper,offer=self.pair();lead.pair(helper.id,offer['code']);helper.active=lambda:True
        self.assertTrue(lead.remove(helper.id)['pending']);self.assertTrue(helper.store.records())
        helper.active=lambda:False;self.assertTrue(lead.remove(helper.id)['removed'])
    def test_offline_remove_is_pending_and_retry_works(self):
        lead,helper,offer=self.pair();lead.pair(helper.id,offer['code'])
        real=P.request
        with mock.patch('pairing.request',side_effect=OSError('offline')):self.assertTrue(lead.remove(helper.id)['pending'])
        self.assertTrue(lead.store.record(helper.id)['revoke']);self.assertTrue(lead.remove(helper.id)['removed'])
    def test_fake_removal_success_cannot_discard_credentials(self):
        lead,helper,offer=self.pair();lead.pair(helper.id,offer['code'])
        with mock.patch('pairing.request',return_value={'removed':True}):self.assertTrue(lead.remove(helper.id)['pending'])
        self.assertTrue(lead.store.records());self.assertTrue(helper.store.records())
    def test_lost_removal_ack_can_be_retried(self):
        lead,helper,offer=self.pair();lead.pair(helper.id,offer['code']);row=lead.store.record(helper.id)
        lead.remote_remove(row);self.assertFalse(helper.store.records())
        self.assertTrue(lead.remove(helper.id)['removed'])
    def test_discovery_connects_to_private_synthetic_peer(self):
        lead,helper,offer=self.pair()
        with mock.patch('discovery.mdns.browse',return_value=[]),mock.patch('discovery.tailscale.get_peers',return_value=[]):
            found=lead.discover(extra=[('127.0.0.1',helper.port)])
        self.assertEqual(found[0]['id'],helper.id)
    def test_private_address_policy(self):
        for ip in ('127.0.0.1','10.1.2.3','169.254.1.2','100.64.0.4','fd00::1','::ffff:192.168.1.1'):self.assertTrue(P.private(ip),ip)
        for ip in ('8.8.8.8','0.0.0.0','100.128.0.1','2001:4860:4860::8888','bad'):self.assertFalse(P.private(ip),ip)
    def test_dns_rebinding_policy_all_addresses_must_be_private(self):
        with mock.patch('pairing.socket.getaddrinfo',return_value=[(None,None,None,None,('10.0.0.2',0)),(None,None,None,None,('8.8.8.8',0))]):
            with self.assertRaises(ValueError):P.addresses('helper.local')

class StorageTests(Scratch):
    def enroll(self,store,peer=None,**meta):
        peer=peer or secrets.token_hex(16)
        value={'user':'macuser','repo':'/a source with spaces','host_key':KEY,**meta}
        with store.locked():out=store.enroll(peer,value,'127.0.0.1',store.root/'keys'/peer)
        return peer,out
    def test_spaces_quoted_strict_host_key_and_permissions(self):
        store=Store(self.root/'home with spaces');peer,out=self.enroll(store)
        cfg=(store.home/'.ssh/config').read_text();self.assertIn('StrictHostKeyChecking yes',cfg);self.assertIn('IdentityFile "',cfg)
        effective=subprocess.run(['ssh','-G','-F',str(store.home/'.ssh/config'),out['alias']],capture_output=True,text=True)
        self.assertEqual(effective.returncode,0,effective.stderr);self.assertIn('stricthostkeychecking true',effective.stdout)
        self.assertEqual(store.config.stat().st_mode&0o777,0o600);self.assertEqual(store.root.stat().st_mode&0o777,0o700)
    def test_n_macs_get_unique_orders_preserve_existing_config(self):
        store=Store(self.root/'home');atomic(store.config,'# keep me\n[defaults]\nthreads=3\n')
        peers=[self.enroll(store) for _ in range(4)]
        config=tomllib.loads(store.config.read_text());self.assertEqual(len(config['web']['nodes']),5)
        self.assertEqual([out['order'] for _,out in peers],[1,2,3,4]);self.assertIn('# keep me',store.config.read_text())
        self.assertEqual(config['defaults']['threads'],3);self.assertTrue(list(store.config.parent.glob('config.toml.bak-*')))
    def test_existing_ssh_wildcard_cannot_disable_host_checks(self):
        store=Store(self.root/'home');atomic(store.home/'.ssh/config','Host *\n StrictHostKeyChecking no\n ProxyCommand false\n')
        peer,out=self.enroll(store)
        effective=subprocess.run(['ssh','-G','-F',str(store.home/'.ssh/config'),out['alias']],capture_output=True,text=True)
        self.assertIn('stricthostkeychecking true',effective.stdout);self.assertNotIn('proxycommand false',effective.stdout)
    def test_bad_toml_no_trust_written(self):
        store=Store(self.root/'home');atomic(store.config,'[invalid')
        with self.assertRaises(ValueError):self.enroll(store)
        self.assertFalse((store.home/'.ssh/config').exists());self.assertEqual(store.config.read_text(),'[invalid')
    def test_existing_inventory_materialized_without_losing_helper(self):
        store=Store(self.root/'home');peer=secrets.token_hex(16)
        with store.locked():store.enroll(peer,{'user':'macuser','repo':'/source','host_key':KEY},'127.0.0.1',store.root/'keys'/peer,
                           baseline=[{'id':'first','host':'local','role':'lead','order':0},{'id':'existing','host':'known-helper','role':'packer','peer':None,'order':1}])
        self.assertIn('existing',tomllib.loads(store.config.read_text())['web']['nodes'])
    def test_symlink_refused_without_chmod_of_target(self):
        store=Store(self.root/'home');store.home.mkdir();other=self.root/'other';other.mkdir(mode=0o755)
        (store.home/'.ssh').symlink_to(other,target_is_directory=True)
        with self.assertRaises(ValueError):self.enroll(store)
        self.assertEqual(other.stat().st_mode&0o777,0o755)
    def test_journal_recovers_interrupted_write(self):
        store=Store(self.root/'home');store.identity();file=store.config;atomic(file,'old')
        new=b'new';atomic(store.root/'transaction.json',json.dumps([{'path':str(file),'old':base64.b64encode(b'old').decode(),'new_hash':P.hashlib.sha256(new).hexdigest()}]),backup=False)
        atomic(file,new)
        with store.locked():pass
        self.assertEqual(file.read_text(),'old');self.assertFalse((store.root/'transaction.json').exists())
    def test_recovery_refuses_to_overwrite_manual_edit(self):
        store=Store(self.root/'home');store.identity();atomic(store.config,'manual')
        atomic(store.root/'transaction.json',json.dumps([{'path':str(store.config),'old':base64.b64encode(b'old').decode(),'new_hash':P.hashlib.sha256(b'new').hexdigest()}]),backup=False)
        with self.assertRaises(ValueError):
            with store.locked():pass
        self.assertEqual(store.config.read_text(),'manual')
    def test_key_options_cannot_be_injected(self):
        for value in ('command="bad" '+KEY,'ssh-rsa AAAA','ssh-ed25519 AAAA'):
            with self.assertRaises(ValueError):public_key(value)
    def test_dynamic_cable_endpoint_from_verified_interface(self):
        store=Store(self.root/'home');peer,out=self.enroll(store,tb_interface='en9')
        self.assertTrue(out['peer'].startswith('ssh+tb://'));self.assertTrue(out['peer'].endswith('/en9:5560'))
    def test_private_browser_handoff_has_no_secret_in_filename(self):
        page=launch_file(8290,home=self.root/'home',next_home=True)
        secret=json.loads((page.parent/'control.json').read_text())['capability']
        self.assertNotIn(secret,str(page));self.assertIn('#pair='+secret,page.read_text());self.assertEqual(page.stat().st_mode&0o777,0o600)

    def test_public_model_endpoint_refused_before_any_write(self):
        store=Store(self.root/'home')
        with self.assertRaises(ValueError):self.enroll(store,data_host='8.8.8.8')
        self.assertFalse(store.config.exists());self.assertFalse((store.home/'.ssh/config').exists())
    def test_interrupted_own_key_generation_repairs_missing_public_half(self):
        store=Store(self.root/'home');store.identity();peer=secrets.token_hex(16)
        path,key=store.make_key(peer);path.with_suffix('.pub').unlink()
        repaired,public=store.make_key(peer)
        self.assertEqual(repaired,path);self.assertEqual(public,key)
    def test_linked_state_is_not_read(self):
        store=Store(self.root/'home');store.identity();other=self.root/'other.json';other.write_text('{"secret":"not read"}')
        linked=store.root/'linked.json';linked.symlink_to(other)
        with self.assertRaises(ValueError):P.read_json(linked)
    def test_dual_stack_prefers_supported_ipv4_path(self):
        with mock.patch('pairing.socket.getaddrinfo',return_value=[(None,None,None,None,('fd00::2',0,0,0)),(None,None,None,None,('192.168.1.2',0))]):
            self.assertEqual(P.addresses('helper.local')[0],'192.168.1.2')

class ManagementTests(Scratch):
    def handler(self,*,path='/api/pairing/state',origin=None,host='127.0.0.1:8190',source='127.0.0.1',cookie=None,method='GET',body=None):
        headers={'Host':host}
        if origin is not None:headers['Origin']=origin
        if cookie:headers['Cookie']=cookie
        raw=json.dumps(body or {}).encode();headers['Content-Type']='application/json';headers['Content-Length']=str(len(raw))
        h=SimpleNamespace(path=path,headers=headers,client_address=(source,1234),server=SimpleNamespace(server_port=8190),command=method,
                          rfile=io.BytesIO(raw),wfile=io.BytesIO(),sent_headers={})
        h.send_response=lambda status:setattr(h,'status',status);h.send_header=lambda k,v:h.sent_headers.update({k:v});h.end_headers=lambda:None
        return h
    def test_state_does_not_disclose_code_to_another_local_account(self):
        manager=self.manager('home');P.prepare_offer(manager.store);h=self.handler()
        self.assertTrue(W.dispatch(h,SimpleNamespace(pairing=manager)));self.assertEqual(h.status,403)
        self.assertNotIn(P.read_json(manager.store.root/'offer.json')['code'],h.wfile.getvalue().decode())
    def test_network_and_rebinding_and_cross_origin_refused(self):
        for kwargs in ({'source':'192.168.1.2'},{'host':'evil.example:8190'},{'origin':'https://evil.example'}):
            self.assertFalse(W.allowed(self.handler(**kwargs)))
    def test_post_requires_origin_and_capability(self):
        manager=self.manager('home');h=self.handler(path='/api/pairing/session',method='POST',body={'capability':manager.capability})
        W.dispatch(h,SimpleNamespace(pairing=manager));self.assertEqual(h.status,403)
    def test_local_session_cookie_is_httponly_and_state_authenticated(self):
        manager=self.manager('home');app=SimpleNamespace(pairing=manager)
        h=self.handler(path='/api/pairing/session',method='POST',origin='http://127.0.0.1:8190',body={'capability':manager.capability})
        W.dispatch(h,app);self.assertEqual(h.status,200);self.assertIn('HttpOnly',h.sent_headers['Set-Cookie'])
        self.assertNotIn('Access-Control-Allow-Origin',h.sent_headers)
        h=self.handler(cookie='caravan_pair_8190='+manager.capability);W.dispatch(h,app)
        self.assertEqual(h.status,200);self.assertIn('token',json.loads(h.wfile.getvalue()))
    def test_csrf_header_required_even_with_owner_cookie(self):
        manager=self.manager('home');h=self.handler(path='/api/pairing/code',method='POST',origin='http://127.0.0.1:8190',cookie='caravan_pair_8190='+manager.capability)
        W.dispatch(h,SimpleNamespace(pairing=manager));self.assertEqual(h.status,403)
    def test_remote_login_opens_native_pane_never_sudo(self):
        manager=self.manager('home');h=self.handler(path='/api/pairing/remote-login',method='POST',origin='http://127.0.0.1:8190',cookie='caravan_pair_8190='+manager.capability)
        h.headers['X-Caravan-Pairing']=manager.local_token
        with mock.patch('web_pairing.sys.platform','darwin'),mock.patch('web_pairing.subprocess.run') as run:
            W.dispatch(h,SimpleNamespace(pairing=manager));self.assertEqual(h.status,200)
            self.assertEqual(run.call_args.args[0],['/usr/bin/open',P.SETTINGS_URL])

if __name__=='__main__':unittest.main()
