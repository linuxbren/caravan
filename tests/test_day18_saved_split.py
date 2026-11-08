from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import model_inventory as inv
import placement
import web_catalog

SHARDS = {1: ["embed"] + list(range(0, 7)), 2: list(range(7, 14)), 3: list(range(14, 20)),
          4: list(range(20, 28)), 5: list(range(28, 32)) + ["norm", "lm_head"]}


def make_tree(d: Path, have: list, place: dict | None):
    wm = {}
    for i, items in SHARDS.items():
        f = "model-%05d-of-00005.safetensors" % i
        for it in items:
            if it == "embed":
                wm["model.embed_tokens.weight"] = f
            elif it == "norm":
                wm["model.norm.weight"] = f
            elif it == "lm_head":
                wm["lm_head.weight"] = f
            else:
                wm["model.layers.%d.mlp.weight" % it] = f
        if i in have:
            (d / f).write_bytes(b"x")
    (d / "config.json").write_text(json.dumps({"num_hidden_layers": 32, "model_type": "llama"}))
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": wm}))
    (d / "tokenizer.json").write_text("{}")
    if place is not None:
        placement.write_placement(d, place)


class SavedSplit(unittest.TestCase):
    def test_saved_packer_layers_wins_over_default(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            make_tree(d, [4, 5], {"mode": "split", "node_ids": ["exo1", "exo2"], "packer_layers": 24})
            self.assertEqual(json.loads((d / "caravan-placement.json").read_text())["packer_layers"], 24)
            r = inv.inspect_tree(d, packer_layers=16)
            self.assertTrue(r["lead_ok"])
            self.assertEqual(r["packer_layers"], 24)

    def test_old_placement_without_field_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            make_tree(d, [4, 5], {"mode": "split", "node_ids": ["exo1", "exo2"]})
            r = inv.inspect_tree(d, packer_layers=16)
            self.assertTrue(r["lead_ok"])
            self.assertEqual(r["packer_layers"], 24)

    def test_packer_tree_ok_with_saved_split(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            make_tree(d, [1, 2, 3, 4], {"mode": "split", "packer_layers": 24})
            self.assertTrue(inv.inspect_tree(d, packer_layers=None)["packer_ok"])

    def test_defaults_match_download_default(self):
        self.assertEqual(web_catalog._default_packer_layers("someone/unknown-21B", 32), 24)
        self.assertEqual(web_catalog._default_packer_layers("someone/small", 16), 8)


if __name__ == "__main__":
    unittest.main()
