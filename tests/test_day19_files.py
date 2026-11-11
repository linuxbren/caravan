"""Day19 theme3: all disk/network/process fixtures are box-local or mocked."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'agent'), str(Path(__file__).resolve().parents[1]/'proxy')]
import model_files as M
import gguf_files as G
import mlx_split_fetch as F
import model_inventory as I
import web_files as WF
import web_catalog as C
import web_nodes as N
import web_picker as WP
import web_server as WS
import split_balance as B


def tensor_bytes():
    h=json.dumps({'w': {'dtype':'U8','shape':[4],'data_offsets':[0,4]}}).encode()
    return struct.pack('<Q',len(h))+h+b'abcd'


def model(k=3):
    cfg={'num_hidden_layers':12,'model_type':'llama','tie_word_embeddings':False}
    wm={f'model.layers.{i}.weight':f'layer-{i}.safetensors' for i in range(12)}
    wm.update({'model.embed_tokens.weight':'embed.safetensors','lm_head.weight':'head.safetensors','model.norm.weight':'head.safetensors'})
    idx={'weight_map':wm,'metadata':{'total_size':6_000_000_000}}
    nodes=[dict(id=f'n{i}',label=f'Mini {i}',role='lead' if i==k-1 else 'packer',host=f'fake{i}',
                ram={'available_gb':20,'total_gb':24},disk={'free_gb':100}) for i in range(k)]
    return cfg,idx,nodes


def write_model(d, cfg, idx, files):
    d=Path(d); d.mkdir(parents=True,exist_ok=True)
    (d/'config.json').write_text(json.dumps(cfg));(d/'model.safetensors.index.json').write_text(json.dumps(idx))
    (d/'tokenizer.json').write_text('{}')
    for f in files: (d/f).write_bytes(tensor_bytes())


class Accounting(unittest.TestCase):
    def test_reject_path_escape(self):
        for name in ('../x','/x','a/../x','a//x','a\\x','./x'):
            with self.subTest(name=name), self.assertRaises(ValueError): M.safe_name(name)

    def test_repo_validation(self):
        for repo in ('https://bad/repo','owner/repo;cmd','../repo','owner/repo/sub'):
            with self.subTest(repo=repo),self.assertRaises(ValueError):M.repo_name(repo)
        self.assertEqual(M.repo_name('org/model-4bit'),'org/model-4bit')

    def test_empty_tree(self):
        with tempfile.TemporaryDirectory() as d:
            out=M.inspect(Path(d)/'absent')
            self.assertEqual(out['on_disk_bytes'],0); self.assertEqual(out['files'],{})

    def test_storage_reports_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'file').write_bytes(b'12345')
            self.assertEqual(M.tree_usage(d)['on_disk_bytes'],5)

    def test_symlink_not_counted_or_followed(self):
        with tempfile.TemporaryDirectory() as d:
            outside=Path(d)/'outside'; outside.mkdir();(outside/'x').write_bytes(b'12345')
            root=Path(d)/'models';root.mkdir();(root/'link').symlink_to(outside,target_is_directory=True)
            out=M.tree_usage(root)
            self.assertEqual(out['on_disk_bytes'],0);self.assertEqual(out['links'],['link'])
            with self.assertRaises(ValueError):M.contained(root,'link/x')

    def test_linked_model_root_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'real';root.mkdir();link=Path(d)/'link';link.symlink_to(root,target_is_directory=True)
            self.assertIsNone(M.tree_usage(link)['on_disk_bytes'])

    def test_hardlinks_allocated_once(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a';a.write_bytes(b'x'*10000);os.link(a,Path(d)/'b')
            out=M.tree_usage(d)
            self.assertEqual(out['on_disk_bytes'],20000);self.assertEqual(out['allocated_bytes'],a.stat().st_blocks*512)

    def test_invalid_header_missing_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'x.safetensors').write_bytes(b'bad')
            inv=M.inspect(d)
            self.assertEqual(M.storage_plan(['x.safetensors'],inv,{'x.safetensors':3})['downloads'],['x.safetensors'])

    def test_obsolete_only_listed_no_writes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'old.safetensors').write_bytes(tensor_bytes());(Path(d)/'tokenizer.json').write_text('{}')
            before={str(p):p.read_bytes() for p in Path(d).iterdir()}
            out=M.storage_plan(['new.safetensors'],M.inspect(d),{'new.safetensors':200})
            self.assertEqual(out['not_needed_for_plan'],['old.safetensors']);self.assertEqual(out['download_bytes'],200)
            self.assertEqual(before,{str(p):p.read_bytes() for p in Path(d).iterdir()})

    def test_unknown_inventory_remains_unknown(self):
        self.assertIsNone(M.storage_plan(['file'],None)['downloads'])
        self.assertIsNone(M.storage_plan(['file'],{'files':None})['downloads'])

    def test_required_size_mismatch(self):
        out=M.storage_plan(['a'],{'files':{'a':2}}, {'a':3})
        self.assertEqual(out['downloads'],['a']);self.assertEqual(out['download_bytes'],3)

    def test_metadata_digest_canonical(self):
        self.assertEqual(M.plan_digest({'b':1,'a':2},{}),M.plan_digest({'a':2,'b':1},{}))

    def test_cli_inspect_no_create(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p=Path(d)/'missing'; M.main(['--inspect-json',json.dumps({'path':str(p)})]);self.assertFalse(p.exists())


class BalanceFiles(unittest.TestCase):
    def test_four_nodes_replan_and_retain(self):
        cfg,idx,nodes=model(4);counts=[3]*4;files=F.plan_stage_files(cfg,idx,counts)['stages']
        inv={n['id']:{'storage':{'files':{f:100 for f in files[i]},'on_disk_bytes':len(files[i])*100},
                          'has_config':True,'has_index':True,'has_tokenizer':True} for i,n in enumerate(nodes)}
        sizes={f:100 for f in idx['weight_map'].values()}
        before=json.dumps(inv,sort_keys=True)
        out=B.preview(12,6,nodes,[4,2,3,3],config=cfg,index=idx,inventories=inv,sizes=sizes)
        self.assertEqual(out['stages'][0]['downloads'],['layer-3.safetensors'])
        self.assertEqual(out['stages'][1]['not_needed_for_plan'],['layer-3.safetensors'])
        self.assertEqual(out['stages'][0]['on_disk_bytes'],400)
        self.assertFalse(out['ready']);self.assertEqual(before,json.dumps(inv,sort_keys=True))

    def test_whole_boundary_shard_shared(self):
        cfg,idx,nodes=model(3);idx['weight_map']['model.layers.4.weight']='layer-3.safetensors'
        files=F.plan_stage_files(cfg,idx,[4]*3)['stages']
        self.assertIn('layer-3.safetensors',files[0]);self.assertIn('layer-3.safetensors',files[1])

    def test_n_stage_inventory_catalog_load_plan(self):
        cfg,idx,nodes=model(3);counts=[4]*3;files=F.plan_stage_files(cfg,idx,counts)['stages']
        with tempfile.TemporaryDirectory() as d:
            inventories=[]
            for i,n in enumerate(nodes):
                path=Path(d)/n['id'];write_model(path,cfg,idx,files[i])
                (path/'caravan-placement.json').write_text(json.dumps(dict(mode='split',node_ids=[n['id'] for n in nodes],split_counts=counts,layer_plan=counts)))
                st=I.inspect_tree(path);self.assertTrue(st['stage_ok'][i])
                inventories.append(dict(n,models={'org/model':st}))
            with mock.patch.object(I,'scan_local',return_value={}):
                rows=C.build_entries_from_inventories(node_inventories=inventories,nodes=nodes,fit_nodes=nodes,max_split_stages=3)
            self.assertTrue(rows[0]['usable'],rows[0].get('disabled_reason'))
            self.assertEqual(rows[0]['split_counts'],counts)
            self.assertEqual([n['model_path'] for n in rows[0]['pipeline_nodes']],[str(Path(d)/n['id']) for n in nodes])

    def test_no_default_two_stage_limit(self):
        _,_,nodes=model(7)
        self.assertEqual(len(N.split_stage_nodes(nodes)),7)
        self.assertEqual(N.stage_limit(nodes),7)

    def test_app_builds_own_paths_for_missing_third(self):
        cfg,idx,nodes=model(3)
        with tempfile.TemporaryDirectory() as d:
            write_model(d,cfg,idx,[])
            entry=dict(id='model',hf='org/model',source='hf-mlx',lead_path=d, nodes={n['label']:dict(path='/own/'+n['id'],has_config=True,has_index=True,has_tokenizer=True) for n in nodes})
            app=types.SimpleNamespace(mgr=types.SimpleNamespace(snapshot=lambda:{}),
                 configured_nodes=lambda:nodes,list_loadable_models=lambda:[entry],nodes=lambda:{'nodes':nodes},_ssh_fn=lambda:None)
            def inspect(app,n,path):
                return {'files':{},'on_disk_bytes':0}
            with mock.patch.object(WF,'inspect_node',side_effect=inspect):out=WS.App.balance(app,{'model_id':'model','counts':[4]*3})
            self.assertEqual(len(out['file_requests']),3)
            self.assertEqual(out['file_requests'][1]['dest'],'/own/n1')
            self.assertFalse(out['ready']);self.assertTrue(out['stages'][1]['downloads'])


class PinnedMlx(unittest.TestCase):
    def setUp(self):
        self.cfg,self.idx,_=model();self.payload=tensor_bytes();self.sha='a'*40
        self.siblings=[types.SimpleNamespace(rfilename=f,size=len(self.payload),lfs={'sha256':hashlib.sha256(self.payload).hexdigest()}) for f in set(self.idx['weight_map'].values())]
        self.info=types.SimpleNamespace(sha=self.sha,siblings=self.siblings)
        self.calls=[]
        def snapshot(repo,revision,local_dir,token,allow_patterns):
            self.calls.append((revision,allow_patterns));write_model(local_dir,self.cfg,self.idx,[])
        self.hub=types.SimpleNamespace(HfApi=mock.Mock(return_value=types.SimpleNamespace(model_info=mock.Mock(return_value=self.info))),snapshot_download=snapshot)

    def request(self,d,i=1):
        return dict(repo_id='org/model',dest=str(d),counts=[4]*3,stage_index=i,metadata_digest=M.plan_digest(self.cfg,self.idx))

    def test_only_middle_stage_shards_fetched_pinned(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(sys.modules,{'huggingface_hub':self.hub}),mock.patch.object(F,'_resolve_token',return_value=None),mock.patch('range_fetch.fetch') as fetch:
            fetch.side_effect=lambda repo,f,dest,size,**kw:(Path(dest)/f).write_bytes(self.payload)
            req=self.request(d);req['placement']={'mode':'split','split_counts':[4]*3};out=M.fetch_mlx(req);self.assertEqual(json.loads((Path(d)/'caravan-placement.json').read_text())['split_counts'],[4]*3);self.assertEqual(out['files'],[f'layer-{i}.safetensors' for i in range(4,8)])
            self.assertEqual(len(fetch.call_args_list),4)
            self.assertTrue(all('/resolve/'+self.sha+'/' in c.kwargs['url'] for c in fetch.call_args_list))
            self.assertTrue(all(rev==self.sha for rev,_ in self.calls))
            self.assertFalse((Path(d)/'embed.safetensors').exists())

    def test_changed_metadata_does_not_touch_dest(self):
        with tempfile.TemporaryDirectory() as d,mock.patch.dict(sys.modules,{'huggingface_hub':self.hub}),mock.patch.object(F,'_resolve_token',return_value=None):
            dest=Path(d)/'new';req=self.request(dest);req['metadata_digest']='wrong'
            with self.assertRaisesRegex(ValueError,'metadata changed'):M.fetch_mlx(req)
            self.assertFalse(dest.exists())

    def test_corrupt_existing_never_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as d,mock.patch.dict(sys.modules,{'huggingface_hub':self.hub}),mock.patch.object(F,'_resolve_token',return_value=None):
            bad=Path(d)/'layer-4.safetensors';bad.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'move these corrupt'):M.fetch_mlx(self.request(d))
            self.assertEqual(bad.read_bytes(),b'bad')

    def test_same_size_wrong_checksum_rejected(self):
        with tempfile.TemporaryDirectory() as d,mock.patch.dict(sys.modules,{'huggingface_hub':self.hub}),mock.patch.object(F,'_resolve_token',return_value=None):
            (Path(d)/'layer-4.safetensors').write_bytes(self.payload[:-1]+b'x')
            with self.assertRaisesRegex(ValueError,'checksum differs'):M.fetch_mlx(self.request(d))


class GgufRanges(unittest.TestCase):
    def plan(self):
        data=b'abcdefgh'
        return dict(format='gguf',repo_id='org/gguf',filename='q.gguf',revision='a'*40,source_bytes=100,
                    source_sha256='b'*64,n_layers=12,tensors=[dict(name='blk.4.w',offset=20,size=8,sha256=hashlib.sha256(data).hexdigest())])

    def response(self,data=b'abcdefgh',code=206,cr='bytes 20-27/100'):
        r=io.BytesIO(data);r.status=code;r.headers={'Content-Range':cr};return r

    def test_exact_tensor_range_only(self):
        with tempfile.TemporaryDirectory() as d:
            op=mock.Mock(return_value=self.response());p=G.fetch_tensor(self.plan(),self.plan()['tensors'][0],Path(d)/'partial',opener=op)
            self.assertEqual(p.read_bytes(),b'abcdefgh');self.assertEqual(op.call_args.args[0].headers['Range'],'bytes=20-27')

    def test_resume_exact_remaining_range(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'part';p.write_bytes(b'abcd');op=mock.Mock(return_value=self.response(b'efgh',cr='bytes 24-27/100'))
            G.fetch_tensor(self.plan(),self.plan()['tensors'][0],p,opener=op)
            self.assertEqual(op.call_args.args[0].headers['Range'],'bytes=24-27');self.assertEqual(p.read_bytes(),b'abcdefgh')

    def test_ignored_range_refused_no_full_copy(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'part'
            with self.assertRaisesRegex(ValueError,'no full-file fallback'):G.fetch_tensor(self.plan(),self.plan()['tensors'][0],p,opener=lambda *a,**kw:self.response(code=200))
            self.assertFalse(p.exists())

    def test_wrong_content_range_refused(self):
        with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'requested tensor range'):
            G.fetch_tensor(self.plan(),self.plan()['tensors'][0],Path(d)/'p',opener=lambda *a,**kw:self.response(cr='bytes 0-7/100'))

    def test_wrong_checksum_refused(self):
        with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'checksum failed'):
            G.fetch_tensor(self.plan(),self.plan()['tensors'][0],Path(d)/'p',opener=lambda *a,**kw:self.response(b'xxxxxxxx'))

    def test_extra_response_bytes_refused(self):
        with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'extra bytes'):
            G.fetch_tensor(self.plan(),self.plan()['tensors'][0],Path(d)/'p',opener=lambda *a,**kw:self.response(b'abcdefghi'))

    def test_out_of_bounds_refused(self):
        p=self.plan();p['tensors'][0]['offset']=99
        with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'outside source'):
            G.fetch_tensor(p,p['tensors'][0],Path(d)/'p')

    def test_mutable_revision_refused(self):
        p=self.plan();p['revision']='main'
        with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'immutable'):
            G.fetch_tensor(p,p['tensors'][0],Path(d)/'p')

    def test_three_and_four_node_tensor_plans(self):
        p=self.plan();p['tensors']=[dict(name=f'blk.{i}.w',offset=i,size=1,sha256='c'*64) for i in range(12)]
        for k in (3,4):
            out=[G.stage_plan(p,[1]*k,i) for i in range(k)]
            sets=[{t['name'] for t in s['tensors']} for s in out]
            self.assertEqual(len(set.union(*sets)),12)
            self.assertEqual(sum(len(s) for s in sets),12)

    def test_moving_share_replans(self):
        p=self.plan();p['tensors']=[dict(name=f'blk.{i}.w',offset=i,size=1,sha256='c'*64) for i in range(12)]
        self.assertNotEqual(G.stage_plan(p,[1,1,1],1)['tensors'],G.stage_plan(p,[1,2,1],1)['tensors'])

    def test_invalid_shares(self):
        for shares in ([0,1],[True,1],[float('nan'),1],[-1,1]):
            with self.subTest(shares=shares),self.assertRaises(ValueError):G.stage_plan(self.plan(),shares,0)

    def test_empty_cache_all_missing(self):
        with tempfile.TemporaryDirectory() as d:
            out=G.status(self.plan(),cache=Path(d)/'cache',records=Path(d)/'records')
            self.assertEqual(out['downloads'],['blk.4.w']);self.assertEqual(out['download_bytes'],8)

    def test_retained_cache_listed_not_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            cache=Path(d)/'cache';cache.mkdir()
            key='a'*16;(cache/key).write_bytes(b'previous')
            root=Path(d)/'records';root.mkdir();record=G.record_path(self.plan(),root)
            record.write_text(json.dumps({'seen_tensors':{'c'*64:{'cache_key':key,'size':8}}}))
            out=G.status(self.plan(),cache=cache,records=root)
            self.assertEqual(out['not_needed_for_plan'],[key]);self.assertTrue((cache/key).exists())

    def test_source_mismatch_no_cache_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'m.gguf';p.write_bytes(b'local')
            hub=types.SimpleNamespace(HfApi=lambda **kw:types.SimpleNamespace(model_info=lambda *a,**kw:types.SimpleNamespace(sha='a'*40,siblings=[types.SimpleNamespace(rfilename='m.gguf',size=5,lfs={'sha256':'0'*64})])))
            with mock.patch.dict(sys.modules,{'huggingface_hub':hub}),mock.patch.object(F,'_resolve_token',return_value=None),self.assertRaisesRegex(ValueError,'differs from this source'):
                G.source_manifest(p,'org/model','m.gguf',cache_root=Path(d)/'plans')
            self.assertFalse((Path(d)/'plans').exists())


class FileJobs(unittest.TestCase):
    def test_duplicate_repo_job_refused(self):
        with mock.patch.object(WP,'list_jobs',return_value=[{'repo_id':'org/model','status':'running'}]),self.assertRaisesRegex(ValueError,'already running'):
            WF.start(None,dict(repo_id='org/model'))

    def test_owned_cancel_unique_marker_no_sweep(self):
        app=types.SimpleNamespace(configured_nodes=lambda:[{'id':'n','host':'local'}])
        with mock.patch.object(WF,'shell',return_value=types.SimpleNamespace(returncode=0)) as sh:
            WF.cancel(app,{'file_transfers':[{'id':'n','token':'a'*32}]})
            cmd=sh.call_args.args[2]
            self.assertIn('SIGTERM',cmd);self.assertIn('--job',cmd);self.assertNotIn('pkill',cmd)

    def test_cancel_unknown_host_never_contacted(self):
        app=types.SimpleNamespace(configured_nodes=lambda:[])
        with mock.patch.object(WF,'shell') as sh:
            WF.cancel(app,{'file_transfers':[{'id':'unknown','token':'a'*32}]});sh.assert_not_called()

    def test_prepare_n_picker_uses_same_balance_contract(self):
        cfg,idx,nodes=model(4)
        def snapshot(repo,revision,local_dir,token,allow_patterns):write_model(local_dir,cfg,idx,[])
        hub=types.SimpleNamespace(HfApi=lambda **kw:types.SimpleNamespace(model_info=lambda *a,**kw:types.SimpleNamespace(sha='a'*40,siblings=[types.SimpleNamespace(rfilename=f,size=100000000) for f in set(idx['weight_map'].values())])),snapshot_download=snapshot)
        with mock.patch.dict(sys.modules,{'huggingface_hub':hub}),mock.patch.object(F,'_resolve_token',return_value=None),mock.patch.object(WF,'inspect_node',return_value={'files':{},'on_disk_bytes':0}):
            out=WF.prepare_new_mlx(None,'org/model',nodes,[3]*4)
            self.assertEqual(out['counts'],[3]*4);self.assertEqual(len(out['file_requests']),4)
            self.assertTrue(all(r['dest']=='~/.caravan/mlx-models/org--model' for r in out['file_requests']))


class FileHttp(unittest.TestCase):
    def test_preview_hides_execution_requests_and_fetch_is_explicit(self):
        plan=dict(stages=[],counts=[4]*3,entry={'private':'entry'},file_requests=[{'dest':'/server/path'}])
        app=types.SimpleNamespace(balance=mock.Mock(side_effect=lambda *a,**kw:dict(plan)))
        server=ThreadingHTTPServer(('127.0.0.1',0),WS.make_handler(app));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def post(path):
                with urlopen(Request('http://127.0.0.1:'+str(server.server_port)+path,data=b'{}',headers={'Content-Type':'application/json'})) as r:return json.load(r)
            with mock.patch.object(WF,'start',return_value={'id':'job'}) as start:
                out=post('/api/files/preview');self.assertNotIn('entry',out);self.assertNotIn('file_requests',out);start.assert_not_called()
                self.assertEqual(post('/api/files/fetch')['job']['id'],'job');start.assert_called_once()
                self.assertTrue(app.balance.call_args.kwargs['fresh'])
        finally:server.shutdown();server.server_close();thread.join()





class NativeGgufCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.tmp=tempfile.TemporaryDirectory(); cls.binary=Path(cls.tmp.name)/'seed'
        subprocess.run(['cc','-O2','-o',str(cls.binary),str(Path(__file__).resolve().parents[1]/'agent/fnv_seed.c')],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_peer_fetch_seeds_native_cache_and_repeat_fetches_nothing(self):
        p=GgufRanges().plan();tensor=p['tensors'][0]
        with tempfile.TemporaryDirectory() as d:
            cache,records,staging=[Path(d)/name for name in ('cache','records','staging')]
            op=mock.Mock(return_value=GgufRanges().response())
            with mock.patch.object(G,'ensure_bin',return_value=self.binary),mock.patch.object(F,'_resolve_token',return_value=None):
                out=G.fetch_plan(p,cache=cache,records=records,staging=staging,opener=op)
                self.assertTrue(out['ok']);self.assertEqual(out['downloads'],[])
                self.assertEqual(len(list(cache.iterdir())),1)
                self.assertEqual(next(cache.iterdir()).read_bytes(),b'abcdefgh')
                self.assertEqual(list(staging.iterdir()),[])
                out=G.fetch_plan(p,cache=cache,records=records,staging=staging,opener=op)
                self.assertEqual(op.call_count,1)
                self.assertFalse(any(Path(d).rglob('*.gguf')))

    def test_verified_source_manifest_cached_by_file_identity(self):
        data=b'local-GGUF-fixture';sha=hashlib.sha256(data).hexdigest()
        info=types.SimpleNamespace(sha='a'*40,siblings=[types.SimpleNamespace(rfilename='model.gguf',size=len(data),lfs={'sha256':sha})])
        hub=types.SimpleNamespace(HfApi=lambda **kw:types.SimpleNamespace(model_info=lambda *a,**kw:info))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model.gguf';path.write_bytes(data)
            with mock.patch.dict(sys.modules,{'huggingface_hub':hub}),mock.patch.object(F,'_resolve_token',return_value=None),mock.patch.object(G,'tensor_plan',return_value=([('blk.1.w',2,4)],12)) as tensor_plan:
                a=G.source_manifest(path,'org/gguf','model.gguf',cache_root=Path(d)/'plans')
                b=G.source_manifest(path,'org/gguf','model.gguf',cache_root=Path(d)/'plans')
                tensor_plan.assert_called_once();self.assertEqual(a,b)
                self.assertEqual(a['tensors'][0]['sha256'],hashlib.sha256(data[2:6]).hexdigest())


class TransferLifecycle(unittest.TestCase):
    def capture(self):
        _,_,nodes=model(3)
        app=types.SimpleNamespace(configured_nodes=lambda:nodes,mgr=types.SimpleNamespace(repo='/box/repo'))
        plan=dict(repo_id='org/model',model_id='m',counts=[4]*3,node_ids=[n['id'] for n in nodes],
                  stages=[dict(id=n['id'],label=n['label'],downloads=['x'],required_bytes=1) for n in nodes],
                  file_requests=[dict(format='mlx',revision='a'*40,dest='/own/'+n['id'],required_files=['x']) for n in nodes])
        captured=[]
        def start(repo,**kw):captured.extend(kw['runners']);return {'id':'j'}
        with mock.patch.object(WF,'active',return_value=[]),mock.patch.object(WP,'list_jobs',return_value=[]),mock.patch.object(WP,'start_download',side_effect=start),mock.patch.object(WP,'_job_set'),mock.patch.object(WP,'get_job',return_value={'id':'j'}):
            WF.start(app,plan)
        return app,captured

    def test_remote_failure_exit_not_misreported_done(self):
        app,runners=self.capture();commands=[]
        def shell(app,node,cmd,timeout=60):
            commands.append(cmd)
            out=json.dumps({'exit':'7','log':'network failed'}) if 'alive=None' in cmd else ''
            return types.SimpleNamespace(returncode=0,stdout=out,stderr='')
        with mock.patch.object(WF,'shell',side_effect=shell),self.assertRaisesRegex(RuntimeError,'network failed'):
            runners[1]['run']('org/model','/own/n1',None,lambda *a:None)
        self.assertTrue(any('nohup bash -c' in c and 'wait' in c and '.exit' in c for c in commands))

    def test_disappeared_process_not_marked_complete(self):
        app,runners=self.capture()
        def shell(app,node,cmd,timeout=60):
            out=json.dumps({'exit':None,'alive':False,'pid':123,'log':''}) if 'alive=None' in cmd else ''
            return types.SimpleNamespace(returncode=0,stdout=out,stderr='')
        with mock.patch.object(WF,'shell',side_effect=shell),mock.patch.object(WF.time,'sleep'),self.assertRaisesRegex(RuntimeError,'disappeared'):
            runners[0]['run']('org/model','/own/n0',None,lambda *a:None)

    def test_per_node_request_paths_and_unique_tokens(self):
        app,runners=self.capture()
        self.assertEqual([r['dest'] for r in runners],['/own/n0','/own/n1','/own/n2'])
        self.assertEqual(len(runners),3)

    def test_missing_placement_write_fails_job(self):
        app,runners=self.capture()
        with mock.patch.object(WF,'shell',return_value=types.SimpleNamespace(returncode=1)),self.assertRaisesRegex(RuntimeError,'save stage placement'):
            runners[0]['save_placement']({'counts':[4]*3})


class PickerConfiguredRoots(unittest.TestCase):
    def test_live_stats_projection_cannot_lose_or_override_configured_roots(self):
        _, _, nodes = model(2)
        nodes[-1]['host'] = 'local'
        for n in nodes:
            n.update(model_root='~/isolated/' + n['id'], physical_id='physical-' + n['id'],
                     python='~/special/bin/python')
        live = [{k:v for k,v in n.items() if k not in ('model_root','physical_id','python')}
                for n in nodes]
        live[0]['model_root'] = '/not-the-configured-root'
        app = types.SimpleNamespace(configured_nodes=lambda:nodes, nodes=lambda:{'nodes':live})
        server = ThreadingHTTPServer(('127.0.0.1',0),WS.make_handler(app))
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with mock.patch.object(WF,'prepare_new_mlx',return_value={'plan':True}) as prepare, \
                 mock.patch.object(WF,'start',return_value={'id':'job'}):
                body = dict(repo_id='org/model',placement_id='split:2',weights_gb=1,
                            packer_layers=6,counts=[6,6])
                request = Request('http://127.0.0.1:'+str(server.server_port)+'/api/picker/download',
                                  data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request) as response: out=json.load(response)
                self.assertEqual(out['job']['id'],'job')
                targets = prepare.call_args.args[2]
                for target in targets:
                    original = next(n for n in nodes if n['id']==target['id'])
                    for key in ('model_root','physical_id','python'):
                        self.assertEqual(target[key],original[key])
                    self.assertEqual(target['ram'],original['ram'])
        finally:
            server.shutdown();server.server_close();thread.join()


class GgufUi(unittest.TestCase):
    def test_explicit_fallback_downloads_complete_gguf_only_on_lead(self):
        _,_,nodes=model(3);nodes[-1]['host']='local'
        app=types.SimpleNamespace(configured_nodes=lambda:nodes,nodes=lambda:{'nodes':nodes},mgr=types.SimpleNamespace(repo='/box/repo'))
        server=ThreadingHTTPServer(('127.0.0.1',0),WS.make_handler(app));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with mock.patch.object(WP,'_fetch_repo_blobs',return_value={'gguf_files':[{'rfilename':'model.gguf','size':1000}]}),mock.patch.object(WP,'start_download',return_value={'id':'job'}) as start,mock.patch.object(WP,'_job_set'):
                body=dict(repo_id='org/gguf',source='gguf',gguf_file='model.gguf',weights_gb=1,packer_layers=1,full_file_fallback=True)
                request=Request('http://127.0.0.1:'+str(server.server_port)+'/api/picker/download',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request) as r:out=json.load(r)
                self.assertEqual(out['stages'],1)
                self.assertEqual(start.call_args.kwargs['runners'][0]['id'],'n2')
        finally:server.shutdown();server.server_close();thread.join()

    def test_gguf_preview_lead_first_and_peer_cache_status(self):
        import web_gguf_files as WGF
        _,_,nodes=model(3);nodes[-1]['host']='local'
        p=GgufRanges().plan()
        app=types.SimpleNamespace(configured_nodes=lambda:nodes,nodes=lambda:{'nodes':nodes})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model.gguf';path.write_bytes(b'x'*100)
            response=types.SimpleNamespace(returncode=0,stdout=json.dumps(dict(downloads=['blk.4.w'],download_bytes=8,required_bytes=8,on_disk_bytes=0,allocated_bytes=0,not_needed_for_plan=[])))
            with mock.patch.object(WGF,'source_manifest',return_value=p),mock.patch.object(WF,'shell',return_value=response):
                out=WGF.preview(app,dict(id='gguf/m',lead_path=str(path)),dict(repo_id='org/gguf',gguf_file='model.gguf',counts=[1,1,1]))
            self.assertEqual(out['node_ids'],['n2','n0','n1'])
            self.assertEqual(out['stages'][0]['on_disk_bytes'],100)
            self.assertIn('complete GGUF',out['note']);self.assertFalse(out['ready'])
            self.assertEqual(out['entry']['gguf_shares'],[1,1,1])
            self.assertIs(out['entry']['gguf_peer_files_ready'],False)





class GgufVerifiedLaunch(unittest.TestCase):
    def test_preview_marks_only_safe_complete_peer_files(self):
        import web_gguf_files as WGF
        _,_,nodes=model(3);nodes[-1]['host']='local';plan=GgufRanges().plan()
        app=types.SimpleNamespace(configured_nodes=lambda:nodes,nodes=lambda:{'nodes':nodes})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model.gguf';path.write_bytes(b'x'*100)
            response=types.SimpleNamespace(returncode=0,stdout=json.dumps(dict(downloads=[],download_bytes=0,required_bytes=8,on_disk_bytes=8,allocated_bytes=8,not_needed_for_plan=[])))
            with mock.patch.object(WGF,'source_manifest',return_value=plan),mock.patch.object(WF,'shell',return_value=response):
                out=WGF.preview(app,dict(id='gguf/m',lead_path=str(path)),dict(repo_id='org/gguf',gguf_file='model.gguf',counts=[1,1,1]))
                self.assertTrue(out['ready']);self.assertIs(out['entry']['gguf_peer_files_ready'],True)
                nodes[0]['ram']['available_gb']=1
                out=WGF.preview(app,dict(id='gguf/m',lead_path=str(path)),dict(repo_id='org/gguf',gguf_file='model.gguf',counts=[1,1,1]))
                self.assertFalse(out['ready']);self.assertIs(out['entry']['gguf_peer_files_ready'],False)

    def manager(self):
        from web_workers import WorkerManager
        mgr=WorkerManager.__new__(WorkerManager);mgr._note=mock.Mock();mgr._check_cancel=mock.Mock();mgr._ssh_node=mock.Mock(return_value=types.SimpleNamespace(stdout='NO_LOCAL_COPY'))
        return mgr

    def test_verified_own_files_never_scan_full_peer_gguf(self):
        mgr=self.manager();meta={};peers=[dict(id=f'n{i}',label=f'Mini {i}') for i in range(3)]
        mgr._seed_gguf_peers(dict(gguf_peer_files_ready=True),Path('/missing/full.gguf'),[1,1,1,1],peers,meta)
        mgr._ssh_node.assert_not_called();self.assertEqual(meta['file_mode'],'balance-verified-peer-cache');self.assertNotIn('seed',meta)

    def test_legacy_load_keeps_optional_full_peer_seed(self):
        self.legacy({})

    def test_truthy_nonboolean_flag_cannot_skip_legacy_seed(self):
        self.legacy(dict(gguf_peer_files_ready='true'))

    def legacy(self,entry):
        import gguf_split
        mgr=self.manager();meta={};peers=[dict(id='p',label='Peer',repo='~/cv3')]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model.gguf';path.write_bytes(b'x'*100)
            with mock.patch.object(gguf_split,'seed_command',return_value='LEGACY_SEED') as seed:
                mgr._seed_gguf_peers(entry,path,[1,1],peers,meta)
            seed.assert_called_once_with(path.name,100,[1,1],1,repo='~/cv3')
        mgr._ssh_node.assert_called_once();self.assertNotIn('file_mode',meta)


class FinalStorageRegressions(unittest.TestCase):
    def test_inventory_payload_preserves_n_stage_and_disk_fields(self):
        cfg,idx,nodes=model()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'org--model';files=F.plan_stage_files(cfg,idx,[4]*3)['stages'][1]
            write_model(path,cfg,idx,files)
            (path/'caravan-placement.json').write_text(json.dumps({'mode':'split','split_counts':[4]*3}))
            item=I.inventory_payload(roots=[d])['models']['org/model']
            self.assertEqual(item['stage_counts'],[4]*3);self.assertTrue(item['stage_ok'][1])
            self.assertGreater(item['storage']['on_disk_bytes'],0)
            self.assertEqual(item['full_weights_gb'],6)
            self.assertTrue(all(item[k] for k in ('has_config','has_index','has_tokenizer')))
            plan=B.preview(12,6,nodes,[4]*3,config=cfg,index=idx,inventories={n['id']:item for n in nodes})
            self.assertTrue(all(stage['metadata_ready'] for stage in plan['stages']))

    def test_custom_model_root_and_python_config(self):
        raw={'web':{'nodes':{'sim':{'host':'local','model_root':'~/sim-models','python':'~/special/bin/python'}}}}
        node=N.nodes_from_config({'_raw':raw})[0]
        self.assertEqual(WF.model_dest(node,'org/model'),'~/sim-models/org--model')
        self.assertEqual(node['python'],'~/special/bin/python')

    def test_linked_root_blocks_ready_file_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'real';root.mkdir();link=Path(d)/'link';link.symlink_to(root,target_is_directory=True)
            self.assertIsNone(M.storage_plan(['file'],M.inspect(link))['downloads'])

    def test_duplicate_physical_destination_refused(self):
        _,_,nodes=model();nodes[0]['physical_id']='same';nodes[1]['physical_id']='same'
        plan=dict(repo_id='org/model',model_id='m',counts=[4]*3,node_ids=[n['id'] for n in nodes],stages=[dict(id=n['id']) for n in nodes],
                  file_requests=[dict(format='mlx',revision='a'*40,dest='/same') for n in nodes])
        app=types.SimpleNamespace(configured_nodes=lambda:nodes)
        with mock.patch.object(WP,'list_jobs',return_value=[]),self.assertRaisesRegex(ValueError,'separate model_root'):
            WF.start(app,plan)

    def test_whole_job_resolves_revision_once(self):
        _,_,nodes=model();app=types.SimpleNamespace(configured_nodes=lambda:nodes,mgr=types.SimpleNamespace(repo='/box/repo'))
        plan=dict(repo_id='org/model',model_id='m',counts=[4]*3,node_ids=[n['id'] for n in nodes],stages=[dict(id=n['id'],label=n['label'],downloads=['x']) for n in nodes],
                  file_requests=[dict(format='mlx',dest='/own/'+n['id'],required_files=['x']) for n in nodes])
        api=types.SimpleNamespace(model_info=mock.Mock(return_value=types.SimpleNamespace(sha='b'*40)))
        hub=types.SimpleNamespace(HfApi=lambda **kw:api);captured=[];written=[]
        def start(repo,**kw):captured.extend(kw['runners']);return {'id':'j'}
        def shell(app,node,cmd,timeout=60):
            import shlex
            if cmd.startswith('printf %s '):written.append(json.loads(shlex.split(cmd)[2]))
            out=json.dumps({'exit':'0','log':''}) if 'alive=None' in cmd else ''
            return types.SimpleNamespace(returncode=0,stdout=out)
        with mock.patch.object(WF,'active',return_value=[]),mock.patch.dict(sys.modules,{'huggingface_hub':hub}),mock.patch.object(F,'_resolve_token',return_value=None),mock.patch.object(WP,'list_jobs',return_value=[]),mock.patch.object(WP,'start_download',side_effect=start),mock.patch.object(WP,'_job_set'),mock.patch.object(WP,'get_job',return_value={'id':'j'}):
            WF.start(app,plan)
        with mock.patch.object(WF,'shell',side_effect=shell):
            for runner in captured:runner['run']('org/model',runner['dest'],None,lambda *a:None)
        api.model_info.assert_called_once();self.assertEqual([r['revision'] for r in written],['b'*40]*3)

    def test_existing_incompatible_metadata_not_overwritten(self):
        fixture=PinnedMlx();fixture.setUp()
        with tempfile.TemporaryDirectory() as d,mock.patch.dict(sys.modules,{'huggingface_hub':fixture.hub}),mock.patch.object(F,'_resolve_token',return_value=None):
            write_model(d,dict(fixture.cfg,num_hidden_layers=8),fixture.idx,[])
            before=(Path(d)/'config.json').read_text()
            with self.assertRaisesRegex(ValueError,'different model metadata'):M.fetch_mlx(fixture.request(d))
            self.assertEqual((Path(d)/'config.json').read_text(),before)

    def test_same_size_corrupt_rpc_cache_not_reused(self):
        p=GgufRanges().plan()
        with tempfile.TemporaryDirectory() as d:
            cache=Path(d)/'cache';cache.mkdir();(cache/('a'*16)).write_bytes(b'xxxxxxxx')
            records=Path(d)/'records';records.mkdir()
            G.record_path(p,records).write_text(json.dumps({'seen_tensors':{p['tensors'][0]['sha256']:{'cache_key':'a'*16,'size':8}}}))
            with mock.patch.object(F,'_resolve_token',return_value=None),self.assertRaisesRegex(ValueError,'cached tensor checksum'):
                G.fetch_plan(p,cache=cache,records=records,staging=Path(d)/'staging')
            self.assertEqual((cache/('a'*16)).read_bytes(),b'xxxxxxxx')





class RestartOwnership(unittest.TestCase):
    def test_owned_record_discovery(self):
        token='a'*32
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/token;base.with_suffix('.pid').write_text('123')
            base.with_suffix('.json').write_text(json.dumps(dict(repo_id='org/model',node_id='n0',dest='/own/model',counts=[4]*3)))
            with mock.patch('subprocess.run',return_value=types.SimpleNamespace(stdout='python /repo/agent/model_files.py --job '+token)):
                found=M.active_transfers(d)
            self.assertEqual(found[0]['token'],token);self.assertEqual(found[0]['repo_id'],'org/model')

    def test_reused_pid_not_owned(self):
        token='a'*32
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/token;base.with_suffix('.pid').write_text('123');base.with_suffix('.json').write_text('{}')
            with mock.patch('subprocess.run',return_value=types.SimpleNamespace(stdout='python /unrelated.py --job '+token)):
                self.assertEqual(M.active_transfers(d),[])

    def test_orphan_transfers_rediscovered_without_bogus_byte_totals(self):
        _,_,nodes=model();app=types.SimpleNamespace(configured_nodes=lambda:nodes)
        def active(app,n):return [dict(repo_id='org/model',token='abcdef'[int(n['id'][-1])]*32)]
        with mock.patch.object(WF,'active',side_effect=active):
            jobs=WF.orphans(app,set());self.assertEqual(len(jobs),1)
            self.assertTrue(jobs[0]['file_mode']);self.assertEqual(len(jobs[0]['file_transfers']),3)
            self.assertNotIn('total_bytes',jobs[0]['progress']['n0'])
            self.assertEqual(WF.orphans(app,{'org/model'}),[])

    def test_file_cancel_never_uses_repo_wide_legacy_kill(self):
        job=dict(id='owned',repo_id='org/model',file_mode=True,status='running')
        with mock.patch.dict(WP._jobs,{'owned':job}),mock.patch.object(WP,'kill_local_fetch') as kill:
            callback=mock.Mock(return_value={'ok':True})
            self.assertTrue(WP.cancel_job('owned',kill_procs=callback)['ok'])
            kill.assert_not_called();callback.assert_called_once()
            failed=WP.cancel_job('owned',kill_procs=lambda *a:{'ok':False})
            self.assertFalse(failed['ok']);self.assertIn('confirm',failed['job']['error'])

    def test_restart_active_transfer_blocks_duplicate_job(self):
        _,_,nodes=model();app=types.SimpleNamespace(configured_nodes=lambda:nodes)
        plan=dict(repo_id='org/model',model_id='m',counts=[4]*3,node_ids=[n['id'] for n in nodes],stages=[dict(id=n['id']) for n in nodes],file_requests=[dict(format='mlx',revision='a'*40,dest='/own/'+n['id']) for n in nodes])
        with mock.patch.object(WP,'list_jobs',return_value=[]),mock.patch.object(WF,'active',return_value=[{'repo_id':'org/model'}]),self.assertRaisesRegex(ValueError,'still running'):
            WF.start(app,plan)





class TwoStageSavedBalance(unittest.TestCase):
    def test_fetch_saves_legacy_packer_count_too(self):
        _,_,nodes=model(2);app=types.SimpleNamespace(configured_nodes=lambda:nodes)
        plan=dict(repo_id='org/model',model_id='m',counts=[5,7],node_ids=[n['id'] for n in nodes],
                  stages=[dict(id=n['id'],label=n['label'],downloads=[]) for n in nodes],
                  file_requests=[dict(format='mlx',revision='a'*40,dest='/own/'+n['id']) for n in nodes])
        with mock.patch.object(WF,'active',return_value=[]),mock.patch.object(WP,'list_jobs',return_value=[]),mock.patch.object(WP,'start_download',return_value={'id':'j'}) as start,mock.patch.object(WP,'_job_set'),mock.patch.object(WP,'get_job',return_value={'id':'j'}):
            WF.start(app,plan)
        self.assertEqual(start.call_args.kwargs['placement']['packer_layers'],5)
        self.assertEqual(start.call_args.kwargs['placement']['split_counts'],[5,7])


if __name__=='__main__':unittest.main()
