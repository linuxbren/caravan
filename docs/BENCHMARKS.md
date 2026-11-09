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
| Llama 3.1 8B | off | 21.2 | 243.0 / 227.7 | 0.372 | 3.75 | 3/3 |
| | on | 22.8 | 243.9 / 229.5 | 0.347 | 3.75 | 3/3 |
| Qwen2.5 14B | off | 11.7 | 120.8 / 117.9 | 0.689 | 4.35 | 3/3 |
| | on | 12.3 | 122.9 / 118.4 | 0.667 | 4.35 | 3/3 |
| DeepSeek-R1-Distill-Qwen 14B | off | 11.7 | 122.7 / 117.9 | 0.680 | 4.30 | 3/3 |
| | on | 12.4 | 125.1 / 118.0 | 0.536 | 4.35 | 3/3 |

**What it shows.**

- **Writing up ~28–50%** with no reading or quality regression (reading
  slightly higher). Peak memory unchanged. Quality 3/3 on every run.
- **Llama 3.1 8B (Nov 1 suite):** keepalive on is a smaller lift
  (21.2 → 22.8 writing; reading flat). Same method, even cut K=16,
  raw `~/.caravan/bench-2026-11-01/llama-suite/ka-*.jsonl`.
- **Qwen2.5 14B / Distill-Qwen 14B (Nov 1 suite):** keepalive on is a
  small lift (11.7 → 12.3 / 12.4 writing; reading flat). Even cut K=24.
  Raw `~/.caravan/bench-2026-11-01/qwen25-suite/ka-*.jsonl` and
  `distill-suite/ka-*.jsonl`.
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
| Llama 3.1 8B | 1 | 22.5 | **22.5** | 22.5 | 0.32 | 2.52 | 3/3 |
| | 2 | 20.9 / 20.8 | **39.3** | 41.7 | 0.60 | 3.24 | 3/3 |
| | 3 | ~13–14 each | **39.0** | 41.0 | **0.60** | 3.26 | 3/3 |
| Qwen2.5 14B | 1 | 12.3 / 12.4 | **12.3** | 12.4 | 0.60 | 4.35 | 3/3 |
| | 2 | 11.7 / 11.3 | **21.7** | 23.0 | 1.12 | 5.54 | 3/3 |
| | 3 | ~7.5 each | **21.5** | 22.9 | **1.13** | 5.67 | 3/3 |
| Distill-Qwen 14B | 1 | 12.3 | **12.2** | 12.3 | 0.35 | 4.36 | 3/3 |
| | 2 | 11.7 / 11.0 | **21.5** | 22.7 | 0.98 | 5.55 | 3/3 |
| | 3 | ~7.6 each | **21.6** | 22.9 | **0.87** | 5.69 | 3/3 |

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
| Llama 3.1 8B-Instruct-4bit | `mlx-community/Llama-3.2-1B-Instruct-4bit` | 680 MB (size_mb 663) | vocab exact 128256; Mini-verified Nov 1 |
| Qwen2.5 14B-Instruct-4bit | `mlx-community/Qwen2.5-0.5B-Instruct-4bit` | ~278 MB | vocab exact; Mini-verified Nov 1 |
| DeepSeek-R1-Distill-Qwen 14B-4bit | same 0.5B helper | ~278 MB | vocab exact (Qwen2.5 tokenizer); Mini-verified Nov 1 |

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




## Idea 3 follow-up: lighter drafts + prompt-lookup (Nov 1, MLX)

Same test ports / LPM off / keepalive on / medians of 2 / quality 3/3.
Flags: `--split-draft-model`, `--split-speculate-k`, new
`--split-prompt-lookup N` (draft-free n-gram / prompt lookup). Draft
prefill now uses the **full prompt** (earlier bug: last token only).
`RotatingKVCache` (GPT-OSS sliding window 128) refuses multi-token verify
when trim room would run out. Timing fields: `draft_s`, `verify_s`,
`pl_hits` / `pl_misses`. Raw JSON:
`~/.caravan/bench-2026-11-01/speculate2/`. Suite prompts: count (standard),
repeat (verbatim copy), code_edit, code_cont.

### Verify path

`SplitModel.__call__` already sends the full token list in **one** packer
`fwd` (one Thunderbolt RT) then lead layers. Multi-token verify is one RT.
Qwen draft k=3 count: `draft_s≈0.47s`, `verify_s≈1.75s` over 33 rounds
(~53 ms/verify for up to 4 tokens) vs ~22 ms/token baseline — wins when
acceptance is high.

### Gemma 4 26B-A4B-it-4bit

Tokenizer note: `gemma-3-270m-it-4bit` (~181 MB downloaded) shares 262k
vocab size but **not** identical `tokenizer.json` (~6206 id remaps, mostly
specials/unused). Content encodes mostly align after BOS; used as draft
anyway. `gemma-4-E2B-it-4bit` (3.3 GB) is an exact tokenizer match.

