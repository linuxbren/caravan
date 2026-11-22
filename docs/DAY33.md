# Day 33 — Power-loss recovery test

**Result: pass** (second plug pull, Nov 21). Both Macs came back by
themselves, Caravan restored the split model, then ran the chat that the
power loss cut off again by itself and saved the whole reply, which the
client fetched afterwards. The first plug pull (Nov 19) was partial:
restore passed, but the reply in flight was lost because Caravan had no
record of it. The request journal built after it closed that gap.

One problem showed up on Nov 21 and is fixed: the restore checked the link
to the 2nd Mac before Thunderbolt was up, so the split ran over Wi-Fi.

Day 33 ran Nov 19 2026 (America/Chicago). The owner pulled the power on
both Mac minis at once while a split model was busy, then plugged them back
in. Both Macs have "Start up automatically after a power failure" and
automatic login on.

## Second plug pull (Nov 21): pass

Release 7b33dc8 on both Macs. Qwen3 30B split over Thunderbolt, all Auto.
A test loop streamed ~29K-token chats to `/v1/chat/completions` on the 1st
Mac and logged each job id from the stream's first line. After a cut it sent
nothing new and only asked `/api/jobs/<id>` about the cut job.

Plugs pulled about 18:07, back in about 18:08 (CST).

| Event | Time | After plug-in |
|---|---|---|
| Last good check, both Macs | 18:07:49 | — |
| Both Macs stop answering | 18:07:54 | — |
| Chat `job_1795305954_fbdda1c009` cut (sent 18:05:54) | 18:08:11 | — |
| 1st Mac / 2nd Mac boot | 18:08:14 / 18:08:17 | +14 / +17 s |
| 1st Mac answers ping and ssh | 18:08:27 | +27 s |
| Page answers: "Waiting for your other Macs to start… (attempt 2); trying again in 4s: The 2nd Mac is not reachable yet" | 18:08:32 | +32 s |
| 2nd Mac's model server and tunnel up (over Wi-Fi, see below) | 18:08:42 | +42 s |
| Qwen3 30B ready, split | 18:09:37 | +97 s |
| Caravan runs the cut chat again by itself (try 1 of 2) | 18:09:39 | +99 s |
| Cut chat finished: 159 tokens, 754 characters, `stop` | 18:12:26 | +266 s |

The whole prompt (29,201 tokens) was read again, as designed: it runs from
the start, not mid-sentence. `GET /api/jobs/<id>` returned status `done`,
`recovered: true`, note "Finished after a restart"; `caravan jobs <id>` on
the 1st Mac printed "Finished after a restart: Caravan ran the request again
from the start (try 1)" and the reply. Settings after the restore showed
Memory compression 16. No one touched either Mac.

### Found: the restore picked Wi-Fi

The restore's link check ran at about 18:08:40, before either Mac had its
new Thunderbolt link-local address (they change on every boot: here
169.254.17.245 and 169.254.6.11). It found only Wi-Fi ("link to 2nd Mac:
Wi-Fi, en1, 4.83 ms") and kept it for the whole load, although Thunderbolt
answered at 0.39 ms a minute later. Reading the prompt fell from about 550
to about 200 tokens per second, so the cut chat took about 2.8 minutes
instead of about 1.5. On Nov 19 the check happened to run after
Thunderbolt was up.

### Fixed: wait for Thunderbolt, then say so if it comes late

- **Wait.** When a load opens the link to another Mac and Thunderbolt has
  worked to that Mac in the last 30 days, Caravan now waits up to 60 s for
  Thunderbolt before settling for Wi-Fi or Ethernet. Every 5 s it reads both
  Macs' interfaces again, so the new link-local addresses are found. The
  page shows "Waiting for the Thunderbolt link to 2nd Mac (15s of
  60s)…", Stop still works, and if Thunderbolt never answers the note says
  "Thunderbolt to 2nd Mac did not answer within 60s; using Wi-Fi, splits
  will be slower". A Mac that never had Thunderbolt does not wait.
  `CARAVAN_TB_WAIT_S` changes the limit (0 turns the wait off).
