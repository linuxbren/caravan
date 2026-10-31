import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import mlx_split_fetch as f
import mlx_split


def index(n, per_file, extra):
    wm = {}
    for i in range(n):
        for w in ("self_attn.q_proj.weight", "mlp.gate.weight"):
            wm[f"model.layers.{i}.{w}"] = f"model-{i // per_file + 1:05d}.safetensors"
    wm.update(extra)
    return {"weight_map": wm}


class PlanTest(unittest.TestCase):
    def test_untied_boundary_shard_shared(self):
        idx = index(8, 3, {"model.embed_tokens.weight": "model-00001.safetensors",
                           "model.norm.weight": "model-00003.safetensors",
                           "lm_head.weight": "model-00003.safetensors"})
        p = f.plan_files({"num_hidden_layers": 8}, idx)
        self.assertEqual(p["split"], ((0, 4), (4, 8)))
        self.assertFalse(p["tied"])
        # layers 0-2 file1, 3-5 file2 (straddles 3|4), 6-7 file3
        self.assertEqual(p["front"], {"model-00001.safetensors", "model-00002.safetensors"})
        self.assertEqual(p["head"], {"model-00002.safetensors", "model-00003.safetensors"})
        self.assertEqual(p["shared"], {"model-00002.safetensors"})

    def test_tied_head_needs_embeddings_and_vision_skipped(self):
        idx = index(4, 2, {"language_model.model.embed_tokens.weight": "model-00001.safetensors",
                           "language_model.model.norm.weight": "model-00002.safetensors",
                           "vision_tower.encoder.layers.0.w": "model-00009.safetensors",
                           "embed_vision.embedding_projection.weight": "model-00009.safetensors"})
        idx["weight_map"] = {("language_model." + k if k.startswith("model.layers") else k): v
                             for k, v in idx["weight_map"].items()}
        cfg = {"text_config": {"num_hidden_layers": 4}}
        p = f.plan_files(cfg, idx)
        self.assertTrue(p["tied"])
        self.assertEqual(p["front"], {"model-00001.safetensors"})
        self.assertEqual(p["head"], {"model-00001.safetensors", "model-00002.safetensors"})
        self.assertIn("model-00009.safetensors", f.plan_files(cfg, idx, with_vision=True)["front"])

    def test_front_layers_override_and_unknown_to_both(self):
        idx = index(6, 1, {"model.rotary.inv_freq": "model-00099.safetensors", "lm_head.weight": "model-00006.safetensors"})
        p = f.plan_files({"num_hidden_layers": 6}, idx, front_layers=2)
        self.assertEqual(p["split"], ((0, 2), (2, 6)))
        self.assertIn("model-00099.safetensors", p["front"] & p["head"])
        self.assertNotIn("model-00003.safetensors", p["front"])

    def test_check_local_shards(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            idx = index(4, 2, {"lm_head.weight": "model-00002.safetensors", "model.embed_tokens.weight": "model-00001.safetensors"})
            (d / "config.json").write_text(json.dumps({"num_hidden_layers": 4}))
            (d / "model.safetensors.index.json").write_text(json.dumps(idx))
            (d / "model-00001.safetensors").write_text("x")
            self.assertEqual(mlx_split.check_local_shards(str(d), "front"), ["model-00001.safetensors"])
            with self.assertRaises(FileNotFoundError):
                mlx_split.check_local_shards(str(d), "head")
            self.assertEqual(mlx_split.check_local_shards(t + "/nope", "head"), [])


if __name__ == "__main__":
    unittest.main()
