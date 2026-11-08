# Day 18: load prompt, real Resume, GGUF stage 2, saved split, Optimize now additions

Nov 7, 2026, ~5:58 PM CT onward (America/Chicago). Branch `caravan-v3-mlx-split`.
Direct edits on the box, committed as linuxbren. No cloud agents.

## Status by item

| # | Item | Status | Commits |
|---|---|---|---|
| 1 | Load now / Not now prompt after a download (no silent auto-load) | Done (code + tests; live UI check queued) | 61fd3a3 |
| 2 | Resume continues a partial file with HTTP Range | Done, verified live on EXO1 and EXO2 | 07a8df8 |
| 2b | Split-download progress overcount / false "stalled?" | Done (code + tests; live check queued) | d173929 |
| hotfix | Dark Champion 21B greyed out ("missing shards on EXO1") | Done, verified live | 1955cab |
| 3 | GGUF stage 2: peers load their share from their own disk | Done, verified live (3B); 30B timing queued | 0dbe51c, (note text) |
| 4 | llama.cpp upgrade + before/after | Partial: "before" recorded; upgrade paused for Brenden's live test | — |
| 5 | MLX optimizing single stage | Blocked: needs a decision (see below) | — |
| 6 | Optimize now: native MTP, adaptive lookup, GGUF tuning | Partial: MTP + lookup sweeps wired; GGUF knobs + plan, runner not wired | f5670e8 |
| 7 | Qwen3.6-35B-A3B + helper | Investigated; live test queued | — |

## 1. Load now / Not now

When a download finishes and nothing is loaded, the page asks "No model is loaded.
Load <name> now?" with **Load now** / **Not now**. Not now leaves a Load button on
the job card. With a model already loaded it still only offers the Load button.
The `<dialog>` uses the shared theme dialog style, so it follows Amber, Green,
Meadow and Nebula. Tests: `tests/test_day18_load_prompt.py` (3).

## 2. Resume with HTTP Range

hf_xet keeps no partial file, so Resume used to restart a file from 0.
`agent/range_fetch.py` now downloads every weight file (MLX shards and GGUF)
into `.cache/huggingface/download/<name>.incomplete` and resumes with
`Range: bytes=<have>-`. If the server ignores Range it starts that file clean.
Small files (config, tokenizer) still use `snapshot_download`.
Tests: `tests/test_day18_range_fetch.py` (4).

Live records (Qwen/Qwen2.5-0.5B-Instruct-GGUF `qwen2.5-0.5b-instruct-q4_0.gguf`,
428,730,208 bytes, sha256 7671c0c3…af6ed):

| Where | Stop | Resumed from | Rest | sha256 |
|---|---|---|---|---|
| Box | killed at 6 s | 337,641,472 B | 91,088,736 B in 1.7 s | match |
| EXO1 (first try) | `timeout` missing on macOS, no stop | 0 | 428.7 MB in 92.3 s | match |
| EXO1 | killed at 20 s | 116,391,936 B | 312,338,272 B in 169.8 s | match |

Speed check on EXO1, same file, from 0: hf_xet `hf_hub_download` 138 s, plain
curl 89 s. Single-stream Range is not slower on this line.

Through the web UI (`/api/picker/download`, Qwen/Qwen2.5-3B-Instruct-GGUF
q4_0, 1,997,879,712 B, job 1b421e5f088b, 6:18–6:21 PM CT): EXO1 picked up at
~1.75 GB, EXO2 logged `RESUMED qwen2.5-3b-instruct-q4_0.gguf from 1012924416 bytes`;
both finished with the full size.

### 2b. Progress overcount (Brenden's report)

Job d653dbe7d055 (Dark Champion 21B, split:2) showed EXO2 at "17.62/11.77 GB ·
stalled?" while files were landing. Causes and fixes (d173929):
- The disk probe counted a `.incomplete` as well as the finished file beside it. Now counted once (local and remote probe).
- The Mini's total came from the planned split, not what that Mini's fetcher
  actually downloads (EXO2 needed shards 1–4, ~20.7 GB). The remote fetcher's first
  line (`my_gb`) now sets that Mini's total (`web_picker.apply_reported_total`).
- Shown bytes are capped at the total.
- "Stalled?" now needs no growth on any signal (shown bytes, disk, network), not
  "no new maximum". Tests: `tests/test_day18_progress_overcount.py` (4).

## Hotfix: saved split point (1955cab)

Dark Champion 21B (32 layers) was downloaded with the server default
packer_layers 24, but the catalog checked it with 32//2 = 16, so EXO1's shards
4–5 looked incomplete. Now:
- `caravan-placement.json` stores `packer_layers` and `n_stages` at download time.
- `inspect_tree` uses the saved value over the caller's default; older split
  placements without it are detected from the shards present (24 tried first).
- The catalog uses the saved/detected value, and the load uses the same entry value.
- Defaults match: catalog and server both use 24 (models of 24 layers or fewer split in half).
- Backfilled `packer_layers: 24, n_stages: 2` in this model's placement file on both
  Minis (weights untouched). Web restarted on EXO1 with KEEP_WORKERS=1 at ~6:28 PM CT.
