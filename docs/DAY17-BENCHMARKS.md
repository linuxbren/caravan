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

Pending live EXO2 tests. No fabricated before/after values.

## Local validation

2026-11-06 CT: `python3 -m unittest discover -s tests -p test_day17_mtp_verify.py -v`
passes 7 tests (rejection positions k=1..8, all accept, early EOS, invalid plans,
missing/mismatched heads). `python3 -m pytest ...` failed before test execution:
box system Python has no pytest. Python compile and browser-JS syntax pass.