| setting | count | repeat | code_edit | code_cont | peak GB | notes |
|---|---:|---:|---:|---:|---:|---|
| baseline | **38.4** | 38.2 | 38.2 | 38.3 | 7.39 | matches 38.1 |
| E2B k=1 | 37.4 | — | — | — | 10.05 | draft_s 1.10 / verify_s 2.36 |
| E2B k=2 | 36.4 | — | — | — | 10.05 | draft_s 1.48 / verify_s 2.09 |
| **g3-270m k=2** | **44.4** | **46.6** | **44.7** | 38.1 | 7.54 | **best overall** (~+16% count) |
| g3-270m k=3 | 41.5 | — | — | — | 7.54 | |
| g3-270m k=4 | 37.3 | — | — | — | 7.54 | |
| PL n=3 k=4 | 29.1 | **49.0** | 33.8 | 31.0 | 7.39 | wins only on repeat |
| PL n=5 k=6 | 24.8 | 43.6 | 28.4 | 25.0 | 7.39 | |
| hybrid PL+270m k=2 | 28.9 | 48.8 | 36.1 | 34.6 | 7.54 | PL false hits hurt count |

**E2B cost:** draft alone ~3–4× the 270m draft time; acceptance mid; never
beats baseline. **Best Gemma setting: `--split-draft-model gemma-3-270m-it-4bit --split-speculate-k 2`.**

### GPT-OSS 20B MXFP4-Q8

No small same-family / o200k_harmony draft on mlx-community (only 20B/120B;
CUDA EAGLE/DFlare not MLX). Tokenizer-translation not practical without a
small o200k MLX model. Sliding-window KV (128) limits speculation headroom.

| setting | count | repeat | code_edit | code_cont | peak GB |
|---|---:|---:|---:|---:|---:|
| baseline | **34.0** | 33.9 | 33.2 | 34.0 | 6.13 | matches 34.2 |
| PL n=3 k=4 | 29.8 | 33.3 | 33.9 | 32.9 | 6.13 | accept_frac ~0.07 |
| PL n=2 k=3 | 31.1 | 32.9 | **34.9** | 33.4 | 6.13 | tiny code_edit bump |

**Best GPT-OSS: baseline (no speculate).** Prompt-lookup does not help the
standard chat mix; sliding window + low n-gram hits.

### Qwen3 30B-A3B-4bit (prefill fix recheck)

| setting | count | repeat | code_edit | code_cont | peak GB |
|---|---:|---:|---:|---:|---:|
| baseline | **45.5** | 44.5 | 42.8 | 44.7 | 8.68 | ~45.9 prior |
| **draft 0.6B k=3** | **59.3** | **62.3** | **72.0** | **57.5** | 9.14 | was 57.4 before prefill fix |
| PL n=3 k=4 | 30.4 | **63.7** | 36.8 | 30.5 | 8.68 | repeat-only win |

**Best Qwen: draft 0.6B k=3** (still). Prefill fix ~+3% on count vs 57.4.

### Self-speculation / lead-only early exit

Not attempted: lead holds only the upper layers; logits need packer
embeddings + lower layers. Would need new packer early-exit protocol.



### Llama 3.1 8B-Instruct-4bit (Mini suite, Nov 1)

Target `mlx-community/Meta-Llama-3.1-8B-Instruct-4bit` (~4.2 GB on disk) on
both Minis; draft `Llama-3.2-1B-Instruct-4bit` on the lead only (~680 MB).
Even cut K=16. Test ports 8194 / 5560. LPM off. Keepalive on unless noted.
Medians of 2. Client suite under `~/.caravan/bench-2026-11-01/llama-suite/`.
`speculate_bench.py` guards `denom > 0` on short quality replies.

**Keepalive A/B** (also in the keepalive table above): off **21.2** writing /
243.0 / 227.7 reading; on **22.8** / 243.9 / 229.5. Quality 3/3.

**Pipeline** (also in the idea 1 table): wall aggregate N=1 **22.5**, N=2
**39.3**, N=3 **39.0**; max TTFT ≤0.60 s. Same ~1.7× N=1→N=2 pattern as the
30B-class models; N=3 wall ≈ N=2.

**Guess-ahead suite** (`speculate_bench.py` count / repeat / code_edit /
code_cont; `--no-split-draft` vs auto-pair `llama3`):

| setting | count | repeat | code_edit | code_cont | accept (count) | quality |
|---|---:|---:|---:|---:|---:|---|
| nodraft (baseline) | **22.7** | 22.0 | 20.7 | 22.2 | — | 3/3 |
| **auto-pair Llama-3.2-1B k=3** | **51.5** | **51.6** | **64.7** | **46.8** | 0.75 | 3/3 |

