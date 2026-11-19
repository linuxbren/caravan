# Day 33 — Power-loss recovery test

**Result: partial.** Restore passed: both Macs came back by themselves and
the split model was ready over Thunderbolt about 80 s after power came
back. Resuming the work failed: the reply being written at the cut was
lost, and the prompts after recovery were new ones sent by the test
script, not Caravan finishing the lost one. The point of the test is that
Caravan *continues the work* after power returns, so Day 33 is recorded as
partial, and Caravan now journals chats and runs unfinished ones again
(see "Resume after a power loss" below). A second plug-pull test follows.

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

**Restore: pass.** Caravan brought the split model back over Thunderbolt
by itself, 76 s after the 1st Mac powered up (about 80 s after the plugs
went back in), with no one touching either Mac. The restore's first
attempt found the 2nd Mac not yet reachable and retried after 2 s, then
4 s, as designed.

**Work resume: fail.** Request 2 below was being answered at the cut. It
was lost: Caravan had no record of it, so nothing ran it again, and the
client only got an ssh timeout. The later successful replies (6 and 7)
were new prompts from the test loop.

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

## Resume after a power loss (new)

Built after the test, to make Caravan finish the work:

- **Journal.** Every chat sent to the page (`/api/chat` and
  `/v1/chat/completions`, streamed or not) is written to
  `~/.caravan/web-ui/jobs/<id>.json` before the model sees it: one file per
  job, written to a temp file, fsync'd, renamed, and the folder fsync'd, so
  a power loss leaves either the old or the new record, never half of one.
  It is marked done, with the whole reply, when the reply finishes.
  Caravan has no Anthropic-style `/v1/messages` endpoint today, so there is
  nothing else to journal.
- **Run again.** Once the same model is ready (boot restore loads it by
  itself), Caravan runs each unfinished job again **from the start**, not
  mid-sentence, and saves the reply. A try is counted before it starts, so
  a second power loss mid-replay still counts.
- **Getting the answer.** `X-Caravan-Job` header; a streamed reply starts
  with the SSE comment `: caravan-job <id>`; `GET /api/jobs` and
  `GET /api/jobs/<id>`; `caravan jobs [<id>]`. The chat shows a recovered
  reply once, with the note "Finished after a restart".
- **Limits.** Older than 1 hour when the model is back: not run
  (`expired`). At most 2 tries (`gave_up`). Requests over 4 MB are not
  saved. Done jobs never run again; a job the client cancelled is not run
  again. Finished jobs are deleted after 3 days, at most 500 kept.
- **Opt-out.** `[jobs] resume = false` in `~/.caravan/config.toml`, or
  `CARAVAN_RESUME_JOBS=0`. Default on.
- **Privacy.** The journal holds prompts and replies, stays on the 1st Mac
  (owner-only folder and files), and `caravan uninstall` removes it with
  `~/.caravan`.
- Not covered: requests sent while the 1st Mac is still loading get "no
  model loaded" and are not saved (the client must send them again). If
  the power goes after the reply finished but before "done" was written,
  that one reply runs again (at least once, not exactly once).

See [WEB](WEB.md#chats-after-a-power-loss-or-crash). Tests:
`tests/test_day33_jobs.py` (journal crash safety, run-again-once, limits,
opt-out, endpoint wiring, CLI).

### Live check with a fake crash

Run on the 1st Mac after installing this release; the results are added here in the next commit.

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

Tests: `tests/test_day33_power_restore.py` and `tests/test_day33_jobs.py`; the full suite passes.
Nothing in `agent/` worker code or the requirements changed (one message
in `agent/service_endpoints.py`), so `caravan update` keeps a loaded model.
