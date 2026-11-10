import sys,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agent"))
import memory_guard as M

class WrappedDecoderLayerTests(unittest.TestCase):
 def test_flat_and_wrapped_counts(self):
  self.assertEqual(M.model_layer_count({"num_hidden_layers":32}),32)
  self.assertEqual(M.model_layer_count({"text_config":{"num_hidden_layers":64}}),64)
  self.assertEqual(M.model_layer_count({"num_hidden_layers":1,"text_config":{"num_hidden_layers":64}}),64)
  self.assertEqual(M.model_layer_count({}),0)
 def test_qwen35_single_budget_uses_all_decoder_layers(self):
  cfg={"model_type":"qwen3_5","text_config":{"num_hidden_layers":64,"num_key_value_heads":4,"head_dim":256}}
  self.assertEqual(M.bytes_per_token_for_layers(cfg,M.model_layer_count(cfg)),262144)
  hr={"headroom_gb":6.8,"available_gb":8.55,"safety_gb":1.75,"local_headroom_gb":6.8,"packer_available_gb":None,"packer_headroom_gb":None}
  with mock.patch.object(M,"headroom_gb",return_value=hr):
   p=M.plan([{"role":"user","content":"test"}],cfg=cfg,n_layers=M.model_layer_count(cfg),max_tokens=512,count_tokens=lambda _:11322)
  self.assertTrue(p["ok"]);self.assertEqual(p["bytes_per_token"],262144);self.assertLess(p["budget_tokens"],26000);self.assertGreater(p["need_gb"],3)
