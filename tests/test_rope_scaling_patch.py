import types
import unittest
import mlx_arch as A


class RoPE:  # stands in for mlx.nn.RoPE
    def __init__(self, dims, traditional=False, base=10000, scale=1.0):
        self.dims, self.traditional, self.base, self.scale = dims, traditional, base, scale


class Llama3RoPE:  # an already-scaling class
    pass


FAKE_NN = types.SimpleNamespace(RoPE=RoPE)


def init_rope(dims, base, trad, sc, maxpos):
    return ("scaled", dims, base, trad, sc.get("rope_type"), maxpos)


def model(rope_factory, n=3, with_none=False):
    layers = [types.SimpleNamespace(self_attn=types.SimpleNamespace(rope=rope_factory())) for _ in range(n)]
    if with_none:
        layers[0] = None
    return types.SimpleNamespace(model=types.SimpleNamespace(layers=layers))


LLAMA3 = {"rope_scaling": {"rope_type": "llama3", "factor": 32.0}, "max_position_embeddings": 131072}


class RopePatch(unittest.TestCase):
    def test_mixtral_llama3_patched(self):
        m = model(lambda: RoPE(128, base=500000.0))
        self.assertEqual(A.fix_rope_scaling(m, LLAMA3, nn=FAKE_NN, initialize_rope=init_rope), 3)
        self.assertEqual(m.model.layers[1].self_attn.rope, ("scaled", 128, 500000.0, False, "llama3", 131072))

    def test_no_scaling_noop(self):
        m = model(lambda: RoPE(128))
        self.assertEqual(A.fix_rope_scaling(m, {}, nn=FAKE_NN, initialize_rope=init_rope), 0)

    def test_already_scaled_class_untouched(self):
        m = model(Llama3RoPE)
        self.assertEqual(A.fix_rope_scaling(m, LLAMA3, nn=FAKE_NN, initialize_rope=init_rope), 0)

    def test_dropped_layers_and_text_config(self):
        m = model(lambda: RoPE(64), with_none=True)
        cfg = {"text_config": LLAMA3}
        self.assertEqual(A.fix_rope_scaling(m, cfg, nn=FAKE_NN, initialize_rope=init_rope), 2)

    def test_linear_already_applied(self):
        m = model(lambda: RoPE(64, scale=0.5))
        cfg = {"rope_scaling": {"type": "linear", "factor": 2.0}}
        self.assertEqual(A.fix_rope_scaling(m, cfg, nn=FAKE_NN, initialize_rope=init_rope), 0)


if __name__ == "__main__":
    unittest.main()
