"""Clock-offset and chat-gap math for the Caravan web UI (Day 15).

Pure functions, no I/O. The browser and the Mini each have their own clock.
We estimate offset = Mini_time - browser_time with an NTP-style exchange:

    offset ≈ t_server - (t_client_send + rtt/2)

Several samples give a median offset and a half-range uncertainty.
Times that arrived on the Mini are then projected into browser-local time
as browser ≈ mini - offset, so the UI can line up "you hit send" with
"Caravan received it" honestly.
"""
from __future__ import annotations

from statistics import median
from typing import Iterable, Optional, Sequence


def estimate_offset(samples: Sequence[dict]) -> dict:
    """samples: [{client_send, server_recv, client_recv}, ...] in seconds
    (same time base within each machine; floats ok).

    Returns {offset_s, uncertainty_s, rtt_s, n} or empty if no usable samples.
    offset_s is (Mini - browser): add it to a browser stamp to get Mini time,
    subtract it from a Mini stamp to get browser time.
    """
    offsets = []
    rtts = []
    for s in samples:
        try:
            t0 = float(s["client_send"])
            t1 = float(s["server_recv"])
            t2 = float(s["client_recv"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (t2 >= t0):
            continue
        rtt = t2 - t0
        # Classic NTP: θ = ((t1 - t0) + (t1 - t2)) / 2 = t1 - (t0+t2)/2
        # Equivalent to t1 - (t0 + rtt/2).
        off = t1 - (t0 + rtt / 2.0)
        offsets.append(off)
        rtts.append(rtt)
    if not offsets:
        return {"offset_s": None, "uncertainty_s": None, "rtt_s": None, "n": 0}
    off_m = float(median(offsets))
    rtt_m = float(median(rtts))
    # Half the range of offsets, floored by half the median RTT (can't know
    # better than that without a two-way sync protocol).
    spread = (max(offsets) - min(offsets)) / 2.0 if len(offsets) > 1 else 0.0
    unc = max(spread, rtt_m / 2.0)
    return {
        "offset_s": round(off_m, 6),
        "uncertainty_s": round(unc, 6),
        "rtt_s": round(rtt_m, 6),
        "n": len(offsets),
    }


def mini_to_browser(mini_s: float, offset_s: Optional[float]) -> Optional[float]:
    """Project a Mini wall-clock stamp into browser-local seconds."""
    if offset_s is None or mini_s is None:
        return None
    return float(mini_s) - float(offset_s)


def browser_to_mini(browser_s: float, offset_s: Optional[float]) -> Optional[float]:
    if offset_s is None or browser_s is None:
        return None
    return float(browser_s) + float(offset_s)


def chat_gaps(timestamps: dict) -> dict:
    """Compute gaps (seconds) between the four milestones.

    Expected keys (any missing → that gap is None):
      sent_browser, received_mini, first_word_mini, done_mini
    All in the *same* time base (caller should project first).
    """
    def g(a, b):
        if a is None or b is None:
            return None
        return round(float(b) - float(a), 4)

    sent = timestamps.get("sent")
    recv = timestamps.get("received")
    first = timestamps.get("first_word")
    done = timestamps.get("done")
    return {
        "send_to_receive_s": g(sent, recv),
        "receive_to_first_s": g(recv, first),
        "first_to_done_s": g(first, done),
        "send_to_done_s": g(sent, done),
        "send_to_first_s": g(sent, first),
    }


def reply_stats(usage: dict, wall_s: Optional[float] = None) -> dict:
    """Derive per-reply cards from a worker `usage` object (OpenAI-shaped
    with Caravan's `usage.caravan` extension). Never invents numbers: missing
    fields stay None.
    """
    usage = usage or {}
    caravan = usage.get("caravan") or {}
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")
              if isinstance(usage.get("prompt_tokens_details"), dict) else None)
    prefill_s = caravan.get("prefill_s")
    ttft_s = caravan.get("ttft_s")
    total_s = caravan.get("total_s")
    if wall_s is not None and total_s is None:
        total_s = wall_s

    def rate(n, secs):
        if n is None or secs is None:
            return None
        try:
            secs = float(secs)
            n = int(n)
        except (TypeError, ValueError):
            return None
        if secs <= 0 or n < 0:
            return None
        return round(n / secs, 2)

    # Writing speed: completion tokens over (total - ttft), matching how
    # Day 12 scoreboards measure decode. Fall back to total if ttft missing.
    write_s = None
    if total_s is not None and ttft_s is not None:
        try:
            write_s = max(float(total_s) - float(ttft_s), 1e-6)
        except (TypeError, ValueError):
            write_s = None
    elif total_s is not None:
        write_s = float(total_s)

    how = caravan.get("how")
    shared_hit = False
    if isinstance(how, str):
        shared_hit = "shared-prefix-hit" in how or how.startswith("shared-prefix")

    speculate = caravan.get("speculate") or {}
    guess = None
    if isinstance(speculate, dict) and speculate:
        guess = {
            "k": speculate.get("k"),
            "from_draft": speculate.get("from_draft"),
            "accepted_frac": speculate.get("accepted_frac"),
        }

    learn = caravan.get("learn") or {}
    tuned = None
    if isinstance(learn, dict) and learn.get("winner"):
        tuned = learn.get("winner")

    split = caravan.get("split")

    return {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "cached_tokens": cached,
        "total_s": total_s,
        "ttft_s": ttft_s,
        "prefill_s": prefill_s,
        "read_tok_s": rate(pt, prefill_s),
        "write_tok_s": rate(ct, write_s),
        "how": how,
        "shared_start": shared_hit,
        "guess_ahead": guess,
        "tuned": tuned,
        "split": split,
        "peak_gb": caravan.get("peak_gb"),
    }


# Display cleanup for streamed replies (Qwen/Gemma/GPT-OSS end tokens that
# sometimes leak into delta.content even after the worker stops).
_REPLY_MARKERS = (
    "<|im_end|>",
    "<|end|>",
    "<|end_of_text|>",
    "<|return|>",
    "<|eot_id|>",
    "</s>",
    "<eos>",
    "<|turn|>",
    "<turn|>",
    "<|turn>",
    "<channel|>",
    "<|channel|>",
    "<|channel>",
    "<|message|>",
)


def strip_reply_markers(text: str) -> str:
    """Remove known end/channel markers from user-visible reply text."""
    if not text:
        return text
    out = text
    for m in _REPLY_MARKERS:
        if m in out:
            out = out.replace(m, "")
    return out

