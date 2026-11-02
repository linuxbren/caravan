## 2026-11-01 — Day 9: ROADMAP #13(a) auto-pick split + pipeline

**Goal.** When flags are omitted, `mlx_worker` auto-picks (1) pipeline chat
count from free memory / model+KV size (cap 2 on 24 GB Minis; never risk
swap) and (2) lead/packer layer cut from each Mini's detected memory and
layer sizes (packer reports `mem_total_gb` in hello). Explicit flags win.
One plain startup log line each. Unit tests. Mini-verify auto vs hand-tuned
across ≥ Qwen3, Llama 3.1 8B, Qwen2.5 14B (ports 8194/5560, LPM off,
warm-up, medians ≥2, quality 3/3). Update ROADMAP / METHODOLOGY /
BENCHMARKS / this log. Commit on Omarchy as linuxbren noreply; sync all
copies; stop test workers. No video / no push / no tag.

**Hardware.** EXO1 lead + EXO2 packer, Thunderbolt `169.254.104.38:5560`,
LPM off both (`lowpowermode 0`).

**Software.** Branch `caravan-v3-mlx-split`. New helpers
`choose_packer_layers` / `choose_pipeline_chats` / `host_memory_gb` /
`read_n_layers` in `agent/mlx_split.py`; wire-up + hello mem fields +
startup logs in `agent/mlx_worker.py`. Driver
`handoff/lab/day9_driver.sh`. MLX 0.32.4 / mlx-lm 0.32.2. Test ports only.

**Auto picks:**

| model | K | pipeline | why |
|---|---:|---:|---|
| Qwen3-30B-A3B-4bit | 24 | 2 | equal RAM ~26/26; balanced 48-layer qwen3_moe / headroom 3.0 GB after ~8.4 GB weights |
| Llama-3.1-8B-Instruct-4bit | 16 | 2 | equal RAM; balanced 32-layer llama / headroom 7.9 GB after ~2.0 GB |
| Qwen2.5-14B-Instruct-4bit | 24 | 2 | equal RAM; balanced 48-layer qwen2 / headroom 3.9 GB after ~3.7 GB |

Hand-tuned targets were identical (K24/N2, K16/N2, K24/N2).

**Results (medians of 2; quality 3/3 every suite; no failures):**

| model | mode | tg128 write | pp512 | pp4096 | pipe N=2 wall |
|---|---|---:|---:|---:|---:|
| Qwen3 | auto | 45.0 | 462.2 | 429.0 | 68.3 |
| Qwen3 | tuned | 45.0 | 461.9 | 429.0 | 68.8 |
| Llama | auto | 22.5 | 242.8 | 228.9 | 37.3 |
| Llama | tuned | 22.6 | 243.2 | 229.7 | 38.2 |
| Qwen2.5 | auto | 12.4 | 122.8 | 118.5 | 20.9 |
| Qwen2.5 | tuned | 12.4 | 123.2 | 117.4 | 18.9 |

Auto matched or beat tuned (Qwen2.5 pipe wall auto > tuned). Unit tests:
**133** pass (`AutoTuneTest` covers equal-RAM idea-5 cuts, memory skew,
pipeline cap-at-2 / never-3, host_memory). Raw
`~/.caravan/bench-2026-11-01/day9-autotune/{qwen3,llama,qwen25}-{auto,tuned}/`.

**What broke.** None on the six lead suites. (Earlier: CloudAgent unavailable
on the executor → implemented on existing checkouts; Qwen3 4-bit path on
EXO1 is under `~/.exo/models/…`.)

**Fix / next.** ROADMAP #13(b) learn-per-model; #13(c) optional
`~/.caravan/config.toml`. Day 9 video not made yet (Brenden: don't make it
yet).

**Post status.** Not drafted; not posted. No push / no tag.

## 2026-11-01 — Day 8 full scoreboard video (v15)

**Goal.** Redo Day 8 lab video as v15 covering **all** local models Mini-tested,
using only documented numbers from `docs/BENCHMARKS.md`. Keep v14 as a
superseded draft. Show helper before/after for every model, plus non-helper
gains since Day 7 (keepalive off/on; several-chats wall N=1/2/3). Mention the
12-family helper map, live download-prompt tests, and planned "fewer flags".

**Hardware / software.** Same Minis / same benches already logged. Video
`handoff/lab/videos/make_runtime_video_v15.py`, data `v15_data.json`, out
`2026-11-01_caravan-v3-day8-full-scoreboard_v15.mp4` (+ `/workspace/out/v15.mp4`).
Duration **1:24**. Payoff in first 3s + burned-in captions. Stills in
`stills_v15/`. Audience: techie friend new to local-AI lingo (gloss, never
announce teaching).

**Scoreboard numbers used (all from BENCHMARKS / matching METHODOLOGY):**

Helper off → auto-pair on (count / best documented):
| model | off | on | helper |
|---|---:|---:|---|
| Qwen3 30B-A3B | 45.9 | 59.7 | 0.6B |
| Gemma 4 26B | 38.4 | 44.5 | 270M |
| GPT-OSS 20B | 34.3 | skip | none |
| Llama 3.1 8B | 22.7 | 51.5 | 1B |
| Qwen2.5 14B | 12.4 | 33.8 | 0.5B |
| Distill-Qwen 14B | 12.3 | 16.9 | 0.5B (shared) |

Keepalive writing off → on: Qwen3 30.4→45.6; Gemma 27.7→38.3; GPT-OSS
26.6→34.1; Llama 21.2→22.8; Qwen2.5 11.7→12.3; Distill 11.7→12.4.

Pipeline wall aggregate N=1 / 2 / 3: Qwen3 44.4/72.7/70.8; Gemma 37.0/61.0/59.8;
GPT-OSS 33.5/54.0/53.0; Llama 22.5/39.3/39.0; Qwen2.5 12.3/21.7/21.5; Distill
12.2/21.5/21.6.

Also on screen: 12-family map (8 pairings + 4 skips in `guessers.json` /
METHODOLOGY table); download prompts 335 / 663 / 278 MB yes→remembered; next
item ROADMAP "Fewer flags: self-tuning defaults + settings file".

**Post status.** Video ready; Day 8 X draft still the earlier Llama-led draft
unless Brenden wants a rewrite for the full scoreboard. Not posted.

## 2026-11-01 — Day 8 Llama 8B video (v14, superseded by v15) + X draft

**Goal.** Ship Day 8 lab video (payoff-first + burn-in captions) and X draft.
Headline is the Llama 3.1 8B Mini suite / guess-ahead win; same day also
Mini-verified Qwen2.5 14B and Distill-Qwen 14B on the shared 0.5B helper.
Post shape: line 1 = headline result/number; line 2 = full Day N opener.

**Hardware / software.** Same Minis. Video
`handoff/lab/videos/make_runtime_video_v14.py`, data `v14_data.json`, out
`2026-11-01_caravan-v3-llama8b-guess-ahead_v14.mp4` (+ `/workspace/out/v14.mp4`).
Duration **0:54**. Payoff in first 3s + burned-in captions. Stills in
`stills_v14/`. **Superseded by v15** (full six-model scoreboard); v14 kept as draft.

**Results.** Llama nodraft count **22.7** → auto-pair **51.5** (suite 51.5 /
51.6 / 64.7 / 46.8; accept ~0.75; q 3/3; range ~47–65). Qwen2.5 14B **12.4 →
33.8**; Distill-Qwen 14B **12.3 → 16.9** (same 0.5B helper). Both kept
`mini_verified`. ROADMAP also gained planned item "Fewer flags…".

**Post status.** drafted (not posted). Aim ~6 PM Central. Final Day 8 X draft:

---
The 8B model now writes 2–3× faster (~22 → 47–65 tokens/sec) thanks to a tiny 1B helper.

Day 8 of building Caravan in the open, my homebrew app for running AI models across my Mac minis.

Guess-ahead: a small same-family helper on the lead Mini drafts the next few word pieces; the big model, split across both Minis, checks them in one Thunderbolt trip. Llama 3.1 8B went 22.7 → 51.5 on the count prompt (edit hit 64.7). Quality stayed 3/3.

Same day we also Mini-verified Qwen2.5 14B (12.4 → 33.8) and Distill-Qwen 14B (12.3 → 16.9) on one shared 0.5B helper.

What's your best local speedup trick — helper model, quant, or something else?
---


## 2026-11-01 — Qwen2.5 14B + Distill-Qwen 14B full Mini suites

**Goal.** Run both through every prior Mini test class (keepalive, pipeline
N=1/2/3, guess-ahead nodraft vs auto-pair, first-load gate, shut-off,
download prompt). Shared draft Qwen2.5-0.5B-Instruct-4bit (278 MB). Decide
keep vs skip for `qwen25` and `deepseek-r1-distill-qwen`.

**Hardware.** EXO1 lead / EXO2 packer, M4 24 GB, Thunderbolt 4. LPM off.
Test ports 8194 / 5560. Even cut K=24. Models ~8 GB class each on both
Minis.

**Software.** Branch tip after `1c10c5f`. Clients `split_client.py`,
`pipeline_bench.py`, `speculate_bench.py`. Raw
`~/.caravan/bench-2026-11-01/qwen25-suite/` and `distill-suite/`.

**Qwen2.5-14B-Instruct-4bit (America/Chicago ~16:16–16:37 + dl 17:23).**

| test | result |
|---|---|
| keepalive off / on write | **11.7** / **12.3** (read 120.8/117.9 → 122.9/118.4; q 3/3) |
| pipeline wall_agg N1 / N2 / N3 | **12.3** / **21.7** / **21.5** (max TTFT ≤1.13 s) |
| nodraft count/repeat/edit/cont | **12.4 / 12.0 / 11.4 / 12.2** |
| auto-pair same | **33.8 / 37.1 / 46.4 / 35.9** (accept ~0.73; q 3/3) |
| first-load gate | keep=1; baseline **10.49** / spec **24.73**; be≈0.45 |
| shut-off (be=0.80) | disabled (`0.729 < 0.80`) |
| download prompt | `A 278 MB helper…` yes → download; draft restored |

**DeepSeek-R1-Distill-Qwen-14B-4bit (~16:42–17:17 + dl 17:21).**

| test | result |
|---|---|
| keepalive off / on write | **11.7** / **12.4** (read 122.7/117.9 → 125.1/118.0; q 3/3) |
| pipeline wall_agg N1 / N2 / N3 | **12.2** / **21.5** / **21.6** (max TTFT ≤0.98 s) |
| nodraft count/repeat/edit/cont | **12.3 / 12.4 / 12.4 / 12.4** |
| auto-pair same | **16.9 / 17.4 / 17.9 / 21.2** (accept ~0.45; q 3/3) |
| first-load gate | keep=1; baseline **11.17** / spec **13.98**; be≈0.255 |
| shut-off (be=0.80) | disabled (`0.542 < 0.80`) |
| download prompt | `A 278 MB helper…` yes → download; draft restored |

**Takeaway.** Keep both pairings (`mini_verified`). Qwen2.5 Instruct gets a
Llama-class relative lift on this smaller dense 14B (~+173% count). Distill
gains less (~+37%) with lower accept (~0.45) on reasoning-heavy replies, but
still clears the gate. Pipeline tops out at two chats for both.

**Post status.** folded into Day 8 draft above (not posted).



## 2026-11-01 — Llama 3.1 8B full Mini suite (every prior test class)

**Goal.** Run Meta-Llama-3.1-8B-Instruct-4bit through every prior Mini test
class (split keepalive A/B, pipeline N=1/2/3 wall + TTFT, guess-ahead
nodraft vs auto-pair suite, first-load gate, shut-off, download prompt) and
document beside Qwen3 / Gemma / GPT-OSS. Decide keep vs skip for `llama3`
in `guessers.json`.

**Hardware.** EXO1 lead / EXO2 packer, Mac mini M4 24 GB, Thunderbolt 4.
LPM off. Test ports 8194 / 5560. Model ~4.2 GB both Minis; draft
Llama-3.2-1B-Instruct-4bit ~680 MB on lead. Even cut K=16.

**Software.** Branch `caravan-v3-mlx-split` tip after `b9bec26`. Clients
`split_client.py`, `pipeline_bench.py`, `speculate_bench.py` (denom>0
guard). Raw `~/.caravan/bench-2026-11-01/llama-suite/`.

**Results (America/Chicago ~14:08–14:32).**

| test | result |
|---|---|
| keepalive off / on write | **21.2** / **22.8** (read 243.0/227.7 → 243.9/229.5; q 3/3) |
| pipeline wall_agg N1 / N2 / N3 | **22.5** / **39.3** / **39.0** (max TTFT ≤0.60 s) |
| nodraft count/repeat/edit/cont | **22.7 / 22.0 / 20.7 / 22.2** |
| auto-pair same | **51.5 / 51.6 / 64.7 / 46.8** (accept ~0.75; q 3/3) |
| first-load gate | keep=1; baseline **19.29** / spec **35.87**; be≈0.45; q 3/3 |
| shut-off (be=0.80, no skip-first-load) | disabled (`0.688 < 0.80`) |
| download prompt | `A 663 MB helper…` yes → download; draft restored |

**Takeaway.** Keep Llama pairing (`mini_verified`). Strongest count lift so
far on the Minis (~+127%). Pipeline pattern matches larger MoEs (~1.7× at
N=2; N=3 wall ≈ N=2). Keepalive gain small on this lighter 8B (already less
Metal cool-down than 30B-class).

**Post status.** drafted via Day 8 video/X entry (not posted).

## 2026-11-01 — download-prompt wild test + top-10 family map

**Goal.** Live-test the guesser download ask on EXO1 (move caches aside, no
delete of originals); map top open LLM families to small same-vocab drafts.

**Prompt test (America/Chicago ~13:24–13:26).** Test ports 8194/5560 only.
Moved Qwen3-0.6B HF/draft aside; cleared state answers. Yes path: size prompt
335 MB → download → gate keep baseline **36.98** / spec **40.71**; reload
auto-pair remembered yes. No path: decline → baseline; reload remembered no.
Restored `.bak` + original state (2318 B). Production not stopped.

**Family map.** See `agent/guessers.json` + METHODOLOGY table. Mini-verified:
Qwen3, Gemma4, Llama3, Qwen2.5, Distill-Qwen (see suite entries). Vocab-checked: Gemma3, Gemma2,
SmolLM. Skips: GPT-OSS, Mistral, Phi-4, native DeepSeek. Tests: 22.

# Brenden's Mac Mini LLM Lab — Experiment Log

Each entry: date, goal, hardware, software/runtime, model + quant, config, results (tok/s, memory, quality), what broke, fix/next step, post status.

<!-- entries below, newest first -->


## 2026-11-01 — Day 7 guess-ahead video (v13) + X draft + Gemma quality gate

**Goal.** Tighten the first-load quality matcher so Gemma cannot pass by matching "4"/"Paris"/"Cold" inside `<|channel>thought` text; score only the final answer after the `<channel|>` closer. Ship Day 7 lab video + X draft for guess-ahead auto-pair. Docs: ROADMAP, METHODOLOGY, LOG, CHANGELOG, guessers.json.

**Hardware.** EXO1 lead / EXO2 packer, Mac mini M4 24 GB, Thunderbolt 4. LPM off (`pmset` 0). Keepalive on. Test ports 8194 / 5560.

**Software.** `guess_ahead.final_answer_text` + stricter `answer_ok`; gate `max_tokens` 256; 20 unit tests. Video `handoff/lab/videos/make_runtime_video_v13.py`, data `v13_data.json`, out `2026-11-01_caravan-v3-guess-ahead_v13.mp4` (+ `/workspace/out/v13.mp4`). Duration **1:02**.

**Results (America/Chicago ~12:34–12:36).** First-load Gemma keep=1, quality **3/3** (thought no longer scores; closer segment does). Autopair write median **44.3**; nodraft **38.4**. Prior auto-pair table still stands: Qwen 45.9→**59.7**, Gemma 38.4→**44.5**, GPT-OSS skip **34.3**; shut-off `0.438 < 0.80`. Raw: `~/.caravan/bench-2026-11-01/guess-ahead/` and `guess-ahead-strict/`.

**Takeaway.** Matcher bug fixed without killing the Gemma draft pair. Milestone/tag still waiting on Brenden's push go.

**Post status.** drafted (not posted). Final Day 7 X draft:

---
Day 7 of building Caravan in the open, my homebrew app for running AI models across my Mac minis.

Idea 3 is guess-ahead: a small helper model on the lead Mini drafts the next few tokens, then one Thunderbolt round trip checks them on the full split model. Same-family pairing only (vocab has to line up). Caravan asks once before downloading a helper and remembers the answer.

Measured writing speed (tokens/sec, medians of 2, Low Power Mode off): Qwen3 45.9→59.7 with a 0.6B draft, Gemma 38.4→44.5 with a 270M draft. GPT-OSS has no small same-vocab helper yet, so we skip it and stay at 34.3.

The first-load quality gate now scores only the final answer — Gemma's thinking channel used to leak matches. Mid-chat shut-off still kills guessing when accepts drop below break-even (we saw 0.438 < 0.80 on a nasty prompt).
---



## 2026-11-01 — Day 6 several chats video (v12) + X draft

**Goal.** Lab video for idea 1 (several chats on the two-Mini split) in a techie-friend voice: explain the layer split and pipeline crisply, no "we're teaching" framing, no elementary token definition, no lab shorthand (tg128 / TTFT / N=). Same measured numbers as the stall-fix benches.

**Hardware / software.** Same as idea 1 benches. Video script `handoff/lab/videos/make_runtime_video_v12.py`, data `v12_data.json`, ID LAB-2026-11-01-03. Duration 1:03. v10 (jargon) and v11 (beginner) kept, superseded, not posted.

