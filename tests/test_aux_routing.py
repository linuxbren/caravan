import copy,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"proxy"))
import aux_routing as A
class Aux(unittest.TestCase):
 def body(self):return {"model":"mlx-community/main","messages":[{"role":"system","content":"Never answer the message. Name it."},{"role":"user","content":"Fix login"}],"max_tokens":64,"reasoning_effort":"none","response_format":{"type":"json_schema","json_schema":{"name":"session_title"}}}
 def test_exact_title_only(self):
  b=self.body();self.assertTrue(A.is_title(b))
  for patch in [{"tools":[{"type":"function"}]},{"stream":True},{"reasoning_effort":"medium"},{"max_tokens":2048},{"response_format":{}},{"response_format":"bad"},{"messages":[None,{}]},{"messages":[{"role":"user","content":"Generate a title"}]}]:
   self.assertFalse(A.is_title(dict(b,**patch)))
 def test_default_disabled_never_contacts_sidecar(self):
  conn=mock.Mock();self.assertIsNone(A.try_title(self.body(),env={},connection=conn));conn.assert_not_called()
 def test_valid_title_routes_without_mutating_main_body(self):
  b=self.body();before=copy.deepcopy(b)
  result={"choices":[{"finish_reason":"stop","message":{"content":'{"title":"Fix login button"}'}}]}
  conn=mock.Mock();conn.getresponse.side_effect=[NS(status=200,read=lambda:b"{}"),NS(status=200,read=lambda n:json.dumps(result).encode())]
  out=A.try_title(b,env={"CARAVAN_AUX_MODEL":"small"},connection=lambda *a,**k:conn)
  self.assertEqual(out["caravan_aux"]["route"],"title-sidecar");self.assertEqual(b,before)
 def test_missing_sidecar_falls_back(self):
  self.assertIsNone(A.try_title(self.body(),env={"CARAVAN_AUX_MODEL":"small"},connection=mock.Mock(side_effect=ConnectionRefusedError())))
 def test_invalid_json_or_answer_shaped_output_falls_back(self):
  for text in ["not JSON",json.dumps({"title":"word "*20})]:
   conn=mock.Mock();conn.getresponse.side_effect=[NS(status=200,read=lambda:b"{}"),NS(status=200,read=lambda n:json.dumps({"choices":[{"finish_reason":"stop","message":{"content":text}}]}).encode())]
   self.assertIsNone(A.try_title(self.body(),env={"CARAVAN_AUX_MODEL":"small"},connection=lambda *a,**k:conn))
 def test_unrelated_few_shot_copy_is_rejected(self):
  self.assertFalse(A.title_matches_user("Fix login button on mobile","Checking Caravan after reboot and improving Hermes speed"))
  self.assertTrue(A.title_matches_user("Improve Caravan startup speed","Checking Caravan after reboot"))
 def test_invalid_timeout_fails_closed(self):
  for timeout in ["nan","inf","-1","0","100","bad"]:
   conn=mock.Mock()
   self.assertIsNone(A.try_title(self.body(),env={"CARAVAN_AUX_MODEL":"small","CARAVAN_AUX_TIMEOUT_S":timeout},connection=conn))
   conn.assert_not_called()
