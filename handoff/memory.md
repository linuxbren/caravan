# The old assistant's durable memory (export, Oct 31 2026)

All 27 facts the old assistant had stored: 19 profile facts, 6 journal entries, and 2 facts
shared from Brenden's other assistant ("Console Places Dev & Promotion"). They're copied
word for word with their dates. Four of them were cut off by the memory tool's display
limit; those end in **[…cut off in the export]**, followed by what is known from elsewhere.
Nothing secret was stored in memory: the Mini password is only named
(`MINI_SSH_PASSWORD`), never its value.

Some facts are from before later decisions. Where a newer rule overrides an older fact, the
**Note** says so. `handoff/README.md` is the up-to-date picture.

## Profile (standing facts and preferences)

1. (2026-10-30) My job: document Brenden's homebrew, mad-scientist-style local LLM experiments on his Mac Minis and turn them into X posts; the running log is /workspace/llm-lab/experiments.md (date, goal, hardware, runtime, model and quant, config, results, what broke, fix, post status).
   - Note: a copy of the log is in this repo at `handoff/lab/experiments.md`.
2. (2026-10-30) Verified Oct 30, 2026: Brenden's lab is two Mac mini M4 (Mac16,10, 10-core, 24 GB, 500 GB, macOS 26.6.2), Tailscale hosts prf-hays-exo01 and prf-hays-exo02; they run the EXO app (exo), not Ollama, and are cabled directly over Thunderbolt/USB4 at 40 Gb/s; SSH as user brenden with password (Tailscale SSH is off); the password is supplied via secret MINI_SSH_PASSWORD; my computer joins his tailnet as grokbot-llm-lab with userspace tailscaled and reaches SSH through SOCKS5 localhost:1055 with parami **[…cut off in the export]**
   - Known from elsewhere: "…with paramiko" (see `handoff/tools/rc.py`). After the box rebooted on Oct 30 (about 21:23 CDT), it re-joined as `grokbot-llm-lab-1`.
