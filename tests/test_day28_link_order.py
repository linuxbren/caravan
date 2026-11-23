"""Day 28 link-order fix: one route picker (proxy/peer_route.py) with the
fixed order Thunderbolt > wired Ethernet > Wi-Fi > other, used by every
path that reaches another Mac. Before, the GGUF split's SSH tunnel used the
peer's .local name, which resolved to Wi-Fi (15 ms) instead of Thunderbolt
(0.6 ms), and 2-Mac writing speed drifted from 19 to 11 tok/s."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "proxy", "agent"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import peer_route as PR  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

PORTS = """
Hardware Port: Ethernet
Device: en0
Ethernet Address: d0:11:e5:9a:67:fe

Hardware Port: Ethernet Adapter (en5)
Device: en5
Ethernet Address: d6:95:67:b0:d1:70

Hardware Port: Wi-Fi
Device: en1
Ethernet Address: d0:11:e5:98:c4:5a

Hardware Port: Thunderbolt 1
Device: en2
Ethernet Address: 36:a0:83:e8:0d:c0

Hardware Port: Thunderbolt 2
Device: en3
Ethernet Address: 36:a0:83:e8:0d:c4

Hardware Port: Thunderbolt Bridge
Device: bridge0
Ethernet Address: 36:a0:83:e8:0d:00

