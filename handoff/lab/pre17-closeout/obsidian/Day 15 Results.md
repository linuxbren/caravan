---
title: Caravan Day 15 results
tags: [caravan, day15, web-ui, self-tune]
created: 2026-11-04
updated: 2026-11-06
---

# Day 15 — diary (late Nov 4 → early Nov 5, America/Chicago)

Back to [[Projects/Caravan/Caravan]]. Skim note for the whole Day 15 stretch. Detail for the first web UI ship lives in [[Projects/Caravan/Day 15 Web Interface|Day 15 Web Interface]]; Brenden's manual numbers in [[Projects/Caravan/Human Testing|Human Testing]].

**Day 14** is still the planned break day (v22 improvements video). Not built yet; uncommitted.

## Shipped

### Web UI (298b301), then send / Gemma fixes (651ffbd)
- Browser chat on EXO1: model switch, streaming, 0.01 s timestamps, journey strip, Tailscale http://100.68.62.20:8190/
- Fixes after blank Gemma + stuck Send: cancel in-flight chat on Load/Unload, drain POST bodies, thinking placeholder + timeouts, strip end markers

### No replies over Tailscale http (a1fa68c)
- Page called `crypto.randomUUID`, which browsers block on plain http → chat never left the page
- Fallback ID + strip `<|eot_id|>`; verified chats on Llama / Gemma / Qwen3 / GPT-OSS

### Optimizations panel (17b477c / 45447ca)
- Switches: guess-ahead, self-tuning, shared start, two chats, fused kernels, memory compression, keep-warm (Auto + pinned on/off)
- **Apply & restart** reloads with picks; each reply shows `ran with:` / `chosen:`
- Bugfix: with two chats on, learned **guess-ahead off** was ignored — now honored

### Layout + panel polish
- Order top → bottom: chat, last reply, settings, clock sync, milestones, how far we've come, load progress, the string (815d4de / e1c25cd)
- Self-tuning row moved to top of Optimizations (2a4920f)
- Self-tuning → Auto resets every other option to Auto; pinned note; Auto buttons show resolved value e.g. `Auto (on)` (bced54e)

## Disk + Flint
- EXO1 nearly full (~1.1 GB free of 460 GB). Big buckets: `~/.caravan` ~209 GB (MLX copies ~93 GB, GGUF ~34 GB, etc.), `~/.exo` ~65 GB, `~/.ollama` ~41 GB, `~/Library` ~34 GB, `~/cv3` ~20 GB, `~/.cache` ~17 GB
- **Flint-abliterated Mix 24G GGUF** downloaded to **EXO2** `~/.caravan/models/Flint-abliterated-Mix-24G.gguf` (size + sha match HF). For single-Mini GGUF path testing; split would need MLX. Details also in [[Projects/Caravan/Ideas to Discuss|Ideas to Discuss]]

## Fresh auto-learn test
- Learned settings moved (not deleted) to EXO1 `~/.caravan/learn-backup-2026-11-04/`
- Restore later: `mv ~/.caravan/learn-backup-2026-11-04/*.json ~/.caravan/mlx/` then reload the model
- Manual test prompts handed over (lighthouse story, 1–60 spelled out, alphabet+animals, shared-start long paste, quality checks, self-tune short/long pairs)

## Self-tuning — how it behaves today
- Explores only every **4th** reply (`EXPLORE_EVERY = 4`); needs ~**3 samples** per side before trusting a mean
- Live (no reload) options only: guess-ahead, shared start, two chats
- Memory compression, fused kernels, keep-warm need a model restart — **not** in the explore loop yet (that's why pinned leftovers looked “stuck”)
- 96 hand combinations if you flip everything; self-tuning samples a smarter subset

## In progress now (early Nov 5)
- Extend self-tuning to **reload** options: `kv_bits` / memory compression, fused kernels, keep-warm
- **Deep optimize** button: Start → Caravan feeds prompts, queues reload trials, auto-reload when idle, walk-away; progress / cancel / done summary
- ETA honest (ballpark 15–45 min per model, not a fixed 20); Quick (live options) vs Deep (incl. reloads) under discussion
- Meet the name “Self Tuning” — no “except these three”

## Four news posts (flagged for later)
Logged in [[Projects/Caravan/Ideas to Discuss|Ideas to Discuss]]: llama.cpp Gemma graph (~2.8×), techfren / 0xSero interview, Rapid-MLX vs mlx-lm Qwen3.6, stackmini appliance. Plus Flint post → download above.

## Open after this stretch
- Settings file (#13c), node view (#14), or keep pushing fused / deep self-tune
- Clear space on EXO1 when ready (DeepSeek / Qwen2.5 14B / bench folder are easy wins; `.exo` left alone per “restore exo” preference)

### 01:05 CT — Self-tuning for every option + Deep/Quick optimize
- **Done:** code, 237 tests passing, commit f5c418e synced to all four copies, web server restarted (it re-adopted the running Qwen3 worker, so no reload). Headless page check passed with zero chats.
- **In progress:** no live Deep run yet, so no end-to-end timing. The running worker gets the new logic on the next Apply & restart.

## Closeout — Nov 5 (picker, placement, progress)

Day 15 kept going past the first web ship. The Models drawer and load path landed on `caravan-v3-mlx-split`:

### Model picker
- Search Hugging Face MLX / GGUF / Cloud; real sizes (no 4 GB guess); category chips + **New** + max-download filter
- **Capacity fit** (unload RAM, not current free); green / yellow / red / gray with plain reasons
- **N-node** from `~/.caravan/config.toml` `[web.nodes.*]`; `MAX_SPLIT_STAGES=2` caps runtime load
- On-disk list + HF cache / guess-ahead drafts cleanup; Delete stops fetches then removes on all Minis
- **Settings** model dropdown from disk inventory only (no static catalog phantoms)

### Placement + progress + HF token (27fcd76 … 0f5e46a)
- Download asks **1 Mini / K-split / copy-all**; default = smallest fit; saved as `caravan-placement.json`
- Truthful progress under **hf_xet**: hook → disk/xet → `nettop` bytes_in; “starting…”; ~30s stall
- Optional HF token in Settings → `~/.caravan/hf_token` (never echoed)

### Placement-aware load (d60c983)
- Bug: EXO1-only JevK5 4-bit still started a packer → `model not on packer Mini`
- Fix: `mode: one|all` → single non-split worker; `split` → lead+packer; preflight before kill
- `qwen3_5_text` remapped → `qwen3_5` for mlx_lm 0.32.2
- Verified: JevK5 4-bit loaded single on EXO1; chat reply **"Hello!"** (~39 write tok/s)

Open into Day 16: Topology for N nodes, Deep/Quick optimize live verify, single-Mini on a non-lead Mini, filter `caches` ghost on EXO2.
