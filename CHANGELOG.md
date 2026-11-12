### Day 21 release — day21-2026-11-10 (published 2026-11-10 CST)

## Day 24 — quieter page and Advanced sections (published; pending live review)

- Settings: Self-tuning stays visible; other optimizations, Optimize now,
  and Apply & restart sit under a closed Advanced section. Self-tuning
  On/Off takes effect immediately on a loaded MLX model, with no reload.
  After a self-tuning or Optimize now
  run, the Self-tuning section shows that model's before and after speed
  as two lines ("Before · Write 88.4 tok/s · first token 0.29s" and
  "After · Write 94.5 tok/s · first token 0.15s"), using the same wording
  as the reply stats, empty until a run has finished, stored with the
  speed averages. The same two lines also appear next to the control that
  produced them. The slots are reserved so Settings rows do not jump.
  The Helper download button on Guess-ahead stays in a reserved slot and
  is not rewritten when status or helper polls repeat the same result.
- Models: Reasoning is renamed Thinking. Default filter chips are Chat,
  Coding, Thinking, Tools, and Vision. Embedding, any-to-any, text-to-image,
  text-to-video, text-to-speech, and Decision stay available behind Advanced
  so Caravan can sit between an agent app and a model. The list summary
  follows the selected fits-on chip ("fit on 1 Mac") and says Macs, not
  nodes. A Family menu lists known families present in the results. Row
  hover shows maker, release date, context, and capabilities. Each
  download in progress has its own stacked card, and MLX and GGUF use the
  same friendly Mac name.
- Topology: Balance and Thunderbolt stay collapsed until clicked. Balance
  idle status is plain text, split into "already applied" and "not safe to
  apply".
