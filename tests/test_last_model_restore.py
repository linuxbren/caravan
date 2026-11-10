import copy,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/"agent"),str(Path(__file__).resolve().parents[1]/"proxy")]
import web_restore as R
import web_server as W
import web_pipeline as P
from web_workers import WorkerManager

NODES=[dict(id="n1",role="lead",host="local"),dict(id="n2",role="packer",host="peer",ssh="peer")]
def request(mid="q"):
    return dict(model_id=mid,engine="mlx",balance=True,counts=[4,8],node_ids=["n2","n1"],settings={"guess_ahead":"off","kv_bits":"8"})

class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=R.Store(Path(self.tmp.name)/"last.json")
    def test_empty_and_explicit_unload_tombstone(self):
        self.assertIsNone(self.store.read());self.store.write(request());self.store.write(None);self.assertIsNone(self.store.read());self.assertIsNone(json.loads(self.store.path.read_text())["request"])
    def test_atomic_roundtrip_private_and_no_commands_or_paths(self):
        self.store.write(dict(request(),command="kill someone",lead_path="/arbitrary",force_split=True,_restore_token="secret"));got=self.store.read();self.assertEqual(got["counts"],[4,8]);self.assertNotIn("command",got);self.assertNotIn("force_split",got);self.assertNotIn("lead_path",got);self.assertNotIn("_restore_token",got);self.assertEqual(self.store.path.stat().st_mode&0o777,0o600);self.assertFalse(list(self.store.path.parent.glob("*.tmp")))
    def test_failed_replace_preserves_previous_success(self):
        self.store.write(request("old"))
        with mock.patch.object(R.os,"replace",side_effect=OSError("disk full")),self.assertRaises(OSError):self.store.write(request("new"))
        self.assertEqual(self.store.read()["model_id"],"old")
    def test_invalid_record_and_engine_fail_closed(self):
        for blob in [{"schema":99,"request":request()},{"schema":1},{"schema":1,"request":dict(request(),engine="shell")}]:
            self.store.path.write_text(json.dumps(blob))
            with self.assertRaises(ValueError):self.store.read()
    def test_invalid_counts_ids_and_unknown_claims(self):
        for update in [dict(counts=[True,8]),dict(counts=[1.5,10.5]),dict(counts=[float("nan"),8]),dict(node_ids=["n1","n1"]),dict(counts=[12]),dict(placement={"mode":"bad","node_ids":["n1"]})]:
            with self.subTest(update=update),self.assertRaises(ValueError):R.canonical(dict(request(),**update))
    def test_gguf_fractional_shares_and_tune_roundtrip(self):
        self.store.write(dict(request(),engine="gguf",counts=[1.5,2.5],gguf_tune={"flash_attn":"on","ubatch":128,"command":"bad"}));got=self.store.read();self.assertEqual(got["counts"],[1.5,2.5]);self.assertNotIn("command",got["gguf_tune"])

