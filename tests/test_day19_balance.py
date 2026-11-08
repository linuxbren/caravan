"""Day 19: real framed fake pipelines and pure 2/3/4-node Balance checks.

No SSH, registered computers, downloads or MLX imports are used here.
"""
import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import mlx_split as S
import mlx_split_fetch as F
import mlx_worker as W
import split_balance as B
import web_pipeline as P
from test_mlx_worker import FakeOps, IDENT, KEY


def fixture(n=12, k=3):
    config = {"num_hidden_layers": n, "tie_word_embeddings": True}
    wm = {f"model.layers.{i}.weight": f"layer-{i}" for i in range(n)}
    wm.update({"model.embed_tokens.weight": "embedding", "model.norm.weight": "norm", "mtp.x": "mtp"})
    nodes = [{"id": f"n{i}", "label": f"Mini {i}", "role": "lead" if i == k-1 else "packer",
              "ram": {"available_gb": 12, "total_gb": 24}} for i in range(k)]
    inv = {node["id"]: {"shards_present": list(wm.values()), "has_config": True,
                         "has_index": True, "has_tokenizer": True} for node in nodes}
    return config, {"weight_map": wm}, nodes, inv


class BalanceTest(unittest.TestCase):
    def run_plan(self, k=3, counts=None, **kw):
        cfg, idx, nodes, inv = fixture(k=k)
        return B.preview(12, 6, nodes, counts, config=cfg, index=idx, inventories=inv, **kw)

    def test_even_three(self):
        out = self.run_plan()
        self.assertEqual(out["counts"], [4, 4, 4])
        self.assertEqual([x["range"] for x in out["stages"]], [[0, 4], [4, 8], [8, 12]])
        self.assertTrue(out["ready"])
        self.assertIsNone(out["speed"])

    def test_four(self):
        self.assertEqual(self.run_plan(4)["counts"], [3]*4)

    def test_manual_boundary_moves_exactly_one_layer(self):
        out = self.run_plan(counts=[3, 5, 4])
        self.assertEqual(out["mode"], "manual")
        self.assertEqual([x["range"] for x in out["stages"]], [[0, 3], [3, 8], [8, 12]])

    def test_different_free_memory(self):
        cfg, idx, nodes, inv = fixture()
        nodes[0]["ram"]["available_gb"] = 15
        out = B.preview(12, 6, nodes)
        self.assertGreater(out["counts"][0], out["counts"][1])
        self.assertFalse(out["ready"])  # files unknown, not green

    def test_low_free_memory_not_total_ram(self):
        cfg, idx, nodes, inv = fixture()
        nodes[0]["ram"]["available_gb"] = 1
        out = B.preview(12, 6, nodes, [4,4,4], config=cfg, index=idx, inventories=inv)
        self.assertFalse(out["safe"])
        self.assertFalse(out["ready"])

    def test_missing_files_replanned_after_move(self):
        cfg, idx, nodes, inv = fixture()
        files = F.plan_stage_files(cfg, idx, [4,4,4])["stages"]
        for i, n in enumerate(nodes): inv[n["id"]]["shards_present"] = list(files[i])
        out = B.preview(12, 6, nodes, [5,3,4], config=cfg, index=idx, inventories=inv, sizes={"layer-4": 123})
        self.assertEqual(out["stages"][0]["downloads"], ["layer-4"])
        self.assertEqual(out["stages"][0]["download_bytes"], 123)
        self.assertFalse(out["ready"])
        self.assertEqual(inv["n0"]["shards_present"], list(files[0]))  # read only

    def test_unknown_inventory_blocks(self):
        cfg, idx, nodes, inv = fixture()
        out = B.preview(12, 6, nodes, config=cfg, index=idx)
        self.assertFalse(out["ready"])
        self.assertIsNone(out["stages"][0]["downloads"])

    def test_missing_tokenizer_blocks(self):
        cfg, idx, nodes, inv = fixture()
        inv["n1"]["has_tokenizer"] = False
        self.assertFalse(B.preview(12, 6, nodes, config=cfg, index=idx, inventories=inv)["ready"])

    def test_unknown_or_offline_memory_refused(self):
        for change in ({"ram": {}}, {"offline": True}):
            cfg, idx, nodes, inv = fixture()
            nodes[1].update(change)
            with self.assertRaises(ValueError): B.preview(12, 6, nodes)

    def test_invalid_counts(self):
        for counts in ([0,6,6], [4,4,3], [4.0,4,4], [True,5,6], [6,6], [-1,6,7]):
            with self.subTest(counts=counts), self.assertRaises(ValueError): self.run_plan(counts=counts)

    def test_bad_model_size(self):
        for size in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError): B.preview(12, size, fixture()[2])

    def test_simulated_workers_share_physical_memory_budget(self):
        cfg, idx, nodes, inv = fixture()
        nodes[0]["physical_id"] = nodes[1]["physical_id"] = "same-mini"
        out = B.preview(12, 6, nodes, config=cfg, index=idx, inventories=inv)
        self.assertEqual([s["capacity_gb"] for s in out["stages"]], [6,6,12])
        self.assertGreater(out["counts"][2], out["counts"][0])


