"""One-option trials, worker controls, hardware loss isolation and reload recovery."""
from __future__ import annotations
import copy
import os
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / 'agent'), str(REPO / 'proxy')]
import optimize_schedule as AB
import sweep_control
import tuned_settings as TS
import web_optimize as WO
import web_settings
from web_workers import WorkerManager

NODES = [dict(id='a', host='local', chip='Apple M4', cpus=10, ram={'total_gb': 32})]
ACTIVE = dict(self_tune=True, guess_ahead=False, guess_ahead_loaded=False,
              shared_start=False, pipeline_chats=1, keepalive=None,
              kv_bits=16, fuse_kernels='off', pinned=[])


class ScheduleTest(unittest.TestCase):
    def test_one_challenger_each(self):
        items = AB.schedule({}, {}, ACTIVE, 'hardware')
        trials = [i for i in items if not i['skip']]
        self.assertEqual([i['name'] for i in trials], ['kv_bits', 'fuse_kernels'])
        self.assertEqual([i['challenger'] for i in trials], [8, 'on'])

    def test_pin_and_block(self):
        e = {}; TS.block_value(e, 'kv_bits', 8, 'unsupported')
        items = AB.schedule(e, {'fuse_kernels': 'off'}, ACTIVE, 'x')
        self.assertEqual(next(i for i in items if i['name'] == 'kv_bits')['challenger'], 4)
        self.assertEqual(next(i for i in items if i['name'] == 'fuse_kernels')['skip'], 'pinned')

    def test_hardware_records_are_retained_and_isolated(self):
        e = {}
        AB.commit(e, 'a', 'kv_bits', 16, 8)
        AB.commit(e, 'b', 'kv_bits', 16, 4)
        self.assertEqual(AB.schedule(e, {}, ACTIVE, 'a')[3]['challenger'], 4)
        self.assertEqual(AB.schedule(e, {}, ACTIVE, 'b')[3]['challenger'], 8)
        self.assertEqual(AB.schedule(e, {}, ACTIVE, 'c')[3]['challenger'], 8)
        self.assertEqual(len(e['optimize_hardware']), 2)

    def test_fingerprint_arbitrary_node_count_stable_load_sensitive_hardware(self):
        for count in (1, 2, 3, 7):
            nodes = [dict(NODES[0], id=str(i)) for i in range(count)]
            fp = AB.fingerprint(nodes, split=count > 1)
            self.assertEqual(fp, AB.fingerprint(list(reversed(nodes)), split=count > 1))
            nodes[0]['ram'] = {'total_gb': 64, 'used_gb': 1}
            self.assertNotEqual(fp, AB.fingerprint(nodes, split=count > 1))
        n = copy.deepcopy(NODES); fp = AB.fingerprint(n, split=False)
        n[0]['cpu_pct'] = 99; n[0]['ram']['used_gb'] = 29
        self.assertEqual(fp, AB.fingerprint(n, split=False))
        n[0]['chip'] = 'Apple M5'
        self.assertNotEqual(fp, AB.fingerprint(n, split=False))
        with self.assertRaises(ValueError): AB.fingerprint([{'id': 'a'}], split=False)

    def test_incomplete_or_bad_results_never_promoted(self):
        for a,b in (([], []), ([10], []), ([10], [float('nan')]), ([0], [10])):
            with self.assertRaises(ValueError): AB.pick(a,b)
        self.assertFalse(AB.pick([10]*3, [10.2]*3))
        self.assertTrue(AB.pick([10]*3, [10.4]*3))

    def test_layer_cut_bounds(self):
        a = dict(ACTIVE, keepalive=True, two_chats_available=True, packer_layers=1, n_layers=32)
        items = AB.schedule({}, {}, a, 'a', n_layers=32)
        self.assertEqual(next(i for i in items if i['name'] == 'packer_layers')['challenger'], 2)

    def test_saved_best_overlays_probe_but_not_pins(self):
        active=dict(ACTIVE, kv_bits=8)
        e={"winner":{"kv_bits":16}}
        self.assertEqual(AB.baseline(e,active)["kv_bits"],16)
        self.assertEqual(AB.baseline(e,active,{"kv_bits":"8"})["kv_bits"],8)

    def test_single_never_overlays_unavailable_saved_settings(self):
        e={"winner":{"keepalive":True,"guess_ahead":True,"shared_prefix":True,"pipeline_chats":2}}
        base=AB.baseline(e,ACTIVE)
        self.assertNotIn("keepalive",base)
        self.assertFalse(base["guess_ahead"])
        self.assertFalse(base["shared_prefix"])
        self.assertEqual(base["pipeline_chats"],1)

    def test_pending_not_applied_during_sweep(self):
        e = {'pending_reload': {'kv_bits': 8}}
        self.assertEqual(TS.plan_reload(e, ['kv_bits'], apply_pending=False)['values']['kv_bits'],16)
        self.assertEqual(e['pending_reload'], {'kv_bits': 8})


class ControlsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 't.json'
        self.e = SimpleNamespace(_learn_lock=threading.Lock(), _learn_explicit={},
            _learn_guess_override=None, pipeline_chats=1, _learn_entry={},
            _learn_path=str(path), _learn_key='x', client=object(), draft_model=object(),
            _sweep_pause=False, shared=False)
        self.e._learn_store = {'models': {'x': self.e._learn_entry}}
        self.e._shared_prefix_on = lambda: self.e.shared
        self.e._set_shared_prefix = lambda v, reason='': setattr(self.e, 'shared', v)

    def test_pause_hold_commit_release_and_disk(self):
        e=self.e
        self.assertTrue(sweep_control.apply(e, {'pause': True})['paused'])
        sweep_control.apply(e, {'hold': {'guess_ahead': True, 'pipeline_chats': 2}})
        self.assertTrue(e._learn_guess_override); self.assertEqual(e.pipeline_chats, 2)
        sweep_control.apply(e, {'commit': dict(name='guess_ahead',winner=True,lost=False,fingerprint='hw')})
        raw = TS.load_store(Path(e._learn_path))['models']['x']
        self.assertTrue(raw['winner']['guess_ahead'])
        self.assertIn('guess_ahead:off',raw['optimize_hardware']['hw']['losses'])
        self.assertFalse(sweep_control.apply(e, {'release': True})['paused'])
        self.assertTrue(e._learn_guess_override) # committed winner survives release
        self.assertEqual(e.pipeline_chats, 1) # uncommitted hold restored

    def test_startup_paused_accepts_hold_commit(self):
        self.e._sweep_pause=True; self.e._sweep_restore=None
        sweep_control.apply(self.e, {'hold': {'pipeline_chats': 2}})
        sweep_control.apply(self.e, {'commit': dict(name='pipeline_chats',winner=2,lost=1,fingerprint='h')})
        sweep_control.apply(self.e, {'release': True})
        self.assertEqual(self.e.pipeline_chats, 2)

    def test_bad_controls_do_not_mutate(self):
        for body in ({'hold': {'kv_bits':8}}, {'hold': {'pipeline_chats':0}},
                     {'hold': {'guess_ahead':'false'}},
                     {'commit':dict(name='oops',winner=True,fingerprint='x')}):
            with self.assertRaises(ValueError): sweep_control.apply(self.e,body)
        self.assertFalse(self.e._sweep_pause)
        self.assertEqual(self.e._learn_entry,{})

    def test_worker_http_pause_hold_commit_release(self):
        from http.server import ThreadingHTTPServer
        import mlx_worker
        self.e.call = lambda fn: fn()
        server = ThreadingHTTPServer(("127.0.0.1", 0), mlx_worker.make_handler(self.e))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        m = WorkerManager(state_dir=Path(self.tmp.name) / "state", lead_port=server.server_port)
        self.assertTrue(m.sweep({"pause":True})["paused"])
        self.assertTrue(m.sweep({"hold":{"guess_ahead":True}})["paused"])
        result = m.sweep({"commit":dict(name="guess_ahead",winner=True,lost=False,fingerprint="hardware")})
        self.assertTrue(result["winner"]["guess_ahead"])
        self.assertFalse(m.sweep({"release":True})["paused"])
        self.assertTrue(self.e._learn_guess_override)

    def test_everyday_observer_does_nothing_while_held(self):
        import mlx_worker
        self.e._sweep_pause=True
        # Deliberately don't supply the rest of Engine's MLX fields: a paused
        # observer must return before reading stats or changing another knob.
        mlx_worker.Engine._learn_observe(self.e, {"completion_tokens":100})
        self.assertEqual(self.e._learn_entry,{})

    def test_flags_win(self):
        self.e._learn_explicit={'guess_ahead':False}
        with self.assertRaises(ValueError): sweep_control.apply(self.e,{'hold':{'guess_ahead':True}})
        with self.assertRaises(ValueError): sweep_control.apply(self.e,{'commit':dict(name='guess_ahead',winner=True,fingerprint='x')})

    def test_disk_failure_is_not_committed_in_memory(self):
        with patch.object(TS,'save_store',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                sweep_control.apply(self.e,{'commit':dict(name='kv_bits',winner=8,lost=16,fingerprint='x')})
        self.assertEqual(self.e._learn_entry,{})


class LauncherTest(unittest.TestCase):
    def test_force_only_auto_options_and_do_not_consume_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=WorkerManager(state_dir=Path(tmp)/"state")
            m.tuned_path=Path(tmp)/"t.json"
            entry={"lead_path":"/model"}
            st,e=m._tuned_entry("/model",create=True)
            e["pending_reload"]={"kv_bits":4,"keepalive":False}
            TS.save_store(st,m.tuned_path)
            m._sweep_load={"force":{"kv_bits":8,"fuse_kernels":"off"}}
            settings=web_settings.normalize({"fuse_kernels":"on"})
            lead,packer=web_settings.to_args(settings)
            m.plan_reload_args(entry,settings,lead,packer)
            self.assertEqual(lead[lead.index("--kv-bits")+1],"8")
            self.assertEqual(lead[lead.index("--fuse-kernels")+1],"all")
            self.assertEqual(lead.count("--fuse-kernels"),1)
            _,saved=m._tuned_entry("/model")
            self.assertEqual(saved["pending_reload"],{"kv_bits":4,"keepalive":False})
            self.assertIsNone(saved["reload_trial"])

    def test_adopt_uses_resolved_load_entry_not_inventory_fit_row(self):
        import web_catalog
        with tempfile.TemporaryDirectory() as tmp:
            m=WorkerManager(state_dir=Path(tmp))
            (Path(tmp)/"lead.pid").write_text("123")
            inventory={"id":"m","name":"M","lead_path":"/model","available_lead":False}
            resolved=dict(inventory,available_lead=True)
            with patch("web_workers.subprocess.check_output",return_value=f"python {m.worker} --model /model --split-role none --port {m.lead_port}"), \
                 patch.object(web_catalog,"list_models",return_value=[inventory]), \
                 patch.object(web_catalog,"get_model",return_value=resolved), \
                 patch.object(m,"lead_healthy",return_value=True), \
                 patch.object(m,"lead_active_settings",return_value={}):
                self.assertTrue(m.adopt_running())
            self.assertTrue(m._loaded_entry["available_lead"])
            self.assertEqual(m._loaded_entry["run_mode"],"single")
            with patch.object(m,"_do_switch") as load:
                m.switch("m",entry=m._loaded_entry,wait=True,sweep={"force":{"kv_bits":8}})
                self.assertTrue(load.called)


class FakeMgr:
    def __init__(self):
        self._lead_path='/model'; self._loaded_entry={'id':'m','placement':{'nodes':['a']}}
        self.active=copy.deepcopy(ACTIVE); self.entry={}; self.reloads=[]; self.controls=[]
        self.state=dict(status='ready',model_id='m',split=False,settings=web_settings.normalize({}))
    def snapshot(self): return copy.deepcopy(self.state)
    def lead_active_settings(self): return dict(self.active)
    def optimize_hardware(self): return copy.deepcopy(NODES)
    def _tuned_entry(self,*args,**kw): return {},self.entry
    def sweep(self,body):
        self.controls.append(copy.deepcopy(body))
        for n,v in (body.get('hold') or {}).items(): self.active['shared_start' if n=='shared_prefix' else n]=v
        if body.get('commit'):
            c=body['commit']; AB.commit(self.entry,c['fingerprint'],c['name'],c['winner'],c['lost'])
        return {'paused':not body.get('release')}
    def switch(self,model_id,wait,settings,entry,sweep):
        self.reloads.append(copy.deepcopy(sweep))
        self.active.update(sweep['force'])
    def send(self,msgs):
        speed=12 if self.active['kv_bits']==8 else 10
        if self.active['fuse_kernels']=='on': speed*=0.9
        return dict(elapsed=1, total_s=100/speed, completion_tokens=100)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._prev_speed = os.environ.get("CARAVAN_SPEED_AVERAGES")
        os.environ["CARAVAN_SPEED_AVERAGES"] = str(Path(self._td.name) / "speed.json")

    def tearDown(self):
        if self._prev_speed is None:
            os.environ.pop("CARAVAN_SPEED_AVERAGES", None)
        else:
            os.environ["CARAVAN_SPEED_AVERAGES"] = self._prev_speed
        self._td.cleanup()

    def run_opt(self,mgr=None,send=None):
        mgr=mgr or FakeMgr(); opt=WO.Optimizer(mgr,send=send or mgr.send)
        opt.start(); opt._thread.join(5)
        self.assertFalse(opt.snapshot()['running']); return mgr,opt

    def test_serial_pairs_choose_winners_only_needed_reloads(self):
        mgr=FakeMgr(); opt=WO.Optimizer(mgr,send=mgr.send)
        snapshots=[]
        def send(msgs):
            snapshots.append(opt.snapshot())
            return mgr.send(msgs)
        opt._send=send; opt.start('quick'); opt._thread.join(5)
        s=opt.snapshot(); self.assertEqual(s['phase'],'done',s)
        self.assertEqual(mgr.entry['winner'],{'kv_bits':8,'fuse_kernels':'off'})
        self.assertEqual(s['prompts'],12)
        self.assertEqual(s['reloads'],3) # kv challenger; fuse challenger + rollback
        self.assertEqual([r['force']['kv_bits'] for r in mgr.reloads],[8,8,8])
        self.assertEqual(mgr.active['fuse_kernels'],'off')
        self.assertEqual(mgr.controls[-1],{'release':True})
        for snap in snapshots:
            self.assertEqual(sum(i['state']=='running' for i in snap['schedule']),1)
        self.assertEqual(s['mode'],'now')
        self.assertEqual(mgr._loaded_entry['placement'],{'nodes':['a']})

    def test_records_before_and_after_speeds(self):
        import web_speed as S
        mgr=FakeMgr()
        def send(msgs):
            r=mgr.send(msgs)
            # Baseline (16-bit) is slower to first word than the 8-bit winner.
            r["ttft"]=2.1 if mgr.active["kv_bits"]==16 else 1.2
            return r
        _,opt=self.run_opt(mgr,send=send)
        self.assertEqual(opt.snapshot()["phase"], "done")
        got=S.get_tuning("m")
        self.assertEqual(got["source"], "optimize_now")
        self.assertIsNotNone(got["lines"])
        self.assertEqual(len(got["lines"]), 2)
        self.assertTrue(got["lines"][0].startswith("Before · "))
        self.assertTrue(got["lines"][1].startswith("After · "))
        self.assertIn("Write", got["lines"][0])
        self.assertIn("tok/s", got["lines"][0])
        self.assertIn("first token", got["lines"][0])
        self.assertNotIn("words/s", got["line"])
        self.assertIn("10.0 tok/s", got["lines"][0])  # baseline kv 16
        self.assertIn("12.0 tok/s", got["lines"][1])  # winner kv 8
        self.assertIn("first token 2.10s", got["lines"][0])
        self.assertIn("first token 1.20s", got["lines"][1])
        self.assertEqual(got["line"], "\n".join(got["lines"]))
        self.assertEqual(opt.snapshot()["prompts"], 12)  # samples are not counted as trial prompts

    def test_unavailable_saved_keepalive_does_not_trigger_reload(self):
        mgr=FakeMgr();mgr.entry={"winner":{"keepalive":True}}
        _,opt=self.run_opt(mgr)
        self.assertEqual(opt.snapshot()["reloads"],3)
        self.assertNotIn("keepalive",opt.snapshot()["summary"]["winner"])

    def test_cancel_after_challenger_reply_does_not_commit_and_restores(self):
        mgr=FakeMgr(); opt=WO.Optimizer(mgr,send=mgr.send)
        def send(msgs):
            if mgr.active['kv_bits']==8: opt.cancel()
            return mgr.send(msgs)
        opt._send=send; opt.start(); opt._thread.join(5)
        self.assertEqual(opt.snapshot()['phase'],'canceled')
        self.assertFalse(mgr.entry.get('winner'))
        self.assertEqual(mgr.active['kv_bits'],16)
        self.assertEqual(opt.snapshot()['prompts'],4)
        self.assertEqual(opt.snapshot()['reloads'],2)

    def test_cancel_during_reload_finishes_and_restores_no_more_probes(self):
        mgr=FakeMgr(); opt=WO.Optimizer(mgr,send=mgr.send)
        orig=mgr.switch
        def switch(*args,**kw):
            orig(*args,**kw); opt.cancel()
        mgr.switch=switch; opt.start(); opt._thread.join(5)
        self.assertEqual(opt.snapshot()['phase'],'canceled')
        self.assertEqual(opt.snapshot()['prompts'],3)
        self.assertEqual(mgr.active['kv_bits'],16)

    def test_failed_challenger_load_recovers_without_loss(self):
        mgr=FakeMgr(); orig=mgr.switch
        def switch(*args,**kw):
            if kw['sweep']['force']['kv_bits']==8:
                mgr.state['status']='error'; raise RuntimeError('load failed')
            orig(*args,**kw); mgr.state['status']='ready'
        mgr.switch=switch
        _,opt=self.run_opt(mgr)
        self.assertIn('load failed',opt.snapshot()['error'])
        self.assertEqual(mgr.state['status'],'ready')
        self.assertEqual(mgr.active['kv_bits'],16)
        self.assertFalse(mgr.entry.get('optimize_hardware'))

    def test_recovery_failure_still_releases_existing_worker(self):
        mgr=FakeMgr()
        def switch(*args,**kw): raise RuntimeError("preflight denied")
        mgr.switch=switch
        _,opt=self.run_opt(mgr)
        self.assertIn("restore failed",opt.snapshot()["error"])
        self.assertEqual(mgr.controls[-1],{"release":True})

    def test_pause_at_boundary_then_resume(self):
        mgr=FakeMgr(); gate=threading.Event(); opt=WO.Optimizer(mgr,send=mgr.send)
        def send(msgs):
            if not gate.is_set(): opt.pause(); gate.set()
            return mgr.send(msgs)
        opt._send=send; opt.start(); self.assertTrue(gate.wait(2))
        # Event-owned pause lets us check without racing a short real inference.
        self.assertTrue(opt.snapshot()['paused']); self.assertTrue(opt.snapshot()['running'])
        self.assertFalse(mgr.reloads)
        opt.pause(False); opt._thread.join(5)
        self.assertEqual(opt.snapshot()['phase'],'done')

    def test_user_chat_cancel_wait_no_prompt(self):
        mgr=FakeMgr(); opt=WO.Optimizer(mgr,send=mgr.send,inflight=lambda:1)
        opt.start(); opt.cancel(); opt._thread.join(5)
        self.assertEqual(opt.snapshot()['prompts'],0)
        self.assertFalse(mgr.controls)

    def test_missing_measurements_no_commit(self):
        mgr,opt=self.run_opt(send=lambda m:{'elapsed':1})
        self.assertIn('token counts',opt.snapshot()['error'])
        self.assertFalse(mgr.entry.get('winner'))
        self.assertEqual(mgr.controls[-1],{'release':True})

    def test_skip_previously_lost_values(self):
        mgr=FakeMgr(); mgr.entry={}
        fp=AB.fingerprint(NODES,split=False)
        AB.commit(mgr.entry,fp,'kv_bits',16,8)
        AB.commit(mgr.entry,fp,'kv_bits',16,4)
        AB.commit(mgr.entry,fp,'fuse_kernels','off','on')
        _,opt=self.run_opt(mgr)
        self.assertEqual(opt.snapshot()['prompts'],0)
        self.assertFalse(mgr.reloads)

    def test_single_start_atomic(self):
        mgr=FakeMgr(); opt=WO.Optimizer(mgr,send=mgr.send,inflight=lambda:1)
        opt.start()
        with self.assertRaises(RuntimeError): opt.start()
        opt.cancel(); opt._thread.join(2)

    def test_shared_prompt_long(self):
        self.assertGreater(len(WO.prompt_plan(0)[0]['content'])/4,TS.SHARED_PREFIX_MIN_PROMPT)


if __name__=='__main__': unittest.main()
