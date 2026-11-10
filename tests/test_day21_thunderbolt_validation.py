"""Bound-link identity validation and fail-closed preview. No real network in tests."""
import copy
import io
import json
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'proxy'));sys.path.insert(0,str(ROOT/'agent'))
import thunderbolt_discovery as D
import thunderbolt_probe as P

EDGE={'source':'a','target':'b','source_interface':'en2','target_interface':'en2','source_address':'169.254.1.1','address':'169.254.1.2'}
IDENTITY={'alias':'100.64.1.2','user':'brenden','hostname':'b.local'}
def inventory(address,hostname='a.local'):
    return {'hostname':hostname,'username':'brenden','interfaces':[{'interface':'en2','kind':'thunderbolt','members':[],'addresses':[address]}],
            'routes':[{'address':EDGE['address'],'interface':'en2'}]}
def successful_run(argv,**kw):
    meta={**{'source':EDGE['source_address'],'target':EDGE['address'],'interface':'en2','bound_ifindex':5,'tcp_connect_ms':0.2}}
    hello={'nonce':'1'*32,'hostname':'b.local','connection':'169.254.1.1 12345 169.254.1.2 22'}
    return subprocess.CompletedProcess(argv,0,json.dumps(hello),P.META+json.dumps(meta)+'\n')

def graph(n=3):
    configured=[{'id':'a','role':'lead','host':'local','repo':'~/lead'}]
    configured += [{'id':chr(97+i),'role':'packer','host':'brenden@mini'+str(i),'ssh':'brenden@mini'+str(i),'repo':'~/cv3','peer':'169.254.1.'+str(i+1)+':5560'} for i in range(1,n)]
    nodes=[dict(inventory('169.254.1.'+str(i+1),c['id']+'.local'),id=c['id'],label=c['id'],offline=False) for i,c in enumerate(configured)]
    for node in nodes:node['routes']=[{'address':other['interfaces'][0]['addresses'][0],'interface':'en2'} for other in nodes if node['id']!=other['id']]
    snap={'observed_at':100,'read_only':True,'nodes':nodes,'graph':D.candidate_graph(nodes)}
    def probe(source,edge,identity):return {'status':'verified','identity_verified':True,'reachable':True,'transport_bound':True,'bound_ifindex':5,'latency_ms':1.2,'checked_at':100,'source_address':edge['source_address']}
    with mock.patch.object(D.time,'time',return_value=100):snap=D.validate_graph(snap,configured,probe=probe)
    return configured,snap