class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.mgr=WorkerManager(state_dir=Path(self.tmp.name));self.app=NS(mgr=self.mgr,configured_nodes=lambda:NODES);self.c=R.Controller(self.app)
    def test_ui_shows_restore_warnings_as_text_without_locking_controls(self):
        html=(Path(__file__).resolve().parents[1]/"proxy/web/index.html").read_text()
        self.assertIn('id="restoreNotice" role="status"',html)
        self.assertIn('restoreNotice.textContent = r.message',html)
        self.assertIn('["preparing", "blocked", "save_error"]',html)

    def test_no_intent_no_load(self):
        with mock.patch.object(self.c,"http") as http:self.c.start("http://unused",background=False);http.assert_not_called()
        self.assertEqual(self.c.snapshot()["phase"],"empty")
    def test_healthy_keep_workers_adoption_does_not_reload_or_overwrite(self):
        self.c.store.write(request("saved"));self.mgr._set(status="ready")
        with mock.patch.object(self.c,"http") as http:self.c.start("http://unused",background=False);http.assert_not_called()
        self.assertEqual(self.c.store.read()["model_id"],"saved");self.assertEqual(self.c.snapshot()["phase"],"adopted")
    def test_disabled_restore_still_records_success(self):
        self.c.state["enabled"]=False
        with mock.patch.object(self.c,"http") as http:self.c.start("http://unused",background=False);http.assert_not_called()
        self.assertEqual(self.c.snapshot()["phase"],"disabled")
        self.c.record(dict(id="q",split_counts=[4,8],pipeline_nodes=[NODES[1],NODES[0]]),dict(status="ready",split=True,settings={}))
        self.assertEqual(self.c.store.read()["model_id"],"q")
    def test_missing_peer_or_files_or_memory_stops_once_keeps_intent(self):
        for why in ["Missing shard","Not enough free memory"]:
            c=R.Controller(self.app);c.store.write(request())
            with mock.patch.object(c,"http",side_effect=ValueError(why)) as http,mock.patch.object(self.mgr,"lead_healthy",return_value=False):
                c.start("http://unused",background=False);c.start("http://unused",background=False);self.assertEqual(http.call_count,1)
            self.assertEqual(c.snapshot()["phase"],"blocked");self.assertIn(why,self.mgr.snapshot()["error"]);self.assertEqual(c.store.read()["model_id"],"q")
    def test_transient_peer_readiness_retries_with_backoff_then_restores(self):
        now=[0];delays=[]
        def wait(seconds):delays.append(seconds);now[0]+=seconds
        c=R.Controller(self.app,clock=lambda:now[0],wait=wait);c.store.write(request())
        attempts=[]
        def post(path,body,**kwargs):
            attempts.append(copy.deepcopy(body))
            if len(attempts)==1:raise ValueError("live free memory is unknown for n2")
            if len(attempts)==2:raise ValueError("Mini n2 is unavailable; bring it online and press Load")
            self.mgr._set(status="ready")
        with mock.patch.object(c,"http",side_effect=post),mock.patch.object(self.mgr,"lead_healthy",return_value=False):c.start("http://unused",background=False)
        self.assertEqual(c.snapshot()["phase"],"restored");self.assertEqual(delays,[2,4])
        self.assertEqual(attempts[0],attempts[2]);self.assertEqual(c.store.read()["counts"],[4,8])
    def test_peer_retry_budget_is_bounded_and_intent_preserved(self):
        now=[0]
        c=R.Controller(self.app,retry_timeout=5,clock=lambda:now[0],wait=lambda s:now.__setitem__(0,now[0]+s));c.store.write(request())
        with mock.patch.object(c,"http",side_effect=ValueError("Live free memory is unknown for n2")) as http,mock.patch.object(self.mgr,"lead_healthy",return_value=False):c.start("http://unused",background=False)
        self.assertEqual(now[0],5);self.assertEqual(http.call_count,2);self.assertEqual(c.snapshot()["phase"],"blocked");self.assertIsNone(c.token);self.assertEqual(c.store.read()["model_id"],"q")
    def test_user_stop_during_backoff_cancels_without_another_post(self):
        c=R.Controller(self.app);c.store.write(request());c._wait=lambda seconds:c.clear()
        with mock.patch.object(c,"http",side_effect=ValueError("Live free memory is unknown for n2")) as http,mock.patch.object(self.mgr,"lead_healthy",return_value=False):c.start("http://unused",background=False)
        self.assertEqual(http.call_count,1);self.assertEqual(c.snapshot()["phase"],"empty");self.assertIsNone(c.store.read());self.assertIsNone(c.token)
    def test_ambiguous_transport_timeout_is_not_retried(self):
        c=R.Controller(self.app);c.store.write(request())
        with mock.patch.object(c,"http",side_effect=TimeoutError("timed out")) as http,mock.patch.object(self.mgr,"lead_healthy",return_value=False):c.start("http://unused",background=False)
        self.assertEqual(http.call_count,1);self.assertEqual(c.snapshot()["phase"],"blocked")
    def test_malformed_saved_json_is_clear_ui_error(self):
        self.c.store.path.write_text("not json")
        with mock.patch.object(self.c,"http") as http:self.c.start("http://unused",background=False);http.assert_not_called()
        self.assertIn("Could not restore",self.mgr.snapshot()["error"])
    def test_unadopted_busy_lead_is_not_taken_over(self):
        self.c.store.write(request())
        with mock.patch.object(self.mgr,"lead_healthy",return_value=True),mock.patch.object(self.c,"http") as http:self.c.start("http://unused",background=False);http.assert_not_called()
        self.assertIn("unadopted worker",self.mgr.snapshot()["error"])
    def test_user_control_cancels_pending_restore(self):
        self.c.store.write(request());self.c.authorize({},begin=True)
        with mock.patch.object(self.c,"http") as http:self.c.start("http://unused",background=False);http.assert_not_called()
    def test_stale_or_forged_restore_token_rejected(self):
        self.c.token="valid"
        with self.assertRaises(ValueError):self.c.authorize({"_restore_token":"forged"})
        self.c.cancel()
        with self.assertRaises(ValueError):self.c.authorize({"_restore_token":"valid"})
    def test_clear_does_not_delete_weights_or_other_state(self):
        model=self.mgr.state_dir/"weights";model.write_text("keep");self.c.store.write(request());self.c.clear();self.assertIsNone(self.c.store.read());self.assertEqual(model.read_text(),"keep")
    def test_four_stage_success_preserves_exact_counts_minis_settings(self):
        nodes=[dict(id="n"+str(i),role="packer" if i<4 else "lead",host="peer") for i in range(1,5)]
        self.app.configured_nodes=lambda:nodes
        self.c.record(dict(id="q",split_counts=[2,3,4,5],pipeline_nodes=nodes),dict(status="ready",split=True,settings={"kv_bits":"8"}))
        got=self.c.store.read();self.assertEqual(got["counts"],[2,3,4,5]);self.assertEqual(got["node_ids"],[n["id"] for n in nodes]);self.assertEqual(got["settings"]["kv_bits"],"8")
    def test_remote_single_records_actual_node_not_default_lead(self):
        self.mgr._worker_node=NODES[1];self.c.record(dict(id="small",source="mlx"),dict(status="ready",split=False,settings={}))
        got=self.c.store.read();self.assertEqual(got["placement"],{"mode":"one","node_ids":["n2"]});self.assertNotIn("balance",got)
    def test_gguf_success_records_engine_shares_tune_and_placement(self):
        self.c.record(dict(id="gguf/q",source="gguf",gguf_shares=[2,1],_loaded_tune={"ubatch":64}),dict(status="ready",split=True,gguf={"nodes":["n1","n2"]},settings={}))
        got=self.c.store.read();self.assertEqual(got["engine"],"gguf");self.assertEqual(got["counts"],[2,1]);self.assertEqual(got["gguf_tune"]["ubatch"],64)
    def test_failed_load_preserves_previous_success(self):
        self.c.store.write(request("old"))
        with mock.patch.object(self.mgr,"_deny_managed_service"),mock.patch.object(self.mgr,"_do_switch",side_effect=RuntimeError("missing")):
            self.mgr.switch("new",wait=True,entry=dict(id="new",available_lead=True))
        self.assertEqual(self.c.store.read()["model_id"],"old")
    def test_shutdown_cleanup_does_not_erase_restore_intent(self):
        self.c.store.write(request())
        with mock.patch.object(self.mgr,"_deny_managed_service"),mock.patch.object(self.mgr,"_kill_lead"),mock.patch.object(self.mgr,"_kill_packer"),mock.patch.object(self.mgr,"_kill_gguf"):self.mgr.stop(reason="web-server exit")
        self.assertEqual(self.c.store.read()["model_id"],"q")
    def test_stop_during_load_never_re_records_or_resurrects(self):
        started=threading.Event();finish=threading.Event()
        def load(entry,settings):
            started.set();finish.wait(3);self.mgr._loaded_entry=dict(id="new",split_counts=[4,8],pipeline_nodes=[NODES[1],NODES[0]]);self.mgr._set(status="ready",split=True)
        with mock.patch.object(self.mgr,"_deny_managed_service"),mock.patch.object(self.mgr,"_do_switch",side_effect=load),mock.patch.object(self.mgr,"_kill_lead"),mock.patch.object(self.mgr,"_kill_packer"),mock.patch.object(self.mgr,"_kill_gguf"):
            self.mgr.switch("new",entry=dict(id="new",available_lead=True));self.assertTrue(started.wait(2));self.mgr.stop(reason="ui");finish.set();self.mgr._switch_thread.join(3)
        self.assertEqual(self.mgr.snapshot()["status"],"idle");self.assertIsNone(self.c.store.read())

