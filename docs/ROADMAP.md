# Roadmap

What has been built so far, what comes next and in what order, and what is
still known to be broken or limited. All numbers come from
[LOG.md](LOG.md), measured on a 24 GB Mac mini M4 (mlx-lm 0.32.2 for MLX).
"4k" and "16k" are chat lengths in tokens. Reading and writing speeds are
tokens per second. "Wait" is the time to the first word of the reply.

*Last updated 2026-10-31 (v2.1).*

## Done, by version

Each version builds on the previous one. Branches are local and not merged
yet: `improvements-1-3` (v1), `caravan-v2-mlx-cache` (v2), and
`caravan-v2.1` (v2.1).

### v0: baseline (`45ed2c2`, 2026-10-30)

One GGUF model split across two Macs with llama.cpp RPC. A proxy keeps
each conversation in its own llama-server slot and saves it to disk. The
agent picks head or tail and the fastest link. Configurable target model,
stale slot-file cleanup, tuned proxy and llama-server flags, and docs for
the public repo. This is the reference point for the v1 numbers.

### v1: rebased llama.cpp, MLX step a, auto KV cache (`32b9756`, `737fea2`, `c846e65`)

In plain words: a newer llama.cpp that resumes long chats after a restart
almost instantly. MLX models can now be served through the same proxy. The
KV cache uses full precision (f16) when it fits, else 8-bit.

- **Rebased llama.cpp** (upstream `5047748f`, one Caravan patch kept). A
  16k chat after a restart: GPT-OSS waits 46.3 → **0.65 s**, Gemma 4
  56.1 → **0.93 s** (Qwen3 has no sliding window, so it barely changes:
  1.18 → 1.10 s).
- **Reading speed, v0 → v1** (pp4096): GPT-OSS 403.0 → 453.6, Gemma 4
  354.9 → 379.7, Qwen3 338.0 → 356.4. **Writing** (tg128): 35.9 → 37.1,
  34.4 → 36.7, 41.4 → 42.5. Most of the gain comes from the rebase. f16
  mostly helps writing, and costs about 1.7 GB on Gemma.
- **Auto KV cache**: f16 for Gemma 4 and GPT-OSS, q8_0 for Qwen3 (f16
  would need 19,097 MiB against an 18,186 MiB GPU limit).
- **MLX step a**: models with an MLX id are sent to `mlx_lm.server` on
  the same Mac. It works, but Gemma 4 and GPT-OSS reuse nothing between
  messages: turn 2 of a 4k chat takes 10.8 s and 9.2 s, and after a restart
  16.0 s and 12.7 s.

### v2: MLX chats kept and saved per session (`f57af3b`, `6d4bdb0`, `fac73b8`, `f73eafb`, `7835efd`)

In plain words: Caravan's own MLX worker keeps each conversation's cache
between messages and saves it to disk, so MLX now works like the llama.cpp
side. GPT-OSS replies no longer contain its internal markup. Saved chats
are held to a per-Mac cap.

- **Turn 2 of a 4k chat, v1 → v2:** Gemma 4 10.76 → **0.49 s**, GPT-OSS
  9.16 → **0.50 s** (Qwen3 0.44 → 0.56 s; it already reused its cache).
  At 16k: Gemma 4 55.1 → 0.72 s, GPT-OSS 37.3 → 0.59 s.
- **First message after a restart (4k):** Qwen3 16.0 → 0.59 s, Gemma 4
  16.0 → 0.64 s, GPT-OSS 12.7 → 0.52 s. At 16k: Gemma 4 60.3 → 0.84 s,
  GPT-OSS 40.7 → 0.59 s. Loading a save takes 0.01–0.13 s (warm disk).
- **GPT-OSS reasoning cleanup:** `content` is only the answer, and the
  thinking moves to `reasoning_content` (and `reasoning`), the way
  llama-server returns it. Reasoning that a client sends back is ignored,
  so the history still matches the cache.
- **Writing speed** improved slightly (tg128: 47.0 → 49.1, 39.8 → 42.2,
  35.3 → 37.4). Peak memory is the same or a little lower.
- **llama.cpp path:** no regression (e.g. 16k after a restart 0.652 →
  0.65 s for GPT-OSS, reading within noise or better).
- **Saved-chat cap** (`7835efd`): after the 30-day age rule, llama.cpp
  and MLX saves together are held to 200 files / 50 GB. The least recently
  used go first, and an active session is never evicted.
- Cost: the worker takes 6–9 s to start (it loads and warms up up front)
  vs 1.6 s for mlx_lm.server.

### v2.1: wired limit held from startup, optional deferred save (`b9ebeb7`)

In plain words: the MLX worker now locks the model in GPU memory once at
startup, as mlx_lm.server does, instead of around every request. Saving
after a one-message request can be turned off.

- `--wired-limit startup|per-request|off` (default `startup`), and
  `CARAVAN_MLX_SAVE_MIN_TURNS` (default 1 = unchanged; 2 skips the save
  for one-message requests).