class RangeShardTest(unittest.TestCase):
    def test_ranges_any_count(self):
        for k in (2,3,4,7):
            self.assertEqual(S.plan_ranges(k*2, [2]*k)[-1][1], k*2)

    def test_cli_counts(self):
        self.assertEqual(S.parse_counts("4, 5,3"), [4,5,3])
        for bad in ("", "4", "1,0", "1,foo"):
            with self.assertRaises(ValueError): S.parse_counts(bad)

    def test_tied_embeddings_only_first_and_lead(self):
        cfg, idx, _, _ = fixture()
        p = F.plan_stage_files(cfg, idx, [4,4,4])
        self.assertIn("embedding", p["stages"][0])
        self.assertNotIn("embedding", p["stages"][1])
        self.assertIn("embedding", p["stages"][-1])
        self.assertIn("mtp", p["stages"][-1])
        self.assertNotIn("mtp", p["stages"][0])

    def test_legacy_two_stage_parity(self):
        cfg, idx, _, _ = fixture()
        a, b = F.plan_files(cfg, idx, 5), F.plan_stage_files(cfg, idx, [5,7])
        self.assertEqual([a["front"],a["head"]], b["stages"])
        self.assertEqual(a["shared"], b["shared"])

    def test_whole_shard_shared_across_many_stages(self):
        cfg, idx, _, _ = fixture()
        idx["weight_map"] = {name: "whole" for name in idx["weight_map"]}
        p = F.plan_stage_files(cfg, idx, [3,3,3,3])
        self.assertEqual(p["stages"], [{"whole"}]*4)
        self.assertEqual(p["shared"], {"whole"})

    def test_missing_index_not_silent_for_n_stage(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(FileNotFoundError):
            S.check_local_shards(d, "front", counts=[2,2,2], stage_index=1)

    def test_recovery_hint_preserves_full_n_stage_plan(self):
        hint = S._fetch_hint("/model", "packer", 8, "org/model", [4,4,4], 1)
        self.assertIn("--split-counts 4,4,4 --stage-index 1",hint)
        self.assertNotIn("--packer-layers",hint)

    def test_commands_use_own_model_and_previous_peer(self):
        node = {"id": "n2", "model_path": "/own/model", "peer": "tb2:5592"}
        a = P.stage_args(node, [4,4,4], 1, "tb1:5591")
        self.assertIn("/own/model", a)
        self.assertEqual(a[a.index("--split-upstream")+1], "tb1:5591")
        self.assertIn("~/.caravan/mlx/pipeline-n2/sessions", a)
        self.assertIn("--no-learn", a)

    def test_commands_need_peer_and_model(self):
        for node in ({"id": "n2"}, {"id": "n2", "model_path": "/m"}):
            with self.assertRaises(ValueError): P.stage_args(node, [4,4,4], 1, "tb1:5591")


class FetchCliTest(unittest.TestCase):
    def test_middle_stage_cli_selects_only_middle_shards(self):
        import types
        import contextlib
        import io
        cfg,idx,_,_ = fixture()
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/"config.json").write_text(json.dumps(cfg))
            (Path(root)/"model.safetensors.index.json").write_text(json.dumps(idx))
            hub = types.SimpleNamespace(snapshot_download=mock.Mock())
            with mock.patch.dict(sys.modules, {"huggingface_hub":hub}), \
                 mock.patch.object(F,"_resolve_token",return_value=None), \
                 mock.patch.object(F,"file_sizes",return_value={name:100 for name in idx["weight_map"].values()}), \
                 contextlib.redirect_stdout(io.StringIO()):
                out = F.main(["org/model",root,"--role","packer","--split-counts","4,4,4",
                              "--stage-index","1","--dry-run","--no-progress"])
            self.assertEqual(out["files"], [f"layer-{i}" for i in range(4,8)])
            self.assertNotIn("embedding",out["files"])
            hub.snapshot_download.assert_called_once()  # metadata, no weight shards

    def test_gguf_fetch_report_unaffected_by_mlx_stage_plan(self):
        import types
        import contextlib
        import io
        args = types.SimpleNamespace(repo="org/gguf", gguf_file="m.gguf",dry_run=True,no_progress=True)
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.dict(sys.modules,{"huggingface_hub":types.SimpleNamespace(snapshot_download=mock.Mock())}), \
             mock.patch.object(F,"file_sizes",return_value={"m.gguf":100}), \
             contextlib.redirect_stdout(io.StringIO()):
            out = F._fetch_gguf(args,Path(root),None)
        self.assertEqual(out["files"],["m.gguf"])
        self.assertTrue(out["gguf"])