class PlacementSafetyTest(unittest.TestCase):
    def setUp(self):
        self.entry=dict(id="small",hf="org/small",source="hf-mlx")
        self.body=dict(model_id="small",engine="mlx",placement={"mode":"one","node_ids":["n2"]},node_ids=["n2"])
        self.model=dict(full_ok=True,has_tokenizer=True,path="/verified/remote/model",weights_gb=2)
        self.app=NS(configured_nodes=lambda:NODES,nodes=lambda:{"nodes":[]},_ssh_fn=lambda:mock.Mock(),mgr=NS(snapshot=lambda:{"status":"idle"}),gather_model_inventories=lambda:[dict(id="n2",models={"org/small":self.model})])
    def validate(self,stats):
        with mock.patch("web_nodes.gather_node_stats",return_value=stats):return R.validate_placement(self.app,self.entry,self.body)
    def test_single_exact_remote_placement_uses_verified_inventory_path(self):
        got=self.validate(dict(ram={"available_gb":8}));self.assertEqual(got["lead_path"],self.model["path"]);self.assertEqual(got["placement"]["node_ids"],["n2"]);self.assertEqual(got["run_mode"],"single")
    def test_offline_mini_is_not_replaced_by_another(self):
        with self.assertRaisesRegex(ValueError,"unavailable"):self.validate(dict(offline=True))
    def test_missing_full_files_block_no_auto_fetch(self):
        self.model["full_ok"]=False
        with self.assertRaisesRegex(ValueError,"files are missing"):self.validate(dict(ram={"available_gb":8}))
    def test_busy_idle_mini_cannot_assume_total_ram_is_free(self):
        with self.assertRaisesRegex(ValueError,"Not enough free memory"):self.validate(dict(ram={"available_gb":1,"total_gb":24}))
    def test_unknown_or_nan_free_memory_is_not_a_green_load(self):
        for value in [None,float("nan"),True]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,"unknown"):self.validate(dict(ram={"available_gb":value,"total_gb":24}))
    def test_changed_engine_rejected_before_inventory_or_process_work(self):
        self.entry["source"]="gguf"
        with self.assertRaisesRegex(ValueError,"engine"):self.validate({})
    def test_gguf_cannot_silently_insert_a_different_lead(self):
        self.entry.update(source="gguf",lead_path="/unused")
        self.body["engine"]="gguf"
        with self.assertRaisesRegex(ValueError,"original local lead"):self.validate({})

    def test_removed_mini_fails_before_any_remote_work(self):
        self.body["node_ids"]=["gone"];self.body["placement"]["node_ids"]=["gone"]
        with self.assertRaisesRegex(ValueError,"no longer configured"):self.validate({})


