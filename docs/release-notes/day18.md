# Day 18

Safer split models, downloads that resume, GGUF peers loading from their own disk, and more Optimize now coverage.

## What changed

**Downloads and loading**
- **Load now / Not now:** when a download finishes and no model is loaded, Caravan asks before loading. It never loads silently.
- **Real Resume:** weight files (MLX shards and GGUF) resume from where they stopped using HTTP Range, instead of restarting the file. Verified live on both Minis.
- **Progress fix:** split downloads no longer overcount bytes or show a false "stalled?".
- **Saved split point:** `caravan-placement.json` records `packer_layers`/`n_stages`, so the picker, inventory and load agree (fixed Dark Champion 21B showing "missing shards on EXO1").
- **Split point safety:** split downloads now default to a balanced point for each Mini's RAM. If a saved point would leave a Mini under the 1.75 GB margin, the picker shows "⚠ Split:" with the balanced point and any extra files needed, and the load uses the balanced point when the files are there. Nothing downloads automatically. Tonight's numbers for Dark Champion 21B 8-bit (32 layers, ~0.71 GB/layer, two 24 GB Minis): **24/8 left EXO2 1.51–1.71 GB free and every chat returned 507; 16/16 (~11.3 GB per Mini) worked at 14.2–20.0 tok/s write, 117.8–140.7 tok/s read.**

**Correct output**
- **Tie-embedding gibberish fix:** models whose config ties the input and output word tables but whose files also ship a separate output table (Dark Champion 21B) no longer produce gibberish when split. Caravan follows the config, and a split stage now refuses to run with missing weights instead of filling them with random values. Verified live: coherent replies at 16/16.
- **Rope scaling:** about 40 mlx_lm model classes (mixtral, qwen3_moe, phi3, gemma2 and others) ignore `rope_scaling`. Caravan now applies it after load (llama3, yarn, dynamic, linear) in single-Mini and split runs.
- **MTP-aware split planning:** `mtp.*` weights go to the lead only, nextn layers go to neither Mini, and helper heads (`*_mtp`/`*_nextn`) are refused for splitting.

**Picker**
- **Plain-language warnings:** risky checkpoints get a ⚠ in the picker plus a line under it saying what's off, whether the model still runs, and what to do.
- **Report this model:** that line has a link that opens a prefilled GitHub issue (label `model-report`). It contains only the model id, the warning text, the Caravan version, `model_type` and the tie flag. You review it and submit it yourself; Caravan never sends it.
- **Opt-in warning ping:** off by default. If `CARAVAN_ALERT_WEBHOOK_URL` (and optionally `CARAVAN_ALERT_WEBHOOK_KEY`) is set, the web server POSTs `{model, warnings, mini, caravan_version}` once per model and warning set, in the background with a 5 s timeout.

**GGUF (llama.cpp)**
- **GGUF stage 2:** GGUF downloads go to every online Mini. At a split load, each peer fills its rpc-server cache from its own copy, so its share no longer crosses the link. Live: 43 tensors / 0.8 GB seeded in 6.2 s on qwen2.5-3b; Qwen3-30B-A3B EXO2 share 73 tensors / 8.41 GB in 19.0 s, with hashes matching llama.cpp.
- **GGUF Optimize now:** the button now runs the llama.cpp tuner on GGUF models (flash attention, ubatch). It reloads twice per option and keeps a challenger only if it's more than 3% faster. Progress, ETA, Pause and Cancel work like MLX, and winners are used on the next load.

**Logging**
- **Per-reply timing line:** the MLX worker now logs, for every reply (single Mini and split), `timing (single|split): read X tok (C cached) at Y tok/s, write Z tok at W tok/s, first token A s, total B s` next to the existing answer line in `lead.log`, matching the stats under each reply in the chat window. Takes effect on the next model load.

**Optimize now (MLX)**
- New sweep options: native MTP and adaptive prompt lookup, tried last, one at a time, with the same 3% margin.

## Install

Download **caravan-day18.zip** or **caravan-day18.tar.gz**, extract it, and follow
**INSTALL.md** in the root. [Read the guide online](https://github.com/linuxbren/caravan/blob/day18-2026-11-07/INSTALL.md).
Model execution needs Apple Silicon Macs. Source packages don't bundle models, Python,
dependencies or compiled llama.cpp, and lab video media is left out.
This is experimental software, not a signed Mac installer.

Upgrading from Day 17: `git pull --ff-only` on each Mini (or extract the new package over a clean copy). Then restart only the web server on the lead, with `CARAVAN_WEB_KEEP_WORKERS=1`.

## Checks and limits

- Box test suite: **486 OK** (33.8 s) at the release commit (484 before the timing log; 2 new tests). A fresh source-package test runs after publishing and is logged in the day record.
- Verified live on the Minis: Resume (EXO1 and EXO2), GGUF stage 2 (3B), the saved split hotfix, and the Dark Champion tie fix at 16/16.
- Brenden's test session (Dark Champion 21B, 16/16 split, 7:27–7:46 PM CT): 31 turns, context 854 → 5,849 tokens. Learned write speed averaged 11.96 tok/s over 29 replies with guess-ahead on vs 11.31 tok/s over 3 with it off; about 13.7 early, sliding to about 12. Lead peak memory 13.07 GB. No 507 refusals, no gibberish; one harmless BrokenPipe about 7:42 PM CT.
- After pulling e9159c8 on both Minis and restarting only the EXO1 web server (`CARAVAN_WEB_KEEP_WORKERS=1`), the loaded model stayed up (same lead worker adopted). The picker data shows the ⚠ warning for Dark Champion, the page has the Report this model link, and `split_check` reports 16/16 OK (5.49/6.79 GB free; balanced 15/17), so no split warning shows, which is correct.
- **Not yet run live:** the GGUF Optimize now runner, the MLX MTP/lookup sweeps, the ⚠ Split warning on a tight split, the rope scaling and timing log lines (both need a model reload), clicking Report this model, and the opt-in ping.
- **llama.cpp upgrade: partial.** "Before" numbers were recorded on 6a1a922 (qwen2.5-3b 50.6 tok/s on one Mini; Qwen3-30B-A3B 34.4 one Mini / 35.1 split). The build of upstream 76a67730 was stopped for live testing and both Minis were restored to 6a1a922. The new build is still pending.
- MLX split is still two stages. The split-safety math covers any number of Minis, but the runtime loads on 2.
- Qwen3.6-35B-A3B with a helper was investigated only. Native MTP needs MoE head support and split-mode MTP.

Full details and every test result, including failures: [Day 18](https://github.com/linuxbren/caravan/blob/day18-2026-11-07/docs/DAY18.md).
Daily release policy: [RELEASES.md](https://github.com/linuxbren/caravan/blob/day18-2026-11-07/docs/RELEASES.md).
