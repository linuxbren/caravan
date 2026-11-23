"""One place that decides how this Mac reaches another Mac.

The rule (Day 28 link-order fix): try links in a fixed order and use the
first one that works:

    1. Thunderbolt  (Thunderbolt N hardware ports, or a bridge made only of them)
    2. wired Ethernet
    3. Wi-Fi
    4. anything else that still reaches the Mac (Tailscale/VPN), last

"Works" means: this Mac and the other Mac both have an active interface on
the same IPv4 subnet, a TCP connect to the other Mac's SSH port over that
interface succeeds (RTT measured, bound to the interface on macOS), and an
SSH login to that address presents the other Mac's existing host key and
echoes a fresh nonce. A faster-looking later link never jumps ahead of a
working earlier one.

Why this exists: before, the GGUF split's SSH tunnel used the other Mac's
.local name, which resolved to the home network (Wi-Fi: 15 ms, jittery)
instead of Thunderbolt (0.6 ms), and 2-Mac writing speed drifted from
19 to 11 tok/s. Data paths never resolve a .local name blindly now: they
connect to the picked address and keep the configured SSH alias as the
host-key anchor.

The choice is re-made on every model load / reconnect (``pick(...,
fresh=True)``), so a Thunderbolt cable plugged in later is used next time.
Control SSH (stats, stop, update) reuses a recent pick and falls back to
the plain alias if the picked address stops answering.

Each pick is recorded per Mac in ~/.caravan/web-ui/peer-routes.json and
shown in Topology and ``caravan status``.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

log = logging.getLogger("caravan.peer_route")

ORDER = ("thunderbolt", "wired", "wifi", "other")
LABELS = {"thunderbolt": T("server.peer_route.thunderbolt"), "wired": T("server.link_upgrade.wired_ethernet"), "wifi": "Wi-Fi",
          "other": T("server.peer_route.other_network_tailscale_vpn")}
SSH_PORT = 22
MARK = "CARAVAN_PEER_ROUTE_V1"
CONTROL_TTL_S = 300.0     # control SSH reuses a pick this young
NEGATIVE_TTL_S = 30.0     # ...and a failed pick this long (offline Mac: no probe storm)
# Day 30: after a power loss the Macs bring Wi-Fi up before the Thunderbolt
# link-local addresses, so a load that checks too early falls back to Wi-Fi.
TB_WAIT_S = float(os.environ.get("CARAVAN_TB_WAIT_S", "60"))
TB_WAIT_INTERVAL_S = 5.0
TB_REMEMBER_S = 30 * 24 * 3600.0   # wait only if Thunderbolt worked to this Mac recently
IP_BOUND_IF = 25          # Darwin <netinet/in.h>

_TB_PORT = re.compile(r"^Thunderbolt( \d+| Bridge)$", re.I)
_WIFI_PORT = re.compile(r"^(Wi-?Fi|AirPort)\b", re.I)
_WIRED_PORT = re.compile(r"(Ethernet|\bLAN\b|10/100|Gigabit)", re.I)
_CGNAT = ipaddress.ip_network("100.64.0.0/10")

_lock = threading.Lock()
_mem: dict = {}           # target -> route (this process)
_ssh_g: dict = {}         # target -> parsed `ssh -G`


# ---------------------------------------------------------------- parsing

def classify_ports(ports_text: str) -> dict:
    """{device: kind} from `networksetup -listallhardwareports`."""
    out, name = {}, None
    for line in (ports_text or "").splitlines():
        line = line.strip()
        if line.startswith("Hardware Port:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and name is not None:
            dev = line.split(":", 1)[1].strip()
            if _TB_PORT.match(name):
                kind = "thunderbolt"      # "Thunderbolt Ethernet Slot 0" is a wired adapter
            elif _WIFI_PORT.match(name):
                kind = "wifi"
            elif _WIRED_PORT.search(name):
                kind = "wired"
            else:
                kind = "other"
            out[dev] = kind
            name = None
    return out


def parse_ifconfig(text: str) -> dict:
    """{dev: {"active": bool|None, "inet": [(ip, prefix)], "members": [...]}} from `ifconfig -a`."""
    out, cur = {}, None
    for raw in (text or "").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+): flags=", raw)
        if m:
            cur = out.setdefault(m[1], {"active": None, "inet": [], "members": []})
            continue
        if cur is None:
            continue
        s = raw.strip()
        m = re.match(r"inet (\d+\.\d+\.\d+\.\d+)(?: --> \S+)? netmask (0x[0-9a-fA-F]+|\d+\.\d+\.\d+\.\d+)", s)
        if m:
            mask = m[2]
            try:
                prefix = bin(int(mask, 16)).count("1") if mask.startswith("0x") else \
                    ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen
            except ValueError:
                prefix = 32
            cur["inet"].append((m[1], prefix))
        elif s.startswith("status:"):
            cur["active"] = s.split(":", 1)[1].strip() == "active"
        elif s.startswith("member:"):
            cur["members"].append(s.split()[1])
    return out


def interfaces(ports_text: str, ifconfig_text: str) -> list:
    """Usable IPv4 interfaces with their kind, best kind first."""
    kinds = classify_ports(ports_text)
    cfg = parse_ifconfig(ifconfig_text)
    rows = []
    for dev, info in cfg.items():
        if dev.startswith(("lo", "gif", "stf", "awdl", "llw", "anpi", "ap")) or info.get("active") is False:
            continue
        kind = kinds.get(dev)
        if dev.startswith("bridge"):
            members = [kinds.get(m) for m in info["members"]]
            if members and all(k == "thunderbolt" for k in members):
                kind = "thunderbolt"
            elif "wifi" in members:
                kind = "wifi"
            elif members and all(k in ("thunderbolt", "wired") for k in members):
                kind = "wired"
            else:
                kind = "other"
        if kind is None:
            kind = "other"  # utun (Tailscale), VPN, unknown
        for ip, prefix in info["inet"]:
            a = ipaddress.IPv4Address(ip)
            if a.is_loopback or a.is_unspecified or a.is_multicast:
                continue
            if not (a.is_private or a in _CGNAT):
                continue  # never a public address
            if a.is_link_local and kind != "thunderbolt":
                continue  # self-assigned on Wi-Fi/Ethernet: no real network
            rows.append({"dev": dev, "kind": kind, "ip": ip, "prefix": prefix})
    rows.sort(key=lambda r: ORDER.index(r["kind"]))
    return rows


def candidates(local: list, remote: list) -> list:
    """Paths from this Mac to the other one, in the fixed order.

    A path's kind is the worse of the two ends (Wi-Fi here + Ethernet there = wifi).
    """
    out, seen = [], set()
    for r in remote:
        rip = ipaddress.IPv4Address(r["ip"])
        for l in local:
            if r["ip"] == l["ip"]:
                continue
            same = rip in ipaddress.IPv4Network(f"{l['ip']}/{l['prefix']}", strict=False)
            overlay = l["kind"] == r["kind"] == "other" and rip in _CGNAT and \
                ipaddress.IPv4Address(l["ip"]) in _CGNAT
            if not (same or overlay):
                continue
            kind = ORDER[max(ORDER.index(l["kind"]), ORDER.index(r["kind"]))]
            key = r["ip"]
            if key in seen:
                continue
            seen.add(key)
            out.append({"kind": kind, "address": r["ip"], "interface": l["dev"],
                        "local_ip": l["ip"], "remote_interface": r["dev"]})
    out.sort(key=lambda c: ORDER.index(c["kind"]))
    return out


# ---------------------------------------------------------------- probes

def is_mac() -> bool:
    return sys.platform == "darwin"


def local_inventory(run=None) -> list:
    run = run or subprocess.run
    ports = run(["networksetup", "-listallhardwareports"], capture_output=True, text=True, timeout=5).stdout
    cfg = run(["ifconfig", "-a"], capture_output=True, text=True, timeout=5).stdout
    return interfaces(ports, cfg)


def inventory_command() -> str:
    return ("networksetup -listallhardwareports; printf " + shlex.quote("\n" + MARK + "\n")
            + "; ifconfig -a")


def parse_inventory(stdout: str) -> list:
    if (stdout or "").count(MARK) != 1:
        raise ValueError(T("server.peer_route.peer_did_not_report_its_network"))
    ports, cfg = stdout.split(MARK)
    return interfaces(ports, cfg)


def tcp_rtt_ms(address: str, interface: Optional[str] = None, local_ip: Optional[str] = None,
               port: int = SSH_PORT, timeout: float = 1.0, tries: int = 3) -> Optional[float]:
    """Best TCP connect time over this interface, ms; None if it never connects."""
    best = None
    for _ in range(max(1, tries)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            if interface and is_mac():
                s.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, socket.if_nametoindex(interface))
            if local_ip:
                s.bind((local_ip, 0))
            t = time.perf_counter()
            s.connect((address, int(port)))
            ms = (time.perf_counter() - t) * 1000.0
            best = ms if best is None else min(best, ms)
        except OSError:
            pass
        finally:
            s.close()
    return None if best is None else round(best, 2)


def ssh_config(target: str, run=None) -> dict:
    """Effective `ssh -G target` values we care about (cached per target)."""
    run = run or subprocess.run
    if target in _ssh_g:
        return _ssh_g[target]
    vals = {}
    try:
        r = run(["ssh", "-G", target], capture_output=True, text=True, timeout=5)
        for line in (r.stdout or "").splitlines():
            k, _, v = line.partition(" ")
            if k in ("hostname", "hostkeyalias", "proxycommand", "proxyjump"):
                vals[k] = v.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    _ssh_g[target] = vals
    return vals


def host_opts(target: str, address: Optional[str], run=None, bind: Optional[str] = None) -> list:
    """ssh -o options that send this target's connection to `address`,
    keeping its configured host key as the identity anchor. [] = can't reroute.

    The source address of the picked interface is bound too (macOS scoped
    routing then sends it out of that interface, e.g. Ethernet rather than
    Wi-Fi when both are on the home subnet)."""
    if not address or not target:
        return []
    if bind is None:
        prev = _mem.get(target) or {}
        if prev.get("address") == address:
            bind = prev.get("local_ip")
    cfg = ssh_config(target, run=run)
    if cfg.get("proxycommand", "none") not in ("", "none") or cfg.get("proxyjump", "none") not in ("", "none"):
        return []  # a jump host decides the path; leave it alone
    alias = cfg.get("hostkeyalias") or cfg.get("hostname") or target.rsplit("@", 1)[-1]
    opts = ["-o", "HostName=" + address, "-o", "CheckHostIP=no"]
    if not cfg.get("hostkeyalias"):
        opts += ["-o", "HostKeyAlias=" + alias]
    if bind:
        opts += ["-o", "BindAddress=" + bind]
    return opts


def verify_identity(target: str, address: str, run=None) -> tuple:
    """(ok, detail): SSH to address with the target's own host key and a fresh nonce."""
    run = run or subprocess.run
    nonce = secrets.token_hex(8)
    opts = host_opts(target, address, run=run)
    if not opts:
        return False, T("server.peer_route.ssh_alias_uses_a_jump_host")
    argv = ["ssh", *opts, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "UpdateHostKeys=no", "-o", "ConnectTimeout=3", target,
            "printf %s " + shlex.quote(nonce) + "; echo; hostname"]
    try:
        r = run(argv, capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)[:120]
    lines = (r.stdout or "").strip().splitlines()
    if r.returncode == 0 and lines and lines[0] == nonce:
        return True, (lines[1] if len(lines) > 1 else "")
    return False, ((r.stderr or "").strip().splitlines() or ["identity check failed"])[-1][:160]


