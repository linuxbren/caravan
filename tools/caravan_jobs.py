"""`caravan jobs`: chats Caravan saved in its request journal (Day 30).

    caravan jobs              recent chats, newest first
    caravan jobs <id>         the saved reply of one chat
    caravan jobs <id> --json  the whole saved job as JSON

A chat that a power loss or crash cut off is run again from the start
once the model is back; its reply is saved here ("Finished after a
restart"). Reads the running Caravan page on this Mac.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = int(os.environ.get("CARAVAN_WEB_PORT", "8190"))
STATUS_WORDS = {
    "running": "running", "interrupted": "waiting to run again", "done": "done",
    "failed": "failed", "cancelled": "cancelled", "expired": "too old to run again",
    "gave_up": "stopped too often", "skipped": "skipped",
}


def _port() -> int:
    try:
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caravan_service as service  # type: ignore
        return int(service.stored("web", Path.home())["port"])
    except Exception:
        return DEFAULT_PORT


def _get(path, port, timeout=10):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


def _when(t):
    return time.strftime("%b %d %H:%M:%S", time.localtime(float(t))) if t else "-"


def format_list(data) -> str:
    jobs = data.get("jobs") or []
    lines = []
    if not data.get("enabled", True):
        lines.append("Resume after a restart is off ([jobs] resume = false); new chats are not saved.")
    if not jobs:
        lines.append("No saved chats.")
        return "\n".join(lines)
    for j in jobs:
        status = STATUS_WORDS.get(j.get("status"), j.get("status") or "?")
        if j.get("recovered") and j.get("status") == "done":
            status = "finished after a restart"
        prompt = (j.get("prompt_preview") or "").replace("\n", " ")[:60]
        lines.append(f"{j.get('id')}  {_when(j.get('created'))}  {status:<26} {prompt}")
    return "\n".join(lines)


def format_job(job) -> str:
    status = STATUS_WORDS.get(job.get("status"), job.get("status") or "?")
    out = [f"Job {job.get('id')}: {status}"]
    if job.get("recovered"):
        out.append("Finished after a restart: Caravan ran the request again from the start "
                   f"(try {job.get('replays')}).")
    if job.get("error") and job.get("status") != "done":
        out.append("Note: " + str(job["error"]))
    out.append(f"Asked {_when(job.get('created'))}; finished {_when(job.get('finished'))}")
    if job.get("status") == "done":
        out.append("")
        out.append(job.get("reply") or "(empty reply)")
    return "\n".join(out)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    port = _port()
    try:
        if argv:
            job = _get("/api/jobs/" + urllib.request.quote(argv[0]), port)
            print(json.dumps(job, indent=2, ensure_ascii=False) if as_json else format_job(job))
        else:
            data = _get("/api/jobs?limit=50", port)
            print(json.dumps(data, indent=2, ensure_ascii=False) if as_json else format_list(data))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[Caravan] No saved chat {argv[0] if argv else ''}.", file=sys.stderr)
            return 1
        print(f"[Caravan] The page answered HTTP {e.code}.", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(f"[Caravan] Caravan is not running on this Mac ({e}). Run caravan start.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