Count ≈ **+127%** vs nodraft (strongest single-chat guess-ahead lift measured
so far on the Minis). Accept ~0.75 across count/repeat/edit; code_cont 0.71.

**First-load gate** (cache write, skip-first-load off): keep=1, quality 3/3,
baseline **19.29** / spec **35.87** tok/s, accepted_frac 0.75,
break_even_frac ≈ **0.45**.

**Shut-off:** with cached break_even raised to **0.80** and lead restarted
*without* `--split-draft-skip-first-load` (cache hit loads be=0.80), hex
stream chat disabled guessing (`accepted_frac 0.688 < 0.80` then
`0.354 < 0.80`). Skip-first-load leaves default be=0.35 and will not demo
shut-off against a high-accept draft.

**Download prompt:** draft moved aside; PTY yes on
`A 663 MB helper… Download Llama-3.2-1B-Instruct-4bit?` → download + draft
wired; `download_answers.llama3=true`. Draft restored from `.bak`.

**Decision:** keep `llama3` pairing as **mini_verified** in
`agent/guessers.json`.




### Qwen2.5 14B-Instruct-4bit (Mini suite, Nov 1)

Target `mlx-community/Qwen2.5-14B-Instruct-4bit` on both Minis; draft
`Qwen2.5-0.5B-Instruct-4bit` on the lead only (~278 MB). Even cut K=24.
Test ports 8194 / 5560. LPM off. Keepalive on unless noted. Medians of 2.
Raw `~/.caravan/bench-2026-11-01/qwen25-suite/`.

**Keepalive A/B** (also in the keepalive table above): off **11.7** writing /
120.8 / 117.9 reading; on **12.3** / 122.9 / 118.4. Quality 3/3.

**Pipeline** (also in the idea 1 table): wall aggregate N=1 **12.3**, N=2
**21.7**, N=3 **21.5**; max TTFT ≤1.13 s. Same ~1.8× N=1→N=2 pattern; N=3
wall ≈ N=2.

**Guess-ahead suite** (`speculate_bench.py` count / repeat / code_edit /
code_cont; `--no-split-draft` vs auto-pair `qwen25`):

| setting | count | repeat | code_edit | code_cont | accept (count) | quality |
|---|---:|---:|---:|---:|---:|---|
| nodraft (baseline) | **12.4** | 12.0 | 11.4 | 12.2 | — | 3/3 |
| **auto-pair Qwen2.5-0.5B k=3** | **33.8** | **37.1** | **46.4** | **35.9** | ~0.73 | 3/3 |

Count ≈ **+173%** vs nodraft. Accept ~0.73–0.76 across prompts.

**First-load gate** (cache write, skip-first-load off): keep=1, quality 3/3,
baseline **10.49** / spec **24.73** tok/s, accepted_frac 0.75,
break_even_frac ≈ **0.45**.

**Shut-off:** with cached break_even raised to **0.80**, hex stream chat
disabled guessing (`accepted_frac 0.729 < 0.80`).

**Download prompt:** draft moved aside; PTY yes on
`A 278 MB helper… Download Qwen2.5-0.5B-Instruct-4bit?` → download + draft
wired; `download_answers.qwen25=true`. Draft restored from `.bak`.

**Decision:** keep `qwen25` pairing as **mini_verified** in
`agent/guessers.json`.


### DeepSeek-R1-Distill-Qwen 14B-4bit (Mini suite, Nov 1)

Target `mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit` on both Minis;
same draft `Qwen2.5-0.5B-Instruct-4bit` (Distill-Qwen shares the Qwen2.5
tokenizer). Even cut K=24. Test ports 8194 / 5560. LPM off. Keepalive on
unless noted. Medians of 2. Raw
`~/.caravan/bench-2026-11-01/distill-suite/`.

**Keepalive A/B:** off **11.7** writing / 122.7 / 117.9 reading; on **12.4**
/ 125.1 / 118.0. Quality 3/3.

**Pipeline:** wall aggregate N=1 **12.2**, N=2 **21.5**, N=3 **21.6**; max
TTFT ≤0.98 s. Same N=2 peak / N=3 ≈ N=2 pattern.

**Guess-ahead suite:**

| setting | count | repeat | code_edit | code_cont | accept (count) | quality |
|---|---:|---:|---:|---:|---:|---|
| nodraft (baseline) | **12.3** | 12.4 | 12.4 | 12.4 | — | 3/3 |
| **auto-pair Qwen2.5-0.5B k=3** | **16.9** | **17.4** | **17.9** | **21.2** | ~0.45 | 3/3 |

Count ≈ **+37%** vs nodraft. Accept ~0.45–0.46 (lower than Qwen2.5 Instruct;
long reasoning traces). Still clears the first-load keep gate.