class Pipeline:
    def __init__(self, root, k):
        self.stores, self.states, self.clients, self.sockets, self.threads = [], [], [], [], []
        self.k = k
        for i in range(k):
            ops = FakeOps(("KVCache",))
            store = W.SessionStore(ops, Path(root)/str(i), dict(IDENT, stage=str(i)), max_sessions=99)
            self.stores.append(store)
            if i == k-1: break
            def forward(tokens, cache):
                for c in cache: c.feed(tokens)
                return {"tokens": tokens, "path": [0]}, json.dumps(tokens).encode()
            info = {"stage": str(i), "range": [i,i+1], "n_layers": k}
            local = S.FrontState(store, forward, info, ops.new_cache)
            state = local
            if i:
                def hidden(h, payload, cache, i=i):
                    tokens = json.loads(payload)
                    for c in cache: c.feed(tokens)
                    return dict(h, path=h["path"]+[i]), payload
                state = S.ChainState(local, self.clients[-1], hidden)
            self.states.append(state)
            a,b = socket.socketpair(); self.sockets += [a,b]
            def serve(state=state, b=b):
                try:
                    while True:
                        h,p = S.read_frame(b)
                        try:
                            if h.get("op") == "stats" and isinstance(state,S.FrontState):
                                rh,rp = dict(state.info),b""
                            else:
                                rh,rp = state.handle(h,p)
                        except Exception as e: rh,rp = {"error": str(e)},b""
                        b.sendall(S.encode_frame(rh,rp))
                except (OSError, ConnectionError): pass
            th = threading.Thread(target=serve, daemon=True); th.start(); self.threads.append(th)
            self.clients.append(S.FrontClient(f"fake:{i}", connect=lambda a=a:a))
        self.client = self.clients[-1]
        self.split = S.SplitSessions(self.stores[-1], self.client, log=lambda _:None)

    def turn(self, prompt):
        s,n,how = self.split.prepare(KEY, prompt)
        todo = prompt[n:-1]
        rh, rp = self.client.call("fwd", tokens=todo, ctx="session", key=KEY)
        for c in s.cache: c.feed(todo)
        self.split.checkpoint(s, prompt[:-1])
        self.split.rewind(s)
        return n, rh

    def close(self):
        for sock in self.sockets:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            sock.close()
        for th in self.threads: th.join(timeout=1)