class BoundProbeTests(unittest.TestCase):
    def call(self,run=successful_run,collect=None,**kw):
        with mock.patch.object(P.secrets,'token_hex',return_value='1'*32):
            return P.local_probe(EDGE,IDENTITY,run=run,collect=collect or (lambda _:inventory(EDGE['source_address'])),platform='darwin',**kw)
    def test_success_identity_reachability_latency(self):
        r=self.call();self.assertEqual(r['status'],'verified');self.assertTrue(r['identity_verified']);self.assertTrue(r['reachable']);self.assertGreaterEqual(r['latency_ms'],0);self.assertEqual(r['tcp_connect_ms'],0.2)
    def test_strict_ssh_has_no_mux_config_or_trust_fallback(self):
        argv=P.ssh_argv('en2','169.254.1.1','169.254.1.2',IDENTITY,'1'*32)
        for value in ['StrictHostKeyChecking=yes','UpdateHostKeys=no','ControlPath=none','ControlMaster=no','ClearAllForwardings=yes','ForwardAgent=no','PermitLocalCommand=no','HostKeyAlias=100.64.1.2','BatchMode=yes']:
            self.assertIn(value,argv)
        self.assertEqual(argv[1:3],['-F','/dev/null']);self.assertTrue(any(a.startswith('ProxyCommand=') and '--transport en2 169.254.1.1 169.254.1.2' in a for a in argv));self.assertNotIn('5560',' '.join(argv))
    def test_unsupported_platform_never_runs_unbound(self):
        run=mock.Mock();r=P.local_probe(EDGE,IDENTITY,run=run,platform='linux');self.assertEqual(r['status'],'unverified');run.assert_not_called()
    def test_route_change_before_skips_probe(self):
        run=mock.Mock();inv=inventory(EDGE['source_address']);inv['routes'][0]['interface']='en0';r=self.call(run,lambda _:inv);self.assertEqual(r['status'],'failed');run.assert_not_called()
    def test_route_change_after_fails_closed(self):
        inv=inventory(EDGE['source_address']);bad=copy.deepcopy(inv);bad['routes'][0]['interface']='en0';collect=mock.Mock(side_effect=[inv,bad]);run=mock.Mock(side_effect=successful_run);r=self.call(run,collect);self.assertEqual(r['status'],'failed');self.assertEqual(run.call_count,1)
    def test_source_address_change_fails_closed(self):
        self.assertEqual(self.call(collect=lambda _:inventory('169.254.9.9'))['status'],'failed')
    def test_nonce_mismatch(self):
        def run(*a,**k):
            r=successful_run(*a,**k);j=json.loads(r.stdout);j['nonce']='wrong';r.stdout=json.dumps(j);return r
        self.assertEqual(self.call(run)['status'],'failed')
    def test_hostname_mismatch(self):
        def run(*a,**k):
            r=successful_run(*a,**k);j=json.loads(r.stdout);j['hostname']='forged';r.stdout=json.dumps(j);return r
        self.assertEqual(self.call(run)['status'],'failed')
    def test_wrong_server_endpoint(self):
        def run(*a,**k):
            r=successful_run(*a,**k);j=json.loads(r.stdout);j['connection']='192.168.1.1 123 169.254.1.2 22';r.stdout=json.dumps(j);return r
        self.assertEqual(self.call(run)['status'],'failed')
    def test_missing_bound_transport_evidence(self):
        def run(*a,**k):r=successful_run(*a,**k);r.stderr='';return r
        self.assertEqual(self.call(run)['status'],'failed')
    def test_unknown_host_key_is_unverified_no_enrollment(self):
        def run(*a,**k):r=successful_run(*a,**k);r.returncode=255;r.stderr+='No ED25519 host key is known for alias and strict checking.\n';return r
        r=self.call(run);self.assertEqual(r['status'],'unverified');self.assertTrue(r['reachable'])
    def test_changed_host_key_is_failed(self):
        def run(*a,**k):r=successful_run(*a,**k);r.returncode=255;r.stderr+='REMOTE HOST IDENTIFICATION HAS CHANGED';return r
        self.assertEqual(self.call(run)['status'],'failed')
    def test_timeout_no_retry(self):
        run=mock.Mock(side_effect=subprocess.TimeoutExpired('ssh',8));self.assertEqual(self.call(run)['status'],'failed');self.assertEqual(run.call_count,1)
    def test_public_destination_rejected(self):
        with self.assertRaises(ValueError):P.ssh_argv('en2','169.254.1.1','8.8.8.8',IDENTITY,'1'*32)
    def test_identity_anchor_configured_not_tb_ip(self):
        self.assertEqual(P.identity_for({'host':'u@management'},inventory('169.254.1.2'))['alias'],'management')
        self.assertEqual(P.identity_for({'host':'local'},inventory('169.254.1.1','lead.local'))['alias'],'lead.local')
    def test_invalid_identity_anchor(self):
        with self.assertRaises(ValueError):P.identity_for({'host':'-oProxyCommand=bad'},inventory('169.254.1.2'))
    def test_remote_probe_strict_management_and_correct_repo(self):
        def run(argv,**kw):
            self.assertIn('StrictHostKeyChecking=yes',argv);self.assertIn('UpdateHostKeys=no',argv);self.assertIn('~/cv3',argv[-1]);self.assertNotIn('dev/caravan',argv[-1]);self.assertEqual(kw['timeout'],42)
            return subprocess.CompletedProcess(argv,0,json.dumps({'status':'unverified'}),'')
        self.assertEqual(P.probe_edge({'host':'u@mini','repo':'~/cv3'},EDGE,IDENTITY,run=run)['status'],'unverified')
    def test_transport_kernel_bound_before_connect(self):
        sock=mock.MagicMock();sock.__enter__.return_value=sock;sock.getsockopt.return_value=5;sock.getsockname.return_value=('169.254.1.1',123);sock.getpeername.return_value=('169.254.1.2',22);sock.recv.return_value=b''
        with mock.patch.object(P.socket,'if_nametoindex',return_value=5),mock.patch.object(P.select,'select',return_value=([sock],[],[])),redirect_stderr(io.StringIO()) as err:
            P.transport('en2','169.254.1.1','169.254.1.2',sock_factory=lambda *a:sock,platform='darwin')
        sock.setsockopt.assert_called_once_with(P.socket.IPPROTO_IP,getattr(P.socket,'IP_BOUND_IF',25),5);sock.bind.assert_called_once_with(('169.254.1.1',0));sock.connect.assert_called_once_with(('169.254.1.2',22));self.assertIn('bound_ifindex',err.getvalue())
        names=[c[0] for c in sock.mock_calls];self.assertLess(names.index('setsockopt'),names.index('connect'))
    def test_binding_failure_never_connects(self):
        sock=mock.MagicMock();sock.__enter__.return_value=sock;sock.getsockopt.return_value=0
        with mock.patch.object(P.socket,'if_nametoindex',return_value=5),self.assertRaises(ValueError):P.transport('en2','169.254.1.1','169.254.1.2',sock_factory=lambda *a:sock,platform='darwin')
        sock.connect.assert_not_called()
    def test_transport_byte_budget(self):
        sock=mock.MagicMock();sock.__enter__.return_value=sock;sock.getsockopt.return_value=5;sock.getsockname.return_value=('169.254.1.1',1);sock.getpeername.return_value=('169.254.1.2',22);sock.recv.return_value=b'x'*(P.MAX_BYTES+1)
        with mock.patch.object(P.socket,'if_nametoindex',return_value=5),mock.patch.object(P.select,'select',return_value=([sock],[],[])),redirect_stderr(io.StringIO()),self.assertRaisesRegex(ValueError,'byte budget'):
            P.transport('en2','169.254.1.1','169.254.1.2',sock_factory=lambda *a:sock,platform='darwin')
    def test_transport_deadline(self):
        sock=mock.MagicMock();sock.__enter__.return_value=sock;sock.getsockopt.return_value=5;sock.getsockname.return_value=('169.254.1.1',1);sock.getpeername.return_value=('169.254.1.2',22)
        with mock.patch.object(P.socket,'if_nametoindex',return_value=5),mock.patch.object(P.time,'monotonic',side_effect=[0,0,7]),redirect_stderr(io.StringIO()),self.assertRaisesRegex(TimeoutError,'budget expired'):
            P.transport('en2','169.254.1.1','169.254.1.2',sock_factory=lambda *a:sock,platform='darwin')
    def test_no_worker_or_route_mutation_hooks(self):
        src=Path(P.__file__).read_text()
        for word in ('models/load','models/stop','kickstart','sudo','StrictHostKeyChecking=no','FrontClient'):self.assertNotIn(word,src)

