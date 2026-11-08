import unittest
import mlx_split_fetch as MSF


def wm():
    m = {"model.embed_tokens.weight": "a.safetensors", "lm_head.weight": "c.safetensors",
         "model.norm.weight": "c.safetensors"}
    for i in range(4):
        m[f"model.layers.{i}.mlp.weight"] = "a.safetensors" if i < 2 else "c.safetensors"
    return m


class TiedEmbedSplit(unittest.TestCase):
    def test_config_flag_wins_over_shipped_lm_head(self):
        cfg = {"num_hidden_layers": 4, "tie_word_embeddings": True}
        self.assertTrue(MSF.tied_of(cfg, wm()))
        p = MSF.plan_files(cfg, {"weight_map": wm()}, 2)
        self.assertIn("a.safetensors", p["head"])  # lead needs embed shard

    def test_untied(self):
        cfg = {"num_hidden_layers": 4, "tie_word_embeddings": False}
        p = MSF.plan_files(cfg, {"weight_map": wm()}, 2)
        self.assertFalse(p["tied"])
        self.assertEqual(p["head"], {"c.safetensors"})

    def test_no_lm_head_is_tied(self):
        m = wm(); m.pop("lm_head.weight")
        self.assertTrue(MSF.tied_of({}, m))

    def test_text_config_flag(self):
        self.assertTrue(MSF.tied_of({"text_config": {"tie_word_embeddings": True}}, wm()))


if __name__ == "__main__":
    unittest.main()
