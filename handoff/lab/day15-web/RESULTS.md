# Day 15 — Caravan web interface

**Date.** 2026-11-04 (America/Chicago).  
**Goal.** A browser UI on EXO1 so Brenden can use what Days 1–13 built:
switch preloaded models, chat with live streaming, timestamps to 0.01 s
(browser ↔ Mini clock sync), and real per-reply stats (never invented).

## Software

| Path | Role |
|---|---|
| `proxy/web_server.py` | HTTP + chat proxy + Mini timestamps |
| `proxy/web_workers.py` | Lead/packer start/stop + log progress |
| `proxy/web_catalog.py` | Models already on the Minis |
| `proxy/web_timing.py` | Clock-offset / gap / reply-stat math |
| `proxy/web/index.html` | The page (dark, open-build feel) |
| `proxy/web/journey.json` | Real v0→Day 13 numbers |
| `tests/test_web_server.py` | +16 tests |
| `docs/WEB.md` | How to start / stop / open |

**198 tests OK** (182 prior + 16 new).

## E2E on the Minis (LPM off, ports 8190 / 8194 / 5560)

### Qwen3 30B-A3B 4-bit (split)
- Load: packer 1.8 s + lead 2.9 s → ready (~16 s wall including SSH).
- Chat `CARAVAN_OK`: ttft **0.272 s**, write **65.22 tok/s**, guess-ahead
  accept **66.7%**, tuned `{pipeline_chats:2, guess_ahead:true}`.
- Raw: `qwen3-chat.json`, `qwen3-split.json`.

### Switch → Gemma 4 26B-A4B 4-bit
- Unload + reload across both Minis → ready.
- Chat `GEMMA_OK` (max_tokens 256): ttft **0.233 s**, write **27.61 tok/s**,
  content after reasoning. Raw: `gemma-chat3.json`.
- UI chat `WEB_UI_OK` (playwright): total **2.62 s**, ttft **0.41 s**,
  read **127.5 tok/s**, write **29.9 tok/s**.
  Milestones (browser frame after NTP sync):
  sent 09:59:16.70 → received +0.03 s → first +0.41 s → done +2.22 s.
  Clock: offset −0.1616 s ±0.0020 s, RTT 4.0 ms (n=6).
  Raw: `ui-chat-capture.json`.

### Screenshots
- `01-ready-gemma.png` — chromium headless
- `02-ui-loaded.png` — playwright, empty chat
- `03-after-chat.png` — after WEB_UI_OK with stats filled

## How to open (left running on EXO1)

```
http://100.68.62.20:8190/          # Tailscale EXO1
http://prf-hays-exo01-2.local:8190/
```

Start/stop: see `docs/WEB.md`. Web PID in `~/.caravan/web-ui/web.pid` on EXO1.

## Known issues / caveats
- Gemma (and similar) may spend many tokens in reasoning before content;
  short `max_tokens` can look like an empty reply. UI now shows reasoning.
- Some models append special end markers (`<|im_end|>`, `<turn|>`) into the
  visible text — tokenizer/detok, not the web layer.
- Packer control uses SSH from EXO1 → EXO2 over Thunderbolt
  (`brenden@169.254.103.191`). Needs the existing key trust.
- No auth; LAN/Tailscale only — do not port-forward publicly.
- Shared-start hit not exercised in these short chats (no long system prompt).
