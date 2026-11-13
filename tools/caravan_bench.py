"""Compare a GGUF model to its MLX counterpart.

Prints the same wording as the stats under each reply:

    Read X tok at Y tok/s · Write Z tok at W tok/s · first token A s · total B s

Does not invent numbers. Without --yes it only prints the exact steps,
and can also read already-saved chat averages (--from-averages) without
loading or unloading any model.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

import web_speed as S  # noqa: E402
import gguf_tune as T  # noqa: E402

DEFAULT_PORT = int(__import__("os").environ.get("CARAVAN_WEB_PORT", "8190"))
SPEED_STORE = Path("~/.caravan/speed_averages.json").expanduser()


def format_side(name: str, specs) -> str:
    """One labeled line in reply-stats wording, or a 'no numbers' note."""
    specs = S.specs_from(specs) if specs else {}
    line = S.format_reply_stats(
        specs.get("write_tok_s"),
        specs.get("ttft_s"),
        prompt_tokens=specs.get("prompt_tokens"),
        read_tok_s=specs.get("read_tok_s"),
        completion_tokens=specs.get("completion_tokens"),
        total_s=specs.get("total_s"),
    )
    if line:
        return f"{name}: {line}"
    return f"{name}: no speed numbers recorded yet."


def _median_specs(samples: list) -> dict:
    out = {}
    for key in ("write_tok_s", "read_tok_s", "ttft_s", "prompt_tokens",
                "completion_tokens", "total_s"):
        vals = [float(s[key]) for s in samples if isinstance(s, dict) and key in s
                and isinstance(s[key], (int, float))]
        if vals:
            med = T._median(vals)
            if med is not None:
                out[key] = med
    return out


def _urlopen(url, data=None, timeout=30, headers=None):
    req = urllib.request.Request(
        url, data=data, headers=headers or {},
        method="POST" if data is not None else "GET",
    )
    if data is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def status(port: int, urlopen=_urlopen) -> dict:
    return urlopen(f"http://127.0.0.1:{int(port)}/api/status", timeout=5)


def load_model(port: int, model_id: str, urlopen=_urlopen, wait=300) -> dict:
    urlopen(
        f"http://127.0.0.1:{int(port)}/api/models/load",
        data=json.dumps({"id": model_id}).encode(),
        timeout=30,
    )
    deadline = time.time() + wait
    last = {}
    while time.time() < deadline:
        last = status(port, urlopen=urlopen)
        worker = (last or {}).get("worker") or last
        if worker.get("status") == "ready" and worker.get("model_id") == model_id:
            return last
        if worker.get("status") in ("error", "stopped") and worker.get("error"):
            raise RuntimeError(worker.get("error") or "load failed")
        time.sleep(1)
    raise TimeoutError("The model did not become ready in time.")


def measure_chat(port: int, prompts=None, max_tokens=192, urlopen=_urlopen,
                 timeout=300) -> dict:
    prompts = prompts or T.BENCH_PROMPTS
    samples = []
    for p in prompts:
        body = json.dumps({
            "messages": [{"role": "user", "content": p}],
            "max_tokens": int(max_tokens),
            "temperature": 0,
            "stream": False,
        }).encode()
        data = urlopen(
            f"http://127.0.0.1:{int(port)}/api/chat",
            data=body, timeout=timeout,
        )
        web = (data or {}).get("caravan_web") or {}
        stats = web.get("stats") or {}
        specs = T.specs_from_response(data) if isinstance(data, dict) else {}
        # Prefer the same caravan_web stats the page uses under each reply.
        for k, src in (("write_tok_s", "write_tok_s"), ("read_tok_s", "read_tok_s"),
                       ("ttft_s", "ttft_s"), ("prompt_tokens", "prompt_tokens"),
                       ("completion_tokens", "completion_tokens"), ("total_s", "total_s")):
            if k not in specs and src in stats:
                try:
                    specs[k] = float(stats[src])
                except (TypeError, ValueError):
                    pass
        samples.append(specs)
    return _median_specs(samples)


def averages_for(model_id: str, store=None) -> dict:
    """Best-effort saved chat average for this model, across setups."""
    mid = str(model_id or "").strip()
    if not mid:
        return {}
    data = S._load(store)
    slots = ((data.get("models") or {}).get(mid) or {})
    if not isinstance(slots, dict) or not slots:
        return {}
    # Prefer the setup with the most samples.
    best, best_n = {}, -1
    for slot in slots.values():
        if not isinstance(slot, dict):
            continue
        view = S._snapshot(slot)
        n = int(slot.get("n") or slot.get("write_n") or 0)
        if S._has_specs(S.specs_from(view)) and n >= best_n:
            best, best_n = S.specs_from(view), n
    return best


def steps_text(gguf_id: str, mlx_id: str, port: int = DEFAULT_PORT) -> str:
    """Exact commands Brenden can run. No numbers."""
    return (
        "This compares a GGUF model to its MLX counterpart using the same\n"
        "prompts Auto-tune uses, and prints each side in the same wording as\n"
        "the stats under a reply. It will load each model in turn, so the\n"
        "model currently running is replaced until the command finishes.\n"
        "\n"
        "On the 1st Mac, with Caravan running and both models already\n"
        "downloaded:\n"
        "\n"
        f"  caravan bench --gguf {gguf_id} --mlx {mlx_id} --yes\n"
        "\n"
        "To only print already-saved chat averages, without loading anything:\n"
        "\n"
        f"  caravan bench --gguf {gguf_id} --mlx {mlx_id} --from-averages\n"
        "\n"
        f"Caravan's page is http://127.0.0.1:{int(port)}/\n"
    )


def run_from_averages(gguf_id: str, mlx_id: str, *, gguf_name=None, mlx_name=None,
                      store=None) -> list:
    g = averages_for(gguf_id, store=store)
    m = averages_for(mlx_id, store=store)
    return [
        format_side(gguf_name or f"{gguf_id} (GGUF)", g),
        format_side(mlx_name or f"{mlx_id} (MLX)", m),
    ]


def run_live(gguf_id: str, mlx_id: str, *, port=DEFAULT_PORT, urlopen=_urlopen,
             gguf_name=None, mlx_name=None, prompts=None) -> list:
    st = status(port, urlopen=urlopen)
    worker = (st or {}).get("worker") or st
    if not worker:
        raise RuntimeError(
            "Caravan is not running. Start it with caravan start, then run this again."
        )
    lines = []
    g_specs = None
    m_specs = None
    try:
        load_model(port, gguf_id, urlopen=urlopen)
        g_specs = measure_chat(port, prompts=prompts, urlopen=urlopen)
        lines.append(format_side(gguf_name or f"{gguf_id} (GGUF)", g_specs))
        load_model(port, mlx_id, urlopen=urlopen)
        m_specs = measure_chat(port, prompts=prompts, urlopen=urlopen)
        lines.append(format_side(mlx_name or f"{mlx_id} (MLX)", m_specs))
    finally:
        pass
    return lines


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="caravan bench",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--gguf", required=True, help="GGUF model id (for example gguf/qwen2.5-coder-7b-instruct-q4_k_m)")
    p.add_argument("--mlx", required=True, help="MLX model id for the same model (for example mlx-community/Qwen2.5-Coder-7B-Instruct-4bit)")
    p.add_argument("--yes", action="store_true",
                   help="load each model and measure; replaces the currently loaded model")
    p.add_argument("--from-averages", action="store_true",
                   help="print already-saved chat averages only; do not load or unload a model")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    p.add_argument("--gguf-name", default=None, help=argparse.SUPPRESS)
    p.add_argument("--mlx-name", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.from_averages:
        for line in run_from_averages(
            args.gguf, args.mlx,
            gguf_name=args.gguf_name, mlx_name=args.mlx_name,
        ):
            print(line)
        return 0
    if not args.yes:
        sys.stdout.write(steps_text(args.gguf, args.mlx, port=args.port))
        return 0
    try:
        lines = run_live(
            args.gguf, args.mlx, port=args.port,
            gguf_name=args.gguf_name, mlx_name=args.mlx_name,
        )
    except Exception as e:
        sys.stderr.write(f"Could not finish the comparison: {e}\n")
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
