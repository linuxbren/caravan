# Historical development record

These notes describe an earlier test environment, not installation defaults.
For current instructions use the [documentation index](../README.md).
Older machine names are explained there.

# Optimize now: current-branch replacement for PR #9

## Review (7 November 2026, CT)

PR #9, `Replace Deep/Quick with one-at-a-time Optimize now`, head
`256e1e0`, is one commit / 10 files / +1254 −281 lines. Its description says
that walk-away tuning tries each option once against the current best, reloads
only for an Auto reload knob needing a trial, and keeps ordinary Auto learning.
GitHub reports it conflicting (`mergeable=false`, `rebaseable=false`). It was
read as a diff, not merged, rebased or cherry-picked. Work is based on `fe230ca`
on `caravan-v3-mlx-split`, edited directly without a cloud agent.

The PR adds:

- A/B arms for helper, shared prefix, pipeline width, KV, fused kernels,
  keep-warm and one neighbouring packer layer cut; 3 replies per arm.
- A combined `/caravan/sweep` control for pause, live holds, commit and release.
- Hardware-specific losing values, Auto-only scheduling, skipped known losers,
  winner persistence, progress/ETA, tests and wording/docs.

Checked against the actual current code, Riley's missing-work list was correct:
`web_optimize.py` was still the Deep/Quick coverage/prompt-feeding loop, there
was no sweep endpoint and no A/B hardware-loss store. The UI already said
Optimize now, including a hidden legacy Deep/Quick selector. Existing ordinary
learning, reload trials, blocking incompatible KV, single/split entry keys,
PID ownership, GGUF SSH/RPC and web restart/adoption are newer than the PR.

## Replacement rather than transplant

- Pure planning/persistence lives in `agent/optimize_schedule.py`; MLX-free
  worker controls in `agent/sweep_control.py`. Existing everyday TS APIs remain.
- One option, one incumbent arm and one challenger arm, with identical prompts,
  temperature 0 and 96-token caps. Three samples each; a challenger needs the
  existing 3% improvement margin. Shared-prefix arms seed a prefix before TTFT
  measurements. Pipeline arms send the same pair and score actual aggregate
  tokens/wall time. Other knobs use the existing normalized decode metric.
- Other live knobs are held; unrelated pending reloads are not consumed.
  Flags/config pins remain authoritative. Auto reload knobs are forced only
  during the owned switch. Original page/effective settings and placement are
  retained. A reload only happens when the measured reload value changes.
- Saved best values, not a temporary everyday probe, seed the incumbent.
  Incomplete/invalid/failed/canceled measurements never create a win or loss.
  Normal completion and cancellation/failure restore winners before releasing
  everyday learning. Cancel during reload finishes that operation, restores the
  winner if necessary, and sends no more benchmark prompts. Recovery can require
  one additional reload; a recovery failure is reported rather than hidden.
- `POST /caravan/sweep` accepts `pause`, `hold`, `commit`, `release`; commit
  records are persisted before publication in memory. Bad values and conflicting
  explicit flags get 400. Worker controls execute on the engine queue/learn lock.
- The web API adds `/api/optimize/pause` (`{"paused":true/false}`), keeps start
  and cancel, and refuses load/unload during an owned sweep (409: cancel first).
  The Settings UI shows schedule/skips and Pause/Resume rather than coverage.
- The PR's fingerprint was only single/spanned + two RAM numbers, and its loss
  box discarded the previous hardware's losses. Our hash includes the identity,
  chip, total RAM, CPU count, role and peer of every participating Mini, sorted
  stably. It ignores free RAM, temperatures and utilization. Results/losses for
  multiple hardware hashes coexist under each model entry's
  `optimize_hardware`, with raw per-arm scores and timestamps. Missing hardware
  telemetry refuses the run instead of reusing ambiguous losses.
- The scheduler has no fixed Mini count. It uses worker capabilities and actual
  placement. Existing MLX remains two-stage; this work does not claim to add
  N-stage MLX. GGUF already supports arbitrary Minis but does not expose MLX
  knobs: Optimize now requires an MLX worker, so GGUF is rejected without unload.
- Native MTP / adaptive prompt-lookup combinations remain excluded. Missing
  helpers and unsupported KV are skipped, not enabled by a benchmark.
- New-web adoption releases abandoned live sweep holds without killing workers.
  A hard crash cannot resume an interrupted benchmark; normal reload status
  still exposes any reload value differing from a saved winner. The scheduler
  does not auto-restart on adoption. KEEP_WORKERS, PID tracking and GGUF adoption
  paths remain intact.

## Verification ledger (including unsuccessful attempts)

All timings below are elapsed test runtime, not inference performance.

