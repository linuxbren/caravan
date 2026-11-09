"""Web-owned last-successful-model intent. No workers, downloads or commands stored.

Boot restore POSTs the same guarded load endpoint as the UI, exactly once. A
failed restore leaves the intent available for a later explicit Load/retry.
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


def canonical(request):
    if not isinstance(request, dict) or not isinstance(request.get("model_id"), str) or not request["model_id"].strip():
        raise ValueError("last-model record needs a model ID")
    if len(request["model_id"]) > 1024 or request.get("engine") not in ("mlx", "gguf"):
        raise ValueError("invalid last-model ID/engine")
    out = {"model_id":request["model_id"], "engine":request["engine"],
           "settings":web_settings.normalize(request.get("settings") or {})}
    for key in ("placement_id", "repo_id", "gguf_file"):
        if request.get(key):
            if not isinstance(request[key],str):raise ValueError("invalid saved "+key)
            out[key] = request[key]
    ids = request.get("node_ids")
    if ids is not None:
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("invalid saved Mini IDs")
        out["node_ids"] = list(ids)
    if request.get("placement"):
        p=request["placement"]
        if not isinstance(p,dict) or p.get("mode") not in ("one","all","split"):
            raise ValueError("invalid saved placement")
        pi=p.get("node_ids")
        if not isinstance(pi,list) or not pi or any(not isinstance(x,str) or not x for x in pi) or len(set(pi))!=len(pi):
            raise ValueError("invalid saved placement Minis")
        out["placement"]={"mode":p["mode"],"node_ids":list(pi)}
    if request.get("balance"):
        out["balance"] = True
    if request.get("counts") is not None:
        counts=request["counts"]
        if not isinstance(counts,list) or not counts or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in counts):
            raise ValueError("invalid saved split")
        if out["engine"] == "mlx" and any(not isinstance(x,int) for x in counts):raise ValueError("MLX layer counts must be integers")
        if ids is not None and len(ids)!=len(counts):raise ValueError("one saved share per Mini is required")
        out["counts"] = list(counts)
    if isinstance(request.get("gguf_tune"),dict):
        out["gguf_tune"] = {k:v for k,v in request["gguf_tune"].items() if k in ("flash_attn","ubatch")}
    return out


class Store:
    def __init__(self, path):self.path=Path(path)
    def read(self):
        if not self.path.exists():return None
        if self.path.stat().st_size>1024*1024:raise ValueError("last-model record is too large")
        blob=json.loads(self.path.read_text())
        if not isinstance(blob,dict) or blob.get("schema")!=1 or "request" not in blob:raise ValueError("unsupported/incomplete last-model record")
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
        raise ValueError("Saved model engine no longer matches the installed model")
    if body.get("balance"):return entry
    place=body.get("placement") or {}
    ids=place.get("node_ids") or body.get("node_ids") or []
    configured={n["id"]:n for n in app.configured_nodes()}
    if not ids or len(set(ids))!=len(ids) or not set(ids)<=set(configured):raise ValueError("Saved Minis are missing or no longer configured")
    import web_nodes
    if expected=="gguf" and (configured[ids[0]].get("role")!="lead" or not web_nodes.is_local(configured[ids[0]]) or sum(configured[i].get("role")=="lead" for i in ids)!=1):
        raise ValueError("Saved GGUF placement needs its original local lead; no substitute Mini was selected")
    live={n["id"]:n for n in app.nodes().get("nodes") or []}
    caps=[]
    for nid in ids:
        node=configured[nid];stats=web_nodes.gather_node_stats(node,ssh_fn=app._ssh_fn())
        if stats.get("offline"):raise ValueError(f"Mini {nid} is unavailable; bring it online and press Load")
        available=(stats.get("ram") or {}).get("available_gb",(stats.get("ram") or {}).get("free_gb"))
        if isinstance(available,bool) or not isinstance(available,(int,float)) or not math.isfinite(available) or available<=0:
            raise ValueError(f"Live free memory is unknown for {nid}; nothing was loaded")
        current=live.get(nid,{})
        footprint=float(current.get("active_gb") or current.get("weights_gb") or 0) if app.mgr.snapshot().get("status")=="ready" and current.get("model") else 0
        caps.append(float(available)+max(0,footprint))
    out=dict(entry)
    if expected=="mlx":
        if len(ids)!=1 or place.get("mode") not in ("one","all"):raise ValueError("Saved MLX split must use the Balance planner")
        inv=next((n for n in app.gather_model_inventories() if n.get("id")==ids[0]),{})
        model=(inv.get("models") or {}).get(entry.get("hf")) or {}
        if not model.get("full_ok") or not model.get("has_tokenizer") or not model.get("path"):
            raise ValueError(f"Required complete model files are missing on {ids[0]}; no download was started")
        weights=float(model.get("weights_gb") or 0)
        out.update(placement={"mode":"one","node_ids":ids},lead_path=model["path"],usable=True,available_lead=True,need_split=False,run_mode="single")
        out.pop("split_counts",None);out.pop("pipeline_nodes",None)
        shares=[1]
    else:
        path=Path(entry["lead_path"]).expanduser()
        if not path.is_file():raise ValueError("Saved GGUF file is missing; no download was started")
        weights=path.stat().st_size/1e9;shares=body.get("counts") or [1]*len(ids)
        if len(shares)!=len(ids):raise ValueError("Saved GGUF shares do not match the Minis")
        out.update(placement={"mode":"split" if len(ids)>1 else "one","node_ids":ids},gguf_shares=shares)
        if body.get("gguf_tune"):out["tune_override"]=body["gguf_tune"]
    if not weights or any(c-weights*s/sum(shares)-1.3<1.75 for c,s in zip(caps,shares)):
        raise ValueError("Not enough free memory to restore this placement with 1.75 GB headroom; choose a smaller model or another split")
    return out


class Controller:
    def __init__(self, app, *, store=None):
        self.app=app;self.mgr=app.mgr
        self.store=store or Store(self.mgr.state_dir/"last-model.json")
        self.lock=threading.RLock();self.token=None;self.cancelled=False;self.started=False
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
                self.state.update(phase="saved",message="Last successful model saved for next login",last_model=request["model_id"],saved_at=time.time())
        except Exception as e:
            self.note("save_error","Model loaded, but last-model preference could not be saved: "+str(e))
            self.mgr._note(self.state["message"])
    def cancel(self):
        with self.lock:self.token=None;self.cancelled=True;self.state.update(phase="cancelled",message="Automatic restore cancelled by model controls")
    def clear(self):
        self.cancel()
        with self.lock:
            self.store.write(None);self.state.update(phase="empty",last_model=None,message="Models unloaded; next login will restore nothing")
    def authorize(self,body,*,begin=False):
        token=body.get("_restore_token")
        if token:
            with self.lock:
                if token!=self.token or self.cancelled:raise ValueError("Automatic restore was cancelled; nothing was changed")
        elif begin:self.cancel()
    def start(self,base_url,*,background=True):
        with self.lock:
            if self.started:return
            self.started=True
        self.base_url=base_url
        if background:
            self.thread=threading.Thread(target=self.run,daemon=True,name="caravan-restore-last");self.thread.start()
        else:self.run()
    def http(self,path,body=None):
        req=Request(self.base_url+path,data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json"})
        try:
            with urlopen(req,timeout=180) as r:return json.load(r)
        except HTTPError as e:
            try:msg=json.loads(e.read()).get("error") or str(e)
            except Exception:msg=str(e)
            raise ValueError(msg) from None
    def run(self):
        if not self.state["enabled"]:self.note("disabled","Automatic restore disabled; last successful loads are still saved");return
        try:
            with self.lock:
                if self.cancelled:return
                if self.mgr.snapshot().get("status")=="ready":self.note("adopted","Kept the existing healthy model; no reload needed");return
            request=self.store.read()
            with self.lock:
                if self.cancelled:return
                if request is None:self.note("empty","No last model to restore");return
                self.token=uuid.uuid4().hex;token=self.token
                self.state.update(phase="preparing",message="Restoring last model: "+request["model_id"],last_model=request["model_id"])
            self.mgr._note(self.state["message"])
            healthy=getattr(self.mgr,"lead_healthy",None)
            if callable(healthy) and healthy():raise ValueError("An unadopted worker already owns the lead port; it was not stopped")
            self.http("/api/models/load",dict(request,_restore_token=token))
            deadline=time.monotonic()+1200
            while time.monotonic()<deadline:
                with self.lock:
                    if self.token!=token:return
                snap=self.mgr.snapshot()
                if snap.get("status")=="ready":self.note("restored","Last model restored; UI model controls remain available");return
                running=getattr(self.mgr,"_switch_thread",None)
                if snap.get("status")=="error" or (snap.get("status")=="idle" and (snap.get("error") or not (running and running.is_alive()))):
                    raise ValueError(snap.get("error") or "Model did not become ready")
                threading.Event().wait(.25)
            raise ValueError("Timed out restoring last model; use Load to try again")
        except Exception as e:
            with self.lock:
                if self.cancelled:return
                message="Could not restore last model: "+str(e)+". Check Minis/files/memory, then press Load. No automatic retry or download."
                self.token=None  # a timed-out HTTP preparation must not start later
                self.state.update(phase="blocked",message=message)
                if self.mgr.snapshot().get("status")!="ready":self.mgr._set(status="idle",error=message)
            self.mgr._note(message)
