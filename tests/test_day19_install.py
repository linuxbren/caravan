"""Portable installer/LaunchAgent/agent-lifecycle tests; no real launchctl or MLX."""
import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for folder in ("agent","proxy","tools"):
    sys.path.insert(0,str(ROOT/folder))
import service_config as SC
import service_runner as SR
import caravan_service as CLI
import web_workers as W


class PlanTest(unittest.TestCase):
    def plan(self,root,**kw):
        return SC.make_plan(**dict({"home":root,"repo":ROOT,"python":sys.executable},**kw))

    def test_web_plist_preserves_workers_and_has_absolute_paths(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.plan(root,kind="web")
            plist = SC.render(p)
            self.assertEqual(plist["EnvironmentVariables"]["CARAVAN_WEB_KEEP_WORKERS"],"1")
            self.assertTrue(plist["AbandonProcessGroup"])
            self.assertTrue(plist["KeepAlive"])
            self.assertTrue(plist["RunAtLoad"])
            self.assertEqual(plist["ExitTimeOut"],30)
            self.assertEqual(plist["WorkingDirectory"],str(ROOT))
            self.assertEqual(plist["ProgramArguments"][2:4],["--host","127.0.0.1"])
            self.assertNotIn("~",plistlib.dumps(plist).decode())
            self.assertEqual(plistlib.loads(plistlib.dumps(plist)),plist)
            self.assertTrue(plist["StandardOutPath"].startswith(root+"/.caravan/logs/"))

    def test_symlinked_venv_interpreter_keeps_runtime_prefix(self):
        import venv
        with tempfile.TemporaryDirectory() as root:
            env=Path(root)/"venv with spaces"
            venv.EnvBuilder(with_pip=False,symlinks=True).create(env)
            python=env/"bin/python"
            p=self.plan(root,kind="worker",model="/own/model",python=python)
            self.assertEqual(p["python"],str(python))
            self.assertEqual(SC.worker_command(p)[0],str(python))
            executable=SC.render(p)["ProgramArguments"][0]
            prefix=subprocess.check_output([executable,"-c","import sys;print(sys.prefix)"],text=True).strip()
            self.assertEqual(prefix,str(env))
            path=Path(root)/"plan.json";path.write_text(json.dumps(p))
            self.assertEqual(SC.load(path),p)

    def test_default_venv_symlink_is_not_dereferenced(self):
        with tempfile.TemporaryDirectory() as root:
            python=Path(root)/".caravan/venvs/mlx/bin/python"
            python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
            p=SC.make_plan(kind="web",home=root,repo=ROOT)
            self.assertEqual(p["python"],str(python))
            self.assertEqual(SC.render(p)["EnvironmentVariables"]["PATH"].split(":")[0],str(python.parent))

    def test_port_probe_allows_time_wait_but_not_live_listener(self):
        import socket
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            listener.bind(("127.0.0.1",0));listener.listen(1);port=listener.getsockname()[1]
            plan=self.plan("/tmp",kind="web",web_port=port)
            with self.assertRaises(ValueError):CLI.ensure_port_free(plan)
            client=socket.create_connection(("127.0.0.1",port));accepted,_=listener.accept()
            accepted.close();self.assertEqual(client.recv(1),b"");client.close()
        CLI.ensure_port_free(plan)

    def test_single_worker_uses_agent_and_own_cache(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.plan(root,kind="worker",name="lead",model="/own/model")
            plist = SC.render(p)
            self.assertIn(str(ROOT/"agent/caravan_agent.py"),plist["ProgramArguments"])
            self.assertIn("--service-config",plist["ProgramArguments"])
            self.assertIn("--apply",plist["ProgramArguments"])
            self.assertFalse(plist["AbandonProcessGroup"])
            cmd = SC.worker_command(p)
            self.assertIn("/own/model",cmd)
            self.assertIn(root+"/.caravan/mlx/service-lead/sessions",cmd)
            self.assertEqual(cmd[cmd.index("--split-role")+1],"none")

    def test_n_stage_plans_no_two_mini_limit(self):
        with tempfile.TemporaryDirectory() as root:
            for n in (2,3,4,7):
                for index in range(n):
                    args = {"peer":"127.0.0.1:5599"} if index == n-1 else {"listen":f"127.0.0.1:{5590+index}"}
                    if 0 < index < n-1: args["upstream"] = f"127.0.0.1:{5589+index}"
                    plan = self.plan(root,kind="worker",name=f"node{index}",model="/own/model",
                                     counts=[2]*n,stage_index=index,**args)
                    cmd = SC.worker_command(plan)
                    self.assertEqual(cmd[cmd.index("--split-counts")+1],",".join(["2"]*n))
                    self.assertIn("--no-learn",cmd)
                    self.assertIn("--no-split-draft",cmd)
                    if 0 < index < n-1: self.assertIn("--split-upstream",cmd)

    def test_invalid_names_and_ports(self):
        for name in ("../web","a.b","", "a"*65):
            if name == "": continue  # empty means default
            with self.assertRaises(ValueError): self.plan("/tmp",kind="web",name=name)
        for value in (0,-1,65536):
            with self.assertRaises(ValueError): self.plan("/tmp",kind="web",web_port=value)

    def test_web_refuses_model(self):
        with self.assertRaises(ValueError): self.plan("/tmp",kind="web",model="/m")

    def test_worker_requires_model_and_stage_links(self):
        for kw in ({}, {"model":"/m","counts":[2,2,2],"stage_index":1},
                   {"model":"/m","counts":[2,2],"stage_index":1,"listen":"127.0.0.1:5591"},
                   {"model":"/m","peer":"127.0.0.1:5591"}):
            with self.assertRaises(ValueError): self.plan("/tmp",kind="worker",**kw)

    def test_load_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.plan(root,kind="web")
            path = Path(root)/"p.json"; path.write_text(json.dumps(p))
            self.assertEqual(SC.load(path),p)
            p["label"] = "com.someone.else"; path.write_text(json.dumps(p))
            with self.assertRaises(ValueError): SC.load(path)

    def test_paths_with_spaces_are_single_argv_entries(self):
        p = self.plan("/tmp/a b",kind="worker",repo="/tmp/source tree",python="/tmp/venv dir/python",model="/tmp/my model")
        self.assertEqual(SC.render(p)["ProgramArguments"][0],"/tmp/venv dir/python")
        self.assertIn("/tmp/my model",SC.worker_command(p))

    def test_worker_port_reservations_include_packers(self):
        with tempfile.TemporaryDirectory() as root:
            p = self.plan(root,kind="worker",name="p1",model="/m",counts=[2,2],stage_index=0,listen="127.0.0.1:5591")
            path = SC.paths(p)["config"]; path.parent.mkdir(parents=True); path.write_text(json.dumps(p))
            self.assertEqual(SC.managed_worker_port(root,5591),p)
            self.assertIsNone(SC.managed_lead(root,8194))


class ServiceCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.plan = SC.make_plan(kind="web",home=self.root,repo=ROOT,python=sys.executable)
        self.output = contextlib.redirect_stdout(io.StringIO()); self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None,None,None); self.tmp.cleanup()

    def fake(self,loaded=False):
        def run(args):
            is_job = args[0] == "print" and len(args)>1 and args[1].count("/")>1
            return subprocess.CompletedProcess(args,1 if is_job and not loaded else 0,"loaded","")
        return mock.Mock(side_effect=run)

    def install(self,start=False,run=None):
        with mock.patch.object(CLI,"check_platform"),mock.patch.object(CLI,"validate_files"),mock.patch.object(CLI,"ensure_port_free"):
            CLI.install(self.plan,start=start,run=run or self.fake())

    def test_cli_zero_port_is_refused_not_replaced_with_default(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(CLI.main(["install","--kind","web","--port","0","--dry-run"]),2)

    def test_dry_run_does_not_write_or_launch(self):
        run = self.fake()
        CLI.install(self.plan,dry_run=True,run=run)
        self.assertEqual(list(self.root.iterdir()),[])
        run.assert_not_called()

    def test_no_start_installs_only_owned_files(self):
        self.install()
        self.assertEqual(SC.load(SC.paths(self.plan)["config"]),self.plan)
        self.assertEqual(plistlib.loads(SC.paths(self.plan)["plist"].read_bytes()),SC.render(self.plan))

    def test_idempotent_loaded_job_is_not_restarted(self):
        self.install(); run = self.fake(loaded=True)
        self.install(start=True,run=run)
        self.assertTrue(all(c.args[0][0] == "print" for c in run.call_args_list))

    def test_unknown_loaded_label_not_adopted(self):
        run = self.fake(loaded=True)
        with mock.patch.object(CLI,"check_platform"),mock.patch.object(CLI,"validate_files"),self.assertRaises(ValueError):
            CLI.install(self.plan,run=run)
        self.assertFalse(SC.paths(self.plan)["config"].exists())

    def test_different_definition_is_not_overwritten(self):
        self.install()
        changed = dict(self.plan,host="0.0.0.0")
        with mock.patch.object(CLI,"check_platform"),self.assertRaises(ValueError): CLI.install(changed,start=False)
        self.assertEqual(SC.load(SC.paths(self.plan)["config"]),self.plan)

    def test_uninstall_keeps_models_logs_and_repo(self):
        self.install(); run = self.fake(loaded=True)
        model = self.root/"model.safetensors"; model.write_bytes(b"keep")
        with mock.patch.object(CLI,"check_platform"): CLI.control("uninstall",self.plan,run=run)
        self.assertTrue(model.exists())
        self.assertFalse(SC.paths(self.plan)["config"].exists())
        self.assertIn("bootout",[c.args[0][0] for c in run.call_args_list])

    def test_bootout_failure_keeps_definitions(self):
        self.install(); run = self.fake(loaded=True)
        def fail(args): return subprocess.CompletedProcess(args,5 if args[0] == "bootout" else 0,"","blocked")
        run.side_effect = fail
        with mock.patch.object(CLI,"check_platform"),self.assertRaises(ValueError): CLI.control("uninstall",self.plan,run=run)
        self.assertTrue(SC.paths(self.plan)["config"].exists())

    def test_restart_is_graceful_bootout_then_bootstrap(self):
        self.install(); run = self.fake(loaded=True)
        with mock.patch.object(CLI,"check_platform"): CLI.control("restart",self.plan,run=run)
        ops = [c.args[0][0] for c in run.call_args_list]
        self.assertEqual(ops[-2:],["bootout","bootstrap"])
        self.assertNotIn("kickstart",ops)

    def test_status_is_read_only(self):
        self.install(); run = self.fake(loaded=False)
        before = SC.paths(self.plan)["plist"].read_bytes()
        with mock.patch.object(CLI,"check_platform"): CLI.control("status",self.plan,run=run)
        self.assertEqual(SC.paths(self.plan)["plist"].read_bytes(),before)
        self.assertTrue(all(c.args[0][0] == "print" for c in run.call_args_list))

    def test_plist_tampering_blocks_uninstall(self):
        self.install(); SC.paths(self.plan)["plist"].write_bytes(plistlib.dumps({"Label":"other"}))
        with self.assertRaises(ValueError): CLI.control("uninstall",self.plan,dry_run=True)

    def test_busy_port_does_not_stop_anything_or_write_config(self):
        with mock.patch.object(CLI,"check_platform"),mock.patch.object(CLI,"validate_files"), \
             mock.patch.object(CLI,"ensure_port_free",side_effect=ValueError("busy")),self.assertRaises(ValueError):
            CLI.install(self.plan,run=self.fake())
        self.assertFalse(SC.paths(self.plan)["config"].exists())

    def test_second_service_cannot_reserve_same_port(self):
        self.install()
        other = SC.make_plan(kind="worker",name="other",home=self.root,repo=ROOT,python=sys.executable,model="/m",lead_port=8190)
        with mock.patch.object(CLI,"check_platform"),mock.patch.object(CLI,"validate_files"),self.assertRaises(ValueError):
            CLI.install(other,start=False)
        self.assertFalse(SC.paths(other)["config"].exists())

    def test_missing_gui_session_clear_error(self):
        run = mock.Mock(return_value=subprocess.CompletedProcess([],5,"","no gui"))
        with self.assertRaisesRegex(ValueError,"Log in"): CLI.gui_ready(run)


class RunnerTest(unittest.TestCase):
    def test_middle_and_lead_wait_for_correct_upstream(self):
        factory = mock.Mock(); client = factory.return_value
        p = SC.make_plan(kind="worker",model="/m",counts=[2,2,2],stage_index=1,listen="127.0.0.1:5592",upstream="127.0.0.1:5591")
        client.call.return_value = ({"range":[0,2],"n_layers":6},b"")
        SR.upstream_ready(p,factory)
        client.close.assert_called_once()
        client.call.return_value = ({"range":[0,3],"n_layers":6},b"")
        with self.assertRaises(ValueError): SR.upstream_ready(p,factory)

    def test_agent_preview_never_spawns(self):
        with tempfile.TemporaryDirectory() as root:
            p = SC.make_plan(kind="worker",name="lead",model="/m",home=root)
            path = Path(root)/"p.json"; path.write_text(json.dumps(p)); spawn = mock.Mock()
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(SR.run(path,popen=spawn),0)
            spawn.assert_not_called()

    def test_stop_forwards_only_to_owned_child_and_removes_own_markers(self):
        with tempfile.TemporaryDirectory() as root:
            p = SC.make_plan(kind="worker",name="lead",model="/m",home=root)
            path = Path(root)/"p.json"; path.write_text(json.dumps(p)); stop = threading.Event()
            class Child:
                pid=12345; returncode=None
                def __init__(self): self.terminated=0
                def poll(self): return self.returncode
                def terminate(self): self.terminated+=1; self.returncode=0
                def wait(self,timeout=None): return self.returncode
                def kill(self): raise AssertionError("no escalation needed")
            child=Child()
            def spawn(cmd): stop.set(); return child
            with mock.patch.object(CLI,"validate_files"),mock.patch.object(CLI,"ensure_port_free"),contextlib.redirect_stdout(io.StringIO()):
                SR.run(path,apply=True,stop=stop,popen=spawn,retry_seconds=0)
            self.assertEqual(child.terminated,1)
            self.assertFalse(SC.paths(p)["runtime"].exists())
            self.assertFalse((Path(root)/".caravan/web-ui/lead.pid").exists())

    def test_missing_peer_waits_without_spawning(self):
        with tempfile.TemporaryDirectory() as root:
            p = SC.make_plan(kind="worker",model="/m",home=root)
            path = Path(root)/"p.json"; path.write_text(json.dumps(p)); stop = threading.Event(); spawn=mock.Mock()
            def unavailable(plan): stop.set(); raise RuntimeError("peer missing")
            with mock.patch.object(CLI,"validate_files"),mock.patch.object(SR,"upstream_ready",side_effect=unavailable),contextlib.redirect_stdout(io.StringIO()):
                SR.run(path,apply=True,stop=stop,popen=spawn,retry_seconds=0)
            spawn.assert_not_called()

    def test_web_adopts_a_delayed_managed_worker_without_spawning(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ,{"HOME":root}):
            p = SC.make_plan(kind="worker",name="lead",model="/models/org--Tiny",repo=ROOT,python=sys.executable,home=root)
            path = SC.paths(p)["config"]; path.parent.mkdir(parents=True); path.write_text(json.dumps(p))
            SR.write_runtime(p,12345)
            mgr = W.WorkerManager(state_dir=Path(root)/"web-state",repo=ROOT)
            with mock.patch("worker_ownership.command_of",return_value=f"python {ROOT}/agent/mlx_worker.py --port 8194"), \
                 mock.patch.object(mgr,"lead_healthy",return_value=True):
                mgr.refresh_managed_service()
            self.assertEqual(mgr.snapshot()["status"],"ready")
            self.assertEqual(mgr.snapshot()["model_id"],"org/Tiny")
            self.assertEqual(mgr.snapshot()["managed_service"]["name"],"lead")
            path.unlink(); mgr._managed_poll_at=0; mgr.refresh_managed_service()
            self.assertEqual(mgr.snapshot()["status"],"idle")

    def test_corrupt_auto_start_plan_blocks_worker_mutation(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ,{"HOME":root}):
            path=Path(root)/".caravan/services/lead.json"; path.parent.mkdir(parents=True); path.write_text("broken")
            mgr=W.WorkerManager(state_dir=Path(root)/"web-state",repo=ROOT)
            with self.assertRaises(W.ManagedServiceError): mgr.switch("tiny")
            mgr.refresh_managed_service()
            self.assertEqual(mgr.snapshot()["status"],"error")

    def test_single_mini_install_never_contacts_default_lab_packer(self):
        with tempfile.TemporaryDirectory() as root:
            mgr = W.WorkerManager(state_dir=Path(root)/"state",repo=ROOT)
            with mock.patch("web_nodes.nodes_from_config",return_value=[{"id":"local","role":"lead","host":"local"}]), \
                 mock.patch.object(mgr,"_ssh") as ssh:
                mgr._kill_packer()
            ssh.assert_not_called()

    def test_isolated_topology_never_contacts_legacy_endpoint_on_same_host(self):
        with tempfile.TemporaryDirectory() as root:
            mgr = W.WorkerManager(state_dir=Path(root)/"state",repo=ROOT,
                                  packer_ssh="same-mini",packer_peer="10.0.0.2:5560")
            nodes = [{"id":"scratch","role":"packer","ssh":"same-mini",
                      "peer":"10.0.0.2:5591","listen":"10.0.0.2:5591"}]
            with mock.patch("web_nodes.nodes_from_config",return_value=nodes), \
                 mock.patch.object(mgr,"_ssh") as ssh:
                mgr._kill_packer()
            ssh.assert_not_called()

    def test_configured_legacy_endpoint_keeps_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            mgr = W.WorkerManager(state_dir=Path(root)/"state",repo=ROOT,
                                  packer_ssh="same-mini",packer_peer="10.0.0.2:5560")
            nodes = [{"id":"legacy","role":"packer","ssh":"same-mini",
                      "peer":"10.0.0.2:5560"}]
            with mock.patch("web_nodes.nodes_from_config",return_value=nodes), \
                 mock.patch.object(mgr,"_assert_packer_unmanaged"), \
                 mock.patch.object(mgr,"_ssh",return_value=mock.Mock(returncode=0)) as ssh:
                mgr._kill_packer()
            self.assertIn("--listen 10.0.0.2:5560",ssh.call_args.args[0])

    def test_runtime_cleanup_does_not_delete_replacement_pid(self):
        with tempfile.TemporaryDirectory() as root:
            p = SC.make_plan(kind="worker",model="/m",home=root)
            SR.write_runtime(p,10); SR.write_runtime(p,11); SR.clear_runtime(p,10)
            self.assertEqual(json.loads(SC.paths(p)["runtime"].read_text())["pid"],11)

    def test_web_cannot_stop_or_switch_a_launchd_owned_lead(self):
        mgr = W.WorkerManager.__new__(W.WorkerManager); mgr.lead_port=8194
        mgr._kill_lead=mock.Mock(); mgr._set=mock.Mock()
        with mock.patch.object(SC,"managed_lead",return_value={"name":"lead"}):
            with self.assertRaises(W.ManagedServiceError): mgr.stop()
            with self.assertRaises(W.ManagedServiceError): mgr.switch("model")
        mgr._kill_lead.assert_not_called(); mgr._set.assert_not_called()


class InstallerScriptTest(unittest.TestCase):
    def script(self,home,*args):
        return subprocess.run(["bash",str(ROOT/"scripts/install.sh"),*args],env=dict(os.environ,HOME=str(home)),
                              text=True,capture_output=True,timeout=10)

    def test_dry_run_new_lead_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.script(root,"--dry-run","--python",sys.executable)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(list(Path(root).iterdir()),[])
            self.assertIn("PREVIEW ONLY",result.stdout)
            self.assertIn("git clone",result.stdout)
            self.assertIn("requirements-mac.txt",result.stdout)
            self.assertIn("caravan_service.py",result.stdout)

    def test_worker_without_model_is_only_prepared(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.script(root,"--dry-run","--role","worker","--python",sys.executable)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("no worker was started",result.stdout)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_existing_nonrepo_folder_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)/"existing"; folder.mkdir(); marker=folder/"mine"; marker.write_text("keep")
            result = self.script(root,"--dry-run","--repo",str(folder),"--python",sys.executable)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(marker.read_text(),"keep")

    def test_real_install_rejects_linux_before_writes(self):
        if sys.platform == "darwin": self.skipTest("Linux-only platform refusal test")
        with tempfile.TemporaryDirectory() as root:
            result = self.script(root)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("needs macOS",result.stderr)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_dirty_checkout_is_never_reset_or_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/"repo"
            subprocess.run(["git","init","-q",str(folder)],check=True)
            subprocess.run(["git","-C",str(folder),"remote","add","origin","https://github.com/linuxbren/caravan.git"],check=True)
            marker=folder/"mine"; marker.write_text("keep")
            result=self.script(root,"--dry-run","--python",sys.executable,"--repo",str(folder))
            self.assertNotEqual(result.returncode,0)
            self.assertIn("local changes",result.stderr)
            self.assertEqual(marker.read_text(),"keep")

    def test_matching_checkout_reused_without_pull_or_clone(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/"repo"
            subprocess.run(["git","init","-q",str(folder)],check=True)
            subprocess.run(["git","-C",str(folder),"symbolic-ref","HEAD","refs/heads/caravan-v3-mlx-split"],check=True)
            subprocess.run(["git","-C",str(folder),"remote","add","origin","https://github.com/linuxbren/caravan.git"],check=True)
            result=self.script(root,"--dry-run","--python",sys.executable,"--repo",str(folder))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("leaving its code unchanged",result.stdout)
            self.assertNotIn("Would run: git clone",result.stdout)
            self.assertNotIn("Would run: git -C",result.stdout)

    def test_worker_options_without_model_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            result=self.script(root,"--dry-run","--role","worker","--counts","4,4,4")
            self.assertNotEqual(result.returncode,0)
            self.assertIn("need an installed --model",result.stderr)

    def test_invalid_role_and_relative_path_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertNotEqual(self.script(root,"--dry-run","--role","bogus").returncode,0)
            self.assertNotEqual(self.script(root,"--dry-run","--repo","relative").returncode,0)

    def test_help_does_not_write(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.script(root,"--help")
            self.assertEqual(result.returncode,0)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_worker_dry_run_keeps_n_stage_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            result=self.script(root,"--dry-run","--role","worker","--python",sys.executable,
                               "--model","/own/model","--counts","4,4,4","--stage-index","1",
                               "--listen","127.0.0.1:5592","--upstream","127.0.0.1:5591")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("--counts",result.stdout)
            self.assertIn("--stage-index 1",result.stdout)
            self.assertIn("--upstream 127.0.0.1:5591",result.stdout)


if __name__ == "__main__": unittest.main()
