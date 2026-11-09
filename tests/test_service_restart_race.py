import sys,tempfile,subprocess,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import caravan_service as C
import service_config as SC

def cp(code=0):return subprocess.CompletedProcess([],code,"","Bootstrap failed: 5: Input/output error" if code==5 else "")

class LaunchdRestartRace(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.plan=SC.make_plan(kind="web",home=self.temp.name,repo=self.temp.name,python=sys.executable)
        self.t=0
    def clock(self):return self.t
    def wait(self,n):self.t+=n
    def retry(self,result,run):return C.retry_bootstrap(self.plan,result,run,timeout=1,clock=self.clock,wait=self.wait)
    def test_transient_retries_only_after_job_absent_and_port_free(self):
        run=mock.Mock(side_effect=[cp(113),cp()])
        with mock.patch.object(C,"ensure_port_free") as free:
            self.assertEqual(self.retry(cp(5),run).returncode,0);free.assert_called_once_with(self.plan)
        self.assertEqual([c.args[0][0] for c in run.call_args_list],["print","bootstrap"])
    def test_nontransient_error_never_retried(self):
        result=cp(1);run=mock.Mock();self.assertIs(self.retry(result,run),result);run.assert_not_called()
    def test_occupied_port_never_bootstraps_or_kills(self):
        run=mock.Mock(return_value=cp(113))
        with mock.patch.object(C,"ensure_port_free",side_effect=ValueError("busy")),self.assertRaises(ValueError):self.retry(cp(5),run)
        self.assertTrue(all(c.args[0][0]=="print" for c in run.call_args_list))
    def test_old_job_must_finish_unloading(self):
        run=mock.Mock(side_effect=[cp(),cp(113),cp()])
        with mock.patch.object(C,"ensure_port_free") as free:self.assertEqual(self.retry(cp(5),run).returncode,0);free.assert_called_once()
        self.assertEqual([c.args[0][0] for c in run.call_args_list],["print","print","bootstrap"])
    def test_persistent_native_error_has_bounded_retry(self):
        run=mock.Mock(side_effect=lambda a:cp(113) if a[0]=="print" else cp(5))
        with mock.patch.object(C,"ensure_port_free"),self.assertRaises(ValueError):self.retry(cp(5),run)
        self.assertEqual(self.t,1)
