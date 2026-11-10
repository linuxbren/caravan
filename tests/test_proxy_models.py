import io,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"proxy"))
import slot_pin_proxy as P
class Models(unittest.TestCase):
 def run_models(self,replies):
  def connection(*args,**kwargs):
   result=replies.pop(0)
   if isinstance(result,Exception):raise result
   response=NS(status=200,read=lambda limit:json.dumps(result).encode())
   return NS(request=lambda *a:None,getresponse=lambda:response,close=lambda:None)
  router=NS(mlx=NS(name="mlx",address=lambda:("localhost",8194)),llama=NS(name="llama",address=lambda:("localhost",8080)))
  with mock.patch.object(P,"ROUTER",router),mock.patch.object(P,"MLX_SETTINGS",NS(enabled=True)),mock.patch.object(P.http.client,"HTTPConnection",side_effect=connection):return P.discover_models()
 def test_mlx_loaded_even_if_llama_is_absent(self):
  ok,d=self.run_models([{"data":[{"id":"/Users/test/models/mlx-community--Model","object":"model"}]},ConnectionRefusedError()])
  self.assertTrue(ok);self.assertEqual(d["data"][0]["id"],"mlx-community/Model")
 def test_aggregate_dedupe_and_ignore_malformed_rows(self):
  ok,d=self.run_models([{"data":[None,{"id":"same"}]},{"data":[{"id":"same"},{"id":"gguf"},{}]}]);self.assertTrue(ok);self.assertEqual([x["id"] for x in d["data"]],["same","gguf"])
 def test_no_backend_reachable_is_not_success(self):
  ok,d=self.run_models([ConnectionRefusedError(),ConnectionRefusedError()]);self.assertFalse(ok);self.assertEqual(d["data"],[])
 def test_empty_live_backend_is_valid_no_model(self):
  ok,d=self.run_models([{"data":[]},ConnectionRefusedError()]);self.assertTrue(ok);self.assertEqual(d["data"],[])
