"""Shared short and long prompts for caravan bench and Auto-tune.

The first two short prompts are the ones Auto-tune has always used.
Three more short ones (code, explanation, list) make a set of five.
Long prompts are built-in, deterministic documents with a unique
opening so a shared-start cache does not make a later prompt look
faster. Sizes that will not fit a model's chat window are skipped.
"""
from __future__ import annotations

# The original Auto-tune pair — kept as the first two short prompts.
AUTO_TUNE_SHORT = (
    "Explain how a bicycle gear system works in about 150 words.",
    "Write a short Python function that checks whether a string is a palindrome, with a docstring.",
)

SHORT_PROMPTS = AUTO_TUNE_SHORT + (
    # code
    "Here is a Python function. Find the bug and write a corrected version.\n\n"
    "```python\n"
    "def average(nums):\n"
    "    total = 0\n"
    "    for n in nums:\n"
    "        total += n\n"
    "    return total / len(nums) - 1\n"
    "```",
    # explanation
    "In plain words, explain what a hash table is and when you would use one "
    "instead of a list. About 150 words.",
    # list
    "List eight ways to keep a long-running program reliable, one sentence each.",
)

# Bench long-prompt sizes, in tokens. Two prompts at each size.
BENCH_LONG_SIZES = (1024, 4096, 8192)
# Auto-tune uses one long prompt, skipped if it will not fit.
AUTOTUNE_LONG_TOKENS = 2048
REPLY_TOKENS = 192
# Chat-template and wrapper overhead reserved with the reply.
WINDOW_OVERHEAD = 64


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token). Good enough to size prompts."""
    return max(1, (len(text or "") + 3) // 4)


def fits_window(prompt_tokens: int, window, *, max_tokens: int = REPLY_TOKENS) -> bool:
    """True when this prompt plus a short reply should fit the chat window.

    If the window is unknown, we try the prompt and let the caller skip on failure.
    """
    if not window:
        return True
    try:
        w = int(window)
    except (TypeError, ValueError):
        return True
    if w <= 0:
        return True
    return int(prompt_tokens) + int(max_tokens) + WINDOW_OVERHEAD <= w


def skip_reason(prompt_tokens: int, window) -> str:
    try:
        w = int(window)
    except (TypeError, ValueError):
        w = window
    return (
        f"this model's chat window is {w}, and a "
        f"~{_size_label(prompt_tokens)}-token prompt would not fit."
    )


def _size_label(n: int) -> str:
    n = int(n)
    if n >= 1000 and n % 1024 == 0:
        k = n // 1024
        return f"{k}k"
    if n >= 1000 and n % 1000 == 0:
        return f"{n // 1000}k"
    if n >= 950:
        return f"{max(1, int(round(n / 1024)))}k"
    return str(n)


def size_label(n: int) -> str:
    return _size_label(n)


def fresh_prefix(tag: str) -> str:
    """A unique opening so this prompt does not share a start with an earlier one."""
    return (
        f"({tag}. This opening is only for this prompt, so a shared start "
        f"from an earlier prompt is not reused.)\n\n"
    )


def with_fresh_prefix(text: str, tag: str) -> str:
    return fresh_prefix(tag) + (text or "")


def short_prompts(*, tag_prefix: str = "Short") -> list:
    """The five short prompts, each with a unique opening."""
    out = []
    n = len(SHORT_PROMPTS)
    for i, p in enumerate(SHORT_PROMPTS):
        out.append(with_fresh_prefix(p, f"{tag_prefix} {i + 1} of {n}"))
    return out


def _code_body(series: int, target_tokens: int, used: int) -> str:
    parts = [
        f'"""Utility module, series {series}. Deterministic bench/Auto-tune text."""\n',
        "from __future__ import annotations\n\n",
    ]
    i = 0
    while estimate_tokens("".join(parts)) + used < target_tokens:
        i += 1
        parts.append(
            f"def helper_{series}_{i}(value, scale={i + series}):\n"
            f"    \"\"\"Series {series} helper {i}: scale a value and fold in {i}.\"\"\"\n"
            f"    total = 0\n"
            f"    for n in range(max(1, {i} % 17 + 3)):\n"
            f"        total += (value + n + {series}) * scale\n"
            f"        if total % 5 == 0:\n"
            f"            total = total // 2 + {i}\n"
            f"    return total + {i * series}\n\n"
        )
        if i > 20000:  # safety
            break
    return "".join(parts)


def _doc_body(series: int, target_tokens: int, used: int) -> str:
    # A plain document with a clear recommendation, unique per series.
    opening = (
        f"A short guide to keeping a workshop in good order, edition {series}.\n\n"
        f"The main recommendation is to finish one job before starting the next, "
        f"and to write down what you changed so the next person can follow it.\n\n"
    )
    parts = [opening]
    topics = (
        "tools on the wall", "labels on drawers", "a clean bench",
        "a written checklist", "a spare set of bits", "good light",
        "a place for scraps", "a quiet minute at the end of the day",
    )
    i = 0
    while estimate_tokens("".join(parts)) + used < target_tokens:
        topic = topics[i % len(topics)]
        i += 1
        parts.append(
            f"Section {i} (edition {series}), about {topic}. "
            f"People work faster when they can find what they need, and they "
            f"make fewer mistakes when the last change is written down. "
            f"In this edition, item {i} is a reminder: put {topic} where the "
            f"next person expects it, then check it off. Repeating this "
            f"habit, day after day, is how a workshop stays ready. "
            f"Edition {series}, paragraph {i}.\n\n"
        )
        if i > 20000:
            break
    return "".join(parts)


def build_long_prompt(kind: str, target_tokens: int, series: int) -> str:
    """A deterministic long code file or document, sized to about target_tokens."""
    target = int(target_tokens)
    series = int(series)
    kind = "code" if kind == "code" else "document"
    tag = f"Long {kind} #{series}, about {size_label(target)} tokens"
    prefix = fresh_prefix(tag)
    if kind == "code":
        instruction = (
            "Read this Python module and, in one short paragraph, say what it "
            "does. Then name three functions and what each one is for.\n\n"
        )
    else:
        instruction = (
            "Summarize this document in one short paragraph, then answer: "
            "what is the main recommendation?\n\n"
        )
    used = estimate_tokens(prefix + instruction)
    body = _code_body(series, target, used) if kind == "code" else _doc_body(series, target, used)
    text = prefix + instruction + body
    # Trim if we overshot by a lot; leave a little slack so we stay near the target.
    while estimate_tokens(text) > target + 32 and len(text) > len(prefix) + len(instruction) + 80:
        text = text[: int(len(text) * 0.98)].rsplit("\n", 1)[0] + "\n"
    return text


def long_prompts_for_size(target_tokens: int) -> list:
    """Two long prompts at this size: a code file and a document, different openings."""
    return [
        build_long_prompt("code", target_tokens, series=1),
        build_long_prompt("document", target_tokens, series=2),
    ]


def autotune_long_prompt(chat_window=None) -> tuple:
    """One ~2k-token long prompt for Auto-tune, or (None, reason) if it will not fit."""
    target = AUTOTUNE_LONG_TOKENS
    if not fits_window(target, chat_window):
        return None, skip_reason(target, chat_window)
    return build_long_prompt("document", target, series=10), None


def autotune_prompt_list(chat_window=None, *, tag_prefix: str = "Auto-tune short") -> tuple:
    """Five short prompts plus one long (~2k) if it fits. Returns (prompts, skip_note)."""
    prompts = short_prompts(tag_prefix=tag_prefix)
    kinds = ["short"] * len(prompts)
    long_p, note = autotune_long_prompt(chat_window)
    if long_p:
        prompts.append(long_p)  # already has a unique opening
        kinds.append("long")
    return prompts, kinds, note


def chat_window_from(status=None, settings=None, launch=None) -> int | None:
    """Best-effort running chat window from a status or settings payload."""
    for src in (launch, status, settings):
        if not isinstance(src, dict):
            continue
        for key in ("chat_window", "ctx", "context_length", "n_ctx", "max_context"):
            v = src.get(key)
            try:
                if v is not None and int(v) > 0:
                    return int(v)
            except (TypeError, ValueError):
                pass
        for nested_key in ("active", "worker", "gguf", "current", "launch"):
            nested = src.get(nested_key)
            if isinstance(nested, dict):
                w = chat_window_from(nested)
                if w:
                    return w
    return None


CACHE_NOTE = (
    "Each prompt starts with a unique opening so a shared-start cache "
    "does not make later prompts look faster."
)
