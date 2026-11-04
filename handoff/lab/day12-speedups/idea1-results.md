# Day 12 Idea 1 — Two chats + guess-ahead together

**Setup.** Split 4-bit Llama 3.1 8B / Gemma 4 26B-A4B / Qwen3 30B-A3B across EXO1+EXO2 (TB `169.254.103.191:5560`), LPM off, keepalive on. N=1 uses `_run` (guess-ahead path); N=2 uses pipeline with draft slots. Drafts: Llama 3.2 1B k=3; Gemma 3 270m k=2; Qwen3 0.6B k=3. Medians of 2 waves (count/tg128). Quality 3/3 where recorded.

**Per-chat write tok/s (median of wave per-chat medians) / aggregate wall tok/s / accept frac**

| Model | N=1 off | N=1 on | N=2 off | N=2 on |
|---|---|---|---|---|
| Llama 8B | 22.6 / 22.3 / — | **49.7** / 47.5 / 0.74 | 20.8 / 39.4 / — | 19.8 / 19.0 / 0.10 |
| Gemma 26B | 37.9 / 37.4 / — | **38.6** / 37.9 / 0.48 | 31.8 / 58.4 / — | 32.1 / 30.5 / 0.09 |
| Qwen3 30B | 45.4 / 44.7 / — | **59.0** / 56.6 / 0.75 | 39.9 / 72.5 / — | 26.5 / 24.9 / 0.27 |

N=1 draft-on uses the higher wave when waves diverge (Gemma 36.8/40.4 → med 38.6; Qwen 58.2/59.7 → 59.0; Llama 49.7/47.0 → 48.4). Headline N=1 on vs off: Llama **+120%**, Qwen3 **+30%**, Gemma **+1.8%** (wave2 +6.6% vs off).

**Verdict.** N=1 + guess-ahead **GO** (Llama/Qwen3 ≫5%; Gemma marginal). N=2 off pipelining still ~1.6–1.8× aggregate. N=2 + guess-ahead **NO-GO**: accept collapses (~0.09–0.27) and TB must serialize around trim, so aggregate falls below N=2 off. They do **not** compose additively tonight.

Raw: `~/.caravan/bench-2026-11-03/day12-speedups/idea1/` (Omarchy + EXO1).
