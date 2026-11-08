"""Day 18 split point safety. Numbers from Dark Champion 21B 8-bit (32 layers,
~0.71 GB/layer) on two 24 GB Minis: 24/8 left EXO2 1.5-1.7 GB free (507 on
every chat); 16/16 worked with ~11.3 GB of layers per Mini."""
import json, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import split_balance as SB
import web_catalog
import web_server
from web_workers import WorkerManager

REPO = Path(__file__).resolve().parent.parent
PL = 0.71
GB24 = {"total_gb": 24.0, "available_gb": 20.0}


class MathTest(unittest.TestCase):
    def test_tonight_24_8_is_unsafe_16_16_balanced(self):
        c = SB.check([24, 8], [20.0, 20.0], PL, ["EXO2", "EXO1"])
        self.assertFalse(c["ok"])
        self.assertEqual(c["low"][0]["label"], "EXO2")
        self.assertTrue(1.5 <= c["low"][0]["free_gb"] < 1.75)
        self.assertEqual(c["balanced"], [16, 16])
        self.assertTrue(c["balanced_ok"] and c["better"])
        self.assertAlmostEqual(16 * PL, 11.36, places=2)

    def test_16_16_ok(self):
        self.assertTrue(SB.check([16, 16], [20.0, 20.0], PL)["ok"])

    def test_any_number_of_minis(self):
        self.assertEqual(sum(SB.balanced_counts(80, [20, 44, 44, 60], PL)), 80)
        c = SB.balanced_counts(80, [20, 44, 44], PL)
        self.assertLess(c[0], c[1]); self.assertEqual(c[1], c[2])
        self.assertEqual(SB.balanced_counts(33, [20, 20, 20], PL), [11, 11, 11])

    def test_unequal_two(self):
        c = SB.balanced_counts(32, [20.0, 44.0], PL)  # 24 GB packer + 48 GB lead
        self.assertLess(c[0], 16)
        self.assertTrue(SB.check(c, [20.0, 44.0], PL)["ok"])

    def test_nothing_fits(self):
        c = SB.check([16, 16], [8.0, 8.0], PL, ["A", "B"])
        self.assertFalse(c["ok"]); self.assertFalse(c["better"])
        self.assertIn("smaller version", SB.message(c, ["A", "B"]))

    def test_download_default_balanced(self):
        nodes = [{"id": "exo1", "role": "lead", "ram": GB24}, {"id": "exo2", "role": "packer", "ram": GB24}]
        self.assertEqual(SB.balanced_packer_layers(32, 32 * PL, nodes), 16)
        self.assertIsNone(SB.balanced_packer_layers(32, 32 * PL, [nodes[0]]))

    def test_message_names_files_no_autodownload(self):
        c = SB.check([24, 8], [20.0, 20.0], PL, ["EXO2", "EXO1"])
        m = SB.message(c, ["EXO2", "EXO1"], {"EXO2": [], "EXO1": ["model-00003-of-00005.safetensors"]})
        self.assertIn("16/16", m); self.assertIn("model-00003-of-00005.safetensors", m)
        self.assertIn("won't download", m)


def fake_tree(root: Path, shards_layers):
    """shards_layers: list of layer ranges per shard (5 shards like Dark Champion)."""
    d = root / "dc"; d.mkdir(parents=True)
    wm = {"model.embed_tokens.weight": "model-00001-of-00005.safetensors",
          "lm_head.weight": "model-00005-of-00005.safetensors",
          "model.norm.weight": "model-00005-of-00005.safetensors"}
    for i, rng in enumerate(shards_layers):
        for L in rng:
            wm[f"model.layers.{L}.self_attn.q_proj.weight"] = f"model-0000{i + 1}-of-00005.safetensors"
    (d / "config.json").write_text(json.dumps({"model_type": "mixtral", "num_hidden_layers": 32,
                                               "tie_word_embeddings": True}))
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": wm}))
    return d


SHARDS = [range(0, 8), range(8, 16), range(16, 24), range(24, 32), range(0)]


class CatalogSafetyTest(unittest.TestCase):
    def setUp(self):
        self.d = fake_tree(Path(tempfile.mkdtemp()), SHARDS)
        self.stages = [{"id": "exo1", "label": "EXO1", "role": "lead"},
                       {"id": "exo2", "label": "EXO2", "role": "packer"}]
        self.fit = [dict(s, ram=GB24) for s in self.stages]

    def chk(self, per):
        return web_catalog._split_safety("x/dc", 24, 32 * PL, 32, self.stages, self.fit, per, str(self.d))

    def test_needs_extra_file(self):
        per = {"EXO1": {"shards_present": ["model-00001-of-00005.safetensors", "model-00004-of-00005.safetensors",
                                           "model-00005-of-00005.safetensors"]},
               "EXO2": {"shards_present": ["model-00001-of-00005.safetensors", "model-00002-of-00005.safetensors",
                                           "model-00003-of-00005.safetensors"]}}
        c = self.chk(per)
        self.assertFalse(c["ok"]); self.assertEqual(c["balanced_packer_layers"], 16)
        self.assertEqual(c["extra_files"], {"EXO2": [], "EXO1": ["model-00003-of-00005.safetensors"]})
        self.assertFalse(c["balanced_ready"])
        self.assertIn("model-00003-of-00005.safetensors", c["note"])

    def test_ready(self):
        allf = [f"model-0000{i}-of-00005.safetensors" for i in range(1, 6)]
        c = self.chk({"EXO1": {"shards_present": allf}, "EXO2": {"shards_present": allf}})
        self.assertTrue(c["balanced_ready"]); self.assertIn("load it that way", c["note"])

    def test_unknown_ram_is_silent(self):
        self.assertIsNone(web_catalog._split_safety("x", 24, 22.7, 32, self.stages, self.stages, {}, None))


class LoadEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mgr = WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560", packer_ssh="nobody@127.0.0.1",
                            state_dir=REPO / "handoff" / "lab" / "day15-web" / "test-state", repo=REPO)
        cls.app = web_server.App(mgr)
        cls.switched = []
        mgr.switch = lambda mid, wait=False, settings=None, entry=None: cls.switched.append(entry) or {"status": "loading"}
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(cls.app))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def load(self, row, body=None):
        self.app.list_loadable_models = lambda: [row]
        req = Request(self.base + "/api/models/load", method="POST",
                      data=json.dumps(dict({"model_id": row["id"]}, **(body or {}))).encode(),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def row(self, **sc):
        base = SB.check([24, 8], [20.0, 20.0], PL, ["EXO2", "EXO1"])
        base.update(balanced_packer_layers=16, **sc)
        return {"id": "dc", "hf": "x/dc", "packer_layers": 24, "run_mode": "split",
                "split_check": base, "split_note": "too tight; needs model-00003"}

    def test_missing_files_refuses_with_message(self):
        st, j = self.load(self.row(balanced_ready=False))
        self.assertEqual(st, 409); self.assertIn("model-00003", j["error"])

    def test_ready_loads_balanced(self):
        self.switched.clear()
        st, j = self.load(self.row(balanced_ready=True))
        self.assertEqual(st, 200); self.assertEqual(self.switched[-1]["packer_layers"], 16)
        self.assertIn("16/16", j["balance_note"])

    def test_force_keeps_saved(self):
        self.switched.clear()
        st, _ = self.load(self.row(balanced_ready=False), {"force_split": True})
        self.assertEqual(st, 200); self.assertEqual(self.switched[-1]["packer_layers"], 24)


if __name__ == "__main__":
    unittest.main()
