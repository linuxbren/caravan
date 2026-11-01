# Benchmarks

Only measured numbers are listed here, each with where it came from. The
raw step-by-step notes are in [LOG.md](LOG.md).

## Method

**Hardware.**

- Two Mac minis, Apple M4 with 24 GB unified memory each.
- Linked by a Thunderbolt 4/USB4 cable (40 Gb/s) and the same LAN.
- The version comparisons v0 to v2.1 ran on **one** of them. v3 (the
  MLX split) uses both, compared side by side with v2.1 on one.

**Models.** The same three were used for every version comparison, each
in a GGUF build (llama.cpp) and an MLX build:

| model | GGUF | MLX |
|---|---|---|
| Qwen3-30B-A3B | Q4_K_S | `mlx-community` 4-bit |
| Gemma 4 26B-A4B | Q4_0 | `mlx-community` 4-bit |
| GPT-OSS 20B | MXFP4 | `mlx-community` MXFP4-Q8 |

**How we measure.**

- Everything is measured **through the Caravan proxy**, the same path a
  client uses, on test ports (llama-server 8180, proxy 8190, MLX 8192).
  The production services and exo were paused or left alone.
- Terms:
  - **Reading** (prompt processing): `pp512` and `pp4096` are tokens per
    second on a fresh 512- or 4096-token prompt.
  - **Writing** (generation): `tg128` is tokens per second over 128 new
    tokens.
  - **Wait for the first word** (TTFT) is timed while streaming.
  - **Peak memory** is the summed resident memory of the server process,
    or MLX's footprint.
- Medians of 3 runs unless noted. Quality is 3 fixed checks (a code
  word, a multiplication, a capital city) on every model and version.
- **Resume tests** use a chat of about 4k or 16k tokens:
  - turn 1 is cold
  - turn 2 is warm
  - then the server and proxy are fully restarted
  - turn 3 measures the saved-cache restore
- **Side by side in one session.** From v2.1 on, every variant being
  compared runs in the same session, restarted fresh each round, in
  rotating order. Comparing runs from different days turned out to be
  misleading: Qwen3's 4k reading drifted from 396 to 374–390 tok/s
  between days with no code change. Numbers from different tables below
  are from different days, so compare within a table.
- Restore times were measured with files in the disk cache (warm disk).
  A cold-disk restore will take longer.
- **Low Power Mode must be off on both Macs** (`pmset -g` should show
  `lowpowermode 0`; turn it off in System Settings → Energy, or
  `sudo pmset -a lowpowermode 0`). On Oct 31 EXO2 (the packer) was found
  in Low Power Mode; every two-Mac number up to the "v3 rerun" section
  below was measured that way. Turning it off made the split read 16–30%
  faster but write less than 3% faster.

**Scripts.**

| directory | used for |
|---|---|
| `bench/improvements/` | v0 → v1 |
| `bench/v2/` | v1 → v2 (`suite_v2.sh`, `suite_v2_llama.sh`) |
| `bench/v2.1/` | v1 / v2 / v2.1 same-session A/B (`ab_bench.py`, `suite_v21.sh`) |
| `bench/v3/` | v2.1 (one Mac) vs v3 (split across two) and the bigger brothers (`split_client.py`; see [its README](../bench/v3/README.md)) |
| `bench/cable/` | cable timing and the GPU-wait test for splitting each layer (`cable_timing.py`, `gpu_wait.py`; see [its README](../bench/cable/README.md)) |

## Two Macs over RPC (Sep 2026, llama.cpp)

These numbers are from an ~18 GB Ollama model (16 GB of weights) split
across both Macs. They're single runs during development, not a formal
benchmark, and they predate the v0–v2.1 flag changes, which haven't been
re-measured on two Macs yet.

| what | Wi-Fi/LAN (incl. Tailscale) | Thunderbolt |
|---|---|---|
| Writing | 4.23 tok/s first run; ~3.8–4.5 typical | 6.1 tok/s (6.09 via the Python agent, 6.03 via the C++ binary) |
| Reading | 15.5 tok/s first run; ~65–100 tok/s on long real prompts | 48.5 tok/s on a 149-token prompt |
| Model load, packer cache cold | 7–11 min | 29–39 s |
| Model load, packer cache warm (`rpc-server --cache`) | 53 s; 34 s for a full scripted packer restart | – |

RDMA over Thunderbolt isn't available on these Macs (it needs
Thunderbolt 5: M4 Pro/Max or M3 Ultra), so the Thunderbolt numbers are
plain TCP.

## Runtime compare (Oct 30, one Mac, before v1)

These runs put the GGUF and MLX runtimes next to each other on one Mac
mini. The Caravan column is v0 (proxy + llama-server, q8_0 KV). The
others used f16 KV.

| | model | Caravan v0 | llama.cpp | Ollama 0.40 | exo 1.0.71 (MLX) |
|---|---|---|---|---|---|
| writing tg128 (tok/s) | Qwen3 | 40.8 | 42.9 | 45.2 | 49.6 |
| | Gemma 4 | 34.9 | 37.0 | 37.2 | 41.5 |
| | GPT-OSS | 36.3 | 35.8 | 36.4 | 37.1 |
| reading pp4096 (tok/s) | Qwen3 | 336.7 | 325.4 | 367.6 | 410.6 |
| | Gemma 4 | 357.0 | 344.5 | 375.6 | 325.1 |
| | GPT-OSS | 429.5 | 373.6 | 420.6 | 398.6 |
| peak memory (GB) | Qwen3 | 18.7 | 19.4 | 19.3 | 20.4 |
| | Gemma 4 | 16.3 | 15.5 | 17.3 | 18.8 |
| | GPT-OSS | 12.9 | 12.8 | 13.0 | 15.0 |

Notes:

- exo's Qwen3 runner crashed on long prompts (2 of 3 attempts).
- On a warm 16k GPT-OSS chat, exo took 16.1 s to the first word, against
  2.2 s for Ollama.
- Neither Ollama nor exo saves conversation caches to disk.
- Caravan v0 resumed a 16k Qwen3 chat after a full restart in 1.18 s
  instead of 80 s. It did **not** resume Gemma 4 or GPT-OSS: their
  restored slots were thrown away (56.1 s and 48.1 s). That's what v1
  fixed.

## v0 → v1 (Oct 30, llama.cpp)

v0 is `45ed2c2` on the old llama.cpp build (now the `caravan-patches-v0`
branch of `linuxbren/llama.cpp`) with q8_0 KV. v1 is the
rebased llama.cpp plus the automatic KV type (f16 for Gemma 4 and
GPT-OSS, q8_0 for Qwen3).

**16k chat, wait for the first word after a full restart:**