**First-load gate:** keep=1, quality 3/3, baseline **11.17** / spec
**13.98** tok/s, break_even_frac ≈ **0.255**.

**Shut-off:** with be raised to **0.80**, hex stream disabled
(`accepted_frac 0.542 < 0.80`).

**Download prompt:** draft moved aside; PTY yes on
`A 278 MB helper… Download Qwen2.5-0.5B-Instruct-4bit?` → download + draft
wired; `download_answers.deepseek-r1-distill-qwen=true`. Draft restored
from `.bak`.

**Decision:** keep `deepseek-r1-distill-qwen` pairing as **mini_verified**.


### Auto-tune vs hand-tuned (ROADMAP #13a, Nov 1)

When `--split-packer-layers` and `--split-pipeline-chats` are omitted, the
worker picks both (explicit flags still win). Packer hello carries
`mem_total_gb`; lead logs one plain line each for the chosen split and
pipeline. Verified on both Minis (test ports 8194 / 5560, LPM off, keepalive
on, warm-up, medians of 2, quality 3/3). Raw
`~/.caravan/bench-2026-11-01/day9-autotune/`.

**Auto picks (both equal-RAM ~26 GB reported):**

| model | auto K | auto pipeline | reason (split / pipeline) |
|---|---:|---:|---|
| Qwen3-30B-A3B-4bit | **24** | **2** | balanced cut 48 layers (qwen3_moe) / headroom 3.0 GB after ~8.4 GB weights |
| Llama-3.1-8B-Instruct-4bit | **16** | **2** | balanced cut 32 layers (llama) / headroom 7.9 GB after ~2.0 GB weights |
| Qwen2.5-14B-Instruct-4bit | **24** | **2** | balanced cut 48 layers (qwen2) / headroom 3.9 GB after ~3.7 GB weights |

Hand-tuned targets were the same: Qwen3/Qwen2.5 `K=24` pipe 2; Llama `K=16`
pipe 2. Auto matched those cuts and chat counts on every model.

**Speeds (tok/s, medians of 2):**

| model | mode | write tg128 | read pp512 | read pp4096 | pipe N=2 wall agg | quality |
|---|---|---:|---:|---:|---:|---|
| Qwen3 | auto | **45.0** | 462.2 | 429.0 | **68.3** | 3/3 |
| Qwen3 | tuned K24/N2 | **45.0** | 461.9 | 429.0 | **68.8** | 3/3 |
| Llama 3.1 8B | auto | **22.5** | 242.8 | 228.9 | **37.3** | 3/3 |
| Llama 3.1 8B | tuned K16/N2 | **22.6** | 243.2 | 229.7 | **38.2** | 3/3 |
| Qwen2.5 14B | auto | **12.4** | 122.8 | 118.5 | **20.9** | 3/3 |
| Qwen2.5 14B | tuned K24/N2 | **12.4** | 123.2 | 117.4 | **18.9** | 3/3 |

Auto matched or beat hand-tuned within run noise (Qwen2.5 pipe wall: auto
20.9 > tuned 18.9). **No failures** across 6 lead suites (3 models × auto|
tuned). Unit tests: **133** pass (including `AutoTuneTest`).


## llama.cpp 6a1a922 baseline and GGUF stage 2 (Nov 7, 2026, Day 18)

Prompt "Write a short story about a caravan crossing a desert at night.", 256 tokens,
temp 0, no prompt cache, 3 runs, Caravan commit 1955cab-era web server.

| Model | Where | Write tok/s |
|---|---|---|
| qwen2.5-3b-instruct-q4_0 | one Mini | 50.6 / 50.6 / 50.5 |
| qwen2.5-3b-instruct-q4_0 | split, share over the link (load 4.0 s) | 41.8 / 41.7 / 41.6 |
| qwen2.5-3b-instruct-q4_0 | split, EXO2 share from own disk (load 3.0 s + 6.2 s seed) | 41.8 / 42.1 / 41.1 |
| Qwen3-30B-A3B-Q4_K_S | one Mini | 34.4 / 34.4 / 34.4 |
| Qwen3-30B-A3B-Q4_K_S | split (load 12.1 s) | 35.1 / 35.1 / 34.3 |

"After" (llama.cpp 76a67730), back to back with 6a1a922 the same evening (8:15–8:21 PM CT, write tok/s): 3B single 50.2–50.4 → 48.9–49.1; 3B split 41.6–41.9 → 41.0; 30B single 43.2–43.4 → 43.4–43.5; 30B split 34.9–35.1 → 35.4–35.8. First token on short prompts about 45% faster on 3B. Default kept on 6a1a922. Full table: [DAY18.md](DAY18.md) "After release".

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


## Day 19 — N-stage Balance box-only checkpoint (2026-11-08, before live clearance)