class ChainTest(unittest.TestCase):
    def with_pipeline(self, k, fn):
        with tempfile.TemporaryDirectory() as root:
            p = Pipeline(root,k)
            try: fn(p)
            finally: p.close()

    def test_three_stages_forward_order_and_reuse(self):
        def run(p):
            n,rh = p.turn([1,2,3])
            self.assertEqual(rh["path"], [0,1])
            n,rh = p.turn([1,2,3,4,5])
            self.assertEqual(n,2)
            self.assertEqual([st.sessions[KEY].tokens for st in p.stores], [[1,2,3,4]]*3)
        self.with_pipeline(3,run)

    def test_four_stages_forward_order(self):
        def run(p):
            _,rh = p.turn([1,2,3])
            self.assertEqual(rh["path"], [0,1,2])
            self.assertEqual(p.client.call("hello")[0]["range"], [0,3])
        self.with_pipeline(4,run)

    def test_stats_include_every_packer(self):
        def run(p):
            stats = p.client.call("stats")[0]
            self.assertEqual(len(stats["packers"]),3)
            self.assertEqual([x["range"] for x in stats["packers"]], [[0,1],[1,2],[2,3]])
        self.with_pipeline(4,run)

    def test_each_stage_saves_own_cache(self):
        def run(p):
            p.turn([1,2,3]); p.split.save(KEY)
            for store in p.stores:
                self.assertTrue((store.cache_dir/f"{KEY}.safetensors").exists())
                store.sessions.clear()
            self.assertEqual(p.split.restore(KEY), "restored")
            self.assertEqual([st.sessions[KEY].tokens for st in p.stores], [[1,2]]*4)
        self.with_pipeline(4,run)

    def test_one_missing_stage_rejects_all_restores(self):
        def run(p):
            p.turn([1,2,3]); p.split.save(KEY)
            for st in p.stores: st.sessions.clear()
            (p.stores[0].cache_dir/f"{KEY}.safetensors").unlink()
            self.assertEqual(p.split.restore(KEY), "rejected")
            self.assertTrue(all(KEY not in st.sessions for st in p.stores))
        self.with_pipeline(4,run)

    def test_upstream_epoch_invalidates_all_memory(self):
        def run(p):
            p.turn([1,2,3])
            p.states[0].epoch = "restarted"
            p.stores[0].sessions.clear(); p.states[0].cur=None
            n,_ = p.turn([1,2,3,4])
            self.assertEqual(n,0)
        self.with_pipeline(4,run)

    def test_prepare_disagreement_resets_chain(self):
        def run(p):
            p.turn([1,2,3])
            p.stores[0].reset(p.stores[0].sessions[KEY])
            n,_ = p.turn([1,2,3,4])
            self.assertEqual(n,0)
            self.assertEqual([st.sessions[KEY].tokens for st in p.stores], [[1,2,3]]*3)
        self.with_pipeline(3,run)

    def test_drop_reaches_every_stage(self):
        def run(p):
            p.turn([1,2,3]); p.split.drop([KEY])
            self.assertTrue(all(not st.sessions for st in p.stores))
        self.with_pipeline(4,run)


