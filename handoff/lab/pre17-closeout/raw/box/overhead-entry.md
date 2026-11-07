# Caravan log draft — per-pass overhead + compile / overlap prototypes (do not commit yet)

**Date:** Sat Oct 31, 2026 ~9:05–9:12 PM America/Chicago  
**Tip:** both Minis at `bb81010` (docs: idea 5 uneven layer split). Trees restored clean after this work.  
**Ports:** test only 8194 / 5560. No exo / Hermes / Talaria touched. LPM checked off before runs.  
**Artifacts:** `~/.caravan/bench-2026-10-31/overhead/` on EXO1 (also EXO2 gemma json); copies under `/workspace/caravan-notes/overhead-2026-10-31/` and attempt notes at `/workspace/caravan-notes/{compile,overlap}-attempt.md`.

## Method
One-Mini `overhead_bench.py`: even cut, 32-token prefill, warmup 4, N=20 decode steps. Timed packer half, lead half, full stack, empty (embed+1 only). Medians reported.

Overlap probe: live packer on EXO2 `:5560`, in-process lead Stage + FrontClient on EXO1, N=64, Gemma 4 4-bit even cut. Timed tolist / rpc_wait / packer_compute / net / lead_layers / total.

Compile: ephemeral smokes only — no working wrap.

## Overhead table (median ms / decode step)

| Host | Model | Packer | Lead | Full | Empty (fixed) | Sum halves − full | Implied packer ms/layer |
|------|-------|-------:|-----:|-----:|--------------:|------------------:|------------------------:|
| EXO1 | Gemma 4 26B A4B 4-bit | 10.753 | 14.474 | 25.172 | 1.015 | 0.055 | 0.696 |
| EXO1 | GPT-OSS 20B MXFP4-Q8 | 11.343 | 16.940 | 28.118 | 1.261 | 0.165 | 0.917 |
| EXO1 | Qwen3 30B-A3B 4-bit | 9.892 | 11.333 | 20.938 | 0.672 | 0.287 | 0.401 |
| EXO2 | Gemma 4 26B A4B 4-bit | 11.029 | 15.054 | 25.498 | 1.031 | 0.585 | 0.714 |

Reading: fixed cost on one Mini is ~0.7–1.3 ms (embed + first token path), not tens of ms. Halves sum ≈ full (±0.6 ms). The earlier “each half ≈ full” feeling in the *split* path is RPC / serialize / path tax across machines, not a large GPU fixed cost on one Mini.

## Prototype A — `mx.compile` each half
**Baseline writing (even cut, prior):** Gemma 27.6 / GPT-OSS 26.8 / Qwen3 30.0 tok/s.  
**Result:** could not enable. No writing number, quality N/A.  
**Breakage:** `Slice cannot infer output shapes`; `compile` with uncaptured inputs (weights / KV caches). Would need a full stage rewrite to pass every array as explicit compile inputs with fixed decode shapes. mlx_lm only compiles small helpers, not the full cache decode.

## Prototype B — overlap lead work with packer (`async_eval` / pipeline)
**Overlap probe medians (Gemma, ms):** tolist 0.001 · rpc_wait 17.208 · packer 16.305 · net 0.900 · lead 20.157 · total 37.362 (~26.8 tok/s, matches even-cut ~27.6 within probe vs full-bench noise).  
**Result:** no speedup path for single-chat writing. No patched re-bench. Quality N/A (probe only).  
**Why:** lead needs packer H for the *same* token; packer needs the previous sample. `SplitModel.tolist()` forces sync before RPC; lead is idle on recv for the whole packer window. mlx_lm’s existing `async_eval` of the next sample does not survive that sync + blocking RPC.

Real overlap targets remain idea 1 (multi-chat) and idea 3 (guess-ahead).

## Cleanup
- All test `mlx_worker` stopped; 8194 and 5560 free on both Minis.
- EXO1 `~/dev/caravan-v3` and EXO2 `~/cv3` clean at `bb81010` (untracked `bench/overhead/` removed; scripts live only under the bench output / workspace notes).