# ---------------------------------------------------------------- store

def store_path() -> Path:
    env = os.environ.get("CARAVAN_PEER_ROUTES")
    return Path(env).expanduser() if env else Path.home() / ".caravan" / "web-ui" / "peer-routes.json"


def load_all() -> dict:
    try:
        data = json.loads(store_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(target: str, route: dict) -> None:
    with _lock:
        # Day 30: remember when Thunderbolt last worked to this Mac, across
        # picks that fell back to a slower link (see pick_waiting).
        if route.get("kind") == "thunderbolt":
            route["thunderbolt_seen_at"] = route.get("checked_at") or round(time.time(), 1)
        elif not route.get("thunderbolt_seen_at"):
            prev = _mem.get(target) or load_all().get(target) or {}
            seen = prev.get("thunderbolt_seen_at") or (
                prev.get("checked_at") if prev.get("kind") == "thunderbolt" else None)
            if seen:
                route["thunderbolt_seen_at"] = seen
        _mem[target] = route
        p = store_path()
        try:
            data = load_all()
            data[target] = route
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".new")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
            os.replace(tmp, p)
        except OSError:
            pass


def forget(target: str) -> None:
    with _lock:
        _mem.pop(target, None)


def recorded(target: str) -> Optional[dict]:
    return _mem.get(target) or load_all().get(target)


