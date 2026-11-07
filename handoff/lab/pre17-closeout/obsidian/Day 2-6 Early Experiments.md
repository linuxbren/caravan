---
title: Caravan Day 2–6 early experiments
tags: [caravan, benchmarks, day2, day3, day4, day5, day6]
created: 2026-11-05
updated: 2026-11-05
---

# Day 2–6 — early experiments (Oct 31 – Nov 1)

Back to [[Projects/Caravan/Caravan]]. Scoreboards that sit between Day 1 and Day 12, pulled from EXO1 `~/.caravan/bench-2026-10-31/` before those dumps can be deleted. High-level version story: [[Projects/Caravan/Version History]]. Later Day 12 numbers (keepalive + pipeline + guess-ahead already in): [[Projects/Caravan/Day 12 Results]], [[Projects/Caravan/v0-v3 Comparison]].

## Day 2 — v2 MLX worker, per-chat caches on disk (Oct 31)

One Mini (EXO1). Branch `caravan-v2-mlx-cache`. Raw: `bench-2026-10-31/v2/`.

**Seconds to first word (v1 → v2)** — the point of v2:

| | Qwen3 | Gemma 4 | GPT-OSS |
|---|---|---|---|
| Turn 2, 4k chat | 0.44 → 0.56 | **10.76 → 0.49** | **9.16 → 0.50** |
| Tokens re-read on turn 2 (4k) | reused → 46 | 4,034 → 36 | 4,041 → 32 |
| After restart, 4k | 16.0 → 0.59 | 16.0 → 0.64 | 12.7 → 0.52 |
| Turn 2, 16k | OOM → OOM | 55.1 → 0.72 | 37.3 → 0.59 |
| Writing tg128 | 47.0 → 49.1 | 39.8 → 42.2 | 35.3 → 37.4 |
| Reading pp512 / pp4096 | 439/396 → 438/380 | 427/384 → 397/393 | 434/441 → 433/442 |

GPT-OSS harmony fix: strip channel markup so turn 2 re-reads 32 tokens instead of 4,041. `--kv-bits 8` on Qwen tried and left off (16k still OOM; 4k reading 380 → 325).

## Day 2 evening — v2.1 wired-limit A/B (Oct 31)

Same session, rotated order. Raw: `bench-2026-10-31/v2.1/`. Question: was v2's slower Qwen 4k reading real, or day-to-day drift?

| tok/s (median) | v1 | v2 | v2.1 |
|---|---:|---:|---:|
| Qwen pp512 / pp4096 | 438.3 / 395.9 | 411.1 / 393.4 | 412.6 / 395.6 |
| Gemma pp512 / pp4096 | 429.8 / 383.3 | 394.7 / 376.4 | 396.4 / 375.5 |
| GPT-OSS pp512 / pp4096 | 431.6 / 418.1 | 425.2 / 415.4 | 423.8 / 415.4 |

Takeaway: side-by-side, v1/v2/v2.1 read Qwen 4k the same (393–396). Yesterday's gap was mostly drift. Holding the Metal wired limit at startup made v2.1 a little steadier. Qwen 4k resume still works (cold 11.6 s → turn 2 0.72 s → after restart turn 3 0.52 s).

## Day 4 — v3 split across two Minis (Oct 31, LPM on packer)

EXO1 lead / EXO2 packer over Thunderbolt. First split numbers (Low Power Mode was still on EXO2 — see next table). Writing ~28–42% slower than one Mini; memory per Mac roughly halves so Qwen3 holds a 16k chat.

| | Qwen3 v2.1 / v3 | Gemma v2.1 / v3 | GPT-OSS v2.1 / v3 |
|---|---|---|---|
| Write | 51.0 / 29.5 | 41.3 / 26.9 | 36.5 / 26.1 |
| Read 512 | 465 / 388 | 431 / 328 | 457 / 350 |
| Read 4k | 400 / 332 | 399 / 301 | 445 / 338 |
| Peak GB / Mac | 19.04 / 10.49 | 17.14 / 9.28 | 13.41 / 7.05 |
| 16k first read | OOM / 81.9 s | 46.5 / 61.3 s | 41.4 / 54.2 s |

Per-token hand-off: packer ~17 ms + cable **<1 ms** + lead ~16–20 ms. Cable is not the bottleneck; serial half-then-half is.

## Day 4 cont. — idea 4 split-each-layer: **no-go**

