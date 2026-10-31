# Benchmarks

Only measured numbers are listed here, each with where it came from. The
raw step-by-step notes are in [LOG.md](LOG.md).

## Method

**Hardware.**

- Two Mac minis, Apple M4 with 24 GB unified memory each.
- Linked by a Thunderbolt 4/USB4 cable (40 Gb/s) and the same LAN.
- The version comparisons (v0 onward) ran on **one** of them.

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

**Scripts.**

| directory | used for |
|---|---|
| `bench/improvements/` | v0 → v1 |
| `bench/v2/` | v1 → v2 (`suite_v2.sh`, `suite_v2_llama.sh`) |
| `bench/v2.1/` | v1 / v2 / v2.1 same-session A/B (`ab_bench.py`, `suite_v21.sh`) |

## Two Macs over RPC (Sep 2026, llama.cpp)

These numbers are from an ~18 GB Ollama model (16 GB of weights) split
across both Macs. They're single runs during development, not a formal
benchmark, and they predate the v0–v2.1 flag changes, which haven't been
re-measured on two Macs yet.

| what | Wi-Fi/LAN (incl. Tailscale) | Thunderbolt |
|---|---|---|
| Writing | 4.23 tok/s first run; ~3.8–4.5 typical | 6.1 tok/s (6.09 via the Python agent, 6.03 via the C++ binary) |
| Reading | 15.5 tok/s first run; ~65–100 tok/s on long real prompts | 48.5 tok/s on a 149-token prompt |
| Model load, tail cache cold | 7–11 min | 29–39 s |
| Model load, tail cache warm (`rpc-server --cache`) | 53 s; 34 s for a full scripted tail restart | – |

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
the front Mac runs the embeddings and the first half of the layers, the
head Mac runs the second half, the final norm, `lm_head` and sampling,
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

| | front | cable | head | whole model on one Mac (v2.1) | sent per token |
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
  writes 30% slower than 4-bit (front 23.5 ms + cable 0.81 ms + head
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
  shard files (head 16.65 GB, front 21.09 GB, of 32.44 GB). Gemma 4 8-bit and GPT-OSS
  20B 8-bit were downloaded on EXO1 and EXO2's front files were copied over
  Thunderbolt (planned split: Gemma 22.75 / 15.59 of 27.95 GB, GPT-OSS
  16.98 / 15.8 of 22.23 GB).

## Not measured yet

- The two-Mac split with the v1+ settings (flash attention, automatic
  KV, the rebased llama.cpp).
- Cold-disk restore.
- Larger `ubatch` sizes.
- exo on the same two Macs (exo stays paused), so there are no comparable
  exo two-Mac numbers.
- The v3 split through the proxy under load (only smoke-tested).
- Overlapping the two halves (not built yet).