Hardware Port: Thunderbolt Ethernet Slot 0
Device: en9
Ethernet Address: 00:00:00:00:00:09
"""


def ifcfg(tb=None, wired=None, wifi=None, ts=None, en0_active=True):
    out = ["lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384",
           "\tinet 127.0.0.1 netmask 0xff000000"]
    out += ["en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500"]
    if wired:
        out.append(f"\tinet {wired} netmask 0xffffff00 broadcast 192.168.1.255")
    out.append("\tstatus: " + ("active" if (wired and en0_active) else "inactive"))
    out += ["en1: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500"]
    if wifi:
        out.append(f"\tinet {wifi} netmask 0xffffff00 broadcast 192.168.1.255")
    out.append("\tstatus: " + ("active" if wifi else "inactive"))
    out += ["en2: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500"]
    if tb:
        out.append(f"\tinet {tb} netmask 0xffff0000 broadcast 169.254.255.255")
    out.append("\tstatus: " + ("active" if tb else "inactive"))
    out += ["utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280"]
    if ts:
        out.append(f"\tinet {ts} --> {ts} netmask 0xffffffff")
    return "\n".join(out) + "\n"


LEAD = dict(tb="169.254.110.94", wired="192.168.1.80", wifi="192.168.1.79", ts="100.68.62.20")
PEER = dict(tb="169.254.99.64", wired="192.168.1.39", wifi="192.168.1.38", ts="100.90.134.95")


def inv(**kw):
    return PR.interfaces(PORTS, ifcfg(**kw))


class Down:
    """rtt() stand-in: addresses in `down` never answer."""
    def __init__(self, *down):
        self.down = set(down)
        self.calls = []

    def __call__(self, address, interface=None, local_ip=None):
        self.calls.append(address)
        return None if address in self.down else {"169": 0.6, "192": 15.0, "100": 40.0}[address.split(".")[0]]


OK = lambda target, address: (True, "prf-hays-exo02")  # noqa: E731


def pick(down=(), local=None, remote=None, identity=OK, **kw):
    return PR.pick("caravan-peer", label="2nd Mac", local=local if local is not None else inv(**LEAD),
                   remote=remote if remote is not None else inv(**PEER), rtt=Down(*down),
                   identity=identity, save=False, **kw)


class ClassifyTest(unittest.TestCase):
    def test_hardware_ports(self):
        k = PR.classify_ports(PORTS)
        self.assertEqual(k["en2"], "thunderbolt")
        self.assertEqual(k["en3"], "thunderbolt")
        self.assertEqual(k["bridge0"], "thunderbolt")
        self.assertEqual(k["en1"], "wifi")
        self.assertEqual(k["en0"], "wired")
        self.assertEqual(k["en5"], "wired")
        self.assertEqual(k["en9"], "wired")  # a Thunderbolt *Ethernet adapter* is wired

    def test_interfaces_skip_inactive_loopback_and_self_assigned(self):
        rows = PR.interfaces(PORTS, ifcfg(tb=None, wired="192.168.1.80", wifi="169.254.5.5", en0_active=False))
        self.assertEqual(rows, [])
        rows = inv(**LEAD)
        self.assertEqual([r["kind"] for r in rows], ["thunderbolt", "wired", "wifi", "other"])

    def test_bridge_of_thunderbolt_ports_is_thunderbolt(self):
        cfg = ("bridge0: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 169.254.7.7 netmask 0xffff0000\n"
               "\tmember: en2 flags=3<LEARNING,DISCOVER>\n\tmember: en3 flags=3<LEARNING,DISCOVER>\n\tstatus: active\n")
        self.assertEqual(PR.interfaces(PORTS, cfg)[0]["kind"], "thunderbolt")

    def test_mixed_path_takes_the_worse_end(self):
        local = inv(wifi="192.168.1.79")
        remote = inv(wired="192.168.1.39")
        c = PR.candidates(local, remote)
        self.assertEqual([(x["kind"], x["address"]) for x in c], [("wifi", "192.168.1.39")])

    def test_candidates_in_fixed_order(self):
        c = PR.candidates(inv(**LEAD), inv(**PEER))
        self.assertEqual([x["kind"] for x in c][:1], ["thunderbolt"])
        kinds = [x["kind"] for x in c]
        self.assertEqual(kinds, sorted(kinds, key=PR.ORDER.index))
        self.assertIn("other", kinds)


class OrderTest(unittest.TestCase):
    def test_all_up_picks_thunderbolt_and_skips_the_rest(self):
        r = pick()
        self.assertEqual((r["kind"], r["address"], r["interface"]), ("thunderbolt", PEER["tb"], "en2"))
        self.assertEqual(r["rtt_ms"], 0.6)
        self.assertIsNone(r["warning"])
        self.assertTrue(all(c["status"].startswith("not needed") for c in r["candidates"][1:]))

    def test_thunderbolt_down_goes_to_wired(self):
        r = pick(down=(PEER["tb"],))
        self.assertEqual(r["kind"], "wired")
        self.assertIn("wired Ethernet", r["warning"])

    def test_wired_down_goes_to_wifi_with_a_clear_warning(self):
        r = pick(local=inv(tb=None, wifi=LEAD["wifi"], ts=LEAD["ts"]),
                 remote=inv(tb=None, wifi=PEER["wifi"], ts=PEER["ts"]))
        self.assertEqual((r["kind"], r["address"]), ("wifi", PEER["wifi"]))
        self.assertEqual(r["warning"], "Using Wi-Fi to reach 2nd Mac; Thunderbolt not found, splits will be slower")

    def test_thunderbolt_and_wired_unanswered_goes_to_wifi(self):
        # Wired and Wi-Fi both on 192.168.1.0/24: the wired peer address is
        # tried before the Wi-Fi one.
        d = Down(PEER["tb"], PEER["wired"])
        r = PR.pick("p", local=inv(**LEAD), remote=inv(**PEER), rtt=d, identity=OK, save=False)
        self.assertEqual(r["kind"], "wifi")
        self.assertEqual(d.calls[:2], [PEER["tb"], PEER["wired"]])

    def test_only_tailscale_is_last(self):
        r = pick(down=(PEER["tb"], PEER["wired"], PEER["wifi"]))
        self.assertEqual(r["kind"], "other")
        self.assertIn("much slower", r["warning"])

    def test_thunderbolt_returns_and_is_preferred_again(self):
        self.assertEqual(pick(down=(PEER["tb"],))["kind"], "wired")
        self.assertEqual(pick()["kind"], "thunderbolt")

    def test_cable_plugged_in_later_is_picked_up(self):
        no_cable = pick(local=inv(wifi=LEAD["wifi"]), remote=inv(wifi=PEER["wifi"]))
        self.assertEqual(no_cable["kind"], "wifi")
        self.assertEqual(pick()["kind"], "thunderbolt")

    def test_wrong_mac_on_thunderbolt_is_skipped(self):
        ident = lambda t, a: (a != PEER["tb"], "imposter")  # noqa: E731
        r = pick(identity=ident)
        self.assertEqual(r["kind"], "wired")
        self.assertTrue(r["candidates"][0]["status"].startswith("wrong Mac"))

    def test_faster_later_link_never_jumps_ahead(self):
        class Rtt(Down):
            def __call__(self, a, i=None, l=None):
                return 9.0 if a == PEER["tb"] else 0.1
        r = PR.pick("p", local=inv(**LEAD), remote=inv(**PEER), rtt=Rtt(), identity=OK, save=False)
        self.assertEqual(r["kind"], "thunderbolt")

    def test_nothing_answers_means_unknown_and_old_behaviour(self):
        r = pick(down=(PEER["tb"], PEER["wired"], PEER["wifi"], PEER["ts"]))
        self.assertEqual(r["kind"], "unknown")
        self.assertIsNone(r["address"])
        self.assertEqual(PR.host_opts("caravan-peer", r["address"]), [])

    def test_unreadable_peer_inventory(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=255, stdout="", stderr="no route"))
        with mock.patch.object(PR, "recorded", return_value=None):
            r = PR.pick("p", local=inv(**LEAD), run=run, save=False)
        self.assertEqual(r["kind"], "unknown")
        self.assertIn("Could not check", r["warning"])

    def test_inventory_parse(self):
        out = PORTS + "\n" + PR.MARK + "\n" + ifcfg(**PEER)
        self.assertEqual(PR.parse_inventory(out)[0]["ip"], PEER["tb"])
        with self.assertRaises(ValueError):
            PR.parse_inventory("garbage")


class SshOptsTest(unittest.TestCase):
    def setUp(self):
        PR._ssh_g.clear()

    def g(self, **vals):
        text = "\n".join(f"{k} {v}" for k, v in vals.items())
        return mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=text, stderr=""))

    def test_no_local_name_on_data_path_when_thunderbolt_exists(self):
        run = self.g(hostname="prf-hays-exo02.local", hostkeyalias="caravan-x",
                     proxycommand="none")
        opts = PR.host_opts("caravan-x", "169.254.99.64", run=run)
        self.assertEqual(opts, ["-o", "HostName=169.254.99.64", "-o", "CheckHostIP=no"])
        self.assertFalse(any(".local" in o for o in opts))

    def test_host_key_anchor_kept_when_alias_has_none(self):
        run = self.g(hostname="prf-hays-exo02.local", proxycommand="none")
        opts = PR.host_opts("brenden@exo2", "169.254.99.64", run=run)
        self.assertIn("HostName=169.254.99.64", opts)
        self.assertIn("HostKeyAlias=prf-hays-exo02.local", opts)  # identity anchor, not resolved

    def test_source_address_of_picked_interface_is_bound(self):
        run = self.g(hostname="a.local", hostkeyalias="caravan-x", proxycommand="none")
        PR._mem["caravan-x"] = {"address": "192.168.1.39", "local_ip": "192.168.1.80"}
        try:
            opts = PR.host_opts("caravan-x", "192.168.1.39", run=run)
        finally:
            PR._mem.pop("caravan-x", None)
        self.assertIn("BindAddress=192.168.1.80", opts)  # wired, not Wi-Fi on the same subnet

    def test_jump_host_is_left_alone(self):
        run = self.g(hostname="exo2", proxycommand="ssh -q exo1-lan nc %h %p")
        self.assertEqual(PR.host_opts("exo2-via-exo1", "169.254.99.64", run=run), [])

    def test_identity_check_uses_nonce_and_strict_host_key(self):
        seen = {}

        def run(argv, **kw):
            if argv[:2] == ["ssh", "-G"]:
                return SimpleNamespace(returncode=0, stdout="hostkeyalias caravan-x\nhostname a.local\n", stderr="")
            seen["argv"] = argv
            nonce = re.search(r"printf %s (\w+)", argv[-1])[1]
            return SimpleNamespace(returncode=0, stdout=nonce + "\nprf-hays-exo02\n", stderr="")
        ok, host = PR.verify_identity("caravan-x", "169.254.99.64", run=run)
        self.assertTrue(ok)
        self.assertEqual(host, "prf-hays-exo02")
        self.assertIn("StrictHostKeyChecking=yes", seen["argv"])
        self.assertIn("HostName=169.254.99.64", seen["argv"])

    def test_identity_check_rejects_wrong_echo(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="nope\n", stderr=""))
        PR._ssh_g["t"] = {"hostkeyalias": "t"}
        self.assertFalse(PR.verify_identity("t", "169.254.1.1", run=run)[0])


class RouteForTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CARAVAN_PEER_ROUTES": self.tmp.name + "/r.json"})
        self.env.start()
        PR._mem.clear()
        PR._ssh_g.clear()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
        PR._mem.clear()

    def test_off_when_not_a_mac(self):
        with mock.patch.object(PR, "is_mac", return_value=False):
            self.assertIsNone(PR.route_for("x", fresh=True))

    def test_off_by_env(self):
        with mock.patch.object(PR, "is_mac", return_value=True), \
                mock.patch.dict(os.environ, {"CARAVAN_PEER_ROUTE": "off"}):
            self.assertIsNone(PR.route_for("x", fresh=True))

    def test_fresh_always_repicks_control_reuses_recent(self):
        with mock.patch.object(PR, "is_mac", return_value=True), \
                mock.patch.object(PR, "pick", side_effect=lambda t, **k: PR._save(t, {
                    "kind": "thunderbolt", "address": "169.254.9.9", "checked_at": __import__("time").time()})
                    or PR._mem[t]) as p:
            PR.route_for("x", fresh=True)
            PR.route_for("x", fresh=True)
            self.assertEqual(p.call_count, 2)
            PR.route_for("x")
            self.assertEqual(p.call_count, 2)  # control SSH reused the recent pick

    def test_failed_pick_is_not_retried_on_every_poll(self):
        with mock.patch.object(PR, "is_mac", return_value=True), \
                mock.patch.object(PR, "pick", side_effect=lambda t, **k: PR._save(t, {
                    "kind": "unknown", "address": None, "checked_at": __import__("time").time()})
                    or PR._mem[t]) as p:
            PR.route_for("x")
            PR.route_for("x")
            self.assertEqual(p.call_count, 1)

    def test_pick_is_recorded_for_status_and_topology(self):
        r = PR.pick("caravan-peer", label="2nd Mac", local=inv(**LEAD), remote=inv(**PEER),
                    rtt=Down(), identity=OK)
        data = json.loads(Path(self.tmp.name, "r.json").read_text())
        self.assertEqual(data["caravan-peer"]["kind"], "thunderbolt")
        s = PR.summary(PR.recorded("caravan-peer"))
        self.assertEqual((s["kind"], s["label"], s["interface"]), ("thunderbolt", "Thunderbolt", "en2"))
        self.assertEqual(PR.describe(r), "Thunderbolt, en2, 0.6 ms")
        import caravan
        lines = caravan.link_lines()
        self.assertEqual(lines, ["Link to 2nd Mac: Thunderbolt, en2, 0.6 ms"])

    def test_wifi_warning_is_logged_and_shown_in_status(self):
        with self.assertLogs("caravan.peer_route", "WARNING") as logs:
            PR.pick("caravan-peer", label="2nd Mac", local=inv(wifi=LEAD["wifi"]),
                    remote=inv(wifi=PEER["wifi"]), rtt=Down(), identity=OK)
        self.assertIn("Using Wi-Fi to reach 2nd Mac; Thunderbolt not found, splits will be slower",
                      "\n".join(logs.output))
        import caravan
        self.assertIn("  warning: Using Wi-Fi to reach 2nd Mac; Thunderbolt not found, splits will be slower",
                      caravan.link_lines())

    def test_run_ssh_falls_back_to_alias_when_picked_address_dies(self):
        route = {"kind": "thunderbolt", "address": "169.254.9.9"}
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=255 if len(calls) == 1 else 0, stdout="", stderr="")
        PR._mem["x"] = route
        with mock.patch.object(PR, "route_for", return_value=route), \
                mock.patch.object(PR, "host_opts", side_effect=lambda t, a, run=None, bind=None: ["-o", "HostName=" + a] if a else []):
            PR.run_ssh("x", "true", "-o", "BatchMode=yes", run=run)
        self.assertEqual(calls[0], ["ssh", "-o", "HostName=169.254.9.9", "-o", "BatchMode=yes", "x", "true"])
        self.assertEqual(calls[1], ["ssh", "-o", "BatchMode=yes", "x", "true"])
        self.assertNotIn("x", PR._mem)

    def test_run_ssh_without_picker_keeps_old_argv(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0))
        with mock.patch.object(PR, "is_mac", return_value=False):
            PR.run_ssh("host", "cmd", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", run=run)
        self.assertEqual(run.call_args[0][0], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "host", "cmd"])


TB = {"kind": "thunderbolt", "address": "169.254.99.64", "interface": "en2", "rtt_ms": 0.6, "warning": None}
WIFI = {"kind": "wifi", "address": "192.168.1.38", "interface": "en1", "rtt_ms": 15.0,
        "warning": "Using Wi-Fi to reach p; Thunderbolt not found, splits will be slower"}


def fake_opts(target, address, run=None, bind=None):
    return ["-o", "HostName=" + address, "-o", "CheckHostIP=no"] if address else []


class WiringTest(unittest.TestCase):
    """Every path that reaches another Mac goes through peer_route."""

    def patch(self, route):
        self.rf = mock.Mock(return_value=route)
        return mock.patch.multiple(PR, route_for=self.rf, host_opts=fake_opts)

    def mgr(self):
        import web_workers as W
        m = W.WorkerManager.__new__(W.WorkerManager)
        m.notes = []
        m._note = m.notes.append
        return m, W

    def test_gguf_split_tunnel_uses_picked_thunderbolt(self):
        m, W = self.mgr()
        with self.patch(TB), mock.patch.object(W.subprocess, "Popen") as popen:
            _, route = m._open_tunnel("caravan-x", 50062, node={"id": "p", "ssh": "caravan-x"})
        argv = popen.call_args[0][0]
        self.assertEqual(route, "thunderbolt")
        self.assertIn("HostName=169.254.99.64", argv)
        self.assertEqual(argv[-1], "caravan-x")  # tunnel ownership checks match on the alias
        self.assertFalse(any(".local" in a for a in argv))
        self.rf.assert_called_once()
        self.assertTrue(self.rf.call_args.kwargs["fresh"])

    def test_gguf_split_tunnel_on_wifi_warns(self):
        m, W = self.mgr()
        with self.patch(WIFI), mock.patch.object(W.subprocess, "Popen"):
            _, route = m._open_tunnel("caravan-x", 50062, node={"id": "p", "label": "p", "ssh": "caravan-x"})
        self.assertEqual(route, "wifi")
        self.assertIn(WIFI["warning"], m.notes)

    def test_load_falls_back_on_any_non_network_route(self):
        src = english_source(ROOT / "proxy" / "web_workers.py")
        self.assertIn('and route != "network":', src)
        self.assertIn("PR.forget(target)", src)

    def test_sharded_gguf_tunnel(self):
        import web_gguf_shares
        with self.patch(TB):
            args = web_gguf_shares.tunnel_args({"id": "p", "ssh": "caravan-x"}, 50062)
        self.assertIn("HostName=169.254.99.64", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertEqual(args[-1], "caravan-x")

    def test_mlx_pipeline_peer_and_listen(self):
        import web_pipeline
        mgr = SimpleNamespace(_node_is_local=lambda n: n.get("role") == "lead", _note=mock.Mock())
        nodes = [{"id": "p", "ssh": "caravan-x", "peer": "ssh+tb://caravan-x/en2:5560", "listen": "tb://en2:5560"},
                 {"id": "local", "role": "lead", "host": "local"}]
        with self.patch(TB):
            out = web_pipeline.resolve_nodes(mgr, nodes)
        self.assertEqual(out[0]["peer"], "169.254.99.64:5560")
        self.assertEqual(out[0]["listen"], "169.254.99.64:5560")
        self.assertEqual(out[0]["link"], "thunderbolt")
        with self.patch(WIFI):
            out = web_pipeline.resolve_nodes(mgr, nodes)
        self.assertEqual(out[0]["peer"], "192.168.1.38:5560")
        mgr._note.assert_called_with(WIFI["warning"])

    def test_mlx_pipeline_without_picker_keeps_strict_thunderbolt(self):
        import web_pipeline
        mgr = SimpleNamespace(_node_is_local=lambda n: False)
        with mock.patch.object(PR, "route_for", return_value=None), \
                mock.patch("service_endpoints.resolve", return_value="169.254.1.1:5560") as res:
            out = web_pipeline.resolve_nodes(mgr, [{"id": "p", "ssh": "t", "peer": "ssh+tb://t/en2:5560"}])
        self.assertEqual(out[0]["peer"], "169.254.1.1:5560")
        res.assert_called_once()

    def test_mlx_remote_worker_tunnel(self):
        import web_tunnels
        argv = web_tunnels.tunnel_argv("caravan-x", 8194, route=None)
        self.assertEqual(argv[0], "ssh")
        with mock.patch.object(PR, "host_opts", fake_opts):
            argv = web_tunnels.tunnel_argv("caravan-x", 8194, route=TB)
        self.assertIn("HostName=169.254.99.64", argv)
        self.assertTrue(web_tunnels.tunnel_matches(" ".join(argv), "caravan-x", 8194))
        with self.patch(TB):
            popen = mock.Mock()
            web_tunnels._spawn("caravan-x", 8194, popen=popen)
        self.assertIn("HostName=169.254.99.64", popen.call_args[0][0])
        self.assertTrue(self.rf.call_args.kwargs["fresh"])

    def test_control_ssh_paths(self):
        import web_nodes
        m, W = self.mgr()
        with mock.patch.object(PR, "run_ssh", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as rs:
            m._ssh_node({"id": "p", "ssh": "caravan-x"}, "true")
            m.packer_ssh = "caravan-x"
            m._ssh("true")
            web_nodes.make_ssh_fn(SimpleNamespace(packer_ssh=""))({"id": "p", "host": "caravan-x", "ssh": "caravan-x"}, "true")
        self.assertEqual([c.args[:2] for c in rs.call_args_list], [("caravan-x", "true")] * 3)

    def test_topology_stats_carry_the_link(self):
        import web_nodes
        with mock.patch.object(PR, "recorded", return_value=TB):
            st = web_nodes.gather_node_stats({"id": "p", "host": "caravan-x", "ssh": "caravan-x"},
                                             ssh_fn=lambda n, c, timeout=0: SimpleNamespace(returncode=0, stdout='{"cpu_pct": 1}', stderr=""))
        self.assertEqual(st["link"]["kind"], "thunderbolt")
        html = english_source(ROOT / "proxy" / "web" / "index.html")
        self.assertIn("function linkRow(L)", html)
        self.assertIn("if (n.link && n.role !== \"lead\") h += linkRow(n.link);", html)

    def test_update_all_macs(self):
        import caravan_update_peers as U
        with self.patch(TB):
            argv = U.ssh_argv({"id": "p", "ssh": "caravan-x"}, "true")
        self.assertIn("HostName=169.254.99.64", argv)
        self.assertEqual(argv[-2:], ["caravan-x", "true"])
        with self.patch(TB):
            argv = U.ssh_argv({"id": "p", "ssh": "caravan-x", "ssh_config": "/tmp/cfg"}, "true")
        self.assertNotIn("HostName=169.254.99.64", argv)  # explicit -F config: left alone
        import caravan_update as CU
        run = mock.Mock()
        with self.patch(TB):
            CU._ssh_stop("caravan-x", "true", run_ssh=run)
        self.assertIn("HostName=169.254.99.64", run.call_args[0][0])

    def test_service_endpoint_discovery_ssh(self):
        import service_endpoints as SE
        with self.patch(TB):
            argv = SE._control_ssh("caravan-x", "-o", "BatchMode=yes", command="ifconfig en2")
        self.assertEqual(argv[:3], ["ssh", "-o", "HostName=169.254.99.64"])
        self.assertEqual(argv[-2:], ["caravan-x", "ifconfig en2"])

    def test_cli_pairing_and_proxy_use_the_picker(self):
        self.assertIn("PR.run_ssh(target, cmd", (ROOT / "agent" / "gguf_split_cli.py").read_text())
        self.assertIn("PR.route_for(target, fresh=True)", (ROOT / "agent" / "gguf_split_cli.py").read_text())
        self.assertIn("record_route(result.get('alias')", english_source(ROOT / "proxy" / "pairing.py"))
        import pairing
        with mock.patch.object(PR, "route_for") as rf, mock.patch("threading.Thread") as th:
            pairing.record_route("caravan-x", "2nd Mac")
        th.assert_called_once()
        self.assertEqual(th.call_args.kwargs["kwargs"], {"fresh": True, "label": "2nd Mac"})
        self.assertIn("fallback_fn(args.peer,args.port)", (ROOT / "tools" / "tb_ssh_proxy.py").read_text())

    def test_no_new_raw_ssh_to_another_mac(self):
        """Guard: an ssh argv built outside the picker must be on this list."""
        allowed = {
            "peer_route.py",            # the picker itself
            "gguf_split.py",            # ssh_tunnel_args: builder, callers add route opts
            "web_tunnels.py",           # tunnel_argv: route opts added
            "caravan_update_peers.py",  # ssh_argv: route opts added
            "caravan_update.py",        # fallback argv if the picker import fails
            "service_endpoints.py",     # fallback argv if the picker import fails
            "thunderbolt_probe.py",     # Thunderbolt-only validator (diagnostic, bound socket)
            "thunderbolt_discovery.py", # Thunderbolt-only inventory (diagnostic)
            "pairing.py",               # checks the new pairing key itself
            "pairing_smoke.py",         # same, manual smoke test
            "supervisor.py",            # legacy stage-3 agent, not installed
        }
        pat = re.compile(r"""\[\s*["']ssh["']\s*,|^\s*["']ssh["']\s*,\s*$""", re.M)
        bad = []
        for d in ("proxy", "agent", "tools"):
            for f in (ROOT / d).glob("*.py"):
                if f.name not in allowed and pat.search(f.read_text()):
                    bad.append(f.name)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