| model | v0 | v1 | old build + `--swa-full` |
|---|---|---|---|
| GPT-OSS | 46.3 s | **0.65 s** | 0.59 s |
| Gemma 4 | 56.1 s | **0.93 s** | 0.48 s |
| Qwen3 (no sliding window) | 1.18 s | 1.10 s | – |

With checkpoints stored, Gemma 4's slot file grows from 291 MB to 849 MB.

**Speed** (tok/s; v0 → rebased with q8_0 → v1):

| model | tg128 | pp512 | pp4096 | pp @16k | tg @16k | peak memory |
|---|---|---|---|---|---|---|
| GPT-OSS | 35.9 → 37.1 → 37.1 | 374.7 → 434.0 → 436.8 | 403.0 → 452.3 → 453.6 | 237.3 → 258.6 → 256.6 | 27.7 → 28.9 → 31.1 | 12.8 → 13.0 → 13.4 GB |
| Gemma 4 | 34.4 → 34.8 → 36.7 | 333.9 → 383.5 → 399.9 | 354.9 → 377.8 → 379.7 | 211.0 → 226.4 → 231.5 | 25.9 → 25.8 → 27.5 | 16.4 → 16.7 → 18.4 GB |
| Qwen3 (q8_0 in both) | 41.4 → 42.5 | 361.1 → 401.9 | 338.0 → 356.4 | 124.8 → 128.2 | 20.7 → 20.9 | 18.7 → 18.7 GB |

Most of the reading gain comes from the rebase. f16 mostly adds writing
speed, and costs about 1.7 GB on Gemma 4.

**MLX step a, v1** (plain `mlx_lm.server` 0.32.2 behind the proxy; 4k chat):

| model | pp512 | pp4096 | tg128 | turn 2 | after restart |
|---|---|---|---|---|---|
| Gemma 4 | 427.2 | 383.8 | 39.8 | 10.8 s (no reuse) | 16.0 s |
| GPT-OSS | 434.4 | 441.4 | 35.3 | 9.2 s (no reuse) | 12.7 s |
| Qwen3 | 439.4 | 395.7 | 47.0 | 0.44 s | 16.0 s |

## v1 → v2 (Oct 31)

**MLX: Caravan MLX worker vs `mlx_lm.server`.**

| | Qwen3 | Gemma 4 | GPT-OSS |
|---|---|---|---|
| turn 2, 4k chat (first word) | 0.44 → 0.56 s | 10.76 → **0.49 s** | 9.16 → **0.50 s** |
| tokens re-read on turn 2 (4k) | (reused) → 46 | 4,034 → 36 | 4,041 → 32 |
| turn 2, 16k chat | out of memory in both | 55.1 → **0.72 s** | 37.3 → **0.59 s** |
| after restart, 4k | 16.0 → **0.59 s** | 16.0 → **0.64 s** | 12.7 → **0.52 s** |
| after restart, 16k | out of memory in both | 60.3 → **0.84 s** | 40.7 → **0.59 s** |
| writing tg128 (tok/s) | 47.0 → 49.1 | 39.8 → 42.2 | 35.3 → 37.4 |
| reading pp512 / pp4096 (tok/s) | 439 / 396 → 438 / 380 | 427 / 384 → 397 / 393 | 434 / 441 → 433 / 442 |
| peak footprint (speed tests) | 18.97 → 18.71 GB | 18.6 → 18.41 GB | 13.93 → 13.72 GB |
| save file 4k / 16k | – → 433 MB / – | – → 299 / 573 MB | – → 109 / 412 MB |
| quality | 3/3 → 3/3 | 3/3 → 3/3 | 3/3 → 3/3, no markup in content |

Other v2 measurements:

- Restore takes 0.01–0.13 s.
- The worker takes 6–9 s to start, vs 1.6 s for `mlx_lm.server`.
- `--kv-bits 8` didn't make Qwen3 fit at 16k, and slowed 4k reading
  from 380 to 325 tok/s.

**llama.cpp path, regression check** (same commands as v1):

| | Qwen3 | Gemma 4 | GPT-OSS |
|---|---|---|---|
| reading pp512 (tok/s) | 401.9 → 438.1 | 399.9 → 408.3 | 436.8 → 437.4 |
| reading pp4096 (tok/s) | 356.4 → 366.5 | 379.7 → 404.9 | 453.6 → 453.9 |
| writing tg128 (tok/s) | 42.5 → 43.0 | 36.7 → 37.1 | 37.1 → 37.3 |
| 16k chat after restart (s) | 1.103 → 1.102 | 0.93 → 0.913 | 0.652 → 0.65 |

## v1 / v2 / v2.1 side by side (Oct 31, 07:15–07:33 CDT, MLX)

Each variant was restarted fresh per round, in rotating order. Qwen3:
3 rounds × 2 runs per size; tok/s, median.

| Qwen3 | v1 `mlx_lm.server` | v2 | v2.1 | v2.1 + `mlx_save_min_turns 2` |
|---|---|---|---|---|
| 4k read (min–max) | 395.9 (385–397) | 393.4 (380–398) | 395.6 (390–399) | 396.4 (386–399) |
| 512 read, first after a 4.7k chat | 436 | 380 | 387 | 386 |
| 512 read, next | 441 | 438 | 439 | 434 |
| peak footprint / min free memory | 18.8 GB / 16% | 18.7 GB / 17% | 18.7 GB / 17% | 18.8 GB / 17% |

The worker's own reading speed at 4k was 400.1 / 400.5 / 401.0 tok/s
(v2 / v2.1 / v2.1 + save-min-turns 2).

Swap was 1.04 GB before the run, 1.45 GB at most during it, and 1.08 GB
after.

| Gemma 4 / GPT-OSS (1 round × 3) | v1 | v2 | v2.1 |
|---|---|---|---|
| Gemma 4, 512 / 4k read (tok/s) | 430 / 383 | 396 / 376 | 397 / 376 |
| GPT-OSS, 512 / 4k read (tok/s) | 429 / 418 | 424 / 415 | 424 / 415 |

**Resume, Qwen3 4k, v2.1:**

| turn | wait |
|---|---|
| turn 1 (cold) | 11.6 s |
| turn 2 | 0.72 s |
| restart | 9.7 s |
| turn 3 (re-read 31 of 4,377 tokens) | 0.52 s |
| turn 4 | 0.53 s |

A 4k save takes 0.10 s (399 MB).

**Proxy overhead** (proxy vs the worker directly): about 27 ms for
GPT-OSS, 61–67 ms for Qwen3, and 70–96 ms for Gemma 4.

**What it shows.**

- Side by side, v1, v2 and v2.1 read long prompts at the same speed. The
  4k gap between days was drift.
- Holding the wired limit made v2.1 a little steadier (slowest run 390
  vs 380 tok/s). The medians are within noise.
- Skipping the first save changed nothing measurable.
- The first short read after a big chat is about 0.15 s slower with the
  worker, with or without saves. That's likely the previous session
  being evicted from memory (this bench used `--prompt-cache-size 1`).
