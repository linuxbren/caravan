from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import gguf_original_guard as g


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
        self.src=self.d/g.PARENT/g.NAME;self.src.parent.mkdir();self.src.write_bytes(b'x'*64)
        self.root=self.d/'stage';self.root.mkdir();self.now=time.time_ns()
        self.m=dict(shares=[1,1],stage_index=0,source_name=g.NAME,source_sha256=hashlib.sha256(b'x'*64).hexdigest(),
                    source_bytes=64,catalog_sha256='a'*64,tensors=[dict(name='blk.0.weight',owner=0,size=8),dict(name='output.weight',owner=1,size=16)])
        (self.root/'manifest.json').write_text(json.dumps(self.m))
        self.sha=self.m['source_sha256'];self.record=dict(repo_id=g.REPO,filename=g.NAME,revision='c'*40,sha256=self.sha,size=64)
        self.exe=self.d/'runtime/build/bin/llama-server';self.exe.parent.mkdir(parents=True);self.exe.touch()
        (self.exe.parents[2]/'caravan-shards-version').write_text('catalog-v1/'+g.PIN)
        self.proc=dict(command=shlex.join([str(self.exe),'-m',str(self.root/'model.cvgg')]),started='Tue Nov 10 18:40:00 2026')
        stage=dict(index=0,root=str(self.root),manifest_sha256=g.shards.digest(self.root/'manifest.json'),
                   catalog_sha256='a'*64,loaded_tensors=1,loaded_bytes=8,
                   loaded_names_sha256=hashlib.sha256(b'blk.0.weight').hexdigest(),pid=111,process=self.proc,binary=str(self.exe))
        peer=dict(stage,index=1,root=str(self.d/'peer'),pid=222)
        self.proof=dict(schema='caravan-gguf-removal-live-v1',source_sha256=self.sha,transaction='d'*32,created_ns=self.now,
                        load=dict(ok=True,fresh_process=True,runtime_pin=g.PIN,started_ns=self.now-3_000_000_000,ready_ns=self.now-2_000_000_000),
                        chat=dict(ok=True,text_sha256=g.BASELINE,completion_tokens=128,prompt_tokens=55,cache_n=0,temperature=0,
                                  started_ns=self.now-1_000_000_000,finished_ns=self.now),stages=[stage,peer])
        self.status=dict(worker=dict(status='ready',model_id=g.HUIHUI,lead_pid=1055,balance=dict(counts=[24,40])),
                         restore=dict(last_model=g.HUIHUI),active=dict(kv_bits=16))
        self.patches=[patch.object(g,'SHA',self.sha),patch.object(g,'SIZE',64),
                      patch.object(g.shards,'verify',return_value=dict(ok=True,stage_index=0)),
                      patch.object(g,'available',return_value=10_000)]
        for p in self.patches:p.start()
        self.fetch=lambda r:True;self.process=lambda pid:dict(self.proc);self.opened=lambda p:True
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def gate(self,**kw):
        return g.preflight(self.src,self.root,self.record,self.proof,self.status,now_ns=self.now,
                           fetch=kw.get('fetch',self.fetch),process=kw.get('process',self.process),opened=kw.get('opened',self.opened))
    def batch(self):
        r=self.gate();peer=copy.deepcopy(r);peer.update(stage_index=1,root=str(self.d/'peer'))
        return dict(schema='caravan-gguf-removal-batch-v1',gates=[r,peer])
    def remove(self,batch=None,journal=None,**kw):
        return g.remove_original(self.src,self.root,self.record,self.proof,self.status,batch or self.batch(),journal or self.d/'audit.jsonl',
                                 fetch=self.fetch,process=self.process,opened=self.opened,**kw)
    def fail_keeps(self):
        with self.assertRaises((g.GateError,ValueError,OSError)):self.gate()
        self.assertTrue(self.src.exists())
    def test_dry_run_exact_path_hash_bytes_no_delete(self):
        r=self.gate();self.assertTrue(r['gate_passed']);self.assertEqual(len(r['will_remove']),1)
        self.assertEqual(r['will_remove'][0]['path'],str(self.src));self.assertEqual(r['will_remove'][0]['size'],64)
        self.assertEqual(r['will_remove'][0]['sha256'],self.sha);self.assertTrue(self.src.exists())
    def test_other_model_filename_never_allowed(self):
        original=self.src;self.src=self.src.with_name('other.gguf');self.src.write_bytes(b'x'*64)
        self.fail_keeps();self.assertTrue(original.exists())
    def test_wrong_parent_never_allowed(self):
        self.src=self.d/g.NAME;self.src.write_bytes(b'x'*64);self.fail_keeps()
    def test_symlink_original_refused(self):
        p=self.src;real=self.d/'real';p.rename(real);p.symlink_to(real)
        self.fail_keeps();self.assertTrue(real.exists())
    def test_hardlink_original_refused(self):
        os.link(self.src,self.d/'other-link');self.fail_keeps()
    def test_corrupt_original_same_size_refused(self):
        self.src.write_bytes(b'z'*64);self.fail_keeps()
    def test_wrong_original_size_refused(self):
        self.src.write_bytes(b'x');self.fail_keeps()
    def test_missing_piece_stops_gate(self):
        with patch.object(g.shards,'verify',side_effect=ValueError('missing tensor')):self.fail_keeps()
    def test_wrong_repo_refused(self):
        self.record['repo_id']='other/model';self.fail_keeps()
    def test_unpinned_revision_refused(self):
        self.record['revision']='main';self.fail_keeps()
    def test_source_hash_mismatch_refused(self):
        self.record['sha256']='e'*64;self.fail_keeps()
    def test_source_catalog_mismatch_refused(self):
        self.m['source_name']='other.gguf';(self.root/'manifest.json').write_text(json.dumps(self.m));self.fail_keeps()
    def test_source_network_failure_refuses_without_deletion(self):
        def bad(r):raise OSError('network unavailable')
        with self.assertRaises(OSError):self.gate(fetch=bad)
        self.assertTrue(self.src.exists())
    def test_current_production_not_huihui_blocks(self):
        self.status['worker']['model_id']='gguf/'+g.NAME[:-5];self.fail_keeps()
    def test_saved_restore_not_huihui_blocks(self):
        self.status['restore']['last_model']='gguf/'+g.NAME[:-5];self.fail_keeps()
    def test_missing_production_state_blocks(self):
        self.status={};self.fail_keeps()
    def test_huihui_split_settings_guard(self):
        self.status['active']['kv_bits']=8;self.fail_keeps()
    def test_stale_proof_refused(self):
        self.proof['created_ns']=self.now-301_000_000_000;self.fail_keeps()
    def test_future_proof_refused(self):
        self.proof['created_ns']=self.now+1;self.fail_keeps()
    def test_not_fresh_load_refused(self):
        self.proof['load']['fresh_process']=False;self.fail_keeps()
    def test_failed_load_refused(self):
        self.proof['load']['ok']=False;self.fail_keeps()
    def test_old_load_with_refreshed_timestamp_refused(self):
        self.proof['load']['started_ns']=self.now-400_000_000_000;self.fail_keeps()
    def test_chat_mismatch_refused(self):
        self.proof['chat']['text_sha256']='f'*64;self.fail_keeps()
    def test_cached_prompt_refused(self):
        self.proof['chat']['cache_n']=54;self.fail_keeps()
    def test_missing_stage_refused(self):
        self.proof['stages'].pop();self.fail_keeps()
    def test_duplicate_stage_refused(self):
        self.proof['stages'][1]['index']=0;self.fail_keeps()
    def test_wrong_local_catalog_binding_refused(self):
        self.proof['stages'][0]['manifest_sha256']='0'*64;self.fail_keeps()
    def test_missing_native_tensor_load_refused(self):
        self.proof['stages'][0]['loaded_tensors']=0;self.fail_keeps()
    def test_wrong_native_loaded_names_refused(self):
        self.proof['stages'][0]['loaded_names_sha256']='1'*64;self.fail_keeps()
    def test_reused_pid_refused(self):
        with self.assertRaises(g.GateError):self.gate(process=lambda p:dict(self.proc,started='different start'))
        self.assertTrue(self.src.exists())
    def test_original_open_in_process_blocks(self):
        def opened(p):raise g.GateError('open by a process')
        with self.assertRaises(g.GateError):self.gate(opened=opened)
        self.assertTrue(self.src.exists())
    def test_live_full_gguf_argv_refused(self):
        self.proc['command']=shlex.join([str(self.exe),'-m',str(self.src)])
        self.fail_keeps()
    def test_unmarked_runtime_refused(self):
        (self.exe.parents[2]/'caravan-shards-version').unlink();self.fail_keeps()
    def test_batch_requires_all_minis(self):
        b=self.batch();b['gates'].pop()
        with self.assertRaises(g.GateError):self.remove(batch=b)
        self.assertTrue(self.src.exists())
    def test_failed_peer_gate_deletes_nothing(self):
        b=self.batch();b['gates'][1]['gate_passed']=False
        with self.assertRaises(g.GateError):self.remove(batch=b)
        self.assertTrue(self.src.exists());self.assertFalse((self.d/'audit.jsonl').exists())
    def test_stale_batch_deletes_nothing(self):
        b=self.batch();b['gates'][1]['checked_ns']=self.now-130_000_000_000
        with self.assertRaises(g.GateError):self.remove(batch=b)
        self.assertTrue(self.src.exists())
    def test_batch_different_transaction_deletes_nothing(self):
        b=self.batch();b['gates'][1]['transaction']='e'*32
        with self.assertRaises(g.GateError):self.remove(batch=b)
        self.assertTrue(self.src.exists())
    def test_changed_source_since_batch_blocks(self):
        b=self.batch();replacement=self.d/'replacement';replacement.write_bytes(b'x'*64);replacement.replace(self.src)
        with self.assertRaises(g.GateError):self.remove(batch=b)
        self.assertTrue(self.src.exists())
    def test_intent_write_failure_deletes_nothing(self):
        with patch.object(g,'append_journal',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.remove()
        self.assertTrue(self.src.exists())
    def test_commit_removes_exactly_one_and_logs_sha(self):
        untouched=self.src.with_name('keep.gguf');untouched.write_bytes(b'keep')
        row=self.remove();self.assertFalse(self.src.exists());self.assertEqual(untouched.read_bytes(),b'keep')
        self.assertEqual(row['sha256'],self.sha);self.assertEqual(row['logical_bytes_removed'],64)
        rows=[json.loads(l) for l in (self.d/'audit.jsonl').read_text().splitlines()]
        self.assertEqual([x['event'] for x in rows],['removal-intent','removed'])
        self.assertEqual(rows[0]['gate']['will_remove'][0]['sha256'],self.sha)
    def test_linked_journal_refused_without_removal(self):
        target=self.d/'other';target.write_text('keep');journal=self.d/'audit.jsonl';journal.symlink_to(target)
        with self.assertRaises(g.GateError):self.remove(journal=journal)
        self.assertTrue(self.src.exists());self.assertEqual(target.read_text(),'keep')
    def test_final_audit_error_reports_already_removed(self):
        real=g.append_journal;calls=[]
        def journal(p,row):
            calls.append(row)
            if len(calls)==2:raise OSError('late audit failure')
            real(p,row)
        with patch.object(g,'append_journal',side_effect=journal):
            with self.assertRaises(g.RemovedButAuditFailed) as e:self.remove()
        self.assertFalse(self.src.exists());self.assertEqual(e.exception.result['event'],'removed')


class SourceMetadata(unittest.TestCase):
    def record(self):return dict(revision='a'*40)
    def response(self,**changes):
        d=dict(id=g.REPO,sha='a'*40,private=False,gated=False,siblings=[dict(rfilename=g.NAME,size=g.SIZE,lfs=dict(sha256=g.SHA))]);d.update(changes);return d
    def fetch(self,data):
        import io
        return patch.object(g.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(data).encode()))
    def test_pinned_public_source_matches(self):
        with self.fetch(self.response()):self.assertEqual(g.remote_source(self.record())['sha256'],g.SHA)
    def test_changed_revision_blocks(self):
        with self.fetch(self.response(sha='b'*40)):
            with self.assertRaises(g.GateError):g.remote_source(self.record())
    def test_private_or_gated_source_blocks(self):
        for k in ('private','gated'):
            with self.fetch(self.response(**{k:True})):
                with self.assertRaises(g.GateError):g.remote_source(self.record())
    def test_wrong_lfs_sha_blocks(self):
        d=self.response();d['siblings'][0]['lfs']['sha256']='c'*64
        with self.fetch(d):
            with self.assertRaises(g.GateError):g.remote_source(self.record())
    def test_missing_source_file_blocks(self):
        with self.fetch(self.response(siblings=[])):
            with self.assertRaises(g.GateError):g.remote_source(self.record())


class OSChecks(unittest.TestCase):
    def test_lsof_empty_success_is_not_assumed_clear(self):
        for code,stdout,stderr in [(0,'p123\nn/model.gguf\n',''),(1,'','warning'),(2,'','error')]:
            with patch.object(g.subprocess,'run',return_value=type('P',(),dict(returncode=code,stdout=stdout,stderr=stderr))()):
                with self.assertRaises(g.GateError):g.no_open_file('/model.gguf')
    def test_lsof_negative_empty_means_clear(self):
        with patch.object(g.subprocess,'run',return_value=type('P',(),dict(returncode=1,stdout='',stderr=''))()):
            self.assertTrue(g.no_open_file('/model.gguf'))

if __name__=='__main__':unittest.main()
