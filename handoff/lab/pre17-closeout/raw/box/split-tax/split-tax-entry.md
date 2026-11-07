# Caravan log draft — v3 split per-half tax + GPU keepalive fix (do not commit yet)

**Date:** Sat Oct 31, 2026 ~9:15–9:33 PM America/Chicago  
**Tip:** both Minis restored clean at `bb81010`. Test ports 8194 / 5560 only. LPM off (`lowpowermode 0`). No exo/Hermes/Talaria.  
**Artifacts:** `~/.caravan/bench-2026-10-31/split-tax/` on EXO1; copies under `/workspace/caravan-notes/split-tax/` (`keepalive.patch`, instrumented scripts, JSON/JSONL).

## Question
Even-cut split writing leaves ~5–6 ms/token on each half vs one-Mini half timings (Gemma packer ~16.3 vs 10.8; lead ~20.2 vs 14.5). Where does it go?

## Method
Instrumented `Stage.front_forward` / `array_bytes` / `array_from` / `serve_front` / lead decode (uncommitted). Compared live split (packer EXO2 `:5560`, lead in-process or worker `:8194`) to one-Mini half loops. Then forced a 0–37 ms sleep between local packer steps to mimic turn-taking.

## Breakdown (Gemma 4 26B A4B 4-bit, median ms)

### One-Mini local (tight loop, EXO1)
| piece | ms |
|-------|---:|
| packer eval | 10.221 |
| packer ser (np.asarray/tobytes after eval) | 0.025 |
| packer total | 10.691 |
| lead deser (bytes→mx + eval) | 0.024 |
| lead eval | 14.104 |
| sample `.item()` | 0.303 |
| lead total (from bytes) | 14.820 |
| lead zeros baseline | 14.594 |

Hidden-state payload = **5632 bytes** (bf16 `[1,1,2816]`). Ser/deser are **not** the tax.

### Live split before fix (`split-gemma4.json`, N=64)
| piece | ms |
|-------|---:|
| packer graph_build | **3.483** |
| packer eval | 12.093 |
| packer ser | 0.116 |
| packer `_s` / handle | 15.957 |
| net (rpc − packer_s) | ~0.89 |
| lead deser | 0.218 |
| lead graph_build | **3.380** |
| lead eval | 15.951 |
| sample | 0.348 |
| lead total after rpc | 19.983 |
| step total | 36.894 |

### Top contributors to the ~5–6 ms/half
1. **Idle cool-down / Metal ramp after turn-taking wait (~3.0–3.5 ms)** — shows up as inflated `graph_build_ms` (0.38 → ~3.4) after ~20 ms peer wait. Same code, same cache; a local `time.sleep(20)` between packer steps reproduces packer total **15.9 ms**.
2. **Slower `mx.eval` after the same idle (~1.5–2.0 ms)** — eval 10.2 → 12.1 (packer), 14.1 → 16.0 (lead).
3. **Cable / framing (~0.9 ms)** — real net beyond packer `_s`; encode/send each ~0.05 ms. Negligible vs (1)+(2).

Not the culprits: `tolist`, JSON token list, `TCP_NODELAY` (already on), host↔GPU copy of H, redundant eval in ser after `mx.eval`, bf16 width.

## Cheap fix: GPU keepalive during peer wait
Background thread runs `mx.eval` on a tiny float16 buffer while the socket blocks (lead: during `read_frame` after send; packer: during `read_frame` waiting for the next op). Stops before own layer work.

Local proof: `gap20` total 15.6 → **10.7** with GPU warm thread (matches tight loop). CPU-only warm thread made things worse.

Patch (uncommitted): `GpuKeepalive` in `mlx_split.py`; `FrontClient.enable_gpu_keepalive`; `serve_front` wraps recv; worker enables on lead client + packer `state.keepalive`. Diff: `keepalive.patch`.

## Writing vs even-cut baseline (keepalive on both sides)
`bench/v3/split_client.py` on test lead `:8194`, packer `169.254.104.38:5560`. Medians of 2× tg128. Quality 3/3.

| Model | Baseline write | Keepalive write (2 runs) | Median | Quality |
|-------|---------------:|-------------------------:|-------:|--------:|
| Gemma 4 26B A4B 4-bit | 27.6 | 38.6, 37.7 | **38.15** | 3/3 |
| GPT-OSS 20B MXFP4-Q8 | 26.8 | 34.5, 34.3 | **34.4** | 3/3 |
| Qwen3 30B-A3B 4-bit | 30.0 | 45.8, 45.8 | **45.8** | 3/3 |

Gemma microbench with packer keepalive already on: lead cold total 31.6 ms; lead+packer warm **26.1 ms** (~38 tok/s), matching the writing bench.

## Cleanup
Workers stopped; 8194/5560 free; both trees clean at `bb81010`.

## Recommendation
Land the GPU keepalive (small, localized, measured +38% / +28% / +53% writing on the three models, quality held). Ser/deser and `tolist` are not worth chasing for this gap. Keepalive should not run during own compute (start/stop around the blocking recv only). Optional follow-up: measure reading impact and power draw; confirm no interaction with multi-chat (idea 1).