**Post status.** drafted (not posted). Final Day 6 X draft:

---
Day 6 of building Caravan in the open, my homebrew app for running AI models across my Mac minis.

The model is split in half, one half on each Mini. With one chat, they take turns, so each GPU sits idle about half the time.

Now Caravan runs two chats overlapped: while one Mini works on chat A, the other works on chat B. Total writing speed across chats is up ~1.6× (Qwen3 44→73, Gemma 37→61, GPT-OSS 34→54 tokens/sec).

A third chat used to wait ~4s before its first word. A fairer turn order cut that to ~0.6s.

A single chat on its own isn't faster, and quality checks all passed. Next up: guessing ahead.
---


## 2026-11-01 — Idea 1 N=3 stall fix (fair packer pick)

**Goal.** Fix the third-chat starvation under `--split-pipeline-chats 3`: one chat waited ~4 s before the first word while the scheduler kept feeding the chats that already had work.

**Hardware.** EXO1 lead / EXO2 packer, Mac mini M4 24 GB, Thunderbolt 4. LPM off. Keepalive on.

**Software.** Branch `caravan-v3-mlx-split`, fix `ef244c6` (`_pipe_round` fair pick by `(n_gen, t0)` + admit one prefill per loop). Bench `bench/v3/pipeline_bench.py`. Idea-5 cuts for pipeline runs.

**Results (America/Chicago ~01:25–01:36).** Flag-off writing 38.1 / 34.2 / 45.7. Pipeline N=2 wall 61.0 / 54.0 / 72.7. N=3 wall 59.8 / 53.0 / 70.8; max wait before first word 0.62 / 0.61 / 0.59 s (was ~4.2 / 4.7 / 3.5). Quality 3/3. N=2 unchanged.

**Takeaway.** Two-stage pipeline: wall at three chats ≈ two. Fair turns fix the stall; single-chat path unchanged when the flag is off.

**Post status.** Covered by the Day 6 draft above (drafted, not posted). Details: `docs/BENCHMARKS.md` idea 1 section.


## 2026-10-31 night — Idea 1 several chats at once (`--split-pipeline-chats`)

**Goal.** Overlap Packer 1's half for chat B with the lead's half for chat A so both GPUs stay busy across several chats / agents. Off by default (`N=1`).

**Hardware.** Same two Minis, Thunderbolt 4, LPM off, keepalive on.

**Software.** `3d3e98a` + `be19fe1` on `caravan-v3-mlx-split`. Flag `--split-pipeline-chats N` / `CARAVAN_MLX_SPLIT_PIPELINE_CHATS`. Bench `bench/v3/pipeline_bench.py`.

**Results.** Two chats wall aggregate ≈1.6× one (Qwen3 44.4→72.7, Gemma 37.0→61.0, GPT-OSS 33.5→54.0). Flag-off single-chat matches keepalive baseline. First N=3 run stalled one chat (~4 s TTFT) — fixed Nov 1 (entry above). Quality 3/3.

**Takeaway.** Multi-chat throughput win; one chat on its own is not faster. Use idea-5 balanced cuts with the pipeline.

**Post status.** Covered by the Day 6 draft above (drafted, not posted).

## 2026-10-31 — GPU keepalive while waiting on the peer (Caravan MLX split)

**Goal.** Remove the ~5–6 ms/half/token Metal cool-down that shows up after each Mini sits idle during turn-taking. Keep Metal warm with a tiny `mx.eval` on a side thread during the blocking peer wait, then stop it before this process runs its own layers. A/B keepalive on vs off on all three 4-bit models; also sample CPU while it runs (powermetrics needs a password on the Minis).

**Hardware.** EXO1 (lead) and EXO2 (packer), Mac mini M4 24 GB, Thunderbolt 4 cable. `pmset -g` showed `lowpowermode 0` on both before every run.

**Software.** Branch `caravan-v3-mlx-split`, code commit `0f14e72` (spawn-per-wait `GpuKeepalive` in `agent/mlx_split.py`, `--split-keepalive` / `CARAVAN_MLX_SPLIT_KEEPALIVE` in `agent/mlx_worker.py`). MLX 0.32.4, mlx-lm 0.32.2. `bench/v3/split_client.py bench`. Flag on by default; OFF runs used `--no-split-keepalive`.

**Config.** EXO1 lead on test port 8194, EXO2 packer on 169.254.104.38:5560, worker defaults. Models 4-bit from EXO1 `~/.exo/models/...` and EXO2 `~/.caravan/mlx-models/...`. Medians of 2 (tg128 / pp512 / pp4096). 21:53–22:05 CDT. Output `~/.caravan/bench-2026-10-31/split-tax/ab/` on EXO1 (and packer CPU samples on EXO2). No services stopped; workers killed after each run. A long-lived pause-thread variant was tried on Gemma 4 first and rejected (writing ~17.6 tok/s, reading down); tables below use the spawn-per-wait design only.

**Results: writing / reading 512 / reading 4k (tok/s), TTFT on tg128 (s), peak mem (GB), quality**

| model | keepalive | write | read 512 / 4k | TTFT | peak | q |
|---|---|---:|---|---:|---:|---|
| Gemma 4 | off | 27.7 | 411.9 / 376.4 | 0.401 | 9.09 | 3/3 |
| Gemma 4 | on | 38.3 | 427.0 / 397.7 | 0.344 | 9.09 | 3/3 |
| GPT-OSS | off | 26.6 | 441.5 / 424.7 | 0.380 | 6.94 | 3/3 |
| GPT-OSS | on | 34.1 | 452.3 / 443.6 | 0.335 | 6.94 | 3/3 |
| Qwen3 | off | 30.4 | 450.6 / 409.8 | 0.367 | 10.01 | 3/3 |
| Qwen3 | on | 45.6 | 461.5 / 429.0 | 0.324 | 10.01 | 3/3 |

Writing up ~39% / ~28% / ~50% (Gemma / GPT-OSS / Qwen). Reading and quality did **not** regress (reading slightly up). Peak memory unchanged.

**Power / heat while waiting.** `sudo -n powermetrics` is not available (needs a password). Proxy: `ps -p … -o %cpu=` every 1 s during each bench (lead on EXO1, packer on EXO2). Lead CPU median: Gemma off 4.5 → on 13.9; GPT-OSS 1.7 → 15.0; Qwen 1.4 → 12.8 (keepalive keeps the process busier during the peer wait). Packer CPU median barely moved with the spawn design (GPT-OSS 0.5 → 5.5; Qwen 0.7 → 0.9). The rejected long-lived thread held lead/packer CPU medians around 70–72% and slowed writing. No watt or temperature numbers without powermetrics.

**Takeaway.** Spawn-per-wait GPU keepalive is a real single-chat writing win with no reading or quality cost. Default on; disable with `--no-split-keepalive` or `CARAVAN_MLX_SPLIT_KEEPALIVE=0`. Do not use a long-lived pause thread (MLX lock contention). The remaining gap vs one Mac is still the serial half-then-half pipeline (ideas 1 and 3).

**Deficiencies.** Two runs per setting. CPU% is a proxy for power, not watts or GPU busy. No idle-but-loaded watt draw. No 4k/16k chat or restart under keepalive. Long-lived variant only fully bench'd on Gemma 4.

**Would be faster/more robust if.** Idea 1 / 3 still applied on top. A passwordless `powermetrics` sample (or `ioreg` GPU busy) for real idle-loaded watts. Keepalive tied into `build_lead_command` / `build_packer_command` when the agent starts the split.

**Post status.** not drafted


## 2026-10-31 — Uneven layer split with `--split-packer-layers` (Caravan ROADMAP idea 5)

**Goal.** Move the cut so Packer 1 gets +1 or +2 layers vs the default even split, for 4-bit Gemma 4, GPT-OSS and Qwen3. Expectation from the LPM-off rerun: the packer half was 2–4 ms faster than the lead on Gemma 4 and GPT-OSS, 0.4 ms on Qwen3, so giving the packer a layer or two more should balance the halves. ROADMAP called this a small win alone and more important with idea 1 (several chats at once).

**Hardware.** EXO1 (lead) and EXO2 (packer), Mac mini M4 24 GB, Thunderbolt 4 cable. `pmset -g` showed `lowpowermode 0` on both before every run.

**Software.** Branch `caravan-v3-mlx-split` tip `845216b` on EXO1 `~/dev/caravan-v3` and EXO2 `~/cv3` (same speed code as v3.1). MLX 0.32.4, mlx-lm 0.32.2. Flag `--split-packer-layers K` (alias `--split-front-layers`) on both halves; hello rejects a mismatched cut. `bench/v3/split_client.py bench`.

**Config.** Same as the LPM-off rerun: EXO1 lead on test port 8194, EXO2 packer on 169.254.104.38:5560, worker defaults (4 sessions, 2 GB, prefill step 2048, 16-bit cache, save on). Models 4-bit from EXO1 `~/.exo/models/...` and EXO2 `~/.caravan/mlx-models/...`. Cuts: Gemma 4 K=15/16/17, GPT-OSS K=12/13/14, Qwen3 K=24/25/26. Medians of 2 runs. 20:16–20:32 CDT. Output `~/.caravan/bench-2026-10-31/idea5-uneven/`. No services stopped; workers killed after each run.

**Results: writing / reading 512 / reading 4k (tok/s), TTFT on tg128 (s), peak mem lead/packer (GB), packer/cable/lead (ms/tok), quality**

| model | K | write | read 512/4k | TTFT | peak L/P | halves ms | q |
|---|---:|---:|---|---:|---|---|---|
| Gemma 4 | 15 (even) | 27.6 | 411.6 / 374.3 | 0.400 | 9.09 / 9.07 | 16.7 / 0.82 / 17.9 | 3/3 |
| Gemma 4 | 16 (+1) | 27.4 | 412.6 / 374.9 | 0.398 | 8.58 / 9.58 | 17.8 / 0.82 / 17.0 | 3/3 |
| Gemma 4 | 17 (+2) | 27.4 | 412.8 / 375.9 | 0.407 | 8.07 / 10.09 | 18.6 / 0.85 / 16.1 | 3/3 |
| GPT-OSS | 12 (even) | 26.8 | 442.1 / 425.4 | 0.383 | 6.94 / 6.94 | 16.0 / 0.85 / 19.7 | 3/3 |
| GPT-OSS | 13 (+1) | 26.6 | 439.3 / 426.6 | 0.381 | 6.48 / 7.40 | 17.4 / 0.85 / 18.5 | 3/3 |
| GPT-OSS | 14 (+2) | 26.7 | 439.6 / 431.9 | 0.385 | 6.00 / 7.87 | 18.5 / 0.83 / 17.2 | 3/3 |
| Qwen3 | 24 (even) | 30.0 | 450.5 / 406.9 | 0.373 | 10.01 / 10.02 | 16.1 / 0.76 / 15.6 | 3/3 |
| Qwen3 | 25 (+1) | 30.2 | 449.6 / 410.6 | 0.370 | 9.63 / 10.40 | 16.7 / 0.77 / 14.7 | 3/3 |
| Qwen3 | 26 (+2) | 30.5 | 450.8 / 412.1 | 0.358 | 9.25 / 10.78 | 17.1 / 0.77 / 14.1 | 3/3 |

Even-split matched the LPM-off baseline (30.4 / 27.7 / 26.6 writing; 451/408, 411/375, 440/424 reading) within noise.

**Takeaway.** No single-chat writing gain on Gemma 4 or GPT-OSS: the pipeline is serial, so moving a layer shifts time between halves and the sum stays flat (~35.5 / ~36.6 ms per token). Qwen3's 30.0 → 30.5 is near noise and it was already balanced at even. Best balanced cuts for idea 1: Gemma **K=16**, GPT-OSS **K=13**, Qwen3 **even (K=24)**. Reading flat; memory shifted as expected. Flag works; no code changes.

**Deficiencies.** Two runs per cut. Half timings mix a few prefill calls into the per-call averages (133 calls for 127 write tokens); same method as the LPM-off table. No 4k/16k chat or restart under uneven cuts. Did not try fewer packer layers.

**Would be faster/more robust if.** Idea 1 (several chats at once) used these balanced cuts so both Minis stay busy. Bench scripts refuse when `lowpowermode 1`. A short probe picks K from each half's ms before a long session. For single-chat writing, guess ahead (idea 3) still looks bigger than moving the cut.

**Post status.** not drafted


## 2026-10-31 — v3 two-Mac MLX split and GPU-wait test rerun with Low Power Mode off (Caravan v3.1)

**Goal.** EXO2 (the packer) turned out to be in Low Power Mode during every earlier two-Mac run. Brenden turned it off; rerun the v3 split bench and the GPU-wait test to see what it had cost and whether the split-each-layer verdict changes.

**Hardware.** EXO1 (lead) and EXO2 (packer), Mac mini M4 24 GB, Thunderbolt 4 cable. `pmset -g` showed `lowpowermode 0` on both before the runs.

**Software.** Caravan v3.1 at the branch tip `f68d15e` on both Macs (branch `caravan-v3-mlx-split`), MLX 0.32.4, mlx-lm 0.32.2. `bench/v3/split_client.py bench` (same client as the original v3 numbers), `bench/cable/gpu_wait.py`. Docs commit: see "Post status".

**Config.** Same as the original v3 run: EXO1 lead on test port 8194, EXO2 packer on 169.254.104.38:5560, worker defaults (4 sessions, 2 GB, prefill step 2048, 16-bit cache, save on). Models: Qwen3 30B-A3B 4-bit, Gemma 4 26B-A4B 4-bit, GPT-OSS 20B MXFP4-Q8, plus the three 8-bit builds. Medians of 2 runs. 4-bit 18:10–18:15 CDT, 8-bit 18:15–18:21 CDT, GPU-wait 18:21–18:25 CDT. No services stopped. Only the `bench` part was rerun (no 4k/16k chats or restarts); one-Mac v2.1 numbers are from the earlier session.

**Results: 4-bit, writing / reading 512 / reading 4k (tok/s), bench peak per Mac (GB), quality**

| model | one Mac (v2.1) | old v3 (Low Power Mode on) | new v3 (off) |
|---|---|---|---|
| Qwen3 30B | 51.0 / 465 / 400, 19.04, 3/3 | 29.5 / 388 / 332, 10.44, 3/3 | 30.4 / 451 / 408, 10.02, 3/3 |
| Gemma 4 26B | 41.3 / 431 / 399, 17.14, 3/3 | 26.9 / 328 / 301, 9.28, 3/3 | 27.7 / 411 / 375, 9.09, 3/3 |
| GPT-OSS 20B | 36.5 / 457 / 445, 13.41, 3/3 | 26.1 / 350 / 338, 7.03, 3/3 | 26.6 / 440 / 424, 6.94, 3/3 |

8-bit writing 20.7 / 18.4 / 20.1 tok/s (was 20.6 / 18.1 / 19.8), reading 512 / 4k 442 / 395, 401 / 362, 430 / 405 (was 377 / 320, 316 / 282, 334 / 312), bench peak 17.65 / 15.38 / 12.01 GB, 3/3. Per token, the packer half went 16.7 → 16.1, 17.4 → 16.4, 16.7 → 16.0 ms; the lead (15.7 / 18.5 / 20.3 ms) and the cable (0.8–0.9 ms) didn't change.

GPU-wait, per exchange beyond compute: batch 1 325 / 366 / 359 µs (was 359 / 343 / 331), batch 4 403 / 414 / 403 µs (was 351 / 298 / 348). Estimate (slower new v3 half + exchanges × cost): Qwen3 47.3 ms = 21.1 tok/s, Gemma 4 40.5 ms = 24.7, GPT-OSS 37.5 ms = 26.7 (new v3 30.4 / 27.7 / 26.6, one Mini 51.0 / 41.3 / 36.5). Budgets to beat v3: 175 / 294 / 362 µs; one Mini: 36 / 95 / 148 µs.

**Takeaway.** Low Power Mode on the packer had cost the split a lot of reading speed (turning it off: +16–30%, now within about 6% of one Mac) but almost no writing speed (+0.5–3%), because writing one token at a time waits on memory and the per-pass hand-off, not on GPU sums. Writing is still 27–40% slower than one Mac. Splitting each layer is still a no-go: it now only ties v3 on GPT-OSS and loses to one Mini on all three. Batch 4 per-exchange cost went up, because the slow packer had been hiding part of the wait. New side finding: the packer is now the faster half by 2–4 ms on Gemma 4 and GPT-OSS, so an uneven cut (idea 5) is worth a try.

