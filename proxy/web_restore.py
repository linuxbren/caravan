"""Web-owned last-successful-model intent. No workers, downloads or commands stored.

Boot restore uses the same guarded load endpoint as the UI. Transient pre-worker
unreadiness (unknown Mini memory, an unavailable Mini, or a Thunderbolt
interface that does not yet have one unambiguous IPv4 address) retries with
bounded backoff for up to ten minutes. Permanent safety failures still stop
immediately. User controls cancel all pending retries.
"""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid
import web_settings
from service_endpoints import RetryableReadinessError, error_payload
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402


def mac_name(node,nid,inventory):
    """"The 2nd Mac" (or the Mac's own name) for restore wait messages."""
    import web_nodes
    try:
        label=web_nodes.friendly_mac_label(node,node_id=nid,inventory=inventory)
    except Exception:
        label=T("server.pairing.mac")
    # Day 32: generic names in the active language, plus the English ones
    # older configs saved (labels are stored, so both can appear).
    generic={"Mac",T("server.pairing.mac"),str(nid)}
    if label in generic or label.startswith("paired_"):label=T("server.web_restore.other_mac")
    plain={"My Mac","other Mac",T("server.pairing_store.my_mac"),T("server.web_restore.other_mac")}
    return (T("server.web_restore.the_label", label=label)) if (label[:1].isdigit() or label in plain) else label


def canonical(request):
    if not isinstance(request, dict) or not isinstance(request.get("model_id"), str) or not request["model_id"].strip():
        raise ValueError(T("server.web_restore.last_model_record_needs_a_model"))
    if len(request["model_id"]) > 1024 or request.get("engine") not in ("mlx", "gguf"):
        raise ValueError(T("server.web_restore.invalid_last_model_id_engine"))
    out = {"model_id":request["model_id"], "engine":request["engine"],
           "settings":web_settings.normalize(request.get("settings") or {})}
    for key in ("placement_id", "repo_id", "gguf_file"):
        if request.get(key):
            if not isinstance(request[key],str):raise ValueError(T("server.web_restore.invalid_saved_key", key_=key))
            out[key] = request[key]
    ids = request.get("node_ids")
    if ids is not None:
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError(T("server.web_restore.invalid_saved_mini_ids"))
        out["node_ids"] = list(ids)
    if request.get("placement"):
        p=request["placement"]
        if not isinstance(p,dict) or p.get("mode") not in ("one","all","split"):
            raise ValueError(T("server.web_restore.invalid_saved_placement"))
        pi=p.get("node_ids")
        if not isinstance(pi,list) or not pi or any(not isinstance(x,str) or not x for x in pi) or len(set(pi))!=len(pi):
            raise ValueError(T("server.web_restore.invalid_saved_placement_minis"))
        out["placement"]={"mode":p["mode"],"node_ids":list(pi)}
    if request.get("balance"):
        out["balance"] = True
    if request.get("counts") is not None:
        counts=request["counts"]
        if not isinstance(counts,list) or not counts or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in counts):
            raise ValueError(T("server.web_restore.invalid_saved_split"))
        if out["engine"] == "mlx" and any(not isinstance(x,int) for x in counts):raise ValueError(T("server.web_restore.mlx_layer_counts_must_be_integers"))
        if ids is not None and len(ids)!=len(counts):raise ValueError(T("server.web_restore.one_saved_share_per_mini_is"))
        out["counts"] = list(counts)
    if isinstance(request.get("gguf_tune"),dict):
        out["gguf_tune"] = {k:v for k,v in request["gguf_tune"].items() if k in ("flash_attn","ubatch")}
    return out


