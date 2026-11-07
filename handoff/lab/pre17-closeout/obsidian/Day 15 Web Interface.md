---
title: Day 15 Web Interface
tags: [project, caravan, web-ui, day15]
created: 2026-11-04
updated: 2026-11-06
---

# Day 15 — Caravan web interface

Browser UI on EXO1 so you can *use* Days 1–13: switch preloaded models, stream chat, timestamps to 0.01 s (browser ↔ Mini clock sync), real tok/s and feature tags.

## Open it
- Tailscale: http://100.68.62.20:8190/
- LAN: http://prf-hays-exo01-2.local:8190/
- Docs: `docs/WEB.md` in the repo
- Left running on EXO1 (PID in `~/.caravan/web-ui/web.pid`)

## What shipped
- `proxy/web_server.py` + workers/catalog/timing + `proxy/web/index.html`
- Journey strip uses real v0→Day 13 numbers from lab
- **21 web tests OK** (was 16; +5 keep-alive/markers/UI)

## E2E sample (America/Chicago, LPM off)
| Model | ttft | write tok/s | notes |
|---|---:|---:|---|
| Qwen3 30B-A3B 4-bit | 0.272 s | 65.22 | guess-ahead 66.7% accept |
| Gemma 4 26B-A4B 4-bit | 0.41 s (UI) | 29.9 | after model switch |

UI milestones example: sent → received **+0.03 s** → first **+0.41 s** → done **+2.22 s**. Clock offset −0.1616 ±0.0020 s.

Screenshots: `handoff/lab/day15-web/01-ready-gemma.png`, `02-ui-loaded.png`, `03-after-chat.png`.

## Caveats
- Gemma may think for many tokens before content — UI shows reasoning.
- No auth; home LAN / Tailscale only.
- Packer start uses SSH EXO1→EXO2 over Thunderbolt.

## Links
- [[Projects/Caravan/Caravan|Caravan index]]
- [[Projects/Caravan/Day 13 Results|Day 13]]

## Bugfixes (send state + Gemma stall)

Brenden hit: Gemma chat blank ~20–30s; after loading Qwen3 / GPT-OSS, Send stayed disabled.

**Root causes**
1. `streaming` stayed true across model switch (Send = ready && !streaming).
2. Chat 409 / stop skipped reading POST body → keep-alive request smashing (`Bad request syntax`).
3. No thinking placeholder / client timeout; end markers leaked.

**Fixes:** drain bodies; Connection: close on SSE; cancelChat on Load/Unload; thinking… + 45s/180s timeouts; strip `<|im_end|>` / `<turn|>` etc.

**Verified timings (America/Chicago)**
- Gemma: ttft 0.24 s, write 30.5 tok/s, thinking shown
- Qwen3: ttft 0.27 s, write 42.3 tok/s (after mid-stream switch — Send enabled)
- GPT-OSS: ttft 0.30 s, write 34.5 tok/s
- Left ready on **Qwen3**

Screenshots: `handoff/lab/day15-web/fix-*.png`


- 13:23 CT fix (a1fa68c): chats got no reply over http://100.68.62.20:8190 because the page used crypto.randomUUID, which browsers only allow on HTTPS/localhost; it threw before sending. Added a fallback, plus stripping <|eot_id|> in worker replies. Verified in a non-secure browser: first word Llama 0.41/0.25 s, Gemma 0.25/0.13 s, Qwen3 0.29/0.19 s, GPT-OSS 0.31/0.14 s. Left on Llama.

## Optimization toggles (16:33 CT, commits 17b477c + 45447ca)
- New **Optimizations** card: Guess-ahead (Auto/On/Off), Self-tuning (Auto/Off), Shared start — trim/rebuild (Auto/On/Off), Two chats (Auto/1/2), Fused kernels (Auto/On), Memory compression (Auto/8/4-bit), GPU keep-warm (Auto/Off). **Apply & restart** reloads the model with them.
- "Running with" chips next to the model, and under every reply `ran with: …` (what the worker actually used, incl. words from the helper) + `chosen: …`.
- Fixed: with two chats on, a learned "guess-ahead off" was ignored; now honored.
- Verified in headless Chromium over plain http (Qwen3 + Llama, every toggle): all replied, each flag showed in the lead log `active settings` line. Left on Llama, all Auto (Llama's learned winner currently runs guess-ahead off).

### How to test it yourself
1. Open http://100.68.62.20:8190/, refresh, load a model with everything on Auto.
2. Send the same message twice; note To first word, Write tok/s and the `ran with:` line.
3. Change one option (e.g. Guess-ahead Off), Apply & restart, wait for ready.
4. Send the same message twice; `ran with:` should say `guess-ahead off (pinned)`. Compare the second replies.
5. Set it back to Auto, Apply. Keep Low Power Mode off.

## Fresh start for auto-learn test (2026-11-04, ~11:27 PM CT)
- Moved (not deleted) EXO1 learned state: `~/.caravan/mlx/tuned-settings.json` and `~/.caravan/mlx/guess-ahead-state.json` → `~/.caravan/learn-backup-2026-11-04/` (with RESTORE.txt). EXO2 had no learned-state files.
- Restore: `mv ~/.caravan/learn-backup-2026-11-04/{tuned-settings,guess-ahead-state}.json ~/.caravan/mlx/` on EXO1, then reload the model.
- Reloaded GPT-OSS 20B with all Auto; new tuned-settings.json started fresh (reply_n 1 after one check chat, a single sample at 33.6 tok/s).

## Page rearranged (23:40 CT, 815d4de + e1c25cd)
- Order top to bottom: Chat, Last reply, Settings (model picker + Optimizations), Clock sync, Milestones, How far we have come, Load progress, The string (the lead/packer layers diagram). One column on phones.
- Checked in headless Chromium at 1300 px and 390 px with zero chats sent (fresh auto-learn test left untouched; no model reload).

- Self-tuning now sits at the top of the Optimizations panel. The other rows keep their order (commit 2a4920f).
- Setting Self-tuning to Auto now switches every other option to Auto. You can still pin options afterward. When self-tuning is Auto and options are pinned, a note says 'N pinned — self-tuning can't change these'. Each Auto button shows what the running model resolved it to, e.g. 'Auto (on)' (commit bced54e).

- Self-tuning now covers every option (design decision: it's "Self-tuning", not "Self-tuning except"). Memory compression, fused kernels and GPU keep-warm get reload trials: queued, tried on the next load, scored over 3 replies, then kept or rolled back. Pins still win. Added Optimize this model with Deep (default, reloads itself when no chat is in flight) and Quick (live options only), Start/Cancel, live ETA and a summary of the winners (commit f5c418e). Needs Apply & restart once so the running worker picks it up.

## Later Day 15 — picker + placement (Nov 5)

See [[Projects/Caravan/Day 15 Results|Day 15 Results]] closeout. Tip at end of Day 15 stretch: `d60c983` (placement-aware load). JevK5 4-bit single-Mini on EXO1 verified.