At that checkpoint no Mini was contacted and no new inference/Thunderbolt/RAM benchmark was run.
Do not compare the fake-node simulator's wall time with real model tok/s.
The Linux-box simulator verified 3, 4 and 7 stages: forward order was complete,
cold reuse 0 tokens, second-turn reuse 2 tokens, and each stage saved/restored
its own cache. Full details and regression counts: [DAY19.md](DAY19.md).
The later live checks below supersede the pending two-Mini simulation results. Use an
already-installed small model on two Minis with a second packer process first;
that verifies correctness, not a third GPU's throughput.


## Day 19 live checks — 2026-11-08, afternoon CST

**Correctness/smoke measurements, not a performance comparison or medians.** Two
24 GiB M4 Minis; Low Power Mode read back as off on both. The existing 27B Qwen
split stayed loaded throughout (EXO2 24 / EXO1 40 layers); it was not restarted.
EXO2 hosted both extra packers in the three-stage simulation, so there were
**three stages, only two physical GPUs**. Short 6–7-token answers and concurrent
resident models make these unsuitable for throughput claims. Source artifacts
are under `~/.caravan/day19-live` on the relevant Mini; exact reply JSON names
are below. No release made.

### MLX: Orvena/Orvena-4B-MLX-4bit, 32 layers

**Later correction (18:39 CST):** the write-rate column below preserves the
historical UI values, which divided all six generated tokens by the five decode
intervals and overstated native decode by 20% for these six-token replies.
They are not native throughput numbers. The worker log uses `(tokens - 1) /
(total - TTFT)`; the reboot-follow-up fix now supplies that exact native rate to
the UI. Do not use these old UI figures for a performance comparison. New
native observations and timing lines are in the reboot section below.

No-think template option used for the quality rows; answers were correctly
"four" and "six". Times come from the worker timing log / reply telemetry, not
HTTP wall time. Counts are packer-first. Cold two-stage load: **6.804 s**;
saved normal-picker three-stage reload: **7.901 s**. Polls required new PID and
requested counts; an earlier old-ready-state observation is excluded.

| Artifact `.json` | Split | Prompt / cached | New tokens | Prefill s | First token s | Total s | Historical UI write tok/s (inflated) |
|---|---|---:|---:|---:|---:|---:|---:|
| `two-quality-cold` | 16/16 | 34/0 | 6 | .169 | .213 | .392 | 33.52 |
| `two-quality-warm` (new turn, template diverged) | 16/16 | 61/0 | 6 | .165 | .208 | .387 | 33.52 |
| `two-after-web-restart` (identical prompt) | 16/16 | 61/60 | 6 | .009 | .053 | .241 | 31.91 |
| `three-quality-cold` | 11/11/10 | 34/0 | 6 | .264 | .358 | .540 | 32.97 |
| `three-quality-turn2` (template diverged) | 11/11/10 | 61/0 | 6 | .169 | .218 | .399 | 33.15 |
| `three-quality-warm-repeat` | 11/11/10 | 61/60 | 6 | .009 | .057 | .247 | 31.58 |
| `three-quality-restored` (explicit disk restore, then reply) | 11/11/10 | 61/60 | 6 | .012 | .066 | .248 | 32.97 |
| `service-cold-reply` (native launchd) | 11/11/10 | 24/0 | 6 | .105 | .155 | .337 | 32.97 |
| `service-warm-reply` | 11/11/10 | 24/23 | 6 | .009 | .057 | .238 | 33.15 |
| `service-after-lead-child-crash-fixed` | 11/11/10 | 23/22 | 6 | — | .072 | .255 | 32.79 |
| `service-after-lead-agent-crash` | 11/11/10 | 23/22 | 6 | — | .077 | .262 | 32.43 |

Growing-turn cache reuse was **not** demonstrated for this no-think template:
it safely diverged and reread the prompt. Identical-prompt warm reuse, explicit
Save/Restore, web-only restart adoption and crash-time disk restore did work.
The explicit restore row reports `hit-memory` because Restore loads the disk
cache before the subsequent chat request. An earlier thinking-only check used
48 reasoning tokens and no final answer; it is not counted as a quality pass.

Native service startup observation: **16.976 s**. First-packer graceful child
restart: **16.746 s**, same local agent. Lead child crash: **17.306 s** with the
fixed agent (older already-running agent took **47.249 s**, including false
TIME_WAIT busy retries). Agent SIGKILL → launchd recovery: **2.547 s**, old child
confirmed gone. These are single observations including polling/retry delay.

### Own-files measurements

- The Orvena source is a **single 3,034,300,629-byte safetensors shard** containing
  all layers. Each stage therefore needs that entire file: whole-shard fetching
  is not tensor slicing. The EXO2 second test store was an APFS clone, not a
  symlink or inter-Mini copy. Logical/st_blocks usage is not exclusive physical
  storage when APFS shares blocks. Multi-shard MLX transfer savings remain to
  be exercised by a real reload; read-only 27B previews below were tested.