- Box run 1: 381 tests / 31.412 s, **2 failures + 2 errors**. Three were old
  Deep/Quick-runner expectations; one was an overbroad edit of `reload_status`
  referencing `apply_pending`. Fixed the edit and replaced only obsolete runner
  tests; retained independent reload-learning tests.
- Targeted run 1: 22 tests passed (initial scheduler/control checks).
- Targeted run 2: 31 tests / 0.315 s passed (scheduler + legacy reload tests).
- Box run 2: **399 tests / 32.249 s passed**.
- Targeted run 3: **25 tests / 0.834 s passed**, including actual localhost
  worker HTTP pause → hold → commit → release and the paused ordinary observer.
- Box run 3: 403 tests / 32.689 s, **1 error** in a new launcher test: it used
  `fuse_kernels=off`, which the panel doesn't accept. Corrected it to an On pin
  and an opposing forced Off trial. Also canonicalized active `all` fuse mode.
- Browser parity attempt 1: did not launch; `puppeteer-core` was missing. Installed
  that test-only dependency in `/workspace/optimize-tools`, outside the repo.
- Final box suite / browser parity / Mini suites / live run: results appended
  below as completed. No simulated test score is an EXO1 inference measurement.

## Deployment and live checks

Pending at the initial implementation commit: clean-pull sync, full suite on
both Minis, short EXO1 API trial and Obsidian diary update. Both Minis initially
reported `fe230ca` and an untracked `proxy/web/index.html.bak-pre-amber`; these
unrelated backup files were left alone. Before deployment EXO1 reported Qwen3
30B-A3B 4-bit MLX, single, healthy, ready; Optimize was idle. No model was
unloaded by the read-only check.

PR #9 must not be merged. Its closure/comment is a separate external action;
replacement commit hashes and final verification should be included in the
closure comment once authorized.

### Final pre-deployment box checks

- Targeted run 4: **26 tests passed** (worker controls, scheduler, forced reload
  pins and queue isolation); JavaScript syntax and Python compilation passed.
- Box run 4: **403 tests / 32.661 s passed**.
- Browser parity run 2: **22/24**. The two mismatches were Models drawer data
  arriving during the comparison (57 vs 96 controls), not a Settings control's
  font/geometry mismatch. A cache-warmed repeat was started; its result is
  recorded separately rather than dropping the unsuccessful run.

### Deployment and first live run (12:07–12:09 PM CT)

- Implementation commit: `24b3238`, pushed and clean-pulled onto EXO1
  `~/dev/caravan-v3` and EXO2 `~/cv3`. Untracked old HTML backups were not touched.
- EXO1: **403 tests / 33.623 s**, successful, **1 skipped** (Node isn't installed
  there, so the existing HF-token JavaScript assertion test skips). Verified
  separately: HF tests 6 / 0.002 s, 5 passed + that 1 skip.
- EXO2: **403 tests / 34.346 s**, all passed.
- Cache-warmed browser parity run 3: **24/24** theme × view × desktop/phone
  comparisons within 1 px. Static theme tests and JS syntax also passed.
- Restarted only EXO1 web, with `CARAVAN_WEB_KEEP_WORKERS=1`; it reattached to
  the same running Qwen worker PID 24646. Reloaded Qwen single once to install
  the new worker endpoint (PID 50778); the web-only restart had not killed it.
- Started Optimize, paused before any benchmark prompt (**0 prompts / 0 reloads**
  at pause), held helper Off, committed the existing KV incumbent 16 with no
  losing value under the actual hardware hash, then resumed. All API controls
  returned success. This control-only commit is marked in the store as a manual
  check, not benchmark evidence.
- The full first live pass completed: **12 prompts / 5 reloads / 1.51 min**;
  mean reply **2.053 s**; final measured reload **12.373 s**; no inference errors.
  Every progress sample had zero or one running option, never two.
- KV incumbent 16 normalized decode scores:
  `[30.769231, 50.420168, 50.156740]` (mean **43.782046**).
  Challenger 8: `[29.310345, 49.663735, 49.689441]` (mean **42.887840**,
  **−2.04%**). Kept 16; recorded 8 as a loser on this hardware.
- Fused incumbent Off: `[30.630631, 50.314465, 50.209205]`
  (mean **43.718100**). Challenger On:
  `[30.222222, 50.182959, 50.130548]` (mean **43.511910**, **−0.47%**).
  Kept Off; recorded On as a loser. These are short A/B tuning scores, not
  broad model-speed claims.
- **Live-discovered bug:** the old single-Mini entry contains a keepalive winner
  although single workers report keepalive as unavailable. Overlaying it into
  the baseline caused an unnecessary initial reload. Fixed baseline overlay to
  keep unavailable options at their actual running values; added two regression
  tests (also covering a saved helper winner when no helper is installed).
  The 5-reload first run is retained here, not silently replaced by a good run.
