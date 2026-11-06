# Changelog


## Unreleased

- **Model picker N-node.** Nodes from `~/.caravan/config.toml` `[web.nodes.*]` (default still EXO1/EXO2). Fit/chips/download/Stop/Delete/disk iterate online/configured nodes; 1-node never suggests split; `MAX_SPLIT_STAGES=2` caps actual load with a “N-Mini split coming later” note. See MODEL_PICKER / CONFIGURATION.

- **Model picker (phases 1–2).** Models drawer (see [MODEL_PICKER.md](MODEL_PICKER.md)):
  HF/GGUF/Cloud catalog; capacity-based fit (not current free RAM) with plain
  reasons; live search; real HF sizes; category + **New** chips; max download
  size filter; parallel lead+packer shard download with byte progress; Stop/Delete
  kill fetches on both Minis; on-disk HF cache + guess-ahead drafts cleanup.
  Still open: conversion, GGUF-llama-server load, live Cloud.

- **Memory guard (lead).** Estimate KV vs reclaimable RAM before generate; trim
  oldest turns into `~/.caravan/memory` Markdown notes (EXO1 only) and BM25-recall
  snippets into a short system note. Topology shows reclaimable RAM; UI notes
  moved/recalled counts. Config: `memory_dir`, `memory_safety_gb`.

- **Topology / chat.** 500 ms node poll while visible; sticky stats; 20–100 °C
  temp bar; Heat/Theme colors; Mac mini variant A cards; ioreg GPU % (not
  macmon keepalive 100%); full chat history sent (not only the latest message).

What changed in each Caravan version, newest first. Numbers come from
[BENCHMARKS.md](BENCHMARKS.md); the day-by-day story is in
[LOG.md](LOG.md); what's next is in [ROADMAP.md](ROADMAP.md).

"4k" and "16k" are chat lengths in tokens (a token is about ¾ of a word).
"Reading" is how fast a prompt is taken in, "writing" is how fast the
reply comes out.

## Unreleased

### Fixed
- `bench/v3/speculate_bench.py`: skip write_tps when `(total_s - ttft_s) ≤ 0`
  (short quality replies no longer ZeroDivisionError).
- First-load / quality `answer_ok` scores only the final answer after
  stripping think/channel blocks (Gemma `<channel|>` closer). Thought-only
  output no longer passes. Gate probes use 256 tokens.

### Added
- ROADMAP #13(a) auto-tune: when `--split-packer-layers` /
  `--split-pipeline-chats` are omitted, pick K from Mini memories + layer
  sizes (packer hello `mem_total_gb`) and pipeline chats from free memory
  (cap 2, never swap). Explicit flags win. Startup logs `auto split:` /
  `auto pipeline:`. Mini-verified auto ≡ hand-tuned on Qwen3, Llama 3.1
  8B, Qwen2.5 14B (quality 3/3). See BENCHMARKS / METHODOLOGY.
- Llama 3.1 8B Mini-verified guess-ahead suite (keepalive / pipeline N=1–3 /
  nodraft vs auto-pair / first-load / shut-off / download prompt). Count
  **22.7 → 51.5**; `llama3` → `mini_verified` in `guessers.json`. See
  BENCHMARKS.
- Top open-LLM family → guesser map in `agent/guessers.json` (Llama 3.x,
  Qwen3/2.5, Gemma 4/3/2, Distill-Qwen, SmolLM; skips for GPT-OSS, Mistral,
  Phi-4, native DeepSeek). `verification`: `mini_verified` | `vocab_checked`.
  Live EXO1 download-prompt check (yes/no remembered; caches restored).
- Idea 3 guess-ahead auto-pair: `agent/guessers.json`, vocab match/remap,
  ask-once download (lead only), first-load quality/speed gate (cached),
  mid-chat shut-off below break-even. Flags `--no-split-draft`,
  `--split-draft-auto-download`, `--split-draft-skip-first-load`.
  Docs: CONFIGURATION, MLX-SPLIT, ROADMAP idea 3, METHODOLOGY.md.
- Idea 3 prompt-lookup (`--split-prompt-lookup`) + draft prefill fix;
  Gemma-3-270m draft path; GPT-OSS rotating-KV speculate guard.
- Idea 3 guess-ahead prototype: `--split-draft-model`, `--split-speculate-k`
  (off by default). Packer `trim` for speculative reject. See BENCHMARKS.

## v3.4 (tag `v3.4`, Nov 1 2026)

Branch `caravan-v3-mlx-split`. Day 6 lab video refreshed to the techie-friend
cut (LAB-2026-11-01-03 / v12); v10–v11 kept and marked superseded. Post-style
audience guidance in `handoff/README.md` §5/§6. Not merged to `main`.