class EndpointTest(unittest.TestCase):
    def test_remote_local_interface_resolves_on_own_mini_not_lead(self):
        nodes=[dict(id="p",host="peer",ssh="user@control",peer="ssh+tb://user@control/en2:5560",listen="tb://en2:5560")]
        mgr=NS(_node_is_local=lambda n:False)
        with mock.patch("service_endpoints.resolve",return_value="169.254.1.2:5560") as resolve:
            out=P.resolve_nodes(mgr,nodes)
        self.assertEqual(out[0]["listen"],"169.254.1.2:5560");self.assertTrue(nodes[0]["listen"].startswith("tb://"));self.assertEqual(resolve.call_args.args[0],"ssh+tb://user@control/en2:5560")
    def test_untrusted_ssh_syntax_cannot_be_injected(self):
        with self.assertRaises(ValueError):P.resolve_nodes(NS(_node_is_local=lambda n:False),[dict(id="p",host="-oProxyCommand=bad",listen="tb://en2:5560")])

class SharedHTTPTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.mgr=WorkerManager(state_dir=Path(self.tmp.name));self.app=W.App(self.mgr)
        self.app.configured_nodes=lambda:NODES;self.app.nodes=lambda:{"nodes":NODES};self.app.list_loadable_models=lambda:[dict(id="q",name="Q",source="mlx",available_lead=True),dict(id="small",name="Small",source="mlx",available_lead=True)]
        self.entry=lambda mid:dict(id=mid,name=mid,source="mlx",available_lead=True,split_counts=[4,8],pipeline_nodes=[NODES[1],NODES[0]])
        self.app.balance=lambda body,fresh=False:dict(ready=True,entry=self.entry(body["model_id"]))
        def load(entry,settings):self.mgr._loaded_entry=entry;self.mgr._set(settings=settings,status="ready",model_id=entry["id"],split=True)
        self.patches=[mock.patch.object(self.mgr,"_do_switch",side_effect=load),mock.patch.object(self.mgr,"_deny_managed_service"),mock.patch.object(self.mgr,"lead_healthy",return_value=False),mock.patch.object(self.mgr,"_kill_lead"),mock.patch.object(self.mgr,"_kill_packer"),mock.patch.object(self.mgr,"_kill_gguf")]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),W.make_handler(self.app));self.server.daemon_threads=True;threading.Thread(target=self.server.serve_forever,daemon=True).start();self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown);self.url="http://127.0.0.1:"+str(self.server.server_port)
    def post(self,path,body):
        with urlopen(Request(self.url+path,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"}),timeout=5) as r:return json.load(r)
    def test_restore_uses_same_guarded_http_balance_load_path(self):
        self.app.restore.store.write(request());self.app.restore.start(self.url,background=False);self.assertEqual(self.app.restore.snapshot()["phase"],"restored");got=self.app.restore.store.read();self.assertEqual(got["counts"],[4,8]);self.assertEqual(got["settings"]["kv_bits"],"8")
    def test_http_unknown_peer_memory_retries_same_guarded_load(self):
        attempts=[]
        def balance(body,fresh=False):
            attempts.append(copy.deepcopy(body))
            if len(attempts)==1:raise ValueError("live free memory is unknown for n2")
            return dict(ready=True,entry=self.entry(body["model_id"]))
        self.app.balance=balance;self.app.restore._wait=lambda seconds:None
        self.app.restore.store.write(request());self.app.restore.start(self.url,background=False)
        self.assertEqual(len(attempts),2);self.assertEqual(attempts[0],attempts[1]);self.assertEqual(self.app.restore.snapshot()["phase"],"restored")
    def test_manual_switch_stays_unlocked_and_replaces_last_model(self):
        self.app.restore.store.write(request());self.post("/api/models/load",dict(model_id="small",balance=True,counts=[4,8],node_ids=["n2","n1"]));self.mgr._switch_thread.join(2);self.assertEqual(self.app.restore.store.read()["model_id"],"small");self.assertNotIn("managed_service",self.mgr.snapshot())
    def test_plain_ui_split_load_uses_n_node_planner_not_legacy_ip_defaults(self):
        model=Path(self.tmp.name)/"model";model.mkdir();(model/"config.json").write_text(json.dumps({"num_hidden_layers":12}));(model/"model.safetensors.index.json").write_text("{}")
        self.app.list_loadable_models=lambda:[dict(id="q",name="Q",source="hf-mlx",available_lead=True,run_mode="split",lead_path=str(model),packer_layers=4)]
        with mock.patch.object(self.app,"balance",side_effect=lambda body,fresh=False:dict(ready=True,entry=self.entry(body["model_id"]))) as balance:
            self.post("/api/models/load",{"model_id":"q"});self.mgr._switch_thread.join(2)
        self.assertEqual(balance.call_args.args[0]["counts"],[4,8]);self.assertTrue(balance.call_args.kwargs["fresh"]);self.assertEqual(self.app.restore.store.read()["counts"],[4,8])

    def test_invalid_ui_settings_preserve_last_success_without_starting_workers(self):
        self.app.restore.store.write(request())
        before=self.app.restore.store.path.read_bytes()
        for key,value in [("fuse_kernels","off"),("keepalive","on")]:
            with self.subTest(setting=key):
                with self.assertRaises(HTTPError) as failure:
                    self.post("/api/models/load",dict(model_id="small",settings={key:value}))
                self.assertEqual(failure.exception.code,400)
                self.assertIn(key,json.loads(failure.exception.read())["error"])
                self.assertEqual(self.app.restore.store.path.read_bytes(),before)
                self.assertIsNone(self.mgr._switch_thread)

    def test_ui_unload_records_restore_nothing(self):
        self.app.restore.store.write(request());self.post("/api/models/stop",{});self.assertIsNone(self.app.restore.store.read());self.assertEqual(self.mgr.snapshot()["status"],"idle")
    def test_shared_missing_files_or_memory_blocks_without_switch(self):
        self.app.balance=lambda body,fresh=False:dict(ready=False,stages=[{"downloads":["missing"]}]);self.app.restore.store.write(request())
        self.app.restore.start(self.url,background=False);self.assertEqual(self.app.restore.snapshot()["phase"],"blocked");self.assertIsNone(self.mgr._switch_thread);self.assertEqual(self.app.restore.store.read()["model_id"],"q")


class RemoteAdoptionTest(unittest.TestCase):
    def setUp(self):
        import web_remote_adopt as A
        self.A=A;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.mgr=WorkerManager(state_dir=Path(self.tmp.name));self.node=dict(id="n2",role="packer",host="peer",ssh="user@control",repo="~/cv3")
        self.meta=dict(node="n2",ssh="user@control",repo="~/cv3",pid=123,tunnel_pid=456,model_id="small",model="/models/small",settings={"kv_bits":"8"})
        self.command="ssh -o ExitOnForwardFailure=yes -N -L 8194:127.0.0.1:8194 user@control"
        self.patches=[mock.patch("web_nodes.nodes_from_config",return_value=[self.node]),mock.patch("worker_ownership.command_of",side_effect=lambda pid:self.command),mock.patch.object(self.mgr,"lead_healthy",return_value=True),mock.patch.object(self.mgr,"_ssh_node",return_value=NS(returncode=0,stdout='{"owned":true}'))]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def adopt(self):
        (self.mgr.state_dir/"remote-worker.json").write_text(json.dumps(self.meta));return self.A.adopt(self.mgr)
    def test_adopts_only_both_verified_identities_no_restart(self):
        self.assertTrue(self.adopt());self.assertEqual(self.mgr.snapshot()["model_id"],"small");self.assertEqual(self.mgr._worker_node["id"],"n2")
    def test_changed_or_missing_control_target_is_not_contacted(self):
        self.meta["ssh"]="other";self.assertFalse(self.adopt());self.mgr._ssh_node.assert_not_called()
    def test_reused_tunnel_pid_is_not_adopted_or_killed(self):
        self.command="python other.py";self.assertFalse(self.adopt());self.mgr._ssh_node.assert_not_called()
    def test_remote_unowned_pid_rejected(self):
        self.mgr._ssh_node.return_value=NS(returncode=0,stdout='{"owned":false}');self.assertFalse(self.adopt())
    def test_adopted_tunnel_cleanup_rechecks_pid_identity(self):
        self.assertTrue(self.adopt());self.command="ssh -N -L 8194:127.0.0.1:8194 someone-else"
        with mock.patch("os.kill") as kill:self.mgr._stop_tunnel();kill.assert_not_called()
    def test_exact_adopted_tunnel_can_be_stopped(self):
        self.assertTrue(self.adopt())
        with mock.patch("os.kill",side_effect=lambda *args:setattr(self,"command","")) as kill:self.mgr._stop_tunnel();self.assertEqual(kill.call_args.args[0],456)
