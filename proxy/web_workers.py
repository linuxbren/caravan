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


class GgufLoadError(RuntimeError):
    """Short plain message for the page; full log tail in .detail."""
    def __init__(self, msg: str, detail: str = ""):
        super().__init__(msg)
        self.detail = detail


def gguf_friendly(err: Exception, peers: list) -> str:
    t = str(err)
    names = " + ".join(peers) or "the other Mini"
    if "Failed to connect" in t or "tunnel" in t.lower() or "RPC handshake" in t:
        return f"Couldn't reach {names} for the split. Try again."
    if "rpc-server" in t and "did not start" in t:
        return f"Couldn't start the split helper on {names}. Try again."
    if "out of memory" in t.lower() or "failed to allocate" in t.lower():
        return "Not enough memory for this placement. Try splitting across more Minis."
    if "missing" in t.lower() or "not found" in t.lower():
        return t.split("\n")[0][:160]
    return "The model didn't load. Details below."


class ManagedServiceError(RuntimeError):
    """An installed launchd plan, not the web UI, owns this worker."""


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
            "settings": web_settings.normalize({}),   # what the load used (page + file)
            "page_settings": web_settings.normalize({}),  # what the page asked for
            "from_file": {},                              # options filled from config.toml
            "config_errors": [],
        }
        self._lead_proc: Optional[subprocess.Popen] = None
        self._switch_thread: Optional[threading.Thread] = None
        tp = os.environ.get("CARAVAN_TUNED_SETTINGS")
        self.tuned_path: Optional[Path] = Path(tp).expanduser() if tp else None
        self._lead_path: Optional[str] = None
        self._worker_node: Optional[dict] = None  # None = local lead; else remote node
        self._tunnel_proc: Optional[subprocess.Popen] = None

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

    def _deny_managed_service(self):
        import service_config as SC
        try:
            plan = SC.managed_lead(Path.home(), self.lead_port)
        except ValueError as e:
            raise ManagedServiceError(str(e)) from None
        if plan:
            raise ManagedServiceError(
                f"Auto-start service '{plan['name']}' owns this model. "
                "Use tools/caravan_service.py uninstall --name " + plan["name"] +
                " on the lead (and uninstall its packer jobs before switching splits). Files are kept.")

    def refresh_managed_service(self):
        """Adopt a launchd lead even if web started before peers/model were ready."""
        import service_config as SC
        from worker_ownership import command_of, matches
        now = time.monotonic()
        if now - getattr(self, "_managed_poll_at", 0) < 1:
            return
        self._managed_poll_at = now
        try:
            plan = SC.managed_lead(Path.home(), self.lead_port)
        except ValueError as e:
            self._set(status="error", error=str(e))
            return
        if not plan:
            if self.state.get("managed_service"):
                self._set(status="idle", model_id=None, model_name=None, lead_pid=None, managed_service=None)
            return
        info = {"name":plan["name"], "label":plan["label"], "role":plan["role"],
                "note":"Owned by launchd; use the service CLI to change or stop it."}
        runtime = {}
        try:
            runtime = json.loads(SC.paths(plan)["runtime"].read_text())
            pid = int(runtime["pid"])
            healthy = matches(command_of(pid), Path(plan["repo"])/"agent/mlx_worker.py", port=self.lead_port) and self.lead_healthy()
        except (OSError,ValueError,KeyError):
            pid, healthy = None, False
        mid = Path(plan["model"]).name.replace("--","/")
        self._lead_path = plan["model"]
        self._loaded_entry = {"id":mid,"name":mid,"lead_path":plan["model"],"source":"mlx",
                              "run_mode":"split" if plan["role"] == "lead" else "single"}
        self._set(status="ready" if healthy else "starting_lead", model_id=mid, model_name=mid,
                  lead_pid=pid, split=plan["role"] == "lead", managed_service=info)

    def stop(self, *, reason: str = "stop") -> None:
        self._deny_managed_service()
        self._set(status="stopping", error=None)
        self._note(f"stopping workers ({reason})")
        self._gguf_cancel = True  # a GGUF load in flight stops at its next step
        self._kill_gguf()
        self._kill_lead()
        self._kill_packer()
        self._set(status="idle", model_id=None, model_name=None,
                  lead_pid=None, packer_pid=None)
        self._note("idle")

    def switch(self, model_id: str, *, wait: bool = False, settings=None,
               entry: Optional[dict] = None, sweep=None) -> dict:
        self._deny_managed_service()
        settings = web_settings.normalize(settings)
        if entry is None:
            entry = catalog.get_model(model_id)
        if not entry:
            raise ValueError(f"unknown model: {model_id}")
        if entry.get("source") == "gguf":
            if not entry.get("lead_path"):
                raise FileNotFoundError(f"GGUF file not on the lead Mini: {model_id}")
            entry = dict(entry)
            entry["usable"] = True
            entry["available_lead"] = True
        # available_lead is local-path oriented; remote one-Mini placements set
        # usable/lead_path from the holding Mini instead.
        if not entry.get("available_lead") and not (
            entry.get("usable") and entry.get("lead_path")
            and (entry.get("placement") or {}).get("mode") in ("one", "all")
        ):
            raise FileNotFoundError(f"model not on this Mini: {model_id}")
        if self._switch_thread and self._switch_thread.is_alive():
            raise RuntimeError("a model switch is already in progress")

        def run():
            try:
                self._sweep_load = sweep
                self._do_switch(entry, settings)
            except GgufLoadError as e:
                # Cleaned up already; leave a sane idle state with a plain message.
                self._set(status="idle", model_id=None, model_name=None, lead_pid=None,
                          error=str(e), error_detail=e.detail)
                self._note("load failed: " + str(e))
            except Exception as e:  # noqa: BLE001 — surface to UI
                self._set(status="error", error=f"{type(e).__name__}: {e}")
                self._note(f"error: {e}")
            finally:
                self._sweep_load = None

        self._switch_thread = threading.Thread(target=run, daemon=True)
        self._switch_thread.start()
        if wait:
            self._switch_thread.join()
        return self.snapshot()

    # ----- internals ------------------------------------------------------

    def _do_switch(self, entry: dict, settings=None) -> None:
        page = web_settings.normalize(settings)
        cfg = web_settings.load_config()
        fsets = web_settings.file_settings(entry.get("id"), entry.get("lead_path"), cfg)
        fsets.pop("thinking", None)   # the page's Thinking button reads that one
        settings, from_file = web_settings.merge_with_file(page, fsets)
        self._set(settings=settings, page_settings=page, from_file=from_file,
                  config_errors=cfg.get("errors") or [])
        for err in cfg.get("errors") or []:
            self._note("config.toml: " + err)
        if from_file:
            self._note("config.toml pins: " + ", ".join(f"{k}={v}" for k, v in from_file.items()))
        try:
            self._load_once(entry, settings)
        except Exception as e:  # noqa: BLE001
            trial = getattr(self, "_reload_trial", None)
            if not trial:
                raise
            # A self-tune reload trial broke the load: never try that value
            # again for this model, go back to the winner and load that.
            why = f"{type(e).__name__}: {str(e)[-200:]}"
            self._note(f"self-tuning: {TS.RELOAD_LABEL.get(trial['name'], trial['name'])} "
                       f"{TS.reload_value_label(trial['name'], trial['value'])} failed to load; "
                       f"rejected, rolling back")
            try:
                st, ent = self._tuned_entry(entry["lead_path"], create=True)
                TS.block_value(ent, trial["name"], trial["value"], why)
                ent["reload_trial"] = None
                TS.save_store(st, self.tuned_path)
            except (OSError, ValueError) as ex:
                self._note(f"could not record rejected trial ({ex})")
            self._load_once(entry, settings)

    def _load_once(self, entry: dict, settings: dict) -> None:
        self._reload_trial = None
        if not self.check_lpm():
            raise RuntimeError("Low Power Mode is on — turn it off before loading a model")
        if entry.get("source") == "gguf":
            return self._load_gguf(entry, settings)
        if entry.get("split_counts"):
            from web_pipeline import load_pipeline
            return load_pipeline(self, entry, settings)
        run_mode = self._resolve_run_mode(entry)
        entry = dict(entry)
        entry["run_mode"] = run_mode
        entry["need_split"] = run_mode == "split"
        self._set(balance=None)
        self._set(status="stopping", error=None, model_id=entry["id"],
                  model_name=entry["name"], progress=[], split=(run_mode == "split"))
        self._note(f"switching to {entry['name']} ({run_mode})")
        problems = self.preflight_load(entry)
        if problems:
            raise FileNotFoundError("; ".join(problems))
        if settings.get("guess_ahead") == "mtp" and (run_mode != "single" or not entry.get("native_mtp_available")):
            raise ValueError("native MTP needs a single-Mini matching target with an installed head")
        lead_x, packer_x = web_settings.to_args(settings)
        sweep = getattr(self, "_sweep_load", None)
        if sweep:
            lead_x += ["--sweep-paused"]
            if sweep.get("packer_layers") is not None:
                lead_x += ["--split-front-layers", str(sweep["packer_layers"])]
                packer_x += ["--split-front-layers", str(sweep["packer_layers"])]
        self._lead_path = entry.get("lead_path")
        for line in self.plan_reload_args(entry, settings, lead_x, packer_x):
            self._note("self-tuning: " + line)
        self._extra_lead, self._extra_packer = lead_x, packer_x
        self._note("settings: " + ", ".join(f"{k}={v}" for k, v in settings.items())
                   + (f" -> {' '.join(lead_x)}" if lead_x else " (all auto)"))
        self._kill_gguf()
        self._kill_lead()
        self._kill_packer()
        time.sleep(1.5)

        if run_mode == "split":
            packer_path = self._resolve_packer_path(entry)
            self._set(status="starting_packer", packer_pid=None)
            self._note(f"starting packer on EXO2 ({packer_path})")
            packer_pid = self._start_packer(entry, packer_path)
            self._set(packer_pid=packer_pid)
            self._wait_packer_ready(timeout=300)
            self._set(status="starting_lead")
            self._note(f"starting lead on EXO1 ({entry['lead_path']})")
            lead_pid = self._start_lead(entry, split=True)
        else:
            self._set(status="starting_lead", packer_pid=None)
            node = self._resolve_worker_node(entry, place=entry.get("placement"))
            self._worker_node = node
            if node and not self._node_is_local(node):
                self._note(
                    f"starting single-Mini worker on {node.get('label') or node.get('id')} "
                    f"({entry.get('lead_path')})"
                )
                lead_pid = self._start_remote_single(entry, node)
            else:
                self._note(f"starting single-Mini worker on EXO1 ({entry['lead_path']})")
                lead_pid = self._start_lead(entry, split=False)
        self._set(lead_pid=lead_pid)
        self._wait_lead_ready(timeout=600)

        self._loaded_entry = dict(entry)
        self._set(status="ready", split=(run_mode == "split"))
        self._note("ready")

    # ----- GGUF via llama.cpp (one Mini or rpc split across K Minis) -----

    def _gguf_meta_path(self) -> Path:
        return self.state_dir / "gguf.json"

    def _gguf_nodes(self, place: Optional[dict]) -> list:
        """Configured nodes named by the placement, lead first. Default: lead only."""
        from web_nodes import nodes_from_config
        nodes = nodes_from_config()
        live = {}
        try:
            live = {n.get("id"): n for n in (getattr(self, "live_nodes", None) or [])}
        except Exception:
            live = {}
        want = [str(x).lower() for x in ((place or {}).get("node_ids") or [])]
        lead = [n for n in nodes if n.get("role") == "lead"][:1]
        if not want:
            return lead
        picked = [n for n in nodes if str(n.get("id")).lower() in want
                  or str(n.get("label") or "").lower() in want]
        picked.sort(key=lambda n: 0 if n.get("role") == "lead" else 1)
        if not picked or picked[0].get("role") != "lead":
            picked = lead + [n for n in picked if n not in lead]
        return [dict(n, **{k: v for k, v in (live.get(n.get("id")) or {}).items() if k == "ram"})
                for n in picked]

    def _load_gguf(self, entry: dict, settings: dict) -> None:
        self._quiet_lead_log = True
        try:
            self._load_gguf_inner(entry, settings)
        except Exception as e:  # noqa: BLE001
            peers = [n for n in (self.state.get("gguf") or {}).get("labels") or []][1:]
            try:
                self._kill_gguf()
            except Exception as ke:  # noqa: BLE001
                self._note(f"cleanup: {ke}")
            if getattr(self, "_gguf_cancel", False):
                raise GgufLoadError("Load stopped.", f"{type(e).__name__}: {e}"[-4000:]) from e
            raise GgufLoadError(gguf_friendly(e, peers), f"{type(e).__name__}: {e}"[-4000:]) from e
        finally:
            self._quiet_lead_log = False

    def _load_gguf_inner(self, entry: dict, settings: dict) -> None:
        import gguf_split as G
        place = entry.get("placement") or {}
        nodes = self._gguf_nodes(place)
        peers = [n for n in nodes if not self._node_is_local(n)]
        mode = "split" if peers else "single"
        label = " + ".join(n.get("label") or n.get("id") for n in nodes)
        gblock = {"nodes": [n.get("id") for n in nodes], "labels": [n.get("label") for n in nodes],
                  "mode": mode}
        self._set(status="stopping", error=None, error_detail=None, model_id=entry["id"],
                  model_name=entry["name"], progress=[], split=bool(peers), backend="llama", gguf=gblock)
        self._note(f"switching to {entry['name']} (GGUF, llama.cpp, {'split across ' if peers else 'on '}{label})")
        path = Path(entry["lead_path"]).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"GGUF file missing on the lead Mini: {path}")
        binp = Path(G.LLAMA_BIN).expanduser() / "llama-server"
        if not binp.is_file():
            raise FileNotFoundError(f"llama-server not found at {binp} (set CARAVAN_LLAMA_BIN)")
        self._gguf_cancel = False
        self._kill_gguf()
        self._kill_lead()
        self._kill_packer()
        # _kill_gguf clears the gguf block; put this load's back for Topology.
        self._set(backend="llama", gguf=gblock, status="starting_packer" if peers else "starting_lead")
        time.sleep(1.0)
        meta = {"lead_pid": None, "peers": [], "tunnels": [], "model": str(path),
                "id": entry["id"], "name": entry["name"], "gguf": gblock}
        self._write_gguf_meta(meta)
        rpc = []
        for i, n in enumerate(peers):
            self._check_cancel()
            name = n.get("label") or n.get("id")
            target = (n.get("ssh") or n.get("host") or "").strip()
            if not target:
                raise RuntimeError(f"no SSH target for {name}; set ssh in [web.nodes.{n.get('id')}]")
            self._note(f"starting rpc-server on {name} (127.0.0.1:{G.RPC_PORT}, reached over SSH)")
            r = self._ssh_node(n, G.rpc_start_command(), timeout=40)
            pid = G.parse_pid(r.stdout)
            if not pid:
                raise RuntimeError(f"rpc-server on {name} did not start: "
                                   f"{(r.stdout or '')[-300:]} {(r.stderr or '')[-200:]}")
            meta["peers"].append({"id": n.get("id"), "label": name, "ssh": target, "pid": pid})
            self._write_gguf_meta(meta)
            lp = G.tunnel_port(i)
            tun = self._open_tunnel(target, lp)
            meta["tunnels"].append({"pid": tun.pid, "port": lp, "ssh": target, "id": n.get("id")})
            self._write_gguf_meta(meta)
            if not G.wait_port(lp, proc=tun, timeout=10):
                err = (tun.stderr.read() if tun.poll() is not None and tun.stderr else b"") or b""
                raise RuntimeError(f"SSH tunnel to {name} failed: {err.decode(errors='replace')[:300]}")
            rpc.append(f"127.0.0.1:{lp}")
            self._note(f"rpc-server on {name} up (pid {pid}), tunnel 127.0.0.1:{lp}")
        self._check_cancel()
        free = [self._free_gb(n) for n in nodes] if peers else [None]
        shares = G.shares_from_free(free) if peers else [1]
        if peers:
            self._note("free RAM now: " + ", ".join(
                f"{n.get('label')} {f if f is not None else '?'} GB" for n, f in zip(nodes, free))
                + " → split " + ":".join(str(x) for x in shares)
                + ("" if all(f for f in free) else " (equal: free RAM unknown)"))
        meta["shares"] = shares
        for i, n in enumerate(peers):
            # GGUF stage 2: a peer with its own copy fills its rpc cache from disk.
            self._check_cancel()
            name = n.get("label") or n.get("id")
            try:
                r = self._ssh_node(n, G.seed_command(path.name, path.stat().st_size, shares, i + 1,
                                                     repo=n.get("repo") or "~/cv3"), timeout=1800)
                rep = G.parse_seed(r.stdout)
            except Exception as e:  # noqa: BLE001 - stage 2 is an optimisation only
                rep, r = None, None
                self._note(f"{name}: local seed skipped ({e})")
            if rep:
                meta.setdefault("seed", {})[n.get("id") or name] = rep
                self._note(f"{name} loads its share from its own disk: {rep['tensors']} tensors, "
                           f"{rep['bytes'] / 1e9:.1f} GB ({rep['new']} new, {rep['have']} cached) "
                           f"in {rep['s']}s")
            elif r is not None:
                self._note(f"{name}: no local copy of {path.name}; its share goes over the link")
        try:
            import gguf_tune as GT
            tune = (dict(entry["tune_override"]) if isinstance(entry.get("tune_override"), dict)
                    else GT.best_tune(path, 1 + len(rpc)))
        except Exception:  # noqa: BLE001 - tuning is optional
            tune = {}
        if tune:
            self._note(f"GGUF tuned settings from Optimize now: {tune}")
        args = G.llama_args(str(path), port=self.lead_port, peers=rpc, shares=shares, tune=tune)
        self._set(status="starting_lead", packer_pid=None)
        seeded = bool(meta.get("seed"))
        self._note(("starting llama-server on EXO1; peers with their own copy load from disk, "
                    "others get their share over the link" if seeded else
                    "starting llama-server on EXO1, peers get their share over the link "
                    "(first load copies it, later loads use the peer cache)") if rpc
                   else "starting llama-server on EXO1 (one Mini)")
        log_path = self._lead_log()
        log_path.write_text("")
        lf = open(log_path, "ab", buffering=0)
        self._worker_node = None
        self._lead_proc = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT,
                                           start_new_session=True)
        meta["lead_pid"] = self._lead_proc.pid
        self._write_gguf_meta(meta)
        self._set(lead_pid=self._lead_proc.pid)
        t0 = time.time()
        self._wait_lead_ready(timeout=1200)
        self._check_cancel()
        self._note(f"loaded in {time.time() - t0:.1f}s")
        # GGUF Optimize now reads this (it refused "needs a GGUF model loaded" before).
        self._loaded_entry = {k: v for k, v in entry.items() if k != "tune_override"}
        self._set(status="ready", split=bool(peers))
        self._note("ready")
        self._start_gguf_watch(meta)

    def _check_cancel(self):
        if getattr(self, "_gguf_cancel", False):
            raise RuntimeError("load stopped")

    def _write_gguf_meta(self, meta: dict) -> None:
        self._gguf_meta_path().write_text(json.dumps(meta))

    def _open_tunnel(self, target: str, port: int):
        import gguf_split as G
        return subprocess.Popen(G.ssh_tunnel_args(target, port), stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, start_new_session=True)

    def _free_gb(self, node: dict):
        import gguf_split as G
        try:
            if self._node_is_local(node):
                r = subprocess.run(["/bin/sh", "-c", G.FREE_RAM_CMD], capture_output=True,
                                   text=True, timeout=10)
            else:
                r = self._ssh_node(node, G.FREE_RAM_CMD, timeout=15)
            return G.parse_free_gb(r.stdout)
        except Exception:  # noqa: BLE001
            return None

    # Watch a ready GGUF load: if llama-server dies (e.g. a peer's rpc-server
    # went away mid-chat), clean up everything we started and go idle with a
    # plain message instead of leaving a dead "ready".
    def _start_gguf_watch(self, meta: dict) -> None:
        import gguf_split as G
        token = object()
        self._gguf_watch_token = token
        pid = meta.get("lead_pid")

        def run():
            while getattr(self, "_gguf_watch_token", None) is token:
                time.sleep(1.0)
                if getattr(self, "_gguf_watch_token", None) is not token:
                    return
                if self.state.get("status") != "ready" or self.state.get("model_id") != meta.get("id"):
                    continue
                proc = self._lead_proc if (self._lead_proc and self._lead_proc.pid == pid) else None
                dead = (proc.poll() is not None) if proc else ("llama-server" not in G.pid_cmdline(pid))
                if not dead:
                    continue
                tail = ""
                try:
                    tail = self._lead_log().read_text(errors="replace")[-3000:]
                except OSError:
                    pass
                peers = [p.get("label") or p.get("id") for p in meta.get("peers") or []]
                if "RPC" in tail or "rpc" in tail or "Failed to connect" in tail or "Broken pipe" in tail:
                    msg = (f"Lost {' + '.join(peers) or 'a Mini'} during the split. Load it again."
                           if peers else "llama-server stopped. Load the model again.")
                else:
                    msg = "llama-server stopped. Load the model again."
                self._gguf_watch_token = None
                try:
                    self._kill_gguf()
                except Exception as e:  # noqa: BLE001
                    self._note(f"cleanup: {e}")
                self._set(status="idle", model_id=None, model_name=None, lead_pid=None,
                          split=False, error=msg, error_detail=tail[-2500:])
                self._note("load failed: " + msg)
                return
        threading.Thread(target=run, daemon=True).start()

    def adopt_gguf(self) -> bool:
        """After a web restart: re-attach to the llama-server, tunnels and peer
        rpc-servers recorded in gguf.json (never starts a model)."""
        import gguf_split as G
        mp = self._gguf_meta_path()
        if not mp.is_file():
            return False
        try:
            meta = json.loads(mp.read_text())
        except ValueError:
            return False
        pid = meta.get("lead_pid")
        if not pid or "llama-server" not in G.pid_cmdline(pid) or not self.lead_healthy():
            return False
        for t in meta.get("tunnels") or []:
            if G.is_tunnel_cmd(G.pid_cmdline(t.get("pid"))):
                continue
            tun = self._open_tunnel(t["ssh"], t["port"])  # tunnel died with the old server
            t["pid"] = tun.pid
            G.wait_port(t["port"], proc=tun, timeout=10)
            self._note(f"reopened tunnel 127.0.0.1:{t['port']} to {t.get('id')}")
        self._write_gguf_meta(meta)
        gb = meta.get("gguf") or {}
        self._set(status="ready", model_id=meta.get("id"), model_name=meta.get("name"),
                  lead_pid=pid, split=gb.get("mode") == "split", backend="llama", gguf=gb,
                  error=None, error_detail=None)
        self._note(f"adopted running llama-server (pid {pid}) and "
                   f"{len(meta.get('tunnels') or [])} tunnel(s) after web restart")
        self._start_gguf_watch(meta)
        return True

    def _kill_gguf(self) -> None:
        """Stop only the llama-server, SSH tunnels and peer rpc-servers we recorded."""
        self._gguf_watch_token = None
        if getattr(self, "state_dir", None) is None:
            return
        mp = self._gguf_meta_path()
        if not mp.is_file():
            return
        import gguf_split as G
        try:
            meta = json.loads(mp.read_text())
        except ValueError:
            meta = {}
        pid = meta.get("lead_pid")
        if pid and "llama-server" in G.pid_cmdline(pid):
            try:
                os.kill(int(pid), signal.SIGTERM)
                for _ in range(30):
                    time.sleep(0.3)
                    os.kill(int(pid), 0)
                os.kill(int(pid), signal.SIGKILL)
            except (ProcessLookupError, OSError, ValueError):
                pass
        if self._lead_proc is not None and pid and self._lead_proc.pid == pid:
            try:
                self._lead_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            self._lead_proc = None
        for t in meta.get("tunnels") or []:
            tp = t.get("pid") if isinstance(t, dict) else t
            if tp and G.is_tunnel_cmd(G.pid_cmdline(tp)):
                try:
                    os.kill(int(tp), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
        for p in meta.get("peers") or []:
            target = p.get("ssh")
            if not target:
                continue
            try:
                r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target,
                                    G.rpc_stop_command()], capture_output=True, text=True, timeout=30)
                if r.returncode:
                    self._note(f"could not stop rpc-server on {p.get('id')}: {(r.stderr or '')[:200]}")
            except subprocess.SubprocessError as e:
                self._note(f"could not stop rpc-server on {p.get('id')}: {e}")
        mp.unlink()
        self._set(gguf=None, backend=None)

    def _resolve_run_mode(self, entry: dict) -> str:
        """single | split — placement file wins; else entry flags; else infer."""
        if entry.get("run_mode") in ("single", "split"):
            return entry["run_mode"]
        place = entry.get("placement")
        if not place and entry.get("lead_path"):
            try:
                from placement import read_placement
                place = read_placement(entry["lead_path"])
            except Exception:
                place = None
        mode = (place or {}).get("mode")
        if mode in ("one", "all"):
            # one / all → single-Mini worker (possibly on a non-lead Mini).
            return "single"
        if mode == "split" or entry.get("need_split"):
            return "split"
        return "single"

    def preflight_load(self, entry: dict) -> list:
        """Plain-English checks before killing the current worker."""
        problems = []
        run_mode = entry.get("run_mode") or self._resolve_run_mode(entry)
        lead = entry.get("lead_path")
        place = entry.get("placement")
        remote_node = None
        if run_mode == "single":
            remote_node = self._resolve_worker_node(entry, place=place)
        if remote_node and not self._node_is_local(remote_node):
            # Model lives on another Mini — check there via SSH.
            label = remote_node.get("label") or remote_node.get("id") or "remote Mini"
            if not lead:
                problems.append(f"model folder not found on {label}")
            else:
                # Expanduser locally for the usual ~/.caravan path; same on sibling Minis.
                d = str(Path(lead).expanduser())
                check = (
                    "d=%s; "
                    "if [ -f \"$d/config.json\" ] && ls \"$d\"/*.safetensors >/dev/null 2>&1; "
                    "then echo OK; "
                    "elif [ -f \"$d/config.json\" ] && [ -f \"$d/model.safetensors.index.json\" ]; "
                    "then echo OK; else echo MISSING; fi"
                ) % repr(d)
                try:
                    r = self._ssh_node(remote_node, check, timeout=25)
                    out = (r.stdout or "").strip().splitlines()
                    if not out or out[-1] != "OK":
                        problems.append(f"model missing on {label}: {lead}")
                except Exception as e:
                    problems.append(f"can't reach {label} to check model: {e}")
        elif not lead:
            problems.append("model folder not found on this Mini (EXO1)")
        else:
            lp = Path(lead).expanduser()
            if not lp.is_dir():
                problems.append(f"model folder missing on EXO1: {lead}")
            elif not (lp / "config.json").is_file():
                problems.append(f"config.json missing in {lead}")
            else:
                try:
                    from mlx_arch import architecture_status
                    arch = architecture_status(lp)
                    if not arch.get("supported"):
                        problems.append(arch.get("reason") or "unsupported architecture")
                    elif arch.get("remapped"):
                        self._note("architecture: " + (arch.get("reason") or "remapped"))
                except Exception:
                    pass
                # Need at least one weight file for single / lead
                has_w = any(lp.glob("*.safetensors")) or (lp / "model.safetensors.index.json").is_file()
                if not has_w:
                    problems.append(f"no weight files in {lead}")
        if run_mode == "split":
            # Packer must have a tree — cheap existence check (same as resolve).
            try:
                self._resolve_packer_path(entry)
                self._assert_packer_unmanaged()
            except FileNotFoundError as e:
                problems.append(
                    "model isn't on the packer Mini (EXO2). "
                    "For a one-Mini download, load after placing on EXO1 only — "
                    "or re-download as a split / copy-to-all. "
                    f"({e})"
                )
        return problems

    # ----- Day 15: reload trials (kv_bits, fuse_kernels, keepalive) -------

    def _tuned_entry(self, lead_path, *, create=False, spanned=None):
        """Look up the tuned-settings entry for this model.

        spanned follows the running worker (split vs single-Mini). Using the
        wrong key made Deep/Quick optimize show 0/3 forever on one-Mini loads.
        """
        st = TS.load_store(self.tuned_path)
        if spanned is None:
            spanned = bool(self.state.get("split"))
        key = TS.entry_key(lead_path, spanned=spanned)
        if create:
            return st, TS.ensure_entry(st, key, model=TS.model_stem(lead_path),
                                       hardware=TS.hardware_label(spanned=spanned))
        return st, (st.get("models") or {}).get(key)

    def plan_reload_args(self, entry: dict, settings: dict, lead_x: list, packer_x: list) -> list:
        """Apply learned winners / one queued trial for reload options left on Auto.

        Pinned options (On/Off/8/4 in the panel) are untouched. Returns log lines.
        """
        if (settings.get("self_tune") == "off" or not entry.get("lead_path")
                or settings.get("guess_ahead") == "mtp"
                or settings.get("prompt_lookup") == "adaptive"):
            return []
        auto = [n for n in TS.RELOAD_TRIO if settings.get(n) == "auto"]
        if not auto:
            return []
        try:
            st, e = self._tuned_entry(entry["lead_path"], create=True)
            if not TS.kv_quant_supported(entry["lead_path"]):
                for b in (8, 4):   # attention sinks (gpt-oss): quantized KV crashes the load
                    TS.block_value(e, "kv_bits", b, "model can't use quantized KV (attention sinks)")
            sweep = getattr(self, "_sweep_load", None)
            plan = TS.plan_reload(e, auto, apply_pending=not bool(sweep))
            if sweep:
                for name, value in (sweep.get("force") or {}).items():
                    if name in auto:
                        plan["values"][name] = value
            self._reload_trial = plan.get("trial")
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
        from worker_ownership import matches
        if not matches(cmd,self.worker,port=self.lead_port) or not self.lead_healthy():
            return False
        for m in catalog.list_models():
            lp = m.get("lead_path")
            if lp and f"--model {lp}" in cmd:
                self._lead_path = lp
                cur = web_settings.from_args(cmd)
                is_split = (
                    "--split-role lead" in cmd
                    or "--split-role=lead" in cmd
                    or ("--split-peer" in cmd and "--split-role none" not in cmd
                        and "--split-role=none" not in cmd)
                )
                self._loaded_entry = dict(catalog.get_model(m["id"]) or m,
                                          run_mode="split" if is_split else "single")
                self._set(status="ready", model_id=m["id"], model_name=m["name"],
                          lead_pid=pid, settings=cur, page_settings=cur, split=is_split)
                try:
                    balance = json.loads((self.state_dir / "pipeline-balance.json").read_text())
                    if is_split and balance.get("lead_pid") == pid:
                        self._set(balance=balance)
                except (OSError, ValueError):
                    pass
                active = self.lead_active_settings() or {}
                if active.get("sweep_paused"):
                    self.sweep({"release": True})
                    self._note("released abandoned Optimize now live holds after web restart")
                self._note(f"adopted running lead (pid {pid}) after web restart")
                return True
        return False

    def _lead_log(self) -> Path:
        return self.state_dir / "lead.log"

    def _packer_log_remote(self) -> str:
        return "~/.caravan/web-ui/packer.log"

    @staticmethod
    def _remote_path(path):
        path = str(path)
        if path.startswith("~/"):
            return '"$HOME"/' + shlex.quote(path[2:])
        return shlex.quote(path)

    def _remote_stop_command(self, repo, marker, *, pid=None, port=None, listen=None):
        cmd = "python3 " + self._remote_path(str(repo).rstrip("/") + "/proxy/worker_ownership.py")
        cmd += " --worker " + self._remote_path(str(repo).rstrip("/") + "/agent/mlx_worker.py")
        cmd += " --pid-file " + self._remote_path(marker)
        if pid:
            cmd += " --pid " + str(int(pid))
        if port is not None:
            cmd += " --port " + str(int(port))
        if listen is not None:
            cmd += " --listen " + shlex.quote(listen)
        return cmd

    def _kill_lead(self) -> None:
        from worker_ownership import stop
        self._stop_tunnel()
        meta_path = self.state_dir / "remote-worker.json"
        remote = meta_path.is_file()
        if remote:
            meta = json.loads(meta_path.read_text())
            target = (meta.get("ssh") or "").strip()
            if target:
                cmd = self._remote_stop_command(meta.get("repo") or "~/cv3",
                    "~/.caravan/web-ui/remote-lead.pid", pid=meta.get("pid"), port=self.lead_port)
                r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, cmd],
                                   capture_output=True, text=True, timeout=25)
                if r.returncode:
                    raise RuntimeError("could not stop tracked remote worker: " + (r.stderr or ""))
            meta_path.unlink()
        if self._lead_proc is not None:
            stop(self.worker, pid=self._lead_proc.pid, port=self.lead_port)
        elif not remote:
            stop(self.worker, pid_file=self.state_dir / "lead.pid", port=self.lead_port)
        self._lead_proc = None
        self._worker_node = None

    def _ssh(self, remote_cmd: str, *, timeout: float = 60) -> subprocess.CompletedProcess:
        cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            self.packer_ssh, remote_cmd,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _assert_packer_unmanaged(self):
        script = ("import sys;from pathlib import Path;"
                  "sys.path.insert(0,str(Path('~/cv3').expanduser()/'agent'));"
                  "from service_config import managed_worker_port;"
                  f"reserved=managed_worker_port(Path.home(),{int(self.packer_peer.rsplit(':',1)[1])});"
                  "print('An auto-start service owns this packer; uninstall its job before using web-managed loads' if reserved else '');"
                  "sys.exit(42 if reserved else 0)")
        r = self._ssh("python3 -c " + shlex.quote(script),timeout=25)
        if r.returncode == 42:
            raise ManagedServiceError((r.stdout or "An auto-start service owns this packer")[-800:])
        if r.returncode:
            raise RuntimeError("could not stop tracked packer: ownership check failed: " + (r.stderr or r.stdout or "unknown error")[-800:])

    def _kill_packer(self) -> None:
        from web_pipeline import stop_pipeline
        if stop_pipeline(self):
            return
        # A fresh single-Mini install must not contact the author's lab peer.
        import web_nodes
        peers = [n for n in web_nodes.nodes_from_config() if n.get("role") != "lead"
                 and (n.get("ssh") or n.get("host")) == self.packer_ssh]
        if not peers:
            return
        self._assert_packer_unmanaged()
        cmd = self._remote_stop_command("~/cv3", "~/.caravan/web-ui/packer.pid",
                                        listen=self.packer_peer)
        r = self._ssh(cmd, timeout=25)
        if r.returncode:
            raise RuntimeError("could not stop tracked packer: " + (r.stderr or ""))

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


    def _node_is_local(self, node: Optional[dict]) -> bool:
        if not node:
            return True
        try:
            from web_nodes import is_local
            return is_local(node)
        except Exception:
            h = (node.get("host") or "").strip().lower()
            return h in ("local", "localhost", "127.0.0.1", "")

    def _resolve_worker_node(self, entry: dict, place: Optional[dict] = None) -> Optional[dict]:
        """Which Mini should run a single-Mini load. None → local lead."""
        place = place or entry.get("placement")
        if not place and entry.get("lead_path"):
            try:
                from placement import read_placement
                place = read_placement(entry["lead_path"])
            except Exception:
                place = None
        mode = (place or {}).get("mode")
        if mode == "all":
            return None  # prefer local lead
        if mode != "one":
            # Infer: if lead_path missing locally but held_on names a packer, use that.
            held = entry.get("held_on") or entry.get("worker_node_ids") or []
            if held and entry.get("lead_path"):
                # still local path present
                return None
            if held:
                place = {"mode": "one", "node_labels": list(held), "node_ids": list(held)}
            else:
                return None
        ids = [str(x).lower() for x in ((place or {}).get("node_ids") or [])]
        labels = [str(x).lower() for x in ((place or {}).get("node_labels") or [])]
        try:
            from web_nodes import nodes_from_config
            nodes = nodes_from_config()
        except Exception:
            nodes = []
        if not nodes:
            # Fallback: packer SSH target as exo2
            if any(x in ("exo2", "packer") for x in ids + labels):
                return {
                    "id": "exo2", "label": "EXO2", "role": "packer",
                    "host": self.packer_ssh, "ssh": self.packer_ssh,
                    "repo": "~/cv3",
                }
            return None
        for n in nodes:
            nid = str(n.get("id") or "").lower()
            lab = str(n.get("label") or "").lower()
            if nid in ids or lab in ids or nid in labels or lab in labels:
                if self._node_is_local(n) or (n.get("role") == "lead"):
                    return None
                return n
        # Match exo2 / packer aliases against non-lead nodes
        if any(x in ("exo2", "packer") for x in ids + labels):
            for n in nodes:
                if n.get("role") != "lead" and not self._node_is_local(n):
                    return n
        return None

    def _ssh_node(self, node: dict, cmd: str, timeout: float = 60):
        target = (node.get("ssh") or node.get("host") or self.packer_ssh or "").strip()
        if not target:
            raise RuntimeError("no ssh target for remote worker")
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, cmd],
            capture_output=True, text=True, timeout=timeout)

    def _stop_tunnel(self) -> None:
        proc = getattr(self, "_tunnel_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._tunnel_proc = None

    def _ensure_tunnel(self, node: dict) -> None:
        """Forward local lead_port → remote 127.0.0.1:lead_port so chat/health stay local."""
        self._stop_tunnel()
        target = (node.get("ssh") or node.get("host") or self.packer_ssh or "").strip()
        port = str(self.lead_port)
        # -N -L local:remote; ExitOnForwardFailure so we notice bind races.
        self._tunnel_proc = subprocess.Popen(
            ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
             "-o", "ServerAliveInterval=15", "-N",
             "-L", f"{port}:127.0.0.1:{port}", target],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        time.sleep(0.4)
        if self._tunnel_proc.poll() is not None:
            err = (self._tunnel_proc.stderr.read() if self._tunnel_proc.stderr else b"") or b""
            raise RuntimeError(f"ssh tunnel to {target} failed: {err.decode(errors='replace')[:300]}")

    def _start_remote_single(self, entry: dict, node: dict) -> int:
        """Run mlx_worker as a non-split HTTP server on a non-lead Mini; tunnel to it."""
        model = entry.get("lead_path") or entry.get("packer_path")
        if not model:
            raise RuntimeError("no model path for remote single-Mini load")
        remote_model = model
        repo = (node.get("repo") or "~/cv3").rstrip("/")
        filtered = []
        for a in getattr(self, "_extra_lead", []):
            if a in ("--split-keepalive", "--no-split-keepalive"):
                continue
            filtered.append(a)
        extra = " ".join(shlex.quote(a) for a in filtered)
        remote = (
            "mkdir -p ~/.caravan/web-ui; "
            "LPM=$(pmset -g 2>/dev/null | awk '/lowpowermode/{print $2}'); "
            "[[ \"$LPM\" == \"0\" || -z \"$LPM\" ]] || { echo REFUSE_LPM; exit 2; }; "
            + self._remote_stop_command(repo, "~/.caravan/web-ui/remote-lead.pid", port=self.lead_port) + "; "
            + f"nohup ~/.caravan/venvs/mlx/bin/python {repo}/agent/mlx_worker.py "
            f"--model {shlex.quote(remote_model)} "
            f"--host 127.0.0.1 --port {int(self.lead_port)} --split-role none "
            + (extra + " " if extra else "")
            + f"> ~/.caravan/web-ui/remote-lead.log 2>&1 & echo $! > ~/.caravan/web-ui/remote-lead.pid; "
            "cat ~/.caravan/web-ui/remote-lead.pid"
        )
        r = self._ssh_node(node, remote, timeout=45)
        if r.returncode != 0:
            raise RuntimeError(f"remote worker start failed: {(r.stderr or r.stdout or '')[:400]}")
        pid = None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
        if not pid:
            raise RuntimeError(f"remote worker did not print a pid: {(r.stdout or '')[:200]}")
        self._ensure_tunnel(node)
        self._lead_proc = None
        (self.state_dir / "lead.pid").write_text(str(pid))
        (self.state_dir / "remote-worker.json").write_text(json.dumps({
            "pid": pid, "node": node.get("id") or node.get("label"),
            "ssh": node.get("ssh") or node.get("host"),
            "model": remote_model, "repo": repo,
        }))
        return pid

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

    def _start_lead(self, entry: dict, *, split: bool = True) -> int:
        k = int(entry.get("packer_layers") or 24)
        log_path = self._lead_log()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate log.
        log_path.write_text("")
        args = [
            self.python, str(self.worker),
            "--model", entry["lead_path"],
            "--host", "127.0.0.1",
            "--port", str(self.lead_port),
        ]
        if split:
            args += [
                "--split-role", "lead",
                "--split-peer", self.packer_peer,
                "--split-packer-layers", str(k),
                "--split-draft-skip-first-load",
            ]
            if os.environ.get("CARAVAN_WEB_NO_DRAFT", "").strip() in ("1", "true", "yes"):
                args.append("--no-split-draft")
        else:
            # Explicit non-split (default is none, but say it for logs/ps).
            args += ["--split-role", "none"]
        extra = list(getattr(self, "_extra_lead", []))
        if not split:
            # Drop split-only flags from self-tune extras.
            filtered = []
            skip_next = False
            for a in extra:
                if skip_next:
                    skip_next = False
                    continue
                if a in ("--split-keepalive", "--no-split-keepalive"):
                    continue
                filtered.append(a)
            extra = filtered
        args += extra
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
        remote = bool(getattr(self, "_worker_node", None)) and not self._node_is_local(self._worker_node)
        while time.time() < deadline:
            if self._lead_proc and self._lead_proc.poll() is not None:
                tail = log_path.read_text(errors="replace")[-2000:] if log_path.exists() else ""
                raise RuntimeError(f"lead exited early (rc={self._lead_proc.returncode}): {tail}")
            if (not remote) and log_path.exists() and not getattr(self, "_quiet_lead_log", False):
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

    def sweep(self, body):
        """Control the selected worker through its existing local tunnel."""
        from urllib.request import Request, urlopen
        req = Request(f"http://127.0.0.1:{self.lead_port}/caravan/sweep",
                      data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=600) as response:
            return json.loads(response.read())

    def optimize_hardware(self):
        """Probe all participating nodes; no fixed two-Mini fingerprint."""
        import web_nodes
        cfg = web_nodes.nodes_from_config()
        snap = self.snapshot()
        entry = getattr(self, "_loaded_entry", None) or {}
        place = entry.get("placement") or {}
        chosen = set(place.get("node_ids") or place.get("nodes") or [])
        if not snap.get("split"):
            worker = self._worker_node
            cfg = [worker] if worker else [n for n in cfg if web_nodes.is_local(n)]
        elif chosen:
            cfg = [n for n in cfg if n.get("id") in chosen]
        else:
            # MLX currently supports lead + one packer; do not silently include
            # unrelated configured Minis. N-stage will supply placement ids.
            cfg = [n for n in cfg if web_nodes.is_local(n) or
                   (n.get("ssh") or n.get("host")) == self.packer_ssh]
        return [web_nodes.gather_node_stats(n, ssh_fn=web_nodes.make_ssh_fn(self)) for n in cfg]

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