- Existing 27B split logical on-disk totals: EXO1 **10,731,498,067 B**, EXO2
  **10,717,679,207 B** including metadata. Preview 16/48 requested EXO1 shard 1
  (**5,343,269,992 B**), and marked its opposite-side retained shard; 48/16
  requested EXO2 shard 3 (**5,357,088,982 B**). No production fetch/reload.
- MLX explicit fetch/stop/resume and web-restart adoption were exercised. Lead
  partial file reached **407,896,064 B** before the restart/stop/resume check.
  Duplicate Fetch was refused while the rediscovered owned transfer ran.
- GGUF `Qwen/Qwen2.5-3B-Instruct-GGUF`, `qwen2.5-3b-instruct-q4_0.gguf`:
  immutable source **1,997,879,712 B**; first source/hash preview **5.085 s**.
  Equal shares assign lead slots [0,19), peer [19,37), including output slot 36.
  Exact assigned peer tensors >10 MiB: **901,994,496 B**. Fetch/stop/resume then
  ready-preview passed. Shares 2:1 reduced assigned bytes to **673,732,608 B**;
  **18 prior cache keys / 228,261,888 B** were listed retained, never deleted.
  Existing peer all-model RPC cache total was **23,474,650,624 B**; do not call
  this one model's size or claim existing full GGUF copies were deleted.

### GGUF: first native split check, before own-file launcher/rate fixes

Equal shares, isolated lead 8196, RPC 5596 reached over SSH tunnel 5606.
Answers were "Two plus two is four." Native llama.cpp rates are used below;
the old UI inflated short-run decode and warm-prefill speeds, now fixed.
`prompt_ms` is prefill time, **not end-to-end streaming TTFT**.

| Artifact `.json` | Prompt / cached | New tokens | Native prefill ms | Native read tok/s | Native write tok/s |
|---|---:|---:|---:|---:|---:|
| `gguf-quality-cold` | 38/0 | 7 | 146.569 | 259.26 | 38.75 |
| `gguf-quality-warm` | 38/37 | 7 | 24.482 | 40.85 | 42.47 |
| `gguf-after-web-restart` | 38/37 | 7 | 25.122 | 39.81 | 40.47 |

Initial load: **12.094 s**, including **5.8 s** optional legacy full-peer-GGUF
seed scan (55 already-cached tensors, 940,038,144 B with one padded layer).
Interface en2 counters around load: **1,368,325 B received / 91,684,706 B sent**.
These are aggregate Thunderbolt-interface counters including SSH, probes,
small tensors and any background traffic, not exact model bytes or a controlled
cold-cache comparison. The complete legacy peer GGUF already existed and was
left untouched. Web restart kept lead/RPC/tunnel PIDs unchanged and returned a
complete shutdown JSON response. See the later verified-own-cache reload below.


### GGUF: verified peer-only cache reload after fixes

`76d3c44`, same equal shares/model/ports. Fresh Balance verified the exact
assigned peer cache, then runtime skipped the full-peer-GGUF scan and padded
legacy seed (`file_mode=balance-verified-peer-cache`, no `seed` metadata).
Reload **5.951 s**; aggregate en2 counters **1,376,105 B received / 91,657,390 B
sent**. Compared with the earlier 12.094 s observation this removes the 5.8 s
optional scan; these are single warm-cache observations, not a median or a
controlled cold-cache speedup. The lead still opens its full GGUF.

| Artifact `.json` | Prompt / cached | New tokens | Native prefill ms | Native read tok/s | Native write tok/s | Total telemetry s |
|---|---:|---:|---:|---:|---:|---:|
| `gguf-own-cache-cold` | 38/0 | 7 | 136.771 | 277.84 | 40.00 | .2868 |
| `gguf-own-cache-warm` | 38/37 | 7 | 24.279 | 41.19 | 44.30 | .1597 |
| `gguf-own-cache-after-web-restart` | 38/37 | 7 | 33.782 | 29.60 | 40.04 | .1836 |

UI rates were asserted equal to the native values for every post-fix reply.
Representative actual llama.cpp log lines (relative log clock, not wall time):

```text
slot print_timing: prompt eval time = 136.77 ms / 38 tokens (3.60 ms per token, 277.84 tokens per second)
slot print_timing:        eval time = 150.00 ms / 7 tokens (25.00 ms per token, 40.00 tokens per second)
slot print_timing: prompt eval time = 24.28 ms / 1 tokens (24.28 ms per token, 41.19 tokens per second)
slot print_timing:        eval time = 135.45 ms / 7 tokens (22.57 ms per token, 44.30 tokens per second)
```