Synthetic GPU-wait over Thunderbolt: full exchange ~300–360 µs beyond compute, 48–96 exchanges/token. Estimate loses to one Mini by 25–60% and loses or ties v3. Parked. (Cable-only was ~60–90 µs; the big cost is stopping the GPU to hand results over.)

## Day 4 evening — LPM off rerun (v3.1)

EXO2 had been in Low Power Mode. Raw: `bench-2026-10-31/v3.1-rerun/`.

| Model | one Mac (v2.1) | v3 LPM on | v3 LPM off |
|---|---|---|---|
| Qwen3 30B | 51.0 / 465 / 400 | 29.5 / 388 / 332 | **30.4 / 451 / 408** |
| Gemma 4 26B | 41.3 / 431 / 399 | 26.9 / 328 / 301 | **27.7 / 411 / 375** |
| GPT-OSS 20B | 36.5 / 457 / 445 | 26.1 / 350 / 338 | **26.6 / 440 / 424** |

(write / read512 / read4k). LPM off: reading **+16–30%** (now within ~6% of one Mac); writing almost unchanged (+0.5–3%). Split-each-layer still no-go. Packer half now 2–4 ms faster than lead on Gemma/GPT-OSS → try uneven cut.

## Day 5 — idea 5 uneven layer cut (Oct 31)

Raw: `bench-2026-10-31/idea5-uneven/`. Single-chat writing stays flat (serial pipeline); best balanced cuts for multi-chat later:

| Model | Best K | Write even → best | Note |
|---|---|---|---|
| Gemma 4 | **16** (+1) | 27.6 → 27.4 | halves 17.8 / 0.82 / 17.0 ms |
| GPT-OSS | **13** (+1) | 26.8 → 26.6 | halves 17.4 / 0.85 / 18.5 ms |
| Qwen3 | **24** (even) | 30.0 → 30.5 (+2) | already balanced |

## Day 5 — GPU keepalive A/B (Oct 31)

Raw: `bench-2026-10-31/split-tax/ab/`. Spawn-per-wait Metal warm-up during peer wait. **Default on.** Long-lived pause thread rejected (Gemma write ~17.6).

| Model | off write / read512 / read4k | on write / read512 / read4k | Write Δ |
|---|---|---|---|
| Gemma 4 | 27.7 / 412 / 376 | **38.3** / 427 / 398 | **+39%** |
| GPT-OSS | 26.6 / 442 / 425 | **34.1** / 452 / 444 | **+28%** |
| Qwen3 | 30.4 / 451 / 410 | **45.6** / 462 / 429 | **+50%** |

Reading/quality not hurt. Peak mem unchanged.

## Day 6 — idea 1 several chats + stall fix (Oct 31 night → Nov 1)

Raw: `bench-2026-10-31/idea1-pipeline/`, `idea1-stallfix/`. Flag `--split-pipeline-chats N`, off by default. Uses idea-5 cuts.

**Two chats wall aggregate ≈1.6× one** (keepalive on):

| Model | N=1 write | N=2 wall | N=3 wall (after stall fix) | N=3 max wait to first word |
|---|---:|---:|---:|---:|
| Gemma 4 | 37.0 / 38.1 | 61.0 | 59.8 | 0.62 s (was ~4.2) |
| GPT-OSS | 33.5 / 34.2 | 54.0 | 53.0 | 0.61 s (was ~4.7) |
| Qwen3 | 44.4 / 45.7 | **72.7** | 70.8 | 0.59 s (was ~3.5) |

Fair packer pick (`(n_gen, t0)`) fixed third-chat starvation. One chat alone is not faster. Quality 3/3.

## Disposable bench bulk

EXO1 `~/.caravan/bench-2026-10-31/` (~17 GB) is mostly MLX prompt-cache `.safetensors` under `v2/*/mlx-cache/` and similar. Durable numbers are in this note, `handoff/lab/experiments.md` (Oct 31 / Nov 1 entries), and `docs/BENCHMARKS.md` (idea 1 / keepalive / idea 5). Safe to delete the bench folder for disk; keep models and settings.

## Sources
- EXO1: `~/.caravan/bench-2026-10-31/{v2,v2.1,v3.1-rerun,idea5-uneven,split-tax,idea1-pipeline,idea1-stallfix}/`
- Lab log: `handoff/lab/experiments.md` (sections for v2, v2.1, v3, LPM-off, idea 4/5, keepalive, idea 1)
- `docs/BENCHMARKS.md` idea 1 / keepalive / uneven-cut tables
