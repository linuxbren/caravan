import sys,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import tb_ssh_proxy as T
class Proxy(unittest.TestCase):
 def test_every_connection_resolves_fresh_address_and_execs_nc(self):
  resolve=mock.Mock(side_effect=["169.254.1.2:22","169.254.3.4:22"]);exe=mock.Mock()
  for _ in range(2):T.main(["user@peer","en2","22"],resolve_fn=resolve,exec_fn=exe)
  self.assertEqual(resolve.call_count,2);self.assertEqual(exe.call_args.args,("/usr/bin/nc",["nc","169.254.3.4","22"]))
 def test_discovery_failure_never_connects_to_another_route(self):
  exe=mock.Mock()
  with self.assertRaises(ValueError):T.main(["user@peer","en2","22"],resolve_fn=mock.Mock(side_effect=ValueError("bad endpoint")),exec_fn=exe)
  exe.assert_not_called()

 def test_discovery_never_consumes_parent_ssh_stdin(self):
  def endpoint(value,run):run(["ssh","peer","command"]);return "169.254.1.2:22"
  with mock.patch.object(T,"resolve",side_effect=endpoint),mock.patch.object(T.subprocess,"run") as run:
   self.assertEqual(T.discover("endpoint"),"169.254.1.2:22")
  self.assertEqual(run.call_args.kwargs["stdin"],T.subprocess.DEVNULL)
