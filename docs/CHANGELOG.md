# Changelog

## Day 26 — Download progress under the model you clicked

- In the Models list, the download progress card appears right under
  the model you clicked Download on. It stays visible there even if
  you close the file list, and moves to the top of the list only
  when that model is not currently shown. See [Day 26](DAY26.md).

- The `caravan bench` First token bars now follow the printed seconds:
  a shorter bar is sooner, matching the label "First token (s, lower
  is better)". Reading and Writing bars are unchanged. `--ascii` uses
  the same scaling; `--details` is unchanged. The Day 25 sample chart
  was redrawn with the same numbers. See [Day 26](DAY26.md).

- GGUF Prompt lookup and Guess-ahead are Auto, Off, or On under
  Advanced. Auto stays off until a test finds a winner. Auto-tune may
  try Prompt lookup last when only one chat is in use, and treats a
  garbled trial as a loss. Guess-ahead On needs a smaller same-family
  model already on this Mac; Caravan will not download one. See [Day 26](DAY26.md).

- Voice design notes (listening first) are in [VOICE](VOICE.md).
  No listening code is shipped. See [Day 26](DAY26.md).
- This follow-up does not change `agent/`, `runtime/`, or the
  requirements files, so a `caravan update` from the Day 25 pin
  keeps a loaded model running. The web page still restarts. No
  `day26` tag yet.

## Day 25 — GGUF Self-tuning, Chat window, Two chats, and caravan bench

- GGUF Self-tuning learns from real chats, proposes one quiet trial,
  and fills the same Before and After lines Auto-tune uses. A change
  reloads when you are not mid-reply.
- Chat window (Auto and offered sizes) with a sane Auto default from
  the model and this Mac's memory. Two chats is available for GGUF;
  Auto keeps one chat.
- `caravan models` lists downloaded models with a friendly name, GGUF
  or MLX, and the id to copy, and marks the currently loaded one.
- `caravan bench` compares a GGUF model to its MLX counterpart. It
  does not invent numbers. The default output is a compact chart of
  reading, writing, and first-token speed; `--details` (also
  `--text`) adds the reply-stats lines; `--ascii` and `NO_COLOR` use
  plain '#' bars. A plain name finds the matching pair; `--gguf` and
  `--mlx` still work. Default: five short prompts and a long-prompt
  series; `--short` or `--long` for just one. `--from-averages`
  draws the same kind of chart. After a live run, the original model
  is put back. First measured result (1st Mac, Qwen2.5 Coder 7B):
  GGUF Q4_K_M Write 22.3 tok/s, MLX 4bit Write 23.5 tok/s. A later
  full-series run on the same Mac is in [Day 25](DAY25.md) and
  [BENCHMARKS](BENCHMARKS.md).
- Auto-tune (MLX and GGUF) uses the same five short prompts plus one
  ~2k-token long prompt, scores on medians including long-prompt
  read speed, and still treats a garbled trial as a loss.
- While Auto-tune is running, the Start or Tune again button becomes a disabled **Tuning…** state with a small campfire flicker, and a live step line says what is happening (for example "Measuring the current setup · short prompt 3 of 5"). Previous Before and After lines are hidden until the run finishes (and come back if it fails or is cancelled). A **Tuning…** badge is visible from the chat page; Self-tuning shows a subtler "Self-tuning a setting…" note. A brief **Done** or **Nothing faster found** highlight appears when the run finishes. See [Day 25](DAY25.md).
- `caravan bench --yes` shows a small campfire animation on a
  terminal with the current step and elapsed time. Piped output,
  `NO_COLOR`, and `--quiet` use a plain step line or stay silent.
  Ctrl-C still puts the original model back.
- Does not change `agent/`, `runtime/`, or the requirements files, so
  a `caravan update` from the Day 24 pin keeps a loaded model running.
  The web page still restarts. See [Day 25](DAY25.md).

## Day 24 live review — Campfire theme, and Start until a model is tuned

- Campfire replaces Nebula: Amber, Green, Meadow, Campfire. Drawn in
  SVG and CSS (no photos). A saved Nebula choice opens as Campfire.
  The Webb image and credit are removed.
- Auto-tune's primary button says Start until this model has a saved
  result, then Tune again; Reset tuning returns it to Start. A
  `caravan update` from the previous Day 24 pin keeps a loaded model
  running.

## Day 24 live review — Auto-tune section

- Auto-tune sits below Self-tuning, outside Advanced, with Tune again,
  Reset tuning, and the Before and After lines in an indented block.
  Auto-tune works whether Self-tuning is On or Off. A `caravan update`
  from the previous Day 24 pin keeps a loaded model running.


## Day 24 live review — Tune again, next to Self-tuning

- Tune again sits next to Self-tuning, outside Advanced, and always runs
  a fresh trial on the loaded model. Reset tuning clears saved results
  without unloading. When nothing is faster, one plain line is shown
  instead of two identical Before and After lines. The Self-tuning hint
  is for each model, not only MLX. A `caravan update` from the previous
  Day 24 pin keeps a loaded model running.


## Day 21 follow-up — Mac installation and documentation

- Friendly Mac-owner README and current Day 20/21 setup, Balance, restore,
  auxiliary title-worker and read-only Thunderbolt guidance.
