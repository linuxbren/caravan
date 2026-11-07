# Idea 5: uneven layer split (`--split-packer-layers`)

- **Date:** Sat Oct 31 2026, 8:16–8:32 PM CDT
- **Goal:** Move the cut so Packer 1 gets +1 or +2 layers vs the default even split, for 4-bit Gemma 4, GPT-OSS, and Qwen3. Expectation (from the LPM-off rerun): the packer half was 2–4 ms faster than the lead on Gemma 4 and GPT-OSS (16.4 vs 18.5, 16.0 vs 20.3 ms/token), 0.4 ms on Qwen3, so giving the packer a layer or two more should balance the halves. ROADMAP called this a small win on its own and more important once idea 1 (several chats at once) makes the slower half set the pace.
- **Hardware:** EXO1 = lead (`prf-hays-exo01`), EXO2 = Packer 1 (`prf-hays-exo02`). Both Mac mini M4 24 GB, Thunderbolt 4 cable. `pmset -g lowpowermode 0` on both before every run.
- **Software + commit:** `caravan-v3-mlx-split` at `845216b` (handoff tip; same speed code as v3.1 / `f68d15e` / `0e9f1df`) on EXO1 `~/dev/caravan-v3` and EXO2 `~/cv3`. MLX 0.32.4 / mlx-lm 0.32.2 venv. Flag `--split-packer-layers K` (alias `--split-front-layers`) exists and works on both lead and packer; hello handshake rejects a mismatched cut.
- **Config:** Same as the Oct 31 LPM-off rerun (`handoff/tools/rerun.sh` / `docs/BENCHMARKS.md`): packer on `169.254.104.38:5560`, lead on test port `8194`, worker defaults (4 sessions, 2 GB, prefill step 2048, 16-bit cache, save on). Models 4-bit from EXO1 `~/.exo/models/...` and EXO2 `~/.caravan/mlx-models/...`. Client: `bench/v3/split_client.py bench` (warm, tg128 ×2, pp512 ×2, pp4096 ×2, quality 3/3). Medians of 2 runs. Output: `~/.caravan/bench-2026-10-31/idea5-uneven/` on both Minis (caches + lead/packer logs + `*.jsonl` + `*.split-after-bench.json`).
- **Cuts tried:**

  | Model (layers) | even (default) | +1 | +2 |
  |---|---|---|---|
  | Gemma 4 26B (30) | K=15 | K=16 | K=17 |
  | GPT-OSS 20B (24) | K=12 | K=13 | K=14 |
  | Qwen3 30B-A3B (48) | K=24 | K=25 | K=26 |

## Results

Writing / reading tok/s are medians of 2 runs. Peak memory = busier Mac from `/caravan/split` after the bench. TTFT = median wait before first word on the tg128 requests (short prompt). Quality 3/3 on every run. Half timings = median over the two tg128 runs, same formulas as BENCHMARKS (packer = front_s/calls; cable = (wait−front)/calls; lead = (write_s − wait)/tokens).

### vs v3 LPM-off baseline (even split, earlier tonight)

| Model | baseline write | this session even write | baseline read 512/4k | this session even 512/4k |
|---|---:|---:|---|---|
| Qwen3 | 30.4 | 30.0 | 451 / 408 | 450.5 / 406.9 |
| Gemma 4 | 27.7 | 27.6 | 411 / 375 | 411.6 / 374.3 |
| GPT-OSS | 26.6 | 26.8 | 440 / 424 | 442.1 / 425.4 |

Even-split numbers match the baseline within noise.

### Idea 5 table (this session)

