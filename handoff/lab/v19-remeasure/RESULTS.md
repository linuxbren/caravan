# v19 remeasure — Nov 4, 2026 (00:04–00:33 CST)

EXO1 lead / single Mini, EXO2 packer (Thunderbolt 169.254.103.191:5560), test port 8194 (+ proxy 8190 inside the v0/v1/v2 harnesses), Low Power Mode 0 on both (checked by every driver). Only our own test workers were stopped. Raw: `v19/` (EXO1 `~/.caravan/bench-2026-11-04/v19/`), packer logs `exo2/`, drivers `*.sh`, orchestration logs `*.log`.

## 1. Day 12 split (e652708), plain (no guesser, one chat), `bench/v3/split_client.py bench`, medians of 2
| model | K | write tok/s | read 512 | read 4k | quality | raw |
|---|---|---|---|---|---|---|
| Qwen3 30B-A3B 4-bit | 24 | 45.6 | 462.4 | 428.4 | 3/3 | v19/split-qwen3-bench-off |
| Gemma 4 26B-A4B 4-bit | 15 | 35.8 | 425.9 | 395.6 | 3/3 | v19/split-gemma-bench-off |
| GPT-OSS 20B MXFP4-Q8 | 13 | 31.9 | 450.8 | 441.4 | 3/3 | v19/split-gptoss-bench-off |

Gemma 35.8 is below Day 12 idea1's 37.9 and GPT-OSS 31.9 below Day 5's 34.1 (K=12). Different bench path (split_client vs idea1 `_run`), and GPT-OSS ran at K=13. Not re-investigated.

## 2. Llama 3.1 8B Instruct, one Mini, writing tg128 / reading pp512 (median of 3, through the proxy, same harness as the original v1/v2 numbers)
| version | engine | write | read 512 | raw |
|---|---|---|---|---|
| v0 (45ed2c2 worktree + old llama.cpp build, q8_0) | llama.cpp, Q4_K_M GGUF (downloaded) | 21.2 | 222.1 | v19/v0/v0-llama-write, v0-llama-write.out |
| v1 (caravan-improvements c846e65) | mlx_lm.server, MLX 4-bit | 23.1 | 224.4 | v19/single/v1-llama-write |
| v2 (caravan-v2 7835efd) | Caravan MLX worker | 23.6 | 204.5 | v19/single/v2-llama-write |
| v2.1 (caravan-v2.1 24adc11) | Caravan MLX worker | 23.3 | 204.5 | v19/single/v2.1-llama-write |

First attempt of the three MLX runs failed (HTTP 502: the proxy only routes model ids starting `mlx-community/` to MLX; I had passed a path). Fixed by a symlink `~/.caravan/models/mlx/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit` → existing `~/.caravan/mlx-models/...`; failed dirs kept as `*-failed-502`.

## 3. First-word race: new chat sharing a ~4k-token system prompt (`day12_prefix_bench.py`, N=2048 → ~3,984 tokens), wall seconds for an 8-token reply
| version | setup | Qwen3 cold store | Qwen3 new chat | Llama cold store | Llama new chat |
|---|---|---|---|---|---|
| v0 | bare llama-server (old build), 1 slot, one Mini | 11.26 | 0.50 / 0.38 | 19.87 | 0.43 / 0.43 |
| v1 | bare mlx_lm.server, one Mini | 16.17* | 0.38 / 0.38 | 19.14* | 0.33 / 0.33 |
| v2.1 | Caravan MLX worker, per-chat caches, one Mini | 9.98 | 10.08 / 10.09 | 17.98 | 18.80 / 18.84 |
| v3 Day 12 split, shared-prefix off | today | 9.53 | 9.54 / 9.53 | — | — |
| v3 Day 12 split, shared-prefix on | today | 9.56 | 5.24 / 5.24 (ttft 5.05) | Nov 3: 17.57 ttft | Nov 3: 8.90 ttft |

\* first request after load includes warm-up.
**Caveat (important):** v0/v1 were run against the bare servers, not through the Caravan proxy. A bare server keeps one shared cache with no per-chat separation, so a new chat whose start matches the last one reuses almost all of it (~0.4 s). Caravan v2+ keeps each chat separate (needed for several users / restart resume), so v2.1 re-reads everything; Day 12's shared-prefix reuses only whole 2048-token blocks, hence 5 s not 0.4 s. The v0/v1 rows show what reuse could reach, not a like-for-like Caravan race. The miss-control (different preamble) stayed cold everywhere.

Incident: the first v1 prefix runs sent the model id instead of the local path, so mlx_lm.server began fetching from Hugging Face. Killed after ~10 min; left behind (not deleted) a partial ~4.3 GB in EXO1 `~/.cache/huggingface/hub/models--mlx-community--Qwen3-30B-A3B-4bit` and ~9 MB for Llama. Those runs were set aside as `*-aborted-hfdownload` and redone with the path.

## Downloaded
- `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` → `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`, 4,920,739,232 bytes (4.9 GB), EXO1 `~/.caravan/models/`.
- Unintended partial HF cache above.

## Other changes on EXO1 (all additive)
- Worktree `~/.caravan/bench-2026-11-04/v19/caravan-v0` at 45ed2c2 (detached) from `~/dev/caravan`.
- Symlink `~/.caravan/models/mlx/mlx-community--Meta-Llama-3.1-8B-Instruct-4bit`.