class VerifiedPlanTests(unittest.TestCase):
    def test_three_minis_preserve_order_and_port(self):
        cfg,s=graph();p=D.suggested_plan(cfg,s,now=100);self.assertEqual(p['order'],['b','c','a']);self.assertTrue(p['matches_current_config']);self.assertTrue(p['preview_only']);self.assertFalse(p['apply_supported']);self.assertEqual(p['nodes'][1]['upstream_peer'],'169.254.1.2:5560');self.assertEqual(p['nodes'][-1]['peer'],'169.254.1.3:5560')
    def test_two_minis_only_required_direction_needed(self):
        cfg,s=graph(2);s['graph']['edges']=[e for e in s['graph']['edges'] if e['source']=='a'];self.assertTrue(D.suggested_plan(cfg,s,now=100)['matches_current_config'])
    def test_n_minis(self):
        cfg,s=graph(7);self.assertEqual(len(D.suggested_plan(cfg,s,now=100)['nodes']),7)
    def test_expired_edge_readout_is_unverified(self):
        cfg,s=graph(2);out=D.fresh_snapshot(s,now=131)
        self.assertTrue(all(e['status']=='unverified' for e in out['graph']['edges']));self.assertTrue(all(e['status']=='verified' for e in s['graph']['edges']))
        self.assertEqual(out['graph']['validation_counts']['unverified'],2)
    def test_stale_graph_rejected(self):
        cfg,s=graph()
        with self.assertRaisesRegex(ValueError,'expired'):D.suggested_plan(cfg,s,now=131)
    def test_stale_edge_rejected(self):
        cfg,s=graph();s['graph']['edges'][0]['checked_at']=60
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_unverified_edge_no_other_network_fallback(self):
        cfg,s=graph();s['graph']['edges'][0]['status']='unverified'
        with self.assertRaisesRegex(ValueError,'no fallback'):D.suggested_plan(cfg,s,now=100)
    def test_lead_preflight_edge_required_not_just_chain(self):
        cfg,s=graph();s['graph']['edges']=[e for e in s['graph']['edges'] if not(e['source']=='a' and e['target']=='b')]
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_no_mixed_addresses_for_same_peer(self):
        cfg,s=graph();next(e for e in s['graph']['edges'] if e['source']=='c' and e['target']=='b')['address']='169.254.8.8'
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_plan_refuses_missing_kernel_binding_evidence(self):
        cfg,s=graph(2);s['graph']['edges'][0].pop('transport_bound')
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_no_implicit_missing_node(self):
        cfg,s=graph();s['graph']['node_ids'].pop()
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_no_duplicate_or_missing_lead(self):
        cfg,s=graph();cfg[1]['role']='lead'
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_dynamic_current_en2_config_matches(self):
        cfg,s=graph(2);cfg[1].update(peer='ssh+tb://brenden@mini1/en2:5560',listen='tb://en2:5560');self.assertTrue(D.suggested_plan(cfg,s,now=100)['matches_current_config'])
    def test_endpoint_trust_target_cannot_change(self):
        cfg,s=graph(2);cfg[1]['peer']='ssh+tb://u@evil/en2:5560'
        with self.assertRaisesRegex(ValueError,'identity differs'):D.suggested_plan(cfg,s,now=100)
    def test_endpoint_port_not_guessed(self):
        cfg,s=graph(2);cfg[1]['peer']='169.254.1.2'
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_duplicate_link_evidence_rejected(self):
        cfg,s=graph(2);s['graph']['edges'].append(copy.deepcopy(s['graph']['edges'][0]))
        with self.assertRaises(ValueError):D.suggested_plan(cfg,s,now=100)
    def test_bad_verified_result_is_not_verified(self):
        cfg,s=graph(2)
        bad=lambda *a:{'status':'verified','identity_verified':True,'reachable':True,'transport_bound':True,'bound_ifindex':5,'latency_ms':float('nan'),'source_address':EDGE['source_address']}
        self.assertTrue(all(e['status']=='unverified' for e in D.validate_graph(s,cfg,probe=bad)['graph']['edges']))
    def test_unbound_success_cannot_be_marked_verified(self):
        cfg,s=graph(2)
        r=D.validate_graph(s,cfg,probe=lambda source,e,identity:{'status':'verified','identity_verified':True,'reachable':True,'latency_ms':1,'source_address':e['source_address'],'checked_at':100})
        self.assertTrue(all(e['status']=='unverified' for e in r['graph']['edges']))
    def test_probe_budget_bounds_attempts(self):
        cfg,s=graph(4);probe=mock.Mock(return_value={'status':'unverified'})
        with mock.patch.object(D,'MAX_PROBES',2):r=D.validate_graph(s,cfg,probe=probe)
        self.assertEqual(probe.call_count,2);self.assertTrue(any('budget' in e['reason'] for e in r['graph']['edges']))
    def test_budget_prioritizes_existing_pipeline_requirements(self):
        cfg,s=graph(3)
        def probe(source,edge,identity):return {'status':'verified','identity_verified':True,'reachable':True,'transport_bound':True,'bound_ifindex':5,'latency_ms':1,'source_address':edge['source_address'],'checked_at':100}
        with mock.patch.object(D,'MAX_PROBES',3),mock.patch.object(D.time,'time',return_value=100):
            out=D.validate_graph(s,cfg,probe=probe)
        self.assertTrue(D.suggested_plan(cfg,out,now=100)['matches_current_config'])
    def test_probe_cannot_redefine_endpoint(self):
        cfg,s=graph(2);r=D.validate_graph(s,cfg,probe=lambda *a:{'status':'failed','address':'8.8.8.8','source':'evil','reason':'failed'});self.assertEqual(r['graph']['edges'][0]['source'],'a');self.assertEqual(r['graph']['edges'][0]['address'],'169.254.1.2')
    def test_preview_requires_opt_in_and_same_validation_token(self):
        cfg,s=graph(2);c=D.Controller();c.cached=s;c.key=json.dumps(cfg,sort_keys=True);c.until=D.time.monotonic()+30
        with mock.patch.object(D.time,'time',return_value=100):
            for opt,token in [(False,s['validation_id']),(True,'wrong'),(True,None)]:
                with self.assertRaises(ValueError):c.plan(cfg,opt_in=opt,validation_id=token)
            self.assertTrue(c.plan(cfg,opt_in=True,validation_id=s['validation_id'])['preview_only'])
    def test_validate_cache_single_flight_no_repeat(self):
        cfg,s=graph(2);c=D.Controller()
        with mock.patch.object(D,'discover',return_value=s),mock.patch.object(D,'validate_graph',return_value=s) as validate:
            c.validate(cfg);r=c.validate(cfg);self.assertEqual(validate.call_count,1);r['graph']['edges'].clear();self.assertTrue(c.cached['graph']['edges'])
    def test_preview_expired_controller_rejected(self):
        cfg,s=graph(2);c=D.Controller();c.cached=s;c.key=json.dumps(cfg,sort_keys=True);c.until=0
        with self.assertRaises(ValueError):c.plan(cfg,opt_in=True,validation_id=s['validation_id'])

