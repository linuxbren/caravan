# Improvements bench (Caravan v0 vs v1)

These scripts produced the 2026-10-30 numbers in `docs/LOG.md`. They run on one Mac (the head) and use **test ports only**: llama-server on 8180, the proxy on 8190 and mlx_lm.server on 8192. Production ports 8080/8090 and exo's 52415 are never touched. Each script starts its own server and proxy, measures everything **through the proxy**, and stops what it started. Results go to `~/.caravan/bench-2026-10-30/improvements/<tag>/`.

- `imp_bench.py <tag> <model.gguf> <max_tokens> <ubatch> <n_slots> <ctx_per_slot> [phases]`: the GGUF path. Phases:
  - `main`: pp512, pp4096 and tg128, median of 3.
  - `quality`: short and long smoke prompts.
  - `d16k`: a 16k-token prefix plus about 550 new tokens.
  - `resume`: a 3-turn chat with about 16k tokens. The server and proxy restart before turn 3.
  - `resume_raw`: a 16k prefix. Restart, then send the same prefix plus about 560 new tokens.

  Settings, all through environment variables:
  - `CARAVAN_DIR`: the Caravan checkout whose supervisor and proxy are used.
  - `LLAMA_BIN`: the directory with `llama-server`.
  - `KV`: `q8_0`, `auto` or `f16`.
  - `SWA_FULL=1`: adds `--swa-full`.
- `mlx_bench.py <tag> <mlx model id> <max_tokens>`: the MLX path (step a). It uses `agent/mlx_backend.py` to build the mlx_lm.server command from the local model copy, then runs main, quality and a 4k-token 3-turn resume.
- `suite_imp.sh [all|resume|speed|mlx|extra|next]`: the exact runs used. Set `GPT_OSS_GGUF` to the real GPT-OSS GGUF file.
- `summ.py`: prints a summary of every `results.json`.
- `common.py`: prompts, filler text, scoring and the memory sampler (shared with the earlier runtime-compare bench).

**Comparison recipe.**
- v0: `CARAVAN_DIR=<checkout of 45ed2c2>`, `LLAMA_BIN=<build of caravan-patches-v0>`, `KV=q8_0`.
- v1: `CARAVAN_DIR=<improvements branch>`, `LLAMA_BIN=<build of caravan-patches>`, `KV=auto`.
- Attribution run, to separate the rebase from the cache type: v1 with `KV=q8_0`.
