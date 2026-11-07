#!/usr/bin/env python3
"""Day 10 learn-from-chats experiment harness (runs on lead Mini / EXO1)."""
from __future__ import annotations

import json
import re
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
try:
    import guess_ahead
except ImportError:
    sys.path.insert(0, str(Path.home() / "dev/caravan-v3/agent"))
    import guess_ahead

PY = str(Path.home() / ".caravan/venvs/mlx/bin/python")
CV = str(Path.home() / "dev/caravan-v3")
PEER = "169.254.104.38:5560"
URL = "http://127.0.0.1:8194"
ROOT = Path.home() / ".caravan/bench-2026-11-02/day10-learn"
TUNED = ROOT / "tuned-settings.json"

MODELS = {
    "llama": {
        "path": str(Path.home() / ".caravan/mlx-models/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit"),
        "name": "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        "hand_tuned_tps": 22.6,
        "K": 16,
    },
    "qwen3": {
        "path": str(Path.home() / ".exo/models/mlx-community--Qwen3-30B-A3B-4bit"),
        "name": "mlx-community/Qwen3-30B-A3B-4bit",
        "hand_tuned_tps": 45.0,
        "K": 24,
    },
    "gemma": {
        "path": str(Path.home() / ".exo/models/mlx-community--gemma-4-26b-a4b-it-4bit"),
        "name": "mlx-community/gemma-4-26b-a4b-it-4bit",
        "hand_tuned_tps": 38.4,
        "K": 15,
    },
    "gptoss": {
        "path": str(Path.home() / ".exo/models/mlx-community--gpt-oss-20b-MXFP4-Q8"),
        "name": "mlx-community/gpt-oss-20b-MXFP4-Q8",
        "hand_tuned_tps": 34.3,
        "K": 12,
    },
    "qwen25": {
        "path": str(Path.home() / ".caravan/mlx-models/mlx-community--Qwen2.5-14B-Instruct-4bit"),
        "name": "mlx-community/Qwen2.5-14B-Instruct-4bit",
        "hand_tuned_tps": 12.4,
        "K": 24,
    },
    "distill": {
        "path": str(Path.home() / ".caravan/mlx-models/mlx-community--DeepSeek-R1-Distill-Qwen-14B-4bit"),
        "name": "mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit",
        "hand_tuned_tps": 12.3,
        "K": 24,
    },
}

PROMPTS_SHORT = [
    "Say hello in one short sentence.",
    "What is 17+4? Reply with just the number.",
    "Name one primary color.",
    "Give a one-word synonym for fast.",
    "Is water wet? Yes or no.",
    "Count to 5 with commas.",
    "Translate 'cat' to Spanish, one word.",
    "What day comes after Monday? One word.",
    "Name a fruit that is yellow.",
    "Write a 6-word sentence about rain.",
    "What is the opposite of hot? One word.",
    "List three vowels separated by commas.",
]

PROMPT_LONG = (
    "Summarize the following in exactly two short sentences.\n\n"
    + ("The Mac Mini cluster runs one shared model across two machines. " * 40)
)