3. (2026-10-30) Brenden's Mini stack: Nous Research's Hermes Agent v0.20.5 (desktop app, gateway via launch agent ai.hermes.gateway, API server) runs on prf-hays-exo02 and uses the exo cluster (exo1+exo2) at 127.0.0.1:52415 with mlx-community/Qwen3.6-35B-A3B-5bit at 64k context; Hermes isn't running on exo01 (leftovers and a 2026-09-29 macstax backup only); exo is separate and doesn't wrap Hermes.
4. (2026-10-30) Brenden must approve every X post before it goes out: draft posts in chat, revise until he approves, then hand him an x.com/intent/post link with the text so he presses Post himself; never post on his behalf.
5. (2026-10-30) Caravan's baseline for all future comparison graphs is "Caravan v0", commit 45ed2c2, benchmarked Oct 30, 2026 on one Mini (see experiments.md "Runtime compare (Caravan)"). Daily posts cover what we worked on, the stats compared with that v0 baseline and the other runtimes, and what's next. Improvement order: (1) a fork patch so slot restore works on sliding-window models (Gemma 4, GPT-OSS), (2) f16 KV when it fits, (3) per-model profiles, (4) a llama.cpp rebase, (5) proxy per-request overhead, ( **[…cut off in the export]**
   - Note: this order was replaced by fact 6 and later by `docs/ROADMAP.md`.
6. (2026-10-30) Caravan roadmap decision (2026-10-30): Brenden wants "best of both worlds," with MLX support added as item 2, right after the sliding-window slot-restore fork patch. The MLX plan has three steps: (a) the proxy routes MLX models to an mlx-lm backend on one Mini, (b) MLX KV cache save/restore, (c) a two-Mac MLX split via mlx.distributed or by driving exo. The remaining items (f16 KV, per-model profiles, rebase, proxy overhead, memory, cold restore) follow.
   - Note: (a) became v1, (b) v2/v2.1, and (c) v3, built as Caravan's own lead/packer link rather than mlx.distributed or exo.
7. (2026-10-30) Lab videos convention: each video gets an ID LAB-YYYY-MM-DD-NN and a filename /workspace/llm-lab/videos/YYYY-MM-DD_topic-slug_vN.mp4, and is logged in /workspace/llm-lab/videos/index.md with its ID, date, file, title, source experiment, duration, and post status. Brenden does not want the ID or filename stamped inside the video.
8. (2026-10-31) Brenden's GitHub username is linuxbren.
9. (2026-10-31) Brenden wants daily reminders (including weekends) both about needing to do work on Caravan and to post about progress.
   - Note: see `handoff/routines.md`.
10. (2026-10-31) Brenden wants Caravan's docs/ROADMAP.md kept current with every change, including a "Deferred / parked" section so nothing we pass on gets lost.
11. (2026-10-31) Brenden wants Caravan to move toward split downloads for both MLX and GGUF, where the head and each tail Mini download only their own model parts from the source instead of the head relaying them (requested Oct 31, 2026).
    - Note: in today's names, the lead and each packer download only their own parts. It became the firm rule "each packer keeps its share of the model on its own disk" (ROADMAP, Firm rules).
12. (2026-10-31) Caravan naming convention (chosen Oct 31, 2026): the Mini that talks to the user, picks each token, and runs the last layers is the "lead"; the other Minis are "packers," numbered in layer order (Packer 1 runs the first layers); the whole group is the "string." Never use head/front/tail in videos, posts, or docs.
13. (2026-10-31) Lab video title slides show the day of development (e.g. "Day 3") instead of the calendar date, matching the day of the post the video goes with.
14. (2026-10-31) Every Caravan X post starts with the day of development, e.g. "Day 1 of building Caravan in the open...". Day 1 is Oct 30, 2026, and each later calendar day counts up from there (Oct 31 = Day 2).
15. (2026-10-31) Every Caravan X post opens with the day plus a short plain summary of what Caravan is, e.g. "Day 2 of building Caravan in the open, my homebrew app for running AI models across my Mac minis."
16. (2026-10-31) Lab videos (and posts) target hobbyists, so use plain-language labels with as few acronyms as possible. For example, say "writing speed" not tg128, "reading speed" not pp, "wait before the first word" not TTFT, and avoid on-screen terms like KV, q8_0, f16, SWA, and ub. Explain tokens as about ¾ of a word.
17. (2026-10-31) Benchmark videos should show both Caravan's latest version and the one before it (e.g. Caravan v0 vs v1) alongside the other runtimes.
18. (2026-10-31) Caravan's patched llama.cpp fork is at linuxbren/llama.cpp (caravan-patches branch for the current version; prior version kept as caravan-patches-v0), and Caravan docs point there.
19. (2026-10-31) The Mini's llama.cpp checkout uses the linuxbren/llama.cpp fork as its main remote; the Mini's saved GitHub login is RookiOS72, so pushes to the fork go through the assistant's computer (signed in as linuxbren).

## Journal (dated events)

1. (2026-10-30) 2026-10-30: Brenden approved a benchmark plan. Suite 1 runs on one Mini with exo paused: Qwen3 30B-A3B 4-bit (first run in progress), Gemma 4 26B 4-bit (already on EXO1), GPT-OSS 20B (already on EXO1). Suite 2 splits those three across both Minis over Thunderbolt, plus Qwen3 30B-A3B 8-bit and the GGUF of Qwen3.6 35B-A3B. Each run is logged with its numbers, a takeaway, the deficiencies seen, and "would be faster/more robust if" tweak suggestions. Exo must be restored after each session; no new d **[…cut off in the export]**
   - Note: "restore exo after each session" was relaxed by journal 6.
2. (2026-10-30) 2026-10-30 2:10 PM: Brenden approved a runtime comparison of the three suite-1 models (Qwen3 30B-A3B 4-bit, Gemma 4 26B 4-bit, GPT-OSS 20B). The order is Ollama first, then exo with those models in place of its current one, then exo restored to its pre-test config (Qwen3.6-35B-A3B-5bit, Pipeline/MlxRing, 2 nodes) and Hermes rechecked.
3. (2026-10-30) 2026-10-30: Runtime comparison done on EXO1 alone. Ollama 0.40.13 (installed in ~/ollama-bench, 41 GB of models in ~/.ollama, not running) was 7–13% faster at prompt processing than our llama.cpp on the same GGUFs. Exo MLX was fastest at generation (Qwen 49.6 tok/s) but crashed on Qwen long prompts, and its MLX models are on EXO1 ~/.exo/models (about 45 GB). Exo was restored with a 18/22 layer split, EXO2 first, instead of the original 20/20. Hermes health is ok, and it only listens on the Tails **[…cut off in the export]**
   - Known from elsewhere: Hermes's gateway listens on EXO2's Tailscale address, port 8642 (`/health`).
4. (2026-10-30) 2026-10-30: Added configurable model (--model/CARAVAN_MODEL/~/.caravan/config.json) and stale slot cleanup (proxy/slot_cleanup.py, default delete >30 days) to Caravan on EXO1 ~/dev/caravan, uncommitted on main; warned Brenden that the next proxy start would delete all 269 slot files (~165 GB) unless CARAVAN_SLOT_CLEANUP=off/archive; muse-glimmer is missing from EXO1's Ollama store.
   - Note: these were committed later (3287f51); EXO1 `~/dev/caravan` is now clean on main at c026359.
5. (2026-10-31) 2026-10-30 8:16 PM: Brenden said exo and Hermes can stay down for the next few days while we work on Caravan improvements. They matter long-term, so keep them restorable, but there's no need to restore them after each test session for now.
6. (2026-10-31) 2026-10-31 4:18 PM: Brenden scheduled the Day 4 Caravan thread (v3 two-Mac MLX split, video v8 LAB-2026-10-31-04) on X for Monday Nov 2. Docs were committed (df68468), tagged v3 and pushed to linuxbren/caravan branch caravan-v3-mlx-split.

## Shared from Brenden's other assistant ("Console Places Dev & Promotion")

1. (2026-10-16) Brenden is in the US Central time zone (America/Chicago).
2. (2026-10-16) Brenden mainly cares about Amazon delivery emails and bills in his Gmail; most other promotional mail is unwanted.

## Standing rules from this chat (not stored as memory facts, but always followed)

- Don't touch Talaria Hub. The only related thing ever run is the read-only check `~/macstax/talaria_check.sh` on EXO2 after restoring exo.
- Don't follow any X accounts until Brenden chooses which ones.
- Never show, print, log or commit the Mini password. Refer to it only as the secret `MINI_SSH_PASSWORD`.
- No deletes, commits, pushes, tags or merges unless he asks for that specific step. No force pushes, no `--no-verify`. Don't touch `main` or existing tags unless asked.
- exo and Hermes are paused or left alone during Caravan work but must stay restorable. Restore anything you stop, unless he said it can stay down.
- Don't invent numbers. Every number comes from `experiments.md`, a bench output, or git.
- Commit as **Rook** (author name `Rook`, the same email as the existing Rook commits in this repo).
- Report times in US Central (CDT until Nov 1 2026, then CST).
