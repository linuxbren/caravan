# Roadmap

What's built, what's next and in what order, and what's still limited.
Numbers are from [BENCHMARKS.md](BENCHMARKS.md) (one Mac mini M4 24 GB
unless noted). "4k" and "16k" are chat lengths in tokens.

*Last updated 2026-10-31 (v3, branch `caravan-v3-mlx-split`, in progress).*

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

1. ~~**Publish the rebased llama.cpp branch.**~~ **Done (2026-10-31).**
   The fork moved to `linuxbren/llama.cpp`. There, `caravan-patches` is
   the rebased branch (upstream `5047748f` + the RPC patch) that the v1+
   numbers depend on, and `caravan-patches-v0` keeps the old base used
   for v0.
2. **Two-Mac MLX split.** *In progress (v3, 2026-10-31).* Run one MLX
   model across both Macs, as llama.cpp RPC does for GGUF, so models and
   long chats that don't fit on one 24 GB Mac (Qwen3 at 16k) can run on
   MLX. Design: [MLX-SPLIT.md](MLX-SPLIT.md).
   - [x] Feasibility: `mx.distributed` ring fails on ≥2 MB messages over
     Thunderbolt; jaccl needs Thunderbolt 5; mlx-lm pipeline sharding
     covers only Qwen3. Chosen: Caravan's own layer pipeline over one TCP
     connection.
   - [x] Head/front worker pair (`--split-role head|front`), Qwen3, Gemma 4
     and GPT-OSS.
   - [x] Per-stage session caches with save/restore on each Mac (both
     halves or neither).
   - [x] `mlx.split` config and front-command builder; unit tests.
   - [ ] Side-by-side numbers vs v2.1 on one Mac, and the 8-bit "bigger
     brothers" split across both.
3. **Split download (MLX).** Each Mac downloads only its own layers
   straight from Hugging Face; nothing relayed through the head. Read
   `model.safetensors.index.json`, map each node's layer range to its
   shard files, fetch them with `snapshot_download(allow_patterns=...)`
   plus config and tokenizer files. Edge cases: shards that straddle the
   cut (both Macs fetch them), embeddings and `lm_head`, tied embeddings
   (the head needs the embedding shard too), vision towers (skipped for
   text-only), and re-planning when more tails join (a new cut means new
   shards, and files no longer needed should be reported, not deleted).
   *Prototype in v3: `agent/mlx_split_fetch.py`.*
4. **Split download (GGUF), stage 1: rpc-server's local tensor cache.**
   With `ggml-rpc-server -c/--cache` the tail keeps the tensors it
   receives on disk, keyed by hash, so it only receives its weights over
   the wire the first time. *Checked 2026-10-31: our build has `-c,
   --cache` and the tail plist already uses it.* What's left: the head
   still needs the full GGUF on its own disk and reads all of it.
5. **Split download (GGUF), stage 2: tail loads its own tensors.** A fork
   patch so the tail loads its assigned tensors from its own disk instead
   of the head pushing them. Each tail fetches only its tensors' byte
   ranges (HTTP Range requests using the tensor offsets in the GGUF
   header), or uses `gguf-split` shards. Then the head no longer needs the
   tail's part on disk either.
6. **Per-model profiles.** Today Qwen3 needs hand-tuned worker settings
   (sessions in memory, cache budget, chunk size, cache quantization, when
   to save). The plan:
   - Compute a starting profile from the model's size and config against
     the GPU limit.
   - Check it with a short probe on first load.
   - Refine it from the peak memory and speeds the worker already reports.
   - Ship starter profiles for Qwen3, Gemma 4 and GPT-OSS.
7. **Gemma 4 short-prompt cost.** Short prompts read about 8% slower with
   the worker than with plain `mlx_lm.server` (397 vs 430 tok/s at 512
   tokens). The likely cause is the per-reply snapshot of the
   sliding-window layers; make it cheaper or skip it when it isn't needed.
8. **Proxy overhead.** 27–96 ms per MLX request, depending on the model.
   It's mostly cheap already, against v1 behind the same proxy. What's
   left is the one-off ~0.15 s on the first short request after a big
   chat.
9. **Memory headroom.** Qwen3 leaves 16–17% free, and swap reaches about
   1.45 GB.
   - Size the MLX cache from the real GPU limit.
   - Adapt it to free memory.
   - Warn before a request would run out of memory instead of failing.
10. **Cold-disk restore.** Measure restore with the file out of the disk
    cache. Then consider preloading recently used sessions at startup.
11. **Re-measure the two-Mac split** with the v1+ settings (flash
    attention over RPC, automatic KV, larger `ubatch`).