- Verified: `/api/models` lists it `usable=True, packer_layers=24`.
Tests: `tests/test_day18_saved_split.py` (4).

## 3. GGUF stage 2

llama.cpp RPC already sends only a hash for tensors over 10 MiB when the peer's
`rpc-server -c` cache has that tensor. Stage 2 fills that cache from the peer's own
copy of the GGUF before the load:
- GGUF downloads now go to every online Mini.
- At a split load, each peer with the same file (name + size) runs
  `agent/gguf_rpc_seed.py`: reads tensor offsets with gguf-py, works out the
  layers llama.cpp gives that device (same rule as llama-model.cpp, ±1 layer),
  and a small C helper (`agent/fnv_seed.c`, built once to
  `~/.caravan/bin/caravan-fnv-seed`) writes `<cache>/rpc/<fnv1a64>` files.
- No peer copy: same as before (share over the link). Seeding can't fail a load.
- Lockdown unchanged: rpc-server still listens on 127.0.0.1 only, reached over the SSH tunnel.

Checks:
- Hash format: seeding Qwen3-30B-A3B-Q4_K_S (EXO2 share, 1:1) into a temp dir gave
  73 tensors / 8.41 GB in 19.0 s; 70 of the 73 names already existed in EXO2's real
  rpc-server cache (the 3 others are padding layers). The hashes match llama.cpp.
- Live split load, qwen2.5-3b-instruct-q4_0 (llama.cpp 6a1a922), 6:22–6:26 PM CT:

| Run | EXO2 share came from | Load | Write tok/s (3 × 256 tok, temp 0) |
|---|---|---|---|
| No local copy on EXO2 | link (cache grew 574→617 files) | 4.0 s | 41.8 / 41.7 / 41.6 |
| Local copy, cache entries removed first | own disk: 43 tensors, 0.8 GB seeded in 6.2 s | 3.0 s (+6.2 s seed) | 41.8 / 42.1 / 41.1 |

  After the seeded load the cache was still 617 files: every big tensor was a hit.
  Over Thunderbolt the first seed costs more than it saves; it pays off on
  slower links and on later loads (seed reports "have" and skips).
Tests: `tests/test_day18_gguf_seed.py` (4).

## 4. llama.cpp upgrade (partial)

"Before" numbers, llama.cpp 6a1a922 (Sep 5), prompt "Write a short story about a
caravan crossing a desert at night.", n_predict 256, temp 0, no prompt cache, 3 runs:

| Model | Where | Write tok/s |
|---|---|---|
| qwen2.5-3b-instruct-q4_0 | one Mini (EXO1) | 50.6 / 50.6 / 50.5 |
| qwen2.5-3b-instruct-q4_0 | split 20.4:12.9 | 41.6–42.1 (above) |
| Qwen3-30B-A3B-Q4_K_S | one Mini (EXO1) | 34.4 / 34.4 / 34.4 |
| Qwen3-30B-A3B-Q4_K_S | split EXO1+EXO2 (load 12.1 s) | 35.1 / 35.1 / 34.3 |

Attempts (all failed, nothing changed in the running binaries):
1. EXO1 `git pull` refused: EXO1 is on local branch `caravan-patches` (one patch,
   2f26123e "rpc: use getaddrinfo…") and `origin` is linuxbren/llama.cpp. Made
   branch `caravan-day18` at upstream 76a67730 (Nov 7); the patch no longer applies
   (upstream rewrote that code). Caravan only dials 127.0.0.1 tunnels, so it isn't needed.
2. EXO2 master pulled to 76a67730.
3. First build: `cmake: command not found` over non-interactive SSH (PATH).
4. Second build (with /opt/homebrew/bin) was stopped when Brenden started live
   testing. It had already relinked some dylibs in `build/bin`; they were put back
   from the backup `~/dev/llama.cpp-bin-6a1a922` (mv over, so running processes kept
   theirs). `llama-server --version` = 6a1a922 on both. New-version-only dylib files
   (`*.0.29.0.dylib`, `*.0.9.0.dylib`) are left in place, unused.
Next: build 76a67730 into a separate dir, switch `CARAVAN_LLAMA_BIN`, re-run the table.

## 5. MLX optimizing "single stage" (blocked, needs a decision)

Optimize now already runs in one pass (one option at a time). The "two-stage" in
the docs is the MLX split runtime (`MAX_SPLIT_STAGES = 2`): MLX splits across at
most 2 Minis. Making that N-stage is a runtime change (mlx_split chain, packer
relay) that can't be tested beyond 2 Minis here. Question for Brenden: which one did he mean?

## 6. Optimize now additions (partial)