- Qwen3 30B-A3B 4-bit MLX finished single on EXO1, healthy and ready; KV 16,
  fused Off, worker learning unpaused. Raw first run:
  EXO1 `/tmp/optimize-live-check.json`.
- Box run 5 after the live-discovered baseline fix: **405 tests / 32.583 s**,
  all passed. Follow-up deployment/live results recorded below.

### Second live run and adoption correction (12:11 PM CT)

- After `c9b60d6` sync: EXO1 **405 / 34.121 s** successful (same Node-dependent
  skip); EXO2 **405 / 33.760 s** all passed.
- Web-only restart preserved the same Qwen worker PID **50958**. The second pass
  correctly skipped KV8 and fused On as already lost, selected KV4, and sent
  its 3 incumbent prompts with **0 initial reloads**: baseline fix verified.
- **Run failed:** **3 prompts / 0 reloads / 0.12 min**, mean reply **2.081 s**.
  The adopted `_loaded_entry` was an inventory/fit row whose `available_lead`
  was false. Its first requested switch failed preflight with
  `FileNotFoundError: model not on this Mini: qwen3-30b-a3b-4bit`; recovery hit
  the same invalid entry. No worker was killed and no new loss/winner recorded.
  Cleanup had also skipped release after recovery failed, leaving the live
  worker paused. Released it immediately through `/caravan/sweep`; response
  confirmed `paused:false`, Qwen stayed single and healthy.
- Corrected adoption to retain a resolved `catalog.get_model` load entry plus
  the actual adopted run mode, not a UI fit row. Cleanup now attempts release
  even if restoring fails. Added regression tests for both. Confirmed the
  resolved Qwen path really has `available_lead:true` and one-Mini placement.
- Targeted checks after correction: **30 tests / 0.838 s**, all passed.
  Raw failed run remains EXO1 `/tmp/optimize-live-check-final.json`.
- Box run 6 after adoption/cleanup corrections: **407 tests / 32.174 s**, all
  passed. Changed modules also parsed as Python 3.9 syntax successfully.

### Final verified state (12:13–12:14 PM CT)

- Recovery/adoption replacement commit: **`f98cc1a`**, following baseline fix
  **`c9b60d6`** and implementation **`24b3238`**. All pushed as linuxbren.
- Full suites on final code: box **407 / 32.174 s** passed; EXO1
  **407 / 34.214 s** successful, 1 existing Node-dependent UI test skipped;
  EXO2 **407 / 34.719 s** all passed. No final suite failures.
- Another web-only restart again retained worker PID50958, ready and unpaused.
- Third live run after adoption fix: **6 prompts / 2 reloads / 0.69 min**,
  measured end-to-end check **42.282 s**; mean reply **2.135 s**, final reload
  **14.413 s**. Only KV4 was tried: KV8 and fused On were skipped from persisted
  hardware loss records. There was no unnecessary initial reload. Every sample
  had one or zero running options.
- KV16 scores `[32.380952, 50.847458, 49.792531]`, mean **44.340314**;
  KV4 scores `[37.229879, 49.663735, 49.408132]`, mean **45.433915**
  (**+2.47%**). That does **not** clear the 3% switch margin, so retained KV16
  and recorded KV4 as not beating the incumbent, not as an inference failure.
- Fourth, skip-only live run: **0 prompts / 0 reloads**, successful (**1.571 s**
  API-check elapsed including hardware collection). This confirms losing values
  survive worker reloads and don't re-run on the same hardware.
- Final model: **Qwen3 30B-A3B 4-bit MLX, single on EXO1, healthy and ready**;
  KV16, fused Off, `sweep_paused:false`. No unrelated workers were restarted.
- Raw successful rerun: EXO1 `/tmp/optimize-live-check-verified.json`.
  The first run and failed second run remain alongside it. All repo changes are
  documented here, `DAY17.md`, `WEB.md`, `CHANGELOG.md`; diary is Omarchy
  `~/Documents/obsidian/Projects/Caravan/Optimize Now Scheduler.md`.
- PR #9 remains open: the actual request found in Brenden's Riley conversation
  explicitly authorizes personal reimplementation, but closure/comment appeared
  only in the assistant relay. No closure or comment was sent without that
  explicit external-action approval. Suggested close comment (after approval):
  "Reimplemented this on caravan-v3-mlx-split in 24b3238, c9b60d6 and f98cc1a,
  keeping the newer reload safeguards. The full suite passes on the box and
  both Minis, and the live pause/hold/commit checks passed. Closing this stale
  PR without merging it. Details and all test runs are in docs/OPTIMIZE-NOW.md."

Remaining limitations: the existing MLX backend is two-stage, not N-stage;
GGUF does not expose MLX optimization knobs. Native MTP/adaptive lookup sweeps
remain intentionally excluded. A hard web crash doesn't resume a benchmark;
adoption releases live holds and normal tuning status exposes reload drift.