Web-only restart preserved lead/RPC/SSH-tunnel PIDs and cache. All isolated
GGUF/MLX/web/RPC/tunnel/service processes were then stopped by ownership; the
original Qwen 27B 24/40 split remained healthy, worker PIDs unchanged.
Remaining: three physical Minis, multi-shard MLX live savings, fresh install /
permanent login/reboot, cold-cache GGUF comparison and sustained benchmarks.


## Day 19 follow-up install/service measurements — 2026-11-08, 18:08–18:18 CST

These are **installation/readiness observations, not inference benchmarks**.
Original Qwen 27B 24/40 split and normal web PIDs stayed unchanged throughout.
Noninteractive sudo required a password, so the approved clean equivalent used
EXO1's existing GUI user with a fresh isolated HOME/clone/venv/config/deps.
A truly separate account, FileVault/permissions and reboot remain untested.

| Native run | Installer exit s | UI verified s | Result |
|---|---:|---:|---|
| Fresh install, b1e5410 | 95.897 | 96.189 | new web 73454 on 8197, idle, local-only config |
| Identical repeat | 1.441 | 1.449 | same PID, config and venv |
| Updated repeat, a59760c | — | 1.552 | same PID; selected-port message corrected |
| Isolated staged web activation | — | .135 | real launchctl load/status/log, no model |
| Isolated staged web restart | — | .132 | real owned restart, then uninstall/cleanup |

Fresh imports/pip check: Python 3.14.7 arm64, MLX 0.32.4, mlx-lm 0.32.2,
huggingface_hub 2.4.0, gguf 0.19.0. Dependencies are not fully locked; these are
the versions resolved for this actual run. HTML response 159,019 bytes. Exact
results/versions/install and native staged-web logs are retained on EXO1 under
`~/.caravan/day19-fresh-20261108-1808`; temporary HOME/clone/venv/jobs removed.

Three real permanent login plists were installed and linted, **not loaded**:
EXO1 web + Qwen lead; EXO2 Qwen packer. Explicit next-login staging preserves
today's original unmanaged web/model and guards ownership once launchd loads
the jobs. No production startup/reboot timing is claimed. Reboot/logout was
explicitly forbidden for this run; exact downtime and approval-gated steps are
in DAY19.md. Follow-up code suite: **673 passed, 39.892 s** (ten new tests).


## Day 19 actual reboot recovery — 2026-11-08, 18:22–18:40 CST

Two existing 24 GiB M4 Minis, automatic login `brenden` already enabled and
FileVault already off. Post-reboot `pmset -g` read `lowpowermode 0` on both. System Events restart was noninteractive; no login,
security or network settings changed. These are **single observed upper bounds
including polling**, not medians or cold-boot throughput claims.

| Restart run | SSH + GUI s | launchd loaded s | Web ready s | Qwen stage ready s |
|---|---:|---:|---:|---:|
| EXO2 original fixed-IP plan | ~60.5 | ~60.5 | n/a | failed; no model by 300 |
| EXO2 retry with explicit TB interface | 40.105 | 40.105 | n/a | 48.533 packer |
| EXO1 with dynamic TB peer | 42.960 | 42.960 | 42.960 | 59.815 lead/split |

Original EXO2 TB IPv4 changed `169.254.103.191` → `169.254.35.180`; the old
saved bind failed safely. After recovery/code fix, a second real reboot changed
it again to **169.254.201.113**, automatically resolved by the explicit en2
service plans. The first ~60.5 s observation has a probe gap/whole-second start
stamp after an expected disconnect timeout; it is not precise boot timing.

Model: `mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit`,
**24 packer / 40 lead layers**, no-think, temperature 0, max 32 tokens.
Prompt: “What is two plus two? Answer in one short sentence.” All four checks
answered **“Two plus two equals four.”** Decode below uses the actual native
`(completion_tokens - 1)/(total - TTFT)`; read counts **uncached** prompt tokens.

| Artifact / check | Prompt / cached | Answer tokens | Prefill s | TTFT s | Total native s | Native read tok/s | Native write tok/s | Request wall s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `first-reply.json`, post-reboot cold | 26/0 | 6 | .521 | .801 | 1.722 | 49.9 | 5.43 | 1.7794 |
| `post-fix-checks.json`, restored after deployment | 26/25 | 6 | .094 | .397 | 1.389 | 10.6 | 5.04 | 1.4432 |
| same, after owned lead restart (hit-disk) | 26/25 | 6 | .101 | .403 | 1.396 | 9.9 | 5.04 | 1.4630 |
| same, after web-only restart (hit-memory) | 26/25 | 6 | .038 | .349 | 1.346 | 26.3 | 5.02 | 1.3878 |

