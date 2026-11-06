"""Placement-aware load: one-Mini skips packer; preflight; qwen3_5_text remap."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "agent"))

import mlx_arch as A  # noqa: E402
import placement as PL  # noqa: E402
import web_catalog as C  # noqa: E402


class ArchTest(unittest.TestCase):
    def test_qwen3_5_text_remaps_supported(self):
        st = A.architecture_status(model_type="qwen3_5_text")
        self.assertTrue(st["supported"])
        self.assertEqual(st["effective"], "qwen3_5")
        self.assertTrue(st["remapped"])

    def test_apply_remaps_patches_dict(self):
        fake = {"mistral": "llama"}
        with mock.patch.dict("sys.modules", {"mlx_lm": mock.Mock(), "mlx_lm.utils": mock.Mock(MODEL_REMAPPING=fake)}):
            # Re-import apply against patched - call directly with monkeypatch
            import mlx_lm.utils as U
            U.MODEL_REMAPPING = fake
            applied = A.apply_mlx_lm_remaps()
            self.assertIn(("qwen3_5_text", "qwen3_5"), applied)
            self.assertEqual(fake["qwen3_5_text"], "qwen3_5")


class RunModeTest(unittest.TestCase):
    def _mgr(self):
        import web_workers as W
        return W.WorkerManager.__new__(W.WorkerManager)

    def test_one_placement_is_single(self):
        mgr = self._mgr()
        entry = {
            "placement": {"mode": "one", "node_ids": ["exo1"], "node_labels": ["EXO1"], "full_copy": True},
            "lead_path": "/tmp/m",
        }
        self.assertEqual(mgr._resolve_run_mode(entry), "single")

    def test_all_placement_is_single(self):
        mgr = self._mgr()
        entry = {"placement": {"mode": "all", "node_ids": ["exo1", "exo2"]}, "lead_path": "/tmp/m"}
        self.assertEqual(mgr._resolve_run_mode(entry), "single")

    def test_split_placement_is_split(self):
        mgr = self._mgr()
        entry = {"placement": {"mode": "split", "k": 2, "node_ids": ["exo1", "exo2"]}}
        self.assertEqual(mgr._resolve_run_mode(entry), "split")

    def test_other_mini_only_refuses(self):
        mgr = self._mgr()
        entry = {
            "placement": {"mode": "one", "node_ids": ["exo2"], "node_labels": ["EXO2"]},
            "lead_path": "/tmp/m",
        }
        with self.assertRaises(RuntimeError) as cm:
            mgr._resolve_run_mode(entry)
        self.assertIn("isn't supported yet", str(cm.exception))

    def test_preflight_missing_folder(self):
        mgr = self._mgr()
        mgr._note = lambda *a, **k: None
        problems = mgr.preflight_load({
            "run_mode": "single",
            "lead_path": "/no/such/model/dir",
        })
        self.assertTrue(any("missing" in p for p in problems))

    def test_get_model_reads_placement(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "config.json").write_text(json.dumps({
                "model_type": "qwen3_5_text",
                "architectures": ["Qwen3_5ForCausalLM"],
                "num_hidden_layers": 4,
                "hidden_size": 64,
                "vocab_size": 100,
            }))
            (d / "model.safetensors").write_bytes(b"x" * 100)
            (d / "tokenizer.json").write_text("{}")
            PL.write_placement(d, {
                "mode": "one", "k": 1, "node_ids": ["exo1"],
                "node_labels": ["EXO1"], "repo_id": "org/m", "full_copy": True,
            })
            # Point scan at our temp root
            with mock.patch.object(C.inv, "MODEL_ROOTS", [d.parent]):
                # folder name must look like org--name
                named = d.parent / "org--m"
                if named.exists():
                    pass
                else:
                    named.symlink_to(d) if hasattr(Path, 'symlink_to') else None
            # Directly exercise resolve via entry with lead path
            entry = C.resolve_entry({
                "id": "m", "name": "m", "hf": "org/m",
                "lead_paths": [str(d)], "packer_paths": [str(d)],
                "packer_layers": 2,
            })
            place = PL.read_placement(entry["lead_path"])
            self.assertEqual(place["mode"], "one")
            # WorkerManager path
            mgr = self._mgr()
            entry["placement"] = place
            entry["lead_path"] = str(d)
            self.assertEqual(mgr._resolve_run_mode(entry), "single")


class LoadOnceBranchTest(unittest.TestCase):
    def test_single_skips_packer(self):
        import web_workers as W
        mgr = W.WorkerManager.__new__(W.WorkerManager)
        mgr._reload_trial = None
        mgr.check_lpm = lambda: True
        mgr._note = lambda *a, **k: None
        notes = []
        mgr._set = lambda **kw: notes.append(kw)
        mgr.plan_reload_args = lambda *a, **k: []
        mgr._kill_lead = lambda: None
        mgr._kill_packer = lambda: None
        started = {"packer": False, "lead_split": None}

        def start_lead(entry, *, split=True):
            started["lead_split"] = split
            return 1

        def start_packer(*a, **k):
            started["packer"] = True
            return 2

        mgr._start_lead = start_lead
        mgr._start_packer = start_packer
        mgr._wait_lead_ready = lambda timeout=600: None
        mgr._wait_packer_ready = lambda timeout=300: None
        mgr._resolve_packer_path = lambda e: "/packer"
        mgr.preflight_load = lambda e: []
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "config.json").write_text(json.dumps({"model_type": "llama", "num_hidden_layers": 2}))
            (d / "model.safetensors").write_bytes(b"x")
            PL.write_placement(d, {"mode": "one", "node_ids": ["exo1"], "node_labels": ["EXO1"], "full_copy": True})
            entry = {
                "id": "m", "name": "M", "lead_path": str(d),
                "packer_layers": 1,
                "placement": PL.read_placement(d),
            }
            with mock.patch("web_settings.to_args", return_value=([], [])):
                with mock.patch("time.sleep", return_value=None):
                    mgr._load_once(entry, {})
        self.assertFalse(started["packer"])
        self.assertEqual(started["lead_split"], False)


if __name__ == "__main__":
    unittest.main()
