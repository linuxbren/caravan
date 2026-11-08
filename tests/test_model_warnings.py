import json, tempfile, unittest
from pathlib import Path
import mlx_arch as A
import model_inventory as MI


class ModelWarnings(unittest.TestCase):
    def test_unknown_text_type(self):
        self.assertTrue(A.model_warnings({"model_type": "foo_text"}))
        self.assertEqual(A.model_warnings({"model_type": "qwen3_5_text"}), [])
        self.assertEqual(A.model_warnings({"model_type": "qwen3_5_moe",
                                           "text_config": {"model_type": "qwen3_5_moe_text"}}), [])

    def test_tie_conflict_dark_champion(self):
        w = A.model_warnings({"model_type": "mixtral", "tie_word_embeddings": True},
                             {"lm_head.weight": "a", "model.embed_tokens.weight": "b"})
        self.assertEqual(len(w), 1)
        self.assertIn("extra output table", w[0])

    def test_untied_without_lm_head(self):
        w = A.model_warnings({"tie_word_embeddings": False}, {"model.embed_tokens.weight": "b"})
        self.assertIn("gibberish", w[0])

    def test_consistent_models_clean(self):
        self.assertEqual(A.model_warnings({"tie_word_embeddings": True}, {"model.embed_tokens.weight": "b"}), [])
        self.assertEqual(A.model_warnings({"tie_word_embeddings": False},
                                          {"lm_head.weight": "a", "model.embed_tokens.weight": "b"}), [])

    def test_mtp_head(self):
        self.assertTrue(A.model_warnings({"model_type": "qwen3_5_mtp"}))

    def test_inventory_carries_warnings(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "config.json").write_text(json.dumps({"model_type": "mixtral", "num_hidden_layers": 2,
                                                       "tie_word_embeddings": True}))
            (d / "tokenizer.json").write_text("{}")
            (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {
                "model.embed_tokens.weight": "a.safetensors", "lm_head.weight": "a.safetensors",
                "model.layers.0.w": "a.safetensors", "model.layers.1.w": "a.safetensors"}}))
            r = MI.inspect_tree(d)
            self.assertTrue(any("extra output table" in w for w in r["warnings"]))


if __name__ == "__main__":
    unittest.main()