**Deficiencies.** Two runs per setting, one evening. Old and new are different sessions, not interleaved side by side. One-Mac numbers weren't rerun. Chat-reuse, 16k and restart tests weren't rerun. The GPU-wait test is still synthetic (see its own entry), and EXO1's batch-1 "compute" also came out 17–20% lower for Gemma 4 and GPT-OSS, which Low Power Mode on EXO2 doesn't explain directly (likely the lead's timing includes the per-token handshake with the packer); not looked into.

**Would be faster/more robust if.** A check in the bench scripts that refuses to run (or warns) when `pmset -g` shows `lowpowermode 1` on either Mac. Interleaved side-by-side runs (one Mac, split) in one session, 3+ runs each. Trying `--split-packer-layers` one or two layers higher for Gemma 4 and GPT-OSS. For writing speed, the bigger wins are still "several chats at once" and "guess ahead".

**Post status.** Not drafted; not posted. Docs commit 0e9f1df on `caravan-v3-mlx-split`.

## 2026-10-31 — GPU-wait test: splitting each layer across both Minis, with real GPU waits (Caravan ROADMAP idea 4, follow-up)

**Goal.** Measure the full cost of one split-each-layer exchange: both Minis compute their half, wait for the GPU, swap the partial result over the cable, add. Then decide go/no-go against v3 and one Mini.

**Hardware.** EXO1 (lead) and EXO2 (packer), Mac mini M4 24 GB, Thunderbolt cable. EXO2 turned out to be in Low Power Mode (not changed).

**Software.** `bench/cable/gpu_wait.py` (branch `caravan-v3-mlx-split`, commit f68d15e by Rook, pushed Oct 31), MLX 0.32.4 in the MLX venv, Caravan's link framing (`encode_frame` / `read_frame`, TCP_NODELAY), port 5572. No model loaded; synthetic 4-bit weights sized like half of each model's layer (0.8–2.4 GB per Mac). No services stopped. Run 17:31–17:36 CDT.

**Config.** Qwen3 30B-A3B (48 layers, 96 exchanges per token), Gemma 4 26B-A4B (30, 60), GPT-OSS 20B (24, 48); batch 1 and 4; 200 timed tokens + 20 warm-up per mode. Modes: compute only, wait after each part (no cable), swap only (no GPU), full exchange, overlap trick (batch 4: two half-batches).

**Results: cost per exchange on top of compute (µs, median; p95 for the full exchange)**

| model | batch | GPU wait only | cable only | full exchange | overlap trick |
|---|---:|---:|---:|---|---:|
| Qwen3 30B | 1 | 277 | 60 | 359 (p95 365) | — |
| Qwen3 30B | 4 | 201 | 69 | 351 (p95 406) | 441 |
| Gemma 4 26B | 1 | 261 | 74 | 343 (p95 351) | — |
| Gemma 4 26B | 4 | 219 | 80 | 298 (p95 362) | 514 |
| GPT-OSS 20B | 1 | 246 | 87 | 331 (p95 342) | — |
| GPT-OSS 20B | 4 | 230 | 92 | 348 (p95 470) | 647 |

**Estimate, single chat** (slower v3 half + exchanges × cost): Qwen3 51.0 ms = 19.6 tok/s (v3 29.5, one Mini 51.0); Gemma 4 39.4 ms = 25.4 tok/s (v3 26.9, one Mini 41.3); GPT-OSS 36.4 ms = 27.5 tok/s (v3 26.1, one Mini 36.5). Per-exchange budget to beat v3: 180 / 306 / 371 µs; to beat one Mini: 31 / 90 / 144 µs.

**Takeaway.** No-go. Splitting each layer loses to one Mini on every model (by 25–60%), loses to v3 on Qwen3 and Gemma 4, and is only about 5% ahead of v3 on GPT-OSS, inside this test's error. The big cost is stopping the GPU to hand results over (about 250 µs each time, 48–96 times per token), not the cable. Even with a free cable it would still lose to one Mini. Parked; do "several chats at once" and "guess ahead" instead.

**Deficiencies.** Synthetic GPU work: no attention over the chat history, no routing, 4-bit affine instead of GPT-OSS's MXFP4, dense matmuls over all touched experts at batch 4. The estimate adds the measured exchange cost to v3's measured halves, which assumes the split halves cost the same as v3's. EXO2 was in Low Power Mode, which slowed its batch-4 compute 50–80% compared with EXO1 (batch 1 was within 3–6%). One run, one evening.

**Would be faster/more robust if.** The GPU could hand results to the other Mac without a full stop (GPU-to-GPU or RDMA links, for example MLX's jaccl on Thunderbolt 5). Fewer exchanges per token (for example exchanging once per layer with a different split). Repeat with EXO2 out of Low Power Mode, and with real model layers rather than synthetic ones.

**Post status.** Not drafted; not posted.

## 2026-10-31 — Cable timing over Thunderbolt for splitting each layer across both Minis (Caravan ROADMAP idea 4)

**Goal.** Before building anything, measure how long one small exchange between the Minis takes, since splitting each layer needs two per layer. Then apply the roadmap's go/no-go rule.

**Hardware.** EXO1 (lead) → EXO2 (packer), Mac mini M4 24 GB each, Thunderbolt cable (`en2` on EXO1, link-local TCP).

**Software.** `bench/cable/cable_timing.py` on branch `caravan-v3-mlx-split`, commit 2260d2e (Rook), pushed with annotated tag `v3.1` on Oct 31 (not merged into main). Caravan's own split link (`FrontClient` → `serve_front`, TCP_NODELAY, same framing as v3) vs plain TCP. MLX venv Python (mlx-lm 0.32.2). No models loaded; no Caravan or exo services were running, so nothing was stopped. Test ports 5570/5571, servers stopped afterwards. Run 17:13–17:15 CDT.

**Config.** Sizes = hidden_size × batch × 2 bytes from each config.json (Qwen3 30B-A3B 2048 × 48 layers, Gemma 4 26B-A4B 2816 × 30, GPT-OSS 20B 2880 × 24), batch 1/4/16, plus 1 KB–1 MB. 100 warm-up + 2,000 timed round trips per size (200 at 1 MB). One extra run with `--gpu-sync` (each side makes an MLX array and waits for one tiny op before sending).

**Results (round trip, µs, Caravan link median / p95; plain TCP median)**

| exchange | Caravan link | plain TCP | Caravan + GPU sync |
|---|---|---|---|
| Qwen3 batch 1 (4 KB) | 101 / 123 | 91 | 1,103 |
| Gemma 4 batch 1 (5.6 KB) | 104 / 127 | 92 | 1,107 |
| GPT-OSS batch 1 (5.8 KB) | 104 / 126 | 88 | 1,106 |
| batch 4 (16–23 KB) | 122–137 / 149–163 | 105–111 | 1,143–1,169 |
| batch 16 (64–92 KB) | 191–213 / 214–237 | 158–182 | 1,294–1,310 |
| 1 MB | 693 / 729 | 754 | 4,483 |

Bulk one way: 1,978 MB/s. A repeat run (5,000 per size) agreed within about 3%. A lone MLX sync on EXO1: about 175 µs.

**Prediction (slower v3 half + layers × 2 × round trip).** Single chat: Qwen3 16.6 + 9.7 = 26.3 ms (the roadmap had guessed 22), Gemma 4 18.8 + 6.2 = 25.0 ms, GPT-OSS 20.5 + 5.0 = 25.5 ms, vs one Mini 19.6 / 24.2 / 27.4 and the v3 split 34 / 37 / 38. Batch 4, best-case estimates (same step time at any batch): Qwen3 141 tok/s vs one Mini 204, Gemma 4 148 vs 165, GPT-OSS 150 vs 146 (v3 + several chats ≈ 98). Batch 16: one Mini wins for all three.

**Takeaway.** The cable costs about 100 µs per exchange, twice the guess, and Caravan's framing adds only 10–35 µs over plain TCP. Splitting each layer would beat today's v3 split for every model, but would beat one Mini only for GPT-OSS, and only by a hair. By the letter of the rule GPT-OSS passes at batch 4 (by 3%), but only if waiting for the GPU before each exchange were free, and it isn't. **Verdict: not a go yet; park it for Thunderbolt 4** and do "several chats at once" and "guess ahead" first.

**Deficiencies.** The GPU-sync run puts the two syncs one after the other and copies bytes into a new array each time, so it overstates the real wait. The batch 4/16 numbers for every option are estimates (no batching is built). The "half" is v3's per-half time; splitting each layer could have different overhead. One evening run, idle Macs, one cable.

**Would be faster/more robust if.** A GPU-wait test with both Minis syncing at the same time on arrays already on the GPU (this decides the GPT-OSS case: it needs under about 15 µs per exchange at batch 4). Measure batched step times on one Mini so the batch columns are real. A faster link (Thunderbolt 5 / RDMA) would cut the 100 µs floor. Repeat on another day to check drift.

**Post status.** Not drafted; not posted.

## 2026-10-31 — Caravan v3: one MLX model split across two Mac minis (lead + packer over Thunderbolt), vs v2.1 on one Mini; bigger brothers; split download

**Goal.** Run one MLX model across both Minis, so models and long chats that don't fit on one 24 GB Mini can run on MLX. Compare v2.1 (whole model on one Mini) with v3 (split) on the same three models, side by side in one session. Then run the bigger-brother quants split across both Minis, and prototype a split download where each Mini fetches only its own part.

**Hardware.** EXO1 (the lead, the Mini you talk to) and EXO2 (Packer 1, runs the first layers), Mac mini M4 24 GB each (GPU limit ≈ 19.07 GB), joined by a Thunderbolt cable (TCP over the link-local Thunderbolt addresses). Internet is Starlink, about 13 MB/s shared. exo paused on both Minis. On EXO2, `CARAVAN_SLOT_CLEANUP=off` and nothing deleted. Test ports only (8192 v2.1 worker, 8194 v3 lead, 5560 split link, 8190 proxy smoke). mlx-lm 0.32.2. Runs 10:08–10:35 CDT (bridge), 10:38–11:05 CDT (Qwen3.6, Qwen3 8-bit), 12:18–12:25 CDT (GPT-OSS 20B 8-bit), 12:31–12:39 CDT (Gemma 4 26B 8-bit).

**Why our own pipeline.** `mx.distributed` ring fails over Thunderbolt on messages of 2 MB and up. jaccl needs Thunderbolt 5. mlx-lm's pipeline sharding only covers Qwen3. So v3 splits by layers itself. Packer 1 runs the embeddings and layers 0..K-1 and sends the hidden state over one TCP connection (`caravan-split-1`). The lead runs the rest plus the norm, `lm_head` and sampling, and serves the HTTP API. Each stage keeps its own per-session caches in lockstep and saves them to its own disk; a restore needs both halves or neither, and the lead detects a restarted packer by its epoch.

**Code (not pushed, not merged).** Branch `caravan-v3-mlx-split` off `c026359`, worktree `~/dev/caravan-v3` on EXO1, commits by Rook: b03d1e9 (split), a167835 (hybrid-model cache fix, bench client), d68e094 (docs), 83f86a9 (rename to lead / packers, old names kept as aliases), 14dfcb4 and 8a64430 (ROADMAP: beating the turn-taking, the split-each-layer plan and its cable-timing test). New `agent/mlx_split.py`, `agent/mlx_split_fetch.py`, worker flags `--split-role/--split-peer/--split-listen/--split-packer-layers` (`--split-packer-layers` still works as a deprecated alias), `mlx.split` config, `bench/v3/split_client.py`, docs/MLX-SPLIT.md. 118 unit tests passed at d68e094; 120 pass after the rename (re-run Oct 31 on EXO1). EXO2 runs the v3 code from its own copy (`~/cv3`) with a venv matching EXO1; that copy predates the rename, so it only knows the old flag names until it's updated.

**v2.1 vs v3: one Mac vs two Macs (Oct 31, MLX)**

v2.1 runs the whole model on one Mac mini. v3 splits it across both:
Packer 1 (EXO2) runs the embeddings and the first half of the layers, the
lead (EXO1) runs the second half, the final norm, `lm_head` and sampling,
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

| | Packer 1 | cable | lead | whole model on one Mac (v2.1) | sent per token |
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

**Bigger brothers, split across two Macs (Oct 31, MLX, v3)**

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

**How the weights get to the other Mini today.**
- MLX v3: each Mini loads from its own local copy, and each stage reads only its own layers (lazy load). Nothing is streamed from lead to packer at load. For this sprint, EXO2's 4-bit copies were copied once over Thunderbolt from EXO1. Qwen3 30B 8-bit came from the new split download (each Mini fetched only its own shards from Hugging Face). Gemma 4 26B 8-bit and GPT-OSS 20B 8-bit: EXO1 downloaded its own files plus the packer-only files, and copied only the packer's files to EXO2 over Thunderbolt (planned split: Gemma 22.75 / 15.59 GB, GPT-OSS 16.98 / 15.8 GB, of 27.95 / 22.23 GB).
- llama.cpp two-Mini runs: the lead needs the full GGUF on disk and sends the packer's tensors over RPC at load. With `rpc-server --cache` (our build has `-c, --cache`, and the packer's `com.caravan.rpc-server.plist` uses it) the packer keeps them on disk by hash, so only the first load crosses the wire (a restart then loads in ~53 s instead of 7–11 min over LAN).

**What broke.**
- Two unit tests failed at first (resync after a packer restart): `prepare` now checks the packer's epoch first.
- Gemma 4 and GPT-OSS think before answering: content was empty at 200 tokens, so the bench gives them 1,536.
- v2.1 Qwen with default worker settings ran out of GPU memory at 4k; the tuned settings fix 4k, but 16k still doesn't fit on one Mini (expected).
- Qwen3.6 (`qwen3_5_moe`, hybrid attention) crashed the lead at load: its cache builder walked all layers after the packer's had been dropped. Fixed by building a prototype cache first.
- Qwen3.6 doesn't reuse the chat: every turn diverges (the template drops earlier reasoning, and linear-attention layers can't be rewound), so it re-reads the whole chat (11 s at 4k, 53 s at 16k), even after a restart. Parked.
- Hugging Face's xet downloads stalled (0 KB/s); switched to plain HTTP (`HF_HUB_DISABLE_XET=1`) with retries. Stale `.incomplete` files were left in place (no deletes).
- A bench orchestration bug (`a; b &` blocking SSH) and a port check fooled by status text; both fixed in the box-side scripts.
- GPT-OSS 120B doesn't fit (see below).
- A results pull with an unexpanded `~` path created two empty local files on the box (removed; the originals on EXO1 were untouched).

**GPT-OSS's bigger brother.** GPT-OSS only comes in 20B and 120B. The stock 120B is 63.4 GB. Every GGUF quant (Q2_K, IQ2, IQ1_S, ...) is 62.6–66 GB, because the experts stay in MXFP4. The smallest MLX build, `jesusoctavioas/gpt-oss-120b-mlx-2Bit` (36.6 GB, plain 2-bit), would put about 18.3 GB of weights on each Mini against a ~19.07 GB GPU limit, with no room for chat memory (our stages peak 1.5–2.2 GB above their weights). It would need ~37 GB of disk split across the two. `manjunathshiva/gpt-oss-120b-tq3a-tq2e-g32` (37.7 GB) uses a TurboQuant mode stock mlx can't load. So the bigger brother is GPT-OSS 20B at 8-bit (`lmstudio-community/gpt-oss-20b-MLX-8bit`, 22.2 GB; doesn't fit on one Mini). Note: GPT-OSS was released with MXFP4 experts, so the 8-bit build mostly re-encodes them; expect little quality gain.

**exo.** No exo two-Mac MLX speed numbers are in this log, so there's nothing comparable.

**Video.** LAB-2026-10-31-04, `videos/2026-10-31_caravan-v2.1-vs-v3_mlx-split_v8.mp4`, 1:26, title "Day 4" (lead / packer naming, plus an opening slide on why Caravan links the Minis itself). Replaces LAB-2026-10-31-03 (v7, 1:18, kept).

**Next.** Beat the turn-taking between the two halves (ideas in ROADMAP, "Beating the turn-taking in the split"; first a cable-timing test for splitting each layer across both Minis) and trim per-pass overhead; update EXO2's copy to the renamed code; wire split download into the agent; GGUF stage 2 (each packer fetches its own tensors from the file instead of receiving them over the cable). See ROADMAP, including Deferred / parked.

**Post status.** Day 4 thread drafted Oct 31; Brenden scheduled it on X for Monday Nov 2 (goes with video v8, LAB-2026-10-31-04). Not live yet.


## 2026-10-31 — Caravan v2.1: wired limit held from startup, optional deferred first save, same-session A/B vs v1 and v2

**Goal.** Find out whether v2's slower Qwen 4k reading (374–390 vs v1's 396 tok/s yesterday) came from v2 raising and dropping the Metal wired limit around every request. Lock the model's memory once at startup instead, as mlx_lm.server does. Test whether skipping the save after one-message requests helps. Re-measure with v1, v2 and v2.1 alternated in one session so drift between days cancels out.

**Hardware.** EXO1, a Mac mini M4 with 24 GB. exo paused. Test ports only: 8190 (proxy), 8192 (MLX). Same three MLX models. mlx-lm 0.32.2. Run 07:15–07:33 CDT.

**Code (not pushed, not merged).** New branch `caravan-v2.1` off `caravan-v2-mlx-cache`, worktree `~/dev/caravan-v2.1`, commit b9ebeb7 by Rook. The v2 worktree stays at 7835efd for comparison.
- Worker flag `--wired-limit startup|per-request|off`, default startup. At load the log shows `wired limit 0 -> 19069665280 bytes (held for process lifetime)`. `per-request` reproduces v2.
- Proxy setting `CARAVAN_MLX_SAVE_MIN_TURNS` (also `--mlx-save-min-turns` and `proxy.mlx_save_min_turns`), default 1, which changes nothing. With 2, one-message requests aren't saved and the 2nd turn saves the whole chat.
- 7 new unit tests (97 total, all pass).
- Bench: `bench/v2.1/ab_bench.py` plus `suite_v21.sh`. Each round restarts every variant fresh, in rotated order. Raw data: EXO1 `~/.caravan/bench-2026-10-31/v2.1/`.

**Qwen3 30B, reading tok/s** (3 rounds × 2 = 6 runs per size, median, with min–max for 4k)

| | v1 (mlx_lm.server) | v2 | v2.1 | v2.1 + skip first save |
|---|---|---|---|---|
| 4k prompt | 395.9 (385–397) | 393.4 (380–398) | 395.6 (390–399) | 396.4 (386–399) |
| 4k, the worker's own read time | – | 400.1 | 400.5 | 401.0 |
| 512, first one after a 4.7k chat | 436 | 380 | 387 | 386 |
| 512, the next one | 441 | 438 | 439 | 434 |
| Peak footprint / lowest free memory | 18.84 GB / 16% | 18.71 GB / 17% | 18.68 GB / 17% | 18.75 GB / 17% |