- **Gemma 4 short prompts are about 8% slower** with the worker than with
  plain `mlx_lm.server`. That gap is real and still open.

## v2.1 vs v3: one Mac vs two Macs (Oct 31, MLX)

v2.1 runs the whole model on one Mac mini. v3 splits it across both:
the packer Mac runs the embeddings and the first half of the layers, the
lead Mac runs the second half, the final norm, `lm_head` and sampling,
and they talk over one TCP connection on the Thunderbolt cable. Both
variants were run in one session (10:08–10:35 CDT; bigger brothers
10:38–11:05 CDT), with exo paused on both Macs. Each Mac loads from its
own local copy of the weights. The bench talks to the worker directly
(`bench/v3/split_client.py`); the proxy path was smoke-tested separately.

Speeds are tok/s, the median of 2 runs. Memory is the peak per Mac (for
v3, the busier of the two). "Quality" is 3 short checks (code, a
multiplication, a capital). 4k and 16k chats plant a code word in turn 1
and ask for it back.

Qwen3 v2.1 uses the tuned settings (`--prompt-cache-size 1
--prompt-cache-bytes 536870912 --prefill-step-size 512`); with the
defaults it runs out of GPU memory at 4k. v3 uses the defaults.

| | Qwen3 30B 4-bit v2.1 | v3 | Gemma 4 26B 4-bit v2.1 | v3 | GPT-OSS 20B v2.1 | v3 |
|---|---|---|---|---|---|---|
| writing (tok/s) | 51.0 | 29.5 | 41.3 | 26.9 | 36.5 | 26.1 |
| reading 512 (tok/s) | 465 | 388 | 431 | 328 | 457 | 350 |
| reading 4k (tok/s) | 400 | 332 | 399 | 301 | 445 | 338 |
| peak memory per Mac (GB) | 19.04 | 10.49 | 17.14 | 9.28 | 13.41 | 7.05 |
| 4k chat, turn 2 | 0.39 s | 0.51 s | 0.40 s | 0.59 s | 0.37 s | 0.46 s |
| 4k chat, after a restart | 0.33 s | 0.74 s | 0.46 s | 0.71 s | 0.34 s | 0.50 s |
| 16k chat, first read | out of memory | 81.9 s | 46.5 s | 61.3 s | 41.4 s | 54.2 s |
| 16k chat, turn 2 | – | 0.72 s | 0.42 s | 0.52 s | 0.39 s | 0.49 s |
| quality | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |

All 16k runs that fit found the code word. Restarts restored from disk
(`hit-disk`) on both versions, both halves on v3.

**Where the time goes (v3, per token written):**

| | packer | cable | lead | whole model on one Mac (v2.1) | sent per token |
|---|---|---|---|---|---|
| Qwen3 30B 4-bit | 16.6 ms | 0.72 ms | 16.3 ms | 19.6 ms | 5.4 KB |
| Gemma 4 26B 4-bit | 17.5 ms | 0.78 ms | 18.8 ms | 24.2 ms | 7.4 KB |
| GPT-OSS 20B | 17.0 ms | 0.89 ms | 20.5 ms | 27.4 ms | 9.6 KB |

A 4k read sends 16.6 MB (Qwen3) to 22.9 MB (Gemma 4) over the cable in
0.02–0.03 s.

**What it shows.**

- Memory per Mac roughly halves, so Qwen3 30B goes from right at the GPU
  limit to about 10.5 GB and now holds a 16k chat.
- Writing is 28–42% slower and reading 16–25% slower. The halves run one
  after the other, and each half costs almost as much as the whole model
  did on one Mac. So the time is per-pass overhead, not compute and not
  the cable (under 1 ms per token).
- Chat reuse and restart resume work across the split, at +0.1–0.4 s.
- exo's two-Mac MLX mode wasn't measured in this lab (no comparable
  numbers).

## Bigger brothers, split across two Macs (Oct 31, MLX, v3)

The same models at a higher-quality quantization, both versions on v3
across both Macs. None of the bigger ones fits on one 24 GB Mac.

| | Qwen3 30B 4-bit | Qwen3 30B 8-bit | Gemma 4 26B 4-bit | Gemma 4 26B 8-bit | GPT-OSS 20B MXFP4 (stock) | GPT-OSS 20B 8-bit | Qwen3.6 35B-A3B 5-bit (extra) |
|---|---|---|---|---|---|---|---|
| weights per Mac (GB) | 8.41 | 15.89 | 6.9 | 13.02 | 5.42 | 10.5 | 11.57 |
| writing (tok/s) | 29.5 | 20.6 | 26.9 | 18.1 | 26.1 | 19.8 | 25.7 |
| reading 512 / 4k (tok/s) | 388 / 332 | 377 / 320 | 328 / 301 | 316 / 282 | 350 / 338 | 334 / 312 | 387 / 362 |
| peak memory per Mac (GB) | 10.49 | 18.12 | 9.28 | 15.58 | 7.05 | 12.13 | 14.33 |
| 16k chat, first read / turn 2 | 81.9 / 0.72 s | 83.2 / 0.89 s | 61.3 / 0.52 s | 64.4 / 0.71 s | 54.2 / 0.49 s | 57.5 / 0.84 s | 53.2 / 53.5 s |
| 4k chat, after a restart | 0.74 s | 1.14 s | 0.71 s | 1.06 s | 0.50 s | 0.99 s | 12.1 s |
| quality | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |

- Qwen3 30B 8-bit fits a 16k chat at 18.1 GB per Mac, close to the
  ~19 GB GPU limit, so that's about the ceiling for this pair of Macs. It
  writes 30% slower than 4-bit (packer 23.5 ms + cable 0.81 ms + lead
  24.0 ms per token).
- Qwen3.6 35B-A3B (hybrid attention, `qwen3_5_moe`) runs, but it doesn't
  reuse the chat: its linear-attention layers can't be rewound and the
  template drops the reasoning from earlier replies, so every turn
  re-reads the whole chat. That's a model-family limit, not the split
  (see ROADMAP, parked).
- Gemma 4 26B 8-bit (27.95 GB) and GPT-OSS 20B 8-bit (22.23 GB) both fit a
  16k chat with room to spare (15.6 and 12.1 GB per Mac). Writing is 33% and
  24% slower than their 4-bit / MXFP4 versions; quality 3/3 on all of them.
- GPT-OSS only comes in 20B and 120B. The 120B doesn't fit two 24 GB Macs
  with chat room: every GGUF quant is 62.6–66 GB (experts stay MXFP4), and
  the smallest MLX build (`jesusoctavioas/gpt-oss-120b-mlx-2Bit`, 36.58 GB)
  would be ~18.3 GB of weights per Mac against a ~19.07 GB limit, while our
  stages peak 1.5–2.2 GB above their weights. So its bigger brother here is
  `lmstudio-community/gpt-oss-20b-MLX-8bit`. GPT-OSS ships with MXFP4
  experts, so the 8-bit build is mostly a re-encode; don't expect much
  quality gain from it.