- **Late Thunderbolt.** While a split runs on Wi-Fi or Ethernet, Caravan
  checks once a minute whether Thunderbolt to that Mac answers now. If it
  does, it shows one note: "Thunderbolt to the 2nd Mac is working now, but
  this model is still using Wi-Fi. To switch to Thunderbolt, Unload and Load
  the model again when no chat is running." It does not switch by itself:
  switching means starting the model again, which would stop a reply being
  written and make the model unavailable for about a minute at a moment the
  user did not choose. The note lets the user pick the moment.

Tests: `tests/test_day33_thunderbolt_wait.py`.

### Thunderbolt check after the fix

Release 2a155f9 on both Macs (Nov 21, no power pull):

- **Late Thunderbolt note.** `caravan update` restarted the page, which
  took over the split still running on Wi-Fi from the plug pull. Within a
  minute the page showed "Thunderbolt to the 2nd Mac is working now, but
  this model is still using Wi-Fi. To switch to Thunderbolt, Unload and
  Load the model again when no chat is running." The model kept running.
- **Restore picks Thunderbolt.** llama-server and the page on the 1st Mac
  were killed with `kill -9` at 18:22:27 (no chat running). launchd started
  the page again, boot restore reloaded the split and it was ready at
  18:22:58 on "link to 2nd Mac: Thunderbolt, en2, 0.45 ms". The saved route
  records the wait: Thunderbolt found on the first try (0.3 s), so nothing
  was delayed. Memory compression 16.
- Not repeated live: Thunderbolt coming up *during* the wait. That needs
  the link taken down on purpose (administrator rights on a Mac) or another
  power pull; the unit tests cover it with addresses that change between
  tries.

## First plug pull (Nov 19): partial

### Setup

- Qwen3 30B-A3B Q4_K_M (GGUF) split across the 1st and 2nd Mac over
  Thunderbolt, every setting on Auto (window 32768, 16-bit chat memory,
  flash attention on). Loaded 14:53:36; `last-model.json` named it.
- A loop on the development node sent back-to-back ~29.7K-token prompts
  (300 tokens out) to the 1st Mac. Both GPUs were at 99–100%.
- A watcher on the development node recorded, every ~5 s: ping and ssh
  for both Macs over the LAN and the tailnet, a Thunderbolt ping from the
  1st Mac to the 2nd, the Caravan status on the 1st Mac, and a tiny chat
  once ready.

### Timeline (CST)

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

### Load loop

| # | Sent | Ended | Result |
|---|---|---|---|
| 1 | 14:53:54 | 14:56:14 | OK, 29,717 tokens, read 247 tok/s, write 15.6 tok/s |
| 2 | 14:56:14 | 14:57:43 | cut by the power loss (ssh timeout) |
| 3–5 | 14:57:45–14:58:15 | at once | "no model loaded" while the restore was starting (worker status starting_lead) |
| 6 | 14:58:25 | 14:59:37 | OK, 18,372 tokens, read 328 tok/s, write 19.8 tok/s |
| 7 | 14:59:37 | 15:02:03 | OK, 29,723 tokens |

The loop was stopped at 15:03 after recovery was confirmed.

### Files after the power loss

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

Release 7b33dc8 on both Macs, Qwen3 30B split, all Auto. A streamed
~7.3K-token chat was sent to `/v1/chat/completions` on the 1st Mac, then
llama-server and the Caravan web process were killed with `kill -9`
mid-request. launchd started the web again by itself; boot restore
reloaded the split model.

| Run | Sent | Killed | What was cut | Ready again | Run again | Finished |
|---|---|---|---|---|---|---|
| 1 | 15:20:22 | 15:20:35 | while reading the prompt | ~15:20:59 | 15:20:59 (try 1) | 15:21:21, 200 tokens (all thinking; `max_tokens` 200) |
| 2 | 15:21:46 | 15:22:09 | nothing: the reply had finished | 15:22:37 | not run again (done) | — |
| 3 | 15:22:52 | 15:23:22 | mid-reply, ~418 stream events written | ~15:23:43 | 15:23:43 (try 1) | 15:24:44, 1,200 tokens, 5,721 characters |