| Model | K (packer layers) | Writing (tok/s) | Reading 512 / 4k (tok/s) | Wait before first word, tg128 (s) | Peak mem lead / packer (GB) | Weights lead / packer (GB) | packer / cable / lead (ms/tok) | Quality |
|---|---:|---:|---|---:|---|---|---|---|
| Gemma 4 | **15 (even)** | **27.6** | 411.6 / 374.3 | 0.400 | 9.09 / 9.07 | 6.90 / 6.89 | 16.7 / 0.82 / 17.9 | 3/3 |
| Gemma 4 | 16 (+1) | 27.4 | 412.6 / 374.9 | 0.398 | 8.58 / 9.58 | 6.44 / 7.35 | 17.8 / 0.82 / 17.0 | 3/3 |
| Gemma 4 | 17 (+2) | 27.4 | 412.8 / 375.9 | 0.407 | 8.07 / 10.09 | 5.98 / 7.80 | 18.6 / 0.85 / 16.1 | 3/3 |
| GPT-OSS | **12 (even)** | **26.8** | 442.1 / 425.4 | 0.383 | 6.94 / 6.94 | 5.42 / 5.42 | 16.0 / 0.85 / 19.7 | 3/3 |
| GPT-OSS | 13 (+1) | 26.6 | 439.3 / 426.6 | 0.381 | 6.48 / 7.40 | 4.97 / 5.87 | 17.4 / 0.85 / 18.5 | 3/3 |
| GPT-OSS | 14 (+2) | 26.7 | 439.6 / 431.9 | 0.385 | 6.00 / 7.87 | 4.52 / 6.33 | 18.5 / 0.83 / 17.2 | 3/3 |
| Qwen3 | 24 (even) | 30.0 | 450.5 / 406.9 | 0.373 | 10.01 / 10.02 | 8.41 / 8.41 | 16.1 / 0.76 / 15.6 | 3/3 |
| Qwen3 | 25 (+1) | 30.2 | 449.6 / 410.6 | 0.370 | 9.63 / 10.40 | 8.06 / 8.76 | 16.7 / 0.77 / 14.7 | 3/3 |
| Qwen3 | **26 (+2)** | **30.5** | 450.8 / 412.1 | 0.358 | 9.25 / 10.78 | 7.71 / 9.11 | 17.1 / 0.77 / 14.1 | 3/3 |

Raw tg128 writing (tok/s): Gemma 27.6/27.6, 27.6/27.1, 27.5/27.3; GPT-OSS 26.8/26.8, 26.6/26.5, 26.7/26.7; Qwen3 29.9/30.1, 30.2/30.3, 30.6/30.3.

## Takeaway

- **Single-chat writing did not meaningfully improve** on Gemma 4 or GPT-OSS. The pipeline is serial (packer then lead then sample), so moving a layer shifts ms from one half to the other and the sum stays about the same (~35.5 ms Gemma, ~36.6 ms GPT-OSS → ~28 / ~27 tok/s). That matches ROADMAP's note that idea 5 is a small win alone and matters most with idea 1 (several chats), where the slower half sets the pace.
- **Best balanced cut** (prep for idea 1), by half-timing gap:
  - **Gemma 4: K=16** (17.8 vs 17.0 ms, was 16.7 vs 17.9)
  - **GPT-OSS: K=13** (17.4 vs 18.5, was 16.0 vs 19.7); K=14 overshoots
  - **Qwen3: K=24 (even)** already balanced (16.1 vs 15.6); K=26 was the fastest write in this session (30.5) but widens the gap the other way
- **Reading** stayed flat across cuts (within ~1–2% / day noise). Memory shifted as expected: packer peak rose and lead peak fell as K grew. Quality 3/3 everywhere. Nothing broke; workers stopped cleanly; test ports 8194/5560 clear after.
- Flag works. No code changes made.

## Deficiencies

- Only 2 runs per cut (same as the LPM-off rerun), so sub-1% writing moves are noise.
- Half timings mix a few prefill calls into the per-call averages (133 calls for 127 write tokens); same method as the LPM-off table, good enough to rank cuts.
- Did not re-run 4k/16k chat or restart resume under uneven cuts.
- Did not try K that favors the lead (fewer packer layers); not needed given the measured direction.

## Would be faster / more robust if

- Idea 1 (several chats at once) used these balanced cuts so both Minis stay busy; then the slower-half gap is the thing that matters.
- Bench scripts refused to start when `lowpowermode 1` on either Mac (parked housekeeping).
- A tiny auto-probe picked K from a 32-token write of each half's ms before a long session.

## Post status

not drafted

## Cleanup

All test workers stopped. Confirmed `pgrep mlx_worker` empty and ports 8194 / 5560 free on both Minis after the last run. Production ports and exo/Hermes/Talaria Hub untouched.