- Qwen3 30B 8-bit ran from split downloads: each Mac had only its own
  shard files (lead 16.65 GB, packer 21.09 GB, of 32.44 GB). Gemma 4 8-bit and GPT-OSS
  20B 8-bit were downloaded on EXO1 and EXO2's packer files were copied over
  Thunderbolt (planned split: Gemma 22.75 / 15.59 of 27.95 GB, GPT-OSS
  16.98 / 15.8 of 22.23 GB).

## v3 rerun with Low Power Mode off (Oct 31, MLX, v3.1)

The same split bench as the two sections above, rerun after Brenden
turned Low Power Mode off on EXO2 (`pmset -g`: `lowpowermode 0` on both
Macs). Same models, same `bench/v3/split_client.py bench` client, same
worker defaults (4 sessions, 2 GB, prefill step 2048, 16-bit cache, save
on). Code: v3.1 at the branch tip, `f68d15e`, on both Macs (no speed
changes since v3). EXO1 lead on test port 8194, EXO2 packer on
169.254.104.38:5560. Medians of 2 runs. 4-bit 18:10–18:15 CDT, 8-bit
18:15–18:21 CDT; no services stopped. Raw output on EXO1 in
`~/.caravan/bench-2026-10-31/v3.1-rerun/`. Only the `bench` part was
rerun, not the 4k / 16k chat and restart tests. The one-Mac (v2.1)
numbers are from the earlier side-by-side session; they ran on one Mac
and weren't rerun.

**4-bit (the v3 headline models)**

| | Qwen3 30B: one Mac (v2.1) | old v3 | new v3 | Gemma 4 26B: one Mac | old v3 | new v3 | GPT-OSS 20B: one Mac | old v3 | new v3 |
|---|---|---|---|---|---|---|---|---|---|
| writing (tok/s) | 51.0 | 29.5 | **30.4** | 41.3 | 26.9 | **27.7** | 36.5 | 26.1 | **26.6** |
| reading 512 (tok/s) | 465 | 388 | **451** | 431 | 328 | **411** | 457 | 350 | **440** |
| reading 4k (tok/s) | 400 | 332 | **408** | 399 | 301 | **375** | 445 | 338 | **424** |
| peak memory per Mac, this bench (GB) | – | 10.44 | **10.02** | – | 9.28 | **9.09** | – | 7.03 | **6.94** |
| quality | 3/3 | 3/3 | **3/3** | 3/3 | 3/3 | **3/3** | 3/3 | 3/3 | **3/3** |

Peak memory here is the bench only (from `/caravan/split` right after
it), so it's compared with the old run's same snapshot, not with the
16k-chat peaks in the tables above (10.49 / 9.28 / 7.05 GB).

**8-bit (the bigger brothers)**

| | Qwen3 30B 8-bit: old | new | Gemma 4 26B 8-bit: old | new | GPT-OSS 20B 8-bit: old | new |
|---|---|---|---|---|---|---|
| writing (tok/s) | 20.6 | **20.7** | 18.1 | **18.4** | 19.8 | **20.1** |
| reading 512 / 4k (tok/s) | 377 / 320 | **442 / 395** | 316 / 282 | **401 / 362** | 334 / 312 | **430 / 405** |
| peak memory per Mac, this bench (GB) | 18.07 | **17.65** | 15.58 | **15.38** | 12.10 | **12.01** |
| quality | 3/3 | **3/3** | 3/3 | **3/3** | 3/3 | **3/3** |

**Where the time goes, per token written (ms, median of both runs)**

| | packer: old → new | cable: old → new | lead: old → new |
|---|---|---|---|
| Qwen3 30B 4-bit | 16.7 → 16.1 | 0.73 → 0.80 | 16.1 → 15.7 |
| Gemma 4 26B 4-bit | 17.4 → 16.4 | 0.79 → 0.82 | 18.5 → 18.5 |
| GPT-OSS 20B | 16.7 → 16.0 | 0.84 → 0.88 | 20.2 → 20.3 |
| Qwen3 30B 8-bit | 23.5 → 22.9 | 0.82 → 0.85 | 23.6 → 23.9 |
| Gemma 4 26B 8-bit | 24.6 → 23.8 | 0.96 → 0.89 | 28.9 → 29.1 |
| GPT-OSS 20B 8-bit | 23.0 → 22.2 | 0.94 → 0.88 | 25.9 → 26.3 |

Packer = time the packer reports ÷ link calls; cable = (time the lead
waited − packer time) ÷ calls; lead = (writing time − time waiting on
the packer) ÷ tokens written. Both runs are worked out the same way here,
so the old column can differ by up to 0.3 ms from the single-run numbers
in "where the time goes" above.

**What it shows.**

- **Reading got 16–30% faster; writing less than 3%.** Reading a prompt
  keeps the GPU doing sums flat out, and Low Power Mode had been slowing
  the packer's GPU. Writing one token at a time is mostly waiting for
  memory and the per-pass overhead, which Low Power Mode barely touched:
  the packer's half only got 0.5–1 ms faster per token.
- Reading on the split is now within about 6% of one Mac (Qwen3's 4k is
  even 2% ahead; different days, so call it a tie). Writing is still
  27–40% slower than one Mac, for the same reason as before: the Macs
  take turns, and each half costs almost what the whole model does on
  one Mac.
