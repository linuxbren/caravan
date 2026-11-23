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
from caravan_i18n import T, fmt_date  # noqa: E402  (Day 32: user-facing text)

DEFAULT_PORT = int(os.environ.get("CARAVAN_WEB_PORT", "8190"))
STATUS_WORDS = {
    "running": "running", "interrupted": T("cli.jobs.waiting_to_run_again"), "done": "done",
    "failed": "failed", "cancelled": "cancelled", "expired": T("cli.jobs.too_old_to_run_again"),
    "gave_up": T("cli.jobs.stopped_too_often"), "skipped": "skipped", "stopped": T("cli.jobs.stopped_by_you"),
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
    return fmt_date(time.localtime(float(t)), "short") if t else "-"


def format_list(data) -> str:
    jobs = data.get("jobs") or []
    lines = []
    if not data.get("enabled", True):
        lines.append(T("cli.jobs.resume_after_a_restart_is_off"))
    if not jobs:
        lines.append(T("cli.jobs.no_saved_chats"))
        return "\n".join(lines)
    for j in jobs:
        status = STATUS_WORDS.get(j.get("status"), j.get("status") or "?")
        if j.get("recovered") and j.get("status") == "done":
            status = T("cli.jobs.finished_after_a_restart")
        prompt = (j.get("prompt_preview") or "").replace("\n", " ")[:60]
        lines.append(f"{j.get('id')}  {_when(j.get('created'))}  {status:<26} {prompt}")
    return "\n".join(lines)


def format_job(job) -> str:
    status = STATUS_WORDS.get(job.get("status"), job.get("status") or "?")
    out = [T("cli.jobs.job_id_status", id=job.get('id'), status=status)]
    if job.get("recovered"):
        out.append(T("cli.jobs.finished_after_a_restart_caravan_ran", replays=job.get('replays')))
    if job.get("error") and job.get("status") != "done":
        out.append(T("cli.jobs.note_error", error=str(job["error"])))
    out.append(T("cli.jobs.asked_when_finished_when2", when=_when(job.get('created')), when2=_when(job.get('finished'))))
    if job.get("status") == "done":
        out.append("")
        out.append(job.get("reply") or T("cli.jobs.empty_reply"))
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
            print(T("cli.jobs.caravan_no_saved_chat_v", v=argv[0] if argv else ''), file=sys.stderr)
            return 1
        print(T("cli.jobs.caravan_the_page_answered_http_code", code=e.code), file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(T("cli.jobs.caravan_caravan_is_not_running_on", e=e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
