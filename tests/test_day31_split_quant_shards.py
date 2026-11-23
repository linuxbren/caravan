"""Day 31 follow-up (v0.9.3): split loads of a pre-quantized MLX model whose
pieces straddle shard files.

Qwen3-32B-4bit crashed on the lead with KeyError
'model.layers.17.mlp.up_proj.weight': layer 17's up_proj weight is in shard
1 (only on the 2nd Mac), its scales and biases in shard 2 (on both). mlx_lm
0.32.2's load_model quant inference needs the weight whenever the scales are
there. The fix (found on the Macs, Claude's local patch) leaves such a piece
unquantized; it belongs to the other stage and is dropped after load.
No mlx needed: shapes and the mlx_lm logic are faked here.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import mlx_split as S  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json


class Arr:
    def __init__(self, *shape, dtype="bfloat16"):
        self.shape, self.dtype = shape, dtype


class Linear:
    def __init__(self, out_dims, in_dims):
        self.weight = Arr(out_dims, in_dims)

    def to_quantized(self, **kw):  # only its presence matters here
        return kw


def infer_quant_config_0322(path, module, weights):
    """mlx_lm 0.32.2 infer_quant_config (affine branch)."""
    scales = weights[f"{path}.scales"]
    in_dims = module.weight.shape[-1]
    group_size = in_dims // scales.shape[-1]
    bits = (weights[f"{path}.weight"].shape[-1] * 32) // in_dims
    return {"group_size": group_size, "bits": bits, "mode": "affine"}


def class_predicate_0322(p, m, weights, infer, per_layer=None):
    """mlx_lm 0.32.2 load_model._quantize.class_predicate."""
    if p in (per_layer or {}):
        return per_layer[p]
    if not hasattr(m, "to_quantized"):
        return False
    if f"{p}.scales" not in weights:
        return False
    return infer(p, m, weights)


IN, OUT, GROUP, BITS = 5120, 25600, 64, 4


def piece(i, name):
    return f"model.layers.{i}.mlp.{name}"


def tensors(path):
    return {f"{path}.weight": Arr(OUT, IN * BITS // 32, dtype="uint32"),
            f"{path}.scales": Arr(OUT, IN // GROUP),
            f"{path}.biases": Arr(OUT, IN // GROUP)}


def shard_map():
    """Qwen3-32B-4bit-like: 4 shards, layer 17 up_proj weight in shard 1,
    its scales/biases in shard 2."""
    shards = {1: {}, 2: {}, 3: {}, 4: {}}
    for i in range(64):
        f = 1 if i < 17 else 2 if i < 37 else 3 if i < 57 else 4
        for name in ("up_proj", "down_proj"):
            t = tensors(piece(i, name))
            if (i, name) == (17, "up_proj"):
                shards[1][f"{piece(i, name)}.weight"] = t.pop(f"{piece(i, name)}.weight")
            shards[f].update(t)
    return shards


def loaded(*files):
    sm = shard_map()
    out = {}
    for f in files:
        out.update(sm[f])
    return out


def run_predicate(weights, infer):
    return {(i, n): class_predicate_0322(piece(i, n), Linear(OUT, IN), weights, infer)
            for i in range(64) for n in ("up_proj", "down_proj")}


class StraddledPiece(unittest.TestCase):
    def test_lead_shards_crash_without_the_guard(self):
        with self.assertRaises(KeyError) as cm:
            run_predicate(loaded(2, 3, 4), infer_quant_config_0322)
        self.assertIn("model.layers.17.mlp.up_proj.weight", str(cm.exception))

    def test_lead_shards_load_with_the_guard(self):
        skipped = []
        got = run_predicate(loaded(2, 3, 4), S.partial_quant_guard(infer_quant_config_0322, skipped))
        self.assertEqual(skipped, ["model.layers.17.mlp.up_proj"])
        self.assertIs(got[(17, "up_proj")], False)
        want = {"group_size": GROUP, "bits": BITS, "mode": "affine"}
        for i in range(24, 64):  # the lead's own layers quantize exactly as before
            self.assertEqual(got[(i, "up_proj")], want)
            self.assertEqual(got[(i, "down_proj")], want)
        self.assertIs(got[(3, "up_proj")], False)  # no scales here: skipped as before

    def test_complete_pieces_go_to_mlx_lm_unchanged(self):
        calls = []

        def infer(p, m, w):
            calls.append(p)
            return infer_quant_config_0322(p, m, w)
        skipped = []
        weights = loaded(1, 2, 3, 4)  # one Mac holding every shard
        guarded = run_predicate(weights, S.partial_quant_guard(infer, skipped))
        self.assertEqual(skipped, [])
        self.assertEqual(guarded, run_predicate(weights, infer_quant_config_0322))
        self.assertEqual(len(calls), 128)

    def test_packer_shards_have_nothing_to_skip(self):
        skipped = []
        run_predicate(loaded(1, 2), S.partial_quant_guard(infer_quant_config_0322, skipped))
        self.assertEqual(skipped, [])


class StageWiring(unittest.TestCase):
    def test_stage_uses_getattr_logs_and_restores(self):
        src = english_source(REPO / "agent/mlx_split.py")
        body = src[src.index("class Stage:"):src.index("def _assert_loaded")]
        self.assertIn('getattr(_mlx_utils, "infer_quant_config", None)', body)
        self.assertIn("partial_quant_guard(_orig_iqc, skipped_quant)", body)
        fin = body[body.index("finally:"):body.index("self._loaded_keys")]
        self.assertIn("_mlx_utils.infer_quant_config = _orig_iqc", fin)
        self.assertIn("if skipped_quant:", body)
        self.assertIn("_stage_log(", body[body.index("if skipped_quant:"):])


if __name__ == "__main__":
    unittest.main()
