"""Hermes full-tool prefix reuse, auxiliary isolation, and managed proxy. No MLX."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'agent'), str(ROOT/'proxy'), str(ROOT/'tools')]
import mlx_worker as W
import service_config as SC
import slot_pin_proxy as P
from test_mlx_worker import FakeOps, IDENT, turn
from test_day19_balance import Pipeline


class Identity(unittest.TestCase):
    def body(self):
        return {'model':'mlx-community/test', 'messages':[{'role':'system','content':'full instructions'},
                {'role':'user','content':'hello'}], 'tools':[{'type':'function','function':{'name':'terminal'}}]}

    def test_title_no_longer_overwrites_main(self):
        main=self.body(); title=self.body(); title['messages'][0]['content']='Generate title'; title.pop('tools')
        self.assertEqual(P.session_fingerprint(main),P.session_fingerprint(title))
        self.assertNotEqual(P.mlx_session_fingerprint(main),P.mlx_session_fingerprint(title))

    def test_growing_history_has_same_key(self):
        a=self.body(); b=copy.deepcopy(a); b['messages'] += [{'role':'assistant','content':'hi'},{'role':'user','content':'next'}]
        self.assertEqual(P.mlx_session_fingerprint(a),P.mlx_session_fingerprint(b))

    def test_template_inputs_are_scoped(self):
        a=self.body()
        for key,value in [('tools',[]),('thinking',False),('chat_template_kwargs',{'enable_thinking':False}),('model','other')]:
            b=copy.deepcopy(a);b[key]=value
            self.assertNotEqual(P.mlx_session_fingerprint(a),P.mlx_session_fingerprint(b))

    def test_json_dictionary_order_does_not_change_identity(self):
        a=self.body();b=json.loads(json.dumps(a,sort_keys=True))
        self.assertEqual(P.mlx_session_fingerprint(a),P.mlx_session_fingerprint(b))

    def test_fifo_status_does_not_enqueue_diagnostics(self):
        gate=P.FifoGate();self.assertEqual(gate.status(),{"active":False,"waiting":0})
        ticket,_,_=gate.acquire();self.assertEqual(gate.status(),{"active":True,"waiting":0})
        gate.release(ticket);self.assertFalse(gate.status()["active"])

    def test_prompt_and_ephemeral_calls_unchanged(self):
        for b in [{}, {'prompt':'a'*3000}, {'messages':[]}]:
            self.assertEqual(P.mlx_session_fingerprint(b),P.session_fingerprint(b))


class Tokenizer:
    def apply_chat_template(self, msgs, **kw):
        tools=json.dumps(kw.get('tools',[]),sort_keys=True)
        return [ord(c) for c in tools + ''.join(m['role']+':'+m['content']+'\n' for m in msgs)+'assistant:']


class Boundary(unittest.TestCase):
    def setUp(self):
        self.e=W.Engine.__new__(W.Engine);self.e.tokenizer=Tokenizer();self.e.prefill_step=2048
        self.b={'tools':[{'name':'tool','description':'x'*1500}], 'messages':[{'role':'system','content':'system'}, {'role':'user','content':'first'}]}

    def test_exact_prefix_before_first_user_content(self):
        t=self.e.chat_prompt(self.b);n=self.b['_caravan_agent_prefix']
        other=copy.deepcopy(self.b);other['messages'][1]['content']='other';u=self.e.chat_prompt(other)
        self.assertEqual(t[:n],u[:n]);self.assertEqual(n,other['_caravan_agent_prefix'])

    def test_followup_preserves_boundary(self):
        t=self.e.chat_prompt(self.b);n=self.b['_caravan_agent_prefix']
        self.b['messages'] += [{'role':'assistant','content':'reply'},{'role':'user','content':'next'}]
        u=self.e.chat_prompt(self.b);self.assertEqual(n,self.b['_caravan_agent_prefix']);self.assertEqual(t[:n],u[:n])

    def test_changed_tools_never_reused_as_same_prefix(self):
        t=self.e.chat_prompt(self.b);key,_=self.e._agent_prefix_key(t,self.b)
        self.b['tools'][0]['description']='y'*1500
        u=self.e.chat_prompt(self.b);self.assertNotEqual(key,self.e._agent_prefix_key(u,self.b)[0])

    def test_untrusted_client_boundary_is_removed(self):
        self.b.pop('tools');self.b['_caravan_agent_prefix']=1234
        self.e.chat_prompt(self.b);self.assertNotIn('_caravan_agent_prefix',self.b)

    def test_openai_reasoning_none_is_honored(self):
        self.b["reasoning_effort"]="none"
        with mock.patch.object(W,"thinking_kwargs",return_value=({},False)) as fn:
            self.e.chat_prompt(self.b)
        self.assertFalse(fn.call_args.args[1])

    def test_explicit_thinking_wins(self):
        self.b.update(reasoning_effort="none",thinking=True)
        with mock.patch.object(W,"thinking_kwargs",return_value=({},False)) as fn:
            self.e.chat_prompt(self.b)
        self.assertTrue(fn.call_args.args[1])

    def test_short_prompts_stay_normal(self):
        self.b['tools']=[];self.e.chat_prompt(self.b)
        self.assertNotIn('_caravan_agent_prefix',self.b)

    def test_chunks_cut_exactly_at_checkpoint(self):
        t=list(range(7000)); chunks=list(self.e._prefill_chunks(t,0,{'_caravan_agent_prefix':3217}))
        self.assertIn((2048,3217,True),chunks)
        self.assertEqual([x for a,b,_ in chunks for x in t[a:b]],t[:-1])

    def test_reused_boundary_is_not_recaptured(self):
        chunks=list(self.e._prefill_chunks(list(range(7000)),3217,{'_caravan_agent_prefix':3217}))
        self.assertFalse(any(boundary for _,_,boundary in chunks))


class PrefixReuse(unittest.TestCase):
    def setup_engine(self, root, stages):
        e=W.Engine.__new__(W.Engine); e.prefill_step=512; e.shared_prefix_enabled=False
        if stages==1:
            e.store=W.SessionStore(FakeOps(),Path(root)/'single',IDENT,max_sessions=99)
            e.client=e.split=None;p=None
        else:
            p=Pipeline(root,stages);e.store=p.stores[-1];e.client=p.client;e.split=p.split
        return e,p

    def prefill(self,e,key,prompt,body):
        s,n,how=e._prepare_agent_prefix(key,prompt,body)
        for a,b,boundary in e._prefill_chunks(prompt,n,body):
            if e.client:e.client.call('fwd',tokens=prompt[a:b],ctx='session',key=key)
            for c in s.cache:c.feed(prompt[a:b])
            if boundary:
                e.s_checkpoint(s,prompt[:b]);e._store_agent_prefix(key,prompt,body,s)
        e.s_checkpoint(s,prompt[:-1]);e.s_rewind(s)
        return n,how

    def run_case(self,stages, disk=False,missing=False):
        with tempfile.TemporaryDirectory() as root:
            e,p=self.setup_engine(root,stages)
            try:
                prompt=list(range(1600));body={'_caravan_agent_prefix':1400}
                self.assertEqual(self.prefill(e,'chat_a',prompt,body)[0],0)
                reserved,_=e._agent_prefix_key(prompt,body)
                stores=p.stores if p else [e.store]
                if disk:
                    for st in stores:st.sessions.clear()
                if missing:
                    (stores[0].cache_dir/f'{reserved}.safetensors').unlink()
                second=prompt[:1400]+[99999,2,3]
                n,how=self.prefill(e,'chat_b',second,body)
                self.assertEqual(n,0 if missing else 1400)
                for st in stores:self.assertEqual(st.sessions['chat_b'].tokens,second[:-1])
                if not missing:self.assertIn('agent-prefix',how)
                # A longer same-session checkpoint wins over the shared prefix.
                n,how=self.prefill(e,'chat_b',second+[4,5],body)
                self.assertEqual(n,len(second)-1)
            finally:
                if p:p.close()

    def test_single_recurrent_wrapped_cache(self):self.run_case(1)
    def test_two_stages(self):self.run_case(2)
    def test_three_stages(self):self.run_case(3)
    def test_five_stages(self):self.run_case(5)
    def test_disk_single(self):self.run_case(1,disk=True)
    def test_disk_three(self):self.run_case(3,disk=True)
    def test_missing_stage_refuses_prefix(self):self.run_case(3,disk=True,missing=True)

    def test_one_token_tail_divergence_reuses_exact_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            e,p=self.setup_engine(root,1)
            prompt=list(range(1600));body={'_caravan_agent_prefix':1400}
            self.prefill(e,'chat_a',prompt,body)
            changed=prompt[:1598]+[99999,3]
            n,how=self.prefill(e,'chat_a',changed,body)
            self.assertEqual(n,1400);self.assertIn('agent-prefix',how)

    def test_changed_prefix_is_cold_not_stale(self):
        with tempfile.TemporaryDirectory() as root:
            e,p=self.setup_engine(root,1)
            prompt=list(range(1600));body={'_caravan_agent_prefix':1400}
            self.prefill(e,'chat_a',prompt,body)
            changed=[99999]+prompt[1:]
            n,how=self.prefill(e,'chat_b',changed,body)
            self.assertEqual(n,0)

    def test_three_stage_wrapped_recurrent_state(self):
        with tempfile.TemporaryDirectory() as root:
            e,p=self.setup_engine(root,3)
            try:
                for st in p.stores:st.ops=FakeOps(('KVCache','RotatingKVCache'))
                prompt=list(range(1600));body={'_caravan_agent_prefix':1400}
                self.prefill(e,'chat_a',prompt,body)
                self.assertEqual(self.prefill(e,'chat_b',prompt[:1400]+[4,5,6],body)[0],1400)
                for st in p.stores:
                    self.assertEqual(st.sessions['chat_b'].cache[1].offset,1402)
            finally:p.close()

    def test_clone_failure_drops_partial_state(self):
        with tempfile.TemporaryDirectory() as root:
            e,p=self.setup_engine(root,2)
            try:
                prompt=list(range(1600));body={'_caravan_agent_prefix':1400}
                self.prefill(e,'chat_a',prompt,body)
                orig=e.client.call
                def fail(op,*a,**kw):
                    if op=='clone_to':return ({'error':'missing stage'},b'')
                    return orig(op,*a,**kw)
                with mock.patch.object(e.client,'call',side_effect=fail):
                    s,n,how=e._prepare_agent_prefix('chat_b',prompt,body)
                self.assertEqual(n,0);self.assertEqual(s.tokens,[])
            finally:p.close()


class ProxyService(unittest.TestCase):
    def test_render_and_load(self):
        with tempfile.TemporaryDirectory() as root:
            plan=SC.make_plan(kind='proxy',home=root,repo=ROOT,web_port=8090,lead_port=8194)
            plist=SC.render(plan)
            self.assertEqual(plist['EnvironmentVariables']['CARAVAN_PROXY_PORT'],'8090')
            self.assertTrue(plist['KeepAlive']);self.assertTrue(plist['RunAtLoad'])
            args=plist['ProgramArguments'];self.assertIn(str(ROOT/'proxy/slot_pin_proxy.py'),args)
            self.assertEqual(args[args.index('--mlx-port')+1],'8194')
            f=Path(root)/'proxy.json';f.write_text(json.dumps(plan));self.assertEqual(SC.load(f),plan)

    def test_proxy_never_exposes_public_socket(self):
        with self.assertRaises(ValueError):SC.make_plan(kind='proxy',host='0.0.0.0')

    def test_cli_proxy_default_port(self):
        import caravan_service as C
        import contextlib,io
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(C.main(['install','--kind','proxy','--dry-run']),0)
        self.assertEqual(json.loads(out.getvalue())['plan']['port'],8090)
