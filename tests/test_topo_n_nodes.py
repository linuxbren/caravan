"""Day 16: Topology gather + disk sizes skip non-models + tuned single key."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web_nodes as N


class GatherAllNNodesTest(unittest.TestCase):
    def test_one_node(self):
        nodes = [{"id": "exo1", "label": "EXO1", "role": "lead", "host": "local"}]

        def local():
            return {"cpu_pct": 10, "gpu_pct": 5,
                    "ram": {"total_gb": 64, "used_gb": 20, "available_gb": 40},
                    "disk": {"total_gb": 400, "used_gb": 100, "free_gb": 300},
                    "temp_c": 42.0}

        out = N.gather_all(
            nodes, local_gather=local, model="m",
            split={"lead": {"name": "layers 0-47", "weights_gb": 2.0}})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label"], "EXO1")
        self.assertFalse(out[0].get("offline"))
        self.assertEqual(out[0]["layers"], "layers 0-47")
        self.assertEqual(out[0]["model"], "m")

    def test_three_nodes_offline_middle(self):
        nodes = [
            {"id": "exo1", "label": "EXO1", "role": "lead", "host": "local"},
            {"id": "exo2", "label": "EXO2", "role": "packer",
             "host": "exo2", "ssh": "exo2", "repo": "~/cv3"},
            {"id": "exo3", "label": "EXO3", "role": "packer",
             "host": "exo3", "ssh": "exo3", "repo": "~/cv3"},
        ]

        def local():
            return {"cpu_pct": 1,
                    "ram": {"total_gb": 64, "used_gb": 10, "available_gb": 50},
                    "disk": {"total_gb": 400, "used_gb": 50, "free_gb": 350}}

        def ssh_fn(node, cmd, timeout=25):
            class R:
                returncode = 1
                stdout = ""
                stderr = "down"

            if node["id"] == "exo3":
                class ROK:
                    returncode = 0
                    stdout = (
                        '{"cpu_pct": 3, "ram": {"total_gb": 64, "used_gb": 8, '
                        '"available_gb": 50}, "disk": {"total_gb": 400, '
                        '"used_gb": 40, "free_gb": 360}}'
                    )
                    stderr = ""
                return ROK()
            return R()

        split = {
            "lead": {"name": "layers 24-47", "weights_gb": 1.0},
            "packers": [
                {"name": "layers 0-11", "weights_gb": 0.5},
                {"name": "layers 12-23", "weights_gb": 0.5},
            ],
        }
        out = N.gather_all(nodes, ssh_fn=ssh_fn, local_gather=local,
                           model="m", split=split)
        self.assertEqual(len(out), 3)
        self.assertFalse(out[0]["offline"])
        self.assertTrue(out[1]["offline"])
        self.assertFalse(out[2]["offline"])
        self.assertEqual(out[0]["layers"], "layers 24-47")
        self.assertEqual(out[1]["layers"], "layers 0-11")
        self.assertEqual(out[2]["layers"], "layers 12-23")


class DiskSizesSkipCachesTest(unittest.TestCase):
    def test_caches_not_listed(self):
        import picker_disk_sizes as P
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / ".exo" / "models"
            (root / "caches").mkdir(parents=True)
            (root / "caches" / "x.bin").write_bytes(b"x" * 100)
            good = root / "mlx-community--Tiny-1bit"
            good.mkdir()
            (good / "config.json").write_text("{}")
            (good / "w.safetensors").write_bytes(b"y" * 50)
            # sizes() calls Path.home() — patch the home used inside module
            real = P.Path
            class FakePath(type(Path("."))):  # noqa: E701 — too clever; use mock
                pass
            with mock.patch("picker_disk_sizes.Path") as PP:
                # Make Path(...) still work, Path.home() -> home
                def path_side(*a, **k):
                    return Path(*a, **k) if a else Path()
                PP.side_effect = lambda *a, **k: Path(*a, **k) if a else Path()
                PP.home = mock.Mock(return_value=home)
                # du_gb and helpers also use Path() — re-implement call via rewrite
            # Simpler: temporarily chdir-style by patching sizes internals
            orig = P.sizes

            def fake_sizes():
                models = {}
                for root2 in (home / ".caravan" / "mlx-models", home / ".exo" / "models"):
                    if not root2.is_dir():
                        continue
                    for pth in root2.iterdir():
                        if not P._looks_like_model(pth):
                            continue
                        models[pth.name.replace("--", "/")] = P.du_gb(pth)
                return {"models": models, "cleanup": {}}

            s = fake_sizes()
            self.assertIn("mlx-community/Tiny-1bit", s["models"])
            self.assertNotIn("caches", s["models"])


class TunedEntrySpannedTest(unittest.TestCase):
    def test_single_uses_single_key(self):
        import web_workers as W
        mgr = W.WorkerManager.__new__(W.WorkerManager)
        mgr.state = {"split": False}
        mgr.tuned_path = None
        with mock.patch.object(W.TS, "load_store", return_value={"models": {
            "foo:single": {"reply_n": 3},
            "foo:spanned": {"reply_n": 9},
        }}):
            with mock.patch.object(
                    W.TS, "entry_key",
                    side_effect=lambda p, spanned=True: (
                        f"foo:{'spanned' if spanned else 'single'}")):
                _st, e = W.WorkerManager._tuned_entry(mgr, "/tmp/foo", create=False)
        self.assertEqual(e["reply_n"], 3)


class ResolveWorkerNodeTest(unittest.TestCase):
    def test_exo2_placement(self):
        import web_workers as W
        mgr = W.WorkerManager.__new__(W.WorkerManager)
        mgr.packer_ssh = "brenden@169.254.103.191"
        mgr.state = {"split": False}
        nodes = [
            {"id": "exo1", "label": "EXO1", "role": "lead", "host": "local"},
            {"id": "exo2", "label": "EXO2", "role": "packer",
             "host": "brenden@169.254.103.191", "ssh": "brenden@169.254.103.191",
             "repo": "~/cv3"},
        ]
        with mock.patch("web_nodes.nodes_from_config", return_value=nodes):
            n = W.WorkerManager._resolve_worker_node(
                mgr, {"lead_path": "/x"},
                place={"mode": "one", "node_ids": ["exo2"], "node_labels": ["EXO2"]})
        self.assertIsNotNone(n)
        self.assertEqual(n["id"], "exo2")


if __name__ == "__main__":
    unittest.main()


class TestModelHosts(unittest.TestCase):
    CFG = [{"id": "exo1", "role": "lead", "host": "local"},
           {"id": "exo2", "role": "packer", "host": "x"}]

    def _g(self, **kw):
        import json, types, web_nodes
        lg = lambda: {"cpu": 1}
        ssh = lambda n, cmd, timeout=25: types.SimpleNamespace(returncode=0, stdout=json.dumps({"cpu": 1}), stderr="")
        return {n["id"]: n for n in web_nodes.gather_all(self.CFG, ssh_fn=ssh, local_gather=lg, **kw)}

    def test_single_lead_only(self):
        r = self._g(model="JevK5", split=None, running_on=["exo1"])
        self.assertEqual(r["exo1"]["model"], "JevK5")
        self.assertEqual(r["exo2"]["model"], "")
        self.assertIsNone(r["exo2"]["layers"])

    def test_single_default_is_lead(self):
        r = self._g(model="JevK5", split=None)
        self.assertEqual(r["exo2"]["model"], "")

    def test_single_remote_worker(self):
        r = self._g(model="M", split=None, running_on=["exo2"])
        self.assertEqual(r["exo1"]["model"], "")
        self.assertEqual(r["exo2"]["model"], "M")

    def test_idle(self):
        r = self._g(model=None, split=None, running_on=[])
        self.assertEqual(r["exo1"]["model"], "")
        self.assertEqual(r["exo2"]["model"], "")

    def test_split_both_with_layers(self):
        sp = {"lead": {"name": "0-23"}, "packers": [{"name": "24-47"}]}
        r = self._g(model="Big", split=sp)
        self.assertEqual(r["exo1"]["model"], "Big")
        self.assertEqual(r["exo2"]["model"], "Big")
        self.assertEqual(r["exo1"]["layers"], "0-23")
        self.assertIn("24-47", str(r["exo2"]["layers"]))
