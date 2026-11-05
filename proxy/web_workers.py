"""Start / stop the lead (local) and packer (SSH to EXO2) for the web UI.

Only touches Caravan's own test workers (mlx_worker.py on ports we own).
Never touches launchd, Talaria Hub, exo, or Hermes. Progress is parsed from
worker logs ("loaded …", "listening on …").
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import sys

import web_catalog as catalog
import web_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
import tuned_settings as TS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WORKER = REPO / "agent" / "mlx_worker.py"
DEFAULT_PY = str(Path("~/.caravan/venvs/mlx/bin/python").expanduser())
LEAD_PORT = int(os.environ.get("CARAVAN_WEB_LEAD_PORT", "8194"))
PACKER_PEER = catalog.DEFAULT_PACKER_PEER
PACKER_SSH = catalog.DEFAULT_PACKER_SSH
WEB_STATE_DIR = Path(os.environ.get(
    "CARAVAN_WEB_STATE", str(Path.home() / ".caravan" / "web-ui"))).expanduser()


class WorkerManager:
    def __init__(self, *, python: str = DEFAULT_PY, lead_port: int = LEAD_PORT,
                 packer_peer: str = PACKER_PEER, packer_ssh: str = PACKER_SSH,
                 state_dir: Optional[Path] = None, repo: Optional[Path] = None):
        self.python = python
        self.lead_port = lead_port
        self.packer_peer = packer_peer
        self.packer_ssh = packer_ssh
        self.state_dir = Path(state_dir or WEB_STATE_DIR)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.repo = Path(repo or REPO)
        self.worker = self.repo / "agent" / "mlx_worker.py"
        self._lock = threading.Lock()
        self.state = {
            "status": "idle",          # idle | stopping | starting_packer | starting_lead | ready | error
            "model_id": None,
            "model_name": None,
            "progress": [],            # [{t, msg}]
            "error": None,
            "lead_pid": None,
            "packer_pid": None,
            "lead_url": f"http://127.0.0.1:{lead_port}",
            "split": True,
            "lpm_ok": None,
            "settings": web_settings.normalize({}),
        }
        self._lead_proc: Optional[subprocess.Popen] = None
        self._switch_thread: Optional[threading.Thread] = None
        tp = os.environ.get("CARAVAN_TUNED_SETTINGS")
        self.tuned_path: Optional[Path] = Path(tp).expanduser() if tp else None
        self._lead_path: Optional[str] = None

    # ----- public ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self.state)
            s["progress"] = list(self.state["progress"])
        return s

    def _note(self, msg: str) -> None:
        with self._lock:
            self.state["progress"].append({"t": round(time.time(), 3), "msg": msg})
            # keep last 40
            self.state["progress"] = self.state["progress"][-40:]

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)

    def check_lpm(self) -> bool:
        """Refuse timing / heavy load if Low Power Mode is on (macOS)."""
        try:
            out = subprocess.check_output(["pmset", "-g"], text=True, timeout=5)
        except (FileNotFoundError, subprocess.SubprocessError):
            # Non-macOS (unit tests): treat as OK.
            self._set(lpm_ok=True)
            return True
        m = re.search(r"lowpowermode\s+(\d+)", out)
        ok = (m is None) or (m.group(1) == "0")
        self._set(lpm_ok=ok)
        return ok

    def stop(self, *, reason: str = "stop") -> None:
        self._set(status="stopping", error=None)
        self._note(f"stopping workers ({reason})")
        self._kill_lead()
        self._kill_packer()
        self._set(status="idle", model_id=None, model_name=None,
                  lead_pid=None, packer_pid=None)
        self._note("idle")

    def switch(self, model_id: str, *, wait: bool = False, settings=None) -> dict:
        settings = web_settings.normalize(settings)
        entry = catalog.get_model(model_id)
        if not entry:
            raise ValueError(f"unknown model: {model_id}")
        if not entry.get("available_lead"):
            raise FileNotFoundError(f"model not on this Mini: {model_id}")
        if self._switch_thread and self._switch_thread.is_alive():
            raise RuntimeError("a model switch is already in progress")

        def run():
            try:
                self._do_switch(entry, settings)
            except Exception as e:  # noqa: BLE001 — surface to UI
                self._set(status="error", error=f"{type(e).__name__}: {e}")
                self._note(f"error: {e}")

        self._switch_thread = threading.Thread(target=run, daemon=True)
        self._switch_thread.start()
        if wait:
            self._switch_thread.join()
        return self.snapshot()

    # ----- internals ------------------------------------------------------

    def _do_switch(self, entry: dict, settings=None) -> None:
        settings = web_settings.normalize(settings)
        self._set(settings=settings)
        if not self.check_lpm():
            raise RuntimeError("Low Power Mode is on — turn it off before loading a model")
        self._set(status="stopping", error=None, model_id=entry["id"],
                  model_name=entry["name"], progress=[])
        self._note(f"switching to {entry['name']}")
        lead_x, packer_x = web_settings.to_args(settings)
        self._lead_path = entry.get("lead_path")
        for line in self.plan_reload_args(entry, settings, lead_x, packer_x):
            self._note("self-tuning: " + line)
        self._extra_lead, self._extra_packer = lead_x, packer_x
        self._note("settings: " + ", ".join(f"{k}={v}" for k, v in settings.items())
                   + (f" -> {' '.join(lead_x)}" if lead_x else " (all auto)"))
        self._kill_lead()
        self._kill_packer()
        time.sleep(1.5)

        packer_path = self._resolve_packer_path(entry)
        self._set(status="starting_packer")
        self._note(f"starting packer on EXO2 ({packer_path})")
        packer_pid = self._start_packer(entry, packer_path)
        self._set(packer_pid=packer_pid)
        self._wait_packer_ready(timeout=300)

        self._set(status="starting_lead")
        self._note(f"starting lead on EXO1 ({entry['lead_path']})")
        lead_pid = self._start_lead(entry)
        self._set(lead_pid=lead_pid)
        self._wait_lead_ready(timeout=600)

        self._set(status="ready")
        self._note("ready")

    # ----- Day 15: reload trials (kv_bits, fuse_kernels, keepalive) -------

    def _tuned_entry(self, lead_path, *, create=False):
        st = TS.load_store(self.tuned_path)
        key = TS.entry_key(lead_path, spanned=True)
        if create:
            return st, TS.ensure_entry(st, key, model=TS.model_stem(lead_path),
                                       hardware=TS.hardware_label(spanned=True))
        return st, (st.get("models") or {}).get(key)

    def plan_reload_args(self, entry: dict, settings: dict, lead_x: list, packer_x: list) -> list:
        """Apply learned winners / one queued trial for reload options left on Auto.

        Pinned options (On/Off/8/4 in the panel) are untouched. Returns log lines.
        """
        if settings.get("self_tune") == "off" or not entry.get("lead_path"):
            return []
        auto = [n for n in TS.RELOAD_TRIO if settings.get(n) == "auto"]
        if not auto:
            return []
        try:
            st, e = self._tuned_entry(entry["lead_path"], create=True)
            plan = TS.plan_reload(e, auto)
            TS.save_store(st, self.tuned_path)
        except (OSError, ValueError) as ex:
            return [f"reload plan skipped ({ex})"]
        v = plan["values"]
        both = []
        if "kv_bits" in v and int(v["kv_bits"]) != 16:
            both += ["--kv-bits", str(int(v["kv_bits"]))]
        if "fuse_kernels" in v:
            both += ["--fuse-kernels", "all" if v["fuse_kernels"] == "on" else "off"]
        if "keepalive" in v:
            both.append("--split-keepalive" if v["keepalive"] else "--no-split-keepalive")
        lead_x += both + ["--learn-reload-auto", ",".join(auto)]
        packer_x += both
        return plan["reasons"]

    def tuning_status(self, active: Optional[dict]) -> dict:
        """What self-tuning is doing with reload options, for the page."""
        lp = self._lead_path
        if not lp:
            return {"known": False}
        try:
            _, e = self._tuned_entry(lp)
        except (OSError, ValueError):
            e = None
        a = active or {}
        running = {"kv_bits": a.get("kv_bits"), "keepalive": a.get("keepalive"),
                   "fuse_kernels": a.get("fuse_kernels")}
        out = TS.reload_status(e, running, a.get("reload_auto") or [])
        out["known"] = True
        out["replies_learned"] = int((e or {}).get("reply_n") or 0)
        out["winner"] = dict((e or {}).get("winner") or {})
        return out

    def adopt_running(self) -> bool:
        """After a web-server restart, adopt a lead we started earlier.

        Reads our own lead.pid + its command line; never starts or stops anything.
        """
        try:
            pid = int((self.state_dir / "lead.pid").read_text().strip())
            cmd = subprocess.check_output(["ps", "-o", "command=", "-p", str(pid)],
                                          text=True, timeout=5).strip()
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
        if "mlx_worker.py" not in cmd or not self.lead_healthy():
            return False
        for m in catalog.list_models():
            lp = m.get("lead_path")
            if lp and f"--model {lp}" in cmd:
                self._lead_path = lp
                self._set(status="ready", model_id=m["id"], model_name=m["name"],
                          lead_pid=pid, settings=web_settings.from_args(cmd))
                self._note(f"adopted running lead (pid {pid}) after web restart")
                return True
        return False

    def _lead_log(self) -> Path:
        return self.state_dir / "lead.log"

    def _packer_log_remote(self) -> str:
        return "~/.caravan/web-ui/packer.log"

    def _kill_lead(self) -> None:
        # Only our own worker on the test port / our log marker.
        if self._lead_proc and self._lead_proc.poll() is None:
            try:
                self._lead_proc.send_signal(signal.SIGTERM)
                self._lead_proc.wait(timeout=8)
            except Exception:
                try:
                    self._lead_proc.kill()
                except Exception:
                    pass
        self._lead_proc = None
        # Also clear any leftover mlx_worker we started on this port.
        subprocess.run(
            ["pkill", "-f", f"mlx_worker.py.*--port {self.lead_port}"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Narrow fallback used by Day 12/13 scripts when the port match misses.
        subprocess.run(
            ["pkill", "-f", "mlx_worker.py"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _ssh(self, remote_cmd: str, *, timeout: float = 60) -> subprocess.CompletedProcess:
        cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            self.packer_ssh, remote_cmd,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _kill_packer(self) -> None:
        try:
            self._ssh("pkill -f mlx_worker.py 2>/dev/null || true; sleep 1; echo killed")
        except Exception as e:
            self._note(f"packer kill warn: {e}")

    def _resolve_packer_path(self, entry: dict) -> str:
        # Ask EXO2 which candidate exists.
        cands = entry.get("packer_path_candidates") or [entry.get("packer_path")]
        cands = [c for c in cands if c]
        if not cands:
            raise FileNotFoundError("no packer path candidates")
        script = " ; ".join(
            f'[ -d {shlex.quote(c)} ] && echo FOUND:{c} && exit 0'
            for c in cands
        ) + "; echo NONE; exit 1"
        r = self._ssh(script, timeout=30)
        for line in (r.stdout or "").splitlines():
            if line.startswith("FOUND:"):
                return line[len("FOUND:"):]
        raise FileNotFoundError(
            f"model not on packer Mini; tried {cands}; ssh_rc={r.returncode} "
            f"err={(r.stderr or '')[:200]}")

    def _start_packer(self, entry: dict, packer_path: str) -> Optional[int]:
        k = int(entry["packer_layers"])
        # Prefer EXO2's own clone of the repo (~/cv3).
        remote = (
            "mkdir -p ~/.caravan/web-ui; "
            "LPM=$(pmset -g 2>/dev/null | awk '/lowpowermode/{print $2}'); "
            "[[ \"$LPM\" == \"0\" || -z \"$LPM\" ]] || { echo REFUSE_LPM; exit 2; }; "
            f"nohup ~/.caravan/venvs/mlx/bin/python ~/cv3/agent/mlx_worker.py "
            f"--model {shlex.quote(packer_path)} "
            f"--split-role packer --split-listen {shlex.quote(self.packer_peer)} "
            f"--split-packer-layers {k} --no-split-draft --split-draft-skip-first-load "
            + "".join(f"{shlex.quote(a)} " for a in getattr(self, "_extra_packer", []))
            + f"> ~/.caravan/web-ui/packer.log 2>&1 & echo $! > ~/.caravan/web-ui/packer.pid; "
            "cat ~/.caravan/web-ui/packer.pid"
        )
        r = self._ssh(remote, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"packer start failed: {(r.stderr or r.stdout or '')[:300]}")
        pid = None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
        return pid

    def _wait_packer_ready(self, timeout: float = 300) -> None:
        # Packer has no HTTP; watch the log for "loaded".
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self._ssh(
                "tail -n 40 ~/.caravan/web-ui/packer.log 2>/dev/null || true",
                timeout=20)
            text = r.stdout or ""
            for line in text.splitlines()[-10:]:
                if "loaded" in line.lower() or "serve" in line.lower() or "listening" in line.lower():
                    self._note("packer: " + line.strip()[:160])
                if re.search(r"loaded .+ in [\d.]+s", line) or "serve_front" in line or "stage" in line and "loaded" in line:
                    # Also accept "packer stage … loaded"
                    if "loaded" in line:
                        self._note("packer ready")
                        return
            if "Error" in text or "Traceback" in text:
                # Keep waiting a bit — load errors are fatal though.
                if "Traceback" in text:
                    raise RuntimeError("packer traceback:\n" + "\n".join(text.splitlines()[-20:]))
            time.sleep(1.5)
        raise TimeoutError("packer did not become ready in time")

    def _start_lead(self, entry: dict) -> int:
        k = int(entry["packer_layers"])
        log_path = self._lead_log()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate log.
        log_path.write_text("")
        args = [
            self.python, str(self.worker),
            "--model", entry["lead_path"],
            "--split-role", "lead",
            "--split-peer", self.packer_peer,
            "--host", "127.0.0.1",
            "--port", str(self.lead_port),
            "--split-packer-layers", str(k),
            "--split-draft-skip-first-load",
            # Keep draft auto-pair on (Day 12 win) unless env disables.
        ]
        if os.environ.get("CARAVAN_WEB_NO_DRAFT", "").strip() in ("1", "true", "yes"):
            args.append("--no-split-draft")
        args += list(getattr(self, "_extra_lead", []))
        # Shared-prefix: leave to learn / saved tuned settings (Day 13).
        env = os.environ.copy()
        lf = open(log_path, "ab", buffering=0)
        self._lead_proc = subprocess.Popen(
            args, stdout=lf, stderr=subprocess.STDOUT, cwd=str(self.repo / "agent"),
            start_new_session=True)
        (self.state_dir / "lead.pid").write_text(str(self._lead_proc.pid))
        return self._lead_proc.pid

    def _wait_lead_ready(self, timeout: float = 600) -> None:
        import urllib.request
        deadline = time.time() + timeout
        log_path = self._lead_log()
        url = f"http://127.0.0.1:{self.lead_port}/health"
        last_size = 0
        while time.time() < deadline:
            if self._lead_proc and self._lead_proc.poll() is not None:
                tail = log_path.read_text(errors="replace")[-2000:] if log_path.exists() else ""
                raise RuntimeError(f"lead exited early (rc={self._lead_proc.returncode}): {tail}")
            if log_path.exists():
                text = log_path.read_text(errors="replace")
                if len(text) > last_size:
                    for line in text[last_size:].splitlines():
                        if line.strip():
                            self._note("lead: " + line.strip()[:160])
                    last_size = len(text)
                if "Traceback" in text and "listening on" not in text:
                    # May still be loading; only fail if process died (above).
                    pass
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        self._note("lead health ok")
                        return
            except Exception:
                pass
            time.sleep(1.0)
        raise TimeoutError("lead did not become ready in time")

    def lead_healthy(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.lead_port}/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def lead_active_settings(self):
        """Day 15: settings the running lead reports (learned winners applied)."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.lead_port}/caravan/settings", timeout=3) as r:
                return json.loads(r.read().decode()).get("active")
        except Exception:
            return None

    def lead_split_info(self):
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.lead_port}/caravan/split", timeout=5) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"error": str(e)}