def warning_for(kind: str, label: str) -> Optional[str]:
    if kind == "thunderbolt":
        return None
    if kind == "wired":
        return T("server.peer_route.using_wired_ethernet_to_reach_label", label=label)
    if kind == "wifi":
        return T("server.peer_route.using_wi_fi_to_reach_label", label=label)
    if kind == "other":
        return T("server.peer_route.using_other_to_reach_label_no", other=LABELS['other'], label=label)
    return T("server.peer_route.could_not_check_the_links_to", label=label)


def summary(route: Optional[dict]) -> Optional[dict]:
    """Small dict for Topology / status: kind, label, interface, rtt, age."""
    if not route:
        return None
    kind = route.get("kind") or "unknown"
    return {"kind": kind, "label": LABELS.get(kind, T("server.peer_route.configured_name_not_checked")),
            "address": route.get("address"), "interface": route.get("interface"),
            "rtt_ms": route.get("rtt_ms"), "checked_at": route.get("checked_at"),
            "warning": route.get("warning")}


def describe(route: Optional[dict]) -> str:
    s = summary(route)
    if not s:
        return T("server.peer_route.not_checked_yet")
    bits = [s["label"]]
    if s.get("interface"):
        bits.append(s["interface"])
    if s.get("rtt_ms") is not None:
        bits.append(f"{s['rtt_ms']:g} ms")
    return T.join(bits)


