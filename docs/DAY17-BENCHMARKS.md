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
  these options. No reload is permitted, so on/off PL and split two-chat
  comparisons may remain unavailable; ordinary single-Mini concurrent requests
  are not evidence of split overlap.
- Split N≥2 block verification already existed but had cache-accounting errors:
  all-accepted blocks omitted the last draft input, rejection over-trimmed draft
  KV by one, and EOS returned before rewind. Corrected accounting is pure unit
  tested; live split benchmark intentionally not run without approval.

## Run log

See the interrupted EXO2 run below. No completed on/off claim; all failures retained.

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
  Adaptive prompt lookup explicitly pins one split chat and rejects Two chats=2;
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
Both Minis had Low Power Mode off; own downloads had completed and picker
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

The manager currently calls unscoped `pkill -f mlx_worker.py` in `_kill_packer`
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