## v3.3 (tag `v3.3`, `f31d15a`, Nov 1 2026)

Branch `caravan-v3-mlx-split`. Idea 1 several chats + N=3 stall fix + first
Day 6 lab video (LAB-2026-11-01-01 / v10). Not merged to `main`.

- **Idea 1 N=3 stall fix.** `_pipe_round` preferred the just-led chat for
  the next packer fetch, so a third chat waited ~4 s (tg128). Fair pick by
  `(n_gen, t0)` + admit one prefill per loop. N=3 max TTFT ≤0.62 s; wall
  aggregate ≈ N=2. N=2 unchanged. See
  [BENCHMARKS.md](BENCHMARKS.md#idea-1-several-chats-at-once-oct-31nov-1-mlx).

- **Idea 1: several chats at once (off by default).** `--split-pipeline-chats N`
  (env `CARAVAN_MLX_SPLIT_PIPELINE_CHATS`) overlaps Packer 1's work for chat B
  with the lead's layers for chat A when N≥2. Default N=1 is unchanged.
  With idea-5 cuts + keepalive: two chats ≈1.6× aggregate writing vs one;
  N=3 stall fixed Nov 1 (see bullet above). Flag-off single-chat matches
  keepalive baseline (~38 / 34 / 46 tok/s). Bench:
  `bench/v3/pipeline_bench.py`. Details:
  [BENCHMARKS.md](BENCHMARKS.md#idea-1-several-chats-at-once-oct-31nov-1-mlx).

## v3.2 (tag `v3.2`, `cb61970`, Oct 31 2026)

Branch `caravan-v3-mlx-split`. GPU keepalive default on (writing +28–50%)
and Day 5 lab video LAB-2026-10-31-05. Not merged to `main`.

## Notes that shipped in v3.2 (were unreleased after v3.1)

On branch `caravan-v3-mlx-split`.

**New**

- **GPU keepalive while waiting on the peer (default on).** During
  turn-taking each Mini sits idle ~15–20 ms; Metal then pays ~5 ms extra
  on the next graph build + eval. A short-lived side thread runs a tiny
  `mx.eval` during the blocking recv (`GpuKeepalive` in `mlx_split.py`).
  `--split-keepalive` on by default; `--no-split-keepalive` or
  `CARAVAN_MLX_SPLIT_KEEPALIVE=0` disables. A long-lived pause thread
  was tried and rejected (writing regressed).

- **GPU-wait test (`bench/cable/gpu_wait.py`).** Both Macs run every
  layer's two exchanges at the same time with GPU work sized like half of
  each model's layer. One exchange costs about 330–360 µs, mostly waiting
  for the GPU. Splitting each layer across both Macs would lose to one
  Mac on all three models and only roughly tie v3 on GPT-OSS: no-go,
  parked. See [BENCHMARKS.md](BENCHMARKS.md#gpu-wait-for-splitting-each-layer-oct-31-thunderbolt-4).

**Benchmarks**

- **Uneven layer split (idea 5).** Packer +1 / +2 layers vs even: no
  single-chat writing gain (serial pipeline). Best balanced cuts for
  idea 1: Gemma K=16, GPT-OSS K=13, Qwen3 even. See
  [BENCHMARKS.md](BENCHMARKS.md#uneven-layer-split-oct-31-mlx-idea-5).

- **GPU keepalive A/B** (`0f14e72`, LPM off, medians of 2): writing
  Gemma 4 38.3 vs 27.7, GPT-OSS 34.1 vs 26.6, Qwen3 45.6 vs 30.4 tok/s
  (on vs off); reading 512 / 4k slightly up; peak mem unchanged; quality
  3/3. `sudo powermetrics` needs a password on the Minis; lead CPU%
  median rose during waits under keepalive. See
  [BENCHMARKS.md](BENCHMARKS.md#gpu-keepalive-while-waiting-on-the-peer-oct-31-mlx).

- **v3 split rerun with Low Power Mode off on both Macs.** EXO2 (the
  packer) had been in Low Power Mode for all earlier two-Mac numbers.
  With it off, on v3.1 (`f68d15e`): writing 30.4 / 27.7 / 26.6 tok/s
  (was 29.5 / 26.9 / 26.1), reading 16–30% faster and now within about
  6% of one Mac, 8-bit writing 20.7 / 18.4 / 20.1 (was 20.6 / 18.1 /
  19.8), quality 3/3 on all six. See
  [BENCHMARKS.md](BENCHMARKS.md#v3-rerun-with-low-power-mode-off-oct-31-mlx-v31).
- **GPU-wait test rerun** with Low Power Mode off: about the same per
  exchange at batch 1 (325–366 µs), higher at batch 4 (403–414 µs).
  Splitting each layer is still a no-go (21.1 / 24.7 / 26.7 tok/s
  estimated). Raw JSON: `bench/cable/results/2026-10-31-gpu-wait-lpm-off.json`.

**Docs**

- GPU keepalive results and flag docs (LOG, ROADMAP idea 6,
  BENCHMARKS, MLX-SPLIT, CONFIGURATION, handoff experiments).
- Setup note: Low Power Mode must be off on both Macs for benchmarks
  (BENCHMARKS Method, MLX-SPLIT "Running it", `bench/v3` and
  `bench/cable` READMEs, ROADMAP known issues).

## v3.1 (tag `v3.1`, `2260d2e`, Oct 31 2026)

On branch `caravan-v3-mlx-split`, after the `v3` tag. Pushed with tag
`v3.1`; not merged into `main`.

**New**

- **Shard size check at startup (MLX split).** Before a split stage
  loads, it checks that every shard file it needs is complete: the size
  must match what the file's own safetensors header implies, and, when
  `mlx_split_fetch.py` downloaded it, the size Hugging Face lists (saved
  in `caravan-split-sizes.json` next to the files). A cut-off download or
  copy now stops the stage with an error that names the file and the
  `mlx_split_fetch.py` command to fetch it again from Hugging Face. It
  never falls back to getting files from the other Mac. 6 new unit tests
  (126 in total).
- **Cable-timing benchmark (`bench/cable/`).** Times one round trip over
  the Thunderbolt cable through Caravan's own split link and through
  plain TCP, at each model's per-layer exchange size. About 100 µs for
  one chat (the first guess was 50 µs). Result for splitting each layer
  across both Macs: not a go yet over Thunderbolt 4; see
  [BENCHMARKS.md](BENCHMARKS.md#cable-timing-oct-31-thunderbolt-4).

## v3 (tag `v3`, `df68468`): one MLX model split across two Macs

Branch `caravan-v3-mlx-split` (off `main` at `c026359`), pushed with tag
`v3`; not merged into `main`. Commits: `b03d1e9` (the split), `a167835` (cache fix for hybrid
models, bench client), `d68e094` (docs and results), `83f86a9` (lead /
packer names), `14dfcb4` and `8a64430` (roadmap), `df68468` (docs).

**New**

- **Split an MLX model across two Macs.** The packer Mac (Packer 1) runs
  the first half of the layers, the lead Mac runs the rest, picks each
  token and serves the API. They talk over one TCP connection on the
  Thunderbolt cable. The proxy needed no change. See
  [MLX-SPLIT.md](MLX-SPLIT.md).
- **Chat memory on both halves.** Each Mac keeps and saves its own half of
  each chat's cache. A saved chat is restored only when both halves are on
  disk and match; otherwise it's read again from scratch.
- **Split download (prototype CLI).** `agent/mlx_split_fetch.py` downloads
  only the files a Mac needs for its own layers from Hugging Face. Not yet
  run by the agent.
- Worker flags `--split-role`, `--split-peer`, `--split-listen`,
  `--split-packer-layers`; config `mlx.split.packer` /
  `mlx.split.packer_layers`; env `CARAVAN_MLX_SPLIT_PACKER` /
  `CARAVAN_MLX_SPLIT_PACKER_LAYERS`; `GET /caravan/split` on the lead.
  See [CONFIGURATION.md](CONFIGURATION.md#mlx-split-across-two-macs-v3).
- Bench client `bench/v3/split_client.py`.

**Why Caravan has its own link instead of MLX's.** MLX runs the model on
each Mac. Only MLX's ready-made ways of linking two Macs were skipped:
its standard link (`mx.distributed` ring) breaks on messages of about
2 MB or more over our Thunderbolt 4 cable, its fast direct-memory link
(jaccl, RDMA) needs Thunderbolt 5, and mlx-lm's built-in splitting only
covers Qwen models.

**Measured** (Oct 31, two Mac minis M4 24 GB, side by side with v2.1 on
one Mac):

- Memory per Mac roughly halves: Qwen3 30B 19.04 → 10.49 GB, Gemma 4 26B
  17.14 → 9.28 GB, GPT-OSS 20B 13.41 → 7.05 GB. Qwen3 30B now holds a 16k
  chat on MLX (on one Mac it runs out of memory).
- The cost: writing is 28–42% slower (Qwen3 51.0 → 29.5, Gemma 4 41.3 →
  26.9, GPT-OSS 36.5 → 26.1 tok/s), reading 16–25% slower, and resuming a
  chat takes 0.1–0.4 s longer. The two Macs take turns on every token;
  the cable is not the problem (under 1 ms and under 10 KB per token).
- Bigger versions that don't fit on one Mac now run split, all 3/3 on the
  quality checks with a 16k chat: Qwen3 30B 8-bit (20.6 tok/s, 18.12 GB
  per Mac), Gemma 4 26B 8-bit (18.1 tok/s, 15.58 GB), GPT-OSS 20B 8-bit
  (19.8 tok/s, 12.13 GB).
- Split download, Qwen3 30B 8-bit: lead 16.65 GB and packer 21.09 GB
  instead of 32.44 GB each.

**Fixed**

- Hybrid-attention models (Qwen3.6, `qwen3_5_moe`) crashed the lead at
  load; the stage now builds its cache from the full model first.

**Renamed (old names deprecated, still accepted)**

The Mac you talk to is now the **lead**; the other Macs are **packers**,
numbered in layer order (Packer 1 runs the first layers); the whole group
is the **string**. These replace "head", "front" and "tail".

| New | Deprecated alias |
|---|---|
| `--split-role lead` / `packer` | `--split-role head` / `front` |
| `--split-packer-layers K` | `--split-front-layers K` |
| `mlx.split.packer` / `packer_layers` | `mlx.split.front` / `front_layers` |
| `CARAVAN_MLX_SPLIT_PACKER` / `_PACKER_LAYERS` | `CARAVAN_MLX_SPLIT_FRONT` / `_FRONT_LAYERS` |
| `mlx_backend.build_lead_command()` / `build_packer_command()` | `build_head_command()` / `build_front_command()` |
| `mlx_split_fetch.py --role lead\|packer --packer-layers K` | `--role head\|front --front-layers K` |

When both are given, the new name wins. Saved split caches keep their old
stage id, so caches saved before the rename still load. Internal code
names (role values `head` / `front` / `tail`, `supervisor.build_head_command()`
and `build_tail_command()` for llama.cpp) are unchanged.

**Known limits:** slower than one Mac; two Macs only; the split link is
unauthenticated (keep it on the cable); the agent and the launchd plists
don't start a split yet (start both workers by hand); `--kv-bits` with the
split is untested; the bench talked to the worker directly (the proxy path
was smoke-tested only). GPT-OSS 120B still doesn't fit across two 24 GB
Macs (parked).

## v2.1 (`b9ebeb7`, docs `24adc11`, tag `v2.1`)

- The MLX worker sets Metal's wired limit once at startup and holds it
  (`--wired-limit startup`, the default).
- Optional deferred first MLX save (`mlx_save_min_turns`).
- Benchmarks now compare versions side by side in one session. With that
  method v1, v2 and v2.1 read a 4k prompt at 396, 393 and 396 tok/s
  (Qwen3).
- `main` later got docs-only commits: `c026359` points at the
  `linuxbren/llama.cpp` fork.

## v2 (`f57af3b`, `6d4bdb0`, `fac73b8`, `f73eafb`, `7835efd`)

- **Caravan MLX worker** (`agent/mlx_worker.py`) with one cache per chat,
  reused from message to message and saved to disk. Turn 2 of a 4k chat:
  Gemma 4 10.76 → 0.49 s, GPT-OSS 9.16 → 0.50 s. First message after a
  restart: 12.7–16.0 → 0.52–0.64 s.
- GPT-OSS replies cleaned up: the answer in `content`, the reasoning in
  `reasoning_content`.
- Per-Mac cap on saved chats: 200 files / 50 GB, llama.cpp and MLX
  together, least recently used first, never active chats.

## v1 (`32b9756`, `737fea2`, `c846e65`)

- Rebased llama.cpp (upstream `5047748f`, fork branch `caravan-patches`
  = `86e16204`). A 16k chat after a restart: GPT-OSS 46.3 → 0.65 s,
  Gemma 4 56.1 → 0.93 s. Faster 4k reading (GPT-OSS 403 → 454, Gemma 4
  355 → 380, Qwen3 338 → 356 tok/s).
- MLX models routed through the proxy to plain `mlx_lm.server` (step a).
- Automatic KV cache type: f16 when it fits, else q8_0.

## v0 (`45ed2c2`, Oct 30)

The baseline: configurable target model, cleanup of saved slots after 30
days, proxy performance work, explicit llama-server flags, docs for the
public repo. Benchmarked on the older llama.cpp base, now fork branch
`caravan-patches-v0` (`2f26123e`).

## Before v0 (Sep 2026)

GGUF split across two Macs with llama.cpp RPC, the proxy, launchd
services, the Thunderbolt cable (packer cold load 7–11 min → 29–39 s,
writing ~4 → 6.1 tok/s), `rpc-server --cache`, the self-organizing agent,
and the experimental C++ binary.