Each client saw `X-Caravan-Job` and the first line `: caravan-job <id>`
before the kill. After it, `GET /api/jobs/<id>` and `caravan jobs <id>` on
the 1st Mac returned the whole reply with "Finished after a restart …
from the start (try 1)". The re-run read all 7,316 prompt tokens again
(nothing cached). Run 3 finished 82 s after the kill. The watcher's tiny
chat that was in flight at run 1 was also run again and finished. Run 2
shows a finished job is not run again. Journal folder `drwx------`,
files `-rw-------`.

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

Tests: `tests/test_day33_power_restore.py`, `tests/test_day33_jobs.py` and `tests/test_day33_thunderbolt_wait.py`; the full suite passes.
Nothing in `agent/` worker code or the requirements changed (one message
in `agent/service_endpoints.py`), so `caravan update` keeps a loaded model.

## Medium prompts: crash series (Nov 21, 19:11–19:18 CST)

Brenden asked for a series of medium prompts instead of one long one. Same
setup as the plug-pull test: Qwen3 30B (GGUF) split over Thunderbolt, all
11 settings Auto (Auto window 32768), release 2a155f9. Five real-ish tasks,
3.3K–7.5K prompt tokens, replies capped at 700 tokens (/no_think,
temperature 0), streamed to `/v1/chat/completions` on the 1st Mac by
`tools/medium_series.py`. Each prompt ran once uninterrupted, then again
with a new opening (so nothing was cached) and `kill -9` of llama-server
and the web on the 1st Mac at a set point. After the kill nothing was
touched: launchd restarted the web, the boot restore reloaded the split and
the journal ran the job again from the start. Times use the Mac clock.

| # | Task | Prompt tokens | Cut | Kill → ready | Ready → re-run | Re-run | Crash total | Uninterrupted | Lost* | Reply tokens (base / re-run) | Write tok/s (base / re-run) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | code review | 3,366 | early reply (token 32 of ~522) | 28.3 s | 2.0 s | 18.4 s | 55.8 s | 23.2 s | 37.4 s | 522 / 384 | 30.3 / 30.4 |
| 2 | log triage | 5,565 | prompt reading (5 s into 10.2 s) | 21.1 s | 0.2 s | 26.8 s | 53.2 s | 26.9 s | 26.4 s | 468 / 464 | 28.0 / 28.0 |
| 3 | meeting email | 2,501 | late reply (token 412 of ~514) | 20.3 s | 1.0 s | 19.2 s | 58.2 s | 20.8 s | 39.0 s | 514 / 467 | 31.1 / 31.2 |
| 4 | sales CSV | 7,550 | prompt reading (3 s into 14.9 s) | 20.2 s | 1.1 s | 31.3 s | 55.7 s | 30.2 s | 24.4 s | 404 / 435 | 26.3 / 26.4 |
| 5 | handbook Q&A | 4,472 | mid reply (token 119 of ~239) | 20.2 s | 1.2 s | 16.4 s | 49.8 s | 16.0 s | 33.4 s | 239 / 250 | 29.2 / 29.3 |
| | **average** | 4,691 | | **22.0 s** | **1.1 s** | **22.4 s** | **54.5 s** | **23.4 s** | **32.1 s** | | **29.0 / 29.0** |

\*Lost = crash total − re-run (time before the run that finished: work
thrown away plus the restore). Crash total − uninterrupted averages 31.1 s;
the two differ a little because the new opening changes the reply length.

- 5/5 done, `recovered: true`, "Finished after a restart", 1 replay each.
- 5/5 restores picked Thunderbolt (en2, 0.39–0.49 ms); no Wi-Fi fallback.
- The web answered about 1.1 s after the kill (launchd); the split was
  ready in 20–28 s (the first restore of the series was the slowest).
- 5/5 answers fetched with `GET /api/jobs/<id>` and `caravan jobs <id>`.
- Re-runs read the whole prompt again (3 cached tokens at most) and wrote
  at the same speed as the uninterrupted runs (prompt reading 507–591
  tok/s both ways).
- Nothing failed, so no code change. Raw files:
  `~/Projects/caravan-day33/medium/` (series.log, per-run job JSON,
  `caravan jobs` output, summary.md).