- Mac-only no-Git/no-Homebrew bootstrap, checksum-verified source and uv,
  private Python, read-only doctor, and safe per-user control command.
- Prepared repeatable checksummed source-package build and daily checklist.
- Experimental: no signed app/pkg, automatic pairing, fully locked dependencies
  or fresh-account/FileVault-on certification. Day 21 tag remains unchanged.



## Unreleased

### Day20 — day20-2026-11-09
- Hermes main/title cache isolation and durable exact system/tool prefix reuse; full toolset retained.
- Opt-in tiny title helper with narrow routing, strict fallback and guarded startup.
- Measured negative trials: automatic prefix prewarm not enabled, KV8 not retained; lookup and thinking-off remain explicit options.
- Honest Qwen3.5-family single/split matrix: full Huihui single GPU OOM, split succeeds; smaller models slightly faster single. Nested decoder memory guard corrected.
- Bounded restore retry and reconnecting Omarchy tunnels; unattended main model recovery proven at64.735s. New auxiliary startup still awaits physical reboot verification.
- Day20 experiment walkthrough, film sources and unsent X drafts. Full notes: [DAY20-RELEASE.md](DAY20-RELEASE.md).


### Day 18 (Nov 7, evening CT) — overview: [DAY18.md](DAY18.md)
- Day 18 (Nov 7): Dark Champion 21B split verified coherent after 07249e7 at 16/16 (14.2 tok/s write, 0.47 s first token, 387 tokens). 24/8 failed with HTTP 507 (EXO2 1.51–1.71 GB free vs 1.75 GB margin). Split Stage rope-scaling notes now logged (flushed stderr instead of print). Per-reply timing line in lead.log (read/cached, read tok/s, write tok/s, first token, total). 486 tests OK.
- Download finished + nothing loaded: asks **Load now / Not now** (all four themes); no silent auto-load.
- Resume continues a partial file with HTTP Range (verified live on both Minis) instead of starting from 0.
- Split-download progress: no double count of `.incomplete`, total = what that Mini really fetches, never above it; "stalled?" only when nothing grows.
- Hotfix: the split point (`packer_layers`) is saved with each download and used by the model list and load; catalog and download defaults match (Dark Champion 21B usable again).
- GGUF stage 2: GGUF downloads go to every Mini; at a split load each peer fills its rpc-server cache from its own copy, so big tensors don't cross the link. rpc-server stays loopback + SSH tunnel.
- Optimize now: native MTP and adaptive lookup sweeps (one at a time, 3% margin, losers skipped); GGUF tuning knobs and plan (runner not wired yet).

