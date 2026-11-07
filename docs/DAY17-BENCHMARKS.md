# Day 17 performance experiments — 2026-11-06 (CT)

Every run, including failures and negative results, is retained below or in
`bench/results/day17/`. Each row includes model, placement, code commit, exact
prompt/settings and CT timestamp. No vendor figure is a Caravan measurement.

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
