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
- Helper Download/Not now prompt: tested live afterwards, see the section below. Not re-run here:
  an MTP/two-chat re-bench (numbers above are from the earlier runs).

## Open
- hf_xet keeps no partial files: Resume restarts a part-downloaded single file from 0 %.
- GGUF stage 2 (peers load their own tensors from disk) — see ROADMAP.
- llama.cpp b10819 → latest upgrade held until after GGUF split; then rerun the speed tests.
- Box `stash@{0}` (22:51 CT, Resume WIP on 5b067ba) looks superseded by 2842988; not dropped.

## Day 17 video
`handoff/lab/videos/2026-11-07_caravan-v3-day17-tour_v23.mp4` — 125 s, 1280x720 H.264, silent, 30 single-line captions in a bottom band (each checked to fit the frame width, no wrapping). Captions: `2026-11-07_day17-tour_captions.txt`; generator: `make_day17_video.py`. Numbers come from the Day 17 fact sheet / DAY17-BENCHMARKS.md.

## Helper Download / Not now — live end-to-end (Nov 7, 12:20–12:24 AM CT)

Setup: Qwen3 30B-A3B 4-bit MLX split EXO1+EXO2 (both Minis have the files; placement file
temporarily set to split), guess-ahead on. To simulate a missing helper, EXO1's
`~/.caravan/mlx-models/drafts/Qwen3-0.6B-4bit` (343,236 KB, sha1 list saved) was moved aside.
Split load ready in ~16 s.

- **Prompt: PASS.** `/api/helpers` offered `Qwen3-0.6B-4bit`; the page opened "A 335 MB helper can
  make qwen3-30b-a3b-4bit write faster. Download it?" with Download / Not now / Close
  (`day17-final-helper-ask.png`). 335 MB is the pairing-table estimate (labelled so); real
  download 0.34 GB, 343,228 KB on disk.
- **Not now: PASS.** Dialog closed, `guess-ahead-state.json` → `web_download_answers.qwen3-30b-a3b: false`,
  no job started, a fresh page load did not reopen it.
- **Change mind: PASS.** Settings → Guess-ahead → "Helper download…" reopened it → Download:
  0.34 GB in 36 s (~13 MB/s steady, brief 1 MB/s dip at 27 s), live progress "0.15/0.34 GB · 14.1 MB/s · ETA 12s",
  then "Downloaded. It will be used on the next model load." Answer flipped to true; offer gone.
  Weight files matched the original byte-for-byte (only README/.gitattributes vs local
  caravan-*.json metadata differ).
- **Applies next load: PASS.** Reload ready in 13 s; log "split speculate: draft Qwen3-0.6B-4bit, k=3, vocab=exact".

Effect (one run each, max_tokens 200, temp 0, `/no_think`; Write tok/s):

| Prompt | No helper | Helper | Change | Helper acceptance |
|---|---|---|---|---|
| Count 1–60 | 44.98 | 56.13 | +24.8% | 74.5% |
| Python prime function | 45.00 | 48.98 | +8.8% | 71.0% |
| 150-word prose | 45.07 | 27.18 | −39.7% | 48.3% |

Mixed, matching the earlier matrix: helps predictable text, hurts free prose. Single runs, not a benchmark.

Restored: original helper folder moved back (sha1 list identical), test download removed, state
file removed (did not exist before), placement back to `one · EXO1`, Qwen3 30B MLX single on EXO1 ready.

Noticed, not fixed: the helper dialog is an unstyled white box in Amber (not themed); the chip
row showed "GUESS-AHEAD OFF" while the split ran without a helper.
Revision (Nov 7 ~12:30 AM CT): Settings scene uses a full-width crop (was letterboxed); speed results and the lockdown check are now text cards built only from DAY17-BENCHMARKS.md / SECURITY.md numbers; 7 long captions shortened; fit check now uses the rendered bbox with a 1120 px limit.

## Fix: helper dialog theme + honest guess-ahead chip (Nov 7, 12:25–12:30 AM CT, d07731c)

- **Dialog.** The helper prompt (`helpers.js`, a plain `<dialog>`) had no base style, so Amber and
  Green showed the browser's white box; only Meadow/Nebula styled `dialog`. Added one base `dialog`
  rule using the theme variables (`--bg2`, `--text`, `--line`, `--mono`). Live computed colours:
  Amber rgb(12,12,8)/rgb(255,233,160), Green rgb(8,17,10)/rgb(184,245,192), Meadow and Nebula keep their glass.
- **Chip.** The worker reports `guess_ahead` true only when it is split *and* a helper (or MTP head)
  is loaded (`mlx_worker.active_settings`). With On chosen and no helper on disk it ran
  without one and the chip said a bare "off". Now, when On was chosen but nothing runs:
  "guess-ahead on · no helper on disk, not running" (split, `guess_ahead_loaded` false) or
  "guess-ahead on · split only, not running" (one Mini). Auto/Off unchanged.
- Live check: split Qwen3 30B + helper moved aside → chip "ON · NO HELPER ON DISK, NOT RUNNING" in all 4 themes;
  one Mini + On → "ON · SPLIT ONLY, NOT RUNNING"; Auto → "OFF". Nothing downloaded (dialog closed with
  Close, no answer saved). Helper restored (hashes identical), placement back to one Mini.
- Tests: box suite OK; JS parses. Live theme parity 23/24 on the first run (the Nebula Models list
  hadn't finished loading: 95 vs 135 elements), **24/24** on the rerun.
- Screenshots: `day17-final-helper-ask-{amber,green,meadow,nebula}.png`,
  `day17-final-chip-{amber,green,meadow,nebula}.png`, `day17-final-chip-single-on.png`.
