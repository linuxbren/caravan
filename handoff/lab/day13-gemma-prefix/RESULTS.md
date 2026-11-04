# Day 13 — Gemma shared-prefix on two-Mini split

**Date.** 2026-11-04 (America/Chicago).  
**Goal.** Fix Day 12's Gemma `shared-prefix-split-resync` (0% TTFT gain) so a new chat that shares a long system prompt reuses the lead+packer KV. Re-check Qwen3 and Llama with **fresh** off vs on. Quality must match with the cache off.

**Setup.** EXO1 lead + EXO2 packer over Thunderbolt `169.254.103.191:5560`. Test ports 8194 / 5560. Low Power Mode off. Models: Gemma 4 26B-A4B 4-bit, Qwen3-30B-A3B 4-bit, Llama 3.1 8B Instruct 4-bit. Flag: `--split-shared-prefix-cache`. Guess-ahead off (`--no-split-draft`). Bench scripts in `scripts/` (+ `fresh_one.sh` on EXO1). Raw JSON under `*-n2048-*/` and `*-fresh/`.

## Root cause (Day 12)

After cloning a session into the reserved shared-prefix key, the lead blindly trimmed every layer. Gemma uses RotatingKVCache / sliding-window on most layers; once wrapped those layers refuse a trim. The packer then saw a different `n` than the lead → `shared-prefix-split-resync` full re-prefill. Net: reuse 0, ~0% TTFT gain.

## Fix

- `agent/mlx_split.py`: packer op `trim_to` — shortens a named session to exactly `n`, or errors `not trimmable`.
- `agent/mlx_worker.py`: `_can_trim_session` / `_trim_session_to`; `_materialize_shared_prefix` re-prefills the exact prefix on **both** halves when trim is unsafe; store logs `via=trim|materialize`; hit path verifies packer reserved `n` before clone.
- Tests: `SharedPrefixTrimTest` (+3). **174 tests OK.**

## TTFT (new chat, ~4k shared system prompt) — all fresh Day 13

Mean of `new_session_0` / `new_session_1`. Off = flag off (always cold). On = flag on hit.

| Model | Off new TTFT (s) | On hit TTFT (s) | Δ | how / via |
|---|---:|---:|---:|---|
| Gemma 4 26B-A4B 4-bit | 11.764 | 1.554 | **−86.8%** (~7.6×) | `shared-prefix-hit-memory`, store `via=materialize`, reuse 4096 |
| Qwen3-30B-A3B 4-bit | 9.303 | 5.029 | **−45.9%** | hit-memory, `via=trim`, reuse 2048 |
| Llama 3.1 8B 4-bit | 17.473 | 8.898 | **−49.1%** | hit-memory, `via=trim`, reuse 2048 |

Sources: `gemma-n2048-{off,on}/prefix.json`; `qwen3-n2048-{off,on}-fresh/prefix.json`; `llama-n2048-{off,on}-fresh/prefix.json`.

Gemma cold_store **with** flag on is slower once (22.041 s) because materialize re-prefills the reserved prefix; later new chats pay ~1.55 s. Day 12 Gemma on the same shape was `split-resync` at ~11.79 s (~0%).

## Writing-speed sanity (short prompt, streamed tg≈128, draft off) — fresh

| Model | Flag off median tok/s | Flag on median tok/s |
|---|---:|---:|
| Qwen3 | 27.4 | 27.3 |
| Llama | 15.8 | 15.9 |

Off ≈ on (no regression from the fix). Absolute tok/s here is a quick short-prompt check, **not** the Day 12 scoreboard tg128 method — do not compare these absolutes to Day 12's 45.4 / 22.6. Raw: `*-fresh/write.json`.

## Quality (Gemma, seed=42, “Reply with exactly: PING”)

| Flag | warm content / how / ttft_s | new content / how / ttft_s |
|---|---|---|
| off | `PING` / cold / 6.241 | `PING` / cold / 6.218 |
| on  | `PING` / cold / 11.179 | `PING` / shared-prefix-hit-memory / 1.357 |

Outputs match.

## Software touch list

`agent/mlx_split.py`, `agent/mlx_worker.py`, `tests/test_mlx_split.py`, `tests/test_mlx_worker.py`. Docs: this file, `handoff/lab/experiments.md`, `docs/ROADMAP.md`. Flag still **off by default**.
