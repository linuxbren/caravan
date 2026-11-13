import json, tempfile, threading, time, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_gguf_optimize as WGO
import web_server
from web_workers import WorkerManager

REPO = Path(__file__).resolve().parent.parent


class FakeMgr:
    lead_port = 1
    def __init__(self):
        self._loaded_entry = {"id": "gguf/m", "source": "gguf", "lead_path": "/tmp/m.gguf"}
        self.switches = []
        self._snap = {"status": "ready", "model_id": "gguf/m", "backend": "llama",
                      "gguf": {"nodes": ["exo1", "exo2"]}, "settings": {}}
    def snapshot(self):
        return dict(self._snap)
    def switch(self, mid, wait=False, settings=None, entry=None):
        self.switches.append(entry.get("tune_override"))
        return self.snapshot()


class FakeTuner:
    def __init__(self, path, n, *, restart, measure, store_path, log, cancelled):
        self.restart, self.measure, self.log, self.n = restart, measure, log, n
    def run(self):
        self.restart({"ubatch": 512}); self.measure()
        self.restart({"ubatch": 256}); self.measure()
        self.log("gguf tune: ubatch 512=10.0 vs 256=12.0 tok/s -> keep 256")
        self.restart({"ubatch": 256})
        return {"status": "done", "best": {"ubatch": 256}, "tried": [{"name": "ubatch", "won": True}]}


def wait_done(opt):
    for _ in range(200):
        if not opt.snapshot()["running"]:
            return opt.snapshot()
        time.sleep(0.01)
    raise AssertionError("did not finish")


class GgufOptimizerTest(unittest.TestCase):
    def make(self, mgr=None):
        return WGO.GgufOptimizer(mgr or FakeMgr(), tuner_cls=FakeTuner, measure=lambda: 10.0,
                                 store_path=Path(tempfile.mkdtemp()) / "t.json", sleep=lambda s: None)

    def test_runs_and_reports(self):
        mgr = FakeMgr(); opt = self.make(mgr)
        s = opt.start()
        self.assertTrue(s["running"]); self.assertTrue(s["schedule"])
        s = wait_done(opt)
        self.assertEqual(s["reloads"], 3); self.assertEqual(s["prompts"], 12)  # 2 arms x (5 short + 1 long)
        self.assertEqual(s["summary"]["winner"], {"ubatch": 256}); self.assertTrue(s["summary"]["complete"])
        ub = next(i for i in s["schedule"] if i["name"] == "ubatch")
        self.assertEqual((ub["state"], ub["winner"]), ("kept", "256"))
        self.assertEqual(mgr.switches, [{"ubatch": 512}, {"ubatch": 256}, {"ubatch": 256}])
        self.assertEqual(s["backend"], "llama"); self.assertIsNone(s["error"])

    def test_refuses_non_gguf(self):
        mgr = FakeMgr(); mgr._snap["backend"] = "mlx"
        with self.assertRaises(RuntimeError):
            self.make(mgr).start()

    def test_eta(self):
        opt = self.make()
        opt.state.update(running=True, reload_s=10.0, reply_s=5.0,
                         schedule=[{"name": "a", "state": "pending", "done_arms": 0},
                                   {"name": "b", "state": "running", "done_arms": 1}])
        # a: 2*(10+10)=40, b: 1*(20)=20, + final restore 10
        self.assertEqual(opt.snapshot()["eta_s"], 70)


class GgufEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560", packer_ssh="nobody@127.0.0.1",
                            state_dir=REPO / "handoff" / "lab" / "day15-web" / "test-state", repo=REPO)
        cls.app = web_server.App(mgr)
        cls.fake = FakeMgr()
        cls.app.gguf_optimizer = WGO.GgufOptimizer(cls.fake, tuner_cls=FakeTuner, measure=lambda: 1.0,
                                                   store_path=Path(tempfile.mkdtemp()) / "t.json")
        cls.app.mgr.snapshot = cls.fake.snapshot
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(cls.app))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def post(self, path):
        req = Request(self.base + path, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_start_dispatches_to_gguf_and_get_reports(self):
        s = self.post("/api/optimize/start")
        self.assertEqual(s["backend"], "llama")
        wait_done(self.app.gguf_optimizer)
        with urlopen(self.base + "/api/optimize", timeout=5) as r:
            j = json.loads(r.read())
        self.assertEqual(j["summary"]["winner"], {"ubatch": 256})
        self.assertIs(self.app.optimizer, self.app.gguf_optimizer)
        s = self.post("/api/optimize/gguf/start"); wait_done(self.app.gguf_optimizer)
        self.assertEqual(s["mode"], "now")


if __name__ == "__main__":
    unittest.main()