class LauncherTest(unittest.TestCase):
    def manager(self, root):
        mgr = mock.Mock()
        mgr.state_dir = Path(root)
        mgr.worker = Path(root)/"agent"/"mlx_worker.py"
        mgr.python = "python3"
        mgr.lead_port = 8194
        mgr._node_is_local.side_effect = lambda node: True
        mgr._lead_log.return_value = Path(root)/"lead.log"
        return mgr

    def entry(self):
        return {"id": "tiny", "name": "Tiny", "split_counts": [2,2,2], "pipeline_nodes": [
            {"id": f"n{i}", "host": "local", "model_path": "/own/model", "peer": f"127.0.0.1:{5590+i}",
             "role": "lead" if i == 2 else "packer"} for i in range(3)]}

    def test_preflight_failure_does_not_stop_running_model(self):
        with tempfile.TemporaryDirectory() as root:
            mgr = self.manager(root)
            with mock.patch("mlx_split.check_local_shards", side_effect=FileNotFoundError("missing")):
                with self.assertRaises(FileNotFoundError): P.load_pipeline(mgr, self.entry(), {})
            mgr._kill_lead.assert_not_called()
            mgr._kill_packer.assert_not_called()

    def test_three_stage_launch_commands_and_persistent_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            mgr = self.manager(root)
            client = mock.Mock()
            client.call.side_effect = [({"range":[0,2]}, b""), ({"stages":[{"range":[0,2]},{"range":[2,4]}]}, b"")]
            with mock.patch("mlx_split.check_local_shards"), mock.patch("mlx_split.FrontClient", return_value=client), \
                 mock.patch("web_pipeline.subprocess.Popen") as popen, mock.patch.dict("os.environ", {"HOME":root}):
                popen.return_value.pid = 99999
                P.load_pipeline(mgr, self.entry(), {})
            self.assertEqual(popen.call_count, 3)
            self.assertEqual(len(json.loads((Path(root)/"pipeline.json").read_text())),2)
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index("--split-peer")+1], "127.0.0.1:5591")
            self.assertEqual(mgr._loaded_entry["split_counts"], [2,2,2])
            mgr._wait_lead_ready.assert_called_once()

    def test_stop_after_web_restart_uses_tracked_node_identities(self):
        with tempfile.TemporaryDirectory() as root:
            mgr = self.manager(root)
            path = Path(root)/"pipeline.json"
            path.write_text(json.dumps(self.entry()["pipeline_nodes"][:-1]))
            with mock.patch("worker_ownership.stop") as stop:
                self.assertTrue(P.stop_pipeline(mgr))
            self.assertEqual(stop.call_count, 2)
            self.assertEqual(stop.call_args_list[0].kwargs["listen"], "127.0.0.1:5591")
            self.assertFalse(path.exists())


class GracefulPackerStopTest(unittest.TestCase):
    def stopped_read(self, initial):
        a,b=socket.socketpair();stop=threading.Event();errors=[]
        if initial:a.sendall(initial)
        def read():
            try:S.read_frame(b,stop=stop)
            except Exception as e:errors.append(e)
        t=threading.Thread(target=read);t.start();stop.set();t.join(1.5)
        try:
            self.assertFalse(t.is_alive(),"stop left a blocked frame reader")
            self.assertIsInstance(errors[0],ConnectionAbortedError)
        finally:a.close();b.close();t.join(1)

    def test_stop_interrupts_idle_persistent_frame(self):
        self.stopped_read(b"")

    def test_stop_interrupts_partial_header_and_payload(self):
        frame=S.encode_frame({"op":"hello"},b"payload")
        for prefix in (frame[:5],frame[:-3]):
            with self.subTest(prefix=len(prefix)):self.stopped_read(prefix)

    def test_stop_aware_read_keeps_fragmented_frame_intact(self):
        a,b=socket.socketpair();stop=threading.Event();frame=S.encode_frame({"op":"test"},b"payload");out=[]
        t=threading.Thread(target=lambda:out.append(S.read_frame(b,stop=stop)));t.start()
        for part in (frame[:5],frame[5:15],frame[15:]):a.sendall(part)
        t.join(1.5)
        try:self.assertEqual(out,[({"op":"test"},b"payload")])
        finally:a.close();b.close();t.join(1)

    def test_server_stops_with_an_idle_connected_peer(self):
        import types
        with socket.socket() as probe:probe.bind(("127.0.0.1",0));port=probe.getsockname()[1]
        ready=threading.Event();stop=threading.Event()
        state=types.SimpleNamespace(epoch="test",handle=lambda h,p:({"ok":True},b""))
        t=threading.Thread(target=S.serve_front,args=(f"127.0.0.1:{port}",state),
                           kwargs={"stop":stop,"log":lambda msg:ready.set() if "listening" in msg else None})
        t.start();self.assertTrue(ready.wait(2));peer=socket.create_connection(("127.0.0.1",port));peer.settimeout(2)
        try:
            peer.sendall(S.encode_frame({"op":"hello"}));self.assertTrue(S.read_frame(peer)[0]["ok"])
            stop.set();t.join(2);self.assertFalse(t.is_alive(),"idle peer prevented graceful exit")
        finally:stop.set();peer.close();t.join(2)