- The packer is now the faster half on every model: by 0.4 ms on Qwen3
  4-bit, 2–4 ms on Gemma 4 and GPT-OSS. Moving the cut (ROADMAP idea 5)
  was tried the same evening: no single-chat writing gain (serial
  pipeline); best balanced cuts recorded for idea 1. See
  [Uneven layer split](#uneven-layer-split-oct-31-mlx-idea-5).
- Memory is 0.1–0.4 GB lower than the old snapshot; the memory code
  didn't change, and the cause wasn't looked into.

## Cable timing (Oct 31, Thunderbolt 4)

The first test for splitting each layer across both Macs (ROADMAP idea
4). `bench/cable/cable_timing.py` (see [its README](../bench/cable/README.md)),
EXO1 (lead) to EXO2 (packer) over the Thunderbolt cable (`en2` on EXO1,
EXO2 at its link-local address), test port 5570/5571, MLX venv Python.
No models loaded, no Caravan or exo services running, nothing stopped.
Run 17:13–17:15 CDT. 100 warm-up round trips, then 2,000 per size (200
for 1 MB). Raw JSON: `bench/cable/results/`.

**Round trip, send N bytes and get N back (µs)**

| bytes | what | Caravan link median / p95 / p99 | plain TCP median / p95 / p99 | Caravan + GPU sync median / p95 |
|---:|---|---|---|---|
| 1,024 | | 99.8 / 127.2 / 148.0 | 80.2 / 105.1 / 113.1 | 1,058.9 / 1,340.4 |
| 4,096 | Qwen3 batch 1 | 101.1 / 123.1 / 133.4 | 90.9 / 110.9 / 117.0 | 1,102.9 / 1,327.0 |
| 5,632 | Gemma 4 batch 1 | 103.5 / 126.5 / 137.9 | 92.3 / 111.5 / 118.3 | 1,107.1 / 1,405.6 |
| 5,760 | GPT-OSS batch 1 | 104.4 / 125.7 / 139.6 | 87.9 / 108.9 / 116.0 | 1,106.3 / 1,441.8 |
| 16,384 | Qwen3 batch 4 | 122.1 / 148.5 / 160.0 | 104.6 / 123.2 / 130.7 | 1,143.3 / 1,454.3 |
| 22,528 | Gemma 4 batch 4 | 137.4 / 162.9 / 174.0 | 110.5 / 127.7 / 136.0 | 1,167.0 / 1,525.8 |
| 23,040 | GPT-OSS batch 4 | 128.1 / 150.7 / 165.7 | 111.3 / 129.0 / 138.8 | 1,168.5 / 1,500.0 |
| 65,536 | Qwen3 batch 16 | 190.5 / 214.0 / 222.4 | 158.1 / 183.0 / 196.1 | 1,294.4 / 1,949.3 |
| 90,112 | Gemma 4 batch 16 | 212.7 / 236.8 / 245.0 | 181.8 / 204.4 / 217.5 | 1,308.4 / 1,935.5 |
| 92,160 | GPT-OSS batch 16 | 213.1 / 236.0 / 246.1 | 179.9 / 204.9 / 218.4 | 1,309.6 / 1,949.6 |
| 262,144 | | 253.9 / 275.7 / 314.8 | 237.0 / 260.3 / 277.5 | 2,234.1 / 2,471.0 |
| 1,048,576 | | 693.2 / 729.4 / 946.9 | 754.4 / 788.6 / 866.3 | 4,483.4 / 4,977.9 |

Bulk, one way in 1 MiB frames through the Caravan link: 1,978 MB/s
(1,074 MB/s in the GPU-sync run). A second run without GPU sync (5,000
round trips per size, up to 92 KB) agreed within about 3%. A lone MLX
sync (make a 4 KB array, one op, wait) on EXO1 takes about 175 µs
median.

**What it means for splitting each layer** (ROADMAP formula: time per
step = the slower v3 half + layers × 2 × round trip; one step makes one
token per chat)

| model (layers) | batch | cable per step | predicted ms per step | predicted tok/s | one Mini (v2.1) | v3 split | v3 + several chats (best case) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen3 30B (48) | 1 | 9.7 ms | 26.3 | 38 | 51 | 29 | — |
| | 4 | 11.7 ms | 28.3 | 141 | 204 | 118 | 120 |
| | 16 | 18.3 ms | 34.9 | 459 | 816 | 471 | 482 |
| Gemma 4 26B (30) | 1 | 6.2 ms | 25.0 | 40 | 41 | 27 | — |
| | 4 | 8.2 ms | 27.0 | 148 | 165 | 108 | 106 |
| | 16 | 12.8 ms | 31.6 | 507 | 661 | 432 | 426 |
| GPT-OSS 20B (24) | 1 | 5.0 ms | 25.5 | 39 | 36 | 26 | — |
| | 4 | 6.1 ms | 26.6 | 150 | 146 | 105 | 98 |
| | 16 | 10.2 ms | 30.7 | 521 | 584 | 421 | 390 |

- The slower half is from v3's "where the time goes": Qwen3 16.6 ms
  (packer), Gemma 4 18.8 ms (lead), GPT-OSS 20.5 ms (lead). One Mini is
  19.6 / 24.2 / 27.4 ms per token and the v3 split 34 / 37 / 38 ms.
- The batch 4 and 16 columns are estimates, not measurements: every
  option is assumed to take the same time per step at batch 4 or 16 as at
  batch 1 (a best case; the larger batch costs some extra compute).
  "v3 + several chats" is half the chats on each Mini at a time, each
  step one slower half: batch ÷ 2 ÷ slower half.
- With the GPU-sync round trips instead, every model loses everything
  (for example GPT-OSS batch 1: 48 × 1.1 ms ≈ 53 ms of cable).
- Verdict and next step: ROADMAP, idea 4, "Result, Oct 31 2026".

## GPU wait for splitting each layer (Oct 31, Thunderbolt 4)

The follow-up to the cable timing. `bench/cable/gpu_wait.py` (see
[the README](../bench/cable/README.md#gpu-wait-test-gpu_waitpy)): both
Macs run every layer's two exchanges at the same time, with synthetic
4-bit GPU work sized like half of each model's layer (no model loaded,
0.8–2.4 GB of random weights per Mac). EXO1 lead, EXO2 packer, Caravan's
link framing over Thunderbolt, test port 5572, MLX 0.32.4. 200 timed
tokens per mode after 20 warm-up (9,600–19,200 exchanges per model at
batch 1). Run 17:31–17:36 CDT; no services stopped. Raw JSON:
`bench/cable/results/2026-10-31-gpu-wait.json`.

**Time per token on the lead (ms, median / p95)** (compute is also given
for the packer, the slower Mac)

| model | batch | compute (lead / packer) | wait after each part, no cable | swap only, no GPU | full exchange | overlap trick |
|---|---:|---|---|---|---|---|
| Qwen3 30B | 1 | 11.09 / 11.44 | 34.03 / 34.23 | 5.78 / 6.17 | 45.87 / 46.48 | — |
| | 4 | 30.25 / 47.48 | 55.62 / 56.04 | 6.62 / 6.96 | 81.19 / 86.50 | 89.85 / 90.58 |
| Gemma 4 26B | 1 | 11.92 / 12.30 | 25.57 / 25.81 | 4.42 / 4.98 | 32.91 / 33.36 | — |
| | 4 | 25.16 / 43.92 | 43.54 / 43.98 | 4.80 / 5.48 | 61.81 / 65.66 | 74.75 / 84.13 |
| GPT-OSS 20B | 1 | 11.51 / 12.21 | 22.26 / 22.52 | 4.18 / 4.91 | 28.11 / 28.63 | — |
| | 4 | 30.51 / 55.19 | 44.77 / 45.05 | 4.42 / 4.99 | 71.90 / 77.75 | 86.23 / 87.15 |

**Cost per exchange on top of the compute (µs)** = (time − slower Mac's
compute) ÷ exchanges per token (96 / 60 / 48)

| model | batch | GPU wait only (slower Mac) | cable only, median / p95 | full exchange, median / p95 | overlap trick |
|---|---:|---:|---|---|---:|
| Qwen3 30B | 1 | 277 | 60 / 64 | 359 / 365 | — |
| | 4 | 201 | 69 / 73 | 351 / 406 | 441 |
| Gemma 4 26B | 1 | 261 | 74 / 83 | 343 / 351 | — |
| | 4 | 219 | 80 / 91 | 298 / 362 | 514 |
| GPT-OSS 20B | 1 | 246 | 87 / 102 | 331 / 342 | — |
| | 4 | 230 | 92 / 104 | 348 / 470 | 647 |

**Estimate, single chat** (time per token = slower v3 half + exchanges
× full-exchange cost; v3 and one Mini are measured)

| model | split each layer | v3 split | one Mini | per exchange needed to beat v3 / one Mini |
|---|---|---:|---:|---|
| Qwen3 30B | 51.0 ms, 19.6 tok/s | 29.5 tok/s | 51.0 tok/s | < 180 µs / < 31 µs |
| Gemma 4 26B | 39.4 ms, 25.4 tok/s | 26.9 tok/s | 41.3 tok/s | < 306 µs / < 90 µs |
| GPT-OSS 20B | 36.4 ms, 27.5 tok/s | 26.1 tok/s | 36.5 tok/s | < 371 µs / < 144 µs |

- With the p95 exchange cost: 19.4 / 25.1 / 27.1 tok/s.
- The swap-only column (60–90 µs) is lower than the cable-timing round
  trip (100 µs), because both Macs send at the same time instead of
  taking turns.
- The cable is the smaller part. With a free cable (the cable-only column
  taken off), the estimate would be 22.1 / 28.6 / 31.0 tok/s, still below
  one Mini on all three.
- The overlap trick (two half-batches) was slower: each half-batch reads
  the weights again, and the GPU still has to stop twice.
- EXO2 (the packer) was in Low Power Mode (`pmset` lowpowermode 1), which
  likely explains why its compute was 50–80% slower than EXO1's at batch
  4. At batch 1 the two Macs were within 3–6%. Rerun below with it off.
- Verdict: ROADMAP, idea 4, "GPU-wait test, Oct 31 2026".

### Rerun with Low Power Mode off (Oct 31)

Run 18:21–18:25 CDT. Same script, defaults and port, `f68d15e` on both Macs, both Macs at
`lowpowermode 0`. Raw JSON:
`bench/cable/results/2026-10-31-gpu-wait-lpm-off.json`.

| model | batch | compute (lead / packer, ms) | GPU wait only (µs) | cable only, median / p95 (µs) | full exchange, median / p95 (µs) | overlap trick (µs) |
|---|---:|---|---:|---|---|---:|
| Qwen3 30B | 1 | 11.34 / 9.09 | 234 | 49 / 56 | 325 / 331 | — |
| | 4 | 27.15 / 27.37 | 299 | 55 / 59 | 403 / 411 | 572 |
| Gemma 4 26B | 1 | 9.55 / 9.55 | 272 | 74 / 81 | 366 / 377 | — |
| | 4 | 25.03 / 25.23 | 311 | 64 / 77 | 414 / 424 | 639 |
| GPT-OSS 20B | 1 | 9.53 / 9.56 | 269 | 78 / 97 | 359 / 373 | — |
| | 4 | 30.51 / 30.76 | 295 | 83 / 96 | 403 / 418 | 750 |

Worked out as before: GPU wait only = the slower Mac's (wait after each
part − its compute) ÷ exchanges; full exchange and overlap = (lead's
time − slower Mac's compute) ÷ exchanges.

**Estimate, single chat, with the new v3 halves** (slower half: Qwen3
packer 16.1 ms, Gemma 4 lead 18.5 ms, GPT-OSS lead 20.3 ms)

| model | split each layer | new v3 split | one Mini | per exchange needed to beat v3 / one Mini |
|---|---|---:|---:|---|
| Qwen3 30B | 16.1 + 96 × 0.325 ≈ 47.3 ms, 21.1 tok/s | 30.4 tok/s | 51.0 tok/s | < 175 µs / < 36 µs |
| Gemma 4 26B | 18.5 + 60 × 0.366 ≈ 40.5 ms, 24.7 tok/s | 27.7 tok/s | 41.3 tok/s | < 294 µs / < 95 µs |
| GPT-OSS 20B | 20.3 + 48 × 0.359 ≈ 37.5 ms, 26.7 tok/s | 26.6 tok/s | 36.5 tok/s | < 362 µs / < 148 µs |

- With the p95 exchange cost: 20.9 / 24.3 / 26.2 tok/s. With a free cable:
  23.5 / 27.7 / 29.6 tok/s, still below one Mini on all three.
- Batch 1 barely moved (325–366 µs per exchange, was 331–359). Batch 4
  got worse, 403–414 µs (was 298–351): the slow packer had been hiding
  part of the wait inside its own compute time. Now both Macs compute at
  the same speed and the full cost shows.
- EXO1's compute was also 17–20% lower than last time for Gemma 4 and
  GPT-OSS at batch 1. EXO1 was never in Low Power Mode; most likely the
  lead's "compute" timing includes the once-per-token handshake with the
  slower packer. Not looked into further.
- **Verdict: still no-go.** It now ties v3 on GPT-OSS (26.7 vs 26.6
  tok/s) instead of the earlier 5% lead, loses to v3 on Qwen3 (−30%) and
  Gemma 4 (−11%), and loses to one Mini on all three (−27% to −59%).

## Uneven layer split (Oct 31, MLX, idea 5)

Same split bench as the LPM-off rerun, with `--split-packer-layers K` on
both halves so Packer 1 gets the default half, then one more layer, then
two. Branch tip `845216b` on both Macs (same speed code as v3.1). EXO1
lead on test port 8194, EXO2 packer on 169.254.104.38:5560, worker
defaults. `lowpowermode 0` on both. Medians of 2 runs. 20:16–20:32 CDT.
Raw output on EXO1 in `~/.caravan/bench-2026-10-31/idea5-uneven/`. Only
the `bench` part (warm, tg128 ×2, pp512 ×2, pp4096 ×2, quality). Half
timings use the same formulas as the LPM-off table (packer =
front_s/calls; cable = (wait − front)/calls; lead = (write_s −
wait)/tokens), median of the two tg128 runs.

**4-bit**

| model | K (packer layers) | writing (tok/s) | reading 512 / 4k (tok/s) | wait before first word, tg128 (s) | peak mem lead / packer (GB) | packer / cable / lead (ms) | quality |
|---|---:|---:|---|---:|---|---|---|
| Gemma 4 26B | 15 (even) | 27.6 | 411.6 / 374.3 | 0.400 | 9.09 / 9.07 | 16.7 / 0.82 / 17.9 | 3/3 |
| | 16 (+1) | 27.4 | 412.6 / 374.9 | 0.398 | 8.58 / 9.58 | 17.8 / 0.82 / 17.0 | 3/3 |
| | 17 (+2) | 27.4 | 412.8 / 375.9 | 0.407 | 8.07 / 10.09 | 18.6 / 0.85 / 16.1 | 3/3 |
| GPT-OSS 20B | 12 (even) | 26.8 | 442.1 / 425.4 | 0.383 | 6.94 / 6.94 | 16.0 / 0.85 / 19.7 | 3/3 |
| | 13 (+1) | 26.6 | 439.3 / 426.6 | 0.381 | 6.48 / 7.40 | 17.4 / 0.85 / 18.5 | 3/3 |
| | 14 (+2) | 26.7 | 439.6 / 431.9 | 0.385 | 6.00 / 7.87 | 18.5 / 0.83 / 17.2 | 3/3 |
| Qwen3 30B | 24 (even) | 30.0 | 450.5 / 406.9 | 0.373 | 10.01 / 10.02 | 16.1 / 0.76 / 15.6 | 3/3 |
| | 25 (+1) | 30.2 | 449.6 / 410.6 | 0.370 | 9.63 / 10.40 | 16.7 / 0.77 / 14.7 | 3/3 |
| | 26 (+2) | 30.5 | 450.8 / 412.1 | 0.358 | 9.25 / 10.78 | 17.1 / 0.77 / 14.1 | 3/3 |

Even-split writing matched the LPM-off baseline (30.4 / 27.7 / 26.6)
within noise.

**What it shows.**

- **No single-chat writing gain** on Gemma 4 or GPT-OSS. The halves run
  one after the other, so moving a layer shifts ms from the lead to the
  packer and the sum stays flat (~35.5 ms Gemma, ~36.6 ms GPT-OSS).
  Qwen3's 30.0 → 30.5 is near noise; its even cut was already balanced
  (16.1 vs 15.6 ms).
- **Best balanced cuts** (smallest half-timing gap, for idea 1 later):
  Gemma 4 **K=16**, GPT-OSS **K=13**, Qwen3 **K=24 (even)**. GPT-OSS K=14
  overshoots. Reading stayed flat; packer peak memory rose and lead peak
  fell as K grew. Quality 3/3 on every cut.
- Verdict and next step: ROADMAP, idea 5.


## GPU keepalive while waiting on the peer (Oct 31, MLX)

Same split bench as the LPM-off / idea-5 runs, with `--split-keepalive`
(default on) vs `--no-split-keepalive`. Code commit `0f14e72` on branch
`caravan-v3-mlx-split` (spawn-per-wait `GpuKeepalive`). EXO1 lead on
test port 8194, EXO2 packer on 169.254.104.38:5560, worker defaults.
`lowpowermode 0` on both. Medians of 2 runs. 21:53–22:05 CDT. Raw output
on EXO1 in `~/.caravan/bench-2026-10-31/split-tax/ab/`. Only the `bench`
part. A long-lived pause-thread variant was tried on Gemma 4 and
rejected (writing ~17.6 tok/s); not in the table.

**4-bit**

| model | keepalive | writing (tok/s) | reading 512 / 4k (tok/s) | wait before first word, tg128 (s) | peak mem (GB) | quality |
|---|---|---:|---|---:|---:|---|
| Gemma 4 26B | off | 27.7 | 411.9 / 376.4 | 0.401 | 9.09 | 3/3 |
| | on | 38.3 | 427.0 / 397.7 | 0.344 | 9.09 | 3/3 |
| GPT-OSS 20B | off | 26.6 | 441.5 / 424.7 | 0.380 | 6.94 | 3/3 |
| | on | 34.1 | 452.3 / 443.6 | 0.335 | 6.94 | 3/3 |
| Qwen3 30B | off | 30.4 | 450.6 / 409.8 | 0.367 | 10.01 | 3/3 |
| | on | 45.6 | 461.5 / 429.0 | 0.324 | 10.01 | 3/3 |

**What it shows.**

- **Writing up ~28–50%** with no reading or quality regression (reading
  slightly higher). Peak memory unchanged. Quality 3/3 on every run.
- Cause: after ~15–20 ms idle waiting on the peer, Metal's next graph
  build + eval costs ~5 ms extra. A tiny `mx.eval` on a short-lived
  side thread during the blocking recv removes that cool-down.
- **Power / heat.** `sudo powermetrics` needs a password on the Minis
  (not measured in watts). Lead `ps` CPU% median during the bench rose
  with keepalive on (Gemma 4.5 → 13.9, GPT-OSS 1.7 → 15.0, Qwen 1.4 →
  12.8); packer median barely moved under the spawn design. The
  rejected long-lived thread held CPU medians around 70% and slowed
  writing.
- Flag: `--split-keepalive` (default on); `--no-split-keepalive` or
  `CARAVAN_MLX_SPLIT_KEEPALIVE=0` disables. See
  [MLX-SPLIT.md](MLX-SPLIT.md) and ROADMAP (Beating the turn-taking).


## Idea 1: several chats at once (Oct 31–Nov 1, MLX)

Branch tip after stall fix (tags `v3.3` / `v3.4`; after `v3.2` / `cb61970`). Test
ports 8194 / 5560. Low Power Mode off. Keepalive on. Idea-5 cuts for the
pipeline runs (Gemma K=16, GPT-OSS K=13, Qwen3 K=24). Client:
`bench/v3/pipeline_bench.py` (two waves of concurrent tg128; medians of
2). Flag-off check used `split_client.py bench` with even cuts.

### Flag off (single chat, even cut) — matches keepalive baseline

| model | writing (tok/s) | quality | peak GB (lead) |
|---|---|---|---|
| Gemma 4 26B | **38.1** (raw 38.5 / 37.8) | 3/3 | 9.27 |
| GPT-OSS 20B | **34.2** | 3/3 | 7.00 |
| Qwen3 30B | **45.7** | 3/3 | 10.29 |

Prior keepalive-on medians were 38.3 / 34.1 / 45.6 — within day noise.
Stall-fix recheck Nov 1 ~01:25 America/Chicago.

### Pipeline on (`--split-pipeline-chats 3`), idea-5 cuts — after stall fix

Medians of 2 waves. **Wall aggregate** = decode tokens across chats /
(wave wall − min prefill). **Sum** = sum of per-chat write tok/s.

| model | N | per-chat writing (tok/s) | wall aggregate | sum of per-chat | max TTFT (s) | peak GB | quality |
|---|---|---|---|---|---|---|---|
| Gemma 4 | 1 | 37.4 | 37.0 | 37.4 | 0.33 | 6.95 | 3/3 |
| | 2 | 33.3 / 33.3 | **61.0** | 66.6 | 0.63 | 8.21 | 3/3 |
| | 3 | ~21–22 each | **59.8** | 65.5 | **0.62** | 8.43 | 3/3 |
| GPT-OSS | 1 | 33.8 | 33.5 | 33.8 | 0.32 | 5.70 | 3/3 |
| | 2 | 29.1 / 29.1 | **54.0** | 58.2 | 0.60 | 6.37 | 3/3 |
| | 3 | ~19 each | **53.0** | 57.4 | **0.61** | 6.46 | 3/3 |
| Qwen3 | 1 | 44.8 | 44.4 | 44.8 | 0.31 | 8.70 | 3/3 |
| | 2 | 40.1 / 40.0 | **72.7** | 80.1 | 0.58 | 9.60 | 3/3 |
| | 3 | ~25–27 each | **70.8** | 78.6 | **0.59** | 10.0 | 3/3 |

**Before the stall fix (Oct 31 night):** N=3 left one chat with ~4 s TTFT
(Gemma 4.16 / GPT-OSS 4.71 / Qwen 3.49) and wall aggregate fell below N=2
(Gemma 48.4, GPT-OSS 43.5, Qwen 57.6). Cause: `_pipe_round` always gave
the next packer slot to `need[0]` in list order — the chat that just
finished lead — so a third never-started chat waited until one of the
first two finished tg128.

**After (Nov 1):** fair pick by `(n_gen, t0)` plus admit-one-prefill-per-
loop. N=3 max TTFT ≤0.62 s; wall aggregate ≈ N=2 (two-stage pipeline
cannot beat that much on wall time). N=2 unchanged. Quality 3/3. Workers
stopped; ports free after.

### What it shows

- **Two chats work.** Wall aggregate ≈1.6× one pipeline chat.
- **Three chats no longer stall.** Fair scheduling; wall ≈ N=2; per-chat
  rate falls (three chats share two halves).
- Pipeline N=1 is a few percent under flag-off even-cut (custom decode
  loop vs `stream_generate`); use flag off for single-chat compares.



## Idea 3: guess-ahead (speculative decoding) (Nov 1, MLX)

Branch tip after v3.4. Off by default: `--split-draft-model DIR` and
`--split-speculate-k K` (or `CARAVAN_MLX_SPLIT_DRAFT_MODEL` /
`CARAVAN_MLX_SPLIT_SPECULATE_K`). Draft runs on the lead only; each verify
is one Packer 1 + lead multi-token forward (one Thunderbolt round trip for
up to k drafts + bonus). Rejected tails trim both KV caches (`trim` op).
Test ports 8194 / 5560. Low Power Mode off. Keepalive on. Even cuts.
Client: `bench/v3/speculate_bench.py` (warm + tg128 ×2 + quality 3/3).
Raw JSON on EXO1 under `~/.caravan/bench-2026-11-01/speculate/`. Medians
of 2. Same writing metric as `split_client.py`
(`(completion_tokens-1)/(total_s-ttft_s)`).

**Drafts used (lead disk only):**

| target | draft | on-disk size | notes |
|---|---|---:|---|
| Qwen3 30B-A3B-4bit | `mlx-community/Qwen3-0.6B-4bit` | 335 MB | vocab match 151643 |
| Gemma 4 26B-A4B-it-4bit | `mlx-community/gemma-4-E2B-it-4bit` | 3.3 GB | vocab match 262144; draft ~half a lead half |
| GPT-OSS 20B | — | — | **no suitable small same-family draft** on mlx-community (only 20B/120B quants) |

**Qwen3 30B-A3B-4bit** (target from `~/.exo/models/...`; draft
`~/.caravan/mlx-models/drafts/Qwen3-0.6B-4bit`)

| k | writing (tok/s) | accepted_frac (from_draft/n_gen) | verify_rounds / 128 | peak GB (lead) | quality |
|---|---:|---:|---:|---:|---|
| off (baseline) | **45.9** | — | — | 8.68–8.69 | 3/3 |
| 2 | **57.1** | 0.656 | 44 | 9.01–9.02 | 3/3 |
| 3 | **57.4** | 0.734 | 34 | 9.01–9.02 | 3/3 |
| 4 | 56.3 | 0.781 | 28 | 9.01–9.02 | 3/3 |
| 5 | 55.1 | 0.812 | 24 | 9.01–9.02 | 3/3 |
| 6 | 54.0 | 0.836 | 21 | 9.01–9.02 | 3/3 |

Baseline matches the keepalive flag-off table (45.7). Best single-chat
gain ≈ **+25% at k=3**. Higher k raises acceptance but draft+verify cost
dominates after k=3 on this draft.

**Gemma 4 26B-A4B-it-4bit** (target `~/.exo/models/...`; draft
`gemma-4-E2B-it-4bit` 3.3 GB)

| k | writing (tok/s) | accepted_frac | verify_rounds / 128 | peak GB (lead) | quality |
|---|---:|---:|---:|---:|---|
| off (baseline) | **38.4 / 38.5** | — | — | 7.39 | 3/3 |
| 2 | 25.9 / 26.5 | 0.484 | 66 | 9.99–10.0 | 3/3 |
| 3 | 22.0 | 0.539 | 59 | 9.99–10.0 | 3/3 |
| 4 | 18.5 | 0.562 | 56 | 9.99–10.0 | 3/3 |
| 5 | 16.3 | 0.586 | 53 | 9.99–10.0 | 3/3 |
| 6 | 14.2 | 0.594 | 52 | 9.99–10.0 | 3/3 |

Baseline matches keepalive (38.1). Speculative is **slower** at every k:
E2B draft is heavy on the lead and acceptance stays mid (~0.5). Needs a
much smaller same-tokenizer Gemma draft (not found / not downloaded).

**GPT-OSS 20B:** skipped — no small same-family draft on mlx-community.

**8-bit side note (not the keepalive baseline):** the same Qwen code path
on 8-bit was ~27 tok/s without draft and ~35 with k=4 (still below the
4-bit baseline); peak ~16.6 GB. Idea 3 numbers above are 4-bit only.


## Not measured yet

- The two-Mac split with the v1+ settings (flash attention, automatic
  KV, the rebased llama.cpp).
- Cold-disk restore.
- Larger `ubatch` sizes.
- exo on the same two Macs (exo stays paused), so there are no comparable
  exo two-Mac numbers.
- The v3 split through the proxy under load (only smoke-tested).
- Overlapping the two halves for a **single** chat (still serial per chat;
  idea 1 overlaps across chats; idea 3 is guess-ahead).
- Batching weights inside one step on one Mac (v2.1). Idea 1 covers
  several chats on the split; cable-timing predictions for idea 4 still
  assume a step costs the same at batch 4 or 16 as at batch 1.
- Proxy-path concurrency for idea 1 (bench hit the lead directly; proxy
  FIFO still one-at-a-time for MLX).
- A GGUF split where the packer loads its own part from its own disk
  (stage 2; not built).
