import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from verify_block import cache_plan
from native_mtp import validate_pair, head_path

class VerifyBlockTests(unittest.TestCase):
    def test_rejection_each_boundary(self):
        for k in range(1, 9):
            for accepted in range(k):
                p = cache_plan(k, accepted)
                self.assertEqual(k + 1 - p["target_trim"], accepted + 1)
                self.assertEqual(k - p["draft_trim"], accepted + 1)
                self.assertFalse(p["replay_last_draft"])
    def test_all_accepted_replays_last_draft(self):
        for k in range(1, 9):
            self.assertEqual(cache_plan(k, k), dict(target_trim=0, draft_trim=0, replay_last_draft=True))
    def test_stops_inside_draft_always_rewind(self):
        for k in range(1, 9):
            for accepted in range(1, k+1):
                p = cache_plan(k, accepted, stopped_in_draft=True)
                self.assertEqual(k+1-p["target_trim"], accepted)
                self.assertEqual(k-p["draft_trim"], accepted)
                self.assertFalse(p["replay_last_draft"])
    def test_no_draft(self):
        self.assertEqual(cache_plan(0,0),dict(target_trim=0,draft_trim=0,replay_last_draft=False))
    def test_invalid(self):
        for args in [(-1,0),(2,3),(1,-1)]:
            with self.assertRaises(ValueError): cache_plan(*args)

class NativePairTests(unittest.TestCase):
    def test_matching_and_mismatch(self):
        c = dict(hidden_size=2560,vocab_size=248320,num_hidden_layers=32,intermediate_size=9216)
        h = dict(text_config=c,target_repo="Orvena/Orvena-4B-MLX-4bit")
        self.assertEqual(validate_pair(dict(model_type="qwen3_5",text_config=c),h),c)
        with self.assertRaises(ValueError):
            validate_pair(dict(model_type="qwen3",text_config=c),h)
        with self.assertRaises(ValueError):
            validate_pair(dict(model_type="qwen3_5",text_config={**c,"hidden_size":2048}),h)
    def test_absent_head(self):
        self.assertIsNone(head_path("/no/such/checkpoint"))

class WorkerBlockTests(unittest.TestCase):
    def test_real_worker_block_rewinds_and_replays(self):
        import contextlib
        import types
        from unittest.mock import patch
        import mlx_worker as W
        class Token:
            def __init__(self,n): self.n=n
            def flatten(self): return self
            def __getitem__(self,k): return self
            def item(self): return self.n
        class Logits:
            ndim=3
            def __init__(self,vals): self.vals=vals; self.shape=(1,len(vals),100)
            def __getitem__(self,k): return self.vals[k[1]]
        for proposed,sampled,stop_at in [([10,11,12],[10,11,12,13],None),
                                        ([10,11,12],[10,99,12,13],None),
                                        ([10,11,12],[99,11,12,13],None),
                                        ([10,11,12],[10,11,12,13],1)]:
            with self.subTest(sampled=sampled,stop=stop_at):
                e=W.Engine.__new__(W.Engine)
                trims=[]; draft_trims=[]; emissions=[]
                e.mx=types.SimpleNamespace(stream=lambda s:contextlib.nullcontext(),
                    eval=lambda *a:None,array=lambda ids,dtype:ids,uint32=None)
                e.G=None;e.stream=None;e.wired_mode=None
                e.draft_model=object();e.draft_remap_t2d={}
                e.model=types.SimpleNamespace(session_key=None,
                    lead_logits=lambda h,c:Logits(sampled),
                    trim_caches=lambda n,c:trims.append(n))
                slot=types.SimpleNamespace(h=object(),finished=False,
                    cancel=types.SimpleNamespace(is_set=lambda:False),key="chat-a",
                    pending_draft=proposed,h_n=4,session=types.SimpleNamespace(cache=[]),
                    all_tokens=[5],procs=None,sampler=lambda n:Token(n),draft_cache=[],n_gen=0)
                def emit(s,t,from_draft=False):
                    emissions.append((t,from_draft));s.all_tokens.append(t);s.n_gen+=1
                    return "stop" if stop_at and s.n_gen==stop_at else None
                e._pipe_emit_token=emit
                fake=types.ModuleType("mlx_lm.models.cache")
                fake.trim_prompt_cache=lambda c,n:(draft_trims.append(n) or n)
                with patch.object(W,"request_wiring",lambda *a:contextlib.nullcontext()), patch.dict(sys.modules,{"mlx_lm.models.cache":fake}):
                    e._pipe_lead_sample(slot)
                if stop_at:
                    self.assertEqual(emissions,[(10,True)])
                    self.assertEqual(trims,[3]);self.assertEqual(draft_trims,[2])
                    self.assertTrue(slot.finished)
                elif sampled[0]==99:
                    self.assertEqual(emissions,[(99,False)])
                    self.assertEqual(trims,[3]);self.assertEqual(draft_trims,[2])
                elif sampled[1]==99:
                    self.assertEqual(emissions,[(10,True),(99,False)])
                    self.assertEqual(trims,[2]);self.assertEqual(draft_trims,[1])
                else:
                    self.assertEqual(emissions,[(10,True),(11,True),(12,True),(13,False)])
                    self.assertEqual(trims,[]);self.assertEqual(draft_trims,[])
                    self.assertEqual(slot.draft_y,[12,13])
                self.assertEqual(slot.pending_draft,[])

class WebFlagTests(unittest.TestCase):
    def test_experimental_options_are_real_and_explicit(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"proxy"))
        import web_settings as S
        lead,_=S.to_args({"guess_ahead":"mtp"})
        self.assertIn("--native-mtp",lead);self.assertIn("--no-learn",lead)
        lead,_=S.to_args({"prompt_lookup":"adaptive"})
        self.assertIn("--split-prompt-lookup-adaptive",lead)
        self.assertEqual(lead[-2:],["--split-pipeline-chats","1"])
        with self.assertRaises(ValueError):S.to_args({"prompt_lookup":"adaptive","pipeline_chats":"2"})
        lead,_=S.to_args({})
        self.assertNotIn("--native-mtp",lead)
        self.assertNotIn("--split-prompt-lookup-adaptive",lead)