class PipelineAdoptionTest(unittest.TestCase):
    def setup_owned(self, root):
        import web_workers as WW
        model = Path(root)/"custom"/"org--Tiny"; model.mkdir(parents=True)
        (model/"config.json").write_text(json.dumps({"num_hidden_layers":12}))
        repo = Path(__file__).resolve().parents[1]
        mgr = WW.WorkerManager(state_dir=Path(root)/"state",repo=repo,lead_port=8196)
        nodes = [dict(id="p1",role="packer",host="mini1",peer="10.0.0.2:5591",model_path="/own/p1"),
                 dict(id="p2",role="packer",host="mini2",peer="10.0.0.3:5592",model_path="/own/p2"),
                 dict(id="lead",role="lead",host="local",model_root=str(model.parent))]
        balance = dict(counts=[4,4,4],node_ids=[n["id"] for n in nodes],lead_pid=123)
        (mgr.state_dir/"lead.pid").write_text("123")
        (mgr.state_dir/"pipeline-balance.json").write_text(json.dumps(balance))
        (mgr.state_dir/"pipeline.json").write_text(json.dumps(nodes[:-1]))
        cmd = f"python {mgr.worker} --model {model} --port 8196 --split-role lead --split-counts 4,4,4 --split-peer 10.0.0.3:5592"
        return mgr,cmd,nodes,balance,model

    def test_custom_root_adoption_ignores_same_id_default_root_shadow(self):
        import web_workers as WW
        with tempfile.TemporaryDirectory() as root:
            mgr,cmd,nodes,balance,model = self.setup_owned(root)
            shadow = dict(id="tiny",name="wrong root",lead_path="/default/org--Tiny")
            with mock.patch("web_nodes.nodes_from_config",return_value=nodes), \
                 mock.patch.object(WW.subprocess,"check_output",return_value=cmd), \
                 mock.patch.object(WW.catalog,"list_models",return_value=[shadow]), \
                 mock.patch.object(WW.catalog,"get_model",return_value=shadow) as get, \
                 mock.patch.object(mgr,"lead_healthy",return_value=True), \
                 mock.patch.object(mgr,"lead_active_settings",return_value={}):
                self.assertTrue(mgr.adopt_running())
            get.assert_not_called()
            self.assertEqual(mgr.snapshot()["balance"]["counts"],[4,4,4])
            self.assertEqual(mgr._loaded_entry["lead_path"],str(model))
            self.assertEqual(len(mgr._loaded_entry["pipeline_nodes"]),3)

    def test_different_command_counts_are_not_adopted(self):
        with tempfile.TemporaryDirectory() as root:
            mgr,cmd,nodes,_,_ = self.setup_owned(root)
            with mock.patch("web_nodes.nodes_from_config",return_value=nodes):
                self.assertIsNone(P.adopted_entry(mgr,cmd.replace("4,4,4","3,4,5"),123))

    def test_stale_pid_or_path_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as root:
            mgr,cmd,nodes,balance,_ = self.setup_owned(root)
            with mock.patch("web_nodes.nodes_from_config",return_value=nodes):
                self.assertIsNone(P.adopted_entry(mgr,cmd,124))
                balance["model_path"]="/another/model"
                (mgr.state_dir/"pipeline-balance.json").write_text(json.dumps(balance))
                self.assertIsNone(P.adopted_entry(mgr,cmd,123))

    def test_missing_stage_ownership_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as root:
            mgr,cmd,nodes,_,_ = self.setup_owned(root)
            (mgr.state_dir/"pipeline.json").write_text(json.dumps(nodes[:1]))
            with mock.patch("web_nodes.nodes_from_config",return_value=nodes):
                self.assertIsNone(P.adopted_entry(mgr,cmd,123))


