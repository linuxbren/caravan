"""Disk inventory + Settings model list (no static phantoms)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "agent"))

import model_inventory as inv  # noqa: E402
import web_catalog as catalog  # noqa: E402


def _write_fake_mlx(root: Path, folder: str, *, shards=None, incomplete=False,
                    config=True, tokenizer=True, index=True, n_layers=4):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    if config:
        (d / "config.json").write_text(json.dumps({
            "model_type": "qwen3", "num_hidden_layers": n_layers,
            "hidden_size": 64, "num_attention_heads": 4, "num_key_value_heads": 2,
            "vocab_size": 100,
        }))
    if tokenizer:
        (d / "tokenizer.json").write_text("{}")
    shards = shards if shards is not None else [f"model-0000{i}-of-00002.safetensors" for i in (1, 2)]
    if index:
        wm = {f"model.layers.{i}.weight": shards[i % len(shards)] for i in range(n_layers)}
        wm["model.embed_tokens.weight"] = shards[0]
        wm["lm_head.weight"] = shards[-1]
        (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": wm}))
    for s in shards:
        # 64-byte fake file (header check skipped when we only test presence in inventory)
        (d / s).write_bytes(b"x" * 128)
    if incomplete:
        c = d / ".cache" / "huggingface" / "download"
        c.mkdir(parents=True, exist_ok=True)
        (c / "foo.incomplete").write_bytes(b"partial")
    return d


class InspectTest(unittest.TestCase):
    def test_full_tree_ok(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_fake_mlx(Path(td), "mlx-community--Tiny-4bit")
            info = inv.inspect_tree(d, packer_layers=2)
            self.assertTrue(info["has_config"] and info["has_tokenizer"] and info["has_index"])
            self.assertFalse(info["incomplete"])
            # plan_files may mark lead/packer; full_ok when all shards present
            self.assertTrue(info["full_ok"] or (info["lead_ok"] and info["packer_ok"]))

    def test_incomplete_not_ok(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_fake_mlx(Path(td), "mlx-community--Tiny-4bit", incomplete=True)
            info = inv.inspect_tree(d)
            self.assertTrue(info["incomplete"])
            self.assertFalse(info["full_ok"])
            self.assertIn("incomplete", info["reason"])

    def test_missing_tokenizer(self):
        with tempfile.TemporaryDirectory() as td:
            d = _write_fake_mlx(Path(td), "mlx-community--Tiny-4bit", tokenizer=False)
            info = inv.inspect_tree(d)
            self.assertFalse(info["ok"])
            self.assertIn("tokenizer", info["reason"])


class SettingsListTest(unittest.TestCase):
    def test_static_catalog_not_listed_without_disk(self):
        rows = catalog.build_entries_from_inventories(
            node_inventories=[
                {"id": "exo1", "label": "EXO1", "role": "lead", "models": {}},
                {"id": "exo2", "label": "EXO2", "role": "packer", "models": {}},
            ],
            nodes=[
                {"id": "exo1", "label": "EXO1", "role": "lead",
                 "ram": {"available_gb": 20, "total_gb": 24}, "disk": {"free_gb": 100}},
                {"id": "exo2", "label": "EXO2", "role": "packer",
                 "ram": {"available_gb": 20, "total_gb": 24}, "disk": {"free_gb": 100}},
            ],
        )
        ids = {r["id"] for r in rows}
        self.assertNotIn("gpt-oss-20b-mxfp4", ids)
        self.assertNotIn("gemma-4-26b-a4b-4bit", ids)
        self.assertEqual(rows, [])

    def test_packer_only_gemma_disabled_with_reason(self):
        gem = "mlx-community/gemma-4-26b-a4b-it-8bit"
        rows = catalog.build_entries_from_inventories(
            node_inventories=[
                {"id": "exo1", "label": "EXO1", "role": "lead", "models": {}},
                {"id": "exo2", "label": "EXO2", "role": "packer", "models": {
                    gem: {"path": "/remote/gemma", "weights_gb": 14.0, "full_ok": True,
                          "lead_ok": True, "packer_ok": True, "kind": "full", "n_layers": 30},
                }},
            ],
            nodes=[
                {"id": "exo1", "label": "EXO1", "role": "lead",
                 "ram": {"available_gb": 16, "total_gb": 24}, "disk": {"free_gb": 100}},
                {"id": "exo2", "label": "EXO2", "role": "packer",
                 "ram": {"available_gb": 16, "total_gb": 24}, "disk": {"free_gb": 100}},
            ],
        )
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertFalse(r["usable"])
        self.assertIn("EXO1", r["disabled_reason"])

    def test_complete_on_both_usable(self):
        rid = "mlx-community/Qwen3-30B-A3B-4bit"
        st = {"path": "/x", "weights_gb": 17.0, "full_ok": True, "lead_ok": True,
              "packer_ok": True, "kind": "full", "n_layers": 48}
        rows = catalog.build_entries_from_inventories(
            node_inventories=[
                {"id": "exo1", "label": "EXO1", "role": "lead", "models": {rid: dict(st, path="/lead")}},
                {"id": "exo2", "label": "EXO2", "role": "packer", "models": {rid: dict(st, path="/pack")}},
            ],
            nodes=[
                {"id": "exo1", "label": "EXO1", "role": "lead",
                 "ram": {"available_gb": 18, "total_gb": 24}, "disk": {"free_gb": 200}},
                {"id": "exo2", "label": "EXO2", "role": "packer",
                 "ram": {"available_gb": 18, "total_gb": 24}, "disk": {"free_gb": 200}},
            ],
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["usable"])
        self.assertEqual(rows[0]["id"], "qwen3-30b-a3b-4bit")  # catalog slug
        self.assertEqual(rows[0]["lead_path"], "/lead")

    def test_current_kept_even_if_incomplete(self):
        rid = "mlx-community/Qwen3-30B-A3B-4bit"
        rows = catalog.build_entries_from_inventories(
            node_inventories=[{
                "id": "exo1", "label": "EXO1", "role": "lead",
                "models": {rid: {"path": "/lead", "weights_gb": 17.0, "full_ok": False,
                                 "lead_ok": False, "packer_ok": False, "kind": "partial",
                                 "reason": "missing shards"}},
            }],
            nodes=[{
                "id": "exo1", "label": "EXO1", "role": "lead",
                "ram": {"available_gb": 18, "total_gb": 24}, "disk": {"free_gb": 200},
            }],
            current_id="qwen3-30b-a3b-4bit",
            current_hf=rid,
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["usable"])


if __name__ == "__main__":
    unittest.main()
