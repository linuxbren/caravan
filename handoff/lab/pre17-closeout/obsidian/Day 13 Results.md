---
title: Caravan Day 13 results
tags: [caravan, benchmarks, day13]
created: 2026-11-04
updated: 2026-11-04
---

# Day 13 — Gemma shared-prefix fix on the split (Nov 4)

Back to [[Projects/Caravan/Caravan]]. Goal: fix Day 12's Gemma `shared-prefix-split-resync` (0% TTFT) so a new chat that shares a long system prompt reuses lead + packer KV. Flag still `--split-shared-prefix-cache`, **off by default**.

## What was wrong
After clone-into-reserved, the lead trimmed every layer. Gemma's rotating / sliding-window layers refuse trim once wrapped; packer `n` then disagreed → full re-prefill.

## Fix
Packer `trim_to`; lead trim helpers; `_materialize_shared_prefix` re-prefills the exact prefix on both halves when trim is unsafe. Store path logs `via=trim|materialize`. **174 tests OK.**

## TTFT, ~4k shared system prompt (fresh Day 13)
| Model | Off (s) | On hit (s) | Δ | via |
|---|---:|---:|---:|---|
| Gemma 4 26B-A4B 4-bit | 11.764 | 1.554 | **−86.8%** | materialize, reuse 4096 |
| Qwen3-30B-A3B 4-bit | 9.303 | 5.029 | **−45.9%** | trim, reuse 2048 |
| Llama 3.1 8B 4-bit | 17.473 | 8.898 | **−49.1%** | trim, reuse 2048 |

Quality (Gemma, seed=42, “Reply with exactly: PING”): off and on both `PING`.

## Write sanity (short prompt, draft off)
Qwen3 27.4 → 27.3 tok/s; Llama 15.8 → 15.9. No regression from the fix. (Quick check — not the Day 12 scoreboard method.)

## Cleanup from last night (before Day 13)
On EXO1 Hugging Face hub: deleted incomplete `Qwen3-30B-A3B-4bit` (4.3G), incomplete `Meta-Llama-3.1-8B-Instruct-4bit` (8.9M), shared blobs `31`+`6a` (1.1G) — **≈5.4G**. Also removed `~/v19rm` (264K) and five stale `lead.pid` files. Kept Llama GGUF, mlx-models Llama, bench-2026-11-04, model shortcut. Step-1 video commit: `fb90726`.

Sources: `handoff/lab/day13-gemma-prefix/`, experiments.md Day 13.


## Self-tune shared-prefix (same day, afternoon)

Folded into Day 10 learn-from-real-chats: when a model is first used (empty tuned settings, no flag), try shared-prefix on vs off, score **TTFT** on new chats that share a system prompt, keep the one-time store/materialize out of the on mean (hits only), promote if amortized still beats cold. Flag still overrides. **182 tests OK.**

| Model | Chose | Chats | Off cold mean (s) | Store (s) | Hit mean (s) |
|---|---|---:|---:|---:|---:|
| Gemma 4 26B-A4B 4-bit | **on** | 7 | 12.871 | 23.158 | 2.664 |
| Qwen3-30B-A3B 4-bit | **on** | 7 | 10.369 | 10.399 | 0.897 |
| Llama 3.1 8B 4-bit | **on** | 7 | 19.289 | 19.321 | 1.472 |

Sources: `handoff/lab/day13-spc-learn/`, experiments.md Day 13 (cont.).

## Day 13 post
Video: `2026-11-04_caravan-v3-day13-gemma-shared-prefix-self-tune_v21.mp4` (handoff/lab/videos/; draft, not posted yet).
