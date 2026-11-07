import sys
import signal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"proxy"))
import worker_ownership as O

WORKER="/repo/agent/mlx_worker.py"
def cmd(port=8194,script=WORKER):return f"/usr/bin/python3 {script} --model /m --port {port} --split-role none"

class OwnershipTest(TestCase):
    def test_exact_command_and_port(self):
        self.assertTrue(O.matches(cmd(),WORKER,port=8194))
        self.assertFalse(O.matches(cmd(8294),WORKER,port=8194))
        self.assertFalse(O.matches(cmd(script="/other/agent/mlx_worker.py"),WORKER,port=8194))
        self.assertFalse(O.matches('zsh -c "'+cmd()+'"',WORKER,port=8194))
        self.assertFalse(O.matches(cmd(),WORKER,port=819))
    def test_alias_flags_and_packer(self):
        self.assertTrue(O.matches("python3 /repo/agent/mlx_worker.py --port=8194",WORKER,port=8194))
        c="python3 /repo/agent/mlx_worker.py --split-role packer --split-listen 1.2.3.4:5560"
        self.assertTrue(O.matches(c,WORKER,listen="1.2.3.4:5560"))
        self.assertFalse(O.matches(c,WORKER,listen="1.2.3.4:5561"))
        self.assertFalse(O.matches(c.replace("packer","none"),WORKER,listen="1.2.3.4:5560"))
    def test_only_tracked_pid_is_signaled(self):
        sends=[];calls=[]
        def inspect(pid):calls.append(pid);return cmd() if not sends else ""
        out=O.stop(WORKER,pid=20,port=8194,inspect=inspect,send=lambda *a:sends.append(a))
        self.assertTrue(out["stopped"]);self.assertEqual(sends,[(20,signal.SIGTERM)])
        self.assertEqual(set(calls),{20})
    def test_other_port_survives_and_stale_pid_fails_closed(self):
        for c in [cmd(8294),"python3 other.py --port 8194",""]:
            sends=[];O.stop(WORKER,pid=20,port=8194,inspect=lambda _:c,send=lambda *a:sends.append(a))
            self.assertEqual(sends,[])
    def test_pid_reuse_prevents_kill_escalation(self):
        calls=iter([cmd(),cmd(8294),cmd(8294)])
        sends=[];O.stop(WORKER,pid=20,port=8194,inspect=lambda _:next(calls),send=lambda *a:sends.append(a),timeout=0)
        self.assertEqual(sends,[(20,signal.SIGTERM)])
    def test_no_untracked_sweep(self):
        self.assertFalse(O.stop(WORKER,port=8194)["stopped"])
        s=(Path(__file__).resolve().parents[1]/"proxy/web_workers.py").read_text()
        self.assertNotIn("pkill",s)
        self.assertNotIn("old=$(cat",s)

    def test_manager_remote_command_keeps_node_and_endpoint(self):
        from web_workers import WorkerManager
        m=WorkerManager.__new__(WorkerManager)
        c=m._remote_stop_command("~/other-node-repo","~/.caravan/web-ui/remote-lead.pid",pid=42,port=8194)
        self.assertIn('"$HOME"/other-node-repo/proxy/worker_ownership.py',c)
        self.assertIn("--pid 42 --port 8194",c)
        self.assertNotIn("pkill",c)
