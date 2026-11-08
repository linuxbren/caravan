### Day 19 Balance + N-stage MLX checkpoint — 2026-11-08
- Experimental N-stage layer/shard plans and middle-packer transport; own per-stage caches, restore agreement and chain epoch invalidation.
- Topology Balance Auto/one-layer sliders, live memory/download preview and an explicit fresh-checked reload API, shared with a future TUI. No automatic downloads.
- N-stage launch/owned cleanup and web-restart node mapping. Serial, learning/guess-ahead off; N-stage Optimize is blocked. Old picker/download paths retain their two-stage gate until live verification.
- **529 tests pass (37.908 s), 42 new**; 3/4/7-stage socket simulations pass. No Mini contacted, no new inference benchmark. [Details and live steps](docs/DAY19.md).
- Easy install/auto-start, local-file ownership follow-up, diary sync and the final Day 19 release remain coordinator work.

### Day 18 release notes drafted — 2026-11-07
- Draft at `docs/release-notes/day18.md` (RELEASES.md doesn't name a location; this is the new home for notes). Not tagged or published. Planned tag `day18-2026-11-07`. Before publishing: final commit, test count, and the fresh-package check.

### Split point safety (balanced packer_layers) — 2026-11-07
Tonight's case: Dark Champion 21B 8-bit (32 layers, ~0.71 GB/layer) on two 24 GB Minis. The saved 24/8 split put 17.0 GB on EXO2, which left it 1.51–1.71 GB free against the 1.75 GB margin, and every chat got 507. 16/16 (~11.3 GB per Mini) worked.
- New `proxy/split_balance.py` (pure, any number of Minis): free_i = capacity_i − layers_i × GB/layer − 1.3 GB stage overhead (`CARAVAN_SPLIT_STAGE_OVERHEAD_GB`, calibrated on tonight's numbers: 24/8 → 1.66 GB on EXO2, 16/16 → 7.3 GB each). Capacity is `web_picker._node_capacity_gb` and the margin is `CARAVAN_MEMORY_SAFETY_GB` (1.75). `balanced_counts()` hands out layers one by one to the Mini with the most room left, so equal Minis split evenly and bigger Minis take more.
- **Download planning:** when no `packer_layers` is given, a split download now uses the balanced point for the chosen Minis' RAM instead of the fixed default of 24. The job note says so.
- **Picker:** split rows get `split_check` and `split_note`. When the saved point leaves a Mini under the margin, the row gets a ⚠ and a "⚠ Split:" line under the picker that names the tight Mini, the balanced point, and any extra files each Mini needs. Inventory rows now include `shards_present`, so Caravan can work out which files are missing.
- **Load:** if the balanced point's files are already on every Mini, `/api/models/load` loads at the balanced point and says so (`balance_note` plus an activity note). If files are missing, it returns 409 with the message listing them. **Nothing is downloaded automatically.** `force_split: true` keeps the saved point.
- Today the runtime has 2 stages, so the picker and load checks only run for 2-Mini splits. The math and tests cover N Minis. No Balance slider yet (future dev day).
- Tests: 13 new (`tests/test_day18_split_balance.py`) using tonight's numbers. Full suite 484 OK (33.8s).
- Live check later: the Minis need a pull before `shards_present` shows up in their inventory. Until then, the extra-files list is unknown and the picker just shows the warning.

### GGUF Optimize now wired to the button — 2026-11-07
- New `proxy/web_gguf_optimize.py` (`GgufOptimizer`) wraps `gguf_tune.GgufTuner` and reports in the same shape as the MLX Optimize now: phase, prompts, reloads, per-option schedule (pending/running/kept/skipped + winner), `reply_s`, `reload_s`, `eta_s`, summary. ETA = for each unsettled option, (2 − arms done) × (reload + 2 replies), plus one final reload of the winner.
- Endpoints: `POST /api/optimize/start` now picks the GGUF runner when the loaded model is llama.cpp (`backend == "llama"`); `POST /api/optimize/gguf/start` forces it. `GET /api/optimize`, `/pause`, `/cancel` follow whichever runner started last.
- Reloads go through `mgr.switch(..., entry={..., tune_override})`; the GGUF launcher uses `tune_override` instead of the saved best when present. Waits for your chats and honours Pause; Cancel finishes the current step, then reloads the best settings.
- UI: the Optimize now panel labels GGUF runs "(GGUF, each option reloads llama.cpp twice)".
- Tests: 4 new with a fake tuner/manager (`tests/test_day18_gguf_optimize_web.py`). Full suite 471 OK (32.8s). **Not run live yet.**
- Docs cleanup check: no duplicated "GGUF Optimize now runner" section exists in docs/DAY18.md or CHANGELOG.md (the earlier "duplicate" was two files' output printed back to back). Nothing to remove.

### Report this model + opt-in warning ping — 2026-11-07
- **Report this model:** the ⚠ line under the picker (`#modelWarn`) now has a "Report this model" link. It opens a new tab with a prefilled GitHub issue on linuxbren/caravan (label `model-report`). The body has only the HF repo id, the warning text, the Caravan version (short commit), `model_type`, and the `tie_word_embeddings` flag. No paths, hostnames, IPs, or tokens. The user reads, edits, and submits it themselves; Caravan sends nothing by itself. New `.github/ISSUE_TEMPLATE/model-report.md`; `model-report` label created on GitHub.
- `/api/models` rows now carry `model_type` and `tie_word_embeddings`; the response carries `caravan_version`.
- **Opt-in warning ping** (`proxy/web_alert.py`): off unless `CARAVAN_ALERT_WEBHOOK_URL` is set (default for everyone: off, no thread, no network). When set, the web server POSTs `{model, warnings, mini, caravan_version}` once per (model, warning set) when `/api/models` first shows it. Optional `CARAVAN_ALERT_WEBHOOK_KEY` goes out as both `Authorization: Bearer <key>` and `X-Webhook-Key: <key>`. Dedupe in `~/.caravan/alert-sent.json`; a failed POST isn't recorded, so it retries on the next picker refresh. Background daemon thread, 5 s timeout, never blocks the UI.
- Tests: 6 new (`tests/test_day18_model_report.py`): off when unset, payload shape, dedupe, new warning set re-pings, failed post retries, HTML link + template. Full suite 467 OK (32.3s).

### GGUF Optimize now runner (offline-tested) — 2026-11-07
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

### Picker warnings for risky checkpoints — 2026-11-07
- `mlx_arch.model_warnings(config, weight_map)` flags four cases. It only warns and never blocks:
  - a top-level `*_text` model_type that isn't in the remap table
  - config ties embeddings but the files ship `lm_head` (the Dark Champion case)
  - config says untied but there's no `lm_head` (the output layer would be random)
  - `*_mtp`/`*_nextn` helper heads
- Carried through `inspect_tree` → node inventory → catalog rows (`warnings`). The model picker adds a ⚠ to the name, and the warnings show in its tooltip.
- Tests: 6 new. Full suite 456 OK (32.8s).
- Live check: after the Minis pull this, Dark Champion should show ⚠ with the tie note.

### MTP layers in split planning — 2026-11-07
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

### Rope scaling for classes that ignore it (mixtral etc.) — 2026-11-07
- Some mlx_lm classes ignore `rope_scaling` because they build a plain `nn.RoPE`. Examples: mixtral, qwen3_moe, phi3, gemma2, and about 40 more in mlx_lm 0.32.2.
- `proxy/mlx_arch.fix_rope_scaling()` swaps those for `mlx_lm.models.rope_utils.initialize_rope(...)` when config (or text_config) asks for scaling. Types covered: llama3, yarn, dynamic, and linear.
- Applied after load in the single-Mini worker and in split `Stage` (lead and packer). Classes that already scale (llama, qwen2/3, gpt_oss) are left alone. Site-packages is not edited.
- Tests: 5 new (fake RoPE/config). Full suite 445 OK (32.8s).
- Live check (testing window): load Dark Champion. Worker/packer logs should show `rope scaling: applied llama3 to N attention layer(s)`, and a long prompt should stay coherent.

### Releases — 2026-11-07
- First daily source release: `day17-2026-11-07`; main fast-forwarded to current work.
- Root INSTALL.md covers the web UI, dependencies, private-network setup and more Minis.
- Daily process: [RELEASES.md](docs/RELEASES.md). ZIP/tar.gz exclude lab video media.



### GGUF split hardening and picker downloads — 2026-11-06/07
- Picker downloads GGUF quants (one file, lead only) on the shared job system; finished downloads auto-load only when idle.
- Re-attach to a running GGUF split after a web restart; tensor-split from live free RAM; watchdog cleanup; plain 502 on peer loss mid-chat.
- CLI GGUF split moved to SSH tunnels; `agent/rpc_gate.py` removed (one mechanism). MLX-only Settings disabled for GGUF; Topology names Minis.
- Robustness: 5 cycles 20/20 OK, Stop mid-load and peer kill leave 0 processes. Known limit: GGUF Resume restarts from 0 %.

### Web helper consent and inventory — 2026-11-06
- Ask explicitly before downloading missing split-MLX guess-ahead helpers; allow reconsidering in Settings, and use normal resumable download jobs on the lead.
- No permanent silent decline for non-interactive loads; legacy silent declines no longer suppress the web prompt.
- Show individual draft helpers and native MTP heads in Topology disk inventory; protect helpers while any model is loaded.
- Tests: 6 new helper tests; full suite 371 passed (32.576s). Initial concurrent-work run: 365 tests / 1 GGUF fixture error, retained in WEB.md.

- Settings: validate HF tokens server-side, hide accepted-token input behind “Use a different token”, retain Cancel and saved-file removal, distinguish rejected credentials from unavailable checks.

### Optimize now scheduler (PR #9 replacement, 2026-11-07)

- Replace the hidden Deep/Quick coverage runner with paired, one-option A/B
  trials; keep everyday Auto learning separate.
- Add worker pause/hold/commit/release controls, web Pause/Resume, hardware-scoped
  losses and raw results, and cancel/error winner restoration.
- Preserve placement, config pins, PID ownership and web worker-keeping/adoption.
- See [OPTIMIZE-NOW.md](docs/OPTIMIZE-NOW.md) for the PR comparison and all test
  attempts, including failed runs and deployment status.
- Live testing also found/fixed an unnecessary single-Mini baseline reload and
  post-restart load-entry/recovery-release bugs. Final code passes 407 tests on
  box/EXO1/EXO2 (EXO1: one existing Node-only test skips), plus 24/24 theme parity.