- `native_mtp` and `adaptive_lookup` are new reload options, tried last, one at a
  time, 3% margin, recorded losers skipped. MTP needs one Mini, an installed head
  and 16-bit KV; lookup needs one chat. Both start from off (a saved winner
  isn't used as the starting value). Because these modes load with `--no-learn`,
  the runner goes back to the normal worker to record the result, then applies the winner.
- Page settings that pin them (Guess-ahead or Prompt lookup not Auto) skip them.
  Optimize still refuses to start while MTP/adaptive lookup is the page setting.
- GGUF: `llama_args(tune={"flash_attn", "ubatch"})` and `gguf_schedule()` (same
  rules). Not wired: the runner talks to the MLX worker's `/caravan/sweep`, which
  llama-server doesn't have. Next step: a GGUF runner that stores results in the
  tuned store and reloads llama-server per option.
- Not run live yet. Tests: `tests/test_day18_optimize_more.py` (10).

## 7. Qwen3.6-35B-A3B with a helper (investigated)

- Sizes (HF API): `mlx-community/Qwen3.6-35B-A3B-4bit` 20.4 GB; MTP head
  `mlx-community/Qwen3.6-35B-A3B-MTP-4bit` 0.48 GB (not 0.8); `Qwen/Qwen3.5-0.8B` 1.75 GB.
- Fit: 20.4 GB doesn't fit one 24 GB Mini (Metal ~18 GB). Split: ~10.2 GB each + 0.48 GB head on the lead fits.
- Vocab: Qwen3.5-0.8B 248,320 = Qwen3.6 248,320. The draft is hybrid too (24 layers, linear attention).
- Rewind: Caravan's native MTP (Day 17) already snapshots the whole cache and
  replays on a rejected guess (`agent/native_mtp.py`), so rejected guesses work with
  linear-attention layers. Blockers for this model: it only accepts dense Qwen3.5
  (`num_experts` → rejected; 35B-A3B is MoE), and native MTP is one-Mini only, while
  this model needs the split. Needed: MoE MTP head support, and MTP on the lead in
  split mode with a snapshot of the packer's linear caches per verify.
- Live benchmark (no helper vs helper) queued; it needs a 20.4 GB download to both Minis.

## Queued for the Minis (needs Brenden's go-ahead)

See the report. Tests at the end of the code work: 436 OK on the box.

## Dark Champion 21B gibberish: root cause (Nov 7, read-only diagnosis)

**Symptom:** `mlx-community/Llama-3.2-8X4B-MOE-V2-Dark-Champion-...-21B-MLX` as a 2-Mini split (EXO2 packer layers 0-23, EXO1 lead 24-31) printed multilingual token salad from the first token, ran to 768 tokens, ~12 tok/s.

**Root cause: the two sides disagree on whether embeddings are tied.**
- config.json says `tie_word_embeddings: true`, but the checkpoint also ships `lm_head.*` (in shard 5).
- Caravan's `mlx_split_fetch.tied_of()` only checked for `lm_head` in the weight map, so it said "untied" and gave the lead only shards 4-5. Shard 1, which holds `embed_tokens`, wasn't included.
- mlx_lm's mixtral follows the config. It builds no `lm_head` and drops `lm_head.weight` in sanitize, then computes logits with `embed_tokens.as_linear`.
- On EXO1, `embed_tokens` was never in any local file. `load_model(strict=False)` left it at random init. The quantize predicate also skipped it because there were no scales. So every logit came from a random matrix.
- The startup shard check passed because it used the same wrong `tied_of`.
- Evidence (EXO1, offline):
  - `ModelArgs.tie_word_embeddings=True` means the model has no lm_head.
  - `plan_files(...,24)` gives tied=False and head files = shards 4-5 only.
  - The packer loaded 17.0 GB for 24 layers and the lead about 5.7 GB for 8 layers, so all layer weights were present. Only the output head was garbage.
- **Not the cause:**
  - The `model_type remap: qwen3_5_text → qwen3_5` log line. It's a startup patch that runs for every model and is harmless.
  - The split boundary. It's 24 on both sides.
  - Missing layer tensors.
  - Quantization config.
  - The ignored llama3 rope_scaling. That one is real but secondary.

**Fix (local branch `fix/tied-embed-split`, not committed):**
1. `tied_of` returns True if `tie_word_embeddings` is true (top level, `text_config`, or `llm_config`) or if there's no lm_head. Downloader, inventory, and the startup check all share it, so the lead now needs shard 1 too.
2. `Stage` records the keys mlx_lm actually loaded. If any weight this stage uses was missing, it raises `MissingWeightsError` instead of running random weights. This makes the whole "strict=False silently random" class fail loudly.
3. New tests are in tests/test_tied_embed_split.py.

**To verify (needs Brenden's OK):**
- Fetch shard 1 (~5.2 GB) to EXO1 with `mlx_split_fetch.py ... --role lead --packer-layers 24`.
- Restart the split and send one short chat.

**Follow-up:** mlx_lm mixtral uses plain `nn.RoPE` and ignores llama3 `rope_scaling` (factor 32). Quality drops on long contexts. A Caravan patch could swap in `mlx_lm.models.rope_utils.initialize_rope`.

### Rope scaling for classes that ignore it (mixtral etc.)
- Some mlx_lm classes ignore `rope_scaling` because they build a plain `nn.RoPE`. Examples: mixtral, qwen3_moe, phi3, gemma2, and about 40 more in mlx_lm 0.32.2.
- `proxy/mlx_arch.fix_rope_scaling()` swaps those for `mlx_lm.models.rope_utils.initialize_rope(...)` when config (or text_config) asks for scaling. Types covered: llama3, yarn, dynamic, and linear.
- Applied after load in the single-Mini worker and in split `Stage` (lead and packer). Classes that already scale (llama, qwen2/3, gpt_oss) are left alone. Site-packages is not edited.
- Tests: 5 new (fake RoPE/config). Full suite 445 OK (32.8s).
- Live check (testing window): load Dark Champion. Worker/packer logs should show `rope scaling: applied llama3 to N attention layer(s)`, and a long prompt should stay coherent.

### MTP layers in split planning
- Checked HF indexes on Nov 7:
  - `mlx-community/Qwen3.6-35B-A3B-4bit`: 2090 keys, layers 0-39, `language_model.*`, no `mtp.*` keys.
  - `mlx-community/Qwen3.6-35B-A3B-MTP-4bit`: a standalone helper head. model_type `qwen3_5_mtp`, 46 keys, `fc`, `norm`, `pre_fc_norm_*`, a single `layers.0`, no embeddings. Its config still says 40 layers.
- Before: splitting the MTP repo would have planned 40 nonexistent layers. `mtp.*` keys inside a full checkpoint were fetched by both Minis, and `mtp.layers.0.*` was even counted as layer 0, which went to the packer.
- Now:
  - `mtp.*` keys go to the lead only.
  - Layers numbered at or above `num_hidden_layers` (DeepSeek/GLM nextn) go to neither stage. mlx_lm drops them at load, so neither Mini needs them.
  - `head_only_reason()` refuses to split helper heads (`*_mtp`/`*_nextn`, or no embeddings with fewer layers than config). Split downloads stop with a clear error, and inventory marks them not splittable.
- Tests: 5 new. Full suite 450 OK (32.3s). One failed run before the fix: `mtp.layers.0` was matched as layer 0, so its MTP check now runs first.
- Live check: none needed for the planner. For Qwen3.6 native MTP, confirm the lead still finds the MTP head.

### Picker warnings for risky checkpoints
- `mlx_arch.model_warnings(config, weight_map)` flags four cases. It only warns and never blocks:
  - a top-level `*_text` model_type that isn't in the remap table
  - config ties embeddings but the files ship `lm_head` (the Dark Champion case)
  - config says untied but there's no `lm_head` (the output layer would be random)
  - `*_mtp`/`*_nextn` helper heads
- Carried through `inspect_tree` → node inventory → catalog rows (`warnings`). The model picker adds a ⚠ to the name, and the warnings show in its tooltip.
- Tests: 6 new. Full suite 456 OK (32.8s).
- Live check: after the Minis pull this, Dark Champion should show ⚠ with the tie note.

### GGUF Optimize now runner (offline-tested)
- New `proxy/gguf_tune.py` (`GgufTuner`):
  - Follows `gguf_schedule()` one option at a time: reload, measure the incumbent, reload, measure the challenger.
  - Keeps the challenger only if it's more than 3% faster. Otherwise it records the challenger as a loser so it won't be retried.
  - Saves after every trial, and always leaves the winner running, including after an error.
- Store: `~/.caravan/gguf-tuned.json`, keyed by `<file>.gguf|<N>mini`.
- `measure_http()` reads llama-server's own `timings.predicted_per_second`, using 2 fixed prompts, temperature 0, 192 tokens.
- The web GGUF launcher now passes `best_tune()` to `llama_args(tune=...)`. Bad values are dropped, and with nothing learned the launch behaves as before.
- Not yet wired to the Optimize now button. That needs a web endpoint that calls `GgufTuner` with the launcher's restart. Next step.
- Tests: 5 new. Full suite 461 OK (32.8s). One failed test run: my test assumed ubatch 1024 is the first challenger, but the schedule picks 256 (a tie in distance from 512, so 256 comes first). The test was fixed; the code was unchanged.
- Live check: run the tuner against a small GGUF (Qwen2.5-3B q4_0) on 1 and 2 Minis. Expect about 6 reloads per run.

### ⚠ model warnings: plain-language hints (Nov 7, ~7:10 PM CT)
Brenden asked that users understand what ⚠ means. The hover text now starts with "⚠ means Caravan noticed something unusual about this model:". Each warning is rewritten to say what's off, whether it still runs, and what to do. macOS select menus don't show hover text on options, so the warning also shows as a line under the model picker when that model is selected.

### Report this model + opt-in warning ping — 2026-11-07
- **Report this model:** the ⚠ line under the picker (`#modelWarn`) now has a "Report this model" link. It opens a new tab with a prefilled GitHub issue on linuxbren/caravan (label `model-report`). The body has only the HF repo id, the warning text, the Caravan version (short commit), `model_type`, and the `tie_word_embeddings` flag. No paths, hostnames, IPs, or tokens. The user reads, edits, and submits it themselves; Caravan sends nothing by itself. New `.github/ISSUE_TEMPLATE/model-report.md`; `model-report` label created on GitHub.
- `/api/models` rows now carry `model_type` and `tie_word_embeddings`; the response carries `caravan_version`.
- **Opt-in warning ping** (`proxy/web_alert.py`): off unless `CARAVAN_ALERT_WEBHOOK_URL` is set (default for everyone: off, no thread, no network). When set, the web server POSTs `{model, warnings, mini, caravan_version}` once per (model, warning set) when `/api/models` first shows it. Optional `CARAVAN_ALERT_WEBHOOK_KEY` goes out as both `Authorization: Bearer <key>` and `X-Webhook-Key: <key>`. Dedupe in `~/.caravan/alert-sent.json`; a failed POST isn't recorded, so it retries on the next picker refresh. Background daemon thread, 5 s timeout, never blocks the UI.
- Tests: 6 new (`tests/test_day18_model_report.py`): off when unset, payload shape, dedupe, new warning set re-pings, failed post retries, HTML link + template. Full suite 467 OK (32.3s).

## Dark Champion split verification (Nov 7, 2026, ~6:50–7:20 PM CST)

Model: mlx-community/Llama-3.2-8X4B-MOE-V2-Dark-Champion-Instruct-uncensored-abliterated-21B-MLX (mixtral class, Llama 3.2 merge, tie_word_embeddings=true, files also ship lm_head).
Fix under test: 07249e7 (tied_of honors config; Stage refuses missing weights). Minis at b6b4854 (EXO1 web server restarted at b356caf with CARAVAN_WEB_KEEP_WORKERS=1).

**Before (24/8, EXO1 without shard 1):** gibberish, e.g. "Mastدرس أكبر.coeff-galleryelf.teamujete commentary substancesuvwxyz…", ran the full 768 tokens at ~12 tok/s.

**Step 1: fetched shard 1 to EXO1** (5,171,644,799 B, 6m48s; `~/.caravan/venvs/mlx/bin/python agent/mlx_split_fetch.py … --role lead --packer-layers 24`; system python3 lacks huggingface_hub). Reloaded 24/8: packer 17.0 GB of layers on EXO2 (24 GB Mini), lead ~5.7 GB.
**FAILED: every chat returned HTTP 507** "Not enough memory headroom". EXO2 packer_available_gb 1.51–1.71 (12 retries over ~3 min) vs 1.75 GB safety margin; EXO1 local headroom ~10 GB. Packer counts free + speculative + purgeable + half of inactive.

**Step 2: rebalanced to 16/16** (Brenden approved). Fetched lead files for packer_layers 16 to EXO1 (adds shard 3; lead now holds shards 1,3,4,5 = 18.33 GB on disk). EXO2 already had shards 1–3. Set packer_layers=16 in caravan-placement.json on both Minis; /api/models then reported packer_layers 16, usable, "Fits on 2 Minis, about 13 GB RAM each". Loaded: packer 11.3 GB layers in 4.1s, lead ~11.3 GB in 3.9s; lead auto pipeline chats=1 (tight headroom 1.5 GB). After load vm_stat: EXO1 free 5,388 / inactive 409,090 / wired 854,647 pages; EXO2 free 9,846 / inactive 477,452 / wired 858,719 (16 KB pages; EXO2 ≈ 7.6 GB inactive).

**After (16/16, settings: kv 16, fuse off, keepalive on, no helper):**

| Prompt | max_tokens | Tokens out | First token (mini) | Write tok/s | Read tok/s | Total | Lead peak |
|---|---|---|---|---|---|---|---|
| "Say hello in one sentence." | 60 | 3 | 0.508 s (0.71 s client) | 20.0 | 117.8 | 0.66 s | 11.87 GB |
| "In about 300 words, explain how a sourdough starter works and how to keep one healthy." | 500 | 387 | 0.469 s (0.71 s client) | 14.2 | 140.7 | 27.7 s | 11.93 GB |

Replies: "Hello!" and a clean ~330-word sourdough explanation with 5 numbered tips. Coherent English; gibberish fixed.
/api/models shows the tie warning ("config ties embeddings but the files ship lm_head…").

**Rope log:** no "rope scaling: applied" line in lead.log/packer.log. The split Stage logged via print() (block-buffered stdout). Fixed to a flushed stderr logger; shows on next reload (not reloaded for it).

**Follow-up (not fixed):** split chooser should pick a more balanced packer_layers when the saved point leaves one Mini under the headroom margin (24/8 left EXO2 at 17 GB on 24 GB). Also EXO1/EXO2 checkouts drifted by one commit during the run because another job was pushing.

### GGUF Optimize now wired to the button — 2026-11-07
- New `proxy/web_gguf_optimize.py` (`GgufOptimizer`) wraps `gguf_tune.GgufTuner` and reports in the same shape as the MLX Optimize now: phase, prompts, reloads, per-option schedule (pending/running/kept/skipped + winner), `reply_s`, `reload_s`, `eta_s`, summary. ETA = for each unsettled option, (2 − arms done) × (reload + 2 replies), plus one final reload of the winner.
- Endpoints: `POST /api/optimize/start` now picks the GGUF runner when the loaded model is llama.cpp (`backend == "llama"`); `POST /api/optimize/gguf/start` forces it. `GET /api/optimize`, `/pause`, `/cancel` follow whichever runner started last.
- Reloads go through `mgr.switch(..., entry={..., tune_override})`; the GGUF launcher uses `tune_override` instead of the saved best when present. Waits for your chats and honours Pause; Cancel finishes the current step, then reloads the best settings.
- UI: the Optimize now panel labels GGUF runs "(GGUF, each option reloads llama.cpp twice)".
- Tests: 4 new with a fake tuner/manager (`tests/test_day18_gguf_optimize_web.py`). Full suite 471 OK (32.8s). **Not run live yet.**
- Docs cleanup check: no duplicated "GGUF Optimize now runner" section exists in docs/DAY18.md or CHANGELOG.md (the earlier "duplicate" was two files' output printed back to back). Nothing to remove.

### Split point safety (balanced packer_layers) — 2026-11-07
Tonight's case: Dark Champion 21B 8-bit (32 layers, ~0.71 GB/layer) on two 24 GB Minis. The saved 24/8 split put 17.0 GB on EXO2, which left it 1.51–1.71 GB free against the 1.75 GB margin, and every chat got 507. 16/16 (~11.3 GB per Mini) worked.
- New `proxy/split_balance.py` (pure, any number of Minis): free_i = capacity_i − layers_i × GB/layer − 1.3 GB stage overhead (`CARAVAN_SPLIT_STAGE_OVERHEAD_GB`, calibrated on tonight's numbers: 24/8 → 1.66 GB on EXO2, 16/16 → 7.3 GB each). Capacity is `web_picker._node_capacity_gb` and the margin is `CARAVAN_MEMORY_SAFETY_GB` (1.75). `balanced_counts()` hands out layers one by one to the Mini with the most room left, so equal Minis split evenly and bigger Minis take more.
- **Download planning:** when no `packer_layers` is given, a split download now uses the balanced point for the chosen Minis' RAM instead of the fixed default of 24. The job note says so.
- **Picker:** split rows get `split_check` and `split_note`. When the saved point leaves a Mini under the margin, the row gets a ⚠ and a "⚠ Split:" line under the picker that names the tight Mini, the balanced point, and any extra files each Mini needs. Inventory rows now include `shards_present`, so Caravan can work out which files are missing.
- **Load:** if the balanced point's files are already on every Mini, `/api/models/load` loads at the balanced point and says so (`balance_note` plus an activity note). If files are missing, it returns 409 with the message listing them. **Nothing is downloaded automatically.** `force_split: true` keeps the saved point.
- Today the runtime has 2 stages, so the picker and load checks only run for 2-Mini splits. The math and tests cover N Minis. No Balance slider yet (future dev day).
- Tests: 13 new (`tests/test_day18_split_balance.py`) using tonight's numbers. Full suite 484 OK (33.8s).
- Live check later: the Minis need a pull before `shards_present` shows up in their inventory. Until then, the extra-files list is unknown and the picker just shows the warning.

### Day 18 release notes drafted — 2026-11-07
- Draft at `docs/release-notes/day18.md` (RELEASES.md doesn't name a location; this is the new home for notes). Not tagged or published. Planned tag `day18-2026-11-07`. Before publishing: final commit, test count, and the fresh-package check.

### Brenden's Dark Champion test session (Nov 7, 7:27–7:46 PM CT, 16/16 split)
Taken from the EXO1 lead.log; Brenden ran the chats himself.
- 31 turns in one chat, with the context growing from 854 to 5,849 tokens (prompt cache reused all earlier turns each time).
- Overall speed including reading: about 12–13 tok/s early in the chat, about 10–11 tok/s past 5k tokens of context (e.g. 514 tok in 41.29 s; 245 tok in 24.39 s at 5.2k context).
- No 507 memory refusals and no gibberish. Lead peak memory went from 12.84 to 13.07 GB. After the session, EXO1 had 65,181 free pages and EXO2 had 24,396 (16 KB pages).
- One BrokenPipeError at about 7:42 PM. This is likely a reply that was stopped or a closed tab, and the next turn worked.
- Note: the chat reused session 897be30c98f2d82b, the same one as the earlier gibberish reply, so that reply was probably still in its history.

### Per-reply timing log + wrap-up — 2026-11-07, ~7:55 PM CT
- e9159c8: `agent/mlx_worker.py` `_timing_line()` and a flushed `log()` line after each reply's answer line, single-Mini and split: `session X: timing (single|split): read X tok (C cached) at Y tok/s, write Z tok at W tok/s, first token A s, total B s`. Write speed = (tokens − 1) / (total − first token). Tests: 2 new (`tests/test_timing_log.py`). Full suite **486 OK (33.8 s)**.
- Both Minis pulled to e9159c8 (`git pull --ff-only`, clean). Only the EXO1 web server was restarted (`CARAVAN_WEB_KEEP_WORKERS=1`); it adopted the running lead (pid 78216), so Dark Champion stayed loaded. The worker was not restarted, so the timing line starts on the next model load.
- Read-only checks on EXO1 :8190: status ready, split true; `/api/models` Dark Champion row has the tie-table ⚠ warning; the page has the Report this model link; `split_check` ok at 16/16 (free 5.49/6.79 GB, balanced 15/17, margin 1.75), so no split warning, correctly. Worker :8194 /health 200.
- Brenden's session summary: 31 turns; learned write speed 11.96 tok/s mean over 29 replies with guess-ahead on vs 11.31 over 3 off; ~13.7 early sliding to ~12; peak lead 13.07 GB; no 507s, no gibberish; one harmless BrokenPipe ~7:42 PM CT.
- Moved to next dev day: llama.cpp 76a67730 build and benchmarks, GGUF tuner live run, GGUF stage 2 30B load timing, Qwen3.6 download, Balance slider.
- **Published:** https://github.com/linuxbren/caravan/releases/tag/day18-2026-11-07 — tag `day18-2026-11-07` at 07aab1b; main fast-forwarded to 07aab1b. Assets: caravan-day18.zip 18,653,892 B, caravan-day18.tar.gz 17,789,227 B. Fresh download of the tar.gz extracted with INSTALL.md present; full suite in the package: 486 OK (33.9 s), 0 failures, 0 skips.

## After release (Nov 7, 8:08–8:32 PM CT)

Brenden approved the queued GGUF Mini work. No new models downloaded; Day 18 tag not moved.

**1. Unload.** Dark Champion 16/16 unloaded through `/api/models/stop` in 2.1 s. Free memory (memory_pressure): EXO1 39% → 90%, EXO2 33% → 89% (24 GB Minis, about 12–13 GB freed each).

**2. llama.cpp 76a67730 vs 6a1a922.** 76a67730 built in a separate git worktree on both Minis, `~/dev/llama.cpp-76a67730` (Release, Metal, RPC, native, shared libs; targets llama-server, ggml-rpc-server, llama-bench; `--version` = 0.9.0-dev build 1379, 76a67730). The 6a1a922 build in `~/dev/llama.cpp/build/bin` is untouched. Each config ran back to back (old then new), loaded through Caravan (`/api/models/load`) with the web server restarted with `CARAVAN_LLAMA_BIN` set. Each config got 3 runs of the baseline prompt ("Write a short story about a caravan crossing a desert at night.", 256 tok, temp 0, no prompt cache) and 2 runs of a 1,505-token prompt for read speed. Script: /tmp/cvbench.py + /tmp/cvmatrix.sh on EXO1 (not in repo). Times 8:15–8:21 PM CT.

| Model | Where | Build | Write tok/s (3 runs) | First token, 13-tok prompt | Read tok/s, 1,505-tok prompt | Load |
|---|---|---|---|---|---|---|
| qwen2.5-3b q4_0 | EXO1 | 6a1a922 | 50.4 / 50.3 / 50.2 | 0.072–0.077 s | 554.8 / 555.3 | 3.7 s |
| qwen2.5-3b q4_0 | EXO1 | 76a67730 | 49.0 / 48.9 / 49.1 | 0.039–0.042 s | 554.7 / 554.7 | 2.5 s |
| qwen2.5-3b q4_0 | split 2 Minis | 6a1a922 | 41.9 / 41.7 / 41.6 | 0.077–0.087 s | 638.7 / 787.4 | 9.6 s |
| qwen2.5-3b q4_0 | split 2 Minis | 76a67730 | 41.0 / 41.0 / 41.0 | 0.043–0.054 s | 781.5 / 785.3 | 9.3 s |
| Qwen3-30B-A3B Q4_K_S | EXO1 | 6a1a922 | 43.3 / 43.2 / 43.4 | 0.155–0.161 s | 402.6 / 403.6 | 3.7 s |
| Qwen3-30B-A3B Q4_K_S | EXO1 | 76a67730 | 43.5 / 43.5 / 43.4 | 0.144–0.149 s | 435.5 / 435.1 | 2.5 s |
| Qwen3-30B-A3B Q4_K_S | split 2 Minis | 6a1a922 | 35.1 / 34.9 / 35.1 | 0.167–0.178 s | 458.1 / 579.4 | 16.5 s |
| Qwen3-30B-A3B Q4_K_S | split 2 Minis | 76a67730 | 35.4 / 35.8 / 35.8 | 0.150–0.173 s | 619.8 / 623.7 | 17.0 s |

Notes:
- Tonight's 3B numbers match the morning baseline (50.6 single, 41.6–42.1 split). The 30B single-Mini number is 43.3 tonight against the morning's 34.4. Both builds measured 43.3–43.5 back to back, so this is a change in conditions (the morning run was probably with other memory in use), not a build effect. Compare builds within this table only.
- 76a67730: first token on short prompts about 45% faster (3B), 30B read +8% single and about +7–35% split. Write speed −2.6% on 3B single (50.3 → 49.0), −1.7% on 3B split (41.7 → 41.0), +0.2% on 30B single, +1.6% on 30B split.
- Shares: 3B split 20.1:20.0 (old) and 20.7:19.9 (new). 30B split 20.3:19.9 for both.
- **RPC lockdown holds with 76a67730.** On EXO2 the only listener is `ggml-rpc-server -d MTL0 -H 127.0.0.1 -p 50052 -c` (127.0.0.1:50052). On EXO1 the lead reaches it through an ssh forward on 127.0.0.1:50062. A direct `nc` from EXO1 to EXO2's link IP 169.254.103.191:50052 was refused.

**3. GGUF Optimize now, live (6a1a922 build).**
- The first try was refused with "GGUF Optimize now needs a GGUF model loaded". GGUF loads never set `_loaded_entry`. Fixed in 1ace313: the GGUF load now records the entry, without `tune_override`. 1 new test (`tests/test_gguf_loaded_entry.py`, fails without the fix). Full suite 487 OK (33.9 s).
- qwen2.5-3b, 1 Mini, 8:25–8:27 PM CT: flash_attn on 50.37 vs off 49.00 tok/s → stay on. ubatch 512 48.59 vs 256 48.41 → stay 512. 8 prompts, 5 reloads, avg reload 11.4 s, reply 4.0 s, 1.5 min total.
- qwen2.5-3b, 2 Minis, 8:28–8:30 PM CT: flash_attn on 41.84 vs off 40.63 → on. ubatch 512 42.06 vs 256 41.78 → 512. 8 prompts, 5 reloads, avg reload 18.8 s, reply 4.7 s, 2.2 min total.
- Both winners were saved in `~/.caravan/gguf-tuned.json` (`qwen2.5-3b-instruct-q4_0.gguf|1mini` and `|2mini`: flash_attn on, ubatch 512, with trials and losses).
- The launcher uses the saved winner. On the next load the activity log said "GGUF tuned settings from Optimize now: {'flash_attn': 'on', 'ubatch': 512}", and llama-server ran with `-fa on … -ub 512 -b 2048` (single and split).
- Small oddity: the Optimize now schedule shows the ubatch winner as the string '512', while the store has the int 512. This is display only.

**4. GGUF stage 2 load timing.**
- 3B: EXO2 seeds its share from its own disk, 55 tensors / 0.9 GB (all cached) in 4.8–4.9 s; full load 9.3–9.6 s. Later, with the tuned ubatch: 58 tensors / 1.0 GB (3 new) in 4.7 s, 10.6 s.
- 30B: **true stage 2 not timed.** EXO2 has no local copy of Qwen3-30B-A3B-Q4_K_S.gguf, and putting one there would be a 17 GB transfer, which the no-download rule rules out. Its share comes over the link and its rpc cache: llama-server loaded in 14.1 s, 16.5 s (6a1a922) and 17.0 s (76a67730) end to end.

**5. Decision: keep 6a1a922 as the default.** 76a67730 is stable (12 loads, 30 generations, no errors) and better on first token and read speed. But write speed, the number users feel on long replies, is 1.7–2.6% lower on 3B and only 0.2–1.6% higher on the 30B. That is not "clearly as good or better". The new build stays in `~/dev/llama.cpp-76a67730` on both Minis for anyone to try with `CARAVAN_LLAMA_BIN=~/dev/llama.cpp-76a67730/build/bin`. Re-test it with the GGUF tuner and longer prompts on a later day.

**6. Final state.**
- Dark Champion 21B reloaded at 16/16 split (`--split-packer-layers 16`) at 8:31 PM CT, ready in about 16 s. EXO1 web server runs with KEEP_WORKERS=1 and the default 6a1a922 path.
- The timing line is live. Test chats:
  - `timing (split): read 45 tok (0 cached) at 120.6 tok/s, write 68 tok at 14.05 tok/s, first token 0.51 s, total 5.28 s`
  - `read 40 tok (0 cached) at 114.6 tok/s, write 22 tok at 14.05 tok/s, first token 0.42 s, total 1.92 s`
  - Reply coherent ("Camel, Horned Lizard, Coyote").
- Free memory after the reload: EXO1 43%, EXO2 41%.

## Day 18 video
`handoff/lab/videos/2026-11-08_caravan-v3-day18-ui-tour_v25.mp4` (replaces v24 cards). 85.5 s, 1280x720 H.264, silent, 22 single-line bottom captions, no dates or times on screen (generator asserts this). Real Caravan web UI footage:
- Live (recorded read-only from EXO1 :8190 via Omarchy, headless Chromium screencast, Nov 8): picker with the resumed split download bars, Topology with per-Mini memory, Settings with the GGUF Optimize now result. The model was already unloaded (stopped from the UI at 11:22 AM CT, not by the video work), so no live chat.
- Replayed (current index.html on the box, `day18_replay_server.py` with logged values only): Dark Champion "Hello!" reply with its logged stats (0.51 s first token, 20.0 tok/s write, 118 tok/s read, 0.66 s total), the logged gibberish snippet, and the live `/api/models` ⚠ warning text with Report this model.
- Two number cards: llama.cpp old vs new, and Brenden's test plus 487 tests.
Generator: `make_day18_video.py`; captions: `2026-11-08_day18-ui-tour_captions.txt`.