**What it shows.**
- Side by side, v1, v2 and v2.1 read Qwen 4k at the same speed (393–396). Even the unchanged v2 matches v1, so yesterday's gap was mostly drift between days, not the code.
- Holding the wired limit made v2.1 a little steadier (slowest run 390 vs 380 for v2). The medians are within noise.
- Skipping the first save had no measurable effect. With a warm disk a 4k save takes 0.10 s (399 MB) in the worker.
- The one real v2 cost left on Qwen is about 0.15 s on the first short request right after a big chat (380–387 vs 436). It happens with or without saving, so it is most likely the worker dropping the previous chat from memory (Qwen runs with room for one chat).

**Gemma 4 and GPT-OSS** (1 round × 3; no regression from v2 to v2.1)

| tok/s 512 / 4k | v1 | v2 | v2.1 |
|---|---|---|---|
| Gemma 4 | 430 / 383 | 396 / 376 | 397 / 376 |
| GPT-OSS | 429 / 418 | 424 / 415 | 424 / 415 |

Gemma's short-prompt gap (about 8% behind v1) shows up again in the same session, so it is real, and the wired limit doesn't fix it. It's specific to Gemma, which fits the cost of checkpointing its sliding-window caches. That is next to look at.

**Memory and swap.** Footprint is the same in all versions (Qwen 18.7–18.8 GB, Gemma 18.5, GPT-OSS 13.7). Lowest free memory was 16–18% with Qwen and Gemma, 37% with GPT-OSS. Swap used was 1.04 GB before, 1.45 GB at most during the runs (it rose during the first v1 load and stayed flat after that), and 1.08 GB afterwards. Process RSS reads lower for the worker (2–7 GB vs 6–12 GB for mlx_lm.server), but that's how macOS counts it; footprint is the number that matters.

**Restart resume (Qwen 4k, v2.1).** Still works. First turn cold 11.6 s, turn 2 0.72 s, restart 9.7 s, then turn 3 0.52 s (re-read 31 of 4,377 tokens) and turn 4 0.53 s.

**Next.** Gemma's short-prompt checkpoint cost. The ~0.15 s cost of dropping the previous chat on Qwen. Per-model profiles, proxy overhead, memory headroom and restore from a cold disk (see the v2 entry).

**Post status.** not drafted.

## 2026-10-31 — Caravan v2: MLX step (b), per-session MLX chat caches saved to disk, GPT-OSS replies tidied, vs Caravan v1

**Goal.** Make MLX reuse the chat between messages for Gemma 4 and GPT-OSS. Save each session's MLX cache to disk and load it after a restart, with the same per-session semantics and stale cleanup as the llama.cpp slots. Keep Qwen's tight memory settings. Strip GPT-OSS's harmony "thinking" markup from the reply text. Check that the llama.cpp path did not regress.

**Hardware.** EXO1, a Mac mini M4 with 24 GB. exo stayed paused on both Minis, carried over from 2026-10-30 and not restored. Test ports only: 8190 (proxy), 8192 (MLX worker), 8180 (llama-server). Same three models: the MLX copies in `~/.exo/models` (Qwen3-30B-A3B 4-bit, Gemma 4 26B-A4B 4-bit, GPT-OSS-20B MXFP4-Q8), plus the GGUFs for the llama.cpp check.

**Code (not pushed, not merged).** Caravan branch `caravan-v2-mlx-cache`, off `improvements-1-3`, worktree `~/dev/caravan-v2`. Commits are by Rook: f57af3b (worker with per-session prompt caches), 6d4bdb0 (proxy restore/save, cleanup, launch), fac73b8 (warm-up, disconnect cancel, `--kv-bits`, Qwen lead-strip), f73eafb (bench/v2, README, LOG), 7835efd (per-Mini cap on saved chats). 90 unit tests pass. Raw data: EXO1 `~/.caravan/bench-2026-10-31/v2/` (MLX) and `~/.caravan/bench-2026-10-30/improvements/v2l-*` (llama.cpp).

**Why v1 never reused MLX chats.** mlx-lm 0.32.2 caches prompt plus reply. The next turn re-renders the reply differently, and the sliding-window cache can't be cut back once it has wrapped, so every turn started cold. Each hit was also a full copy, which is what pushed Qwen out of memory. The v2 worker checkpoints the cache at the end of the prompt and rewinds to that point after generating. That checkpoint is the file it saves and loads.

**MLX, Caravan v1 → v2** (seconds to first word; tok/s; quality 3/3 everywhere)

| | Qwen3 | Gemma 4 | GPT-OSS |
|---|---|---|---|
| Turn 2, 4k chat | 0.44 → 0.56 | 10.76 → 0.49 | 9.16 → 0.50 |
| Tokens re-read on turn 2 (4k) | reused → 46 | 4,034 → 36 | 4,041 → 32 |
| Turn 2, 16k chat | OOM → OOM | 55.1 → 0.72 | 37.3 → 0.59 |
| After restart, 4k | 16.0 → 0.59 | 16.0 → 0.64 | 12.7 → 0.52 |
| After restart, 16k | OOM → OOM | 60.3 → 0.84 | 40.7 → 0.59 |
| First turn, 16k (cold) | OOM | 60.1 → 50.6 | 40.6 → 43.0 |
| Writing tg128 | 47.0 → 49.1 | 39.8 → 42.2 | 35.3 → 37.4 |
| Reading pp512 / pp4096 | 439 / 396 → 438 / 380 | 427 / 384 → 397 / 393 | 434 / 441 → 433 / 442 |
| Peak footprint, speed tests (GB) | 18.97 → 18.71 | 18.6 → 18.41 | 13.93 → 13.72 |
| Peak footprint, 16k chat (GB) | 19.41 → 19.38 (both OOM) | 18.28 → 17.67 | 14.25 → 14.09 |
| Save file 4k / 16k | none → 433 MB / – | none → 299 / 573 MB | none → 109 / 412 MB |
| Worker start (s) | 1.6 → 8.7 | 1.6 → 8.2 | 1.6 → 6.1 |

Loading a save takes 0.01–0.13 s, measured on a warm disk. Writing a save takes about 0.05–0.15 s.

**GPT-OSS harmony fix.** In v1, `content` carried `<|channel|>analysis…` markup. v2 parses the channels: `content` is the final answer only, and the thinking goes to `reasoning_content` (also mirrored as `reasoning`). Reasoning that a client sends back in its history is dropped before templating, so the history matches the cache. A 4th turn that echoes the reasoning still hits, re-reading 24 tokens (0.44 s). What the fix buys: turn 2 re-reads 32 tokens instead of 4,041 (9.16 → 0.50 s). Memory doesn't change (13.9 → 13.7 GB). Unit tests cover markers split across pieces, missing channels, and the history-matches-cache check.

**`--kv-bits 8` for Qwen (tried, off by default).** Qwen3 at 16k still runs out of Metal memory (footprint 19.3 GB). 4k reading drops from 380 to 325 tok/s, and turn 2 at 4k is 0.58 s. The save file is smaller (231 vs 433 MB). Not worth turning on.

**llama.cpp path, v1 → v2 (regression check)**

| | Qwen3 | Gemma 4 | GPT-OSS |
|---|---|---|---|
| Reading pp512 | 401.9 → 438.1 | 399.9 → 408.3 | 436.8 → 437.4 |
| Reading pp4096 | 356.4 → 366.5 | 379.7 → 404.9 | 453.6 → 453.9 |
| Writing tg128 | 42.5 → 43.0 | 36.7 → 37.1 | 37.1 → 37.3 |
| 16k chat after restart (s) | 1.103 → 1.102 | 0.93 → 0.913 | 0.652 → 0.65 |

No regression.

**Per-Mini cap on saved chats (added from an X reply).** After the 30-day age rule, the llama.cpp slot files and MLX caches left are counted together and held to 200 files / 50 GB (`CARAVAN_SLOT_MAX_COUNT` / `CARAVAN_SLOT_MAX_GB`, or `slot_cleanup.max_count|max_gb` in config.json). The least recently used go first, in the same delete / archive / off mode, and every eviction is logged. Never evicted: a session in a llama.cpp slot, with unsaved turns, or with a turn in the last 30 minutes. Tested only on scratch copies in EXO1 `/tmp/capdemo`. The CLI archive run took 15 MLX caches (1.15 GB) LRU-first under a 0.8 GB cap. The proxy on port 8190 evicted 2 slot files under a 1-file cap and kept the in-slot session even though it was the oldest. On EXO1's real `~/.caravan/llama-server/slots` the dry run found 0 files, so the defaults would evict nothing there today. The 269-file / ~154–165 GB backlog from Oct 30 isn't on EXO1 any more and wasn't checked; node-a/EXO2 was not touched. By those numbers it is all past the 30-day age rule anyway. The cap alone would keep the newest ~50 GB (~80–90 files) and evict ~180–190 files (~105–115 GB).

**What broke / fixes.**
- Qwen3 30B at 16k doesn't fit on MLX in v1 or v2: 16.4 GB of weights plus about 3.2 GB of KV, and kv8 doesn't save it. Use llama.cpp for Qwen long chats.
- The `~/.caravan/models/gpt-oss-20b.gguf` symlink points at a removed Ollama blob, so the first GPT-OSS llama runs failed (rc=1). The script now defaults to the HF blob that v1 used. The symlink was left untouched.
- `suite_v2_llama.sh` computed its own path after the `cd`, so the first run failed. Fixed.
- I edited `suite_v2.sh` while it was running, and bash crashed mid-run. I killed my test processes and re-ran. Lesson: never edit a running script.
- The Tailscale SOCKS link dropped twice. Restarted tailscaled with the documented command.
- The v2 worker starts in 6–9 s vs 1.6 s, because it loads eagerly and warms up. Gemma reads short prompts about 7% slower. Every one-turn request also writes a small save file, and cleanup ages these out.

**Next.** The two-Mac MLX split, then per-model profiles, proxy overhead, memory headroom, and cold-disk restore.

**Post status.** Not drafted. Video: LAB-2026-10-31-01 (see videos/index.md).

## 2026-10-30 (evening) — Caravan v1: improvements 1–3 (rebased llama.cpp with SWA slot restore, MLX backend step (a), auto f16 KV) vs Caravan v0, single Mac mini M4 24 GB

**Goal.** Implement and measure three Caravan improvements:
1. Rebase the llama.cpp fork onto upstream so saved chats reload for sliding-window models.
2. Route MLX models to mlx_lm.server through the proxy.
3. Pick f16 KV automatically when it fits.

Same three models as the runtime compare. Raw data: EXO1 `~/.caravan/bench-2026-10-30/improvements/`. Scripts: Caravan `bench/improvements/`.

**Hardware.** EXO1, a Mac mini M4 with 24 GB. exo was paused on both Minis from about 20:32 CDT and left paused (see the end of this entry). Test ports only: llama 8180, proxy 8190, mlx 8192.