# ---------------------------------------------------------------- pick

def pick(target: str, *, label: Optional[str] = None, run: Optional[Callable] = None,
         rtt: Callable = tcp_rtt_ms, identity: Callable = None, local: Optional[list] = None,
         remote: Optional[list] = None, save: bool = True, now: Callable = time.time) -> dict:
    """Probe every path to `target` in order and return the first that works.

    Always a fresh check (call on each load / reconnect). The route dict has
    kind, address, interface, rtt_ms, candidates (each with status), warning.
    kind "unknown" + address None means no checked path: callers use the
    configured SSH name unchanged (old behaviour) and show the warning.
    """
    label = label or target
    run = run or subprocess.run
    identity = identity or (lambda t, a: verify_identity(t, a, run=run))
    route = {"peer": target, "label": label, "kind": "unknown", "address": None, "interface": None,
             "rtt_ms": None, "checked_at": round(now(), 1), "candidates": [], "order": list(ORDER)}
    try:
        if local is None:
            local = local_inventory(run=run)
        if remote is None:
            prev = recorded(target)
            argv = ["ssh", *(host_opts(target, (prev or {}).get("address"), run=run) if prev else []),
                    "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", target, inventory_command()]
            r = run(argv, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            if r.returncode and prev and prev.get("address"):
                r = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", target, inventory_command()],
                        capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            remote = parse_inventory(r.stdout if r.returncode == 0 else "")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        route["reason"] = T("server.peer_route.could_not_read_interfaces_e", e=str(e)[:120])
        route["warning"] = warning_for("unknown", label)
        log.warning("%s (%s)", route["warning"], route["reason"])
        if save:
            _save(target, route)
        return route
    cands = candidates(local, remote)
    chosen = None
    for c in cands:
        row = dict(c)
        if chosen is not None:
            row["status"] = T("server.peer_route.not_needed_an_earlier_link_works")
        else:
            ms = rtt(c["address"], c["interface"], c["local_ip"])
            row["rtt_ms"] = ms
            if ms is None:
                row["status"] = T("server.peer_route.no_answer")
            else:
                ok, detail = identity(target, c["address"])
                row["status"] = "ok" if ok else T("server.peer_route.wrong_mac_or_no_login_detail", detail=str(detail)[:100])
                if ok:
                    row["peer_hostname"] = detail
                    chosen = row
        route["candidates"].append(row)
    if chosen:
        route.update(kind=chosen["kind"], address=chosen["address"], interface=chosen["interface"],
                     local_ip=chosen["local_ip"],
                     remote_interface=chosen["remote_interface"], rtt_ms=chosen["rtt_ms"],
                     reason=T("server.peer_route.first_working_link_in_order_labels", labels=LABELS[chosen['kind']]))
    else:
        route["reason"] = T("server.peer_route.no_candidate_path_answered") if cands else T("server.peer_route.no_shared_subnet_with_the_other")
    route["warning"] = warning_for(route["kind"], label)
    if route["warning"]:
        log.warning(route["warning"])
    if save:
        _save(target, route)
    return route


def thunderbolt_seen_at(target: str) -> Optional[float]:
    rec = recorded(target) or {}
    seen = rec.get("thunderbolt_seen_at") or (rec.get("checked_at") if rec.get("kind") == "thunderbolt" else None)
    try:
        return float(seen) if seen else None
    except (TypeError, ValueError):
        return None


def pick_waiting(target: str, *, label: Optional[str] = None, wait_s: Optional[float] = None,
                 interval: float = TB_WAIT_INTERVAL_S, sleep: Callable = time.sleep,
                 now: Callable = time.time, on_wait: Optional[Callable] = None,
                 save: bool = True, **kw) -> dict:
    """pick(), but give a late Thunderbolt link up to `wait_s` to appear.

    Only when Thunderbolt worked to this Mac before (TB_REMEMBER_S). Each
    try is a full pick(): both Macs' interfaces are read again, so the new
    link-local addresses a reboot gives Thunderbolt are found. on_wait(waited,
    wait_s) runs before each pause; it may raise to stop (load cancelled).
    """
    label = label or target
    wait_s = TB_WAIT_S if wait_s is None else float(wait_s)
    seen = thunderbolt_seen_at(target)
    start = now()
    should_wait = bool(wait_s > 0 and seen and start - seen < TB_REMEMBER_S)
    route = pick(target, label=label, save=False, now=now, **kw)
    tries = 1
    while route.get("kind") != "thunderbolt" and should_wait and now() - start < wait_s:
        if on_wait is not None:
            on_wait(now() - start, wait_s)
        sleep(interval)
        route = pick(target, label=label, save=False, now=now, **kw)
        tries += 1
    if should_wait:
        route["thunderbolt_wait"] = {"waited_s": round(now() - start, 1), "tries": tries,
                                     "limit_s": wait_s, "found": route.get("kind") == "thunderbolt"}
        if route.get("kind") != "thunderbolt":
            slower = LABELS.get(route.get("kind"), "its configured name")
            route["warning"] = (T("server.peer_route.thunderbolt_to_label_did_not_answer", label=label, wait_s=wait_s, slower=slower))
            log.warning(route["warning"])
    if seen and route.get("kind") != "thunderbolt":
        route["thunderbolt_seen_at"] = seen
    if save:
        _save(target, route)
    return route


def route_for(target: str, *, fresh: bool = False, label: Optional[str] = None,
              enabled: Optional[bool] = None, wait_thunderbolt: bool = False,
              on_wait: Optional[Callable] = None, **kw) -> Optional[dict]:
    """Fresh pick for data paths; a recent pick (or a new one) for control SSH.

    Returns None where picking is off (not a Mac, CARAVAN_PEER_ROUTE=off),
    so callers keep their exact old argv.
    """
    if enabled is None:
        enabled = is_mac() and os.environ.get("CARAVAN_PEER_ROUTE", "on").lower() not in ("0", "off", "no")
    if not enabled or not target:
        return None
    if not fresh:
        prev = _mem.get(target) or load_all().get(target)
        ttl = CONTROL_TTL_S if (prev or {}).get("address") else NEGATIVE_TTL_S
        if prev and time.time() - float(prev.get("checked_at") or 0) < ttl:
            return prev
    if wait_thunderbolt:
        return pick_waiting(target, label=label, on_wait=on_wait, **kw)
    return pick(target, label=label, **kw)


def ssh_argv(target: str, *opts: str, command: Optional[str] = None, fresh: bool = False,
             label: Optional[str] = None, route: Optional[dict] = None, **kw) -> list:
    """["ssh", <route opts>, *opts, target, (command)] with the picked address."""
    if route is None:
        route = route_for(target, fresh=fresh, label=label, **kw)
    argv = ["ssh", *host_opts(target, (route or {}).get("address")), *opts, target]
    if command is not None:
        argv.append(command)
    return argv


def run_ssh(target: str, command: str, *opts: str, timeout: float = 60, run: Optional[Callable] = None,
            label: Optional[str] = None, **kw):
    """Control SSH over the picked link; if that address stops answering
    (ssh exit 255) the pick is dropped and the plain alias is tried once."""
    run = run or subprocess.run
    route = route_for(target, label=label)
    argv = ssh_argv(target, *opts, command=command, route=route)
    r = run(argv, capture_output=True, text=True, timeout=timeout)
    if getattr(r, "returncode", 0) == 255 and route and route.get("address"):
        forget(target)
        r = run(["ssh", *opts, target, command], capture_output=True, text=True, timeout=timeout)
    return r


def main(argv=None) -> int:
    """python3 proxy/peer_route.py SSH_TARGET [...]  -- read-only: show the pick."""
    import argparse
    ap = argparse.ArgumentParser(description="Show which link Caravan would use to reach each Mac (read-only).")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--no-save", action="store_true", help="do not record the pick")
    ap.add_argument("--probe-all", action="store_true",
                    help="also time the links that were not needed (display only; the pick is unchanged)")
    ap.add_argument("--skip", action="append", default=[], metavar="KIND",
                    help="pretend this kind does not answer (what-if; e.g. --skip thunderbolt)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        print("local interfaces:", json.dumps(local_inventory(), indent=1))
    except (OSError, subprocess.SubprocessError) as e:
        print("local interfaces: unavailable:", e)
    for t in a.targets:
        kinds = {}

        def rtt(address, interface=None, local_ip=None):
            if kinds.get(address) in a.skip:
                return None
            return tcp_rtt_ms(address, interface, local_ip)
        try:
            local = local_inventory()
        except (OSError, subprocess.SubprocessError):
            local = None
        orig = candidates

        def tagged(l, r):
            out = orig(l, r)
            kinds.update({c["address"]: c["kind"] for c in out})
            return out
        globals()["candidates"] = tagged
        try:
            route = pick(t, save=not a.no_save and not a.skip, rtt=rtt, local=local)
        finally:
            globals()["candidates"] = orig
        if a.probe_all:
            for c in route["candidates"]:
                if "rtt_ms" not in c:
                    c["rtt_ms_info_only"] = tcp_rtt_ms(c["address"], c["interface"], c["local_ip"])
        print(json.dumps(route, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
