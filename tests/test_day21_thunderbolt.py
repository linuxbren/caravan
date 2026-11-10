"""Passive trusted Thunderbolt inventory/graph; never launch or modify routes."""
import concurrent.futures
import json
import subprocess
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'proxy'))
import thunderbolt_discovery as D
PORTS='Hardware Port: Thunderbolt 1\nDevice: en2\nHardware Port: Wi-Fi\nDevice: en1\nHardware Port: Thunderbolt 2\nDevice: en3\n'
IFCONFIG='en2: flags=8863<UP> mtu 1500\n\tinet 169.254.1.2 netmask 0xffff0000\n\tstatus: active\nen1: flags=8863<UP> mtu 1500\n\tinet 192.168.0.2 netmask 0xffffff00\n\tstatus: active\n'
def inventory(ip):
    return {'hostname':'test','interfaces':[{'interface':'en2','kind':'thunderbolt','members':[],'addresses':[ip]}],'routes':[]}

class DiscoveryTests(unittest.TestCase):
    def test_only_private_link_local(self):
        for ip in ('169.254.1.2','10.2.3.4','172.16.1.1','192.168.2.2'):self.assertEqual(D.private_ipv4(ip),ip)
        for ip in ('8.8.8.8','0.0.0.0','127.0.0.1','224.0.0.1','::1','fe80::1%en2','bad'):self.assertIsNone(D.private_ipv4(ip))
    def test_hardware_not_service_label(self):
        self.assertEqual([i['interface'] for i in D.parse_interfaces(PORTS,IFCONFIG)],['en2'])
        self.assertEqual(D.parse_interfaces(PORTS.replace('Thunderbolt 1','EXO Thunderbolt 1'),IFCONFIG),[])
    def test_inactive(self):
        self.assertEqual(D.parse_interfaces(PORTS,IFCONFIG.replace('status: active','status: inactive')),[])
    def test_public_address(self):
        self.assertEqual(D.parse_interfaces(PORTS,IFCONFIG.replace('169.254.1.2','8.8.8.8')),[])
    def test_verified_bridge(self):
        bridge='bridge0: flags=8863<UP> mtu 1500\n\tmember: en2 flags=3\n\tmember: en3 flags=3\n\tinet 169.254.2.3 netmask 0xffff0000\n\tstatus: active\n'
        out=D.parse_interfaces(PORTS,bridge);self.assertEqual(out[0]['kind'],'tb-only-bridge')
        self.assertEqual(out[0]['members'],['en2','en3'])
    def test_mixed_bridge_rejected(self):
        bridge='bridge0: flags=8863<UP>\n\tmember: en2 flags=3\n\tmember: en1 flags=3\n\tinet 10.2.3.4\n\tstatus: active\n'
        self.assertEqual(D.parse_interfaces(PORTS,bridge),[])
    def test_ipv6_is_not_silently_unscoped(self):
        self.assertEqual(D.parse_interfaces(PORTS,IFCONFIG.replace('inet 169.254.1.2 netmask 0xffff0000','inet6 fe80::123%en2 prefixlen 64')),[])
    def test_collect_runs_only_reads(self):
        calls=[]
        def run(argv,**kw):
            calls.append(argv)
            value=PORTS if 'networksetup' in argv[0] else IFCONFIG if 'ifconfig' in argv[0] else '  interface: en2\n'
            return subprocess.CompletedProcess(argv,0,value,'')
        out=D.collect_local(['169.254.2.3','8.8.8.8','169.254.2.3'],run=run)
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[1],['/sbin/ifconfig','-a'])
        self.assertEqual(calls[2],['/sbin/route','-n','get','169.254.2.3'])
        self.assertEqual(out['routes'],[{'address':'169.254.2.3','interface':'en2'}])
    def test_route_failure_is_unknown(self):
        def run(argv,**kw):return subprocess.CompletedProcess(argv,1 if 'route' in argv[0] else 0,PORTS if 'networksetup' in argv[0] else IFCONFIG,'')
        self.assertEqual(D.collect_local(['10.0.0.2'],run=run)['routes'][0]['interface'],None)
    def test_ssh_is_strict_and_fixed(self):
        def run(argv,**kw):
            self.assertIn('StrictHostKeyChecking=yes',argv);self.assertIn('BatchMode=yes',argv)
            self.assertEqual(argv[-2],'trusted-mini');self.assertIn('collect_local',argv[-1])
            return subprocess.CompletedProcess(argv,0,json.dumps(inventory('10.0.0.2')),'')
        D.inspect_node({'host':'trusted-mini','repo':'~/cv3'},['10.0.0.3'],run=run)
    def test_invalid_ssh_target(self):
        for target in ('-oProxyCommand=bad','host;bad','host/path','bad host'):
            with self.assertRaises(ValueError):D.inspect_node({'host':target},run=lambda *a,**k:self.fail('must not run'))
    def test_ssh_failure_no_fallback(self):
        run=mock.Mock(return_value=subprocess.CompletedProcess([],255,'','host key unknown'))
        with self.assertRaisesRegex(RuntimeError,'no trust/address fallback'):D.inspect_node({'host':'trusted'},run=run)
        self.assertEqual(run.call_count,1)
    def test_three_node_directed_graph(self):
        ns=[dict(inventory('169.254.1.'+str(i+1)),id='n'+str(i)) for i in range(3)]
        ns[0]['routes']=[{'address':'169.254.1.2','interface':'en2'}]
        ns[1]['routes']=[{'address':'169.254.1.3','interface':'en2'}]
        g=D.candidate_graph(ns);self.assertEqual([(e['source'],e['target']) for e in g['edges']],[('n0','n1'),('n1','n2')])
        self.assertFalse(g['automatic_routing']);self.assertTrue(all(not e['usable_for_routing'] for e in g['edges']))
    def test_wrong_source_route_does_not_make_edge(self):
        ns=[dict(inventory('169.254.1.1'),id='a'),dict(inventory('169.254.1.2'),id='b')]
        ns[0]['routes']=[{'address':'169.254.1.2','interface':'en1'}]
        self.assertEqual(D.candidate_graph(ns)['edges'],[])
    def test_arbitrary_n_two_passes(self):
        calls=[];nodes=[{'id':'n'+str(i),'host':'mini'+str(i)} for i in range(7)]
        def inspect(n,d):
            calls.append((n['id'],list(d)));out=inventory('169.254.1.'+str(int(n['id'][1:])+1));out['id']='forged'
            out['routes']=[{'address':a,'interface':'en2'} for a in d];return out
        out=D.discover(nodes,inspect=inspect);self.assertEqual(len(calls),14);self.assertEqual(len(out['graph']['edges']),42)
        self.assertEqual(out['nodes'][0]['id'],'n0');self.assertTrue(out['read_only'])
    def test_offline_node_diagnostic(self):
        def inspect(n,d):raise RuntimeError('unknown key')
        out=D.discover([{'id':'offline','host':'trusted'}],inspect=inspect)
        self.assertTrue(out['nodes'][0]['offline']);self.assertEqual(out['graph']['edges'],[])
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):D.discover([{'id':'n'},{'id':'n'}])
    def test_cache_does_not_repeat_discovery(self):
        c=D.Controller()
        with mock.patch.object(D,'discover',return_value={'read_only':True}) as d:
            c.snapshot([{'id':'a'}]);c.snapshot([{'id':'a'}]);self.assertEqual(d.call_count,1)
            c.snapshot([{'id':'b'}]);self.assertEqual(d.call_count,2)
            c.until=0;c.snapshot([{'id':'b'}]);self.assertEqual(d.call_count,3)
    def test_no_mutation_hooks_in_module(self):
        src=Path(D.__file__).read_text()
        for forbidden in ('models/load','models/stop','kickstart','route", "add','route\', \'add','socket.create_connection','StrictHostKeyChecking=no'):
            self.assertNotIn(forbidden,src)

    def test_malformed_inventory_fails_closed(self):
        for data in ({}, {'interfaces':[None],'routes':[]}, {'interfaces':[],'routes':[None]}):
            with self.assertRaises(ValueError):D.normalized_inventory(data)
    def test_duplicate_address_not_an_edge(self):
        ns=[dict(inventory('169.254.1.2'),id='a'),dict(inventory('169.254.1.2'),id='b')]
        ns[0]['routes']=[{'address':'169.254.1.2','interface':'en2'}]
        g=D.candidate_graph(ns);self.assertEqual(g['edges'],[]);self.assertEqual(g['ambiguous_addresses'],['169.254.1.2'])
    def test_api_uses_only_configured_nodes(self):
        import web_server
        app=types.SimpleNamespace(configured_nodes=mock.Mock(return_value=[{'id':'trusted'}]),thunderbolt_discovery=mock.Mock())
        app.thunderbolt_discovery.snapshot.return_value={'read_only':True}
        h=object.__new__(web_server.make_handler(app));h.path='/api/thunderbolt?host=evil&route=change';h._json=mock.Mock()
        h.do_GET();app.thunderbolt_discovery.snapshot.assert_called_once_with([{'id':'trusted'}]);h._json.assert_called_once_with(200,{'read_only':True})
    def test_api_failure_is_read_only(self):
        import web_server
        app=types.SimpleNamespace(configured_nodes=lambda:[],thunderbolt_discovery=mock.Mock())
        app.thunderbolt_discovery.snapshot.side_effect=ValueError('invalid config')
        h=object.__new__(web_server.make_handler(app));h.path='/api/thunderbolt';h._json=mock.Mock();h.do_GET()
        h._json.assert_called_once_with(503,{'error':'invalid config','read_only':True})

class DiscoveryUiTests(unittest.TestCase):
    def run_case(self, name):
        import shutil
        if not shutil.which('node'):self.skipTest('Node required for JS contract')
        r=subprocess.run(['node',str(ROOT/'tests/js/thunderbolt_harness.js'),name],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_explicit_get_only(self):self.run_case('success')
    def test_ui_failure_no_fallback(self):self.run_case('error')
