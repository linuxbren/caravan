from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import gguf_shards as s


class Ownership(unittest.TestCase):
    def test_n_minis_unique_cover(self):
        for n in (1,2,3,4,8,64):
            names=[f'blk.{i}.weight' for i in range(24)]+['output.weight','output_norm.weight','token_embd.weight','other.weight']
            own=s.owners(24,[1]*n,names)
            self.assertEqual(set(own),set(names))
            self.assertTrue(all(0<=i<n for i in own.values()))
            self.assertEqual(own['token_embd.weight'],0)
            self.assertEqual(own['other.weight'],0)
            self.assertEqual(own['output.weight'],next(i for i in range(n) if 24 in s.device_layers(24,[1]*n,i,pad=0)))

    def test_matches_existing_split_plan(self):
        for shares in ([1,1],[1,2,1],[3,1,2,4]):
            names=[f'blk.{i}.weight' for i in range(24)]+['output.weight']
            own=s.owners(24,shares,names)
            for i in range(len(shares)):
                layers=s.device_layers(24,shares,i,pad=0)
                for j,name in enumerate(names): self.assertEqual(own[name]==i,j in layers)

    def test_invalid_shares(self):
        for text in ('','0','-1,1','nan,1','inf','1,,2'):
            with self.subTest(text=text),self.assertRaises(ValueError): s.shares_arg(text)

    def test_out_of_bounds_layer(self):
        with self.assertRaises(ValueError): s.owners(4,[1,1],['blk.4.weight'])

    def test_bad_block_count(self):
        for n in (0,-1,True):
            with self.assertRaises(ValueError): s.owners(n,[1],[])


@unittest.skipUnless(shutil.which('cc'),'needs native hash compiler')
class Pieces(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.d=Path(self.tmp.name)
        self.src=self.d/'source.gguf'
        self.src.write_bytes(b'GGUF'+b'\0'*124+bytes(range(64)))
        self.original=self.src.read_bytes()
        self.tensors=[SimpleNamespace(name=name,data_offset=128+i*16,n_bytes=16) for i,name in enumerate(
            ['token_embd.weight','blk.0.weight','blk.1.weight','output.weight'])]
        field=SimpleNamespace(parts=[[2]],data=[0])
        self.reader=SimpleNamespace(tensors=self.tensors,data_offset=128,fields={'qwen2.block_count':field})
        self.mock=patch.object(s,'_reader',return_value=self.reader);self.mock.start()
    def tearDown(self): self.mock.stop();self.tmp.cleanup()
    def create(self,idx=0): return s.create(self.src,self.d/f'stage-{idx}',[1,1],idx)
    def manifest(self,idx=0): return json.loads((self.d/f'stage-{idx}/manifest.json').read_text())
    def local(self):
        m=self.manifest(); t=next(t for t in m['tensors'] if t['owner']==0)
        return self.d/'stage-0/rpc'/t['key']

    def test_all_sizes_and_exact_local_bytes(self):
        a=self.create(0); b=self.create(1)
        self.assertEqual(a['tensor_bytes']+b['tensor_bytes'],64)
        self.assertEqual(a['tensors']+b['tensors'],4)
        self.assertTrue(a['ok'] and b['ok'])
        self.assertEqual(self.src.read_bytes(),self.original)
        self.assertEqual(self.manifest(0)['source_sha256'],self.manifest(1)['source_sha256'])
        self.assertEqual((self.d/'stage-0/model.cvgg').read_bytes(),s.MAGIC+self.original[:128])
        self.assertEqual({p.name for p in (self.d/'stage-0/rpc').iterdir()} &
                         {p.name for p in (self.d/'stage-1/rpc').iterdir()},set())

    def test_refuse_existing_root(self):
        self.create()
        before=self.local().read_bytes()
        with self.assertRaises(FileExistsError): self.create()
        self.assertEqual(self.local().read_bytes(),before)

    def test_refuse_root_equal_source(self):
        with self.assertRaises(FileExistsError): s.create(self.src,self.src,[1],0)
        self.assertEqual(self.src.read_bytes(),self.original)

    def test_refuse_linked_output(self):
        root=self.d/'linked'; root.symlink_to(self.d,target_is_directory=True)
        with self.assertRaises(FileExistsError): s.create(self.src,root,[1],0)

    def test_invalid_index(self):
        for idx in (-1,2,True):
            with self.assertRaises(ValueError): s.create(self.src,self.d/'x',[1,1],idx)
        self.assertFalse((self.d/'x').exists())

    def test_bad_tensor_range(self):
        self.tensors[0].data_offset=999
        with self.assertRaises(ValueError): self.create()
        self.assertFalse((self.d/'stage-0').exists())

    def test_overlapping_ranges(self):
        self.tensors[1].data_offset=128
        with self.assertRaises(ValueError): self.create()

    def test_duplicate_tensor_names(self):
        self.tensors[1].name=self.tensors[0].name
        with self.assertRaises(ValueError): self.create()

    def test_malicious_tensor_name(self):
        self.tensors[0].name='../escape'
        with self.assertRaises(ValueError): self.create()

    def test_missing_piece(self):
        self.create();self.local().unlink()
        with self.assertRaisesRegex(ValueError,'missing or corrupt'): s.verify(self.d/'stage-0')

    def test_same_size_corruption(self):
        self.create();p=self.local();p.write_bytes(b'x'*p.stat().st_size)
        with self.assertRaisesRegex(ValueError,'missing or corrupt'): s.verify(self.d/'stage-0')

    def test_truncated_piece(self):
        self.create();self.local().write_bytes(b'x')
        with self.assertRaises(ValueError): s.verify(self.d/'stage-0')

    def test_linked_piece(self):
        self.create();p=self.local();p.unlink();p.symlink_to(self.src)
        with self.assertRaises(ValueError): s.verify(self.d/'stage-0')

    def test_extra_piece(self):
        self.create();(self.d/'stage-0/rpc/extra').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'unexpected'): s.verify(self.d/'stage-0')

    def test_catalog_corrupt(self):
        self.create();(self.d/'stage-0/model.cvgg').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'checksum'): s.verify(self.d/'stage-0')

    def test_table_corrupt(self):
        self.create();(self.d/'stage-0/weights.tsv').write_text('bad')
        with self.assertRaisesRegex(ValueError,'checksum'): s.verify(self.d/'stage-0')

    def test_manifest_wrong_owner(self):
        self.create();p=self.d/'stage-0/manifest.json';m=json.loads(p.read_text());m['tensors'][0]['owner']=1;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError): s.verify(p.parent)

    def test_native_fnv(self):
        exe=s._hash_bin()
        try:
            r=subprocess.run([str(exe),str(self.src)],input='128 16\n',text=True,capture_output=True,check=True)
            h=0xcbf29ce484222325
            for x in bytes(range(16)): h=((h^x)*0x100000001b3)&0xffffffffffffffff
            self.assertEqual(r.stdout.strip(),f'{h:016x}')
        finally: exe.unlink();exe.parent.rmdir()

    def test_native_refuses_outside_source(self):
        exe=s._hash_bin()
        try:
            p=subprocess.run([str(exe),str(self.src)],input='190 16\n',text=True,capture_output=True)
            self.assertNotEqual(p.returncode,0)
        finally: exe.unlink();exe.parent.rmdir()


