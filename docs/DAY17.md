# Day 17 — speed experiments, picker, identity, GGUF split in the web UI

Nov 6, 2026 ~8:48 PM CT → Nov 7 ~12:30 AM CT (America/Chicago). Branch `caravan-v3-mlx-split`.
Final verified HEAD: see "Verification run" below.

## What shipped (with where the numbers live)

| Area | Commits | Record |
|---|---|---|
| Native MTP (Orvena 4B head), prompt lookup, two chats, split helper matrix | 666cd8f … 1bef1e0 | [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md), `bench/results/day17/` |
| Picker: network-byte progress, one bar per Mini, inline "Step 2 · Choose where it lives", EXO2-only placement, On disk in Topology | b9aa2a2, a0c23a5, b8a6c84, 94c69a1, 7238b0d, ac48fde | [WEB.md](WEB.md) progress test record |
| Read / Write stats line under each reply | 53f6df7, 6adcaca, 462d202 | WEB.md |
| Resume, auto-retry, re-attach after web restart, "Any size" default, stall cause | 2842988, b944186, 1d0377c | WEB.md "Stop / Resume test record" |
| A3 logo, tagline "Your Mac minis. One model. Built in the open." | 44bec5f, 5928ea7 | [BRAND.md](BRAND.md) |
| Settings restyle, plain hints (no day numbers), HF token accepted state | 5b067ba, 112ae8a, a0b7e2a | WEB.md (hint → source map) |
| Helper download prompt (Download / Not now), per-helper On disk rows | 3828553, 7ab5499 | WEB.md |
| Theme parity (4 themes, desktop + phone) | fbe966d, 6f97c65 | `tools/theme_parity.js` |
| GGUF split in the web UI, rpc-server loopback + SSH tunnel, hardening, GGUF downloads | 92cc655 … db77249 | WEB.md, [SECURITY.md](SECURITY.md), DAY17-BENCHMARKS.md |
| Fixes found by the verification run | 8478335, 6f97c65 | below |

Headline numbers (all from DAY17-BENCHMARKS.md / WEB.md; failed runs kept there):
- Orvena 4B native MTP: Write 36.95 → 54.13 tok/s median (+46.5%), 550/560 proposals accepted.
- Prompt lookup (fixed gate): +44.4% on a repeated passage, −5.8% across all 8 mixed replies (stays experimental).
- Split Qwen3 30B MLX, two chats: +69.7% combined output without a helper; helper +25.4% on one chat but −29.4% with two.
- GGUF Qwen3 30B Q4_K_S: split EXO1+EXO2 34.72 tok/s vs one Mini 42.86 (split ~19% slower when it fits on one).
- Robustness: 5 split→MLX→single→split cycles, 20/20 steps OK.

## Verification run (Nov 7, 12:05–12:20 AM CT)

Independent end-to-end check on the live EXO1 :8190 UI with headless Chromium on Omarchy.

- Full suite: box **381 OK** (31.8 s). EXO1 first **347 run, 2 errors**: `agent/mlx_split.py`
  used `float | None` annotations, which Python 3.9 (EXO1 system python) can't import →
  fixed in **8478335** (`from __future__ import annotations`). After: EXO1 **OK (skipped=1)**, EXO2 **OK**.
- Theme parity against the live server: first **18/24**, rerun **20/24** — Models drawer failed in
  Meadow and Nebula (desktop + phone): their full drawer border moved every row 1 px and
  rewrapped long names. Fixed in **6f97c65** (drawers keep only the inner-edge border). After: **24/24**.
- Live UI checks (screenshots `day17-final-*.png`): tagline and A3 favicons served; reply stats
  "Read 22 tok at 66 tok/s · Write 35 tok at 50.9 tok/s · first token 0.39s · total 1.07s"
  (Qwen3 30B MLX, one Mini); Settings shows "Hugging Face token accepted — saved in Settings",
  input hidden, "Use a different token" opens the editor, Cancel closes it; hints carry no day
  numbers; Max download = "Any size"; clicking a quant shows Step 2 inline (cancelled, nothing
  downloaded); Topology On disk lists 5 helpers + Orvena MTP head individually.
- GGUF split via the UI: Settings → Qwen3-30B-A3B-Q4_K_S → "Split across 2 Minis · EXO1 + EXO2"
  → Load: ready in **26.1 s** page-to-ready (includes unloading MLX). Chat: "Read 14 tok at 70 tok/s
  · Write 329 tok at 34.0 tok/s · first token 0.20s · total 9.88s". Topology: EXO1 · LEAD and EXO2
  both show the GGUF. EXO2 rpc-server `127.0.0.1:50052` only; EXO1 tunnel `127.0.0.1:50062`,
  llama-server `127.0.0.1:8194`. From Omarchy, `exo1:50052` and `exo2:50052` refused.
  Web restart (KEEP_WORKERS) → status ready, split re-attached, chat streamed. Unload → idle in 2.0 s,
  0 rpc-server / llama-server / tunnel processes left. Qwen3 30B MLX single reload: **11.0 s** to ready.
- Not exercised live in this run: the helper Download/Not now prompt (needs a split MLX load with
  guess-ahead), an MTP/two-chat re-bench (numbers above are from the earlier runs).

## Open
- hf_xet keeps no partial files: Resume restarts a part-downloaded single file from 0 %.
- GGUF stage 2 (peers load their own tensors from disk) — see ROADMAP.
- llama.cpp b10819 → latest upgrade held until after GGUF split; then rerun the speed tests.
- Box `stash@{0}` (22:51 CT, Resume WIP on 5b067ba) looks superseded by 2842988; not dropped.