- **Qwen3 reading 4k, all versions side by side in one session**
  (6 runs each, median): v1 395.9, v2 393.4, **v2.1 395.6**. v2.1 is a
  little steadier: its slowest run was 390 vs 380 for v2. The 4k gap seen
  on separate days (v2 374–390 vs v1 396) was mostly drift between days.
- **Skipping the first save:** no measurable effect (396.4). A 4k save
  takes about 0.10 s on a warm disk.
- Gemma 4 and GPT-OSS: same as v2 (4k 376 / 415). Restart resume still
  works (Qwen3 4k: 0.52 s after a restart, 31 of 4,377 tokens re-read).

## Next, in order

1. **Two-Mac MLX split.** Run one MLX model across both Minis, the way
   llama.cpp RPC already does for GGUF, so models and long chats that
   don't fit one 24 GB Mac (Qwen3 at 16k today) can run on MLX.
2. **Per-model profiles.** Each model needs its own settings: sessions
   kept in memory, cache memory budget, prompt chunk size, cache
   compression, and when to save. Today Qwen3 needs hand-tuned values.
   Plan:
   - compute a starting profile from the model's config and size (weights
     plus cache memory per token, against the GPU limit);
   - confirm it with a short probe on first load (read a 4k prompt,
     measure memory, keep about 15% free);
   - refine it from real use (peak memory and speeds the worker already
     logs);
   - ship starter profiles for the known models (Qwen3, Gemma 4,
     GPT-OSS).
3. **Gemma short-prompt checkpoint cost.** On Gemma 4, short prompts read
   about 8% slower than v1 (512 tokens: 396–397 vs 430 tok/s, same
   session). GPT-OSS and Qwen3 don't show it. The likely cause is the
   worker's snapshot of Gemma's sliding-window layers before each reply.
4. **Proxy overhead.** Measured at 30–100 ms per request between the
   client and the worker's own timing (GPT-OSS ~27 ms, Qwen3 ~65 ms,
   Gemma 4 70–95 ms). It covers the HTTP hop, the restore check and prompt
   preparation. Against v1 (also behind the proxy) Qwen3 short requests
   differ by only about 6 ms, so it's mostly cheap already. What's left:
   the one-off ~0.15 s on Qwen3's first short request after a big chat
   (likely dropping the previous chat from memory).
5. **Memory headroom.** Qwen3 leaves about 16–17% free and swap reaches
   about 1.45 GB.
   - Size the cache from the real GPU limit (`recommendedMaxWorkingSetSize`).
   - Grow or shrink the cache budget with free memory.
   - Use the two-Mac split for what doesn't fit.
   - Warn before a request runs out of memory instead of failing.
6. **Cold-disk restore.** All restore timings so far were on a warm disk,
   with the file already in macOS's file cache. Measure a real cold read
   (after `sudo purge` or a reboot), then consider preloading recent
   sessions' saves at startup.

## Known limits and open issues

- **Qwen3 at 16k on MLX runs out of memory** (16.4 GB weights + ~3.2 GB
  cache). This happens with mlx_lm.server too, and `--kv-bits 8` doesn't
  help. Use the GGUF on llama-server for long Qwen chats.
- **The MLX worker takes 6–9 s to start** (vs 1.6 s for mlx_lm.server),
  because it loads and warms up before the first message.
- **The cap defaults to delete mode.** Cleanup (`mode`, default `delete`)
  applies the 200-file / 50 GB cap as soon as the proxy starts. On a Mini
  with a backlog of saved chats, run
  `python3 -m proxy.slot_cleanup --dry-run --max-gb 50 --max-count 200`
  first, or set `CARAVAN_SLOT_CLEANUP=archive`.
- **Broken GPT-OSS GGUF symlink** on the reference Mini:
  `~/.caravan/models/gpt-oss-20b.gguf` points at a removed Ollama blob.
  The llama.cpp bench uses the HF blob instead (`GPT_OSS_GGUF` overrides).
  The symlink was left as is.
- The other limits in the README (Thunderbolt address changes, launchd
  paths, C++ binary) still apply.

## Benchmark method

- **Same three models every time:** Qwen3-30B-A3B, Gemma 4 26B-A4B and
  GPT-OSS-20B (MLX 4-bit / 4-bit / MXFP4-Q8, plus their GGUFs for
  llama.cpp). Same prompts: pp512, pp4096, tg128, a 4k and 16k multi-turn
  chat, a restart before turn 3, and a 3-question quality check.
- **Compare versions side by side in one session.** This is the lesson
  from v2.1: runs on different days drifted by up to ~20 tok/s at 4k,
  enough to look like a regression that wasn't there. `bench/v2.1/ab_bench.py`
  restarts every version fresh each round, rotates the order, and takes
  at least 6 runs per size for the model in question.
- Test ports only (llama 8180, proxy 8190, MLX 8192). exo stays paused,
  and nothing else heavy runs on the Mac.
- Record peak memory footprint, lowest free memory and swap, sampled every
  2 s. Read the footprint, not RSS (macOS counts the MLX worker's RSS lower).
- Measure restore on a warm disk and, separately, on a cold one.
