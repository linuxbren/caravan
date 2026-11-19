# Day 33 — Power-loss recovery test

Day 33 ran Nov 19 2026 (America/Chicago). The owner pulled the power on
both Mac minis at once while a split model was busy, then plugged them back
in. Both Macs have "Start up automatically after a power failure" and
automatic login on.

## Setup

- Qwen3 30B-A3B Q4_K_M (GGUF) split across the 1st and 2nd Mac over
  Thunderbolt, every setting on Auto (window 32768, 16-bit chat memory,
  flash attention on). Loaded 14:53:36; `last-model.json` named it.
- A loop on the development node sent back-to-back ~29.7K-token prompts
  (300 tokens out) to the 1st Mac. Both GPUs were at 99–100%.
- A watcher on the development node recorded, every ~5 s: ping and ssh
  for both Macs over the LAN and the tailnet, a Thunderbolt ping from the
  1st Mac to the 2nd, the Caravan status on the 1st Mac, and a tiny chat
  once ready.

## Timeline (CST)

Plug-in is the owner's "about 14:57"; power-up is each Mac's kernel boot
time (1st Mac 14:57:08, 2nd Mac 14:57:13). Watcher times are when that
check round was written (rounds take 5–9 s while Macs are down).

| Event | Time | After plug-in | After power-up (1st Mac) |
|---|---|---|---|
| Last good check, both Macs | 14:56:39 | — | — |
| 1st Mac stops answering | 14:56:44 | — | — |
| 2nd Mac stops answering | 14:56:50 | — | — |
| Long prompt in flight fails (ssh timeout) | 14:57:43 | — | — |
| 1st Mac boots (kernel) | 14:57:08 | +8 s | 0 s |
| 2nd Mac boots (kernel) | 14:57:13 | +13 s | +5 s (2nd Mac 0 s) |
| Caravan web process starts at login (1st Mac) | 14:57:18 | +18 s | +10 s |
| ssh over the LAN answers, both Macs | 14:57:23 | +23 s | +15 s |
| Caravan page answers; boot restore already waiting for the 2nd Mac (attempt 2) | 14:57:28 | +28 s | +20 s |
| ping over the LAN and ssh over the tailnet, both Macs | 14:57:28 | +28 s | +20 s |
| ping over the tailnet, both Macs | 14:57:33 | +33 s | +25 s |
| Restore loads the model ("switching to …, split across My Mac + 2nd Mac") | 14:57:42 | +42 s | +34 s |
| 2nd Mac's model server up; link "Thunderbolt, en2, 0.33 ms" | 14:57:44 | +44 s | +36 s |
| Qwen3 30B ready, split across both Macs ("loaded in 40.1s") | 14:58:24 | +84 s | +76 s |
| First long prompt after recovery answered (sent 14:58:25, 18,372 tokens) | 14:59:37 | +157 s | +149 s |
| First tiny chat answered (queued behind that prompt) | 14:59:37 | +157 s | +149 s |
| Manual check "Reply with the single word OK" → "OK" | 15:02:04 | — | — |

**Result: pass.** Caravan brought the split model back over Thunderbolt by
itself, 76 seconds after the 1st Mac powered up, with no one touching
either Mac. The restore's first attempt found the 2nd Mac not yet
reachable and retried after 2 s, then 4 s, as designed.

## Load loop

| # | Sent | Ended | Result |
|---|---|---|---|
| 1 | 14:53:54 | 14:56:14 | OK, 29,717 tokens, read 247 tok/s, write 15.6 tok/s |
| 2 | 14:56:14 | 14:57:43 | cut by the power loss (ssh timeout) |
| 3–5 | 14:57:45–14:58:15 | at once | "no model loaded" while the restore was starting (worker status starting_lead) |
| 6 | 14:58:25 | 14:59:37 | OK, 18,372 tokens, read 328 tok/s, write 19.8 tok/s |
| 7 | 14:59:37 | 15:02:03 | OK, 29,723 tokens |

The loop was stopped at 15:03 after recovery was confirmed.

## Files after the power loss

- `last-model.json`, `gguf-tuned.json`, `gguf-self-tune.json`,
  `speed_averages.json`, `bench_speedups.json`, `mlx/tuned-settings.json`,
  `web-ui/gguf.json` and `peer-routes.json` all parse; `config.toml` parses
  on both Macs. The restore used `last-model.json` as saved.
- The model file's SHA-256 matches Hugging Face's
  (`a015794b…ed5d32`, 18,632,184,480 bytes).
- The Thunderbolt link-local addresses changed on reboot (2nd Mac
  169.254.151.30 → 169.254.65.112). Caravan found the new one by itself
  (`peer-routes.json`). Only the test watcher had the old address hard-coded;
  it was restarted at 14:59:08 to read the current one.

## Fixed

- **Plain wording while the restore waits.** The page showed "Waiting for
  Minis (attempt 2); retry in 4s: Mini Mac is unavailable; bring it online
  and press Load". The internal id of the 2nd Mac was scrubbed to a bare
  "Mac", and "press Load" was wrong while Caravan retries by itself. It now
  reads "Waiting for your other Macs to start… (attempt 2); trying again in
  4s: The 2nd Mac is not reachable yet". "Press Load to try again" stays in
  the message for when the retries run out.
- **Settings chip after a restore.** The restored model reported no
  Memory compression (`kv_bits` empty) because the saved tune keeps only
  flash attention and prompt batch. Caravan now reports the chat memory
  llama-server was actually started with (16-bit here).

Tests: `tests/test_day33_power_restore.py`; the full suite passes.
Nothing in `agent/` worker code or the requirements changed (one message
in `agent/service_endpoints.py`), so `caravan update` keeps a loaded model.
