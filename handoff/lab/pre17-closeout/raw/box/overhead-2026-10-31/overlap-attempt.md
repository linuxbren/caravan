# Overlap-the-lead prototype attempt (Oct 31 2026, ~9:09 PM CDT)

## Goal
Let the lead prepare or `mx.async_eval` useful work while the packer runs the same token (pipelining sampling / next step).

## Measurement (Gemma 4 4-bit, even cut, live packer on :5560)
In-process lead Stage + `FrontClient` decode loop, N=64 after 32-token prefill.
Medians (ms/token):

| tolist | rpc_wait | packer compute | net | lead layers+sample | total |
|---:|---:|---:|---:|---:|---:|
| 0.001 | 17.208 | 16.305 | 0.900 | 20.157 | 37.362 |

Implied writing ≈ 1000/37.362 ≈ 26.8 tok/s (matches tonight even-cut ~27.6 within probe vs full bench noise).

Raw: `overlap-probe-gemma4.json`.

## Results — cannot speed up single-chat writing this way
No split re-bench with an overlap patch: the serial dependence blocks it.

Evidence:
1. **Same-token dependence:** `lead.run_layers` needs the packer hidden state for that token. Until `rpc_wait` returns, the lead has no H to eval.
2. **Next-token dependence:** the packer needs the concrete sampled token from the previous lead step. `SplitModel` does `inputs.reshape(-1).tolist()` before RPC, which forces any prior `mx.async_eval` (mlx_lm already does this for one-Mac) to finish first.
3. **Idle during wait:** for ~17 ms/token the lead is blocked on socket recv; packer compute is ~16.3 ms of that, net ~0.9 ms. There is no independent lead-layer work to schedule in that window for this chat.

`mx.async_eval` is already used inside `mlx_lm.generate` to overlap sample with the next forward on one Mac. Across the split that overlap collapses at `.tolist()` + blocking RPC.

## What would actually overlap
- Idea 1 (several chats): packer on chat B while lead finishes chat A.
- Idea 3 (guess ahead): draft tokens on the lead so one packer→lead pass checks several tokens.

## Patch
Probe script saved as `overlap_probe.py` beside this note. No persistent change to `mlx_split.py` / `mlx_worker.py`.