class Store:
    def __init__(self, path):self.path=Path(path)
    def read(self):
        if not self.path.exists():return None
        if self.path.stat().st_size>1024*1024:raise ValueError(T("server.web_restore.last_model_record_is_too_large"))
        blob=json.loads(self.path.read_text())
        if not isinstance(blob,dict) or blob.get("schema")!=1 or "request" not in blob:raise ValueError(T("server.web_restore.unsupported_incomplete_last_model_record"))
        return canonical(blob["request"]) if blob.get("request") is not None else None
    def write(self, request):
        request=canonical(request) if request is not None else None
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_name(self.path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            with tmp.open("x") as f:
                os.chmod(tmp,0o600)
                json.dump({"schema":1,"saved_at":time.time(),"request":request},f,indent=2)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:tmp.unlink(missing_ok=True)


GGUF_TUNE_KEYS = ("flash_attn", "ubatch", "cache_type", "slot_save", "ctx", "n_slots",
                  "prompt_lookup", "guess_ahead", "draft_path", "ctx_auto")


def restorable_gguf_tune(tune, model_path=None) -> dict:
    """A saved GGUF tune that is safe to start again.

    Day 28 tuning fix: Guess-ahead and Prompt lookup winners now survive a
    restart, Update now and a Balance reload. Guess-ahead On comes back only
    with a helper file still on disk (or the same family's helper found
    again); otherwise it falls back to Off. Never a download."""
    t = {k: v for k, v in dict(tune or {}).items() if k in GGUF_TUNE_KEYS}
    if t.get("prompt_lookup") not in (None, "on", "off"):
        t.pop("prompt_lookup", None)
    if t.get("guess_ahead") == "on":
        try:
            import gguf_tune as GT
            d = GT.helper_on_disk(t.get("draft_path"), model_path)
        except Exception:  # noqa: BLE001
            d = None
        if d:
            t["draft_path"] = d
        else:
            t["guess_ahead"] = "off"
            t.pop("draft_path", None)
    else:
        if t.get("guess_ahead") not in (None, "off"):
            t.pop("guess_ahead", None)
        t.pop("draft_path", None)
    return t


def request_for(mgr, entry, snap, nodes):
    engine="gguf" if entry.get("source")=="gguf" else "mlx"
    out=dict(entry.get("_restore_request") or {},model_id=entry["id"],engine=engine,settings=snap.get("settings") or {})
    balance=snap.get("balance") or {}
    counts=entry.get("split_counts") or balance.get("counts")
    ids=balance.get("node_ids") or [n["id"] for n in entry.get("pipeline_nodes") or []]
    place=entry.get("placement") or {}
    if snap.get("split") and engine=="mlx":
        if not counts:
            from mlx_split_fetch import n_layers_of
            cfg=json.loads((Path(entry["lead_path"]).expanduser()/"config.json").read_text())
            n=n_layers_of(cfg);k=int(entry["packer_layers"]);counts=[k,n-k]
        if not ids:
            from split_balance import pipeline_order
            ids=[n["id"] for n in pipeline_order(nodes) if not place.get("node_ids") or n["id"] in place["node_ids"]]
        out.update(balance=True,counts=counts,node_ids=ids,placement={"mode":"split","node_ids":ids})
    elif engine=="gguf":
        ids=(snap.get("gguf") or {}).get("nodes") or place.get("node_ids") or []
        if ids:out.update(node_ids=ids,placement={"mode":"split" if snap.get("split") else "one","node_ids":ids})
        if entry.get("gguf_shares"):out["counts"]=entry["gguf_shares"]
        if entry.get("gguf_peer_files_ready"):out["balance"]=True
        if entry.get("_loaded_tune"):out["gguf_tune"]=entry["_loaded_tune"]
    else:
        node=getattr(mgr,"_worker_node",None)
        ids=[node["id"]] if node else [n["id"] for n in nodes if n.get("role")=="lead"][:1]
        if ids:out.update(node_ids=ids,placement={"mode":"one","node_ids":ids})
        out.pop("counts",None);out.pop("balance",None)
    return canonical(out)


def validate_placement(app, entry, body):
    """Fresh safety for explicit single placements / legacy GGUF restores.

    Balance split requests use the shared planner's stronger fresh shard checks.
    Never persist or replay a supplied path, command, RAM or file claim.
    """
    if not body.get("engine"):return entry
    body=canonical(body)
    expected=body["engine"]
    if expected not in ("mlx","gguf") or ("gguf" if entry.get("source")=="gguf" else "mlx")!=expected:
        raise ValueError(T("server.web_restore.saved_model_engine_no_longer_matches"))
    if body.get("balance"):return entry
    place=body.get("placement") or {}
    ids=place.get("node_ids") or body.get("node_ids") or []
    configured={n["id"]:n for n in app.configured_nodes()}
    if not ids or len(set(ids))!=len(ids) or not set(ids)<=set(configured):raise ValueError(T("server.web_restore.saved_minis_are_missing_or_no"))
    import web_nodes
    if expected=="gguf" and (configured[ids[0]].get("role")!="lead" or not web_nodes.is_local(configured[ids[0]]) or sum(configured[i].get("role")=="lead" for i in ids)!=1):
        raise ValueError(T("server.web_restore.saved_gguf_placement_needs_its_original"))
    live={n["id"]:n for n in app.nodes().get("nodes") or []}
    caps=[]
    for nid in ids:
        node=configured[nid];stats=web_nodes.gather_node_stats(node,ssh_fn=app._ssh_fn())
        # Plain Mac name ("the 2nd Mac"), never the internal paired_… id: the
        # page's wording filter turned that id into a bare "Mac" (Day 30).
        name=mac_name(node,nid,list(configured.values()))
        if stats.get("offline"):raise RetryableReadinessError(T("server.web_restore.name_is_not_reachable_yet", name=name), kind="mini")
        available=(stats.get("ram") or {}).get("available_gb",(stats.get("ram") or {}).get("free_gb"))
        if isinstance(available,bool) or not isinstance(available,(int,float)) or not math.isfinite(available) or available<=0:
            raise RetryableReadinessError(T("server.web_restore.free_memory_on_v_is_unknown", v=name[0].lower()+name[1:] if name.startswith(T("server.web_restore.the_label", label="")) else name), kind="memory")
        current=live.get(nid,{})
        footprint=float(current.get("active_gb") or current.get("weights_gb") or 0) if app.mgr.snapshot().get("status")=="ready" and current.get("model") else 0
        caps.append(float(available)+max(0,footprint))
    out=dict(entry)
    if expected=="mlx":
        if len(ids)!=1 or place.get("mode") not in ("one","all"):raise ValueError(T("server.web_restore.saved_mlx_split_must_use_the"))
        inv=next((n for n in app.gather_model_inventories() if n.get("id")==ids[0]),{})
        model=(inv.get("models") or {}).get(entry.get("hf")) or {}
        if not model.get("full_ok") or not model.get("has_tokenizer") or not model.get("path"):
            raise ValueError(T("server.web_restore.required_complete_model_files_are_missing", ids=ids[0]))
        weights=float(model.get("weights_gb") or 0)
        out.update(placement={"mode":"one","node_ids":ids},lead_path=model["path"],usable=True,available_lead=True,need_split=False,run_mode="single")
        out.pop("split_counts",None);out.pop("pipeline_nodes",None)
        shares=[1]
    else:
        path=Path(entry["lead_path"]).expanduser()
        if not path.is_file():raise ValueError(T("server.web_restore.saved_gguf_file_is_missing_no"))
        weights=(entry['gguf_deployment']['source']['source_bytes'] if entry.get('sharded') else path.stat().st_size)/1e9;shares=body.get("counts") or entry.get('gguf_shares') or [1]*len(ids)
        if entry.get('sharded'):
            import gguf_share_download as D
            dep=entry['gguf_deployment']
            if ids!=dep['node_ids'] or D.shares(shares)!=dep['shares']:raise ValueError(T("server.web_restore.saved_own_part_plan_differs_from"))
        if len(shares)!=len(ids):raise ValueError(T("server.web_restore.saved_gguf_shares_do_not_match"))
        out.update(placement={"mode":"split" if len(ids)>1 else "one","node_ids":ids},gguf_shares=shares)
        if body.get("gguf_tune"):out["tune_override"]=restorable_gguf_tune(body["gguf_tune"],entry.get("lead_path"))
    if not weights or any(c-weights*s/sum(shares)-1.3<1.75 for c,s in zip(caps,shares)):
        raise ValueError(T("server.web_restore.not_enough_free_memory_to_restore"))
    return out


class Controller:
    def __init__(self, app, *, store=None, retry_timeout=600, clock=time.monotonic, wait=None):
        self.app=app;self.mgr=app.mgr
        self.store=store or Store(self.mgr.state_dir/"last-model.json")
        self.lock=threading.RLock();self.token=None;self.cancelled=False;self.started=False
        self._cancel_event=threading.Event()
        self.retry_timeout=retry_timeout;self._clock=clock
        self._wait=wait or self._cancel_event.wait
        self.state={"phase":"idle","message":"","enabled":os.environ.get("CARAVAN_WEB_RESTORE_LAST","1").lower() not in ("0","false","no")}
        self.mgr.on_load_success=self.record
        self.mgr.on_user_stop=self.clear
    def snapshot(self):
        with self.lock:return dict(self.state)
    def note(self,phase,message):
        with self.lock:self.state.update(phase=phase,message=message)
    def record(self,entry,snap):
        try:
            request=request_for(self.mgr,entry,snap,self.app.configured_nodes())
            with self.lock:
                cancelled=getattr(self.mgr,"_load_cancel",None)
                if cancelled and cancelled.is_set():return
                self.store.write(request)
                self.state.update(phase="saved",message=T("server.web_restore.last_successful_model_saved_for_next"),last_model=request["model_id"],saved_at=time.time())
        except Exception as e:
            self.note("save_error",T("server.web_restore.model_loaded_but_last_model_preference", e=str(e)))
            self.mgr._note(self.state["message"])
    def cancel(self):
        with self.lock:self.token=None;self.cancelled=True;self._cancel_event.set();self.state.update(phase="cancelled",message=T("server.web_restore.automatic_restore_cancelled_by_model_controls"))
    def clear(self):
        self.cancel()
        with self.lock:
            self.store.write(None);self.state.update(phase="empty",last_model=None,message=T("server.web_restore.models_unloaded_next_login_will_restore"))
    def authorize(self,body,*,begin=False):
        token=body.get("_restore_token")
        if token:
            with self.lock:
                if token!=self.token or self.cancelled:raise ValueError(T("server.web_restore.automatic_restore_was_cancelled_nothing_was"))
        elif begin:self.cancel()
    def start(self,base_url,*,background=True):
        with self.lock:
            if self.started:return
            self.started=True
        self.base_url=base_url
        if background:
            self.thread=threading.Thread(target=self.run,daemon=True,name="caravan-restore-last");self.thread.start()
        else:self.run()
    def http(self,path,body=None,*,timeout=180):
        req=Request(self.base_url+path,data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json"})
        try:
            with urlopen(req,timeout=timeout) as r:return json.load(r)
        except HTTPError as e:
            try:payload=json.loads(e.read())
            except Exception:payload={}
            typed=RetryableReadinessError.from_payload(payload)
            if typed:raise typed from None
            raise ValueError((payload.get("error") if isinstance(payload,dict) else None) or str(e)) from None
    def _await_load(self,token):
        """Wait until the accepted load is ready, or raise a terminal/retryable error.

        /api/models/load starts the switch in the background and returns 200
        before Thunderbolt resolution or worker launch. Retry only pre-worker
        unreadiness flagged on the worker snapshot.
        """
        deadline=time.monotonic()+1200
        while time.monotonic()<deadline:
            with self.lock:
                if self.token!=token:return
            snap=self.mgr.snapshot()
            if snap.get("status")=="ready":
                return
            running=getattr(self.mgr,"_switch_thread",None)
            alive=bool(running and running.is_alive())
            if snap.get("status")=="error" or (snap.get("status")=="idle" and (snap.get("error") or not alive)):
                if alive:
                    running.join(30)
                    snap=self.mgr.snapshot()
                typed=RetryableReadinessError.from_state(snap)
                if typed:raise typed
                raise ValueError(snap.get("error") or T("server.web_restore.model_did_not_become_ready"))
            threading.Event().wait(.25)
        raise ValueError(T("server.web_restore.timed_out_restoring_last_model_use"))
    def _backoff(self,token,attempt,error,retry_deadline,delay):
        remaining=retry_deadline-self._clock()
        if remaining<=0:
            raise ValueError(error.timeout_message(self.retry_timeout) if isinstance(error,RetryableReadinessError) else T("server.web_restore.peer_readiness_timed_out_after_retry", retry_timeout=self.retry_timeout))
        pause=min(delay,remaining)
        with self.lock:
            if self.cancelled or self.token!=token:return 0
            message=error.waiting_message(attempt,pause) if isinstance(error,RetryableReadinessError) else f"Waiting for Minis (attempt {attempt}); retry in {pause:g}s: {error}"
            self.state.update(phase="preparing",attempt=attempt,retry_in_s=pause,message=message)
        self.mgr._note(self.state["message"])
        self._wait(pause)
        return min(delay*2,30)
    def run(self):
        if not self.state["enabled"]:self.note("disabled",T("server.web_restore.automatic_restore_disabled_last_successful_loads"));return
        try:
            with self.lock:
                if self.cancelled:return
                if self.mgr.snapshot().get("status")=="ready":self.note("adopted",T("server.web_restore.kept_the_existing_healthy_model_no"));return
            request=self.store.read()
            with self.lock:
                if self.cancelled:return
                if request is None:self.note("empty",T("server.web_restore.no_last_model_to_restore"));return
                self.token=uuid.uuid4().hex;token=self.token
                self.state.update(phase="preparing",message=T("server.web_restore.restoring_last_model_model_id", model_id=request["model_id"]),last_model=request["model_id"])
            self.mgr._note(self.state["message"])
            healthy=getattr(self.mgr,"lead_healthy",None)
            if callable(healthy) and healthy():raise ValueError(T("server.web_restore.an_unadopted_worker_already_owns_the"))
            # Retry only flagged pre-worker unreadiness. Never retry ambiguous
            # HTTP timeouts, missing files or RAM shortfalls.
            retry_deadline=self._clock()+self.retry_timeout
            delay=2.0;attempt=0;last_retryable=None
            while True:
                with self.lock:
                    if self.cancelled or self.token!=token:return
                remaining=retry_deadline-self._clock()
                if remaining<=0:
                    raise ValueError(last_retryable.timeout_message(self.retry_timeout) if last_retryable else T("server.web_restore.peer_readiness_timed_out_after_retry", retry_timeout=self.retry_timeout))
                attempt+=1
                try:
                    self.http("/api/models/load",dict(request,_restore_token=token),timeout=min(180,max(1,remaining)))
                    self._await_load(token)
                    break
                except RetryableReadinessError as e:
                    last_retryable=e
                    delay=self._backoff(token,attempt,e,retry_deadline,delay)
                    if delay==0:return
            with self.lock:self.state.pop("retry_in_s",None)
            if self.mgr.snapshot().get("status")=="ready":
                self.note("restored",T("server.web_restore.last_model_restored_ui_model_controls"));return
            raise ValueError(self.mgr.snapshot().get("error") or T("server.web_restore.model_did_not_become_ready"))
        except Exception as e:
            with self.lock:
                if self.cancelled:return
                message=T("server.web_restore.could_not_restore_last_model_e", e=str(e))
                self.token=None  # a timed-out HTTP preparation must not start later
                self.state.update(phase="blocked",message=message)
                if self.mgr.snapshot().get("status")!="ready":self.mgr._set(status="idle",error=message)
            self.mgr._note(message)