class ValidationApiTests(unittest.TestCase):
    def handler(self):
        import web_server
        app=types.SimpleNamespace(configured_nodes=mock.Mock(return_value=[{'id':'trusted'}]),thunderbolt_discovery=mock.Mock(),mgr=mock.Mock())
        h=object.__new__(web_server.make_handler(app));h._json=mock.Mock();return app,h
    def test_api_validate_configured_only(self):
        app,h=self.handler();h.path='/api/thunderbolt/validate';h._body=lambda:{};h.do_POST();app.thunderbolt_discovery.validate.assert_called_once_with([{'id':'trusted'}]);app.mgr.assert_not_called()
    def test_api_rejects_request_supplied_targets_or_graph(self):
        for path,body in [('/api/thunderbolt/validate',{'host':'evil'}),('/api/thunderbolt/plan',{'opt_in':True,'graph':{}})]:
            app,h=self.handler();h._api_thunderbolt(path,body);self.assertEqual(h._json.call_args.args[0],400);app.thunderbolt_discovery.validate.assert_not_called();app.thunderbolt_discovery.plan.assert_not_called()
    def test_api_plan_explicit_token_and_opt_in(self):
        app,h=self.handler();h._api_thunderbolt('/api/thunderbolt/plan',{'opt_in':True,'validation_id':'token'});app.thunderbolt_discovery.plan.assert_called_once_with([{'id':'trusted'}],opt_in=True,validation_id='token')
    def test_api_plan_failure_no_fallback(self):
        app,h=self.handler();app.thunderbolt_discovery.plan.side_effect=ValueError('stale');h._api_thunderbolt('/api/thunderbolt/plan',{'opt_in':True,'validation_id':'token'});self.assertEqual(h._json.call_args.args[0],409);self.assertFalse(h._json.call_args.args[1]['fallback']);app.thunderbolt_discovery.validate.assert_not_called()
    def test_no_apply_endpoint(self):
        app,h=self.handler();h.path='/api/thunderbolt/apply';h._body=lambda:{};h.do_POST();self.assertEqual(h._json.call_args.args[0],404);self.assertEqual(app.mgr.mock_calls,[]);self.assertFalse(hasattr(D.Controller(),'apply'))

class ValidationUiTests(unittest.TestCase):
    def run_case(self,name):
        r=subprocess.run(['node',str(ROOT/'tests/js/thunderbolt_harness.js'),name],capture_output=True,text=True,timeout=10);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
for case in ('validate','no_opt_in','missing_graph','preview','preview_error','preview_expired','expired','failed','unverified_reachable'):
    setattr(ValidationUiTests,'test_'+case,lambda self,name=case:self.run_case(name))
