import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'agent'),str(Path(__file__).resolve().parents[1]/'proxy')]
import gguf_share_download as D
import gguf_shards as S
import gguf_runtime as R


def string(s):
    b=s.encode();return struct.pack('<Q',len(b))+b


def fixture(arch='qwen2',large=False,vocab=False):
    names=['token_embd.weight','blk.0.weight','blk.1.weight','blk.2.weight','blk.3.weight','output_norm.weight','output.weight']
    kv=[string('general.architecture')+struct.pack('<I',8)+string(arch),string(arch+'.block_count')+struct.pack('<II',4,4)]
    if vocab:kv.append(string('tokenizer.ggml.tokens')+struct.pack('<IIQ',9,8,20000)+b''.join(string('token-'+str(i)) for i in range(20000)))
    h=b'GGUF'+struct.pack('<IQQ',3,len(names),len(kv))+b''.join(kv)
    off=0;payload=b''
    for i,n in enumerate(names):
        size=8<<20 if i==0 and large else 32
        h+=string(n)+struct.pack('<IQIQ',1,size//4,0,off)
        payload+=bytes([i+1])*size;off+=size
    h+=b'\0'*(-len(h)%32)
    return h+payload,len(h)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.env=patch.dict(os.environ,HOME=str(self.home));self.env.start()
        self.blob,self.header=fixture();self.calls=[];self.break_stream=False
        self.src=dict(repo_id='test/model',filename='model.gguf',revision='a'*40,source_bytes=len(self.blob),source_sha256=hashlib.sha256(self.blob).hexdigest())
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def opener(self,req,timeout=90):
        a,b=map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',req.get_header('Range')).groups());self.calls.append((a,b))
        data=self.blob[a:b+1]
        if self.break_stream and a==self.header:
            outer=self
            class Interrupted(io.BytesIO):
                def read(self,n=-1):
                    if self.tell()>=4<<20:outer.break_stream=False;raise OSError('interrupted')
                    return super().read(n)
            r=Interrupted(data)
        else:r=io.BytesIO(data)
        r.status=206;r.headers={'Content-Range':f'bytes {a}-{b}/{len(self.blob)}'}
        return r
    def plan(self,counts=None):
        f=D.HeaderReader(self.src,self.opener);p=dict(self.src,**D.parse_header(f,{0:(1,4)}))
        self.assertTrue(all(a+n<=self.header for a,n in f.requests),f.requests)
        p.update(shares=counts or [1,1],node_ids=['n'+str(i) for i in range(len(counts or [1,1]))],header_sha256=hashlib.sha256(self.blob[:self.header]).hexdigest(),plan_id='b'*24)
        own=S.owners(p['n_layers'],p['shares'],[t['name'] for t in p['tensors']])
        for t in p['tensors']:t['owner']=own[t['name']]
        return p
    def request(self,p,i=0):return dict(manifest=p,stage_index=i,dest=D.stage_root(p,i),format=D.FORMAT)
    def test_header_read_ahead_never_fetches_weights(self):self.plan()
    def test_large_vocab_metadata_only(self):
        self.blob,self.header=fixture(vocab=True);self.src.update(source_bytes=len(self.blob),source_sha256=hashlib.sha256(self.blob).hexdigest());self.plan()
        self.assertLess(len(self.calls),100)
    def test_reject_architecture(self):
        self.blob,self.header=fixture(arch='other');self.src['source_bytes']=len(self.blob)
        with self.assertRaises(ValueError):self.plan()
    def test_immutable_url(self):
        p=dict(self.src,revision='main')
        with self.assertRaises(ValueError):D.source_url(p)
    def test_source_path_escape(self):
        with self.assertRaises(ValueError):D.source_url(dict(self.src,filename='../key.gguf'))
    def test_whole_file_response_refused(self):
        def bad(req,timeout):r=self.opener(req,timeout);r.status=200;return r
        with self.assertRaises(ValueError):D.read_range(self.src,0,4,bad)
    def test_changed_content_range_refused(self):
        def bad(req,timeout):r=self.opener(req,timeout);r.headers['Content-Range']='bytes 0-3/9999';return r
        with self.assertRaises(ValueError):D.read_range(self.src,0,4,bad)
    def test_compression_refused(self):
        def bad(req,timeout):r=self.opener(req,timeout);r.headers['Content-Encoding']='gzip';return r
        with self.assertRaises(ValueError):D.read_range(self.src,0,4,bad)
    def test_short_range_refused(self):
        def bad(req,timeout):r=self.opener(req,timeout);r.truncate(2);return r
        with self.assertRaises(ValueError):D.read_range(self.src,0,4,bad)
    def test_normalize_fractional_shares(self):self.assertEqual(D.shares([0.5,1.5]),[1,3])
    def test_bad_shares(self):
        for x in ([],[True],[0],[float('nan')],[-1],['2']):
            with self.subTest(x=x),self.assertRaises(ValueError):D.shares(x)
    def test_overlap_refused(self):
        p=self.plan();p['tensors'][1]['offset']=p['tensors'][0]['offset']
        with self.assertRaises(ValueError):D.validate(p,0)
    def test_foreign_owner_refused(self):
        p=self.plan();p['tensors'][0]['owner']=1
        with self.assertRaises(ValueError):D.validate(p,0)
    def test_arbitrary_destination_refused(self):
        r=self.request(self.plan());r['dest']=str(self.home/'other')
        with self.assertRaises(ValueError):D.status(r)
    def test_linked_stage_refused(self):
        r=self.request(self.plan());root=Path(r['dest']).expanduser();root.parent.mkdir(parents=True);target=self.home/'target';target.mkdir();root.symlink_to(target)
        with self.assertRaises(ValueError):D.status(r)
    @unittest.skipUnless(shutil.which('cc'),'native compiler required')
    def test_each_stage_fetches_only_its_own_ranges_and_finalizes(self):
        for counts in ([1],[1,1],[1,2,1]):
            p=self.plan(counts);p['plan_id']=hashlib.sha256(str(counts).encode()).hexdigest()[:24];receipts=[]
            for i in range(len(counts)):
                self.calls=[];r=self.request(p,i);receipt=D.fetch(r,self.opener);receipts.append(receipt)
                wanted={(t['offset'],t['offset']+t['size']-1) for t in p['tensors'] if t['owner']==i}
                self.assertTrue(all((a,b)==(0,self.header-1) or (a,b) in wanted for a,b in self.calls),self.calls)
            for i in range(len(counts)):
                out=D.finalize(self.request(p,i),receipts);self.assertEqual(out['stage_index'],i)
    def test_missing_stage_receipt_refused(self):
        with self.assertRaises(ValueError):D.finalize(self.request(self.plan()),[])
    @unittest.skipUnless(shutil.which('cc'),'native compiler required')
    def test_resume_verified_prefix_only(self):
        self.blob,self.header=fixture(large=True);self.src.update(source_bytes=len(self.blob),source_sha256=hashlib.sha256(self.blob).hexdigest());p=self.plan();r=self.request(p)
        self.break_stream=True
        with self.assertRaises(OSError):D.fetch(r,self.opener)
        self.calls=[];out=D.fetch(r,self.opener)
        self.assertIn((self.header+(4<<20),self.header+(8<<20)-1),self.calls)
        self.assertLess(out['downloaded_bytes'],8<<20)
    @unittest.skipUnless(shutil.which('cc'),'native compiler required')
    def test_corrupt_resume_prefix_refused(self):
        self.blob,self.header=fixture(large=True);self.src.update(source_bytes=len(self.blob),source_sha256=hashlib.sha256(self.blob).hexdigest());p=self.plan();r=self.request(p);self.break_stream=True
        with self.assertRaises(OSError):D.fetch(r,self.opener)
        part=next((D._root(r)/'partials').glob('*.part'))
        with part.open('r+b') as f:f.write(b'BAD')
        with self.assertRaises(ValueError):D.fetch(r,self.opener)
    @unittest.skipUnless(shutil.which('cc'),'native compiler required')
    def test_repeat_fetch_downloads_zero_weights(self):
        r=self.request(self.plan());D.fetch(r,self.opener);self.calls=[];out=D.fetch(r,self.opener)
        self.assertEqual(out['downloaded_bytes'],0);self.assertEqual(self.calls,[])
    def test_runtime_build_finds_homebrew_under_launchd_path(self):
        base=self.home/'.caravan/runtimes/gguf-shards'/R.PIN
        base.mkdir(parents=True);(base/'caravan-shards-version').write_text(R.MARKER)
        expected=base/'build/bin'
        with patch.dict(os.environ,PATH='/usr/bin:/bin'),patch.object(R,'current',side_effect=[FileNotFoundError(),FileNotFoundError(),expected]),patch.object(R.shutil,'which',return_value='/opt/homebrew/bin/cmake') as which,patch.object(R.subprocess,'run') as run:
            self.assertEqual(R.ensure(),expected)
            for call in which.call_args_list:self.assertIn('/opt/homebrew/bin',call.kwargs['path'].split(os.pathsep))
            self.assertEqual([c.kwargs['timeout'] for c in run.call_args_list],[300,1800])
            for call in run.call_args_list:self.assertIn('/opt/homebrew/bin',call.kwargs['env']['PATH'].split(os.pathsep))
            self.assertEqual(os.environ['PATH'],'/usr/bin:/bin')
    def test_missing_build_prerequisite_fails_before_source_fetch(self):
        with patch.object(R,'current',side_effect=FileNotFoundError()),patch.object(R.shutil,'which',side_effect=lambda tool,**kw:'/usr/bin/git' if tool=='git' else None),patch.object(R.subprocess,'run') as run:
            with self.assertRaisesRegex(FileNotFoundError,'needs cmake'):R.ensure()
            run.assert_not_called()
    def test_wrong_runtime_marker_refused(self):
        with patch.dict(os.environ,CARAVAN_GGUF_SHARD_BIN=str(self.home/'build/bin')):
            with self.assertRaises(FileNotFoundError):R.current()
            with patch.object(R.subprocess,'run') as run:
                with self.assertRaises(FileNotFoundError):R.ensure()
                run.assert_not_called()

    @unittest.skipUnless(shutil.which('cc'),'native compiler required')
    def test_balance_fetches_only_missing_local_ranges(self):
        homes=[self.home/'mac0',self.home/'mac1'];p=self.plan();receipts=[]
        for i,home in enumerate(homes):
            home.mkdir()
            with patch.dict(os.environ,HOME=str(home)):receipts.append(D.fetch(self.request(p,i),self.opener))
        for i,home in enumerate(homes):
            with patch.dict(os.environ,HOME=str(home)):D.finalize(self.request(p,i),receipts)
        with patch.dict(os.environ,HOME=str(homes[0])):
            oldroot=D._root(self.request(p));changed=json.loads((oldroot/'source-plan.json').read_text())
            self.assertTrue(all(t.get('sha256') and t.get('key') for t in changed['tensors']))
            changed.update(shares=[2,1],plan_id='c'*24)
            owners=S.owners(changed['n_layers'],changed['shares'],[t['name'] for t in changed['tensors']])
            for t in changed['tensors']:t['owner']=owners[t['name']]
            request=self.request(changed);before=D.status(request)
            self.assertEqual(before['download_bytes'],32);self.assertFalse(before['assembled'])
            self.calls=[];out=D.fetch(request,self.opener)
            weights=[(a,b) for a,b in self.calls if a>=self.header]
            old_names={t['name'] for t in p['tensors'] if t['owner']==0}
            missing=next(t for t in changed['tensors'] if t['owner']==0 and t['name'] not in old_names)
            self.assertEqual(weights,[(missing['offset'],missing['offset']+31)])
            self.assertEqual(out['downloaded_bytes'],self.header+32)



class WebShareTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        import web_gguf_shares as W
        self.W=W;self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.reg=patch.object(W,'REGISTRY',self.home/'registry');self.reg.start()
        self.nodes=[dict(id='n0',role='lead',label='1st node',host='local'),dict(id='n1',role='packer',label='2nd node',host='trusted-peer')]
        self.app=SimpleNamespace(configured_nodes=lambda:self.nodes,nodes=lambda:dict(nodes=[dict(n,ram=dict(available_gb=10,total_gb=16)) for n in self.nodes]),mgr=SimpleNamespace(repo='/repo',python=sys.executable))
        import web_picker, gguf_runtime
        self.blobs=patch.object(web_picker,'_fetch_repo_blobs',return_value=dict(gguf_files=[dict(rfilename='model.gguf',size=15_000_000_000)]));self.blobs.start();self.addCleanup(self.blobs.stop)
        self.runtime=patch.object(gguf_runtime,'current',return_value=Path('/custom/bin'));self.runtime.start();self.addCleanup(self.runtime.stop)
    def tearDown(self):self.reg.stop();self.tmp.cleanup()
    def handler(self):
        import web_server
        h=object.__new__(web_server.make_handler(self.app));h._json=lambda code,out:(code,out)
        return h
    def test_picker_default_uses_own_shares(self):
        import web_files,web_picker
        with patch.object(self.W,'preview',return_value=dict(safe=True)) as prepare,patch.object(web_files,'start',return_value=dict(id='share-job')) as start,patch.object(web_picker,'start_download') as legacy:
            status,out=self.handler()._api_picker_download(dict(repo_id='test/model',source='gguf',gguf_file='model.gguf'))
        self.assertEqual(status,200);self.assertEqual(out['job']['id'],'share-job');prepare.assert_called_once();start.assert_called_once();legacy.assert_not_called()
    def test_string_false_cannot_select_full_fallback(self):
        import web_files
        with patch.object(self.W,'preview',return_value=dict(safe=True)) as prepare,patch.object(web_files,'start',return_value=dict(id='share-job')):
            status,_=self.handler()._api_picker_download(dict(repo_id='test/model',source='gguf',gguf_file='model.gguf',full_file_fallback='false'))
        self.assertEqual(status,200);prepare.assert_called_once()
    def test_share_error_never_silently_uses_legacy(self):
        import web_picker
        with patch.object(self.W,'preview',side_effect=ValueError('Range unsupported')),patch.object(web_picker,'start_download') as legacy:
            status,out=self.handler()._api_picker_download(dict(repo_id='test/model',source='gguf',gguf_file='model.gguf'))
        self.assertEqual(status,400);self.assertIn('Range',out['error']);legacy.assert_not_called()
    def test_unsafe_plan_does_not_start_any_download(self):
        import web_files
        with patch.object(self.W,'preview',return_value=dict(safe=False)),patch.object(web_files,'start') as start:
            status,_=self.handler()._api_picker_download(dict(repo_id='test/model',source='gguf',gguf_file='model.gguf'))
        self.assertEqual(status,409);start.assert_not_called()
    def test_duplicate_physical_nodes_rejected(self):
        self.nodes[1]['host']='local'
        with self.assertRaises(ValueError):self.W.nodes_for(self.app,{})
    def test_unknown_node_rejected(self):
        with self.assertRaises(ValueError):self.W.nodes_for(self.app,dict(node_ids=['not-configured']))
    def test_import_does_not_accept_arbitrary_path(self):
        for name in ('../file','..','/tmp/file',''):
            with self.subTest(name=name),self.assertRaises(ValueError):self.W.import_existing(self.app,dict(tree=name))
    def test_registry_shard_entry_includes_picker_and_restore_plan(self):
        root=self.home/'stage';root.mkdir();(root/'manifest.json').write_text('{}')
        p=dict(repo_id='test/model',filename='model.gguf',revision='a'*40,source_sha256='b'*64,source_bytes=1000,node_ids=['n0','n1'],shares=[1,1],plan_id='c'*24)
        r=self.W.save_deployment(p,[str(root),'~/.caravan/remote-stage'])
        entry=self.W.entries(self.nodes,r['model_id'])[0]
        self.assertTrue(entry['usable']);self.assertTrue(entry['sharded']);self.assertTrue(entry['current'])
        self.assertEqual(entry['gguf_deployment']['node_ids'],['n0','n1'])
        self.assertIn('each keeps only its part',entry['placement_options'][0]['label'])
    def test_offline_node_disables_picker_entry(self):
        root=self.home/'stage';root.mkdir();(root/'manifest.json').write_text('{}')
        p=dict(repo_id='test/model',filename='model.gguf',revision='a'*40,source_sha256='b'*64,source_bytes=1000,node_ids=['n0','n1'],shares=[1,1],plan_id='c'*24)
        self.W.save_deployment(p,[str(root),'remote'])
        self.assertFalse(self.W.entries([self.nodes[0]])[0]['usable'])
    def test_cross_host_redirect_strips_authorization(self):
        from urllib.request import Request
        req=Request('https://huggingface.co/test',headers={'Authorization':'Bearer FAKE','Range':'bytes=0-3'})
        out=D.SourceRedirect().redirect_request(req,None,302,'',{},'https://cdn.hf.co/test')
        self.assertIsNone(out.get_header('Authorization'));self.assertEqual(out.get_header('Range'),'bytes=0-3')
    def test_insecure_redirect_rejected(self):
        from urllib.request import Request
        with self.assertRaises(ValueError):D.SourceRedirect().redirect_request(Request('https://huggingface.co/test'),None,302,'',{},'http://example.test/file')

    def test_same_model_shard_reload_is_busy_before_thread_starts(self):
        import web_workers
        m=web_workers.WorkerManager(state_dir=self.home/'state')
        model='gguf-shards/test/model/model.gguf'
        m._set(status='ready',model_id=model,lead_pid=123)
        entry=dict(id=model,source='gguf',sharded=True,lead_path=str(self.home/'model.cvgg'))
        with patch.object(m,'_deny_managed_service'),patch.object(web_workers.threading,'Thread') as thread:
            out=m.switch(model,entry=entry)
            self.assertEqual(out['status'],'starting_lead')
            self.assertEqual(out['model_id'],model)
            thread.return_value.start.assert_called_once()
    def test_saved_restore_uses_shard_model_and_exact_stage_order(self):
        import web_restore
        from types import SimpleNamespace
        entry=dict(id='gguf-shards/test/model/model.gguf',source='gguf',sharded=True,gguf_shares=[2,1],gguf_peer_files_ready=True,placement=dict(mode='split',node_ids=['n0','n1']))
        out=web_restore.request_for(SimpleNamespace(),entry,dict(split=True,gguf=dict(nodes=['n0','n1']),settings={}),self.nodes)
        self.assertEqual(out['model_id'],entry['id']);self.assertEqual(out['engine'],'gguf');self.assertEqual(out['counts'],[2,1]);self.assertEqual(out['node_ids'],['n0','n1']);self.assertTrue(out['balance'])
    def test_tunnel_reuses_trusted_identity_on_verified_thunderbolt(self):
        import service_endpoints
        n=dict(ssh='u@trusted',peer='ssh+tb://u@trusted/en2:5560')
        with patch.object(service_endpoints,'resolve',return_value='169.254.1.2:5560'):
            args=self.W.tunnel_args(n,50062)
        self.assertIn('HostName=169.254.1.2',args);self.assertIn('HostKeyAlias=trusted',args);self.assertIn('StrictHostKeyChecking=yes',args)
    def test_no_lan_fallback_if_thunderbolt_discovery_fails(self):
        import service_endpoints
        with patch.object(service_endpoints,'resolve',side_effect=ValueError('link down')):
            with self.assertRaises(ValueError):self.W.tunnel_args(dict(ssh='u@trusted',peer='ssh+tb://u@trusted/en2:5560'),50062)
    def test_conflicting_thunderbolt_identity_refused(self):
        import service_endpoints
        with patch.object(service_endpoints,'resolve') as resolve:
            with self.assertRaises(ValueError):self.W.tunnel_args(dict(ssh='u@other',peer='ssh+tb://u@trusted/en2:5560'),50062)
        resolve.assert_not_called()


if __name__=='__main__':unittest.main()
