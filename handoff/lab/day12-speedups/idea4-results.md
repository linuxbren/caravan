# Day 12 Idea 4 — Shared prefix cache across sessions

**Setup.** `--split-shared-prefix-cache` (off by default). Long system preamble (~4k–9k toks depending on model/N), then new sessions sharing it. Split Llama / Gemma / Qwen3, LPM off. Measure prefill_s / ttft_s / how / peak_gb.

| Config | cold prefill / ttft | new_session how | new prefill / ttft | Δ prefill | Δ ttft |
|---|---|---|---|---|---|
| Llama n≈4k off | 17.41 / 17.50 | cold | 17.39 / 17.47 | — | — |
| Llama n≈4k **on** | 17.48 / 17.57 | **hit-memory** (reuse 2048) | **8.81 / 8.90** | **−49.6%** | **−49.4%** |
| Llama n≈7.7k off | 35.56 / 35.66 | cold | 35.54 / 35.63 | — | — |
| Llama n≈7.7k **on** | 35.62 / 35.71 | **hit-memory** (reuse 4096) | **17.72 / 17.81** | **−50.2%** | **−50.1%** |
| Qwen3 n≈4k off | 9.26 / 9.32 | cold | 9.26 / 9.31 | — | — |
| Qwen3 n≈4k **on** | 9.29 / 9.34 | **hit-memory** (reuse 2048) | **4.98 / 5.03** | **−46.4%** | **−46.2%** |
| Gemma n≈4.6k on | 11.71 / 11.79 | split-resync (reuse 0) | 11.72 / 11.79 | ~0% | ~0% |
| Gemma n≈8.9k on | 23.53 / 23.62 | split-resync (reuse 0) | 23.50 / 23.57 | ~0% | ~0% |

Miss-control (different preamble) stayed cold on all runs. Peak memory +~0.2–0.5 GB with cache entries held.

**Verdict.** **GO for TTFT/prefill on Llama + Qwen3** (≈46–50% faster new-session first token when ≥2048-token preamble is shared). Not a writing-speed win (by design). Gemma hit the library but lead/packer reuse counts disagreed → `shared-prefix-split-resync` full re-prefill; needs a packer-trim follow-up. Flag stays **off by default**.

Raw: `~/.caravan/bench-2026-11-03/day12-speedups/idea4/`.