First correct reply observed **79.569 s after EXO1's restart request**, prompt
sent at 77.790 s after inspection; not a minimum time-to-answer measurement.
That was **140.649 s after EXO2's retry request**, including EXO1's later reboot.
Short six-token answers, cache state and other resident login apps make these
correctness/recovery observations, not a sustained throughput comparison.

Actual timing-log lines, clock **CST**:

```text
18:32:00 [mlx-worker] session 7e246f9658244905: timing (split): read 26 tok (0 cached) at 49.9 tok/s, write 6 tok at 5.43 tok/s, first token 0.80 s, total 1.72 s
18:39:07 [mlx-worker] session 7e246f9658244905: timing (split): read 26 tok (25 cached) at 9.9 tok/s, write 6 tok at 5.04 tok/s, first token 0.40 s, total 1.40 s
18:39:10 [mlx-worker] session 7e246f9658244905: timing (split): read 26 tok (25 cached) at 26.3 tok/s, write 6 tok at 5.02 tok/s, first token 0.35 s, total 1.35 s
```

The original cold reply's old UI erroneously showed 6.51 write tok/s vs native
5.43. Fixed MLX structured usage and web display now match the log; all three
post-fix native/UI comparisons passed. Read rates no longer count cached tokens
as newly read. Earlier MLX historical UI-rate table is labeled accordingly.

Native loaded-lead CLI restart reproduced bootstrap error 5 and safely waited
for job removal before successful bootstrap: **6.041 s** to ready. No sudo/root
escalation or unknown-port/PID kill. Web-only restart **1.190 s** to ready,
KEEP_WORKERS=1, lead **2490** and packer **1037** unchanged; next reply hit memory.
Network web HTML: HTTP 200 / 159,019 bytes. Topology: 2/2 online. Unchanged
24/40 Balance preview: safe/ready, zero downloads, logical per-node bytes
EXO2 **10,717,679,207**, EXO1 **10,731,498,067**. No weights fetched/deleted.

Reboot fix commits **4c4e128**, **4cb8951**, **1479fcf**; final full suite
**694 passed in 40.143 s**. Permanent launchd web/lead/packer left running Qwen;
no temporary test listeners/downloads remained. Raw results and native job/PID
snapshots: Omarchy `~/day19-reboot-20261108/`; EXO1 replies:
`~/.caravan/day19-reboot-20261108/`; runtime logs under each Mini's
`~/.caravan/logs`. Full failure/recovery/operating-mode notes: DAY19.md.
Separate-account/FileVault-on and three-physical-Mini coverage remain untested.


## Day 19 revised web-owned last-model mode — Nov 8, 19:05–19:12 CST

Code **e0928ad**, same two 24 GB M4 Minis/model as the fixed-service checks,
but **both fixed Qwen worker jobs removed**. Web-only launchd with KEEP_WORKERS;
normal web/UI API owns the stages. Qwen3.5-27B MLX 4bit, exact split
EXO2 layers0–23 / EXO1 layers24–63, counts24/40, no downloads. Settings: no
self-tune, helper, lookup or shared start; one pipeline chat; KV16; UI fused
and keepalive Auto (actual fused off / keepalive on). Load-to-ready **10.121 s**.

| Check | Prompt / cached | Output | Prefill s | TTFT s | Native total s | Read tok/s | Write tok/s | Request wall s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `migrated-qwen-answer` | 26 / 0 | 6 | .522 | .802 | 1.720 | 49.8 | 5.45 | 1.7471 |

Correct answer: “Two plus two equals four.” Native/UI rates identical; peak
lead allocation9.51GB. Six-token correctness smoke, **not sustained throughput**.
Native log at **19:05:56 CST**:

```text
timing (split): read 26 tok (0 cached) at 49.8 tok/s, write 6 tok at 5.45 tok/s, first token 0.80 s, total 1.72 s
```

**New-mode reboot test did not complete.** EXO2 restart was requested at
**19:05:56.320 CST**, existing automatic login brenden / FileVault Off,
System Events returned0. No SSH return observed in the360s monitor; still
SSH exit255 / connection timed out at19:12:33 CST. Therefore SSH-up,
GUI/TB-ready, restored-model and first-reply times are **unavailable**, not zero
or the old fixed-model figures. EXO1 was **not rebooted**. Final local web/lead
were alive but remote split status failed; no claim of a healthy final split.
Saved Qwen24/40 intent remains for recovery. No reboot/security/network changes
beyond that one approved EXO2 restart request. Brenden must check EXO2 locally
before the remaining reboot/switch/unload tests can resume. See the exact
recovery checklist and raw artifact locations in [DAY19.md](DAY19.md).

Box final validation: **738 tests, 44.459 s**. Native model switching to Orvena,
future-request replay and empty-selection restart remain deferred in this mode;
unit/shared-HTTP coverage is not presented as a native reboot result.
