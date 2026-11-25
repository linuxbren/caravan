"""Start / stop the lead Mac and a configured SSH helper for the web UI.

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
from service_endpoints import RetryableReadinessError  # noqa: E402
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WORKER = REPO / "agent" / "mlx_worker.py"
DEFAULT_PY = str(Path("~/.caravan/venvs/mlx/bin/python").expanduser())
LEAD_PORT = int(os.environ.get("CARAVAN_WEB_LEAD_PORT", "8194"))
PACKER_PEER = catalog.DEFAULT_PACKER_PEER
PACKER_SSH = catalog.DEFAULT_PACKER_SSH
WEB_STATE_DIR = Path(os.environ.get(
    "CARAVAN_WEB_STATE", str(Path.home() / ".caravan" / "web-ui"))).expanduser()



# Words in worker output (English) that mean a progress line is a problem.
_PROBLEM_WORDS = re.compile(r"error|fail|Errno|No space|OSError", re.I)

class GgufLoadError(RuntimeError):
    """Short plain message for the page; full log tail in .detail."""
    def __init__(self, msg: str, detail: str = ""):
        super().__init__(msg)
        self.detail = detail


def gguf_friendly(err: Exception, peers: list) -> str:
    t = str(err)
    names = " + ".join(peers) or T("server.web_workers.the_other_mini")
    if "Failed to connect" in t or "tunnel" in t.lower() or "RPC handshake" in t:
        return T("server.web_workers.couldnt_reach_names_for_the_split", names=names)
    if "rpc-server" in t and "did not start" in t:
        return T("server.web_workers.couldnt_start_the_split_helper_on", names=names)
    if "out of memory" in t.lower() or "failed to allocate" in t.lower():
        return T("server.web_workers.not_enough_memory_for_this_placement")
    if "missing" in t.lower() or "not found" in t.lower():
        return t.split("\n")[0][:160]
    return T("server.web_workers.the_model_didnt_load_details_below")


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
        self._load_cancel = threading.Event()

    # ----- public ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self.state)
            s["progress"] = list(self.state["progress"])
        return s

    def _mac_name(self, node=None) -> str:
        """Friendly Mac name for user-facing load status. Never a hostname."""
        node = node if node is not None else getattr(self, "_worker_node", None)
        try:
            import web_nodes
            inv = web_nodes.nodes_from_config()
            return web_nodes.friendly_mac_label(
                node or {}, inventory=inv, node_count=len(inv) or 1)
        except Exception:
            role = ((node or {}).get("role") or "").lower()
            if role == "packer":
                return T("server.web_nodes.2nd_mac")
            if role == "lead":
                return T("server.web_nodes.1st_mac")
            return T("server.pairing.mac")

    def _note(self, msg: str, problem: bool = False, **codes) -> None:
        """Add a progress line. ``problem`` marks Caravan's own error lines
        so the page does not have to recognise their words (Day 32); worker
        output (always English) is still matched by _PROBLEM_WORDS. ``codes``
        (e.g. code="stage_ready", label=..., count=...) let the page react to
        a line without reading it."""
        try:
            from web_tunnels import plain_load_status
            msg = plain_load_status(msg, mac=self._mac_name())
        except Exception:
            pass
        problem = bool(problem or _PROBLEM_WORDS.search(str(msg)))
        with self._lock:
            self.state["progress"].append({"t": round(time.time(), 3), "msg": msg, "problem": problem, **codes})
            # keep last 40
            self.state["progress"] = self.state["progress"][-40:]

    def _set(self, **kw) -> None:
        ready = kw.get("status") == "ready"
        if ready:
            self._check_load_cancel()
            hook = getattr(self,"on_load_success",None)
            future = dict(self.snapshot(),**kw)
            if callable(hook) and getattr(self,"_loaded_entry",None) and not future.get("managed_service"):
                # Durable preference before advertising successful readiness.
                hook(dict(self._loaded_entry),future)
            self._check_load_cancel()
        with self._lock:
            self.state.update(kw)

    def _check_load_cancel(self):
        if getattr(self, "_load_cancel", None) and self._load_cancel.is_set():
            raise RuntimeError(T("server.web_workers.load_cancelled_by_user"))

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
                T("server.web_workers.auto_start_service_owns_model", name=plan['name']) +
                T("server.web_workers.on_the_lead_and_uninstall_its"))

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
                "note":T("server.web_workers.owned_by_launchd_use_the_service")}
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
        if reason in ("ui", "stop") and callable(getattr(self,"on_user_stop",None)):
            self.on_user_stop()
        self._load_cancel.set()
        self._set(status="stopping", error=None)
        self._note(T("server.web_workers.stopping_workers_reason", reason=reason))
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
            raise ValueError(T("server.web_workers.unknown_model_model_id", model_id=model_id))
        if entry.get("source") == "gguf":
            if not entry.get("lead_path"):
                raise FileNotFoundError(T("server.web_workers.gguf_file_not_on_the_lead", model_id=model_id))
            entry = dict(entry)
            entry["usable"] = True
            entry["available_lead"] = True
        # available_lead is local-path oriented; remote one-Mini placements set
        # usable/lead_path from the holding Mini instead.
        if not entry.get("available_lead") and not (
            entry.get("usable") and entry.get("lead_path")
            and (entry.get("placement") or {}).get("mode") in ("one", "all")
        ):
            raise FileNotFoundError(T("server.web_workers.model_not_on_this_mini_model", model_id=model_id))
        if self._switch_thread and self._switch_thread.is_alive():
            raise RuntimeError(T("server.web_workers.a_model_switch_is_already_in"))

        self._load_cancel = threading.Event()
        self._set(retryable=False, retry_kind=None)
        if entry.get("sharded"):
            # A same-ID Balance reload must not expose the old ready state
            # while its verified new placement is still being preflighted.
            self._set(status="starting_lead")
            self._note(T("server.web_workers.checking_each_macs_own_gguf_pieces"))
        def run():
            try:
                self._check_load_cancel()
                self._sweep_load = sweep
                self._do_switch(entry, settings)
            except GgufLoadError as e:
                # Cleaned up already; leave a sane idle state with a plain message.
                self._set(status="idle", model_id=None, model_name=None, lead_pid=None,
                          error=str(e), error_detail=e.detail)
                self._note(T("server.web_workers.load_failed_e", e=str(e)), problem=True)
            except Exception as e:  # noqa: BLE001 — surface to UI
                if self._load_cancel.is_set():
                    for cleanup in (self._kill_gguf,self._kill_lead,self._kill_packer):
                        try:cleanup()
                        except Exception as ex:self._note(T("server.web_workers.cancel_cleanup_ex", ex=ex))
                    self._set(status="idle",model_id=None,model_name=None,lead_pid=None,packer_pid=None,error=None,retryable=False,retry_kind=None)
                    self._note(T("server.web_workers.load_cancelled_next_login_will_not"))
                elif isinstance(e, RetryableReadinessError):
                    self._set(status="error", error=str(e), retryable=True, retry_kind=e.kind)
                    self._note(f"error: {e}")
                else:
                    import logging as _log
                    from web_tunnels import TunnelError, plain_tunnel_error, plain_load_status
                    if isinstance(e, TunnelError):
                        plain = e.plain
                        _log.getLogger("caravan.tunnel").error(
                            "load tunnel failed: %s", e.detail or e)
                    else:
                        raw = f"{type(e).__name__}: {e}"
                        _log.getLogger("caravan.tunnel").error("load failed: %s", raw)
                        low = raw.lower()
                        if "tunnel" in low or "already in use" in low or "forwarding" in low:
                            plain = plain_tunnel_error(raw, mac=self._mac_name())
                        else:
                            plain = plain_load_status(raw, mac=self._mac_name()) or raw
                    self._set(status="error", error=plain, error_detail=None, retryable=False, retry_kind=None)
                    self._note("error: " + plain)
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
        fallback_notice = None
        try:
            from web_kv_probe import apply_saved_4_fallback, block_four_if_disallowed
            settings, fallback_notice = apply_saved_4_fallback(self, entry, settings)
            if fallback_notice:
                page = dict(page)
                page["kv_bits"] = settings.get("kv_bits") or "auto"
                try:
                    from web_kv_probe import write_last_model
                    write_last_model(self, page["kv_bits"])
                except Exception:
                    pass
            block_four_if_disallowed(self, entry)
        except Exception:
            pass
        self._set(settings=settings, page_settings=page, from_file=from_file,
                  config_errors=cfg.get("errors") or [],
                  quality_notice=fallback_notice)
        for err in cfg.get("errors") or []:
            self._note(T("server.web_workers.config_toml_err", err=err))
        if from_file:
            self._note(T("server.web_workers.config_toml_pins_v", v=T.join(f"{k}={v}" for k, v in from_file.items())))
        if fallback_notice:
            self._note(fallback_notice)
        try:
            self._load_once(entry, settings)
        except Exception as e:  # noqa: BLE001
            trial = getattr(self, "_reload_trial", None)
            if not trial:
                raise
            # A self-tune reload trial broke the load: never try that value
            # again for this model, go back to the winner and load that.
            why = f"{type(e).__name__}: {str(e)[-200:]}"
            self._note(T("server.web_workers.self_tuning_name_reload_value_label", name=TS.RELOAD_LABEL.get(trial['name'], trial['name']), reload_value_label=TS.reload_value_label(trial['name'], trial['value'])), problem=True)
            try:
                st, ent = self._tuned_entry(entry["lead_path"], create=True)
                TS.block_value(ent, trial["name"], trial["value"], why)
                ent["reload_trial"] = None
                TS.save_store(st, self.tuned_path)
            except (OSError, ValueError) as ex:
                self._note(T("server.web_workers.could_not_record_rejected_trial_ex", ex=ex))
            self._load_once(entry, settings)
        # After a successful load at 4 or 8, a short known-answer probe
        # reverts to 16 if the model gives a wrong answer. The revert is
        # a second _load_once (not switch), so this thread is not nested.
        try:
            from web_kv_probe import maybe_probe, finish_probe_reload
            result = maybe_probe(self)
            if result and result.get("need_reload"):
                page16 = dict(page)
                page16["kv_bits"] = "16"
                settings16 = dict(settings)
                settings16["kv_bits"] = "16"
                self._set(page_settings=page16, settings=settings16,
                          quality_notice=result.get("notice"))
                if result.get("notice"):
                    self._note(result["notice"])
                self._load_once(entry, settings16)
                finish_probe_reload(self, result)
            elif fallback_notice:
                self._set(quality_notice=fallback_notice)
        except Exception as ex:
            self._kv_probe_guard = False
            self._note(T("server.web_workers.memory_check_skipped_ex", ex=ex))

    def _load_once(self, entry: dict, settings: dict) -> None:
        self._check_load_cancel()
        self._reload_trial = None
        if not self.check_lpm():
            raise RuntimeError(T("server.web_workers.low_power_mode_is_on_turn"))
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
        self._note(T("server.web_workers.switching_to_name_run_mode", name=entry['name'], run_mode=run_mode))
        problems = self.preflight_load(entry)
        if problems:
            raise FileNotFoundError(T.join(problems, "clause"))
        if settings.get("guess_ahead") == "mtp" and (run_mode != "single" or not entry.get("native_mtp_available")):
            raise ValueError(T("server.web_workers.native_mtp_needs_a_single_mini"))
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
                   + (f" -> {' '.join(lead_x)}" if lead_x else T("server.web_workers.all_auto")))
        self._kill_gguf()
        self._kill_lead()
        self._kill_packer()
        time.sleep(1.5)

        if run_mode == "split":
            packer_path = self._resolve_packer_path(entry)
            self._set(status="starting_packer", packer_pid=None)
            self._note(T("server.web_workers.starting_helper_on_the_2nd_mac"))
            packer_pid = self._start_packer(entry, packer_path)
            self._set(packer_pid=packer_pid)
            self._wait_packer_ready(timeout=300)
            self._set(status="starting_lead")
            self._note(T("server.web_workers.starting_lead_on_the_1st_mac"))
            lead_pid = self._start_lead(entry, split=True)
        else:
            self._set(status="starting_lead", packer_pid=None)
            node = self._resolve_worker_node(entry, place=entry.get("placement"))
            self._worker_node = node
            if node and not self._node_is_local(node):
                self._note(T("server.web_workers.starting_single_mini_worker_on_mac", mac_name=self._mac_name(node)))
                lead_pid = self._start_remote_single(entry, node)
            else:
                self._note(T("server.web_workers.starting_model_worker_on_this_mac"))
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
        mode = (place or {}).get("mode")
        def _with_ram(grp):
            return [dict(n, **{k: v for k, v in (live.get(n.get("id")) or {}).items() if k == "ram"})
                    for n in grp]
        if not want:
            return _with_ram(lead)
        picked = [n for n in nodes if str(n.get("id")).lower() in want
                  or str(n.get("label") or "").lower() in want]
        if mode in ("one", "all"):
            # Honor the saved one-Mini / copy-all choice. Never add the lead
            # just to turn a one-Mini load into a split.
            if mode == "all":
                prefer = [n for n in picked if n.get("role") == "lead"] or lead
                return _with_ram(prefer[:1] or picked[:1])
            return _with_ram(picked)
        # Split: only the Minis named in the placement, lead first if present.
        # Do not inject an unchosen lead.
        picked.sort(key=lambda n: 0 if n.get("role") == "lead" else 1)
        return _with_ram(picked)

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
                raise GgufLoadError(T("server.web_workers.load_stopped_2"), f"{type(e).__name__}: {e}"[-4000:]) from e
            raise GgufLoadError(gguf_friendly(e, peers), f"{type(e).__name__}: {e}"[-4000:]) from e
        finally:
            self._quiet_lead_log = False

    def _load_gguf_inner(self, entry: dict, settings: dict) -> None:
        import gguf_split as G
        if entry.get('sharded'):
            import web_gguf_shares
            return web_gguf_shares.load(self,entry,settings)
        place = entry.get("placement") or {}
        if not place and entry.get("lead_path"):
            try:
                from placement import read_placement
                place = read_placement(Path(entry["lead_path"]).expanduser().parent) or {}
            except Exception:  # noqa: BLE001
                place = {}
        nodes = self._gguf_nodes(place)
        place_mode = (place or {}).get("mode")
        # Placement mode wins. A one-Mini choice on a remote Mac is still
        # single (run llama-server there), not a split with the lead.
        if place_mode in ("one", "all") or len(nodes) <= 1:
            mode = "single"
            peers = []
        else:
            mode = "split"
            peers = [n for n in nodes if not self._node_is_local(n)]
        # Day 30: friendly Mac names in load notes (a hostname label used to
        # be scrubbed to nothing: "split across My Mac + ").
        def _friendly(n):
            if self._node_is_local(n):
                return n.get("label") or T("server.gguf_split.this_mac")
            try:
                return self._mac_name(n) or n.get("label") or n.get("id")
            except Exception:  # noqa: BLE001
                return n.get("label") or n.get("id")
        label = " + ".join(_friendly(n) for n in nodes)
        gblock = {"nodes": [n.get("id") for n in nodes], "labels": [n.get("label") for n in nodes],
                  "mode": mode}
        self._set(status="stopping", error=None, error_detail=None, model_id=entry["id"],
                  model_name=entry["name"], progress=[], split=bool(peers), backend="llama", gguf=gblock)
        self._note(T("server.web_workers.switching_to_name_gguf_llama_cpp", name=entry['name'], v='split across ' if peers else 'on ', label=label))
        path = Path(entry["lead_path"]).expanduser()
        single_node = nodes[0] if mode == "single" and nodes else None
        remote_single = bool(single_node and not self._node_is_local(single_node))
        if remote_single:
            if not self._remote_gguf_exists(single_node, path):
                mac = _friendly(single_node)
                raise FileNotFoundError(T("server.web_workers.gguf_file_missing_on_mac", mac=mac))
        elif not path.is_file():
            raise FileNotFoundError(T("server.web_workers.gguf_file_missing_on_the_lead", path=path))
        binp = Path(G.LLAMA_BIN).expanduser() / "llama-server"
        if not binp.is_file():
            raise FileNotFoundError(T("server.web_workers.llama_server_not_found_at_binp", binp=binp))
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
            name = _friendly(n)
            target = (n.get("ssh") or n.get("host") or "").strip()
            if not target:
                raise RuntimeError(T("server.web_workers.no_ssh_target_for_name", name=name, id=n.get('id')))
            self._note(T("server.web_workers.starting_rpc_server_on_name_127", name=name, rpc_port=G.RPC_PORT))
            r = self._ssh_node(n, G.rpc_start_command(), timeout=40)
            pid = G.parse_pid(r.stdout)
            if not pid:
                raise RuntimeError(T("server.web_workers.rpc_server_on_name_did_not", name=name, v=(r.stdout or '')[-300:], v2=(r.stderr or '')[-200:]))
            meta["peers"].append({"id": n.get("id"), "label": name, "ssh": target, "pid": pid})
            self._write_gguf_meta(meta)
            lp = G.tunnel_port(i)
            # Day 28 tuning fix 2: the split's model traffic goes over the
            # Thunderbolt link when this Mac has one to the peer. It used to
            # follow the peer's .local name, which can resolve to the home
            # network (Wi-Fi: 15 ms, jittery), and writing speed on 2 Macs
            # swung between 19 and 11 tok/s from one load to the next.
            tun, route = self._open_tunnel(target, lp, node=n)
            meta["tunnels"].append({"pid": tun.pid, "port": lp, "ssh": target, "id": n.get("id"),
                                    "route": route, "args": list(getattr(tun, "args", None) or [])})
            self._write_gguf_meta(meta)
            if not G.wait_port(lp, proc=tun, timeout=10) and route != "network":
                self._note(T("server.web_workers.route_route_to_name_did_not", route=route, name=name))
                import peer_route as PR
                PR.forget(target)
                try:
                    tun.terminate()
                except Exception:  # noqa: BLE001
                    pass
                tun, route = self._open_tunnel(target, lp)
                meta["tunnels"][-1].update(pid=tun.pid, route=route,
                                           args=list(getattr(tun, "args", None) or []))
                self._write_gguf_meta(meta)
                if not G.wait_port(lp, proc=tun, timeout=10):
                    err = (tun.stderr.read() if tun.poll() is not None and tun.stderr else b"") or b""
                    raise RuntimeError(T("server.web_workers.ssh_tunnel_to_name_failed_decode", name=name, decode=err.decode(errors='replace')[:300]))
            elif tun.poll() is not None or not G.wait_port(lp, proc=tun, timeout=1):
                err = (tun.stderr.read() if tun.poll() is not None and tun.stderr else b"") or b""
                raise RuntimeError(T("server.web_workers.ssh_tunnel_to_name_failed_decode", name=name, decode=err.decode(errors='replace')[:300]))
            gblock.setdefault("routes", []).append(route)
            self._set(gguf=gblock)
            rpc.append(f"127.0.0.1:{lp}")
            self._note(T("server.web_workers.rpc_server_on_name_up_pid", name=name, pid=pid, lp=lp))
        self._check_cancel()
        free = [self._free_gb(n) for n in nodes] if peers else [None]
        shares = entry.get('gguf_shares') or (G.shares_from_free(free) if peers else [1])
        if entry.get('gguf_shares'):
            import math
            if len(shares) != len(nodes) or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in shares):
                raise ValueError(T("server.web_workers.invalid_explicit_gguf_shares"))
        if peers:
            self._note(T("server.web_workers.free_ram_now_v_split_v2", v=T.join(
                T("server.web_workers.name_free_gb", name=_friendly(n), gb=f if f is not None else '?') for n, f in zip(nodes, free)), v2=":".join(str(x) for x in shares), v3="" if all(f for f in free) else T("server.web_workers.equal_free_ram_unknown")))
        meta["shares"] = shares
        gblock["shares"] = list(shares)
        self._set(gguf=gblock)  # Report the actual applied shares for no-op/reload UI checks.
        self._seed_gguf_peers(entry, path, shares, peers, meta)
        try:
            import gguf_tune as GT
            import web_settings as WS
            try:
                page = self.snapshot().get("settings") or {}
            except Exception:  # noqa: BLE001
                page = {}
            if isinstance(entry.get("tune_override"), dict):
                tune = dict(entry["tune_override"])
                # Day 30: a window saved from an Auto load (restore, Update
                # now, Self-tuning) is sized again, so it can use the full
                # window this version allows.
                if tune.get("ctx") is not None and str(page.get("chat_window") or "auto") == "auto":
                    tune["ctx_auto"] = True
            else:
                tune = WS.apply_gguf_settings(
                    GT.best_tune(path, 1 + len(rpc)), page, model_path=path,
                )
            # Day 30: only the settings you pinned may shorten the window.
            import gguf_self_tune as GST
            pk = sorted(GST.pinned_knobs(page))
            if pk:
                tune["pinned_knobs"] = pk
            else:
                tune.pop("pinned_knobs", None)
        except Exception:  # noqa: BLE001 - tuning is optional
            tune = {}
        if tune:
            self._note(T("server.web_workers.using_saved_gguf_settings"))
        t0 = time.time()
        for attempt in (1, 2):
            args = G.llama_args(str(path), port=self.lead_port, peers=rpc, shares=shares, tune=tune)
            launch = G.resolve_launch(str(path), tune=tune, n_devices=1 + len(rpc))
            if launch:
                if launch.get("helper_fits") is False and tune.get("guess_ahead") == "on":
                    self._note(T("server.web_workers.guess_ahead_helper_left_off_it"))
                    tune = dict(tune, guess_ahead="off", helper_failed=True)
                    tune.pop("draft_path", None)
                lighter = launch.get("lighter") or {}
                if lighter and attempt == 1:
                    words = {"cache_type": T("server.web_workers.8_bit_chat_memory"), "flash_attn": T("server.web_workers.flash_attention_on"),
                             "ubatch": T("server.web_workers.prompt_batch_ubatch", ubatch=lighter.get('ubatch'))}
                    self._note(T("server.web_workers.kept_the_full_context_of_ctx", ctx=str(launch["ctx"]), v=T.join(words.get(k, k) for k in lighter)))
                tune = dict(tune, ctx=launch["ctx"], n_slots=launch["n_slots"],
                            ctx_auto=bool(launch.get("ctx_auto")), **lighter)
            if attempt == 1 and tune.get("guess_ahead") == "on" and tune.get("draft_path"):
                # Day 33 (v0.9.15): say which helper is in use and why.
                try:
                    import guesser_choice as GC
                    g = GC.gguf_source(tune.get("draft_path"), main_name=Path(str(path)).name)
                    if g:
                        self._note(g["why"])
                except Exception:  # noqa: BLE001  (a label never blocks a load)
                    pass
            # Day 30: report the chat memory llama-server really got. A boot
            # restore's saved tune has no cache_type, so the Settings chip
            # showed no Memory compression after a power-loss restore.
            if "-ctk" in args:
                try:
                    launch = dict(launch or {}, cache_type=args[args.index("-ctk") + 1])
                except IndexError:
                    pass
            if "--slot-save-path" in args:
                try:
                    Path(args[args.index("--slot-save-path") + 1]).mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
            self._set(status="starting_lead", packer_pid=None)
            seeded = bool(meta.get("seed"))
            if not rpc:
                self._note(T("server.web_workers.starting_llama_server_on_the_lead"))
            elif meta.get("file_mode") == "balance-verified-peer-cache":
                self._note(T("server.web_workers.starting_llama_server_using_verified_peer"))
            elif seeded:
                self._note(T("server.web_workers.starting_llama_server_on_the_lead_2"))
            else:
                self._note(T("server.web_workers.starting_llama_server_on_the_lead_3"))
            log_path = self._lead_log()
            log_path.write_text("")
            if remote_single:
                self._worker_node = single_node
                pid = self._start_remote_gguf_single(single_node, args, path)
                self._lead_proc = None
                meta["lead_pid"] = pid
                meta["remote_node"] = single_node.get("id") or single_node.get("label")
            else:
                lf = open(log_path, "ab", buffering=0)
                self._worker_node = None
                self._lead_proc = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT,
                                                   start_new_session=True)
                meta["lead_pid"] = self._lead_proc.pid
            self._write_gguf_meta(meta)
            self._set(lead_pid=meta["lead_pid"])
            self._wait_lead_ready(timeout=1200)
            self._check_cancel()
            # Day 28 tuning fix: "health ok" is not enough. A helper that ran
            # out of GPU memory left a server that answered /health but failed
            # every reply. Ask for one tiny reply before saying ready.
            err = self._gguf_first_reply_error()
            if not err:
                break
            spec_on = tune.get("guess_ahead") == "on" or tune.get("prompt_lookup") == "on"
            self._stop_gguf_lead()
            if attempt == 1 and spec_on and not entry.get("strict_tune"):
                self._note(T("server.web_workers.first_test_reply_failed_with_speedups", err=err[:160]))
                if tune.get("guess_ahead") == "on":
                    try:
                        import gguf_tune as GT
                        GT.record_helper_failure(path, 1 + len(rpc), err)
                    except Exception:  # noqa: BLE001
                        pass
                tune = dict(tune, guess_ahead="off", prompt_lookup="off", helper_failed=True)
                tune.pop("draft_path", None)
                continue
            raise RuntimeError(T("server.web_workers.the_model_loaded_but_its_first", err=err[:500]))
        self._note(T("server.web_workers.loaded_in_v_s", v=time.time() - t0))
        # GGUF Optimize now reads this (it refused "needs a GGUF model loaded" before).
        self._loaded_entry = dict({k: v for k, v in entry.items() if k not in ("tune_override", "strict_tune")},
                                  gguf_shares=shares, _loaded_tune=tune,
                                  _launch=launch if launch else None)
        # Day 28: keep the entry so a web restart (Update now) can adopt it.
        try:
            meta["entry"] = json.loads(json.dumps(self._loaded_entry, default=str))
            self._write_gguf_meta(meta)
        except (TypeError, ValueError, OSError):
            pass
        self._set(status="ready", split=bool(peers))
        self._note("ready")
        self._start_gguf_watch(meta)

    def _seed_gguf_peers(self, entry, path, shares, peers, meta):
        import gguf_split as G
        # A fresh Balance reload has already checked each peer's assigned files.
        # Do not scan a legacy full peer GGUF or seed its padded extra layers.
        if entry.get("gguf_peer_files_ready") is True:
            meta["file_mode"] = "balance-verified-peer-cache"
            self._note(T("server.web_workers.using_each_minis_verified_assigned_tensor"))
            return
        for i, n in enumerate(peers):
            # GGUF stage 2: a peer with its own copy fills its rpc cache from disk.
            self._check_cancel()
            name = n.get("label") or n.get("id")
            try:  # Day 30: friendly name in notes, never a hostname
                who = self._mac_name(n) or name
            except Exception:  # noqa: BLE001
                who = name
            try:
                r = self._ssh_node(n, G.seed_command(path.name, path.stat().st_size, shares, i + 1,
                                                     repo=n.get("repo") or "~/.caravan/src/caravan"), timeout=1800)
                rep = G.parse_seed(r.stdout)
            except Exception as e:  # noqa: BLE001 - stage 2 is an optimisation only
                rep, r = None, None
                self._note(T("server.web_workers.who_local_seed_skipped_e", who=who, e=e))
            if rep:
                meta.setdefault("seed", {})[n.get("id") or name] = rep
                self._note(T("server.web_workers.who_loads_its_share_from_its", who=who, tensors=rep['tensors'], v=rep['bytes'] / 1e9, new=rep['new'], have=rep['have'], s=rep['s']))
            elif r is not None:
                self._note(T("server.web_workers.who_no_complete_local_name_existing", who=who, name=path.name))

    def _check_cancel(self):
        self._check_load_cancel()
        if getattr(self, "_gguf_cancel", False):
            raise RuntimeError(T("server.web_workers.load_stopped"))

    def _write_gguf_meta(self, meta: dict) -> None:
        self._gguf_meta_path().write_text(json.dumps(meta))

    def _open_tunnel(self, target: str, port: int, node: Optional[dict] = None):
        """(process, route). Link-order fix: the tunnel goes over the first
        working link in the fixed order Thunderbolt > wired Ethernet > Wi-Fi >
        other (peer_route.pick, re-checked on every load). route is that kind,
        or "network" when nothing could be checked (configured SSH name)."""
        import gguf_split as G
        import peer_route as PR
        args, route = None, "network"
        if node is not None:
            name = (node or {}).get("label") or (node or {}).get("id") or target
            try:  # Day 30: friendly name in the note, never a hostname
                name = self._mac_name(node) or name
            except Exception:  # noqa: BLE001
                pass
            # Day 30: right after a power loss Thunderbolt comes up after
            # Wi-Fi. If it worked to this Mac before, wait up to a minute
            # for it (re-reading the new link-local addresses each try).
            noted = {"at": -99.0}

            def _tb_wait(waited, limit, _name=name):
                self._check_cancel()
                if waited - noted["at"] >= 15:
                    noted["at"] = waited
                    self._note(T("server.web_workers.waiting_for_the_thunderbolt_link_to", name=_name, waited=int(waited), limit=int(limit)))
            picked = PR.route_for(target, fresh=True, label=name, wait_thunderbolt=True, on_wait=_tb_wait)
            if picked is not None:
                if picked.get("warning"):
                    self._note(picked["warning"])
                opts = PR.host_opts(target, picked.get("address"))
                if opts:
                    args = G.ssh_tunnel_args(target, port)
                    args[1:1] = opts + ["-o", "StrictHostKeyChecking=yes"]
                    route = picked["kind"]
                    self._note(T("server.web_workers.link_to_name_describe", name=name, describe=PR.describe(picked)))
        if args is None and node and str(node.get("peer") or "").startswith("ssh+tb://"):
            try:
                import web_gguf_shares
                args = web_gguf_shares.tunnel_args(dict(node, ssh=target), port, pick=False)
                route = "thunderbolt" if any(str(a).startswith("HostName=") for a in args) else "network"
            except Exception as ex:  # noqa: BLE001 - fall back to the plain route
                self._note(T("server.web_workers.thunderbolt_route_not_available", ex=str(ex)[:120]))
                args = None
        if args is None:
            args, route = G.ssh_tunnel_args(target, port), "network"
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, start_new_session=True)
        return proc, route

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
                    msg = (T("server.web_workers.lost_v_during_the_split_load", v=' + '.join(peers) or 'a Mini')
                           if peers else T("server.web_workers.llama_server_stopped_load_the_model"))
                else:
                    msg = T("server.web_workers.llama_server_stopped_load_the_model")
                self._gguf_watch_token = None
                try:
                    self._kill_gguf()
                except Exception as e:  # noqa: BLE001
                    self._note(f"cleanup: {e}")
                self._set(status="idle", model_id=None, model_name=None, lead_pid=None,
                          split=False, error=msg, error_detail=tail[-2500:])
                self._note(T("server.web_workers.load_failed_msg", msg=msg), problem=True)
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
            tun = (subprocess.Popen(t['args'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True) if t.get('args') else self._open_tunnel(t["ssh"], t["port"])[0])  # only the recorded route
            t["pid"] = tun.pid
            G.wait_port(t["port"], proc=tun, timeout=10)
            self._note(T("server.web_workers.reopened_tunnel_127_0_0_1", port=t['port'], id=t.get('id')))
        self._write_gguf_meta(meta)
        gb = meta.get("gguf") or {}
        # Day 28: gguf.json never held an "entry", so after Update now (a web
        # restart) the adopted GGUF model had no _loaded_entry. Auto-tune then
        # answered 409 "needs a GGUF model loaded" and Reset could not clear
        # the model's saved GGUF results. Rebuild the entry from the file.
        self._loaded_entry = self._adopted_gguf_entry(meta)
        self._set(status="ready", model_id=meta.get("id"), model_name=meta.get("name"),
                  lead_pid=pid, split=gb.get("mode") == "split", backend="llama", gguf=gb,
                  error=None, error_detail=None)
        self._note(T.plural("server.web_workers.adopted_llama_server_tunnels", len(meta.get('tunnels') or []), pid=pid))
        self._start_gguf_watch(meta)
        return True

    @staticmethod
    def _adopted_gguf_entry(meta: dict) -> dict:
        """The catalog row for the GGUF model recorded in gguf.json."""
        if isinstance(meta.get("entry"), dict) and meta["entry"].get("source") == "gguf":
            return dict(meta["entry"])
        entry = None
        try:
            entry = catalog.gguf_entry(meta.get("id") or "")
        except Exception:  # noqa: BLE001 - fall back to gguf.json fields
            entry = None
        if not entry or (meta.get("model") and str(Path(entry.get("lead_path") or "").expanduser())
                         != str(Path(meta["model"]).expanduser())):
            entry = {"id": meta.get("id") or "", "name": meta.get("name") or "",
                     "hf": meta.get("id") or "", "source": "gguf", "backend": "llama",
                     "lead_path": meta.get("model") or "", "usable": True,
                     "available_lead": True}
        if meta.get("shares") and not entry.get("gguf_shares"):
            entry = dict(entry, gguf_shares=list(meta["shares"]))
        return entry

    def _gguf_first_reply_error(self, timeout: float = 180.0):
        """None when llama-server writes a short reply, else a short reason."""
        import urllib.request
        body = json.dumps({"messages": [{"role": "user", "content": "Reply with the word ready."}],
                           "max_tokens": 8, "temperature": 0, "stream": False}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.lead_port}/v1/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode() or "{}")
        except Exception as e:  # noqa: BLE001
            detail = ""
            try:
                detail = e.read().decode(errors="replace")[:300]  # HTTPError body
            except Exception:  # noqa: BLE001
                pass
            return f"{type(e).__name__}: {e} {detail}".strip()
        if isinstance(d, dict) and d.get("error"):
            return json.dumps(d["error"])[:300]
        if not isinstance(d, dict) or not d.get("choices"):
            return T("server.web_workers.no_reply")
        return None

    def _stop_gguf_lead(self) -> None:
        """Stop just this llama-server (peers' rpc-servers and tunnels stay up)."""
        proc = self._lead_proc
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1.0)

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
            if p.get('sharded'):
                import web_gguf_shares
                web_gguf_shares.stop_peer(self,p)
                continue
            target = p.get("ssh")
            if not target:
                continue
            try:
                import peer_route as PR
                r = PR.run_ssh(target, G.rpc_stop_command(), "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                               timeout=30, run=subprocess.run)
                if r.returncode:
                    self._note(T("server.web_workers.could_not_stop_rpc_server_on", id=p.get('id'), v=(r.stderr or '')[:200]))
            except subprocess.SubprocessError as e:
                self._note(T("server.web_workers.could_not_stop_rpc_server_on_2", id=p.get('id'), e=e))
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
            label = remote_node.get("label") or remote_node.get("id") or T("server.web_workers.remote_mini")
            if not lead:
                problems.append(T("server.web_workers.model_folder_not_found_on_label", label=label))
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
                        problems.append(T("server.web_workers.model_missing_on_label_lead", label=label, lead=lead))
                except Exception as e:
                    problems.append(T("server.web_workers.cant_reach_label_to_check_model", label=label, e=e))
        elif not lead:
            problems.append(T("server.web_workers.model_folder_not_found_on_this"))
        else:
            lp = Path(lead).expanduser()
            if not lp.is_dir():
                problems.append(T("server.web_workers.model_folder_missing_on_the_lead", lead=lead))
            elif not (lp / "config.json").is_file():
                problems.append(T("server.web_workers.config_json_missing_in_lead", lead=lead))
            else:
                try:
                    from mlx_arch import architecture_status
                    arch = architecture_status(lp)
                    if not arch.get("supported"):
                        problems.append(arch.get("reason") or T("server.web_catalog.unsupported_architecture"))
                    elif arch.get("remapped"):
                        self._note("architecture: " + (arch.get("reason") or "remapped"))
                except Exception:
                    pass
                # Need at least one weight file for single / lead
                has_w = any(lp.glob("*.safetensors")) or (lp / "model.safetensors.index.json").is_file()
                if not has_w:
                    problems.append(T("server.web_workers.no_weight_files_in_lead", lead=lead))
        if run_mode == "split":
            # Packer must have a tree — cheap existence check (same as resolve).
            try:
                self._resolve_packer_path(entry)
                self._assert_packer_unmanaged()
            except FileNotFoundError as e:
                problems.append(
                    T("server.web_workers.model_is_not_on_the_helper", e=e)
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
            try:
                import kv_quality as K
                if not K.allows_memory_compression_4(model_dir=entry["lead_path"]):
                    TS.block_value(e, "kv_bits", 4,
                                   "Memory compression 4 is not available on this model")
            except Exception:
                pass
            sweep = getattr(self, "_sweep_load", None)
            plan = TS.plan_reload(e, auto, apply_pending=not bool(sweep))
            if sweep:
                for name, value in (sweep.get("force") or {}).items():
                    if name in auto:
                        plan["values"][name] = value
            self._reload_trial = plan.get("trial")
            TS.save_store(st, self.tuned_path)
        except (OSError, ValueError) as ex:
            return [T("server.web_workers.reload_plan_skipped_ex", ex=ex)]
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
        from web_pipeline import adopted_entry
        owned = adopted_entry(self, cmd, pid)
        candidates = ([owned] if owned else []) + catalog.list_models()
        for m in candidates:
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
                # A default-root row can share the ID with this isolated store.
                # Never replace a validated owned pipeline with that other path.
                self._loaded_entry = dict(m if m is owned else (catalog.get_model(m["id"]) or m),
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
                    self._note(T("server.web_workers.released_abandoned_optimize_now_live_holds"))
                self._note(T("server.web_workers.adopted_running_lead_pid_pid_after", pid=pid))
                self._sync_learn_flag()
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
                cmd = self._remote_stop_command(meta.get("repo") or "~/.caravan/src/caravan",
                    "~/.caravan/web-ui/remote-lead.pid", pid=meta.get("pid"), port=self.lead_port)
                import peer_route as PR
                r = PR.run_ssh(target, cmd, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                               timeout=25, run=subprocess.run)
                if r.returncode:
                    raise RuntimeError(T("server.web_workers.could_not_stop_tracked_remote_worker", v=r.stderr or ""))
            meta_path.unlink()
        if self._lead_proc is not None:
            stop(self.worker, pid=self._lead_proc.pid, port=self.lead_port)
        elif not remote:
            stop(self.worker, pid_file=self.state_dir / "lead.pid", port=self.lead_port)
        self._lead_proc = None
        self._worker_node = None

    def _ssh(self, remote_cmd: str, *, timeout: float = 60) -> subprocess.CompletedProcess:
        import peer_route as PR
        return PR.run_ssh(self.packer_ssh, remote_cmd, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                          "-o", "StrictHostKeyChecking=accept-new", timeout=timeout, run=subprocess.run)

    def _assert_packer_unmanaged(self):
        script = ("import sys;from pathlib import Path;"
                  "sys.path.insert(0,str(Path('~/.caravan/src/caravan').expanduser()/'agent'));"
                  "from service_config import managed_worker_port;"
                  f"reserved=managed_worker_port(Path.home(),{int(self.packer_peer.rsplit(':',1)[1])});"
                  "print('An auto-start service owns this packer; uninstall its job before using web-managed loads' if reserved else '');"
                  "sys.exit(42 if reserved else 0)")
        r = self._ssh("python3 -c " + shlex.quote(script),timeout=25)
        if r.returncode == 42:
            raise ManagedServiceError((r.stdout or T("server.web_workers.auto_start_service_owns_packer"))[-800:])
        if r.returncode:
            raise RuntimeError(T("server.web_workers.could_not_stop_tracked_packer_ownership", v=(r.stderr or r.stdout or "unknown error")[-800:]))

    def _kill_packer(self) -> None:
        from web_pipeline import stop_pipeline
        if stop_pipeline(self):
            return
        # A fresh single-Mini install, or a separate N-stage topology on the
        # same host, must not clean up the legacy default peer's worker.
        import web_nodes
        peers = [n for n in web_nodes.nodes_from_config() if n.get("role") != "lead"
                 and (n.get("ssh") or n.get("host")) == self.packer_ssh
                 and self.packer_peer in (n.get("peer"), n.get("listen"))]
        if not peers:
            return
        self._assert_packer_unmanaged()
        cmd = self._remote_stop_command("~/.caravan/src/caravan", "~/.caravan/web-ui/packer.pid",
                                        listen=self.packer_peer)
        r = self._ssh(cmd, timeout=25)
        if r.returncode:
            raise RuntimeError(T("server.web_workers.could_not_stop_tracked_packer_v", v=r.stderr or ""))

    def _resolve_packer_path(self, entry: dict) -> str:
        # Ask the configured helper which candidate exists.
        cands = entry.get("packer_path_candidates") or [entry.get("packer_path")]
        cands = [c for c in cands if c]
        if not cands:
            raise FileNotFoundError(T("server.web_workers.no_packer_path_candidates"))
        script = " ; ".join(
            f'[ -d {shlex.quote(c)} ] && echo FOUND:{c} && exit 0'
            for c in cands
        ) + "; echo NONE; exit 1"
        r = self._ssh(script, timeout=30)
        for line in (r.stdout or "").splitlines():
            if line.startswith("FOUND:"):
                return line[len("FOUND:"):]
        raise FileNotFoundError(
            T("server.web_workers.model_not_on_packer_mini", cands=cands, rc=r.returncode, err=(r.stderr or '')[:200]))


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
            # Compatibility fallback: recognize the legacy helper inventory ID.
            if any(x in ("exo2", "packer") for x in ids + labels):
                return {
                    "id": "exo2", "label": "EXO2", "role": "packer",
                    "host": self.packer_ssh, "ssh": self.packer_ssh,
                    "repo": "~/.caravan/src/caravan",
                }
            return None
        for n in nodes:
            nid = str(n.get("id") or "").lower()
            lab = str(n.get("label") or "").lower()
            if nid in ids or lab in ids or nid in labels or lab in labels:
                if self._node_is_local(n) or (n.get("role") == "lead"):
                    return None
                return n
        # Match legacy helper role aliases against non-lead nodes
        if any(x in ("exo2", "packer") for x in ids + labels):
            for n in nodes:
                if n.get("role") != "lead" and not self._node_is_local(n):
                    return n
        return None

    def _ssh_node(self, node: dict, cmd: str, timeout: float = 60):
        target = (node.get("ssh") or node.get("host") or self.packer_ssh or "").strip()
        if not target:
            raise RuntimeError(T("server.web_workers.no_ssh_target_for_remote_worker"))
        import peer_route as PR
        return PR.run_ssh(target, cmd, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                          timeout=timeout, run=subprocess.run,
                          label=node.get("label") or node.get("id"))

    def _stop_tunnel(self, node=None) -> None:
        """Stop only Caravan's own ssh forward to this worker. Never a foreign pid."""
        import web_tunnels as WT
        pids = []
        proc = getattr(self, "_tunnel_proc", None)
        if proc is not None:
            if proc.poll() is None and proc.pid:
                pids.append(proc.pid)
            self._tunnel_proc = None
        target = None
        port = int(self.lead_port)
        adopted = getattr(self, "_adopted_tunnel", None)
        if adopted:
            pid, target, port = adopted
            pids.append(pid)
            self._adopted_tunnel = None
        node = node or getattr(self, "_worker_node", None) or {}
        if not target:
            target = (node.get("ssh") or node.get("host") or self.packer_ssh or "").strip()
        meta_path = self.state_dir / "remote-worker.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("tunnel_pid"):
                    pids.append(int(meta["tunnel_pid"]))
                if not target:
                    target = (meta.get("ssh") or "").strip()
            except (OSError, ValueError, TypeError):
                pass
        if target:
            WT.stop_forward(target, port, pids=pids)
        else:
            for pid in pids:
                cmd = WT.command_of(pid)
                try:
                    args = __import__("shlex").split(cmd or "")
                    maybe = args[-1] if args else ""
                except (ValueError, IndexError):
                    maybe = ""
                if maybe:
                    WT.stop_owned(pid, maybe, port)

    def _ensure_tunnel(self, node: dict) -> None:
        """Forward local lead_port → remote 127.0.0.1:lead_port so chat/health stay local.

        A leftover Caravan forward from a web restart is reused when it still
        works, or replaced (only that process) when it does not. A process
        that is not ours is never killed.
        """
        import web_tunnels as WT
        target = (node.get("ssh") or node.get("host") or self.packer_ssh or "").strip()
        port = int(self.lead_port)
        adopted = getattr(self, "_adopted_tunnel", None)
        if adopted and adopted[1] and adopted[1] != target:
            self._stop_tunnel()
        try:
            got = WT.ensure_forward(target, port)
        except WT.TunnelError:
            raise
        except Exception as e:
            raise WT.TunnelError(
                WT.plain_tunnel_error(e, mac=self._mac_name(node)),
                detail=str(e),
            ) from e
        if got.get("reused"):
            if not (self._tunnel_proc and self._tunnel_proc.pid == got["pid"]):
                self._tunnel_proc = None
                self._adopted_tunnel = (got["pid"], target, port)
        else:
            self._tunnel_proc = got.get("proc")
            self._adopted_tunnel = None

    def _start_remote_single(self, entry: dict, node: dict) -> int:
        """Run mlx_worker as a non-split HTTP server on a non-lead Mini; tunnel to it."""
        model = entry.get("lead_path") or entry.get("packer_path")
        if not model:
            raise RuntimeError(T("server.web_workers.no_model_path_for_remote_single"))
        remote_model = model
        repo = (node.get("repo") or "~/.caravan/src/caravan").rstrip("/")
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
            raise RuntimeError(T("server.web_workers.remote_worker_start_failed_v", v=(r.stderr or r.stdout or '')[:400]))
        pid = None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
        if not pid:
            raise RuntimeError(T("server.web_workers.remote_worker_did_not_print_a", v=(r.stdout or '')[:200]))
        self._ensure_tunnel(node)
        self._lead_proc = None
        (self.state_dir / "lead.pid").write_text(str(pid))
        tun_pid = None
        if self._tunnel_proc is not None and self._tunnel_proc.pid:
            tun_pid = self._tunnel_proc.pid
        elif getattr(self, "_adopted_tunnel", None):
            tun_pid = self._adopted_tunnel[0]
        (self.state_dir / "remote-worker.json").write_text(json.dumps({
            "pid": pid, "node": node.get("id") or node.get("label"),
            "ssh": node.get("ssh") or node.get("host"),
            "model": remote_model, "repo": repo,
            "model_id":entry["id"],"model_name":entry.get("name") or entry["id"],
            "settings":self.snapshot().get("settings") or {},
            "tunnel_pid": tun_pid,
        }))
        return pid

    def _remote_gguf_exists(self, node: dict, path: Path) -> bool:
        """True when the GGUF (and its numbered parts, if any) exist on node."""
        remote = str(path)
        if remote.startswith(str(Path.home())):
            remote = "~" + remote[len(str(Path.home())):]
        cmd = "test -f %s" % repr(remote)
        try:
            from gguf_sets import members
            nearby_cmd = "python3 -c %s" % repr(
                "import json,sys; from pathlib import Path; p=Path(%s).expanduser(); "
                "print(json.dumps({f.name: f.stat().st_size for f in p.parent.glob('*.gguf') if f.is_file()}))"
                % repr(remote)
            )
        except Exception:
            nearby_cmd = None
        try:
            r = self._ssh_node(node, cmd, timeout=25)
            if r.returncode != 0:
                return False
            if not nearby_cmd:
                return True
            r2 = self._ssh_node(node, nearby_cmd, timeout=25)
            if r2.returncode != 0:
                return True
            import json as _json
            sizes = _json.loads((r2.stdout or "{}").strip() or "{}")
            parts = members(Path(remote).name, sizes)
            return all(n in sizes for n in parts)
        except Exception:  # noqa: BLE001
            return False

    def _start_remote_gguf_single(self, node: dict, args: list, path: Path) -> int:
        """Run llama-server on a non-lead Mini and tunnel to it."""
        repo = (node.get("repo") or "~/.caravan/src/caravan").rstrip("/")
        remote_args = []
        for a in args:
            s = str(a)
            home = str(Path.home())
            if s.startswith(home):
                s = "~" + s[len(home):]
            remote_args.append(s)
        quoted = " ".join(shlex.quote(a) for a in remote_args)
        remote = (
            "mkdir -p ~/.caravan/web-ui; "
            "LPM=$(pmset -g 2>/dev/null | awk '/lowpowermode/{print $2}'); "
            "[[ \"$LPM\" == \"0\" || -z \"$LPM\" ]] || { echo REFUSE_LPM; exit 2; }; "
            + self._remote_stop_command(repo, "~/.caravan/web-ui/remote-lead.pid", port=self.lead_port) + "; "
            + "nohup " + quoted + " > ~/.caravan/web-ui/remote-lead.log 2>&1 & echo $! > ~/.caravan/web-ui/remote-lead.pid; "
            "cat ~/.caravan/web-ui/remote-lead.pid"
        )
        r = self._ssh_node(node, remote, timeout=45)
        if r.returncode != 0:
            raise RuntimeError(T("server.web_workers.remote_worker_start_failed_v", v=(r.stderr or r.stdout or "")[:400]))
        pid = None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
        if not pid:
            raise RuntimeError(T("server.web_workers.remote_worker_did_not_print_a", v=(r.stdout or "")[:200]))
        self._ensure_tunnel(node)
        (self.state_dir / "lead.pid").write_text(str(pid))
        tun_pid = None
        if self._tunnel_proc is not None and self._tunnel_proc.pid:
            tun_pid = self._tunnel_proc.pid
        elif getattr(self, "_adopted_tunnel", None):
            tun_pid = self._adopted_tunnel[0]
        (self.state_dir / "remote-worker.json").write_text(json.dumps({
            "pid": pid, "node": node.get("id") or node.get("label"),
            "ssh": node.get("ssh") or node.get("host"),
            "model": str(path), "repo": repo,
            "backend": "llama",
            "tunnel_pid": tun_pid,
        }))
        return pid


    def _start_packer(self, entry: dict, packer_path: str) -> Optional[int]:
        k = int(entry["packer_layers"])
        # Prefer the configured helper's own source checkout.
        remote = (
            "mkdir -p ~/.caravan/web-ui; "
            "LPM=$(pmset -g 2>/dev/null | awk '/lowpowermode/{print $2}'); "
            "[[ \"$LPM\" == \"0\" || -z \"$LPM\" ]] || { echo REFUSE_LPM; exit 2; }; "
            f"nohup ~/.caravan/venvs/mlx/bin/python ~/.caravan/src/caravan/agent/mlx_worker.py "
            f"--model {shlex.quote(packer_path)} "
            f"--split-role packer --split-listen {shlex.quote(self.packer_peer)} "
            f"--split-packer-layers {k} --no-split-draft --split-draft-skip-first-load "
            + "".join(f"{shlex.quote(a)} " for a in getattr(self, "_extra_packer", []))
            + f"> ~/.caravan/web-ui/packer.log 2>&1 & echo $! > ~/.caravan/web-ui/packer.pid; "
            "cat ~/.caravan/web-ui/packer.pid"
        )
        r = self._ssh(remote, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(T("server.web_workers.packer_start_failed_v", v=(r.stderr or r.stdout or '')[:300]))
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
            self._check_load_cancel()
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
                        self._note(T("server.web_workers.packer_ready"))
                        return
            if "Error" in text or "Traceback" in text:
                # Keep waiting a bit — load errors are fatal though.
                if "Traceback" in text:
                    raise RuntimeError(T("server.web_workers.packer_traceback_splitlines", splitlines="\n".join(text.splitlines()[-20:])))
            time.sleep(1.5)
        raise TimeoutError(T("server.web_workers.packer_did_not_become_ready_in"))

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
            self._check_load_cancel()
            if self._lead_proc and self._lead_proc.poll() is not None:
                tail = log_path.read_text(errors="replace")[-2000:] if log_path.exists() else ""
                raise RuntimeError(T("server.web_workers.lead_exited_early", rc=self._lead_proc.returncode, tail=tail))
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
                        self._note(T("server.web_workers.lead_health_ok"))
                        return
            except Exception:
                pass
            time.sleep(1.0)
        raise TimeoutError(T("server.web_workers.lead_did_not_become_ready_in"))

    def set_self_tune(self, value) -> dict:
        """Save Self-tuning and apply it on a running MLX worker with no reload.

        Learning is a live flag on the worker (`_learn_enabled`). Turning it
        off stops observing chats; turning it on starts observing and, if
        needed, opens the learned-settings store. Neither requires a reload.
        """
        raw = "off" if str(value).strip().lower() == "off" else "auto"
        snap = self.snapshot()
        page = dict(snap.get("page_settings") or web_settings.normalize({}))
        page["self_tune"] = raw
        settings = dict(snap.get("settings") or web_settings.normalize({}))
        settings["self_tune"] = raw
        self._set(page_settings=page, settings=settings)
        applied = False
        status = snap.get("status")
        backend = snap.get("backend")
        # "when you load a model" only if nothing is loaded; a leftover of that
        # next to a ready model is confusing.
        ready_on = T("server.web_workers.self_tuning_is_on_caravan_will")
        ready_off = T("server.web_workers.self_tuning_is_off_caravan_will")
        load_on = T("server.web_workers.self_tuning_is_on_it_takes")
        load_off = T("server.web_workers.self_tuning_is_off_it_takes")
        notice = (ready_off if raw == "off" else ready_on) if status == "ready" else (
            load_off if raw == "off" else load_on)
        if status == "ready" and backend == "llama":
            if raw == "off":
                tun = getattr(self, "gguf_self_tuner", None)
                if tun is not None and hasattr(tun, "cancel"):
                    tun.cancel()
            notice = (
                T("server.web_workers.self_tuning_is_off_caravan_will")
                if raw == "off" else
                T("server.web_workers.self_tuning_is_on_for_this")
            )
        elif status == "ready":
            try:
                from urllib.request import Request, urlopen
                req = Request(
                    f"http://127.0.0.1:{self.lead_port}/caravan/self-tune",
                    data=json.dumps({"enabled": raw != "off"}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=10) as response:
                    json.loads(response.read())
                applied = True
                notice = (
                    T("server.web_workers.self_tuning_is_off_caravan_will_2")
                    if raw == "off" else
                    T("server.web_workers.self_tuning_is_on_caravan_will")
                )
            except Exception as e:
                notice = (
                    T("server.web_workers.could_not_update_self_tuning_on", name=type(e).__name__)
                )
                return {"self_tune": raw, "applied": False, "reloaded": False,
                        "notice": notice, "error": str(e)}
        # notice_code lets the page clear the "when you load a model" note
        # once a model is ready without matching its words (Day 32).
        out = {"self_tune": raw, "applied": applied, "reloaded": False,
               "notice": notice}
        if notice in (load_on, load_off):
            out["notice_code"] = "on_load"
        return out

    def _page_self_tune(self) -> str:
        """The user's Self-tuning preference (auto/off).

        After a web restart, adopt can infer "off" from a leftover
        ``--no-learn`` on the command line. Prefer the last-model record
        the page actually saved; default is On.
        """
        try:
            from web_restore import Store
            req = Store(self.state_dir / "last-model.json").read() or {}
            raw = (req.get("settings") or {}).get("self_tune")
            if raw is not None and str(raw).strip():
                return "off" if str(raw).strip().lower() == "off" else "auto"
        except Exception:
            pass
        for key in ("page_settings", "settings"):
            raw = (self.state.get(key) or {}).get("self_tune")
            if raw:
                return "off" if str(raw).strip().lower() == "off" else "auto"
        return "auto"

    def _sync_learn_flag(self) -> None:
        """After adopting a running worker, match its learn flag to the page.

        A split start used to leave ``--no-learn`` on the lead even when
        Self-tuning was On. Turning the flag on live does not reload.
        """
        if self._page_self_tune() == "off":
            return
        try:
            self.set_self_tune("auto")
        except Exception as e:
            self._note(T("server.web_workers.could_not_turn_self_tuning_on", e=e))

    def guess_ahead_auto(self) -> str:
        """Day 27: after the user says yes to a helper download, put
        Guess-ahead on Auto (unless they pinned On) on the page and in
        last-model.json. Auto still decides by measurement."""
        snap = self.snapshot()
        page = dict(snap.get("page_settings") or {})
        if page.get("guess_ahead") == "on":
            return "on"
        page["guess_ahead"] = "auto"
        try:
            self._set(page_settings=page)
        except Exception:
            pass
        try:
            from web_restore import Store
            store = Store(self.state_dir / "last-model.json")
            req = store.read()
            if req and (not snap.get("model_id") or req.get("model_id") == snap.get("model_id")):
                settings = dict(req.get("settings") or {})
                if settings.get("guess_ahead") != "on":
                    settings["guess_ahead"] = "auto"
                    req["settings"] = settings
                    store.write(req)
        except Exception:
            pass
        return "auto"

    def reset_tuning(self) -> dict:
        """Clear saved winners, losses, and leftover Memory compression pins.

        Memory compression goes back to Auto (16). If the loaded model is
        running a tighter value, it is reloaded at 16. Other live settings
        stay as they are. Press Start afterward to run a new trial.
        """
        import web_speed
        snap = self.snapshot()
        mid = snap.get("model_id")
        if mid:
            try:
                web_speed.clear_tuning(mid)
            except Exception:
                pass
        lp = getattr(self, "_lead_path", None)
        if lp:
            try:
                import tuned_settings as TS
                st, e = self._tuned_entry(lp)
                if e:
                    e["winner"] = {}
                    e["optimize_hardware"] = {}
                    e["pending_reload"] = {}
                    e["reload_trial"] = None
                    e["reply_n"] = 0
                    TS.save_store(st, self.tuned_path)
            except Exception:
                pass
        if snap.get("backend") == "llama":
            try:
                import gguf_tune as GT
                import gguf_self_tune as GST
                entry = getattr(self, "_loaded_entry", None) or {}
                path = entry.get("lead_path")
                if path:
                    nodes = (snap.get("gguf") or {}).get("nodes") or [None]
                    n_minis = max(1, len(nodes))
                    store_path = GT.STORE
                    store = GT.load_store(store_path)
                    key = GT.entry_key(Path(path).expanduser(), n_minis)
                    if isinstance(store, dict) and key in store:
                        del store[key]
                        GT.save_store(store, store_path)
                    GST.clear_entry(path, n_minis)
                    tun = getattr(self, "gguf_self_tuner", None)
                    if tun is not None and hasattr(tun, "cancel"):
                        tun.cancel()
            except Exception:
                pass
        # Put Memory compression back to Auto on the page and in last-model,
        # so a leftover 4-bit pin cannot come back after the next load.
        page = dict(snap.get("page_settings") or {})
        page["kv_bits"] = "auto"
        try:
            self._set(page_settings=page)
        except Exception:
            pass
        try:
            from web_restore import Store
            store = Store(self.state_dir / "last-model.json")
            req = store.read()
            if req:
                settings = dict(req.get("settings") or {})
                settings["kv_bits"] = "auto"
                req["settings"] = settings
                store.write(req)
        except Exception:
            pass
        notice = (
            T("server.web_workers.saved_tuning_for_this_model_is")
        )
        live = dict(snap.get("settings") or {})
        live_kv = str(live.get("kv_bits") or "auto").lower()
        mid = snap.get("model_id")
        needs_reload = mid and live_kv not in ("auto", "16", "f16", "", "none")
        if needs_reload:
            try:
                self.switch(mid, wait=True, settings=page)
                notice = (
                    T("server.web_workers.saved_tuning_for_this_model_is")
                )
            except Exception as e:
                notice = (
                    T("server.web_workers.saved_tuning_is_cleared_and_memory", e=str(e)[:160])
                )
        return {
            "ok": True,
            "notice": notice,
        }

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
        snap = self.snapshot()
        if snap.get("backend") == "llama" and snap.get("status") == "ready":
            try:
                import web_settings as WS
                entry = getattr(self, "_loaded_entry", None) or {}
                return WS.gguf_active_settings(
                    entry.get("_loaded_tune"),
                    snap.get("page_settings") or snap.get("settings"),
                    launch=entry.get("_launch"),
                    model_path=entry.get("lead_path"),
                )
            except Exception:
                return None
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