**Code (not pushed, not merged).**
- llama.cpp branch `caravan-patches-rebase-2026-10-30`, in worktree `~/dev/llama.cpp-rebase`.
  - Upstream `5047748f` plus `86e16204` "rpc: use getaddrinfo instead of gethostbyname in socket_t::connect" (Rook).
  - One conflict, in ggml-rpc transport.cpp. I kept the getaddrinfo code and upstream's LOG_DBG.
  - Includes upstream `033df86b` (#26004, which saves context checkpoints in the slot file). Issue #28194 is still open upstream.
  - Built into `~/dev/llama.cpp/build-rebase` (0.8.0-dev). The old `build/` (0.4.0-dev) is untouched.
- Caravan branch `improvements-1-3`, in worktree `~/dev/caravan-improvements`, on main `45ed2c2`:
  - `32b9756` MLX backend, step (a)
  - `737fea2` auto KV cache type
  - `c846e65` bench scripts, LOG and README notes
  - 58 tests OK: the 39 existing plus 19 new.
- **Naming used below:** Caravan v0 = 45ed2c2 + the old build with q8_0 KV. Caravan v1 = improvements-1-3 + the rebased build with `auto` KV.

**1. Resume a 16k chat after a server restart (wait before the first token, s; cold / warm / after restart; all q8_0 KV)**
| model | v0 (old build) | rebased | old build + `--swa-full` |
|---|---|---|---|
| GPT-OSS 20B (2×18k) | 45.5 / 0.77 / **46.3** (cache_n 0) | 44.8 / 0.71 / **0.65** (cache_n 16,086) | 47.3 / 0.75 / 0.59 |
| Gemma 4 26B (1×18k) | 54.9 / 0.70 / **56.1** (cache_n 0) | 53.0 / 0.84 / **0.93** (cache_n 16,286) | 55.7 / 0.74 / 0.48 |
| Qwen3 30B (1×18k, no SWA) | 80.0 / 1.01 / 1.18 (earlier run) | 78.4 / 0.91 / **1.10** (no regression) | — |

- **Raw prefix with a divergent ending after restart (wall time, s), old → rebased:**
  - GPT-OSS 49.2 → **2.23**
  - Gemma 59.3 → **2.59**
  - Qwen 4.55 on the rebased build
- **`--swa-full` on the old build:**
  - It fixed the chat resume for both models.
  - For the divergent-prefix case it fixed Gemma (2.54 s) but **not** GPT-OSS (51.2 s, cache_n 0).
  - It also needs much more KV memory: Gemma had to use 1 slot.
- **How the rebased build reloads:** the server logs `restored N context checkpoint(s) from <slot file>`.
- **Cost:** Gemma slot files grew from 291 to **849 MB**. GPT-OSS went from 213 to 222 MB.
- **Answers:** all correct.

**3. Auto KV and speed: v0 → rebased + q8_0 → v1 (rebased + auto), same session, tok/s**
| metric | Qwen3 30B (auto → q8_0) | Gemma 4 (auto → f16) | GPT-OSS (auto → f16) |
|---|---|---|---|
| tg128 | 41.4 → 42.5 | 34.4 → 34.8 → 36.7 | 35.9 → 37.1 → 37.1 |
| pp512 | 361.1 → 401.9 | 333.9 → 383.5 → 399.9 | 374.7 → 434.0 → 436.8 |
| pp4096 | 338.0 → 356.4 | 354.9 → 377.8 → 379.7 | 403.0 → 452.3 → 453.6 |
| pp @16k (≈550 new) | 124.8 → 128.2 | 211.0 → 226.4 → 231.5 | 237.3 → 258.6 → 256.6 |
| tg @16k | 20.7 → 20.9 | 25.9 → 25.8 → 27.5 | 27.7 → 28.9 → 31.1 |
| peak RSS GB | 18.7 → 18.7 | 16.4 → 16.7 → **18.4** (min free 19%) | 12.8 → 13.0 → 13.4 |
| quality (short, long) | 3/3, 3/3 | 3/3, 3/3 | 3/3, 3/3 |

- **Attribution:** most of the reading-speed gain comes from the rebase. f16 adds about 2 tok/s of writing speed on Gemma and about 2 on GPT-OSS at 16k, and costs about 1.7 GB on Gemma.
- **Run-to-run variation:** the earlier v0 numbers (runtime-compare entry) differ from tonight's v0 rerun by up to about 6% (GPT-OSS pp4096 429.5 earlier vs 403.0 tonight).
- **The limit used for the decision:** Metal `recommendedMaxWorkingSetSize` = **18186.25 MiB**. llama.cpp prints it as "19069.67 MB" (decimal), and the brief's "19069.67 MiB" mixed up the units.
- **Estimates behind the decisions:**
  - Gemma 2×18k ub2048: f16 at 18058 MiB. This is the tightest case, and it ran fine.
  - GPT-OSS: 14406 MiB.
  - Qwen 2×8k: f16 would need 19097, so q8_0.
  - Qwen 1×18k: q8_0, with a warning that it is at the edge (it works in practice).

**2. MLX inside Caravan (step a): mlx-lm 0.32.2 / mlx 0.32.4 through the proxy, local copies in `~/.exo/models`, 4k-token 3-turn chat**
| model | pp512 | pp4096 | tg128 | turn 1 / turn 2 / after restart (s) | peak footprint | quality |
|---|---|---|---|---|---|---|
| Gemma 4 26B-A4B 4-bit | 427.2 | 383.8 | 39.8 | 10.5 / **10.8** / 16.0 | 18.6 GB | 3/3, 3/3 |
| GPT-OSS 20B MXFP4-Q8 | 434.4 | 441.4 | 35.3 | 9.1 / **9.2** / 12.7 | 13.9 GB | 3/3, 3/3 |
| Qwen3 30B-A3B 4-bit | 439.4 | 395.7 | 47.0 | 7.5 / **0.44** / 16.0 | 19.0 GB | 3/3, 3/3 |

- The proxy logs `backend=mlx … cache=mlx-noop` and `slot save mlx-noop`. Save/restore is step (b), so a restart re-reads the chat. "After restart" also includes paging the weights in.
- **Turn 2 reuse:** the sliding-window models (Gemma, GPT-OSS) got no in-memory reuse between turns. Qwen did.
- **GPT-OSS:** mlx_lm has no harmony parser, so `content` contains raw `<|channel|>…` markup. The first run returned 404 on turn 2 when that text was sent back. The rerun (`m-gptoss2`) sends back only the final channel and passes.
- **Qwen:** ran out of Metal memory twice:
  - with the default prompt cache (10 sequences on the GPU)
  - with `--prompt-cache-size 2 --prompt-cache-bytes 1GiB`

  It passes (`m-qwen3`) with `--prompt-cache-size 1 --prompt-cache-bytes 512MiB --prefill-step-size 512`. This is documented in the README.

**What broke / fixes.**
- The cherry-pick conflict (above).
- 2 tests needed new expectations after the KV default changed to `auto`.
- The limit-units mix-up. I recalibrated the reserve to the measured Metal compute buffers.
- MLX GPT-OSS markup and MLX Qwen running out of memory (above).
- The box rebooted at about 21:23 CDT and lost Tailscale. I reinstalled it, and Brenden re-approved the login (the box is now `grokbot-llm-lab-1`). The suite kept running on EXO1 under nohup.

**exo / Hermes.**
- **How exo was paused (about 20:32 CDT):** I deleted instance `04297a2a…` (Qwen3.6-35B-A3B-5bit, MlxRing, Pipeline, 2 nodes), quit EXO.app on both Minis, and SIGTERMed the backend that was left running.
- **What was kept:** pre-state in `exo-state-pre-imp.json` and `exo-instance-pre-imp.json`. Config and models were not touched.
- **Current state:** exo is left paused. The Hermes gateway `/health` still answers ok, but its model backend is down.
- **To restore:**
  1. Run `open -g -a /Applications/EXO.app` on both Minis.
  2. On EXO1, POST `/place_instance` to 127.0.0.1:52415 with `{"model_id":"mlx-community/Qwen3.6-35B-A3B-5bit","sharding":"Pipeline","instance_meta":"MlxRing","min_nodes":2}`.
  3. Check `http://<EXO2-tailnet-IP>:8642/health`, then run `~/macstax/talaria_check.sh` on EXO2.

**Post status.** Not drafted. Video: LAB-2026-10-30-04 (see videos/index.md).

## 2026-10-30 — Runtime compare (LocalAI): LocalAI v4.12.1 added next to Caravan / llama.cpp / Ollama / exo, single Mac mini M4 24 GB

**Goal.** Add LocalAI to the runtime compare with the same three GGUFs and the same prompts and methods. Caravan, llama.cpp, Ollama and exo were **not** rerun; their numbers come from the entries below. Raw data: `bench-2026-10-30/runtime-compare/localai/`.

**Hardware.** EXO1 (Mac mini M4, 24 GB). exo was paused on both Minis from about 19:04 to 19:25 CDT, then restored (see below).

**Runtime.**
- LocalAI **v4.12.1** (released Oct 23, 2026). Official native macOS binary `local-ai-v4.12.1-darwin-arm64` (Apple-signed) in `~/localai-bench`. No Docker, no DMG launcher, no LaunchAgent, nothing auto-starts.
- Backend: `metal-llama-cpp` from LocalAI's backend gallery (`quay.io/go-skynet/local-ai-backends:latest-metal-darwin-arm64-llama-cpp`, digest `sha256:7d4e4b55…3908`), installed with `local-ai backends install llama-cpp`. It bundles **llama.cpp commit c0fd78626** (Metal embedded; LocalAI's launcher runs the `llama-cpp-cpu-all` binary, which is the Metal build).
- Server: `local-ai run --address 127.0.0.1:8081 --max-active-backends 1 --autoload-galleries=false --log-level debug`, with models, backends, data and config dirs all inside `~/localai-bench`.
- Models: YAML configs in `~/localai-bench/models` pointing to symlinks of the existing GGUFs. Nothing was re-downloaded. Copies are in `localai/models-yaml/`.
  - `backend: llama-cpp`, `flash_attention: on`, `gpu_layers: 999`, `mmap: true`, `use_tokenizer_template: true` (the GGUF's own chat template).
  - Options: `parallel:1`, `ubatch:512`, `cache_ram:0`.
  - `<model>-f16`: context 8192, f16 KV, used for pp, tg and quality.
  - `<model>-q8-16k`: context 18432, q8_0 KV, used for the 16k test and the resume test.
- The YAML `batch: 2048` key was ignored, and LocalAI ran with n_batch 512, the same as ubatch 512. For prompt speed the physical batch (ub 512) is what matters, so this matches llama-bench's default ub 512.
- `cache_ram:0` turns off LocalAI's default 8 GB host-RAM prompt cache. That keeps memory comparable to the other runtimes. Same-slot prefix reuse still works without it.
- Install gotcha: the first `backends install` failed because `~/.docker/config.json` names the `desktop` credential helper, which isn't installed. Fixed by pointing `DOCKER_CONFIG` at an empty config in `~/localai-bench/docker-cfg`. The user's docker config was not touched.

**Method.** Same prompts as the earlier runs (common.py), 3 reps, median, all through LocalAI's OpenAI API on :8081.
- pp512 and pp4096: `/v1/completions` with a raw prompt, a unique prefix per rep, and `max_tokens 1`.
- tg128: TG_PROMPT with `max_tokens 128`.
- Quality: short and long smoke prompts as streamed `/v1/chat/completions`.
- 16k: prime 16,384 tokens, then 3 × (≈560 new tokens + tg128).
- Resume: a 3-turn chat with about 16k tokens in turn 1. Between turns 2 and 3, LocalAI was SIGTERMed and restarted, the model was reloaded with a tiny request, and then turn 3 was sent. TTFT was measured from the stream.
- **Where the numbers come from:** LocalAI's `Extra-Usage` header returns llama.cpp's `prompt_ms` and `predicted_ms`. Its `prompt_tokens` and `completion_tokens` came back as 0 in v4.12.1, so token counts (processed tokens, excluding cached ones) were parsed from llama.cpp's own `print_timing` lines in LocalAI's debug log. These are the same llama.cpp timings as the others' "server timings".
- Memory: summed RSS of every process under `~/localai-bench` (the `local-ai` server plus its backend), sampled every 2 s.

**Results: all runtimes** (tok/s; Caravan / **LocalAI** / llama.cpp / Ollama / exo)
| metric | Qwen3-30B-A3B Q4_K_S | Gemma 4 26B-A4B Q4_0 | GPT-OSS 20B MXFP4 |
|---|---|---|---|
| tg128 | 40.8 / **45.4** / 42.9 / 45.2 / 49.6 | 34.9 / **37.6** / 37.0 / 37.2 / 41.5 | 36.3 / **36.7** / 35.8 / 36.4 / 37.1 |
| pp512 | 362.0 / **436.2** / 396.9 / 443.2 / 382.5 | 353.1 / **406.7** / 382.1 / 408.9 / 329.5 | 390.2 / **433.2** / 395.4 / 424.5 / 361.2 |
| pp4096 | 336.7 / **368.0** / 325.4 / 367.6 / 410.6 | 357.0 / **376.8** / 344.5 / 375.6 / 325.1 | 429.5 / **416.9** / 373.6 / 420.6 / 398.6 |
| pp @16k (≈560 new tok) | 121.7 / **123.5** / 123.7 / ~123 / crashed | 206.9 / **222.0** / 218.8 / ~216 / ~147 | 253.0 / **240.8** / 247.3 / ~252 / ~34 |
| tg @16k | 20.0 / **20.8** / 21.2 / 21.0 / — | 26.6 / **27.2** / 28.1 / 25.9 / 31.9 | 28.9 / **28.2** / 28.6 / 28.3 / 26.7 |
| peak memory GB | 18.7 / **18.8** / 19.4 / 19.3 / 20.4 | 16.3 / **15.8** / 15.5 / 17.3 / 18.8 | 12.9 / **12.8** / 12.8 / 13.0 / 15.0 |
| quality (short, long) | 3/3, 3/3 | 3/3, 3/3 | 3/3, 3/3 |

Rep spread was tight: pp4096 Qwen 367.8–368.2, Gemma 371.9–384.7, GPT-OSS 412.4–425.7; tg within ±0.2.
- LocalAI's main-phase peak RSS (8k context, f16 KV) was 18.42 / 15.76 / 12.57 GB. The table shows the overall peak including the 18k q8 model.
- Qwen peaked at 16% system free.
- Cold model load (first request) took 9.7–10.5 s with files in page cache. LocalAI server start took 2.1–2.6 s.

**Resume a 16k chat after a restart (TTFT, s): cold / warm in memory / after restart**
| model | Caravan | LocalAI |
|---|---|---|
| Qwen3-30B | 80.0 / 1.01 / **1.18** | 79.9 / 1.16 / **79.8** |
| Gemma 4 | 55.6 / 0.80 / 56.1 | 55.8 / 1.08 / **56.0** |
| GPT-OSS | 46.2 / 0.75 / 48.1 | 48.8 / 1.17 / **49.1** |

- LocalAI re-prefills the whole conversation after a restart (16,328 / 16,317 / 16,096 tokens reprocessed). That's expected: the llama.cpp prompt cache lives in RAM and dies with the backend.
- LocalAI does have a manual `/v1/slots/save|restore` API (needs `slot_save_path`), but nothing calls it automatically. It wasn't tested.
- All resume answers were correct (ORCHID-7419, 391, Canberra).
- Restart cost: 2.6 s server start + about 4 s model reload, not counted in TTFT. The test took about 3 minutes per model, so it ran on all three.

**Takeaways.**
- **LocalAI ≈ Ollama speed. Both are thin wrappers over llama.cpp.** LocalAI is within ±1.5% of Ollama on almost every short-context number (Qwen tg 45.4 vs 45.2, pp4096 368.0 vs 367.6), Against Caravan at short context, LocalAI is 1–11% faster on tg and 11–20% faster on pp512. Caravan uses q8_0 KV and LocalAI f16. Caravan still has the best GPT-OSS pp4096 (429.5 vs 416.9).
- **At 16k, everything llama.cpp-based is the same engine.** pp is 121–253 tok/s and tg 20–29 across Caravan, LocalAI, llama.cpp and Ollama, within about 6%.
- **Memory is the same as bare llama.cpp** (18.8 / 15.8 / 12.8 GB) once its 8 GB RAM prompt cache is turned off. With LocalAI's default `cache_ram` (8192 MiB), Qwen would likely push this 24 GB Mini into swap. Not measured.
- **Caravan's resume is the only real differentiator.** After a restart, Caravan gets Qwen's first token in 1.2 s versus 79.8 s on LocalAI, a 68× gap. For Gemma 4 and GPT-OSS both re-prefill (≈49–56 s): Caravan's sliding-window restore gap means its saved slots don't help there yet.
- **Warm in memory, LocalAI is fine on GPT-OSS** (1.17 s at 16k, versus exo 16.1 s and Ollama 2.2 s earlier).

**Deficiencies / caveats.**
- KV type differs in the short-context rows: LocalAI, llama.cpp and Ollama used f16; Caravan used q8_0. All the llama.cpp-based runtimes used q8_0 at 16k.
- The llama.cpp versions differ: LocalAI c0fd786, Caravan's patched 2f26123, Ollama's bundled build, plus the separate llama-bench build.
- LocalAI pp and tg come from llama.cpp's log timings, because the API's `prompt_tokens` came back as 0. Its `timing_*` ms fields matched the log values.
- exo uses MLX conversions of the models. exo and Ollama 16k pp values are approximate.
- Single node, single run per config, files in page cache.

**Suggested tweaks.**
- LocalAI on 24 GB Macs: set `cache_ram` explicitly (0, or about 2048) for 30B-class models, and `parallel:1`. Its auto `parallel` is VRAM-scaled and can over-allocate.
- If Brenden wants LocalAI as a serving option, a Caravan-like resume could be bolted on with `slot_save_path` plus `/v1/slots/save|restore` calls from a proxy. That's the same SWA caveat for Gemma 4 and GPT-OSS.

**What broke / fix.**
- First suite attempt: the LocalAI usage token counts were 0, which caused a divide-by-zero in the script, caught within 1 minute. Partial logs are in `localai/aborted-1/` on EXO1. Fix: parse llama.cpp `print_timing` lines.
- Backend install: Docker credential helper (see Runtime).

**Cleanup / restore.**
- LocalAI was stopped, with no processes left. It's still installed in `~/localai-bench` (about 270 MB). No LaunchAgent, no login item.
- exo relaunched on both Minis and placed Qwen3.6-35B-A3B-5bit Pipeline/MlxRing min_nodes 2. Both runners are RunnerReady with the same split as before (exo02 layers 0–19, exo01 19–40).
- Hermes `/health` returned ok (0.20.5). talaria_check passed every check.
- Evidence: `runtime-compare/restore-evidence.txt`, `pre3/`, `exo-state-post3.json`. Ollama is untouched (installed, not running).

**Post status.** Drafted (daily thread, Oct 30, awaiting approval). Video v3: `videos/2026-10-30_runtime-compare_caravan-localai-llamacpp-exo_v3.mp4` (LAB-2026-10-30-03).

## 2026-10-30 — Runtime compare (Caravan): Caravan proxy + llama-server vs llama.cpp / Ollama / exo, single Mac mini M4 24 GB

**Goal.** v1 of the runtime compare left Caravan out: its "llama.cpp" column was the bare engine (`llama-bench`), not requests going through Caravan. This run puts all three suite-1 models through Caravan end to end, single node, and measures its headline feature: resuming a long conversation from a slot saved to disk after a full server+proxy restart. Raw data: `bench-2026-10-30/runtime-compare/caravan/`.

**Hardware.** EXO1 (Mac mini M4, 24 GB). exo was paused on both Minis from 17:17 to 17:45 CDT, then restored (see below). No RPC, no second Mini.

**Runtime.** Caravan `~/dev/caravan` at HEAD 45ed2c2, unmodified, nothing committed.
- llama-server: Caravan's `caravan-patches` build (`~/dev/llama.cpp`, 2f26123). The command line was built by Caravan's own `supervisor.build_head_command` with no peers (so no `--rpc`). The only change was `--slot-save-path`, pointed at a bench-only directory.
- Proxy: `proxy/slot_pin_proxy.py` on :8090 with `CARAVAN_SLOT_CLEANUP=off`, a bench `CARAVAN_SLOT_SAVE_DIR`, a bench `CARAVAN_PROXY_STATE_FILE`, `CARAVAN_N_SLOTS` = `--parallel`, and `CARAVAN_CONFIG` pointed at a nonexistent file (Caravan defaults plus the overrides below).
- Common flags: `--no-kv-unified -fa on -ngl 999 -ctk q8_0 -ctv q8_0 --cache-ram 0 -b 2048`. **KV is q8_0, Caravan's default.**
- Every request went **through the proxy**. pp/tg come from llama-server's `timings` in the proxied response.

**Models / per-model settings.**
| model | GGUF | slots × ctx | -ub |
|---|---|---|---|
| Qwen3-30B-A3B Q4_K_S | `~/.caravan/models/Qwen3-30B-A3B-Q4_K_S.gguf` | 2 × 8192 (main, quality); **1 × 18432** (16k + resume) | 1024 |
| Gemma 4 26B-A4B Q4_0 | `~/.caravan/models/gemma-4-26B_q4_0-it.gguf` | 2 × 18432 | 2048 |
| GPT-OSS 20B MXFP4 | HF blob `27cd6c43…5901` (the suite-1 file) | 2 × 18432 | 2048 |

Qwen at 2 × 18432 and at 2 × 12288 both failed with Metal `kIOGPUCommandBufferCallbackErrorOutOfMemory` on the first request. Weights are 17.5 GB against a ≈19.07 GB Metal limit, so there is only room for about 1 GB of KV plus compute buffers. 2 × 8192 worked for the standard metrics. The 16k and resume tests used one 18k slot.

**Method.** Same prompts as the Ollama runs (common.py builders), 3 reps, median.
- pp512/pp4096: raw `/completion` through the proxy, with a unique prefix per rep.
- tg128: same as the Ollama method.
- Quality: smoke short + long chat prompts via `/v1/chat/completions`.
- 16k: prime 16k, then 3 × (≈550 new tokens + tg128) on the same pinned session.
- Memory: summed RSS of llama-server, sampled every 2 s.
- Resume test, a 3-turn chat:
  - t1: ≈16k-token log + question, cold.
  - t2: follow-up, warm in memory.
  - Then SIGTERM both llama-server and the proxy, and restart both.
  - t3: follow-up. The proxy restores the saved slot from disk.
  - TTFT is streamed through the proxy.
  - Save/restore times come from direct `/slots?action=save|restore` calls on the same 16k slot.
  - A second, prefix-exact variant uses raw `/completion` with no chat template.

### Comparison table (Caravan column added)
Caravan figures use q8_0 KV. The llama.cpp, Ollama and exo main numbers are f16 KV from the entries below. Ollama q8 numbers are in brackets for a like-for-like check.

| metric | model | **Caravan** | llama.cpp (bare) | Ollama | exo |
|---|---|---|---|---|---|
| tg128 tok/s | Qwen | **40.8** | 42.9 | 45.2 (q8 43.8) | 49.6 |
| | Gemma | **34.9** | 37.0 | 37.2 (q8 35.0) | 41.5 |
| | GPT-OSS | **36.3** | 35.8 | 36.4 (q8 35.6) | 37.1 |
| pp4096 tok/s | Qwen | **336.7** | 325.4 | 367.6 (q8 354.0) | 410.6 |
| | Gemma | **357.0** | 344.5 | 375.6 (q8 357.7) | 325.1 |
| | GPT-OSS | **429.5** | 373.6 | 420.6 (q8 416.3) | 398.6 |
| pp512 tok/s | Qwen | **362.0** | 396.9 | 443.2 (q8 437.6) | 382.5 |
| | Gemma | **353.1** | 382.1 | 408.9 (q8 401.9) | 329.5 |
| | GPT-OSS | **390.2** | 395.4 | 424.5 (q8 408.5) | 361.2 |
| pp @16k tok/s | Qwen | **121.7** | 123.7 | ~123 | crashed |
| | Gemma | **206.9** | 218.8 | ~216 | ~147 |
| | GPT-OSS | **253.0** | 247.3 | ~252 | ~34 |
| tg @16k tok/s | Qwen | **20.0** | 21.2 | 21.0 | — |
| | Gemma | **26.6** | 28.1 | 25.9 | 31.9 |
| | GPT-OSS | **28.9** | 28.6 | 28.3 | 26.7 |
| peak memory GB | Qwen | **18.7** | 19.4 | 19.3 | 20.4 |
| | Gemma | **16.3** | 15.5 | 17.3 | 18.8 |
| | GPT-OSS | **12.9** | 12.8 | 13.0 | 15.0 |
| quality | all | **pass** (short + long: ORCHID-7419 / 391 / Canberra, clean stop) | 4/4 | 4/4 | 4/4 except exo Qwen |

Caravan's pp512 is the lowest GGUF number on every model. Part of that is method: llama-bench measures pure prefill, while the server number includes per-request setup on a short prompt. Caravan's peak memory for Gemma (16.3 GB) is above bare llama.cpp because there are 2 × 18k slots allocated.

### Resume-from-saved-slot (Caravan only) — 16k-token conversation
| model | t1 cold TTFT | t2 warm in memory | **t3 after full restart (slot restored from disk)** | slot file (16k) | save / restore | server+proxy restart |
|---|---|---|---|---|---|---|
| Qwen3-30B-A3B | 80.0 s (16,259 tok) | 1.01 s | **1.18 s** (cache_n 16,298, 30 new tok) | 852 MB | 0.18 s / 0.26 s | 1.5 s |
| Gemma 4 26B-A4B | 55.6 s (16,249 tok) | 0.80 s | **56.1 s** (cache_n 0: full re-prefill) | 291 MB | 0.09 s / 0.11 s | 2.1 s |
| GPT-OSS 20B | 46.2 s (16,000 tok) | 0.75 s | **48.1 s** (cache_n 0: full re-prefill) | 213 MB | 0.07 s / 0.06 s | 1.5 s |

- The prefix-exact raw variant confirms the pattern:
  - Qwen: 4.7 s after restart (cache_n 16,611) vs 81.2 s cold.
  - GPT-OSS: 50.4 s after restart (cache_n 0).
  - Gemma: 59.2 s after restart (cache_n 0).
- The proxy did restore in every case. Its log reads `restored slot 0 from disk … (16137 tokens)`, `cache=restored`. llama-server then discarded the restored cache for the two sliding-window-attention models.
- `server-context.cpp` forces "full prompt re-processing due to lack of cache data (likely due to SWA…)" unless a context checkpoint exists. Checkpoints live only in memory and aren't part of the slot file, so restored SWA slots can't be reused.
- **Reference: existing warm-cache 16k TTFT, no restart** (from the entries below): GPT-OSS ≈550 new tokens on a 16k cache, Ollama 2.2 s vs exo 16.1 s. Ollama and exo were **not** tested after a restart (scope cut). Neither has a disk-persisted KV slot, so expect a full re-prefill there, but that's unmeasured.
- Restart and restore times are with the GGUF and slot file in the OS page cache, which is the best case. A cold-disk restore of an 852 MB file will take longer.

### Takeaways
- **Caravan's headline feature works for Qwen3-30B.** A 16k conversation resumes after a full restart in **1.2 s instead of 80 s (≈68× faster)**, about the same as staying warm in memory (1.0 s). The cost is an 852 MB slot file per 16k session and about 0.2 s to save it.
- **It doesn't work on Gemma 4 or GPT-OSS today.** The slot restores, but llama-server re-prefills all 16k tokens (48–56 s) because of their sliding-window layers. This is the most important fix for Caravan. Options: persist SWA context checkpoints with the slot, or use `--swa-full` for these models (costs memory; untested).
- **Throughput through Caravan ≈ bare llama.cpp.** tg is within −6% to +1% and the 16k numbers are within 6%. pp4096 is higher than llama-bench on all three (server-path ubatch 1024/2048 vs llama-bench defaults).
- **Caravan isn't the fastest runtime.** Ollama (newer llama.cpp) beats it on pp512 everywhere and on pp4096 for Qwen/Gemma. exo/MLX still leads decode on all three. With matched q8 KV, Caravan vs Ollama on pp4096 is −5% Qwen, −0.2% Gemma, +3% GPT-OSS.
- **Memory is tight for Qwen.** Caravan's multi-slot design can't hold two 12k slots with Qwen3-30B on one 24 GB Mini. 2 × 8k or 1 × 18k is the limit.

**Deficiencies.**
- Caravan main numbers use q8 KV while the other runtimes' main numbers use f16. The Ollama q8 brackets give the like-for-like check.
- Qwen main/quality and the 16k/resume runs used different slot configs.
- Caravan quality used only the q8 short/long checks; the f16 pair wasn't rerun.
- Resume was measured warm-page-cache only, one run per model.
- Ollama/exo after-restart TTFT wasn't measured (scope cut at 17:36).

**Suggested tweaks.** Persist SWA checkpoints in slot save/restore (patch in caravan-patches), or test `--swa-full` for Gemma/GPT-OSS. Make the proxy log restore time. Size Qwen slots by default (≤ 2 × 8k) on 24 GB nodes.

**What broke / fix.** Qwen at 2 × 18k and 2 × 12k ran out of Metal memory, so I used 2 × 8k / 1 × 18k. Nothing else broke.

**Cleanup / restore.**
- Removed only the 32 bench slot `.bin` files I created under `runtime-compare/caravan/*/slots/` (listing kept in `slot-files-before-cleanup.txt`).
- Not touched: `~/.caravan/proxy/session_slots.json` (still 932 B, Oct 30 05:41) and `~/.caravan/llama-server/slots`.
- Caravan server/proxy stopped; Ollama not running.
- exo restarted on both Minis at 17:45 CDT and placed `mlx-community/Qwen3.6-35B-A3B-5bit` Pipeline/MlxRing min_nodes 2. Runners: exo02 layers 0–19 rank 0, exo01 layers 19–40 rank 1, both RunnerReady. Before the run it was 0–18/18–40; exo picks the split by memory and it can't be pinned.
- Hermes `/health` 200 `{"status":"ok","version":"0.20.5"}`. talaria_check.sh: all PASS.

**Post status:** Drafted (daily thread, Oct 30, awaiting approval).

## 2026-10-30 — Runtime compare (summary): llama.cpp vs Ollama vs exo, single Mac mini M4 24 GB

**Goal.** Run the suite-1 models through two more runtimes on the same box (EXO1) and compare them with the llama.cpp suite-1 numbers. Details are in the Ollama and exo entries below. Raw data: `bench-2026-10-30/runtime-compare/`.

**Hardware.** EXO1, Mac mini M4 24 GB, macOS 26.6.2. exo was paused on both Minis for the Ollama phase. For the exo phase, exo ran on EXO1 only (1-node topology, `min_nodes 1`). Every exo result below is a true single-node result.

**Method notes (read before comparing).**
- pp numbers:
  - llama.cpp: `llama-bench`.
  - Ollama: server-reported `prompt_eval` rate from `/api/generate` (raw, unique prefix per rep, no cache reuse).
  - exo: the `/bench/chat/completions` endpoint's `prompt_tps` (MLX prefill rate). In brackets is the streamed-TTFT rate, which includes about 0.2-0.3 s of API/queue overhead and so understates short prompts.
- tg128:
  - llama.cpp: `llama-bench`.
  - Ollama: `eval` rate.
  - exo: streamed chunk rate (bench endpoint in brackets).
- 3 reps, median. f16 KV unless noted.
- 16k depth: a 16k prime prompt, then about 550 new tokens on top, with tg128 after that.
  - llama.cpp `-d 16384`: q8_0 KV.
  - Ollama: q8_0 KV. pp@16k = new tokens / (prompt_n / prompt_tps), which uses Ollama's own timing, with the cache hit.
  - exo: MLX has no KV-quant knob, so fp16 KV. pp@16k = new tokens / TTFT.
- Peak memory:
  - llama.cpp: `time -l` max RSS.
  - Ollama: summed RSS of `ollama serve` + its bundled `llama-server` (it can double-count mmapped weights).
  - exo: MLX `peak_memory_usage` from the bench endpoint.
  - These are close but not identical metrics.
- Quality: the 4 smoke.py checks (short + long prompt; code, multiplication, capital; plus completion). Same max_tokens as suite 1 (Qwen 200 with /no_think, Gemma 1000, gpt-oss 800).

### Qwen3-30B-A3B
| runtime (quant) | pp512 | pp4096 | tg128 | 16k pp / tg | peak mem | quality |
|---|---|---|---|---|---|---|
| llama.cpp (Q4_K_S GGUF) | 396.9 | 325.4 | 42.9 | 123.7 / 21.2 (q8 KV) | 17.8-19.4 GB RSS | 4/4 |
| Ollama 0.40.13 (same Q4_K_S blob) | 443.2 (q8: 437.6) | 367.6 (q8: 354.0) | 45.2 (q8: 43.8) | ~123 / 21.0 (q8 KV) | 19.3 GB RSS, min free 11% | 4/4 |
| exo 1.0.71 MLX (mlx-community 4bit) | **382.5** [317.5] | **410.6** [397.0] | **49.6** [49.3] | not obtained (runner abort) | 20.4 GB MLX peak | correct when it answered; long prompt aborted the runner 2 of 3 times |

### Gemma 4 26B-A4B
| runtime (quant) | pp512 | pp4096 | tg128 | 16k pp / tg | peak mem | quality |
|---|---|---|---|---|---|---|
| llama.cpp (Q4_0 GGUF) | 382.1 | 344.5 | 37.0 | 218.8 / 28.1 (q8 KV) | 14.9-15.5 GB RSS | 4/4 |
| Ollama (same Q4_0 blob) | **408.9** (q8: 401.9) | **375.6** (q8: 357.7) | 37.2 (q8: 35.0) | ~216 / 25.9 (q8 KV) | 17.3-19.3 GB RSS* | 4/4 (thinking 270-494 tok) |
| exo MLX (mlx-community 4bit) | 329.5 [267.0] | 325.1 [312.6] | **41.5** [41.0] | ~147 / **31.9** (fp16 KV) | 18.8 GB MLX peak | 4/4 ×2 (580 reasoning tok on short) |

\*Gemma's Ollama f16 RSS (19.3 GB) probably double-counts the serve + llama-server mmaps. The d16k run read 15.95 GB.

### GPT-OSS 20B
| runtime (quant) | pp512 | pp4096 | tg128 | 16k pp / tg | peak mem | quality |
|---|---|---|---|---|---|---|
| llama.cpp (MXFP4 GGUF) | 395.4 | 373.6 | 35.8 | 247.3 / **28.6** (q8 KV) | 12.2-12.8 GB RSS | 4/4 |
| Ollama (same MXFP4 blob) | **424.5** (q8: 408.5) | **420.6** (q8: 416.3) | 36.4 (q8: 35.6) | ~252 / 28.3 (q8 KV) | 12.8-13.0 GB RSS, free ≥39% | 4/4 |
| exo MLX (mlx-community MXFP4-Q8) | 361.2 [297.3] | 398.6 [388.7] | **37.1** [36.1] | ~34 (TTFT 16.1 s) / 26.7 (fp16 KV) | 14.3 GB (15.0 GB at 16k) | 4/4 ×2 |

### Takeaways
- **Ollama ≈ newer llama.cpp.** Ollama 0.40 runs a bundled `llama-server` (`-b 512 -ub 512 -fa on -ngl 999`, chatml/no-jinja for raw GGUFs). It matched or beat our llama.cpp `caravan-patches` build on every model: pp512 +7-12%, pp4096 +9-13%, tg +0-5%. The 16k numbers are within 2%. The gain is the newer upstream build, not something specific to Ollama. Caveat: the pp methods differ (server timing vs llama-bench).
- **exo/MLX wins decode on MoE.** tg128 was Qwen 49.6 vs 42.9 (+16%), Gemma 41.5 vs 37.0 (+12%), GPT-OSS 37.1 vs 35.8 (+4%). Qwen pp4096 on MLX (410.6) is the best long-prompt number of the day, but Gemma/GPT-OSS prefill on MLX trails GGUF by 5-15%.
- **exo is the least robust single-node.** It uses the most memory: 20.4 GB for Qwen and 18.8 GB for Gemma, vs 19.3/17.3 GB for Ollama. Qwen's runner aborted (signal 6, mid-prefill) on a repeated 6.9k-token chat, twice across 3 attempts. Gemma's runner aborted on the 17k bench-endpoint request. GPT-OSS (the smallest) ran clean. Long context is where a 24 GB Mini runs out of headroom under MLX without KV quantization.
- **At 16k depth**, exo's prefix cache worked for Gemma (about 560 new tokens in 3.8 s) but only partly for GPT-OSS: 16 s TTFT, vs 2.2 s for Ollama. That's likely the sliding-window layers forcing a partial re-prefill. Gemma tg at 16k was best on exo (31.9 vs 28.1/25.9).
- **Quality** was identical where runs completed: every runtime gave ORCHID-7419 / 391 / Canberra.

**Post status:** not drafted.

## 2026-10-30 — Runtime compare (exo): Qwen3-30B-A3B / Gemma 4 26B-A4B / GPT-OSS 20B on exo 1.0.71 MLX, single Mac mini (EXO1)

**Goal.** Run the suite-1 metrics on exo's MLX engine, one node, for comparison with llama.cpp and Ollama.

**Hardware.** EXO1 (M4, 24 GB). EXO.app started on EXO1 only at 15:41:44 CDT; exo stayed stopped on EXO2, so the topology was 1 node. Every placement was `Pipeline/MlxRing, min_nodes 1`; the log shows "Single device used".

**Runtime.** EXO.app 1.0.71. API on 127.0.0.1:52415.
- `/bench/chat/completions`: prompt_tps, generation_tps, peak_memory_usage.
- `/v1/chat/completions`: streaming with include_usage, for TTFT/tg and quality.

**Models.** All downloaded through exo's `/download/start` on EXO1 only.
- `mlx-community/Qwen3-30B-A3B-4bit` (17.19 GB)
- `mlx-community/gemma-4-26b-a4b-it-4bit` (15.37 GB)
- `mlx-community/gpt-oss-20b-MXFP4-Q8` (12.10 GB)

**Setup.**
- Script: `scripts/exo_suite.py` → `exo_bench.py <tag> <model> <max_tokens>`. For each model: place, wait for RunnerReady, then run phases main (pp512/pp4096/tg128 ×3, streamed plus a bench-endpoint run), quality (×2), d16k (16k prime, then 3 reps of about 550 new tokens + tg128, plus a bench-endpoint run). Delete the instance afterwards.
- Ran under nohup on EXO1, 15:43-16:04 CDT. Qwen retry (quality,d16k) 16:05-16:06 CDT (`exo_retry.py`).
- Raw output: `runtime-compare/exo/`.

### Results (medians; bench-endpoint values in brackets)
| model | pp512 | pp4096 | tg128 | MLX peak | quality |
|---|---|---|---|---|---|
| Qwen3-30B-A3B 4bit | 317.5 [382.5] | 397.0 [410.6] | 49.6 [49.3] | 20.42 GB | short 2/2 OK; long 1/3 OK, 2 runner aborts |
| Gemma 4 26B-A4B 4bit | 267.0 [329.5] | 312.6 [325.1] | 41.5 [41.0] | 18.84 GB | 4/4 ×2 |
| GPT-OSS 20B MXFP4-Q8 | 297.3 [361.2] | 388.7 [398.6] | 37.1 [36.1] | 14.27 GB | 4/4 ×2 |

16k depth (fp16 KV):

| model | prime 16k | new tokens / TTFT | tg128 @16k | notes |
|---|---|---|---|---|
| Qwen | — | — | — | not obtained; the runner aborts before reaching it |
| Gemma | 16,640 tok @ 261 tok/s | ~555 / 3.79 s ≈ 147 tok/s | 31.9 | bench-endpoint re-run at 17.2k → HTTP 500 (runner signal 6) |
| GPT-OSS | 16,376 @ 332 tok/s | ~551 / 16.1 s ≈ 34 tok/s | 26.7 | cache only partly reused; bench full 16.9k cold @ 332 tok/s, peak 15.02 GB, min free 31% |

### Quality
- Gemma: `ORCHID-7419 / 391 / Canberra`, short and long, twice. It reasons a lot: 580 reasoning tokens on the short prompt and 367 on the long.
- GPT-OSS: correct on all four, twice. Same formatting drift as llama.cpp: trailing double spaces, numbering dropped on the long prompt.
- Qwen: correct on every response it produced (short ×3, long ×1). On 2 of 3 long (6,918-token) requests the runner died mid-prefill.

### Takeaways
- MLX gives the fastest decode on all three MoEs. Its Qwen pp4096 beats GGUF. Gemma/GPT-OSS prefill is slower than GGUF.
- Streamed TTFT has about 0.25 s of fixed overhead, so pp512 measured end to end looks 15-20% worse than the engine rate.
- Memory is the problem. MLX peak on Qwen hit 20.4 GB of 24 GB, and MLX has no KV quantization here. Runner aborts were mid-prefill (log: "Starting prefill" → about 5-18 s later "Runner terminated with signal=6"). That looks like a Metal allocation abort, not an exo bug.

### Deficiencies observed
- A dead runner returns an empty 200 body on `/v1/chat/completions` (non-streaming) and a 500 on `/bench`. A client sees an empty body, not an error. Hermes would need to handle that.
- Every runner also shows `RunnerFailed signal=6` on normal instance DELETE (teardown). That's harmless, but it makes real crashes harder to spot in `/state`.
- Node IDs change on every exo restart, so state comparisons must use friendlyName.
- The GPT-OSS prefix cache only partly hits at 16k (16 s TTFT for about 550 new tokens, vs 2.2 s on Ollama). That's bad for multi-turn agents on long contexts.
- The placement API can't pin the layer split or rank order. The split comes from free memory at placement time.

### Suggested tweaks
- This would be more robust if single-node exo serving of 30B-class 4-bit MoEs were capped at about 8k context, or if exo used a KV-quantized cache once MLX/exo exposes one.
- This would be faster if Hermes-style short turns used Qwen3-30B on MLX (49.6 tg, the best of the day), but only 2-node or at short contexts.
- This would be more robust if the client treated an empty 200 body from exo as a retryable error.
- This would be faster for long multi-turn GPT-OSS on exo if the prefix cache handled sliding-window layers. Until then, use llama.cpp/Ollama for GPT-OSS long-context work.

**What broke / fix.**
- `exo/` output dir was missing for the nohup redirect: mkdir, then restarted the suite at 15:43.
- Qwen runner aborts: one retry with a fresh instance reproduced the abort, so it's reported as a deficiency, not fixed.
- Gemma's d16k bench call hit a 500; the streamed d16k data was kept.

**Restore.**
- exo was restarted on EXO2 at 16:06:57 CDT. At 16:07:51 the same `place_instance` as suite 1 (Qwen3.6-35B-A3B-5bit, Pipeline/MlxRing, min_nodes 2) went out, and both runners were RunnerReady at 16:08:06.
- Tiny chat OK at 16:08:29.
- Hermes `/health` returned `{"status": "ok", ... "0.20.5"}` at 16:08:31. `talaria_check.sh` passed all 6 checks. Hermes gateway pid 1027 was never restarted.
- One difference from pre-state: the split is 18/22 with EXO2 as rank 0 (pre: 20/20, EXO1 rank 0). It's chosen by exo's memory-based placement.
- exo/Hermes model downtime: 15:17:29 → 16:08:29 CDT (about 51 min).
- Evidence: `runtime-compare/restore-evidence.txt`, `exo-state-post.json`.

**Post status:** not drafted.

## 2026-10-30 — Runtime compare (Ollama): Qwen3-30B-A3B Q4_K_S / Gemma 4 26B-A4B Q4_0 / GPT-OSS 20B MXFP4, Ollama 0.40.13, single Mac mini (EXO1)

**Goal.** The same suite-1 metrics through Ollama, using the exact GGUF blobs from suite 1, to separate runtime effects from quant effects.

**Hardware.** EXO1, M4 24 GB, macOS 26.6.2. exo paused on both Minis (15:17:29 / 15:17:44 CDT). Phase ran 15:18-15:41 CDT.

**Runtime.**
- Ollama 0.40.13 CLI from the official GitHub release `ollama-darwin.tgz` (signed, TeamIdentifier 3MU9H2V9Y9), unpacked to `~/ollama-bench/`. No app and no launch agent.
- Underneath it runs a bundled `llama-server`: `-c 8192 -np 1 --no-jinja --chat-template chatml --flash-attn on -b 512 -ub 512 -ngl 999 --context-shift --keep 4`, with `--cache-type-k/v` f16 or q8_0 via `OLLAMA_KV_CACHE_TYPE`. Captured in `ollama/qwen-llama-server-cmdline.txt`.
- Prior state: not installed and not running. Left installed but stopped.

**Models.** Created with `ollama create` from the suite-1 GGUF files (copied into `~/.ollama`, 41 GB):
- `rc-qwen3-30b-a3b-q4ks` (template from the GGUF)
- `rc-gemma4-26b-q4_0` (gemma4 renderer/parser, thinking on)
- `rc-gpt-oss-20b-mxfp4`

Modelfiles are in `runtime-compare/modelfiles/`.

**Setup.**
- `scripts/ollama_bench.py` via `ollama_suite.sh`, under nohup. Uses `/api/generate` raw with a unique prefix per rep (no cache reuse) and Ollama's timing fields.
- Runs: f16 KV, then q8_0 KV. Each runs pp512/pp4096/tg128 ×3 plus quality (short/long). Then d16k at q8_0.
- Memory sampler: summed RSS of `ollama-bench/` processes. Qwen was re-run (`-rerun`) after fixing the sampler pattern.

### Results (median tok/s)
| model | KV | pp512 | pp4096 | tg128 | peak RSS | min free |
|---|---|---|---|---|---|---|
| Qwen Q4_K_S | f16 | 443.2 (rerun 450.6) | 367.6 (364.8) | 45.2 | 19.26 GB | 11% |
| Qwen Q4_K_S | q8_0 | 437.6 (412.1) | 354.0 (342.9) | 43.8 (42.9) | 19.11 GB | 16% |
| Gemma Q4_0 | f16 | 408.9 | 375.6 | 37.2 | 19.32 GB* | 27% |
| Gemma Q4_0 | q8_0 | 401.9 | 357.7 | 35.0 | 17.33 GB | 27% |
| GPT-OSS MXFP4 | f16 | 424.5 | 420.6 | 36.4 | 12.96 GB | 40% |
| GPT-OSS MXFP4 | q8_0 | 408.5 | 416.3 | 35.6 | 12.83 GB | 40% |

16k depth, q8_0 KV:

| model | prime | pp of about 550 new tok @16k | tg128 @16k | peak RSS |
|---|---|---|---|---|
| Qwen | 16,602 @ 202 tok/s | ~123 | 21.0 | 18.93 GB (min free 14%) |
| Gemma | 16,601 @ 292.5 | ~216 | 25.9 | 15.95 GB |
| GPT-OSS | 16,328 @ 339.9 | ~252 | 28.3 | 12.81 GB |

\*Probably double-counts mmaps.

### Quality
4/4 on every model, both KV types.
- Qwen: `1) ORCHID-7419 / 2) 391 / 3) Canberra`, 26 tokens.
- Gemma: thinks for 270-494 tokens.
- GPT-OSS: 84-219 tokens, with the same formatting drift.

### Takeaways
- Ollama is effectively a newer llama.cpp. On the same GGUF files, it beat our llama.cpp build on prefill by 7-13% and matched or edged it on tg (+0-5%). The 16k results are within noise of llama.cpp.
- The q8_0 vs f16 KV gap is similar to llama.cpp: up to 5% on pp4096, 2-6% on tg.
- Qwen runs closest to the memory limit (11% free at f16, 8k context).

### Deficiencies observed
- Ollama's default batch is `-b 512`; Caravan uses `-b 2048 -ub 512`. Raising it (for example via the `num_batch` option) was not tested here, so llama.cpp's +9.6% pp4096 ub-2048 gain wasn't tried under Ollama.
- Raw GGUFs get chatml + `--no-jinja` unless the Modelfile carries a template. I had to take the template from the GGUF for Qwen and GPT-OSS.
- `ollama create` copies the blob, so it costs another 41 GB of disk.

### Suggested tweaks
- Faster: Caravan would gain about 10% on prefill by rebasing its llama.cpp patches onto the upstream build Ollama 0.40 bundles.
- More robust: Ollama with q8_0 KV is a quick single-node fallback for Hermes if exo is down (same quality, comparable speed).

**What broke / fix.**
- The first memory-sampler pattern missed the `llama-server` child (RSS 0.04 GB). Fixed the pattern and re-ran Qwen.
- The footprint parse was wrong. Fixed, but after GPT-OSS ran, so its footprint field is 0 (its RSS is valid).
- The Tailscale SOCKS link dropped twice. Jobs survived because they ran under nohup.

**Post status:** not drafted.

## 2026-10-30 — Suite 1 (3/3): GPT-OSS 20B MXFP4, single Mac mini M4 24 GB, llama.cpp Metal

**Goal.** Same matrix as 1/3 and 2/3, plus the Caravan smoke test and quality check, to finish the suite-one comparison.

**Hardware.** Same as 1/3: EXO1, Mac mini M4 24 GB, macOS 26.6.2, Metal working set 19,069.67 MB, `iogpu.wired_limit_mb=0`. exo was paused on both Minis; swap held at 478 MB.

**Runtime.** llama.cpp `caravan-patches`: llama-bench 6a1a922, llama-server 2f26123. `-ngl 999`, Metal, 4 threads (default).

**Model.**
- Source: `ggml-org/gpt-oss-20b-GGUF` / `gpt-oss-20b-MXFP4.gguf`, used directly from the HF cache blob `~/.cache/huggingface/hub/models--ggml-org--gpt-oss-20b-GGUF/blobs/27cd6c43…5901`. The blob name is its LFS sha256; it was not re-hashed this run. 12,109,566,624 bytes (11.27 GiB, 4.63 BPW); Metal buffer 11,536 MiB.
- `~/.caravan/models/gpt-oss-20b.gguf` is a broken symlink to an Ollama blob. It was left untouched, as asked.
- Arch `gpt-oss`: 20.91B params MoE, 32 experts with 4 active, 24 layers, 8 KV heads, trained context 131,072.
- Attention alternates sliding-window (`n_swa` 128) and full layers. It always reasons, using the harmony format with separate `reasoning_content`.

**Setup.** Identical `bench.sh` steps. Smoke with max_tokens 800. Raw output: `bench-2026-10-30/gpt-oss-20b-mxfp4/`.

### Results (tok/s, mean ± sd)

| config | pp512 | pp4096 | tg128 | peak RSS* |
|---|---|---|---|---|
| (a) fa off, KV f16 | 399.7 ± 0.8 | 341.8 ± 1.0 | 34.8 ± 0.1 | 12.23 GB (whole run) |
| (a) fa on, KV f16 | 395.4 ± 0.7 | 373.6 ± 0.7 | 35.8 ± 0.0 | (same run) |
| (b) fa on, KV q8_0 | 392.3 ± 0.4 | 372.7 ± 0.9 | 35.1 ± 0.6 | 12.37 GB |
| (c) fa on, q8_0, ub 512 | 400.7 ± 11.1 | 372.6 ± 0.9 | 35.7 ± 0.3 | 12.47 GB |
| (c) fa on, q8_0, ub 1024 | 396.6 ± 5.7 | 395.3 ± 0.6 | 36.2 ± 0.2 | |
| (c) fa on, q8_0, ub 2048 | 389.7 ± 2.9 | **408.5 ± 0.3** | 36.1 ± 0.3 | |
| (c2) ub 2048 repeat, verbose | 403.4 ± 11.7 | 408.2 ± 0.5 | 36.2 ± 0.2 | 12.47 GB |

Long-context rows (fa on, ub 512):

| config | pp512 @ depth | tg128 @ depth | peak RSS* |
|---|---|---|---|
| f16 KV, depth 8192 | 303.9 ± 0.0 | 32.9 ± 0.0 | 12.75 GB |
| q8_0 KV, depth 8192 | 305.2 ± 0.3 | 31.2 ± 0.5 | 12.55 GB |
| q8_0 KV, depth 16384 | 247.3 ± 0.2 | 28.6 ± 0.0 | 12.78 GB |

\*`time -l` max RSS including mmapped weights. System free memory never went below 32%. No new swap. No OOM anywhere.

### Caravan smoke test

Same hand-started lead (`-c 16384 --parallel 2 --no-kv-unified -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 -b 2048 -ub 512`, no `--rpc`) plus `slot_pin_proxy.py` on :8090. Ready in about 1 s.

| request | prompt tok | pp tok/s | gen tok | gen tok/s | wall |
|---|---|---|---|---|---|
| chat via proxy, first | 73 (harmony preamble) | 113 | 333 (reasoning + answer) | 36.2 | 9.8 s |
| same chat via proxy, repeated | 5 (cache warm) | 54 | 333 | 35.7 | 9.4 s |
| short quality, q8_0 KV | 64 | 140 | 219 | 35.4 | 6.6 s |
| long quality (5,713 tok), q8_0 KV | 5,713 | 349 | 87 | 32.4 | 19.0 s |
| short, f16 KV | 124 | 164 | 224 | 36.6 | 6.9 s |
| long (5,653 tok), f16 KV | 5,653 | 357 | 84 | 33.6 | 18.3 s |

- Proxy: pinned slot 0, saved to disk after turn 1 (a 7 MB slot file), and turn 2 was `cache=warm`. Reply: "Hello, how are you today?".
- Disk restore after a server restart was not re-tested.
- Prompt-token counts differ between the q8 and f16 servers because of prefix reuse within a server; `prompt_n` counts only uncached tokens.
- Its tokenizer packs the same long text into about 5.7k tokens, vs 6.9k for Qwen and 7.1k for Gemma.

### Quality check

Greedy, same prompt as 1/3; reasoning always on (default effort).

- **All four correct**: `ORCHID-7419 / 391 / Canberra`, short and long, q8_0 and f16 KV.
- On the long prompts the reasoning was short (84-87 tokens total). On the short prompts it rambled (about 220 tokens).
- Minor format drift: it dropped the "1) 2) 3)" numbering and added trailing double spaces (markdown line breaks).
- No KV-precision difference visible. Same caveat: sanity check, not an eval.

### Takeaways per item
- **(a) fa:** the biggest fa win of the three models at long prompts: pp4096 +9.3% (342 → 374) and tg +2.9%. pp512 is a wash (-1%). Keep `-fa on`.
- **(b) q8_0 vs f16 KV:** basically free. pp512 -0.8%, pp4096 -0.2%, tg -2%; at 8k depth pp is flat and tg -5%. It saves about 0.2 GB.
- **(c) ubatch:** `-ub 2048` gives pp4096 408.5 vs 372.6 (+9.6%), the fastest long-prompt number of the suite. ub 1024 gives +6%. tg is unchanged.
- **Depth:** the most resilient of the three. pp 395 → 304 at 8k → 247 at 16k (2× Qwen at 16k); tg 35.8 → 32.9 → 28.6.
- **Memory:** the lightest. Peak RSS 12.2-12.8 GB and at least 32% free, so it can share the Mini with other services.
- **End to end:** the fastest long-prompt turn of the suite (18-19 s for about 5.7k tokens, including reasoning), helped by the denser tokenizer.

### Deficiencies observed
- Always reasons. Even "say hello in five words" costs about 330 generated tokens (about 9.5 s). Short-turn latency is dominated by reasoning, not throughput.
- The harmony preamble adds about 60-70 prompt tokens to every fresh conversation.
- Lowest short-context tg of the three (35.8 vs Qwen 42.9), despite fewer active params. It's fastest everywhere else.
- Minor answer formatting drift (numbering dropped, trailing spaces).
- The canonical `~/.caravan/models/gpt-oss-20b.gguf` symlink is broken, so Caravan configs pointing there won't start. This run used the HF blob path directly.

### Suggested tweaks
- This would be a little faster if Caravan used `-ub 2048` for this model (+9.6% on long prompts; it has 6+ GB of headroom).
- This would be a little faster (perceived) if requests set a lower reasoning effort (for example `"reasoning_effort": "low"` or the `chat_template_kwargs` equivalent; untested here) for chat-style turns.
- This would be more robust if q8_0 KV were used by default for this model: it costs almost nothing, so more slots or more context fit.
- This would be more robust if Caravan's single-node profile allowed a longer total context for this model (for example 4 × 16k at q8_0). Memory allows it, and depth degradation is mild.
- This would be more robust if the broken `gpt-oss-20b.gguf` symlink were repointed at the HF blob (needs your OK; not touched).
- MXFP4 is the native release format, so there's no Q4_K_M/Q5_K_M trade-off to make. Larger quants (Q8_0/F16 of the non-MoE tensors) would fit for a quality check.
- Thread count isn't relevant with full offload.

**What broke / fix.** Nothing broke. No OOM, every config ran, smoke and quality passed first try.

**Suite restore (all three models).**
- exo was relaunched on both Minis at 07:38 CDT with `open -g -a EXO.app`. Both nodes were in the topology by 07:38:50.
- At 07:38:55 CDT, `place_instance` was sent for Qwen3.6-35B-A3B-5bit (Pipeline/MlxRing, min_nodes 2). It created instance 94a1664c with layers 0-20 / 20-40 and worldSize 2. Both runners were RunnerReady at 07:39:16.
- A tiny chat via EXO2 127.0.0.1:52415 succeeded at 07:39:23 CDT. `talaria_check.sh` passed all checks: hub, calendar, hermes /health 200, exo chat, vet server, and "exo still serving only Qwen".
- Hermes was never restarted: gateway pid 1027 stayed running throughout.
- Total exo downtime: pause started at 06:53:02 CDT; service was back at 07:39:23 CDT, so about **46 min 21 s**. exo was fully down from 06:54:31 to 07:39:16.

**Post status:** not drafted.

## 2026-10-30 — Suite 1 (2/3): Gemma 4 26B-A4B Q4_0, single Mac mini M4 24 GB, llama.cpp Metal

**Goal.** Same matrix as entry 1/3: fa on/off, f16 vs q8_0 KV, `-ub` 512/1024/2048, depth 8k/16k, peak memory. Then Caravan's lead-only server (no packers) plus proxy smoke test, and the short/long × f16/q8_0 quality check, to compare with Qwen3-30B-A3B on the same box.

**Hardware.** Same as 1/3: EXO1, Mac mini M4 24 GB, macOS 26.6.2, Metal working set 19,069.67 MB, `iogpu.wired_limit_mb=0`. exo was paused on both Minis; vet-pilot was up. Swap stayed at 478 MB for the whole run.

**Runtime.** llama.cpp `caravan-patches`: llama-bench 6a1a922, llama-server 2f26123. `-ngl 999`, Metal.

**Model.**
- File: `~/.caravan/models/gemma-4-26B_q4_0-it.gguf`, 14,439,363,584 bytes (13.43 GiB, 4.57 BPW). sha256 `3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d` (hashed on the Mini this run).
- Source: downloaded 2026-09-10. The download log has no URL and the GGUF `general.name` is just "Hf", so the exact repo is unrecorded.
- Arch `gemma4`, 26B.A4B MoE: 25.23B params, 128 experts with 8 active, 30 layers, trained context 262,144.
- Attention is mostly sliding-window: `n_swa` = 1024 with 256-dim heads. Every 6th layer is global (2 KV heads × 512-dim). That's why depth hurts it far less than Qwen.

**Setup.** Identical to 1/3: `bench.sh` steps A/B/C/C2/D, `-r 3` (`-r 2` for depth), `-b 2048 -ub 512` unless noted, `/usr/bin/time -l`, memory sampled every 5 s. Raw output: `bench-2026-10-30/gemma4-26b-q4_0/` (bench, first smoke run) and `bench-2026-10-30/gemma4-26b-q4_0-smoke2/` (smoke re-run with a bigger token budget).

### Results (tok/s, mean ± sd)

| config | pp512 | pp4096 | tg128 | peak RSS* |
|---|---|---|---|---|
| (a) fa off, KV f16 | 372.2 ± 0.4 | 347.3 ± 0.1 | 35.8 ± 0.6 | 14.92 GB (whole run) |
| (a) fa on, KV f16 | **382.1 ± 0.9** | 344.5 ± 4.6 | **37.0 ± 0.0** | (same run) |
| (b) fa on, KV q8_0 | 377.0 ± 1.1 | 325.2 ± 1.4 | 35.5 ± 0.0 | 14.87 GB |
| (c) fa on, q8_0, ub 512 | 366.0 ± 11.1 | 323.4 ± 0.2 | 35.5 ± 0.1 | 15.13 GB |
| (c) fa on, q8_0, ub 1024 | 355.2 ± 1.0 | 346.7 ± 0.2 | 34.4 ± 0.8 | |
| (c) fa on, q8_0, ub 2048 | 356.0 ± 5.8 | **360.4 ± 0.2** | 35.6 ± 0.1 | |
| (c2) ub 2048 repeat, verbose | 361.4 ± 10.1 | 360.7 ± 0.0 | 35.6 ± 0.1 | 15.12 GB |

Long-context rows (fa on, ub 512):

| config | pp512 @ depth | tg128 @ depth | peak RSS* |
|---|---|---|---|
| f16 KV, depth 8192 | 268.6 ± 0.1 | 31.5 ± 0.0 | 15.54 GB |
| q8_0 KV, depth 8192 | 266.6 ± 0.4 | 29.2 ± 2.6 | 15.13 GB |
| q8_0 KV, depth 16384 | 218.8 ± 0.6 | 28.1 ± 0.2 | 15.33 GB |

\*`time -l` max RSS, which includes mmapped weights. System free memory bottomed at 19% (ub runs) and 25-27% otherwise. No new swap.

- **ub 2048 fits here.** The compute buffer is 2,092 MiB at pp4096 (vs 529 MiB at ub 512), on top of about 13.4 GiB of weights. That leaves roughly 2 GiB of headroom under the Metal limit.

### Caravan smoke test

The lead was started from Caravan's `build_head_command()` (internal name) minus `--rpc`, with the same flags as Qwen: `-c 16384 --parallel 2 --no-kv-unified -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 -b 2048 -ub 512`. `slot_pin_proxy.py` ran by hand on :8090 with cleanup off. Ready in 2-6 s.

Run 2 below uses max_tokens 1000. Run 1 used 300, and Gemma's thinking used up that budget on the long prompts.

| request | prompt tok | pp tok/s | gen tok | gen tok/s | wall |
|---|---|---|---|---|---|
| chat via proxy, first | 22 | 77 | 388 (thinking + answer) | 35.3 | 11.3 s |
| same chat via proxy, repeated | 5 (cache warm) | 58 | 388 | 35.3 | 11.1 s |
| short quality, q8_0 KV | 71 | 144 | 270 | 35.4 | 8.1 s |
| long quality (7,129 tok), q8_0 KV | 7,129 | 315 | 494 | 31.3 | 38.4 s |
| short, f16 KV | 78 | 132 | 295 | 36.4 | 8.7 s |
| long (7,122 tok), f16 KV | 7,122 | 311 | 495 | 31.3 | 38.7 s |

- Proxy: pinned slot 0, saved it to disk after turn 1, and turn 2 was `cache=warm` (5 new prompt tokens). Reply: "Hello, how are you today?".
- The restore-from-disk-after-server-restart path was **not** re-tested for this model; the Qwen run covered it.
- Slot files were about 38-49 MB for 320-410 tokens, roughly 7× GPT-OSS's 7 MB for 405 tokens. That matters for Caravan's slot-dir disk use.

### Quality check

Greedy (temperature 0, seed 1), same needle/17×23/capital prompt as 1/3. Gemma 4 thinks by default; there is no `/no_think` switch, so NO_THINK was empty.

- **Run 2 (max_tokens 1000): all four correct and identical**: `1) ORCHID-7419 / 2) 391 / 3) Canberra`, short and long, q8_0 and f16 KV. The reasoning quoted the needle verbatim from the long log.
- **Run 1 (max_tokens 300):** short prompts correct. Both long prompts returned **empty content** with `finish_reason=length`: about 300 tokens of thinking, no answer yet.
- So there was no retrieval or KV-precision problem at about 7k. The failure is the thinking budget.
- Same caveat as 1/3: this is a sanity check, not an eval.

### Takeaways per item
- **(a) fa:** small win. pp512 +2.7%, tg +3.4%; pp4096 is flat (-0.8%, within noise). Keep `-fa on`.
- **(b) q8_0 vs f16 KV:** q8_0 costs pp4096 -5.6% and tg -4.1%; at 8k depth it's pp -0.7% and tg -7%. Memory saved is small, because SWA layers keep KV tiny (8k depth f16 15.54 GB vs q8_0 15.13 GB). Same answers.
- **(c) ubatch:** `-ub 2048` is the best long-prompt setting: pp4096 360 vs 323 at ub 512 (+11.4%), with tg unchanged and pp512 slightly lower. ub 1024 lands in between (+7.2%).
- **Depth:** degrades gently thanks to SWA. pp 382 → 269 at 8k → 219 at 16k (Qwen: 397 → 198 → 124). tg 37 → 31.5 → 28.1 (Qwen: 43 → 31 → 21). From 8k on it beats Qwen on both.
- **Memory:** 1.5-4 GB lighter than Qwen at peak. Free memory never went below 19%.
- **Thinking is on by default:** a five-word greeting costs about 390 generated tokens (11 s), so latency is dominated by reasoning tokens, not tok/s.

### Deficiencies observed
- Thinking-by-default inflates every reply (270-500 tokens for a three-line answer) and silently produced empty answers at 300 max_tokens. Any Caravan client with a low `max_tokens` will see blank replies.
- pp at ub 512 sags at 4k (323) relative to pp512; it's fixed by a bigger ubatch.
- Slot save files are about 7× larger per token than GPT-OSS's.
- Model provenance isn't recorded (no URL in the download log; generic `general.name`).
- At ub 512, pp512 stddev was ±11 on one run. That's minor thermal or noise variance.

### Suggested tweaks
- This would be a little faster if Caravan used `-ub 2048` for this model on one node (+11% on long prompts; it fits with about 2 GiB to spare).
- This would be a little faster if KV stayed f16 (+4-6%). q8_0 saves only about 0.4 GB here because of SWA, so it isn't worth it unless you run many slots.
- This would be a little faster (perceived) if thinking were turned off or bounded for chat-style turns, via the chat template's thinking toggle in `chat_template_kwargs` or a system-prompt switch, whichever this GGUF's template supports (untested).
- This would be more robust if Caravan clients sent max_tokens ≥ 1024 (or checked `finish_reason=length` with empty `content`) when talking to Gemma 4.
- This would be more robust and still fit with a better quant: at 13.4 GiB there is about 4 GB of headroom, so a Q4_K_M or Q5_K_M (around 16-18 GB) would likely fit for higher quality (needs a download; not done).
- This would be more robust if the GGUF's source and hash were recorded next to the file. The hash is above.
- Thread count isn't relevant with full offload.

**What broke / fix.** The first smoke run's long prompts came back empty because thinking used up the 300 max_tokens. Fixed by re-running the smoke with max_tokens 1000 (`gemma4-26b-q4_0-smoke2/`). Nothing else failed; no OOM.

**Post status:** not drafted.


## 2026-10-30 — Suite 1 (1/3): Qwen3-30B-A3B Q4_K_S, single Mac mini M4 24 GB, llama.cpp Metal

**Goal.** Find out how fast and how tight a ~17 GB 4-bit MoE runs on one 24 GB Mini with llama.cpp. Settle three Caravan flag questions on real numbers:
- flash attention on or off;
- f16 vs q8_0 KV cache;
- `-ub` 512, 1024 or 2048.

Then check Caravan's lead-only server (no packers) and proxy path, plus a quick quality check of q8_0 vs f16 KV at short and long context.

**Hardware.**
- EXO1: Mac mini M4 (Mac16,10; 10-core CPU, 4P+6E), 24 GB, macOS 26.6.2.
- Metal `recommendedMaxWorkingSetSize` = 19069.67 MB (~18186 MiB). `iogpu.wired_limit_mb` = 0 (the default).
- exo was paused on both Minis for the run. EXO1's free memory went from 36% to 90%, swap from 4.0 GB to 0.48 GB.
- Nothing else heavy was running; vet-pilot stayed up.

**Runtime.** llama.cpp `caravan-patches` fork:
- llama-bench build 6a1a922 (2026-09-05);
- llama-server branch tip 2f26123 (2026-09-08).

Full GPU offload (`-ngl 999`), Metal and BLAS backends, everything run by hand from SSH.

**Model.**
- File: `unsloth/Qwen3-30B-A3B-GGUF` / `Qwen3-30B-A3B-Q4_K_S.gguf`, 17,456,009,792 bytes (16.26 GiB). The weights load as a 16,642 MiB Metal buffer.
- sha256 `fa0c96bed61759800bcab82a8a44a8effcd92cdd8bced06b8195232237390b4a`: matches the HF LFS oid and was verified on the Mini.
- Original Qwen3 MoE: 30.5B total, about 3B active, 48 layers, 4 KV heads × 128.
- Why Q4_K_S: it's the ~17 GB 4-bit option; Q4_K_M at 18.56 GB was too tight. Alternatives were IQ4_XS (16.38 GB) and UD-Q4_K_XL (17.72 GB).

**Setup.**
- llama-bench, `-r 3` (`-r 2` for the depth rows), `-o json`.
- Defaults: `-b 2048 -ub 512` unless noted. Each run wrapped in `/usr/bin/time -l`.
- Memory sampled every 5 s with `memory_pressure` and `vm.swapusage`.
- Raw output: `bench-2026-10-30/qwen3-30b-a3b-q4ks/` (`*.json` results, `*.err` stderr including `time -l`, `mem-*.log`, smoke logs, scripts).

### Results (tok/s, mean ± sd)

| config | pp512 | pp4096 | tg128 | peak RSS* |
|---|---|---|---|---|
| (a) fa off, KV f16 | 375.0 ± 2.6 | 303.4 ± 0.2 | 41.0 ± 0.4 | 17.76 GB (whole run) |
| (a) fa on, KV f16 | **396.9 ± 2.5** | 325.4 ± 4.5 | **42.9 ± 0.2** | (same run) |
| (b) fa on, KV q8_0 | 391.7 ± 2.9 | 310.1 ± 1.9 | 40.9 ± 0.6 | 17.83 GB |
| (c) fa on, q8_0, ub 512 | 387.2 ± 7.3 | 307.1 ± 0.2 | 39.7 ± 0.2 | 17.87 GB |
| (c) fa on, q8_0, ub 1024 | 374.1 ± 8.5 | **334.4 ± 0.4** | 41.0 ± 0.3 | |
| (c) fa on, q8_0, ub 2048 | 371.8 ± 5.8 | **FAILED: Metal OOM** | -- | |

Long-context rows (fa on, ub 512; `-d` = tokens already in the KV cache):

| config | pp512 @ depth | tg128 @ depth | peak RSS* |
|---|---|---|---|
| f16 KV, depth 8192 | 198.3 ± 0.0 | 30.8 ± 0.4 | 19.21 GB |
| q8_0 KV, depth 8192 | 187.2 ± 0.3 | 27.9 ± 0.6 | 18.50 GB |
| q8_0 KV, depth 16384 | 123.7 ± 0.0 | 21.2 ± 0.3 | 19.38 GB |

\*Peak RSS is `time -l` "maximum resident set size", which includes the mmapped weights. System free memory bottomed at 12-18%. Swap stayed at 478 MB throughout, so there was no new swapping.

**ub 2048 failure.** From the verbose re-run (`C2_ub2048_v.err`): at a 4096-token context with ub 2048, the compute buffer is 1203 MiB (vs 301 MiB at ub 512). Add the 16,642 MiB of weights and 204 MiB of KV, and Metal fails with `kIOGPUCommandBufferCallbackErrorOutOfMemory` and `failed to decode prompt batch, res = -3`. pp512 at ub 2048 still ran, since its ubatch is capped at 512.

### Caravan smoke test

The lead was started by hand from Caravan's own `build_head_command()` (internal name) without `--rpc`:

```
-c 16384 --parallel 2 --no-kv-unified -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 -b 2048 -ub 512
```

- `slot_pin_proxy.py` ran by hand on :8090, with its slot dir and state file under the bench dir. No launchd involved.
- The server was ready in about 0.9 s because the weights were already in the page cache from llama-bench.

| request | prompt tok | pp tok/s | gen tok | gen tok/s | wall |
|---|---|---|---|---|---|
| chat via proxy, first ("Say hello in five words.") | 18 | 61 | 11 | 41.7 | 0.55 s |
| same chat via proxy, repeated | 1 (cache hit) | -- | 12 | 42.3 | 0.29 s |
| short quality prompt, q8_0 KV | 73 | 152 | 26 | 41.9 | 1.1 s |
| long quality prompt (6,915 tok), q8_0 KV | 6,915 | 293 | 26 | 29.9 | 24.4 s |
| short, f16 KV | 73 | 129 | 26 | 42.8 | 1.2 s |
| long, f16 KV | 6,915 | 292 | 26 | 32.3 | 24.5 s |

Bonus: the second smoke run's very first request found its slot saved on disk by the first run, after a full llama-server restart. It needed 1 prompt token instead of 18, so the proxy's disk restore works with this model.

### Quality check

Greedy decoding (temperature 0, seed 1), `/no_think`. The prompt asks for:
- a needle ("vault access code is ORCHID-7419");
- 17×23;
- the capital of Australia.

The short version asks right after the needle. The long version buries the needle at line 61 of a 290-line inventory log (6,915 tokens).

- **All four runs** (q8_0 and f16 KV, short and long) gave the identical answer: `ORCHID-7419 / 391 / Canberra`. All correct.
- No quant artifacts, repetition or formatting drift were seen.
- This is a sanity check, not an eval. It's an easy retrieval at about 7k tokens; it can't show subtle q8_0 degradation or problems past 8k.

### Takeaways per item

- **(a) Flash attention:** a small but consistent win. pp +6-7%, tg +4.6%. Keep `-fa on` (Caravan's default).
- **(b) q8_0 vs f16 KV:**
  - Cost of q8_0: pp4096 -4.7%, tg -4.5% at short context; tg -9% and pp -6% at 8k depth.
  - What it buys: about half the KV memory. That's what lets a 16k depth fit (19.38 GB peak) under the 19.07 GB Metal working set.
  - Same answers on the quality check.
- **(c) ubatch:** `-ub 1024` gives +8.9% on pp4096 (334 vs 307) with no tg change, and is slightly slower on pp512 (within noise-ish). `-ub 2048` OOMs at a 4k context on this machine.
- **Long context:** depth hurts much more than any flag.
  - pp: 397 → 198 at 8k → 124 at 16k.
  - tg: 43 → 31 → 21.
- **Caravan defaults don't fit one node with this model.**
  - 4 slots × 65,536 at q8_0 is about 13.7 GB of KV on top of 16.3 GiB of weights.
  - On a single 24 GB Mini a realistic total `-c` is about 16-24k (2 slots × 8-12k).

### Deficiencies observed
- Metal OOM at `-ub 2048` (pp4096). The headroom between weights and the working-set limit is only about 1.5 GiB.
- Prompt processing degrades steeply with context depth (124 tok/s at 16k). A cold 16k prompt costs about 2+ minutes before the first token.
- Generation drops by half by 16k depth.
- Peak RSS reached 19.2-19.4 GB at 8k (f16) and 16k (q8_0) depth, with system free memory down to 12-13%. Nothing else big can run alongside.
- The quality check is too easy to separate the KV types. There's no perplexity number.

### Suggested tweaks
- This would be a little faster if Caravan used `-ub 1024` (+9% on long prompts) for this model on one node. Keep `-b 2048`.
- This would be a little faster if KV stayed f16 whenever the total context is ≤ about 8k (+5-9%). q8_0 is only worth it when it's needed to fit more context or slots.
- This would be more robust if the quant were IQ4_XS (16.38 GB, about 1 GiB smaller). That leaves room for `-ub 1024/2048` and longer contexts without hitting the Metal limit; quality cost to be verified. Q4_K_M (18.56 GB) would leave almost no headroom on 24 GB.
- This would be more robust if `iogpu.wired_limit_mb` were raised modestly (for example to about 20-21 GB). This is a system setting, so it needs your OK, and it squeezes macOS and the other services.
- This would be more robust if Caravan's single-node profile capped the context at about 16-24k total (for example `--n-slots 2 --ctx-per-slot 8192`, or 12288 with q8_0) instead of the 4×65k two-node default.
- Thread count doesn't matter here: with full GPU offload the CPU only handles about 167 MiB of tensors.
- Next quality step: `llama-perplexity` on a fixed text, f16 vs q8_0 KV, and a multi-needle test at 16k.

**What broke / fix.**
- `-ub 2048` hit a Metal OOM. It was isolated with a verbose re-run; no fix needed, just don't use it at this size.
- The first quality prompt was 10,040 tokens and was rejected (400, larger than the 8,192-token slot). Shortened to 6,915 tokens and re-run.

**Post status:** not drafted.
