"""Explicit Thunderbolt interfaces with reboot-safe IPv4 resolution.

No network/login settings are changed. An optional already-trusted SSH control
path asks the peer for its interface; weights still travel over Thunderbolt.
"""
import ipaddress
import re
import shlex
import subprocess
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

LOCAL = re.compile(r"tb://([A-Za-z][A-Za-z0-9_]{0,15}):([0-9]+)\Z")
REMOTE = re.compile(r"ssh\+tb://((?:[A-Za-z_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z][A-Za-z0-9_]{0,15}):([0-9]+)\Z")
MARKER = "CARAVAN_THUNDERBOLT_INTERFACE_V1"


class RetryableReadinessError(ValueError):
    """Pre-worker unreadiness that boot restore may retry with bounded backoff.

    Permanent safety failures (public IPs, missing files, tight RAM, bad
    config) stay plain ValueError and must not set retryable.
    """
    retryable = True

    def __init__(self, message, *, kind="peer"):
        super().__init__(message)
        self.kind = kind or "peer"

    def payload(self):
        return {"error": str(self), "retryable": True, "retry_kind": self.kind}

    def waiting_message(self, attempt, pause):
        if self.kind == "thunderbolt":
            lead = T("agent.service_endpoints.waiting_for_thunderbolt_link")
        elif self.kind == "memory":
            lead = T("agent.service_endpoints.waiting_for_memory_info_from_your")
        else:
            lead = T("agent.service_endpoints.waiting_for_your_other_macs_to")
        return f"{lead} (attempt {attempt}); trying again in {pause:g}s: {self}"

    def timeout_message(self, budget):
        if self.kind == "thunderbolt":
            return (T("agent.service_endpoints.thunderbolt_link_was_not_ready_after", budget=budget, self_=self))
        return T("agent.service_endpoints.peer_readiness_timed_out_after_budget", budget=budget, self_=self)

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict) or not payload.get("retryable"):
            return None
        return cls(payload.get("error") or "not ready", kind=payload.get("retry_kind") or "peer")

    @classmethod
    def from_state(cls, state):
        if not isinstance(state, dict) or not state.get("retryable"):
            return None
        return cls(state.get("error") or "not ready", kind=state.get("retry_kind") or "peer")


def error_payload(exc):
    if isinstance(exc, RetryableReadinessError):
        return exc.payload()
    return {"error": str(exc)}


def parse(value):
    value = str(value)
    m = LOCAL.fullmatch(value)
    if m:
        target, interface, port = None, m[1], int(m[2])
    else:
        m = REMOTE.fullmatch(value)
        if not m:
            if "://" in value:
                raise ValueError(T("agent.service_endpoints.use_tb_interface_port_or_ssh"))
            return None
        target, interface, port = m[1], m[2], int(m[3])
    if not 1 <= port <= 65535:
        raise ValueError(T("agent.service_endpoints.invalid_thunderbolt_endpoint_port"))
    return target, interface, port


def address(ports, config, interface):
    devices = []
    name = None
    for line in ports.splitlines():
        if line.startswith("Hardware Port: "):
            name = line.split(": ",1)[1].strip()
        elif line.startswith("Device: ") and name and re.fullmatch(r"Thunderbolt \d+",name,re.I):
            devices.append(line.split(": ",1)[1].strip()); name = None
    if interface not in devices or "status: active" not in config:
        raise RetryableReadinessError(T("agent.service_endpoints.thunderbolt_interface_interface_is_not_active", interface=interface), kind="thunderbolt")
    found = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)",config)
    if len(found) != 1:
        raise RetryableReadinessError(T("agent.service_endpoints.thunderbolt_interface_interface_needs_one_unambi", interface=interface), kind="thunderbolt")
    ip = ipaddress.IPv4Address(found[0])
    if not ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ValueError(T("agent.service_endpoints.thunderbolt_endpoint_must_be_private_link"))
    return str(ip)


def _control_ssh(target, *opts, command):
    """Control SSH over the picked link (peer_route) when it is importable."""
    try:
        import peer_route as PR
        return PR.ssh_argv(target, *opts, command=command)
    except ImportError:
        return ["ssh", *opts, target, command]


def resolve(value, *, run=subprocess.run):
    spec = parse(value)
    if spec is None:
        return value
    target, interface, port = spec
    try:
        if target:
            command = "networksetup -listallhardwareports; printf "+shlex.quote("\n"+MARKER+"\n")+"; ifconfig "+shlex.quote(interface)
            r = run(_control_ssh(target,"-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=5",command=command),
                    capture_output=True,text=True,timeout=12)
            if r.returncode or r.stdout.count(MARKER) != 1:
                raise RetryableReadinessError(T("agent.service_endpoints.trusted_ssh_thunderbolt_discovery_unavailable_no"), kind="thunderbolt")
            ports, config = r.stdout.split(MARKER)
        else:
            r = run(["networksetup","-listallhardwareports"],capture_output=True,text=True,timeout=5)
            if r.returncode:raise RetryableReadinessError(T("agent.service_endpoints.cannot_inspect_thunderbolt_hardware_ports"), kind="thunderbolt")
            ports = r.stdout
            r = run(["ifconfig",interface],capture_output=True,text=True,timeout=5)
            if r.returncode:raise RetryableReadinessError(T("agent.service_endpoints.cannot_inspect_the_selected_thunderbolt_interfac"), kind="thunderbolt")
            config = r.stdout
        return f"{address(ports,config,interface)}:{port}"
    except (OSError, subprocess.SubprocessError) as e:
        raise RetryableReadinessError(T("agent.service_endpoints.thunderbolt_address_not_ready_e", e=e), kind="thunderbolt") from None


def runtime_plan(plan):
    return dict(plan, **{k:resolve(plan[k]) for k in ("listen","peer","upstream") if k in plan})


def dynamic(plan):
    return any(parse(plan[k]) is not None for k in ("listen","peer","upstream") if k in plan)
