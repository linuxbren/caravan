# Roadmap

What's built, what's next and in what order, and what's still limited.
Numbers are from [BENCHMARKS.md](BENCHMARKS.md) (one Mac mini M4 24 GB
unless noted). "4k" and "16k" are chat lengths in tokens.

*Last updated 2026-10-31 (v2.1).*

## Done

### Before v0: the split, the proxy, the agent (Sep 2026)

1. **Prove the split.** One 16 GB-weight GGUF model ran across two Macs
   with llama.cpp RPC (Metal on both).
2. **Make it usable day to day.**
   - The proxy: a session keeps its slot, requests run one at a time,
     requests are cancelled when the client disconnects, and slots are
     saved to disk.
   - launchd supervision.
   - The Thunderbolt cable: the tail's cold load went from 7–11 min to
     29–39 s, and writing from ~4 to 6.1 tok/s.
   - The shard cache, which turned out to be native (`rpc-server --cache`).
3. **The self-organizing agent.**
   - mDNS and Tailscale discovery, head and tail roles.
   - Automatic Thunderbolt > Tailscale > LAN path choice.
   - Supervision.
   - The root cause of the launchd networking failures: the Local
     Network permission.
4. **Unified C++ binary (experiment).** Head and tail in one process with
   mDNS discovery, proven end to end once.

### v0: baseline (`45ed2c2`, Oct 30)

- Configurable target model.
- Saved-slot cleanup after 30 days.
- Proxy performance work: LRU slots, fewer saves, prefix fingerprints for
  raw prompts, smoother streaming.
- Explicit llama-server flags.
- Docs for the public repo.

### v1: rebased llama.cpp, MLX through the proxy, automatic KV (`32b9756`, `737fea2`, `c846e65`)

- **Rebased llama.cpp** (upstream `5047748f`) keeps checkpoints in slot
  files. A 16k chat after a restart: GPT-OSS 46.3 → **0.65 s**, Gemma 4
  56.1 → **0.93 s**.
- **Faster reading** (pp4096): GPT-OSS 403 → 454, Gemma 4 355 → 380,
  Qwen3 338 → 356 tok/s.
- **Automatic KV type**: f16 when it fits (Gemma 4, GPT-OSS), q8_0
  otherwise (Qwen3).
- **MLX step a**: MLX ids routed to `mlx_lm.server`. It worked, but Gemma 4
  and GPT-OSS reused nothing between messages.

### v2: the Caravan MLX worker (`f57af3b`, `6d4bdb0`, `fac73b8`, `f73eafb`, `7835efd`)

- **Per-session MLX caches** with checkpoint and rewind, saved to disk.
  Turn 2 of a 4k chat: Gemma 4 10.76 → **0.49 s**, GPT-OSS 9.16 →
  **0.50 s**. After a restart: 12.7–16.0 → **0.52–0.64 s**.
- **Clean GPT-OSS replies**: the answer goes in `content`, the reasoning
  in `reasoning_content`.
- **Per-Mac cap** on saved chats: 200 files / 50 GB, llama.cpp and MLX
  together, least recently used first, never active sessions.
- **No regression** on the llama.cpp path.

### v2.1: steadier MLX (`b9ebeb7`)

- Wired limit set once at startup and held (`--wired-limit`, default
  `startup`).
- Optional deferred first save (`mlx_save_min_turns`).
- **Benchmarking method changed**: versions are compared side by side in
  one session. With that method, v1, v2 and v2.1 read 4k at 396, 393 and
  396 tok/s.

## Next, in order

1. **Publish the rebased llama.cpp branch.** The v1+ numbers depend on
   `caravan-patches` rebased onto upstream `5047748f`. The fork's
   published `caravan-patches` branch is still the older base, so a fresh
   clone today doesn't get the sliding-window restore fix.
2. **Two-Mac MLX split.** Run one MLX model across both Macs, as llama.cpp
   RPC does for GGUF, so models and long chats that don't fit on one 24 GB
   Mac (Qwen3 at 16k) can run on MLX.
3. **Per-model profiles.** Today Qwen3 needs hand-tuned worker settings
   (sessions in memory, cache budget, chunk size, cache quantization, when
   to save). The plan:
   - Compute a starting profile from the model's size and config against
     the GPU limit.
   - Check it with a short probe on first load.
   - Refine it from the peak memory and speeds the worker already reports.
   - Ship starter profiles for Qwen3, Gemma 4 and GPT-OSS.
4. **Gemma 4 short-prompt cost.** Short prompts read about 8% slower with
   the worker than with plain `mlx_lm.server` (397 vs 430 tok/s at 512
   tokens). The likely cause is the per-reply snapshot of the
   sliding-window layers; make it cheaper or skip it when it isn't needed.
5. **Proxy overhead.** 27–96 ms per MLX request, depending on the model.
   It's mostly cheap already, against v1 behind the same proxy. What's
   left is the one-off ~0.15 s on the first short request after a big
   chat.
6. **Memory headroom.** Qwen3 leaves 16–17% free, and swap reaches about
   1.45 GB.
   - Size the MLX cache from the real GPU limit.
   - Adapt it to free memory.
   - Warn before a request would run out of memory instead of failing.
7. **Cold-disk restore.** Measure restore with the file out of the disk
   cache. Then consider preloading recently used sessions at startup.
8. **Re-measure the two-Mac split** with the v1+ settings (flash
   attention over RPC, automatic KV, larger `ubatch`).
9. **Packaging.** Templated launchd plists (no machine-specific paths), an
   install script, and the agent running the proxy itself.

## Known limits

- **Cleanup defaults to `delete`.** At proxy startup, saves older than 30
  days, and the least recently used saves over 200 files / 50 GB, are
  deleted. Run `python3 -m proxy.slot_cleanup --dry-run` first, or set
  `CARAVAN_SLOT_CLEANUP=archive`.
- **Qwen3 30B at 16k doesn't fit on MLX** on a 24 GB Mac (16.4 GB weights
  + ~3.2 GB cache), even with `--kv-bits 8`. Use the GGUF for long Qwen
  chats.
- **The MLX worker takes 6–9 s to start** (vs 1.6 s for `mlx_lm.server`).
- **MLX tool calls** are returned as text, not as a `tool_calls` field.
- **Same first message = same session**, on both backends.
- **The Thunderbolt address can change.** macOS self-assigns 169.254.x.x
  addresses. The hand-managed plist's `--rpc` fallback is a literal one;
  the agent and `render_llama_plist.py --rpc auto` discover it instead.
- **The launchd plists contain absolute paths** for one user's home
  directory. Edit them for your machine. The proxy plist's
  `CARAVAN_PINNED_SLOT` is a leftover the proxy no longer reads.
- **Head selection is "whoever has the model"**: no election, and two Macs
  that both have it aren't handled. The agent doesn't run the proxy yet.
- **The C++ binary** hardcodes the model and lacks `--cache`, the health
  server, identity and crash supervision.
- **Only tested on two Apple Silicon Macs.** RDMA over Thunderbolt needs
  Thunderbolt 5, so the split runs over plain TCP.
- **RPC is unauthenticated.** Keep it on a private link.
- **Not released.** There are no packages, and there's no support beyond
  this repo.
