---
title: Caravan Day 1 results
tags: [caravan, benchmarks, day1]
created: 2026-11-05
updated: 2026-11-05
---

# Day 1 — v0 → v1 improvements (Oct 30, one Mini)

Back to [[Projects/Caravan/Caravan]]. Single Mac mini M4 24 GB (EXO1). Branch `improvements-1-3`. Video LAB-2026-10-30-04.

Three improvements measured in one evening: rebased llama.cpp so sliding-window chats reload after restart, auto f16/q8 KV, early MLX via `mlx_lm.server`.

## Saved chats reload after restart (llama.cpp, ~16k)

Seconds to first word: cold / warm-in-memory / **after full restart**. `cache_n` is how many tokens the slot actually restored.

| Model | v0 old build | rebased (v1) | old + `--swa-full` |
|---|---|---|---|
| GPT-OSS 20B (2×18k) | 45.5 / 0.77 / **46.3** (cache_n 0) | 44.8 / 0.71 / **0.65** (cache_n 16,086) | 47.3 / 0.75 / 0.59 |
| Gemma 4 26B (1×18k) | 54.9 / 0.70 / **56.1** (cache_n 0) | 53.0 / 0.84 / **0.93** (cache_n 16,286) | 55.7 / 0.74 / 0.48 |
| Qwen3 30B (no SWA) | 80.0 / 1.01 / 1.18 | 78.4 / 0.91 / **1.10** (no regression) | — |

Takeaway: v0's old build wrote slot files that wouldn't reload for SWA models (restart ≈ cold). Rebase fixed it. `--swa-full` also works but is the blunt workaround.

## Writing / reading speed, v0 → rebased+q8 → v1 auto KV (tok/s)

| Metric | Qwen3 (auto→q8_0) | Gemma 4 (auto→f16) | GPT-OSS (auto→f16) |
|---|---|---|---|
| Write tg128 | 41.4 → 42.5 | 34.4 → 34.8 → 36.7 | 35.9 → 37.1 → 37.1 |
| Read pp512 | 361.1 → 401.9 | 333.9 → 383.5 → 399.9 | 374.7 → 434.0 → 436.8 |
| Read pp4096 | 338.0 → 356.4 | 354.9 → 377.8 → 379.7 | 403.0 → 452.3 → 453.6 |
| Quality | 3/3 | 3/3 | 3/3 |

Most of the reading gain is the rebase. f16 adds ~2 write tok/s on Gemma / GPT-OSS at 16k and costs ~1.7 GB on Gemma.

## Early MLX (`mlx_lm.server` step a) — headline speeds

| Model | pp512 | pp4096 | tg128 | turn1 / turn2 / after restart (s) | peak | quality |
|---|---:|---:|---:|---|---:|---|
| Gemma 4 26B-A4B 4-bit | 427.2 | 383.8 | 39.8 | 10.5 / **10.8** / 16.0 | 18.6 GB | 3/3 |
| GPT-OSS 20B MXFP4-Q8 | 434.4 | 441.4 | 35.3 | 9.1 / **9.2** / 12.7 | 13.9 GB | 3/3 |
| Qwen3 30B-A3B 4-bit | 439.4 | 395.7 | 47.0 | 7.5 / **0.44** / 16.0 | 19.0 GB | 3/3 |

Qwen3 already reuses within a session via the server's prompt cache; Gemma and GPT-OSS still re-read everything on turn 2 and after restart. That's the Day 2 (v2) gap.

## Disposable bench bulk

EXO1 `~/.caravan/bench-2026-10-30/` (~30 GB) is mostly leftover session/KV slot `.bin` caches under `improvements/*/slots/`. The durable numbers live here and in `handoff/lab/experiments.md` (2026-10-30 evening). Deleting the bench folder does **not** remove models or `tuned-settings.json`.

## Sources
- EXO1 raw: `~/.caravan/bench-2026-10-30/improvements/` (`r-*`, `x-*`, `s-*`, `m-*` `results.json`)
- Lab log: `handoff/lab/experiments.md` — "2026-10-30 (evening) — Caravan v1"
- Later scoreboard cells for v0/v1 writing/reading also appear in [[Projects/Caravan/v0-v3 Comparison]]
