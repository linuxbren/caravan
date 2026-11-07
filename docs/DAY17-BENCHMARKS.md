# Day 17 performance experiments — 2026-11-06 (CT)

Every run, including failures and negative results, is retained below or in
`bench/results/day17/`. Each row includes model, placement, code commit, exact
prompt/settings and CT timestamp. No vendor figure is a Caravan measurement.

> **Latest, 10:04 PM CT onward:** approved live split matrix completed on `e6640a0`; N2 helper is slower. Qwen is restored single/EXO1, all Auto; the existing queued KV4 trial applied. The dated earlier “pending/no live split/KV16 final” statements below are historical, superseded by the completion section at the end. All139 raw rows (127 responses,12 transport errors) and non-row setup/stall failures are retained.

## Research and initial implementation

- Native MTP source: [Orvena/Orvena-4B](https://huggingface.co/Orvena/Orvena-4B),
  a Qwen3.5-4B fine-tune; [MLX target](https://huggingface.co/Orvena/Orvena-4B-MLX-4bit)
  is 3.1 GB including vision. MLX target omits its MTP head. BF16 index/header
  reads verify 15 head tensors totaling 241,199,104 bytes (230.025 MiB).
- This head does **not** match Qwen3 30B-A3B. It is an EXO2-only matching-target
  experiment. EXO1 Qwen3 stays loaded. Head extraction uses HTTP ranges directly
  from HF, never another Mini. `bench/v3/fetch_native_mtp.py`.
- Runtime architecture follows [mlx-vlm Qwen3.5 MTP](https://github.com/Blaizzy/mlx-vlm/tree/main/mlx_vlm/speculative/drafters/qwen3_5_mtp).
  Native mode is greedy-only, single Mini, one proposed token per verification,
  fresh request caches. Hybrid rejection snapshots and replays; it never trims
  GatedDeltaNet state as ordinary KV. No claim of speed gain before measurement.
- Vendor reports 89.4% held-out acceptance; phone runtime ~21→23 tok/s, 83%
  acceptance. These are **vendor iPhone figures**, not our results.
- `overlap_on=0.50` refers to adaptive **prompt lookup**, not two-chat scheduling.
  Keep default off until remeasured. The already-running EXO1 worker loads no
  helper, runs single-Mini serial, and exposes no live mutation endpoint for
  these options. The original no-reload phase is superseded by Brenden’s explicit
  follow-up approval below; ordinary single-Mini concurrent requests
  are not evidence of split overlap.
- Split N≥2 block verification already existed but had cache-accounting errors:
  all-accepted blocks omitted the last draft input, rejection over-trimmed draft
  KV by one, and EOS returned before rewind. Corrected accounting is pure unit
  tested; live split benchmark intentionally not run without approval.

## Run log

Complete clean follow-up and interrupted/negative attempts are all retained below.

## Local validation

2026-11-06 CT: `python3 -m unittest discover -s tests -p test_day17_mtp_verify.py -v`
passes 7 tests (rejection positions k=1..8, all accept, early EOS, invalid plans,
missing/mismatched heads). `python3 -m pytest ...` failed before test execution:
box system Python has no pytest. Python compile and browser-JS syntax pass.

### Regression validation, 2026-11-06 CT
- Initial expanded run: **63 passed, 5 failed**. One new failure was the option
  order assertion, updated for the new prompt-lookup option. Four were existing
  web-test assumptions/infrastructure: unknown-model inventory calls timeout
  twice, old page-toggle assertion, old section-order assertion. Retained as
  negative results, not silently counted as passes.
- Focused worker, adaptive PL, inventory, native MTP/block and updated option
  suite: **55 passed + 4 subtests**. Actual worker-block tests exercise all
  accept, first/middle reject and early EOS with cache-trim/replay assertions.
- EXO2 first head extraction attempt failed before fetching because target
  folder had disappeared during its download; the download process still held
  open files under that path. Cause not established. Stopped only our own
  downloader and restarted into isolated `~/.caravan/day17/Orvena-target`.
  User models untouched; this is a setup failure, not a speed measurement.

- 2026-11-06 **8:58 PM CT** expanded split/placement/tuning regression:
  **137 passed + 4 subtests, 2 failed**. Both failures are existing optimizer
  test fixtures missing `FakeMgr.state`; no production optimizer change made.
  Experimental settings guard test then passes: **9 passed + 4 subtests**.
- Native mode refuses quantized KV settings (fresh hybrid caches are 16-bit).
  Adaptive prompt lookup explicitly pins one chat and rejects Two chats=2;
  the existing N≥2 pipeline does not implement prompt lookup. This prevents a
  visible Adaptive selection from silently doing nothing.

## EXO2 ABBA attempt interrupted by concurrent UI lifecycle — 9:01–9:02 PM CT

Raw, complete requests/responses/errors:
[`mtp-abba-interrupted.jsonl`](../bench/results/day17/mtp-abba-interrupted.jsonl)
(12 rows: **4 responses, 8 transport errors**). Code commit **b892595**.
Startup/runtime log: [`native-worker-interrupted.log`](../bench/results/day17/native-worker-interrupted.log).
Status evidence: [`collision-status.json`](../bench/results/day17/collision-status.json).

Model **Orvena/Orvena-4B-MLX-4bit**, native head BF16, EXO2-only on localhost
**8294**; temperature 0, seed 17, max_tokens=192, no persistence/learning,
fresh caches. Exact prompts and every setting are embedded in each raw row.
EXO2 had Low Power Mode off; own downloads had completed and picker
jobs were empty immediately before the run. A *new* picker download/model
switch subsequently began during the benchmark, so this is **contaminated and
incomplete**, not a headline performance result.

| CT start | Mode / prompt | Write tok/s | TTFT s | Acceptance | Quality |
|---|---|---:|---:|---:|---|
| 9:01:33 PM | off / count | 36.4915 | 0.1373 | n/a | count-prefix check false: output capped at a partial final number |
| 9:01:38 PM | off / code | 36.6132 | 0.1749 | n/a | Python syntax true; capped output contains only 1 of requested 3 tests |
| 9:01:43 PM | off / quality | 35.7669 | 0.1740 | n/a | exact three-line answer true |
| 9:01:44 PM | on / count | 54.3958 | 0.0934 | 1.0000 | byte-identical to off count, including same truncation |
| 9:01:48 PM | on / code | n/a | n/a | n/a | connection reset |
| 9:01:48 PM | remaining 7 requests | n/a | n/a | n/a | connection refused |

Write speed formula `(completion_tokens - 1)/(total_s - ttft_s)`. Error rows'
`wave_aggregate_tps: 0.0` is an initial harness sentinel (zero successful
completions), **not a measured 0 tok/s inference rate**. No MTP on-mode quality
probe completed. The solitary 36.49→54.40 count pair is not enough to claim
speedup/unchanged quality. Next clean run should raise the token cap or shorten
count/code prompts so quality isn't mis-scored by truncation.

### Concurrent lifecycle evidence and stop condition

Read-only status shows **UI switched to Orvena on EXO2 at 9:01:44 PM CT**, then
**UI stopped workers at 9:02:06 PM CT**. Original EXO1 Qwen3 PID **73853** and our
EXO2 experiment PID **97827** were no longer running. This worker did not call
models/load or models/stop. It restarted only the web server, after confirming
the old process had KEEP_WORKERS=1, and verified Qwen PID 73853 survived that
restart before starting the experiment.

The manager at the time called unscoped `pkill -f mlx_worker.py` in `_kill_packer`
(and a broad local fallback in `_kill_lead`), so any web load/stop can terminate
an independent experimental worker on EXO2. **Stopped further live tests**;
coordinate the picker/browser worker before rerunning. Do not silently reload
EXO1 against the no-touch constraint. Original Qwen state needs restoration by
the coordinating parent, with awareness of any user-initiated model changes.

- Adaptive prompt lookup: **not re-benchmarked**. Original worker was single,
  helper-free, lacked a live settings mutation endpoint; enabling split PL would
  require a reload. No default change justified. Remains off.
- Two-chat mode: **not re-benchmarked**. Single-Mini worker has no split overlap;
  original worker vanished during concurrent UI operations. No default change.
- N≥2 split draft verification: corrected + unit-tested, **no live split run**.
- Matching target and head kept on EXO2 at `~/.caravan/day17/Orvena-target`, with
  a model-inventory symlink `~/.caravan/mlx-models/Orvena--Orvena-4B-MLX-4bit`.
  No user model deleted. Experiment worker had already been terminated by the
  concurrent lifecycle, so nothing else was killed/restarted by this worker.

### Final focused regression — 9:04 PM CT
`uv run --with pytest python -m pytest tests/test_day17_mtp_verify.py tests/test_adaptive_pl.py tests/test_model_inventory.py tests/test_mlx_worker.py tests/test_mlx_split.py tests/test_mlx_backend.py tests/test_placement_load.py tests/test_tuned_settings.py -q`
completed **127 passed + 4 subtests** in **12.31 s** on code `f09f6d0`.
This excludes the previously documented stale HTTP/optimizer fixture failures;
it does not erase those negative results or substitute for live split tests.

## Approved follow-up, 9:09 PM CT onward
Brenden confirmed the earlier switch/stop was **him using the UI**, not an
unidentified agent. Original evidence stays intact. He authorized Qwen reload;
normal `/api/models/load` restored Qwen3 30B-A3B 4-bit, placement one/EXO1.
Auto applied an already-pending KV8 trial; any benchmark reload will pin settings
and record them to avoid mixing learning with measurements.

Worker ownership is now tracked PID + exact script + exact endpoint per node,
with PID identity rechecked before escalation; no process-name sweeps. Historical
lab process-name cleanup commands were replaced by no-ops (safe refusal to
sweep; explicit scoped cleanup needed for reuse). Request-local serial prompt
lookup now permits a single-Mini Qwen on/off comparison after one code reload.
Two-chat single-Mini tests measure actual queuing, not split-stage overlap.

## Completed native-head ABBA — 9:13–9:14 PM CT

Raw: [`mtp-abba-complete.jsonl`](../bench/results/day17/mtp-abba-complete.jsonl);
[`native-worker-complete.log`](../bench/results/day17/native-worker-complete.log).
Runner **f445743**, loaded worker **468acf6**. EXO2 PID99963, localhost8294;
EXO1 remained Qwen PID84363, one/EXO1. The normal UI Qwen reload (84072→84363)
left the independent native worker alive, validating scoped cleanup live.
Both low-power modes off, picker jobs empty, no download processes. Temperature0,
seed17, max768, fresh16-bit caches, no learning/persistence, OFF/ON/ON/OFF.
**12/12 responses, all natural stop, none capped.** Three identical prompts per
wave (exact strings and request JSON in raw rows).

| Prompt | OFF median Write tok/s | ON median Write tok/s | OFF / ON median TTFT s |
|---|---:|---:|---:|
| Count 1…80 | 34.1733 | 56.5985 | 0.11680 / 0.09445 |
| Merge sort + 3 asserts | 36.9483 | 54.1346 | 0.17885 / 0.17680 |
| Exact 3 lines | 36.7097 | 49.5913 | 0.17480 / 0.17620 |
| All 6 responses per mode | **36.9483** | **54.1346 (+46.51%)** | **0.17480 / 0.17545** |

ON accepted **550/560 =98.2143%** proposals (count99.359%, code96.522%, exact100%).
Count and three-line texts are byte-identical across modes and pass complete
checks. Every code response contains3 asserts and passes its generated asserts
plus7 extra cases (empty, singleton, reverse, duplicates, negatives). Function
bodies match; chosen assertion examples differ ON vs OFF. Thus this is a small
semantic quality gate, **not bit-exact decoding or a general quality proof**.
Potential floating-point/batch-shape drift has not been isolated. One OFF count
run fell to31.2443tok/s; retained, not discarded as an outlier.

Reproduce summaries/semantic validation with `python3 bench/v3/day17_summarize.py`;
[`complete-summary.json`](../bench/results/day17/complete-summary.json) includes
all rows and failures, with code execution restricted and time/resource-limited.

## Initial adaptive PL ABBA — 9:14–9:15 PM CT (negative)
Raw: [`pl-abba-initial.jsonl`](../bench/results/day17/pl-abba-initial.jsonl).
Qwen3 30B-A3B4bit singleEXO1 PID84363, worker468acf6, runnerf445743. Self-tune off,
shared-start off, helper off, pipeline1, KV16, fused off. Same three prompts plus
12 repeated copies of one sentence; temperature0,seed17,max768,fresh sessions.
**16/16 responses**. Median Write **50.4466 OFF vs47.1957 adaptive tok/s (-6.44%)**;
TTFT **0.3255 vs0.3185s**. Repeated passage **50.2493 vs46.9168tok/s**. All ON
responses accepted0 draft tokens. Each had one failed proposal and the gate then
stayed closed, including the repeated passage at final overlap1.0.
Count complete and repeated-passage checks pass. All code passes3 generated+7
extra tests. Qwen’s exact-format prompt fails in OFF and ON (Markdown trailing
spaces); this negative is retained, not relabeled a strict pass.

Cause: one suffix mismatch poisoned a high-overlap request before copying began.
Fix: high-overlap mode gets a full acceptance window before sustained misses shut
it off. Low-overlap cold probes still shut off after one bad proposal. Added two
regression tests; focused suite **67 passed +4 subtests**. Default remains OFF
pending the fixed-gate remeasurement. No split or two-chat overlap claim.

## Fixed-gate adaptive PL ABBA — 9:18–9:19 PM CT
Raw: [`pl-abba-fixed.jsonl`](../bench/results/day17/pl-abba-fixed.jsonl).
Worker/runner **589bd92**, Qwen single EXO1 PID84711; same pinned settings/prompts
as initial run, threshold0.50, k4, OFF/Adaptive/Adaptive/OFF. **16/16 responses**,
all natural stop. No user-state change observed by per-request guards.

| Prompt | OFF / Adaptive Write tok/s (median) | OFF / Adaptive TTFT s |
|---|---:|---:|
| Count | 50.4960 /44.5567 | 0.3425 /0.2515 |
| Code | 50.4584 /47.2094 | 0.3255 /0.3285 |
| Strict 3 lines | 47.8327 /47.4864 | 0.3060 /0.3090 |
| Repeated passage | **50.1149 /72.3685 (+44.41%)** | 0.4515 /0.4545 |
| All 8 replies per mode | **50.2398 /47.3128 (-5.83%)** | **0.3255 /0.3185** |

Repeated passage now emits104 of133 tokens from lookup (**78.2% drafted-token
share**), versus0 before the fix; only29 verification rounds. Count:13/310
(4.2% share), code/exact:0. These PL `accepted_frac` fields are historically
**accepted-draft/generated tokens**, unlike native MTP’s accepted/proposed.
The runner retains the original field; do not call78.2% proposal acceptance.
Exact proposal-token totals are not instrumented for PL and are N/A.

Count complete, repeated passage byte-for-byte, and sorting’s3+7 tests pass.
Qwen strict-format still fails OFF and ON due to trailing Markdown spaces;
normalized line content passes. No broad quality or bit-exact guarantee.
**Keep PL default off:** copy is faster but ordinary/mixed prompts regress.
UI help now shows both positive and negative results, not just a speed claim.
Experimental UI loads skip learned reload trials and disable learning; native
mode rejects compressed caches or simultaneous adaptive PL rather than silently
ignoring conflicting settings.

## Single-Mini two-request baseline — 9:19–9:24 PM CT

This is **not** a live split and **not** stage-overlap mode. Qwen stays single on
EXO1; the engine serializes the two requests. Worker/runner **589bd92**, PID84711,
KV16, learning/helper/shared-start off, pipeline1. Temperature0, seed17, max768,
unique session IDs, same count/code/strict-format prompts as the MTP run.

Complete controls: [`concurrency1-before.jsonl`](../bench/results/day17/concurrency1-before.jsonl),
[`concurrency1-after.jsonl`](../bench/results/day17/concurrency1-after.jsonl).
Complete paired repeat: [`concurrency2-complete.jsonl`](../bench/results/day17/concurrency2-complete.jsonl)
(12/12 replies). **18/18 responses** in the complete comparison.
Initial partial attempt: [`concurrency2-interrupted.jsonl`](../bench/results/day17/concurrency2-interrupted.jsonl)
(11/12 rows retained), [`queue-harness-anomaly.json`](../bench/results/day17/queue-harness-anomaly.json),
and [`qwen-worker.txt`](../bench/results/day17/qwen-worker.txt). Background-shell
status froze while its PID/driver were absent; cause unestablished, not blamed
on Brenden. Worker/model remained ready and unchanged. A foreground repeat with
remote stdout redirected completed normally; incomplete data was not overwritten.

| Measurement | One request | Two queued requests |
|---|---:|---:|
| Median server Write tok/s | 50.5126 | 50.4830 |
| Median server processing TTFT s | 0.3160 | 0.3060 |
| Overall harness aggregate tok/s | 46.0763 | 46.5226 |
| Median harness request+guard wall s | 4.5906 | 9.1788 |
| Count aggregate tok/s (median waves) | 47.4655 | 48.2289 |
| Code aggregate tok/s (median waves) | 47.0440 | 47.0520 |
| Strict-format aggregate tok/s (median waves) | 25.7568 | 26.0677 |

Overall aggregate = summed completion tokens / summed unique-wave wall time:
**1084/23.526200375s** versus **2168/46.601003791s** (+0.97%, not a stage-overlap
speedup). `ttft_s` is worker processing time and **excludes queue wait**. Client
first-token timing was not measured (non-streaming requests). Harness wall times
include pre/post UI state-guard calls, which can themselves wait for the engine;
they are **not** a clean end-user chat latency measurement. No default change
justified; single-Mini remains serial. True split N≥2/two-chat performance still
awaits Brenden’s approval to load a split; no split was loaded.

All complete-run counts and3+7 sorting tests pass; strict-format still fails in
all Qwen controls because of trailing Markdown spaces. Off/on/queue raw rows and
semantic summary preserve those failures. Every timestamp in the raw files is CT.

## Validation and remaining limits
- Expanded focused regression on589bd92: **143 passed +4 subtests**,12.31s;
  [`final-regression.txt`](../bench/results/day17/final-regression.txt). Additional
  experimental reload guards then pass a42-test focused run +4 subtests.
- Browser JavaScript parses with `node --check`; Python modules compile. This is
  not a browser screenshot or full end-to-end browser test.
- Native OFF still has the same head resident; only draft execution toggles.
  Peak MLX allocation2.848GB in this short test fits EXO2’s25.8GB RAM comfortably.
  Target/head provenance: [`head-provenance.json`](../bench/results/day17/head-provenance.json).
- No live split; no generic quality proof; no strict bit-identity guarantee.
- Screenshot capture is still pending: executor has no browser/delegation tool,
  and does not bypass that boundary through Shell-driven browser automation.

## Final verification — 2026-11-06T21:28:40.525945-06:00 (CT)
- Source **49b55a8**: **145 passed +4 subtests** in12.44s, command and timestamp
  in [`final-regression-49b55a8.txt`](../bench/results/day17/final-regression-49b55a8.txt).
  Previously reported failed suites remain documented above; not a full-suite claim.
- Qwen3 30B-A3B4-bit **ready**, one/EXO1, PID**85235**, worker8194, UI8190.
  All page preferences restored to **Auto**; active KV16, self-tuning on, helper
  and prompt lookup off, learned pipeline1/shared-start off/fused off; no trial.
  Web restarted with `CARAVAN_WEB_KEEP_WORKERS=1`; same worker PID survived.
- Isolated EXO2 PID99963/8294 stopped by exact PID/script/port helper. Target,
  extracted head and inventory symlink **kept**; no user models deleted.
- Ready-state/API proof: [`final-state.json`](../bench/results/day17/final-state.json),
  [`final-exo1.txt`](../bench/results/day17/final-exo1.txt),
  [`final-exo2.txt`](../bench/results/day17/final-exo2.txt). Live option text shows
  both PL outcomes and serial two-chat semantics; picker jobs empty, no HF fetch
  processes observed on either Mini at final check. Existing unrelated untracked
  screenshots/backups/videos remain untouched; tracked files synchronized.
- [Raw manifest](../bench/results/day17/manifest.json): **85 rows**,77 responses,
  **8 transport errors**, plus the separate11/12-row harness anomaly. All exact
  prompts/settings, raw text, quality negatives, source/worker commits and CT times
  retained. Documentation-only evidence commit follows the runtime source commit.
- Browser/delegation tools are not available to this executor. **No new Day17
  screenshots created**; parent must capture2–3 genuine UI shots at
  `/workspace/dbg/shots/day17-*.png` without reloading/changing Qwen.

## Approved live split follow-up — after9:42 PM CT
Brenden explicitly approved loading Qwen as a split. Preflight `ps` on both
Minis found no downloads/benchmarks; picker jobs empty. Contrary to the stale
file assumption, EXO2 already had a complete17.17GB Qwen4-bit copy at
`~/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit`. EXO1 had the complete
335MB Qwen3-0.6B4-bit helper. **No model download/copy/deletion needed.**
Normal placement helper and `/api/models/load`,24/48 packer layers; original
one/EXO1 placement backed up. Source **ac48fde** on both nodes. Same Day17
three prompts, temperature0,seed17,max768,fresh sessions; KV16, learning/PL/
shared-start off, fused off, keepalive on. Helper k3; one/two HTTP clients
match pipelineN1/N2. UI path explicitly skips the first-load helper micro-gate,
so these recorded HTTP requests are the quality/performance experiment.

Initial N1: **6 replies per mode**, median server Write baseline45.1950→helper
60.2931tok/s. Complete counts and3 generated asserts; strict exact lines retain
the same Markdown-space failure in both modes. Raw files:
[`split-baseline-n1.jsonl`](../bench/results/day17/split-baseline-n1.jsonl),
[`split-draft-n1.jsonl`](../bench/results/day17/split-draft-n1.jsonl).

**Negative:** initial N2 helper count pair timed out around180s; both error rows
retained in [`split-draft-n2.jsonl`](../bench/results/day17/split-draft-n2.jsonl).
N2 without helper also stalled before any result row. Stopped only our own
benchmark drivers; no fabricated0tok/s rate or quality success. Worker/startup
states, failure note, native sample and logs retained with `split-*` filenames.
MacOS refused the documented Python3.14 debugger attach (task-port permission);
no elevation/bypass attempted. On-demand SIGUSR1 stack dumps are added to future
workers’ own stderr, without locals, periodic sampling or decode overhead;
49 targeted tests+4subtests pass. Fresh diagnostic retry pending; model will be
restored to original singleEXO1 after the experiment.

### N2 cause identified by worker-owned stack dump
A fresh bounded N2 baseline completed a count pair, then stalled at the next
code pair. SIGUSR1 dump shows **HTTP handler `apply_memory_guard` and MLX owner
`split_info` concurrently inside `Client.call("stats")` on the same socket**.
Packer waits for the next frame while two lead threads wait for replies. Thus
read-only memory checks can corrupt framing even without helper drafting.
Fix: memory-stat RPC is queued to the MLX/socket-owner thread. A read-only job
class can execute between fully drained pipeline rounds; mutating admin calls
remain deferred until idle. This avoids both the race and serializing entire
chats behind read-only guards. Two targeted ownership/scheduler tests added;
**51 passed+4subtests** focused validation. Fresh live comparison follows.

## Completed approved split matrix — Nov 6, 10:01–10:04 PM CT

Source/loaded workers **e6640a0** on both Minis; initial evidence/diagnostic source
**ac48fde /4ae324a**. The read-only socket-owner fix eliminates the reproduced
N2 deadlock in this bounded rerun. No model file transfer, download or deletion:
EXO2 already held the full17.17GB Qwen copy; existing helper335MB on EXO1.
24+24 layers/48, packer169.254.103.191:5560, lead8194; direct HTTP to lead, not
proxy FIFO. These are the same three Day17 prompts used above, not a larger
quality suite. Each configuration has two waves; N1 has one client, N2 has two
simultaneous clients. KV16, helper k3 when on, self-tuning/shared-start/PL off,
fused off, keepalive on, temperature0,seed17,max768, no thinking, fresh sessions.
Every request's active settings and PID guard are preserved in its raw row.

| Config | CT request starts | Lead PID | Replies | Median Write tok/s | Median worker TTFT s | Overall aggregate tok/s |
|---|---|---:|---:|---:|---:|---:|
| N1 baseline |10:03:18–10:03:44 PM|89522|6|45.0429|0.3140|41.5415|
| N1 helper |10:03:55–10:04:15 PM|89599|6|60.0063|0.3625|52.1061|
| N2 baseline |10:01:43–10:02:13 PM|89330|12|39.8074|0.3855|70.4915|
| N2 helper, multi-token verify |10:02:24–10:03:06 PM|89406|12|27.8321|0.4745|49.7656|

Raw: [`split-fixed-baseline-n1.jsonl`](../bench/results/day17/split-fixed-baseline-n1.jsonl),
[`split-fixed-draft-n1.jsonl`](../bench/results/day17/split-fixed-draft-n1.jsonl),
[`split-fixed-baseline-n2.jsonl`](../bench/results/day17/split-fixed-baseline-n2.jsonl),
[`split-fixed-draft-n2.jsonl`](../bench/results/day17/split-fixed-draft-n2.jsonl).
Corresponding `*-state.json`, `*-run.txt`, `*-lead.txt` retain startup, node/settings
and request output. Lifecycle CT events: `split-fixed-events.jsonl`.

Aggregate = sum completion tokens / sum unique (wave,prompt) wall intervals,
not sum per-request tok/s: N1 baseline **1084/26.094359001s**, helper
**1086/20.842084959s**; N2 baseline **2180/30.925711791s**, helper
**2172/43.644639499s**. Guard overhead is included; server TTFT excludes client
queue wait. This is non-streaming: client-observed first-token timing is N/A.
Two-client baseline aggregate rises **69.69%** over one-client baseline; helper
improves N1 aggregate **25.43%**, but **reduces N2 aggregate29.40%** (and median
Write30.08%). N1 median Write gain33.22% is a different metric from aggregate.
The helper path drains speculative blocks serially to preserve cache ownership,
so it loses normal per-token two-chat overlap. This measurement supports leaving
N2 helper **experimental**, not defaulting to it or promising fewer handoffs
means higher throughput. UI help/chip explicitly includes the negative result.
Existing self-tuning/one-chat defaults are unchanged; these short tests with
shared-start off do not settle long-prompt/shared-prefix performance.

### Per-prompt medians
| Prompt | N1 baseline / helper Write tok/s | N2 baseline / helper Write tok/s | N2 baseline / helper TTFT s | N2 baseline / helper wave aggregate tok/s |
|---|---:|---:|---:|---:|
| Count |45.0590 /60.0063|39.9567 /28.3760|0.3470 /0.4325|74.8219 /53.6025|
| Merge sort |45.0923 /56.2862|39.9077 /26.5558|0.4620 /0.5580|71.1356 /48.4208|
| Strict 3 lines |42.5532 /63.9098|38.6804 /28.4960|0.4325 /0.5305|33.4738 /26.1791|

Helper drafted/generated tokens: **810/1086=74.5856% N1**, **1620/2172=74.5856%
N2**. These are **NOT accepted/proposed**; proposal acceptance is N/A. Pipeline
`split.calls` counters are shared/cumulative across overlapping chats and include
admin/keepalive calls; raw values are retained but not added or marketed as
per-chat verification round trips. Serial helper source/verify-yield counts
likewise are not a direct total wire-RPC count. Block width is k3; all-accept,
rejection and EOS rewind/replay are covered by unit tests.

### Exact prompts and quality

**count**
```text
Count from 1 to 80 in order, separated by commas. Output only the numbers.
```

**code**
```text
Write a Python function merge_sort(values) with a helper merge(left, right), then three assert tests including duplicates and an empty list. Output only Python code.
```

**quality**
```text
Reply exactly with these three lines, with no explanation:
2 + 2 = 4
France: Paris
Water: H2O
```

**36/36 natural stops, none capped.** All12 count responses complete1…80; all12
sorting responses pass their3 generated asserts plus7 additional semantic cases
in a restricted/time-limited child. All12 exact-format responses fail strict
byte-format equality because Qwen emits two Markdown trailing spaces on its first
two lines. Normalized content passes in every mode. Counts and exact-format
outputs agree across configurations; sorting assertion examples vary, so **not
bit-exact output and not a general quality guarantee**. Restricted semantic
results, all raw quality failures, per-mode medians and aggregate denominators
are reproducible via `python3 bench/v3/day17_summarize.py` in
[`complete-summary.json`](../bench/results/day17/complete-summary.json).

### Failures retained, not folded into the successful matrix
- Initial ac48fde helperN2: paired counts timeout180.02/185.01s; two error rows
  in `split-draft-n2.jsonl`. BaselineN2 also stalled before any completed row;
  state/startup/sample retained. No invented0tok/s/TTFT/acceptance.
- Diagnostic4ae324a baselineN2: count pair **39.9793/40.0000 Write tok/s**, TTFT
  **0.463/0.243s**, aggregate**74.8807tok/s**, complete counts; subsequent code
  pair timed out**30.01/35.01s**. Four rows (two responses, two errors) retained
  in `split-baseline-n2-diagnostic.jsonl`, plus lead/packer stack logs. This is
  incomplete and not a full-matrix baseline. The stack proves HTTP memory-guard
  `stats` and owner `split_info` competing for one socket.
- Official macOS Python3.14 remote-exec task-port attach was denied; no privilege
  escalation or alternate attach attempted. Added explicit SIGUSR1 worker-owned
  all-thread stderr dumps without locals or periodic overhead instead.
- First fixed-run orchestrator had an escaped-quote f-string parse error before
  making any load/request. Corrected and recorded as a setup event, not an
  inference failure. Summary tool initially tried parsing lifecycle events as
  responses (`KeyError: mode`); it now excludes `*-events.jsonl`. An exploratory
  aggregate calculation used nonexistent `tokens`; corrected to the recorded
  `completion_tokens`. Neither changed raw measurements.

### Final validation, restoration and storage
- Expanded focused suite: **152 passed +4 subtests,12.44s**. Exact command, source
  and CT timestamp: [`split-final-regression.txt`](../bench/results/day17/split-final-regression.txt).
  This is not a full-suite claim; previously failed suites remain above.
- Original placement restored through normal UI load, original page preferences
  **all Auto**. **Qwen3 30B-A3B4-bit ready single EXO1, PID89648**, worker8194;
  helper/PL off, pipeline1, self-tuning on. Auto applied its **already queued KV4
  trial**, incumbentKV16, remaining3; unlike pinned benchmarks this is **KV4**.
  No preference overwritten to conceal that learned trial. Proof:
  [`split-restored-state.json`](../bench/results/day17/split-restored-state.json).
- EXO2 packer stopped by normal manager cleanup; isolated Orvena stopped earlier.
  Orvena target/head/symlink and pre-existing EXO2 Qwen files **kept**, nothing
  deleted. UI-only restart to refresh help uses KEEP_WORKERS=1; no model reload
  needed for label-only changes. Loaded worker's literal status description may
  retain its older “pending” text until its next normal reload; the new UI chip
  and help use the completed, negative-inclusive result.
- [Updated manifest](../bench/results/day17/manifest.json): **139 rows,127
  responses,12 transport errors**, plus non-row setup/stall evidence. No failed
  or slow run dropped. Screenshots still require the parent browser tools.

### Final served-UI proof — 10:08:53 PM CT
Source133fe3d synchronized on all three checkouts. Restarted only web87870→89854
with `CARAVAN_WEB_KEEP_WORKERS=1` on both old and new web processes; Qwen worker
**89648 survived unchanged**, ready/singleEXO1, allAuto, queuedKV4 trial active.
Served HTML contains the tested/negative-inclusive chip, settings API contains
49.77tok/s slower-helper result. EXO2 has no worker, download or benchmark process.
[`split-final-ui-proof.json`](../bench/results/day17/split-final-ui-proof.json)
retains exact API evidence. Evidence-only commit follows; no further reload.

## GGUF split vs one Mini from the web UI — Nov 6, 11:14–11:33 PM CT

**Live numbers** (Qwen3-30B-A3B-Q4_K_S.gguf, 17.46 GB, EXO1+EXO2, llama.cpp
b10819, 3 prompts × 3 runs, max_tokens 256, temp 0.6; raw rows in
`bench/results/day17/gguf-split.jsonl`, script `bench/gguf_split_bench.py`):

| CT | commit | placement | load s | Write tok/s median (min–max) | Read tok/s median | first token s median |
|---|---|---|---|---|---|---|
| 23:28 | 2dcca97 | split EXO1+EXO2 (first, cold) | 18.6 | 34.52 (34.20–35.08) | 96.06 | 0.255 |
| 23:31 | 8007789 | split EXO1+EXO2 (warm) | 18.6 | 34.72 (34.13–35.09) | 105.51 | 0.256 |
| 23:32 | 8007789 | one Mini EXO1 | 13.3 | 42.86 (41.61–43.66) | 111.99 | 0.241 |

Split is ~19% slower than one Mini for a model that fits on one — the split is
for models that don't fit (that's why one Mini is the default here). Manual
check before wiring: 33.2 tok/s write through the SSH tunnel.

**Failed runs (kept for the record).**
- 23:14 CT, 8a29227: bench saw the old MLX "ready" before the switch began
  (bench race, fixed); the load was then cut off by a web-server restart from
  parallel work. 9 chats failed (409 / connection closed). Not a measurement.
- 23:16 and 23:18 CT, d326874: `llama-server` aborted
  `ggml-rpc.cpp:547: Failed to connect to 169.254.103.191:50052` (rc −6). The
  peer listener never saw the connection; the same command run from an SSH
  shell connected. Same symptom llama.cpp's own `transport.cpp` comment notes
  for launchd-supervised processes (macOS local-network restrictions). A direct
  rpc-server with no gate failed the same way, so it was not the allowlist gate.
  Fixed by tunnelling over SSH to loopback (2dcca97).

Details of the mechanism: [WEB.md](WEB.md#gguf-split-from-the-web-ui-day-17-nov-6-2026). Security: [SECURITY.md](SECURITY.md).


## GGUF robustness and CLI (Nov 6, 23:40–23:55 CT; Nov 7 download)
Raw rows: `bench/results/day17/gguf-robustness.jsonl` (26 lines, script
`bench/gguf_robustness.py`), commit afcf070 unless noted.

- 5 cycles split → MLX → one Mini → split: **20/20 steps OK**. Typical: split
  load ~24.6 s, Write ~34–36 tok/s; MLX Qwen3 30B 4-bit ~22.9 s, ~51 tok/s;
  GGUF one Mini 12.5 s, ~43–44 tok/s.
- Stop mid-load at `starting_packer` and `starting_lead`: idle "Load stopped.",
  0 processes on both Minis.
- Kill EXO2 rpc-server mid-chat: idle "Lost EXO2 during the split. Load it
  again.", 0 processes; first run the chat connection dropped, rerun at
  2e1f6b5 (23:55) chat got a plain HTTP 502.
- Re-attach after web restart: adopted llama-server pid 16411 + 1 tunnel,
  chat 34.47 tok/s. With the tunnel killed before the restart: tunnel reopened
  but llama-server had already aborted; watchdog → idle, plain error, no orphans.
- CLI split (`agent/gguf_split_cli.py`, SSH tunnels): ready 13.0 s, Write
  34.30 / 34.49 / 34.66 tok/s, split 20.0:16.1; Stop → 0 processes.
- Picker GGUF download (b2b2c26): 807.7 MB in 49 s (~13 MB/s). Stop/Resume
  works but Resume restarts from 0 % (74 s). File deleted after.