- Chat: Clear chat is renamed New session. Option chips sit in a Current
  optimizations box, in Settings order with Self-tuning first, with hover
  hints. The Specifications box is replaced by a quiet per-model,
  per-optimization average under the input, stored on the 1st node. During
  live review the line was changed to use the same wording as the stats
  under each reply, with a leading Average label ("Average · Read 165 tok
  at 200 tok/s · Write 10 tok at 20.7 tok/s · first token 0.34s · total
  0.78s"); fields with no data yet are left out. The "Built in the open"
  title and tagline are removed; the line reads "Your Macs. One model."
- Published. No `day24` tag yet; that waits for live review. See
  [Day 24](docs/DAY24.md) and [release notes](docs/release-notes/day24.md).
  A `caravan update` from the Day 23 pin picks this up and reloads a
  loaded model (model-running code in `agent/` changed). A follow-up
  from the first Day 24 pin (chat average wording) does not reload the
  model. A later live-review follow-up (whole-repo fetch for any
  model without a top-level `config.json`, including image, video,
  text-to-speech, and speech-to-text/ASR; "Download only, Caravan
  can't run image models yet" and the same shape for video and
  speech, for every Advanced type Caravan cannot serve; plain
  download errors and friendly Mac names on every download card)
  changes `agent/mlx_split_fetch.py`, so an update from that pin
  reloads a loaded model; the same model is restored.
  A later live-review follow-up (two-line before/after in tok/s, shown
  under Self-tuning and by the button that produced the result) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running.
  A later live-review follow-up (reuse or replace Caravan's leftover
  SSH forward after a web restart that kept the model; never kill a
  process that is not ours; load status uses friendly Mac names and
  no paths; a remaining tunnel error is "Couldn't start the model on
  the 2nd Mac. Try loading again.", with detail in the log only) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (GGUF Settings rows and trusted web
  Load flags — flash attention, automatic 16- or 8-bit memory
  compression never 4-bit, prompt batch, and saved slots; Optimize now
  and self-tuning compare 16-bit vs 8-bit and score read speed,
  first-token time, and write speed; Before/After lines work for GGUF)
  does not change `agent/`, `runtime/`, or the requirements files, so
  an update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (Self-tuning and Optimize now errors
  show a short plain reason next to Self-tuning, for example that a
  trial of Memory compression was rejected; full detail in the log
  only; no hostnames or paths) does not change `agent/`, `runtime/`,
  or the requirements files, so an update from that pin keeps a
  loaded model running. The web page still restarts.
  A later live-review follow-up (Tune again sits next to Self-tuning,
  outside Advanced, and always runs a fresh trial on the loaded model;
  Reset tuning clears saved results without unloading; one plain line
  when nothing is faster instead of two identical Before and After
  lines; the Self-tuning hint is for each model, not only MLX) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (Auto-tune section: Tune again and
  Reset tuning sit under an Auto-tune heading outside Advanced, in an
  indented block with the Before and After lines; Auto-tune works
  whether Self-tuning is On or Off; the page says Auto-tune where it
  used to say Optimize now; API routes unchanged) does not change
  `agent/`, `runtime/`, or the requirements files, so an update from
  that pin keeps a loaded model running. The web page still restarts.
  A later live-review follow-up (Campfire replaces Nebula, drawn in
  SVG and CSS with no photos; saved Nebula opens as Campfire; Auto-tune
  says Start until this model has been tuned, then Tune again) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.

## MIT License (2026-11-12)

- Caravan is open source under the [MIT License](LICENSE). Copyright (c)
  2026 Brenden Dawson. One adapted file keeps its own MIT notice:
  [agent/native_mtp.LICENSE](agent/native_mtp.LICENSE).

## Day 23 — clean-install fixes (published; live testing passed)

- Live testing on both Minis passed on 2026-11-11 CST: single-step update,
  remote access from another device, one-Mac and split MLX and GGUF
  downloads with load and chat, Add a Mac from placement, reboot, and
  uninstall then reinstall.
- `caravan start` says "Caravan started" or "Caravan is running",
  whichever is true, instead of "Service started (or already running)".
- `caravan update` is now a single step: it stops what is needed, installs the
  verified package, and brings the page back. A loaded model stays running when
  the model-running code did not change; otherwise it is reloaded and Caravan
  says so. A failed update restores and starts the previous version. If Caravan
  is already current, it says so and changes nothing.
- Opt-in Tailscale access from other devices: `caravan remote on|off|status`,
  one optional install question, and an **Open from my other devices** Settings
  switch. The page stays on 127.0.0.1; only the user's Tailscale network can
  reach it. Uninstall turns the share off. Off by default.
- Live-install follow-up: visible-page automatic model-list refresh with selection preservation;
  hide metadata-only starter models; Add a Mac from placement with return to fresh options;
  one-third-width desktop drawers and full-width mobile drawers.
- Clarify the already-enabled self-tuning default as On, record it in fresh config,
  and preserve existing Off/pinned settings. Worker learning is enabled before saved winners.

- Supply a checksum-pinned official llama.cpp b12283 engine on every Mac install/update.
- Download complete multi-part GGUF sets, select whole-file/split behavior automatically,
  and show downloaded models and useful load errors in the normal picker.
- Simple status, detailed doctor, safe backed-up startup-file replacement, quiet discovery,
  and idempotent Terminal PATH setup.
- Add-a-Mac flow inside Topology, first-run invitation and themed two-column setup.
- Complete confirmed uninstall: all owned local jobs/workers/data and marked PATH/SSH entries.
- Beginner guide wording and portable regression tests. See [Day 23](docs/DAY23.md).
  Remaining untested gates (fresh account, Gatekeeper, FileVault, a finished
  new-Mac pairing, old-startup-file replacement, and some engine paths) are
  listed there.

## Day 21 follow-up — Mac installation and documentation

- Friendly Mac-owner README and current Day 20/21 setup, Balance, restore,
  auxiliary title-worker and read-only Thunderbolt guidance.
- Mac-only no-Git/no-Homebrew bootstrap, checksum-verified source and uv,
  private Python, read-only doctor, and safe per-user control command.
- Prepared repeatable checksummed source-package build and daily checklist.
- Experimental: no signed app/pkg, automatic pairing, fully locked dependencies
  or fresh-account/FileVault-on certification. Day 21 tag remains unchanged.

- Clearer Topology Balance (Auto default, per-Mini bars, Adjust sliders, live preview, explicit Apply / Back to auto) with black/gray Apply and locked reload state.
- Trusted Thunderbolt inventory, bounded interface-pinned TCP22/SSH identity checks, and an opt-in N-Mini plan preview with no apply endpoint. Live two-Mini proof: EXO1→EXO2 verified; reverse TCP reachable but SSH identity unverified.
- Physical aux title-worker reboot check passed on EXO1: Huihui 24/40 KV16 ready 37.3s after boot, aux health 200 at ~47.1s, title sidecar 0.135s, full 19-tool Hermes replay 11.504s. EXO2 itself did not reboot; its packer was relaunched during restore. Day 20 already proved two-Mini main-model restore.
- Full suite at tag: **907 tests passed in 45.871 s**, no failures/skips. Details and remaining limits: docs/DAY21.md, docs/BENCHMARKS.md. Install: INSTALL.md, docs/SERVICES.md.
- A later two-Mini cold reboot at 17:29 CST failed automatic restore on a Thunderbolt en2 IPv4 race. **Fixed after release in `51d697a`**: typed retryable unreadiness, bounded backoff, “Waiting for Thunderbolt link…”. Suite **912 passed in 46.264 s**. After a keep-workers web-only restart at 17:38:47 CST, Huihui 24/40 KV16 restored at 17:39:00; aux health 200; title sidecar 0.165s; 19-tool Hermes 11.132s wall / 0.316s TTFT / 6.26 tok/s.
- Physical two-Mini confirmation at 17:44–17:46 CST with `51d697a` deployed: both Minis took a new boot; Huihui 24/40 KV16 auto-restored in 39.110s (EXO1 boot-to-ready); aux health 200 at ~45.8s; title sidecar 0.154s; 19-tool Hermes 11.368s wall / 0.399s TTFT / 6.26 tok/s. The waiting-status retry was not observed on this pass (IPv4 was present before packer start). Tag `day21-2026-11-10` stays on `b6c9394`.

### Day 19 release — day19-2026-11-08 (published 2026-11-09 CST)
- Balance controls and arbitrary-stage MLX planning/transport; installer and native launchd services; per-stage pinned/checksummed own-file fetch. Strict GGUF independence remains partial; N-stage Optimize and three physical Minis remain unverified.
- Web restores the last successfully loaded model and exact split; explicit Unload saves no model. Fixed model jobs removed from default setup. **Restore-last-model reboot test: pending, deferred to the next dev day.** Earlier fixed-model reboot success does not validate the revised design.
- Full suite: **738 tests passed in 42.600 s**, no failures/skips.
- Remote access hardening 8ff3852: LAN/TB fallbacks and non-root Tailscale recovery guards (5/5 routes, 16/16 mocked guard cases, 3/3 fallback cases).
- Preserved Huihui Qwen3.5-27B Claude 4.6 Opus abliterated 4-bit, restored EXO2/EXO1 24/40; web/proxy correct short replies, ~0.8 s first token and 5.4 tok/s writing. No reboot or web restart; no video/X draft now. Install: INSTALL.md, docs/SERVICES.md. Details and remaining limits: docs/DAY19.md.

### Day 19 last-model auto-start design — 2026-11-08 (not a release)
- Replaces the normal fixed-model service mode with web-owned last-successful-model restore: atomic model/engine/placement/counts/settings persistence, explicit unload tombstone and one-shot normal UI-path replay. Failed loads keep the previous successful selection; missing Minis/files/memory give a clear idle warning, no auto-download/retry/crash loop.
- UI model switching and Balance remain unlocked. KEEP_WORKERS adopts existing owned local/pipeline/GGUF workers; remote single-Mini worker/tunnel adoption verifies identities and refuses reused PIDs. Normal split UI loads resolve explicit per-node Thunderbolt interfaces through the shared N-node planner.
- Removed only the two installed fixed Qwen jobs; kept web/model files/cache/logs. Normal UI-path Qwen24/40 load/save passed (10.121s), correct cold reply native5.45tok/s /1.7471s wall. New-mode EXO2 restart then failed to return to SSH within360s; EXO1 was NOT rebooted. Native automatic restore/switch/unload tests remain blocked, not passed. Last Qwen intent preserved; final split is not healthy while EXO2 is unreachable.
- **738 tests pass (44.459s), 44 new restore/HTTP/adoption regressions** including safely rejected unsupported UI settings preserving the last successful preference. Exact native evidence/state/recovery steps: DAY19.md and BENCHMARKS.md. No release/tag.

### Day 19 authorized reboot recovery — 2026-11-08 (not a release)
- Rebooted EXO2 first (then repeated after a fix), then EXO1. Existing auto-login/FileVault-off accounts returned unattended; permanent launchd Qwen/web services answered correctly. No login/security/network settings changed.
- Fixed changing Thunderbolt link-local IPs using explicit verified `tb://` / trusted-SSH `ssh+tb://` service endpoints, owned-child rebind and no LAN data fallback. Native EXO2 stage ready 48.533 s; EXO1 web 42.960 s / split 59.815 s; first correct reply observed 79.569 s after EXO1 restart, including inspection delay.
- Fixed stale live-peer display, inflated short MLX UI write rates/cached-read rates, and native launchd error-5 restart races with bounded safe retries (no root/unknown-process killing). Native cold 5.43 write tok/s; after web restart 5.02, warm cache retained. Historical inflated UI benchmarks are labeled, not silently reused.
- **694 tests pass (40.143 s), 21 new reboot regressions**. Permanent fixed-model services left healthy; full timings, raw-artifact locations, remaining account/hardware limits and UI ownership notes: [DAY19.md](docs/DAY19.md), [BENCHMARKS.md](docs/BENCHMARKS.md). No release/tag.

### Day 19 fresh install and next-login staging — 2026-11-08 (not a release)
- Native isolated-HOME fresh clone/venv/dependency install reached the web UI in 96.189 s; repeat 1.449 s, same PID/config. Explicit native status/restart/log/uninstall checks passed; temporary environments cleaned up. No separate account was created because noninteractive sudo required a password.
- Fixed selected-port installer output. Added explicit `--no-start --stage-login`: real LaunchAgents/configs prepared for next login without taking over today's unmanaged workers or web; loaded jobs are protected. Ten new regressions; **673 passed (39.892 s)**.
- Real EXO1 web/Qwen lead and EXO2 Qwen packer plists installed but deliberately not loaded. Original PIDs 69242/57464/54170 preserved. **No reboot or logout**; [DAY19.md](docs/DAY19.md) records the exact interruption/approval plan and [BENCHMARKS.md](docs/BENCHMARKS.md) the measured install results.

### Day 19 authorized live checks and fixes — 2026-11-08 (not a release)
- Two-Mini Balance/picker reload, actual three-stage 11/11/10 MLX simulation, correct answers, warm reuse, Save/Restore, web adoption, own-files fetch/stop/resume/restart and GGUF native split checks. Original Qwen3.5-27B 24/40 workers preserved; no permanent LaunchAgents/reboot.
- Fixed inventory metadata readiness, configured execution roots, endpoint-scoped legacy cleanup, verified custom-root adoption, recursive memory guard/nested model dimensions, preserved venv paths, idle-packer graceful stop/TIME_WAIT handling, complete web shutdown responses, verified peer-only GGUF reloads and native GGUF rate reporting.
- **663 tests pass (40.133 s)** in the final post-cleanup full suite (30 new live-fix regressions). Short-run real measurements and failure notes: [DAY19.md](docs/DAY19.md), [BENCHMARKS.md](docs/BENCHMARKS.md). Three physical Minis, GUI usability, multi-shard MLX savings, fresh-account install and permanent login/reboot remain unverified. Historical box-only checkpoints follow.

### Day 19 each Mini’s own files checkpoint — 2026-11-08
- Shared Balance/file preview + explicit Fetch UI/API, per-Mini logical/allocated disk usage, missing-shard replanning and retained-file lists. No automatic pruning or reload. Revision-pinned MLX stage downloads, published SHA256 checks, owned cancellation and restart-discoverable transfers.
- N-stage legacy picker bridge, saved stage-aware inventories/catalog/load plans, configurable own model roots and co-host simulation isolation. No default two-node cap; N-stage Optimize remains gated.
- Experimental GGUF peer-only, verified/resumable tensor Range downloads into the native RPC cache. Picker now fetches a complete GGUF only on the lead. **Strict independence remains incomplete:** llama.cpp needs that full lead file; small tensors/cache misses still cross RPC. [Limitations and API](docs/FILES.md).
- **633 tests pass (39.078 s), 62 new theme 3 tests**. A real-format synthetic GGUF/loopback HTTP/native-cache smoke fetched 12,582,912 peer bytes out of a 37,748,992-byte source, one required tensor only. Not a Mini/inference benchmark. No Mini or Omarchy touched; live steps and failed intermediate runs in [DAY19.md](docs/DAY19.md).

### Day 19 install + auto-start checkpoint — 2026-11-08
- One-command, idempotent native-Mac installer: platform/Python checks, dedicated clean source copy, reusable MLX venv/dependencies, plain output, portable no-write dry-run and safe config defaults.
- Generated per-user web and single/N-stage worker LaunchAgents; owned install/uninstall/status/graceful restart, logs under `~/.caravan`, no sudo or author-specific paths. Split workers run through `caravan_agent.py --service-config`, retry missing peers and stop only their own child.
- Web KEEP_WORKERS plus process-group preservation; late managed-lead adoption; fixed model jobs block conflicting web model control. Web-only auto-start keeps interactive model switching; fixed plans are a separate initial mode.
- **571 tests pass (37.444 s), 42 new theme 2 tests**. Failed intermediate runs and corrections are recorded in [DAY19.md](docs/DAY19.md). Mac install/launchd/login/reboot still pending; no Mini or Omarchy touched. [Guide](docs/SERVICES.md).

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

## Day 20 — full-tool Hermes cache reuse (2026-11-09)

- Isolate MLX auxiliary prompts from the main conversation cache.
- Capture exact system/tool KV and recurrent-state checkpoints during prefill;
  reuse across chats and disk restores with stage-local files and N-stage
  digest checks, without reducing Hermes tools or changing the selected model.
- Add managed loopback OpenAI proxy launchd auto-start (`--kind proxy`).
- 767 tests pass (29 new). Evidence, setup and live validation: docs/HERMES.md
  and docs/DAY20.md. Reboot testing remains deferred.

  Live validation: same Huihui 24/40, 21 tools. Three full-tool follow-ups
  reused 13,182 tokens; prefill 1.17–1.76 s versus ~208 s cold, first visible
  Hermes text 11.57/9.23/9.78 s. A new chat also reused the prefix. Dense
  decode stays ~6.1 tok/s; cold/changed prompts are not instant. Proxy is now
  launchd-managed on EXO1. No reboot/web restart. Full methodology in DAY20.md.


## Mac pairing and paused C++ follow-up

- Add Macs page: nearby discovery, code-confirmed encrypted enrollment, dedicated
  SSH identity/host pin, backed-up node config and suggested N-node order.
- One-button authenticated removal; offline retries retain cleanup credentials.
  Native Remote Login remains an explicit Mac permission, not an installer sudo step.
- Per-account private browser permission plus local Host/Origin/CSRF checks;
  short-lived, one-use codes and durable guess budget. Experimental: security
  review and native Mac acceptance remain open; see `docs/PAIRING.md`.
- Each newly prepared helper gets a browser page. No running model is reloaded
  by pairing and no existing worker plan is migrated silently.
- Park C++ sources under `docs/history/cpp/`; inventory other clutter for approval.
