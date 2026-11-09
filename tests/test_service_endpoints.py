import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agent"))
import service_endpoints as E
import service_config as SC
import service_runner as SR

PORTS="Hardware Port: Wi-Fi\nDevice: en1\nHardware Port: Thunderbolt 1\nDevice: en2\nHardware Port: Thunderbolt 2\nDevice: en3\n"
def config(ip="169.254.35.180"):
    return f"en2: flags=UP\n inet {ip} netmask 0xffff0000\n status: active\n"
def cp(out,code=0):return subprocess.CompletedProcess([],code,out,"")

class DynamicThunderbolt(unittest.TestCase):
    def test_static_endpoints_do_not_do_io(self):
        run=mock.Mock(side_effect=AssertionError("no IO"));self.assertEqual(E.resolve("169.254.1.2:5560",run=run),"169.254.1.2:5560");run.assert_not_called()

    def test_explicit_interfaces_and_trusted_control(self):
        self.assertEqual(E.parse("tb://en2:5560"),(None,"en2",5560))
        self.assertEqual(E.parse("ssh+tb://brenden@100.64.1.2/en3:5592"),("brenden@100.64.1.2","en3",5592))

    def test_malformed_endpoints_rejected_without_shell_input(self):
        for value in ["tb://en2:0","tb://en2:65536","tb://en2;touch:5560","ssh+tb://-host/en2:5560","ssh+tb://u:password@host/en2:5560","ssh+tb://host/en2:5560?x=1"]:
            with self.subTest(value=value),self.assertRaises(ValueError):E.parse(value)

    def test_local_reboot_changed_address_resolves(self):
        run=mock.Mock(side_effect=[cp(PORTS),cp(config())]);self.assertEqual(E.resolve("tb://en2:5560",run=run),"169.254.35.180:5560")
        self.assertEqual(run.call_args.args[0],["ifconfig","en2"])

    def test_no_wifi_fallback_or_ambiguous_address(self):
        for iface,cfg in [("en1",config()),("en2",config().replace("active","inactive")),("en2",config()+"inet 169.254.1.3\n")]:
            with self.subTest(iface=iface,config=cfg),self.assertRaises(ValueError):E.address(PORTS,cfg,iface)

    def test_public_and_wildcard_loopback_rejected(self):
        for ip in ["8.8.8.8","0.0.0.0","127.0.0.1","224.0.0.1"]:
            with self.subTest(ip=ip),self.assertRaises(ValueError):E.address(PORTS,config(ip),"en2")

    def test_remote_discovery_checks_host_key_and_keeps_tb_data(self):
        run=mock.Mock(return_value=cp(PORTS+E.MARKER+config()));self.assertEqual(E.resolve("ssh+tb://brenden@100.64.1.2/en2:5560",run=run),"169.254.35.180:5560")
        argv=run.call_args.args[0];self.assertIn("StrictHostKeyChecking=yes",argv);self.assertIn("BatchMode=yes",argv);self.assertEqual(argv[-2],"brenden@100.64.1.2")

    def test_remote_failure_or_bad_data_never_falls_back(self):
        for result in [cp("",255),cp("wrong"),cp(PORTS+E.MARKER+config("8.8.8.8"))]:
            with self.subTest(result=result),self.assertRaises(ValueError):E.resolve("ssh+tb://host/en2:5560",run=mock.Mock(return_value=result))

    def test_timeout_is_retryable_value_error(self):
        with self.assertRaises(ValueError):E.resolve("tb://en2:5560",run=mock.Mock(side_effect=subprocess.TimeoutExpired("ifconfig",5)))

    def test_plan_roundtrip_keeps_interface_not_current_ip(self):
        with tempfile.TemporaryDirectory() as d:
            p=SC.make_plan(kind="worker",name="p",home=d,repo=d,python=sys.executable,model="/model",counts=[10,10,12],stage_index=1,listen="tb://en3:5592",upstream="ssh+tb://peer/en2:5591")
            path=Path(d)/"p.json";path.write_text(json.dumps(p));self.assertEqual(SC.load(path),p)
            with mock.patch.object(E,"resolve",side_effect=lambda v: "169.254.2.3:5592" if v.startswith("tb:") else "169.254.1.2:5591"):
                runtime=E.runtime_plan(p)
            self.assertEqual(runtime["listen"],"169.254.2.3:5592");self.assertEqual(runtime["upstream"],"169.254.1.2:5591");self.assertTrue(p["listen"].startswith("tb://"))

    def test_address_change_detected_without_killing_on_control_outage(self):
        saved={"listen":"tb://en2:5560"};old={"listen":"169.254.1.2:5560"}
        with mock.patch.object(E,"runtime_plan",return_value={"listen":"169.254.35.180:5560"}):self.assertTrue(SR.endpoints_changed(saved,old))
        with mock.patch.object(E,"runtime_plan",side_effect=ValueError("not ready")):self.assertFalse(SR.endpoints_changed(saved,old))
        self.assertFalse(SR.endpoints_changed(old,old))