class Launch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
        self.root=self.d/'shards';self.root.mkdir()
        (self.root/'manifest.json').write_text(json.dumps(dict(shares=[1,2,1])))
        work=self.d/'runtime';self.exe=work/'build/bin/llama-server';self.exe.parent.mkdir(parents=True);self.exe.touch()
        self.marker=work/'caravan-shards-version';self.marker.write_text('catalog-v1/76a67730ffc7d650dffa4db04d96be84a59e7ef3')
        self.ver=patch.object(s,'verify',return_value=dict(stage_index=0,n_minis=3));self.mock=self.ver.start()
    def tearDown(self):self.ver.stop();self.tmp.cleanup()
    def test_n_peer_args_and_verification(self):
        args,env=s.serving_command(self.root,self.exe,rpc=['127.0.0.1:50072','127.0.0.1:50073'])
        self.mock.assert_called_once_with(self.root)
        self.assertIn('MTL0,RPC0,RPC1',args);self.assertIn('1,2,1',args)
        self.assertIn(str(self.root/'model.cvgg'),args);self.assertEqual(env['CARAVAN_STRICT_SHARDS'],'1')
        self.assertEqual(env['LLAMA_CACHE'],str(self.root))
    def test_missing_peer_rejected(self):
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe,rpc=['127.0.0.1:50072'])
    def test_non_loopback_rpc_rejected(self):
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe,rpc=['remote:50072','127.0.0.1:50073'])
    def test_privileged_rpc_port_rejected(self):
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe,rpc=['127.0.0.1:22','127.0.0.1:50073'])
    def test_unmarked_stock_binary_rejected(self):
        self.marker.unlink()
        with self.assertRaisesRegex(ValueError,'isolated'):s.serving_command(self.root,self.exe)
    def test_wrong_version_rejected(self):
        self.marker.write_text('wrong')
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe)
    def test_peer_cache_env_and_loopback(self):
        self.mock.return_value=dict(stage_index=2,n_minis=3)
        args,env=s.serving_command(self.root,self.exe,peer=True,port=50062)
        self.assertEqual(args[-5:],['-H','127.0.0.1','-p','50062','-c'])
        self.assertEqual(env['LLAMA_CACHE'],str(self.root))
    def test_wrong_stage_role_rejected(self):
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe,peer=True)
        self.mock.return_value=dict(stage_index=1,n_minis=3)
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe)
    def test_privileged_listen_port_rejected(self):
        with self.assertRaises(ValueError):s.serving_command(self.root,self.exe,port=22)


class RuntimePatch(unittest.TestCase):
    def test_strict_source_anchors(self):
        path=Path(__file__).resolve().parents[1]/'runtime/gguf-shards/apply.py'
        spec=importlib.util.spec_from_file_location('day22_patch',path); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        self.assertEqual(mod.replace_once('abc','b','x'),'axc')
        for text in ('abc','bb'):
            with self.assertRaises(ValueError): mod.replace_once(text,'b' if text=='bb' else 'z','x')

    def test_runtime_has_no_weight_transfer_fallback(self):
        root=Path(__file__).resolve().parents[1]/'runtime/gguf-shards'
        patch_text=(root/'apply.py').read_text()
        helper=patch_text.split('static bool caravan_rpc_load_hash',1)[1].split("\n'''",1)[0]
        self.assertNotIn('RPC_CMD_SET_TENSOR,',helper)
        self.assertIn('RPC_CMD_SET_TENSOR_HASH',helper)
        self.assertIn('size != ggml_nbytes(tensor)',patch_text)
        self.assertIn('fnv_hash(cached_file.data(),size)',patch_text)

if __name__=='__main__': unittest.main()
