import unittest
import mlx_split_fetch as MSF


def main_wm(n=4, extra=()):
    wm = {"model.embed_tokens.weight": "s1", "lm_head.weight": "s3", "model.norm.weight": "s3"}
    for i in range(n):
        wm[f"model.layers.{i}.w"] = "s1" if i < n // 2 else "s2"
    for k, f in extra:
        wm[k] = f
    return wm


class MtpSplitPlan(unittest.TestCase):
    def test_mtp_keys_go_to_head_only(self):
        wm = main_wm(extra=[("mtp.fc.weight", "s4"), ("mtp.layers.0.w", "s4"),
                            ("language_model.mtp.norm.weight", "s4")])
        p = MSF.plan_files({"num_hidden_layers": 4}, {"weight_map": wm}, 2)
        self.assertIn("s4", p["head"])
        self.assertNotIn("s4", p["front"])

    def test_nextn_layers_beyond_count_skipped(self):
        # DeepSeek/GLM style: model.layers.<num_hidden_layers>.* is the MTP layer
        wm = main_wm(extra=[("model.layers.4.eh_proj.weight", "s5")])
        p = MSF.plan_files({"num_hidden_layers": 4, "num_nextn_predict_layers": 1}, {"weight_map": wm}, 2)
        self.assertNotIn("s5", p["head"] | p["front"])
        self.assertEqual(p["n_layers"], 4)

    def test_standalone_mtp_head_refused(self):
        # Real key shape of mlx-community/Qwen3.6-35B-A3B-MTP-4bit (Nov 7 HF index)
        wm = {"fc.weight": "m", "norm.weight": "m", "pre_fc_norm_embedding.weight": "m",
              "pre_fc_norm_hidden.weight": "m", "layers.0.mlp.gate.weight": "m"}
        cfg = {"model_type": "qwen3_5_mtp", "text_config": {"num_hidden_layers": 40}}
        self.assertIn("helper head", MSF.head_only_reason(cfg, wm))
        with self.assertRaises(ValueError):
            MSF.plan_files(cfg, {"weight_map": wm}, 20)

    def test_headless_partial_checkpoint_refused_by_shape(self):
        wm = {"fc.weight": "m", "layers.0.w": "m"}
        self.assertTrue(MSF.head_only_reason({"num_hidden_layers": 40}, wm))

    def test_normal_model_not_flagged(self):
        self.assertEqual(MSF.head_only_reason({"num_hidden_layers": 4}, main_wm()), "")


if __name__ == "__main__":
    unittest.main()