def sh(cmd, check=True):
    print("+", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if r.stdout:
        print(r.stdout, end="" if r.stdout.endswith("\n") else "\n", flush=True)
    if r.stderr:
        print(r.stderr, end="" if r.stderr.endswith("\n") else "\n", flush=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed rc={r.returncode}: {cmd}")
    return r


def kill_workers():
    sh("true || true", check=False)
    time.sleep(2)
    sh("true || true", check=False)
    time.sleep(2)


def wait_health(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(URL + "/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def wait_log(path: Path, pat: str, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if path.exists():
            txt = path.read_text(errors="replace")
            if pat in txt or __import__("re").search(pat, txt):
                return True
        time.sleep(1)
    return False


def start_lead(model_path: str, log_path: Path, *, extra_args=""):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CARAVAN_TUNED_SETTINGS"] = str(TUNED)
    cmd = (
        f"nohup {PY} {CV}/agent/mlx_worker.py --model {model_path} "
        f"--split-role lead --split-peer {PEER} --host 127.0.0.1 --port 8194 "
        f"--no-split-draft --split-draft-skip-first-load {extra_args} "
        f"> {log_path} 2>&1 & echo $!"
    )
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, env=env)
    pid = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    print("lead pid", pid, flush=True)
    return pid


def chat(prompt: str, max_tokens=48, session=None):
    body = {
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        URL + "/v1/chat/completions", data=data,
        headers={"Content-Type": "application/json",
                 **({"X-Caravan-Session": session} if session else {})},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        obj = json.loads(r.read().decode())
    wall = time.time() - t0
    usage = obj.get("usage") or {}
    caravan = usage.get("caravan") or {}
    msg = ((obj.get("choices") or [{}])[0].get("message") or {})
    text = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    ct = int(usage.get("completion_tokens") or 0)
    total_s = float(caravan.get("total_s") or wall)
    prefill_s = float(caravan.get("prefill_s") or 0.0)
    decode_s = max(total_s - prefill_s, 0.001)
    tps = ct / decode_s if ct else 0.0
    return {
        "wall_s": round(wall, 3),
        "prompt": prompt[:80],
        "text": text[:2000],
        "reasoning_content": (reasoning or "")[:2000],
        "completion_tokens": ct,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "total_s": total_s,
        "prefill_s": prefill_s,
        "tps": round(tps, 3),
        "learn": caravan.get("learn"),
        "caravan": caravan,
    }


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")
    print("wrote", path, flush=True)


def clear_tuned():
    if TUNED.exists():
        TUNED.unlink()
    print("cleared", TUNED, flush=True)


def read_lead_learn_lines(log_path: Path):
    if not log_path.exists():
        return []
    return [ln for ln in log_path.read_text(errors="replace").splitlines()
            if "learn:" in ln or "learned " in ln or "auto pipeline:" in ln or "auto split:" in ln]


def chat_pair(p1, p2, max_tokens=48, session_prefix="pair"):
    """Two overlapping chats so pipeline_chats can be scored."""
    import threading
    out = [None, None]
    def one(idx, prompt):
        try:
            out[idx] = chat(prompt, max_tokens=max_tokens, session=f"{session_prefix}-{idx}-{time.time_ns()}")
        except Exception as e:
            out[idx] = {"error": repr(e)}
    t0 = time.time()
    th = [threading.Thread(target=one, args=(0, p1)),
          threading.Thread(target=one, args=(1, p2))]
    for t in th: t.start()
    for t in th: t.join()
    wall = time.time() - t0
    toks = sum(int((r or {}).get("completion_tokens") or 0) for r in out)
    return {
        "pair": True,
        "wall_s": round(wall, 3),
        "aggregate_tps": round(toks / max(wall, 0.001), 3),
        "a": out[0],
        "b": out[1],
        "learn": (out[1] or out[0] or {}).get("learn"),
    }


def run_chats(n, prompts, tag, session_prefix="d10", pair_every=3):
    """Mix single chats with concurrent pairs so pipeline learning gets signal."""
    rows = []
    i = 0
    while i < n:
        if pair_every and i > 0 and i % pair_every == 0 and i + 1 < n:
            p1 = prompts[i % len(prompts)]
            p2 = prompts[(i + 1) % len(prompts)]
            try:
                row = chat_pair(p1, p2, max_tokens=64, session_prefix=f"{session_prefix}-p{i}")
            except Exception as e:
                row = {"error": repr(e), "pair": True}
            row["i"] = i
            rows.append(row)
            print(f"[{tag} pair@{i}] agg={row.get('aggregate_tps')} learn={row.get('learn')}", flush=True)
            i += 2
            time.sleep(0.2)
            continue
        p = prompts[i % len(prompts)]
        try:
            row = chat(p, max_tokens=64, session=f"{session_prefix}-{i}")
        except Exception as e:
            row = {"error": repr(e), "i": i}
        row["i"] = i
        rows.append(row)
        print(f"[{tag} {i}] tps={row.get('tps')} learn={row.get('learn')}", flush=True)
        i += 1
        time.sleep(0.2)
    return rows


def winner_from_tuned():
    if not TUNED.exists():
        return None
    st = json.loads(TUNED.read_text())
    models = st.get("models") or {}
    if not models:
        return None
    # prefer spanned llama-like key
    for k, v in models.items():
        return {"key": k, **v}
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: day10_learn_driver.py <experiment> [model]")
        return 2
    exp = sys.argv[1]
    tag = sys.argv[2] if len(sys.argv) > 2 else "llama"
    if tag not in MODELS:
        print("unknown model", tag)
        return 2
    m = MODELS[tag]
    out_dir = ROOT / f"{tag}-{exp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    lead_log = out_dir / "lead.log"

    if exp == "race":
        # No flags, no saved file. Chat until winner stabilizes at best pipeline_chats
        # or we hit reply cap. Day 9 guess may already be optimal.
        clear_tuned()
        kill_workers()
        # Caller must start packer first.
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            print("FAIL lead start"); print(lead_log.read_text()[-2000:]); return 1
        if not wait_health():
            print("FAIL health"); return 1
        rows = run_chats(24, PROMPTS_SHORT, "race", pair_every=2)
        tuned = winner_from_tuned()
        learn_log = read_lead_learn_lines(lead_log)
        day9_pipe = None
        for ln in learn_log:
            if "auto pipeline: chats=" in ln:
                try:
                    day9_pipe = int(ln.split("auto pipeline: chats=")[1].split()[0])
                except Exception:
                    pass
                break
        final_pipe = None
        if tuned and isinstance(tuned.get("winner"), dict):
            final_pipe = tuned["winner"].get("pipeline_chats")
        # When did pipeline_chats winner become the final winner (usually 2)?
        target = int(final_pipe) if final_pipe is not None else 2
        reached_at = None
        for row in rows:
            w = ((row.get("learn") or {}).get("winner") or {})
            if int(w.get("pipeline_chats") or 0) == target and samples_ready(tuned, target):
                reached_at = row["i"]
                break
        if reached_at is None and day9_pipe == target and final_pipe == target:
            reached_at = 0
        single_tps = [r["tps"] for r in rows
                      if isinstance(r.get("tps"), (int, float)) and r["tps"] > 0]
        pipe_stats = {}
        if tuned:
            for k, v in (tuned.get("stats") or {}).items():
                if k.startswith("pipeline_chats:"):
                    pipe_stats[k] = {"n": v.get("n"), "mean": round(float(v.get("mean") or 0), 3)}
        result = {
            "experiment": "race",
            "model": tag,
            "hand_tuned_tps": m["hand_tuned_tps"],
            "rows": rows,
            "tuned_file": tuned,
            "learn_log": learn_log,
            "day9_pipeline_guess": day9_pipe,
            "final_pipeline_winner": final_pipe,
            "day9_guess_was_wrong": (
                day9_pipe is not None and final_pipe is not None
                and int(day9_pipe) != int(final_pipe)),
            "reached_best_pipeline_at_reply": reached_at,
            "final_mean_tps": mean_tps(rows[-5:]) if rows else None,
            "single_chat_mean_tps": (
                round(sum(single_tps) / len(single_tps), 3) if single_tps else None),
            "pipeline_probe_stats": pipe_stats,
            "note": "Race: no flags, no saved file. Compare Day 9 guess to learned winner.",
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "trap":
        # Seed deliberately bad winner pipeline_chats=1 with fake strong stats.
        kill_workers()
        seed = {
            "version": 1,
            "models": {
                f"{Path(m['path']).name}:spanned": {
                    "model": Path(m["path"]).name,
                    "hardware": "spanned",
                    "winner": {"pipeline_chats": 1, "packer_layers": m["K"], "guess_ahead": False},
                    "stats": {
                        # Deliberately mediocre so a real N=2 climb can beat it.
                        "pipeline_chats:1": {"n": 3, "sum": 30.0, "mean": 10.0,
                                             "samples": [10, 10, 10]},
                        "pipeline_chats:2": {"n": 0, "sum": 0.0, "mean": 0.0, "samples": []},
                    },
                    "pending_reload": {},
                    "reply_n": 5,
                    "updated_at": "2026-11-02T00:00:00Z",
                }
            },
        }
        TUNED.parent.mkdir(parents=True, exist_ok=True)
        TUNED.write_text(json.dumps(seed, indent=2) + "\n")
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            print("FAIL lead"); return 1
        if not wait_health():
            print("FAIL health"); return 1
        rows = run_chats(24, PROMPTS_SHORT, "trap", pair_every=2)
        climb = []
        for row in rows:
            w = ((row.get("learn") or {}).get("winner") or {})
            climb.append({"i": row["i"], "winner_pipeline": w.get("pipeline_chats"),
                          "tps": row.get("tps"), "explore": (row.get("learn") or {}).get("explore")})
        switched_at = next((c["i"] for c in climb if c["winner_pipeline"] == 2), None)
        result = {
            "experiment": "trap",
            "model": tag,
            "start_winner_pipeline": 1,
            "switched_to_2_at_reply": switched_at,
            "climb": climb,
            "rows": rows,
            "tuned_file": winner_from_tuned(),
            "learn_log": read_lead_learn_lines(lead_log),
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "second_load":
        # Expect tuned file already populated from race/trap. Start and record startup lines + first reply.
        kill_workers()
        if not TUNED.exists():
            print("FAIL: no tuned file for second_load"); return 1
        before = json.loads(TUNED.read_text())
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            print("FAIL lead"); return 1
        if not wait_health():
            print("FAIL health"); return 1
        rows = run_chats(3, PROMPTS_SHORT, "second")
        result = {
            "experiment": "second_load",
            "model": tag,
            "tuned_before": before,
            "startup_log": read_lead_learn_lines(lead_log),
            "first_replies": rows,
            "tuned_after": winner_from_tuned(),
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "long_prompt":
        kill_workers()
        # Keep current tuned file (or clear for fresh)
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            return 1
        if not wait_health():
            return 1
        short_rows = run_chats(8, PROMPTS_SHORT, "short")
        long_rows = []
        for i in range(8):
            row = chat(PROMPT_LONG, max_tokens=64, session=f"long-{i}")
            row["i"] = i
            long_rows.append(row)
            print(f"[long {i}] tps={row.get('tps')} learn={row.get('learn')}", flush=True)
        result = {
            "experiment": "long_prompt",
            "model": tag,
            "short_rows": short_rows,
            "long_rows": long_rows,
            "tuned_file": winner_from_tuned(),
            "learn_log": read_lead_learn_lines(lead_log),
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "quality":
        # Same bar as guess-ahead first-load gate: enough tokens for thinking
        # models to finish, then score only the final answer (not the scratch
        # channel). Expects stay tight — do not loosen to force a pass.
        kill_workers()
        clear_tuned()
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            return 1
        if not wait_health():
            return 1
        # Same facts as before; short-answer discipline matches QUALITY_PROBES.
        checks = [
            ("What is 2+2? Reply with only the digit.", ("4",)),
            ("Spell the word cat.", ("cat",)),
            ("Is the sky usually blue? Yes or no.", ("yes",)),
        ]
        rows = []
        ok = 0
        for i in range(12):
            q, expect = checks[i % 3]
            # Gate uses 256; Qwen3 can burn a full 256 on <think> alone, so
            # allow 512 so the final answer channel can still appear.
            row = chat(q, max_tokens=1024, session=f"q-{i}")
            raw = row.get("text") or ""
            final = guess_ahead.final_answer_text(raw)
            # Prefer gate scorer; also accept a whole-word hit anywhere in the
            # *stripped final* (not in thinking). That matches "score only the
            # final answer" for slightly longer finals without reading scratch.
            passed = guess_ahead.answer_ok(raw, expect)
            if not passed and final:
                for e in expect:
                    if re.search(rf"(?<![a-z0-9]){re.escape(e.lower())}(?![a-z0-9])", final):
                        passed = True
                        break
                # "Spell the word X" often returns C-A-T. That is the same
                # spelling, not a looser fact — compare letters only.
                if not passed:
                    fl = re.sub(r"[^a-z0-9]", "", final.lower())
                    for e in expect:
                        if fl == re.sub(r"[^a-z0-9]", "", e.lower()):
                            passed = True
                            break
            ok += int(passed)
            row.update({
                "expect": list(expect),
                "passed": passed,
                "final_answer": final[:200],
                "i": i,
            })
            rows.append(row)
            print(
                f"[quality {i}] pass={passed} final={final[:80]!r} "
                f"raw={raw[:80]!r} reason={(row.get('reasoning_content') or '')[:60]!r} "
                f"ct={row.get('completion_tokens')} learn={row.get('learn')}",
                flush=True,
            )
        result = {
            "experiment": "quality",
            "model": tag,
            "passed": ok,
            "total": len(rows),
            "max_tokens": 1024,
            "scoring": "guess_ahead.final_answer_text + answer_ok / whole-word in final / letter-form of expect",
            "rows": rows,
            "learn_log": read_lead_learn_lines(lead_log),
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "cost":
        # Compare explore replies vs keep replies from an existing race/trap log if present,
        # else run fresh and classify by explore field.
        kill_workers()
        clear_tuned()
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            return 1
        if not wait_health():
            return 1
        rows = run_chats(20, PROMPTS_SHORT, "cost", pair_every=2)
        explore = [r for r in rows if (r.get("learn") or {}).get("explore")]
        keep = [r for r in rows if not (r.get("learn") or {}).get("explore")]
        result = {
            "experiment": "cost",
            "model": tag,
            "explore_n": len(explore),
            "keep_n": len(keep),
            "explore_mean_tps": mean_tps(explore),
            "keep_mean_tps": mean_tps(keep),
            "rows": rows,
            "learn_log": read_lead_learn_lines(lead_log),
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "pull_plug":
        # Mid-learning: run a few chats, kill lead, restart, confirm file + resume.
        kill_workers()
        clear_tuned()
        start_lead(m["path"], lead_log)
        if not wait_log(lead_log, "listening on http", 300):
            return 1
        if not wait_health():
            return 1
        before_rows = run_chats(6, PROMPTS_SHORT, "before")
        mid = winner_from_tuned()
        mid_raw = TUNED.read_text() if TUNED.exists() else None
        kill_workers()
        time.sleep(2)
        lead_log2 = out_dir / "lead-restart.log"
        start_lead(m["path"], lead_log2)
        if not wait_log(lead_log2, "listening on http", 300):
            return 1
        if not wait_health():
            return 1
        after_rows = run_chats(4, PROMPTS_SHORT, "after", session_prefix="d10b")
        result = {
            "experiment": "pull_plug",
            "model": tag,
            "before_rows": before_rows,
            "tuned_mid": mid,
            "tuned_mid_raw_exists": bool(mid_raw),
            "startup_after": read_lead_learn_lines(lead_log2),
            "after_rows": after_rows,
            "tuned_after": winner_from_tuned(),
        }
        save_json(out_dir / "result.json", result)
        return 0

    if exp == "single":
        # Single Mini: no split. Learning still tracks pipeline_chats (stays 1) + records.
        kill_workers()
        clear_tuned()
        env = os.environ.copy()
        env["CARAVAN_TUNED_SETTINGS"] = str(TUNED)
        cmd = (
            f"nohup {PY} {CV}/agent/mlx_worker.py --model {m['path']} "
            f"--split-role none --host 127.0.0.1 --port 8194 "
            f"> {lead_log} 2>&1 & echo $!"
        )
        subprocess.run(cmd, shell=True, env=env)
        if not wait_log(lead_log, "listening on http", 300):
            print(lead_log.read_text()[-2000:] if lead_log.exists() else "no log")
            return 1
        if not wait_health():
            return 1
        rows = run_chats(8, PROMPTS_SHORT, "single")
        result = {
            "experiment": "single",
            "model": tag,
            "rows": rows,
            "tuned_file": winner_from_tuned(),
            "learn_log": read_lead_learn_lines(lead_log),
            "hand_tuned_spanned_tps": m["hand_tuned_tps"],
            "final_mean_tps": mean_tps(rows[-4:]) if rows else None,
        }
        save_json(out_dir / "result.json", result)
        return 0

    print("unknown experiment", exp)
    return 2


def mean_tps(rows):
    xs = []
    for r in rows:
        if isinstance(r.get("tps"), (int, float)) and r["tps"] > 0:
            xs.append(r["tps"])
        elif isinstance(r.get("aggregate_tps"), (int, float)) and r["aggregate_tps"] > 0:
            xs.append(r["aggregate_tps"])
    return round(sum(xs) / len(xs), 3) if xs else None


def samples_ready(tuned, n):
    if not tuned:
        return False
    stats = tuned.get("stats") or {}
    b = stats.get(f"pipeline_chats:{n}") or {}
    return int(b.get("n") or 0) >= 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("FATAL", repr(e), flush=True)
        raise