class BalanceHttpTest(unittest.TestCase):
    def setUp(self):
        from http.server import ThreadingHTTPServer
        import web_server
        self.tmp = tempfile.TemporaryDirectory()
        cfg, idx, nodes, inv = fixture()
        root = Path(self.tmp.name)
        idx["metadata"] = {"total_size": 6_000_000_000}
        (root/"config.json").write_text(json.dumps(cfg))
        (root/"model.safetensors.index.json").write_text(json.dumps(idx))
        (root/"tokenizer.json").write_text('{}')
        for name in set(idx['weight_map'].values()):
            (root/name).write_bytes(b'fixture')
        for n in nodes:
            inv[n["id"]]["path"] = str(root)
        self.entry = {"id":"tiny", "hf":"org/tiny", "source":"mlx", "name":"Tiny", "lead_path":str(root),
                      "weights_gb": 1, "nodes": {n["label"]:inv[n["id"]] for n in nodes}}
        self.app = web_server.App.__new__(web_server.App)
        self.app.mgr = mock.Mock()
        self.app.mgr.snapshot.return_value = {"model_id":"tiny", "status":"idle"}
        self.app.optimizer = mock.Mock()
        self.app.optimizer.snapshot.return_value = {"running":False}
        self.app._inflight = 0
        self.app.configured_nodes = mock.Mock(return_value=nodes)
        self.app.nodes = mock.Mock(return_value={"nodes":nodes})
        self.app.list_loadable_models = mock.Mock(return_value=[self.entry])
        self.app._ssh_fn = mock.Mock(return_value=mock.Mock())
        self.nodes = nodes
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=1); self.tmp.cleanup()

    def post(self, path, body):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        req = Request(f"http://127.0.0.1:{self.server.server_port}{path}", data=json.dumps(body).encode(),
                      headers={"Content-Type":"application/json"})
        try: response = urlopen(req,timeout=5)
        except HTTPError as e: response = e
        with response: return response.code, json.loads(response.read())

    def test_preview_is_read_only_and_uses_full_index_size(self):
        code,out = self.post("/api/balance", {"model_id":"tiny", "ram": {"available_gb":1000}})
        self.assertEqual(code,200)
        self.assertEqual(out["counts"], [4,4,4])
        self.assertEqual(out["stages"][0]["estimated_use_gb"],3.3)
        self.assertNotIn("entry",out)
        self.app.mgr.switch.assert_not_called()

    def test_invalid_counts_are_400(self):
        code,_ = self.post("/api/balance", {"model_id":"tiny", "counts":[1,1,1]})
        self.assertEqual(code,400)

    def test_non_object_is_400(self):
        self.assertEqual(self.post("/api/balance", [1,2,3])[0],400)

    def test_gguf_is_not_balance(self):
        self.entry["source"] = "gguf"
        self.assertEqual(self.post("/api/balance", {"model_id":"tiny"})[0],400)

    def test_reload_rechecks_live_memory_before_switch(self):
        live = {n["id"]:dict(n, ram={"available_gb":1}) for n in self.nodes}
        with mock.patch("web_nodes.gather_node_stats", side_effect=lambda n,**kw:live[n["id"]]):
            code,out = self.post("/api/models/load", {"model_id":"tiny", "balance":True, "counts":[4,4,4]})
        self.assertEqual(code,409)
        self.app.mgr.switch.assert_not_called()

    def test_reload_passes_server_constructed_plan(self):
        self.app.mgr.switch.return_value = {"status":"starting_packer"}
        with mock.patch("web_nodes.gather_node_stats", side_effect=lambda n,**kw:n):
            code,_ = self.post("/api/models/load", {"model_id":"tiny", "balance":True, "counts":[3,5,4]})
        self.assertEqual(code,200)
        entry = self.app.mgr.switch.call_args.kwargs["entry"]
        self.assertEqual(entry["split_counts"], [3,5,4])
        self.assertEqual(len(entry["pipeline_nodes"]),3)

    def test_n_stage_optimize_is_blocked(self):
        self.app.mgr.snapshot.return_value = {"balance":{"counts":[4,4,4]}}
        code,_ = self.post("/api/optimize/start", {})
        self.assertEqual(code,409)
        self.app.optimizer.start.assert_not_called()

    def test_reload_refused_during_a_reply(self):
        self.app._inflight = 1
        self.assertEqual(self.post("/api/models/load", {"model_id":"tiny", "balance":True})[0],409)
        self.app.mgr.switch.assert_not_called()


if __name__ == "__main__": unittest.main()