### Day 17 verification (Nov 7, 12:20 AM CT)
- `agent/mlx_split.py` imports on Python 3.9 again (EXO1's 2 failing test modules).
- Meadow/Nebula drawers keep only the inner-edge border: live theme parity 20/24 → 24/24.
- Overview and verification numbers: [DAY17.md](DAY17.md).
- Helper download dialog follows all four themes (was a white box in Amber/Green).
- Guess-ahead chip says "on · no helper on disk, not running" / "on · split only, not running" instead of a bare "off" when On was chosen.

### Picker Resume + stall diagnosis (Nov 6, late)
- "Stalled" downloads were hf_xet buffering shards while the network kept moving; progress now
  adds network deltas to the bytes already on disk.
- Restart after Stop no longer gets killed by the old job's cancel flag.
- Resume on stopped/failed cards (same files/placement; finished files reused), network
  auto-retry 3x, re-attach after a web restart, Max download defaults to Any size.
- HF token verified in the fetch interpreter on both Minis (whoami OK).
- Raw numbers: WEB.md "Stop / Resume test record".

- GGUF split from the web UI: Settings → Model lists GGUFs on the lead with
  *Where it runs* (one Mini / split across K Minis, default smallest that fits).
  llama.cpp RPC: rpc-server on each peer bound to 127.0.0.1, reached over SSH
  tunnels; only the lead needs the file. Tracked PIDs, clean Stop, plain errors
  with collapsed details. Qwen3 30B Q4_K_S split: 34.7 tok/s write vs 42.9 on
  one Mini. CLI packer no longer binds rpc-server to 0.0.0.0 (allowlisting
  gate, fails closed). See [WEB.md](WEB.md), [SECURITY.md](SECURITY.md).

- Theme parity: Amber, Green, Meadow and Nebula now share one layout. Theme
  variables are scoped to `html[data-theme]` (they were leaking onto the
  theme-switch buttons), and Meadow/Nebula keep the shared monospace for controls
  (their own face only in chat messages). Checked with `tools/theme_parity.js`.

- Replace Settings benchmark-heavy help with plain explanations, measured and
  scoped percentage hints, and clear mixed/negative results. Keep raw measurements
  in docs; [WEB.md](WEB.md) maps each hint to its source row. Copy-only live-page
  mirror avoids a web restart while a remote model is active.

- Align Settings with Models/Topology: shared panels, compact controls and Close
  buttons, consistent type/spacing, stacked option rows, and a wider phone drawer.
  No settings or API behavior changes. Eight Chrome layout checks pass; before/after
  evidence and audit are recorded in [WEB.md](WEB.md). Full suite: 340 tests pass.

- Change the header tagline to “Your Mac minis. One model. Built in the open.”

### A3 Caravan identity
- Finalized the three linked Minis, without an underline, beside a lowercase
  outlined monospace wordmark. Header follows all four theme accents.
- Added SVG masters, pixel-grid 16/32 favicons, 180/512 PNGs and amber app icon.
- Chrome checks: 1280px and 390px in Amber, Green, Meadow and Nebula; no
  horizontal overflow. Static local previews only; no workers restarted.
- Asset usage, font license and screenshot record: [BRAND.md](BRAND.md).

### Day17 — approved live split complete; negative N2 helper result retained
- Final10:08:53PM CT UI refresh preserves QwenPID89648; served help/chip verified.
  [API proof](../bench/results/day17/split-final-ui-proof.json).
- Same-source e6640a0,36/36 uncapped replies. Qwen split baselineN1/N2 aggregate
  **41.54/70.49tok/s**; helperN1/N2 **52.11/49.77tok/s**. N1 Write45.04→60.01,
  N2 Write39.81→27.83; N2 helper is slower, stays experimental, defaults unchanged.
- All count/sorting3+7 checks pass; strict-format fails in every mode due to
  trailing Markdown spaces. Helper74.59% drafted/generated is not proposal acceptance.
- UI chip/help show measured gains AND regressions. Socket-owner fix survived all
  paired waves;152 tests+4subtests pass. Prior stalls/timeouts retained.
- Original singleEXO1 Qwen restored ready, Auto preferences; pre-existing queued
  KV4 trial applied (benchmarks pinnedKV16). No download/copy/deletion needed;
  existing EXO2 Qwen and Orvena weights kept, EXO2 workers stopped.
- All139 raw rows,127 responses,12 transport errors plus non-row failure evidence:
  [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md),
  [raw data/manifest](../bench/results/day17/manifest.json),
  [reproducible quality/summary](../bench/results/day17/complete-summary.json).

### Day17 approved live split — socket ownership fix
- Live N2 testing exposed a real race: HTTP memory guards read the same split
  socket as the MLX scheduler/status calls. Initial stalls/errors are retained.
- Queue memory-stat RPCs to the single socket owner; run read-only checks between
  drained rounds, but keep cache-mutating admin calls deferred until idle.
- Two regression tests added;51 focused tests+4subtests pass. See
  [Day17 record](DAY17-BENCHMARKS.md) for initial split N1 results and N2 failures.

### Picker progress + placement + On disk in Topology (Nov 6)
- Remote download progress was always 0: the ssh measure script was `repr()`-quoted
  (invalid shell). Now `shlex.quote`d; errors are shown, not hidden.
- hf_xet downloads are invisible on disk; progress now also counts per-process
  network bytes (`nettop`) for the fetch's process tree.
- Monotonic per-Mini progress with speed/ETA, Done/Stopped/Failed, survives drawer reopen;
  no auto-load over a ready model.
- Inline "Step 2 · Choose where it lives" with a button naming the action.
- Placement saved on the Mini that holds the weights; single-Mini models on any node
  (e.g. EXO2-only) are usable and route to that node.
- On disk moved to the Topology drawer as one combined list with location notes.
- Chat: `Read N tok/s · Write M tok/s` under each reply (prompt/prefill, fallback TTFT).
- Chat: stats line now reads `Read 58 tok at 279 tok/s · Write 235 tok at 38.6 tok/s · first token 0.25s · total 6.34s`; unknown pieces are dropped.
- Tests: full box suite green (340 OK) via `PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`. Fixed /api/models/stop dropping the socket when the packer SSH stop fails (now 502 JSON, status=error); HTTP tests stub SSH/node probes; stale tests updated for ba60fa9 layout (no "ran with:", progress/Topology out of main order) and FakeMgr.state for the Day 17 spanned key. Day 17 "152 passed" was a focused 8-file pytest subset.
- Numbers: see WEB.md "Test record".

### Day 17 — earlier 9:28 PM CT verification
- **145 passed +4 subtests** on49b55a8. All85 raw rows (including8 transport
  errors and partial queue attempt) retained in the linked benchmark manifest.
- Qwen30B4-bit restored ready, singleEXO1, Auto preferences/KV16. Scoped stop
  removed only the EXO2 experiment process; Orvena weights/head kept.
- UI restart preserves workers; screenshots remain pending parent capture.

### Day 17 — earlier pre-approval performance follow-up
- Qwen single-Mini paired queue baseline: Write50.51/50.48tok/s, harness
  aggregate46.08/46.52tok/s. This is serial queuing, **not split overlap**;
  no default change. Initial partial11/12-row attempt retained as well.
- Split N≥2 draft-block fixes remain unit-tested only; live split awaits approval.
- All runs and negative quality checks remain in the linked raw record below.

### Day 17 — completed matching-target MTP measurement
- Orvena4B EXO2 ABBA: **36.95→54.13 median Write tok/s (+46.51%)**, **98.21%**
  accepted proposals; median TTFT0.1748→0.17545s. 12/12 uncapped replies; count
  and exact-answer equality; code passes3 generated+7 extra tests but assertion
  examples differ (not bit-exact). No compatibility claim for Qwen3 30B-A3B.
- Initial Qwen adaptive run is negative: **50.45→47.20tok/s**, zero accepted
  drafts even on repeated text. Fixed high-overlap one-miss poisoning.
  Fixed-gate copy50.11→72.37tok/s, mixed50.24→47.31;
  keep default OFF. UI shows both results. Experimental loads disable learning
  and skip queued reload trials. Native rejects compressed/conflicting modes.
- Complete prompts, per-run numbers, failures, CT times and commits:
  [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md),
  [raw results](../bench/results/day17/),
  [reproducible summary](../bench/results/day17/complete-summary.json).

### Day 17 follow-up — worker ownership safety
- UI termination validates tracked PID, exact repository script and node-local
  endpoint; stale PID markers fail closed and PID reuse is rechecked before
  escalation. No broad process-name kills. Archived lab sweeps removed too.
- Single-Mini rewindable targets support request-local adaptive prompt lookup;
  overrides restore after cancellation/errors. Two-chat split semantics unchanged.
- Brenden identified the earlier UI switch/stop as his own exploration. All
  interrupted data stays in [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md).

### Day 17 — performance experiments
- EXO2 native-head run archived in full: 4 completed responses + 8 transport
  failures after a concurrent UI model switch/stop killed the isolated worker.
  One capped count pair was byte-identical, 36.49 vs 54.40 tok/s, but **not a
  validated speedup/quality claim**. Full raw rows, CT times and collision
  evidence: [Day 17 benchmark record](DAY17-BENCHMARKS.md).
- Adaptive PL/two-chat reruns remain pending: original single-Mini worker cannot
  enable these without reload; no defaults changed. Live split run still needs
  approval. The broad cleanup found during that attempt is fixed in the
  follow-up above; the independent worker survived a normal UI reload.
- Matching-target native MTP adapter for dense Qwen3.5/Orvena, greedy-only and
  single Mini, behind `--native-mtp`; downloads head tensors directly from HF.
  Target-specific **Native MTP · test** choice appears only with a head installed.
- Split N≥2 verification cache accounting fixed: rejection trim, all-accepted
  last-draft replay, and early-stop rewind; per-session detokenizers isolated.
  Unit tested; live split benchmark awaits approval.
- Adaptive prompt-lookup experimental control uses overlap_on=0.50, stays off by
  default. Two-chat availability and pending split verification are explicit.
- All benchmark numbers, failures, prompts/settings and CT timestamps:
  [Day 17 benchmark record](DAY17-BENCHMARKS.md).

### Nebula theme
- Fourth theme, **Nebula**: the actual JWST "Cosmic Cliffs" (Carina Nebula) image as the background, unblurred, in WebP (about 282 KB) with a JPEG fallback in `proxy/web/assets/`. A very slow drift and zoom stops under `prefers-reduced-motion`. Credit: "Image: NASA, ESA, CSA, STScI" (shown in Nebula). Source: https://esawebb.org/images/weic2205a/ (file: https://cdn.esawebb.org/archives/images/large/weic2205a.jpg), CC BY 4.0. `web_server.py` now serves `/assets/*` from `proxy/web/assets/` with image MIME types, so EXO1 needs a web restart (with `CARAVAN_WEB_KEEP_WORKERS=1`) when this ships.
- Dark frosted-glass panels with light text. Accents are copper `#e0893a` (the Send button, with dark text) and ice blue `#7cc4ff`. Theme bars go rust, then copper, then ice blue. CRT layers are off; rounded sans font, with monospace kept for stats.
- Specifications: "To first word" is now "To first token".

### Meadow theme
- Third theme, **Meadow**, next to Amber and Green in the theme switch (saved in localStorage `caravan-theme`). The idea is a way to "digitally touch grass": sky, trees, fields and a river, but only as an impression.
- No photos and no external assets. The background is an inline SVG (sky gradient, clouds, tree masses, field bands, misty river) blurred about 34px, so it reads as calm colour and never competes with the chat or the stats.
- Frosted-glass panels with dark green-ink text for AA contrast. Scanlines, vignette, bloom and text glow are off. Rounded sans font stack; monospace stays for stats and logs. Leaf green and sky blue accents; the "Theme" bar style uses leaf green, green, then sky blue, and green-yellow-red is unchanged.
- A very slow drift (about ±1.2% over 120 s) that turns off under `prefers-reduced-motion`.

### Layout fixes (all themes)
- Settings drawer: the option grid only goes to two columns when the drawer is wide enough, so nothing is cut off at 1280.
- Phone width: the chat empty state sits below the stacked chat buttons instead of under them.

### Fixes (Day 16 follow-up)
- Topology: each node card shows only the model it actually runs. Single mode puts the model on the lead (or the remote worker Mini); other nodes show "idle · no model". Split shows the model on every stage with its layer range. `/api/nodes` now re-gathers right away when the model/mode changes, so the label no longer lags one gather behind.
- Chat empty state: when a model is ready it reads "<model> is ready. Type a message below to start."; the "Ready when you are… open Settings to load it" text only appears when nothing is loaded.

### Day 16 — Topology N-node, non-lead single Mini, optimize fix
- **Topology drawer** builds one card per configured Mini (`/api/nodes`); handles 1 / 2 / 3+ and offline nodes without blanking last-good stats.
- **Single-Mini load on a non-lead Mini** (e.g. EXO2-only placement): start `mlx_worker` there, SSH-tunnel chat/health to the web host.
- **Self-tune / Deep optimize**: `_tuned_entry` now uses `:single` vs `:spanned` from the running worker so coverage stops stuck at 0/3 on one-Mini loads.
- **Disk list**: skip non-model folders (`caches`, `.cache`, …) — `~/.exo/models/caches` no longer looks installed.



- **Placement-aware load.** One-Mini / copy-to-all placements start a single
  non-split worker (no packer). Split placements keep lead+packer. Preflight
  checks files first. `qwen3_5_text` remapped to `qwen3_5` for mlx_lm 0.32.2
  (JevK5). Finding: EXO1-only download still required the packer Mini.


- **Truthful download progress (hf_xet).** File-only progress froze at 0% while
  `nettop` showed 3–6 MB/s (JevK5). Fallback: fetch JSONL hook → disk/xet →
  `nettop` bytes_in. UI: MB/s, ETA, %, “starting…”, stall ~30s. Live fetches
  reattach after a web-only restart.

- **Download placement.** Quant click chooses 1 Mini / K-split (≤ MAX_SPLIT_STAGES)
  / copy-to-all; unfit options disabled with reasons; default = smallest fit.
  Saved as `caravan-placement.json`; Settings/load respect it; Delete still all Minis.

- **HF token.** `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` env, `~/.cache/huggingface/token`,
  or Settings field → `~/.caravan/hf_token` on each Mini (never echoed to the page).

- **Settings model list from disk.** Dropdown uses N-node MLX inventory (complete shards / tokenizer / no `.incomplete`, capacity not red). Static catalog phantoms (gpt-oss, gemma) removed; partial trees show disabled with a reason. Picker refresh updates Settings after download.

- **Model picker N-node.** Nodes from `~/.caravan/config.toml` `[web.nodes.*]` (default still EXO1/EXO2). Fit/chips/download/Stop/Delete/disk iterate online/configured nodes; 1-node never suggests split; `MAX_SPLIT_STAGES=2` caps actual load with a “N-Mini split coming later” note. See MODEL_PICKER / CONFIGURATION.

- **Model picker (phases 1–2).** Models drawer (see [MODEL_PICKER.md](MODEL_PICKER.md)):
  HF/GGUF/Cloud catalog; capacity-based fit (not current free RAM) with plain
  reasons; live search; real HF sizes; category + **New** chips; max download
  size filter; parallel lead+packer shard download with byte progress; Stop/Delete
  kill fetches on both Minis; on-disk HF cache + guess-ahead drafts cleanup.
  Still open: conversion, GGUF-llama-server load, live Cloud.

- **Memory guard (lead).** Estimate KV vs reclaimable RAM before generate; trim
  oldest turns into `~/.caravan/memory` Markdown notes (EXO1 only) and BM25-recall
  snippets into a short system note. Topology shows reclaimable RAM; UI notes
  moved/recalled counts. Config: `memory_dir`, `memory_safety_gb`.

- **Topology / chat.** 500 ms node poll while visible; sticky stats; 20–100 °C
  temp bar; Heat/Theme colors; Mac mini variant A cards; ioreg GPU % (not
  macmon keepalive 100%); full chat history sent (not only the latest message).

What changed in each Caravan version, newest first. Numbers come from
[BENCHMARKS.md](BENCHMARKS.md); the day-by-day story is in
[LOG.md](LOG.md); what's next is in [ROADMAP.md](ROADMAP.md).

"4k" and "16k" are chat lengths in tokens (a token is about ¾ of a word).
"Reading" is how fast a prompt is taken in, "writing" is how fast the
reply comes out.

## Unreleased

### Fixed
- `bench/v3/speculate_bench.py`: skip write_tps when `(total_s - ttft_s) ≤ 0`
  (short quality replies no longer ZeroDivisionError).
- First-load / quality `answer_ok` scores only the final answer after
  stripping think/channel blocks (Gemma `<channel|>` closer). Thought-only
  output no longer passes. Gate probes use 256 tokens.

### Added
- ROADMAP #13(a) auto-tune: when `--split-packer-layers` /
  `--split-pipeline-chats` are omitted, pick K from Mini memories + layer
  sizes (packer hello `mem_total_gb`) and pipeline chats from free memory
  (cap 2, never swap). Explicit flags win. Startup logs `auto split:` /
  `auto pipeline:`. Mini-verified auto ≡ hand-tuned on Qwen3, Llama 3.1
  8B, Qwen2.5 14B (quality 3/3). See BENCHMARKS / METHODOLOGY.
- Llama 3.1 8B Mini-verified guess-ahead suite (keepalive / pipeline N=1–3 /
  nodraft vs auto-pair / first-load / shut-off / download prompt). Count
  **22.7 → 51.5**; `llama3` → `mini_verified` in `guessers.json`. See
  BENCHMARKS.
- Top open-LLM family → guesser map in `agent/guessers.json` (Llama 3.x,
  Qwen3/2.5, Gemma 4/3/2, Distill-Qwen, SmolLM; skips for GPT-OSS, Mistral,
  Phi-4, native DeepSeek). `verification`: `mini_verified` | `vocab_checked`.
  Live EXO1 download-prompt check (yes/no remembered; caches restored).
- Idea 3 guess-ahead auto-pair: `agent/guessers.json`, vocab match/remap,
  ask-once download (lead only), first-load quality/speed gate (cached),
  mid-chat shut-off below break-even. Flags `--no-split-draft`,
  `--split-draft-auto-download`, `--split-draft-skip-first-load`.
  Docs: CONFIGURATION, MLX-SPLIT, ROADMAP idea 3, METHODOLOGY.md.
- Idea 3 prompt-lookup (`--split-prompt-lookup`) + draft prefill fix;
  Gemma-3-270m draft path; GPT-OSS rotating-KV speculate guard.
- Idea 3 guess-ahead prototype: `--split-draft-model`, `--split-speculate-k`
  (off by default). Packer `trim` for speculative reject. See BENCHMARKS.

## v3.4 (tag `v3.4`, Nov 1 2026)

Branch `caravan-v3-mlx-split`. Day 6 lab video refreshed to the techie-friend
cut (LAB-2026-11-01-03 / v12); v10–v11 kept and marked superseded. Post-style
audience guidance in `handoff/README.md` §5/§6. Not merged to `main`.

## v3.3 (tag `v3.3`, `f31d15a`, Nov 1 2026)

Branch `caravan-v3-mlx-split`. Idea 1 several chats + N=3 stall fix + first
Day 6 lab video (LAB-2026-11-01-01 / v10). Not merged to `main`.

- **Idea 1 N=3 stall fix.** `_pipe_round` preferred the just-led chat for
  the next packer fetch, so a third chat waited ~4 s (tg128). Fair pick by
  `(n_gen, t0)` + admit one prefill per loop. N=3 max TTFT ≤0.62 s; wall
  aggregate ≈ N=2. N=2 unchanged. See
  [BENCHMARKS.md](BENCHMARKS.md#idea-1-several-chats-at-once-oct-31nov-1-mlx).

- **Idea 1: several chats at once (off by default).** `--split-pipeline-chats N`
  (env `CARAVAN_MLX_SPLIT_PIPELINE_CHATS`) overlaps Packer 1's work for chat B
  with the lead's layers for chat A when N≥2. Default N=1 is unchanged.
  With idea-5 cuts + keepalive: two chats ≈1.6× aggregate writing vs one;
  N=3 stall fixed Nov 1 (see bullet above). Flag-off single-chat matches
  keepalive baseline (~38 / 34 / 46 tok/s). Bench:
  `bench/v3/pipeline_bench.py`. Details:
  [BENCHMARKS.md](BENCHMARKS.md#idea-1-several-chats-at-once-oct-31nov-1-mlx).

## v3.2 (tag `v3.2`, `cb61970`, Oct 31 2026)

Branch `caravan-v3-mlx-split`. GPU keepalive default on (writing +28–50%)
and Day 5 lab video LAB-2026-10-31-05. Not merged to `main`.

## Notes that shipped in v3.2 (were unreleased after v3.1)

On branch `caravan-v3-mlx-split`.

**New**

- **GPU keepalive while waiting on the peer (default on).** During
  turn-taking each Mini sits idle ~15–20 ms; Metal then pays ~5 ms extra
  on the next graph build + eval. A short-lived side thread runs a tiny
  `mx.eval` during the blocking recv (`GpuKeepalive` in `mlx_split.py`).
  `--split-keepalive` on by default; `--no-split-keepalive` or
  `CARAVAN_MLX_SPLIT_KEEPALIVE=0` disables. A long-lived pause thread
  was tried and rejected (writing regressed).

- **GPU-wait test (`bench/cable/gpu_wait.py`).** Both Macs run every
  layer's two exchanges at the same time with GPU work sized like half of
  each model's layer. One exchange costs about 330–360 µs, mostly waiting
  for the GPU. Splitting each layer across both Macs would lose to one
  Mac on all three models and only roughly tie v3 on GPT-OSS: no-go,
  parked. See [BENCHMARKS.md](BENCHMARKS.md#gpu-wait-for-splitting-each-layer-oct-31-thunderbolt-4).

**Benchmarks**

- **Uneven layer split (idea 5).** Packer +1 / +2 layers vs even: no
  single-chat writing gain (serial pipeline). Best balanced cuts for
  idea 1: Gemma K=16, GPT-OSS K=13, Qwen3 even. See
  [BENCHMARKS.md](BENCHMARKS.md#uneven-layer-split-oct-31-mlx-idea-5).

- **GPU keepalive A/B** (`0f14e72`, LPM off, medians of 2): writing
  Gemma 4 38.3 vs 27.7, GPT-OSS 34.1 vs 26.6, Qwen3 45.6 vs 30.4 tok/s
  (on vs off); reading 512 / 4k slightly up; peak mem unchanged; quality
  3/3. `sudo powermetrics` needs a password on the Minis; lead CPU%
  median rose during waits under keepalive. See
  [BENCHMARKS.md](BENCHMARKS.md#gpu-keepalive-while-waiting-on-the-peer-oct-31-mlx).

- **v3 split rerun with Low Power Mode off on both Macs.** EXO2 (the
  packer) had been in Low Power Mode for all earlier two-Mac numbers.
  With it off, on v3.1 (`f68d15e`): writing 30.4 / 27.7 / 26.6 tok/s
  (was 29.5 / 26.9 / 26.1), reading 16–30% faster and now within about
  6% of one Mac, 8-bit writing 20.7 / 18.4 / 20.1 (was 20.6 / 18.1 /
  19.8), quality 3/3 on all six. See
  [BENCHMARKS.md](BENCHMARKS.md#v3-rerun-with-low-power-mode-off-oct-31-mlx-v31).
- **GPU-wait test rerun** with Low Power Mode off: about the same per
  exchange at batch 1 (325–366 µs), higher at batch 4 (403–414 µs).
  Splitting each layer is still a no-go (21.1 / 24.7 / 26.7 tok/s
  estimated). Raw JSON: `bench/cable/results/2026-10-31-gpu-wait-lpm-off.json`.

**Docs**

- GPU keepalive results and flag docs (LOG, ROADMAP idea 6,
  BENCHMARKS, MLX-SPLIT, CONFIGURATION, handoff experiments).
- Setup note: Low Power Mode must be off on both Macs for benchmarks
  (BENCHMARKS Method, MLX-SPLIT "Running it", `bench/v3` and
  `bench/cable` READMEs, ROADMAP known issues).

## v3.1 (tag `v3.1`, `2260d2e`, Oct 31 2026)

On branch `caravan-v3-mlx-split`, after the `v3` tag. Pushed with tag
`v3.1`; not merged into `main`.

**New**

- **Shard size check at startup (MLX split).** Before a split stage
  loads, it checks that every shard file it needs is complete: the size
  must match what the file's own safetensors header implies, and, when
  `mlx_split_fetch.py` downloaded it, the size Hugging Face lists (saved
  in `caravan-split-sizes.json` next to the files). A cut-off download or
  copy now stops the stage with an error that names the file and the
  `mlx_split_fetch.py` command to fetch it again from Hugging Face. It
  never falls back to getting files from the other Mac. 6 new unit tests
  (126 in total).
- **Cable-timing benchmark (`bench/cable/`).** Times one round trip over
  the Thunderbolt cable through Caravan's own split link and through
  plain TCP, at each model's per-layer exchange size. About 100 µs for
  one chat (the first guess was 50 µs). Result for splitting each layer
  across both Macs: not a go yet over Thunderbolt 4; see
  [BENCHMARKS.md](BENCHMARKS.md#cable-timing-oct-31-thunderbolt-4).

## v3 (tag `v3`, `df68468`): one MLX model split across two Macs

Branch `caravan-v3-mlx-split` (off `main` at `c026359`), pushed with tag
`v3`; not merged into `main`. Commits: `b03d1e9` (the split), `a167835` (cache fix for hybrid
models, bench client), `d68e094` (docs and results), `83f86a9` (lead /
packer names), `14dfcb4` and `8a64430` (roadmap), `df68468` (docs).

**New**

- **Split an MLX model across two Macs.** The packer Mac (Packer 1) runs
  the first half of the layers, the lead Mac runs the rest, picks each
  token and serves the API. They talk over one TCP connection on the
  Thunderbolt cable. The proxy needed no change. See
  [MLX-SPLIT.md](MLX-SPLIT.md).
- **Chat memory on both halves.** Each Mac keeps and saves its own half of
  each chat's cache. A saved chat is restored only when both halves are on
  disk and match; otherwise it's read again from scratch.
- **Split download (prototype CLI).** `agent/mlx_split_fetch.py` downloads
  only the files a Mac needs for its own layers from Hugging Face. Not yet
  run by the agent.
- Worker flags `--split-role`, `--split-peer`, `--split-listen`,
  `--split-packer-layers`; config `mlx.split.packer` /
  `mlx.split.packer_layers`; env `CARAVAN_MLX_SPLIT_PACKER` /
  `CARAVAN_MLX_SPLIT_PACKER_LAYERS`; `GET /caravan/split` on the lead.
  See [CONFIGURATION.md](CONFIGURATION.md#mlx-split-across-two-macs-v3).
- Bench client `bench/v3/split_client.py`.

**Why Caravan has its own link instead of MLX's.** MLX runs the model on
each Mac. Only MLX's ready-made ways of linking two Macs were skipped:
its standard link (`mx.distributed` ring) breaks on messages of about
2 MB or more over our Thunderbolt 4 cable, its fast direct-memory link
(jaccl, RDMA) needs Thunderbolt 5, and mlx-lm's built-in splitting only
covers Qwen models.

**Measured** (Oct 31, two Mac minis M4 24 GB, side by side with v2.1 on
one Mac):

- Memory per Mac roughly halves: Qwen3 30B 19.04 → 10.49 GB, Gemma 4 26B
  17.14 → 9.28 GB, GPT-OSS 20B 13.41 → 7.05 GB. Qwen3 30B now holds a 16k
  chat on MLX (on one Mac it runs out of memory).
- The cost: writing is 28–42% slower (Qwen3 51.0 → 29.5, Gemma 4 41.3 →
  26.9, GPT-OSS 36.5 → 26.1 tok/s), reading 16–25% slower, and resuming a
  chat takes 0.1–0.4 s longer. The two Macs take turns on every token;
  the cable is not the problem (under 1 ms and under 10 KB per token).
- Bigger versions that don't fit on one Mac now run split, all 3/3 on the
  quality checks with a 16k chat: Qwen3 30B 8-bit (20.6 tok/s, 18.12 GB
  per Mac), Gemma 4 26B 8-bit (18.1 tok/s, 15.58 GB), GPT-OSS 20B 8-bit
  (19.8 tok/s, 12.13 GB).
- Split download, Qwen3 30B 8-bit: lead 16.65 GB and packer 21.09 GB
  instead of 32.44 GB each.

**Fixed**

- Hybrid-attention models (Qwen3.6, `qwen3_5_moe`) crashed the lead at
  load; the stage now builds its cache from the full model first.

**Renamed (old names deprecated, still accepted)**

The Mac you talk to is now the **lead**; the other Macs are **packers**,
numbered in layer order (Packer 1 runs the first layers); the whole group
is the **string**. These replace "head", "front" and "tail".

| New | Deprecated alias |
|---|---|
| `--split-role lead` / `packer` | `--split-role head` / `front` |
| `--split-packer-layers K` | `--split-front-layers K` |
| `mlx.split.packer` / `packer_layers` | `mlx.split.front` / `front_layers` |
| `CARAVAN_MLX_SPLIT_PACKER` / `_PACKER_LAYERS` | `CARAVAN_MLX_SPLIT_FRONT` / `_FRONT_LAYERS` |
| `mlx_backend.build_lead_command()` / `build_packer_command()` | `build_head_command()` / `build_front_command()` |
| `mlx_split_fetch.py --role lead\|packer --packer-layers K` | `--role head\|front --front-layers K` |

When both are given, the new name wins. Saved split caches keep their old
stage id, so caches saved before the rename still load. Internal code
names (role values `head` / `front` / `tail`, `supervisor.build_head_command()`
and `build_tail_command()` for llama.cpp) are unchanged.

**Known limits:** slower than one Mac; two Macs only; the split link is
unauthenticated (keep it on the cable); the agent and the launchd plists
don't start a split yet (start both workers by hand); `--kv-bits` with the
split is untested; the bench talked to the worker directly (the proxy path
was smoke-tested only). GPT-OSS 120B still doesn't fit across two 24 GB
Macs (parked).

## v2.1 (`b9ebeb7`, docs `24adc11`, tag `v2.1`)

- The MLX worker sets Metal's wired limit once at startup and holds it
  (`--wired-limit startup`, the default).
- Optional deferred first MLX save (`mlx_save_min_turns`).
- Benchmarks now compare versions side by side in one session. With that
  method v1, v2 and v2.1 read a 4k prompt at 396, 393 and 396 tok/s
  (Qwen3).
- `main` later got docs-only commits: `c026359` points at the
  `linuxbren/llama.cpp` fork.

## v2 (`f57af3b`, `6d4bdb0`, `fac73b8`, `f73eafb`, `7835efd`)

- **Caravan MLX worker** (`agent/mlx_worker.py`) with one cache per chat,
  reused from message to message and saved to disk. Turn 2 of a 4k chat:
  Gemma 4 10.76 → 0.49 s, GPT-OSS 9.16 → 0.50 s. First message after a
  restart: 12.7–16.0 → 0.52–0.64 s.
- GPT-OSS replies cleaned up: the answer in `content`, the reasoning in
  `reasoning_content`.
- Per-Mac cap on saved chats: 200 files / 50 GB, llama.cpp and MLX
  together, least recently used first, never active chats.

## v1 (`32b9756`, `737fea2`, `c846e65`)

- Rebased llama.cpp (upstream `5047748f`, fork branch `caravan-patches`
  = `86e16204`). A 16k chat after a restart: GPT-OSS 46.3 → 0.65 s,
  Gemma 4 56.1 → 0.93 s. Faster 4k reading (GPT-OSS 403 → 454, Gemma 4
  355 → 380, Qwen3 338 → 356 tok/s).
- MLX models routed through the proxy to plain `mlx_lm.server` (step a).
- Automatic KV cache type: f16 when it fits, else q8_0.

## v0 (`45ed2c2`, Oct 30)

The baseline: configurable target model, cleanup of saved slots after 30
days, proxy performance work, explicit llama-server flags, docs for the
public repo. Benchmarked on the older llama.cpp base, now fork branch
`caravan-patches-v0` (`2f26123e`).

## Before v0 (Sep 2026)

GGUF split across two Macs with llama.cpp RPC, the proxy, launchd
services, the Thunderbolt cable (packer cold load 7–11 min → 29–39 s,
writing ~4 → 6.1 tok/s), `rpc-server --cache`, the self-organizing agent,
and the experimental C++ binary.
