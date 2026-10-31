import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import mlx_split_fetch as f
import mlx_split


def write_st(path, nbytes=16, cut=0, extra=b""):
    """A minimal valid safetensors file with one uint8 tensor of nbytes,
    optionally cut short by `cut` bytes or padded with `extra`."""
    import struct
    head = json.dumps({"w": {"dtype": "U8", "shape": [nbytes], "data_offsets": [0, nbytes]}}).encode()
    data = struct.pack("<Q", len(head)) + head + b"\0" * nbytes + extra
    Path(path).write_bytes(data[:len(data) - cut] if cut else data)
    return len(data)


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
            write_st(d / "model-00001.safetensors")
            self.assertEqual(mlx_split.check_local_shards(str(d), "front"), ["model-00001.safetensors"])
            with self.assertRaises(FileNotFoundError):
                mlx_split.check_local_shards(str(d), "head")
            self.assertEqual(mlx_split.check_local_shards(t + "/nope", "head"), [])


class SizeCheckTest(unittest.TestCase):
    def _dir(self, t):
        d = Path(t)
        idx = index(4, 2, {"lm_head.weight": "model-00002.safetensors",
                           "model.embed_tokens.weight": "model-00001.safetensors"})
        (d / "config.json").write_text(json.dumps({"num_hidden_layers": 4}))
        (d / "model.safetensors.index.json").write_text(json.dumps(idx))
        return d

    def test_expected_size_from_header(self):
        with tempfile.TemporaryDirectory() as t:
            n = write_st(Path(t) / "a.safetensors", 40)
            self.assertEqual(mlx_split.safetensors_expected_size(Path(t) / "a.safetensors"), n)
            (Path(t) / "b.safetensors").write_bytes(b"\x05\x00")
            self.assertIsNone(mlx_split.safetensors_expected_size(Path(t) / "b.safetensors"))
            self.assertIsNone(mlx_split.safetensors_expected_size(Path(t) / "missing.safetensors"))

    def test_cut_off_shard_stops_with_file_and_fetch_command(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._dir(t)
            write_st(d / "model-00001.safetensors", 64, cut=10)
            with self.assertRaises(mlx_split.ShardSizeError) as e:
                mlx_split.check_local_shards(str(d), "front", front_layers=2)
            msg = str(e.exception)
            self.assertIn("model-00001.safetensors", msg)
            self.assertIn("its header says", msg)
            self.assertIn("mlx_split_fetch.py <repo>", msg)
            self.assertIn("--role packer --packer-layers 2", msg)

    def test_extra_bytes_and_garbage_header_also_stop(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._dir(t)
            write_st(d / "model-00001.safetensors", 8, extra=b"zz")
            with self.assertRaises(mlx_split.ShardSizeError):
                mlx_split.check_local_shards(str(d), "front")
            (d / "model-00001.safetensors").write_text("x")
            with self.assertRaisesRegex(mlx_split.ShardSizeError, "cut-off or unreadable header"):
                mlx_split.check_local_shards(str(d), "front")

    def test_recorded_size_mismatch_names_repo(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._dir(t)
            n = write_st(d / "model-00001.safetensors")
            f.write_sizes(d, "org/model", {"model-00001.safetensors": n + 1})
            with self.assertRaises(mlx_split.ShardSizeError) as e:
                mlx_split.check_local_shards(str(d), "front")
            self.assertIn("Hugging Face lists", str(e.exception))
            self.assertIn("mlx_split_fetch.py org/model", str(e.exception))
            f.write_sizes(d, "org/model", {"model-00001.safetensors": n})
            self.assertEqual(mlx_split.check_local_shards(str(d), "front"), ["model-00001.safetensors"])

    def test_missing_shard_hint_uses_recorded_repo(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._dir(t)
            f.write_sizes(d, "org/model", {"model-00002.safetensors": 5})
            with self.assertRaisesRegex(FileNotFoundError, "mlx_split_fetch.py org/model .* --role lead"):
                mlx_split.check_local_shards(str(d), "head")

    def test_write_sizes_merges_same_repo_only(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            f.write_sizes(d, "org/a", {"x.safetensors": 1})
            f.write_sizes(d, "org/a", {"y.safetensors": 2, "z.safetensors": 0})
            r = json.loads((d / mlx_split.SIZES_FILE).read_text())
            self.assertEqual(r, {"repo": "org/a", "sizes": {"x.safetensors": 1, "y.safetensors": 2}})
            f.write_sizes(d, "org/b", {"q.safetensors": 3})
            r = json.loads((d / mlx_split.SIZES_FILE).read_text())
            self.assertEqual(r["sizes"], {"q.safetensors": 3})


if __name__ == "__main__":
    unittest.main()