12. **Packaging.** Templated launchd plists (no machine-specific paths), an
    install script, and the agent running the proxy itself.

## Deferred / parked

Things we chose not to do now, so they don't get lost. Each has why it's
parked and when to pick it up again. Items that are already on the "Next"
list above point to it.

| Item | Why parked | Revisit when |
|---|---|---|
| Gemma 4 ~8% short-prompt checkpoint cost (Next #7) | Small, only on short prompts; v3 split work took priority. | After v3 lands; before Gemma 4 becomes the default MLX model. |
| Qwen3 ~0.15 s drop-previous-chat cost (Next #8) | One-off per big chat, hard to see in use. | With the proxy overhead pass. |
| MLX worker 6–9 s startup (Known limits) | Only paid on (re)start; the split adds the front's ~2–4 s in parallel. | When the agent restarts workers on model switch (packaging). |
| 8-bit MLX chat memory (`--kv-bits 8`, off) | Slower and still didn't fit Qwen3 at 16k on one Mac; untested with the split. | If a split model runs short of memory at long chats. |
| Per-model profiles (Next #6) | Needs the v3 memory numbers first (they change what fits). | Right after v3. |
| Proxy overhead trims (Next #8) | 27–96 ms per request, already small next to model time. | With the next proxy release. |
| Memory headroom (Next #9) | The split halves per-Mac weights, which changes the problem. | Re-check with v3 numbers; then size caches from the real GPU limit. |
| Cold-disk restore measurement and preload (Next #10) | Needs a reliable way to drop files from the disk cache without touching user data. | After v3; before advertising restart resume times. |
| Suite 2: two-Mini runs of Qwen3 30B 8-bit and the Qwen3.6 35B GGUF | Qwen3 30B 8-bit moved into v3 (MLX split); the Qwen3.6 35B GGUF two-Mini run is still parked. | After v3, with Next #11 (re-measure the llama.cpp split). |
| Broken `gpt-oss-20b.gguf` symlink in `~/.caravan/models` | Not ours to change during the sprint; GPT-OSS GGUF runs use the Ollama blob. | Next maintenance pass; fix by hand, not by a script. |
| Saved-chat cap deletes by default (Known limits) + a dry run on the second Mini's backlog (~165 GB) | Deleting a user's saved chats needs their sign-off; v3 runs with `CARAVAN_SLOT_CLEANUP=off`. | Before the next proxy restart on that Mini: run `--dry-run`, review, then decide `archive` vs `delete`. |
| Restore exo and Hermes on both Minis | Paused for the Caravan sprint so they don't compete for memory. | When the Caravan sprint is done. |
| Scrub personal paths (launchd plists, docs) | Cosmetic for the public repo; plists are hand-managed. | With packaging (Next #12). |
| C++ binary hardcodes the model (Known limits) | Experiment only; the Python agent is the supported path. | If the single-binary route is picked up again. |
| `mx.distributed` ring over Thunderbolt (fails on ≥2 MB messages) | Our own TCP pipeline works today. | With a newer mlx release; would allow mlx-lm/exo-style sharding. |
| jaccl / RDMA over Thunderbolt | Needs Thunderbolt 5 (M4 Pro/Max); our Minis are Thunderbolt 4. | If a Thunderbolt 5 Mac joins. |
| GPT-OSS 120B split across two Minis | 63.4 GB of weights vs 48 GB total memory: doesn't fit. | With a third Mac (or more memory). |
| Split link is unauthenticated | Thunderbolt-only cable between two trusted Macs. | Before the split runs over LAN/Tailscale. |
| No overlap of the two halves when writing (serial pipeline) | Simplicity first; it's the main reason writing is slower split. | After v3: overlap the next token's front pass with the head, or compile the stage graphs. |
| `--kv-bits` with the split | Untested. | With the 8-bit chat memory item. |
| More than two stages (one head, several fronts) | Two Macs today. | When a third Mac joins; needs re-planning of the cut and of split downloads. |

## Known limits

- **Cleanup defaults to `delete`.** At proxy startup, saves older than 30
  days, and the least recently used saves over 200 files / 50 GB, are
  deleted. Run `python3 -m proxy.slot_cleanup --dry-run` first, or set
  `CARAVAN_SLOT_CLEANUP=archive`.
- **Qwen3 30B at 16k doesn't fit on MLX** on one 24 GB Mac (16.4 GB weights
  + ~3.2 GB cache), even with `--kv-bits 8`. Use the GGUF for long Qwen
  chats, or the v3 MLX split across both Macs.
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
