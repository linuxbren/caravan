# Day 33 — A Guess-ahead helper for MLX on one Mac

Day 33 started Nov 23 2026 (America/Chicago). ROADMAP #1 (a Guess-ahead
helper for MLX on one Mac) shipped as
[v0.9.13](https://github.com/linuxbren/caravan/releases/tag/v0.9.13).
ROADMAP #2 — first-token timing in Auto-tune — shipped as
[v0.9.14](https://github.com/linuxbren/caravan/releases/tag/v0.9.14).
"Prefer a shipped guesser, else the helper" shipped as
[v0.9.15](https://github.com/linuxbren/caravan/releases/tag/v0.9.15)
([below](#prefer-a-shipped-guesser-else-the-helper-v0915)).
Chat with Ollama Cloud models shipped as
[v0.9.16](https://github.com/linuxbren/caravan/releases/tag/v0.9.16)
([below](#chat-with-ollama-cloud-models-v0916)).
CAR-9 — a GGUF split pick downloads each Mac's part — shipped as
[v0.9.17](https://github.com/linuxbren/caravan/releases/tag/v0.9.17)
([below](#a-gguf-split-pick-downloads-each-macs-part-car-9-v0917)).

Built on the local branch `day33-mlx-1mac-helper` (on `ecddb9a`). Claude
reviewed the uncommitted work, asked for one change (native MTP must not
load a conventional draft helper), then approved the fix at 2026-11-23
21:52 CST (full suite 2,247 of 2,247 with the review command). Merged to
`main` fast-forward only. The Macs were not updated; Brenden updates them
himself.

Released as [v0.9.13](https://github.com/linuxbren/caravan/releases/tag/v0.9.13):
source `baa8056`, pin `8a33cd6`; tag v0.9.13 on the wrap commit. Notes:
[release-notes/day33-v0.9.13.md](release-notes/day33-v0.9.13.md).

## At a glance

- An MLX model on one Mac can use the same Guess-ahead helper as a
  split MLX model and as GGUF.
- The setting is still Auto / Off / On. Off passes `--no-split-draft`.
  On pins Guess-ahead when a helper is already on this Mac. Auto
  auto-pairs a matching helper when it is on disk, and leaves Guess-ahead
  off until a test finds a winner.
- The helper must be the same family (same tokenizer). Caravan checks
  the files on this Mac and whether the helper fits in the memory left
  after the main model is loaded. If the helper is missing, incompatible,
  or does not fit, load continues without it and the log says why (fail
  closed; no crash).
- A reply that used guesses still ends with "guesses kept N%", and
  `caravan bench --speedups` measures the Guess-ahead row on one-Mac
  MLX when a helper is active (otherwise it says there is no helper on
  this Mac for this model).
- Auto-tune can score and try Guess-ahead on one-Mac MLX once a helper
  is loaded.
- When a known helper is not downloaded yet, Settings shows "Download
  helper for faster replies?" the same way it does for GGUF and for a
  split MLX model. A Balance split still does not use a helper.
- User-facing copy and all five locales no longer say that MLX only
  uses a helper when it is split across Macs.

## How it works

A one-Mac MLX model already runs `agent/mlx_worker.py` with
`--split-role none` and loads the full model through `mlx_lm.load()`.
The draft load, vocab maps, first-load quality+speed gate, `_speculate_tokens`,
and "guesses kept" counters already existed for a split lead. They were
gated off for one Mac:

- Draft load lived only in the split-lead branch of `_setup`.
- `_run` would not speculate from a draft unless `self.client` was set
  (prompt-lookup was the only one-Mac speculate path).
- ChatShutoff and Auto-tune scoring of Guess-ahead were split-only.
- The helper offer, Helper button copy, and `caravan bench --speedups`
  skipped one-Mac MLX on purpose.

Day 33 lifts those gates. `_setup_guess_ahead` is shared by a split lead
and a one-Mac worker: auto-pair from `agent/guessers.json`, honor
`--no-split-draft` / `--split-draft-model`, check that the helper
directory is present, check vocab maps, and check free memory
(`helper size + 0.5 GB` against available memory after the main model
is in RAM). A missing explicit `--split-draft-model` path still raises.
Everything else fails closed. Serial `_run` (the one-Mac path) now
speculates when a draft is loaded, tracks `from_draft` / `accepted_frac`
the same way a split lead does, and reports that through the existing
web timing and bench stats. The first-load gate still runs unless
`--split-draft-skip-first-load` is set (the web lead still skips that
flag on a one-Mac launch).

Native MTP (experimental) is still a one-Mac path. Settings Guess-ahead
= Native MTP emits `--native-mtp --no-learn` and does not emit
`--no-split-draft`. `_setup_guess_ahead` therefore treats `native_mtp`
like `--no-split-draft`: it skips auto-pair, download, and load of a
conventional draft helper, including an explicit `--split-draft-model`,
so an unused helper is never loaded beside the MTP head.

Settings flags did not need a new path for Auto / Off / On:
`web_settings.to_args` already emits `--no-split-draft` or
`--pin-guess-ahead`, and `_start_lead` already forwards those extras on
a non-split launch.

## Tests

`tests/test_day33_mlx_1mac_helper.py` covers load, skip, fit, vocab,
consent, Auto / Off / On flags, Auto-tune scoring, the helper offer and
status, speedups, Helper button copy, the five locale files, and the
native-MTP skip (no conventional draft helper is paired, downloaded, or
loaded). There is no live MLX on the Linux dev node.

## Not in this change

- VERSION and CHANGELOG are unchanged until review and wrap.
- A Balance split still does not use a helper (every guess would wait
  on the other Mac).
- Historical Day 27 measurements and mid-page tables stay as they were;
  later notes there point here.

## First-token timing in Auto-tune (ROADMAP #2, v0.9.14)

Built on the local branch `day33-autotune-ttft` (on `5ab8a5de`). Claude
reviewed the uncommitted work and approved it at 2026-11-23 22:40 CST
(full suite 2,273 of 2,273 with the review command). Merged to `main`
fast-forward only. The Macs were not updated; Brenden updates them
himself.

Released as [v0.9.14](https://github.com/linuxbren/caravan/releases/tag/v0.9.14):
source `5249f19`, pin `eaa3710`; tag v0.9.14 on the wrap commit. Notes:
[release-notes/day33-v0.9.14.md](release-notes/day33-v0.9.14.md).

When Guess-ahead is on, the helper also reads the prompt, so the first
word on a long prompt comes about 10% later (Day 27 measured this). Auto-tune
already recorded first-token time from the worker (`usage.caravan.ttft_s`,
or llama-server `timings.prompt_ms`) and already ran a ~2k-token long
prompt, but the Guess-ahead pick did not always use that first-word wait.

- GGUF Auto-tune (`spec_verdict`) only compared a whole long-prompt reply
  when long-prompt *read* dropped more than 15%. A typical 10% first-word
  delay sat under that guard, so a tiny write-speed win could still be
  kept even when the long-prompt reply felt slower.
- MLX Auto-tune scored Guess-ahead with `combined_score` (write, long
  read, and 1/total), which can bury a real write win or ignore a first-word
  delay on the long prompt.

The rule is now the same for GGUF and MLX Guess-ahead and Prompt lookup
(including MLX adaptive prompt lookup):

1. Always reject a long-prompt read drop past 35% (Day 28 hard guard).
2. When both arms have comparable evidence, compare **end-to-end long-prompt
   reply time**: measured long-prompt total if both have it, else measured
   long-prompt first-token time plus writing 192 tokens, else an estimate
   from long-read speed (`prompt tokens / long_read + 192 / write`). Prefer
   the actual long-prompt first-token median (`long_ttft_s`) from the existing
   ~2k Auto-tune prompt — no extra long prompt is added, so Auto-tune does
   not get slower.
3. If that long-prompt reply is more than 2% slower, the helper loses,
   even when short-chat write is a little faster. A real write-speed gain
   (about +40–60%) that pays back the extra first-word wait can still win.
4. If first-token and long-read evidence is missing or zero (older saved
   Auto-tune profiles, a mock, or a worker that does not report it), the
   older chat-only verdict is unchanged — no crash, no made-up time.
5. Other knobs (KV cache, flash, ubatch, Native MTP, Balance, prefix
   reuse) keep their existing scores. Native MTP is not a Guess-ahead
   Auto-tune trial; a quality or garbled arm still loses before speed is
   considered. One-Mac and two-Mac, MLX and GGUF, all use the same verdict.

The Before/After line already shows first-token time. When Auto-tune
rejects a helper because the long-prompt reply was slower, the why line
is "long-prompt first word + reply Xs vs Ys" (all five locales).

Tests: `tests/test_day33_autotune_ttft.py`.

## Prefer a shipped guesser, else the helper (v0.9.15)

Built on the local branch `day33-shipped-guesser` (on `d686067`). Claude
reviewed the uncommitted work and approved it on 2026-11-24 with no
issues found (full suite 2,313 of 2,313 with the review command). Merged
to `main` fast-forward only. The Macs were not updated; Brenden updates
them himself.

Released as [v0.9.15](https://github.com/linuxbren/caravan/releases/tag/v0.9.15):
source `90528a7`, pin `860e177`; tag v0.9.15 on the wrap commit. Notes:
[release-notes/day33-v0.9.15.md](release-notes/day33-v0.9.15.md).

**What "shipped guesser" covers, from the code.** A guesser made for
this exact model. Today the only one Caravan can run is a native MTP head
installed beside an MLX model (`caravan-mtp/`, Day 17), checked against
the model by `native_mtp.validate_pair` (dense Qwen3.5 with one MTP layer,
same sizes, and the exact target the head was extracted for; Day 17
measured Orvena 4B at 36.95 → 54.13 write tok/s). No GGUF path runs a
shipped guesser: llama.cpp MTP was listed as an idea on Day 23 but was
never measured here, so it is not used. The fallback is Caravan's paired
Guess-ahead helper: `agent/guessers.json` for MLX and
`proxy/helper_offer.py` `HELPERS` for GGUF. On GGUF only, any other
smaller same-family file found on this Mac comes last.

**MLX order** (`agent/guesser_choice.py`, first match wins):

1. Guess-ahead Off: no guesser.
2. Settings Guess-ahead = Native MTP (test): the head, with the old strict
   rules (one Mac, 16-bit, greedy replies only, no learning).
3. An explicit `--split-draft-model`: that helper.
4. Auto or On, with a head that can run here (one Mac, 16-bit chat memory,
   Prompt lookup off, head matches this model):
   - inside an Auto-tune reload, the head is left to Auto-tune's own
     Native MTP trial, so the other arm really is the helper;
   - a saved Auto-tune verdict for Native MTP decides first;
   - then the cached first-load check for this model and head;
   - otherwise the head is loaded and checked once after warm-up with
     the same quality probes and the same 5% speed bar as a helper's
     first-load check. If it loses, the head is unloaded and the paired
     helper is set up instead (its own first-load check still runs).
5. Otherwise the paired helper, as before (ask before download, fit check,
   vocab check).

The head and a conventional helper are never loaded together (the
v0.9.13 rule). A split never uses the head, and a Balance split of an
MLX model still uses no helper. A head picked by Auto or On
serves greedy replies (temperature 0, no repetition penalty, which is what
the page sends). Any other reply runs the normal path with no guesser
instead of failing, as the Settings test mode still does. Learning is not
fed by head replies (the head path never called it).

**GGUF order.** `find_gguf_draft` now returns Caravan's paired helper for
the model when it is on this Mac, even if another same-family file is a
little smaller (for example a Qwen2.5 Coder model with both the Coder
0.5B helper and the plain Qwen2.5 0.5B file). Otherwise the smallest
qualifying file wins, as before. The result says `source: "paired"` or
`"found"`. Nothing downloads without the existing Download click.

**Which guesser and why.** The MLX worker logs one `guesser: <kind>
(<source>, <reason>)` line (and again if the first-load check changes it),
and `/caravan/settings` `active.guesser` carries kind, source, reason and
the plain why. The Guess-ahead chip says "built-in guesser" when the head
was picked automatically ("native MTP · experimental" stays for the
Settings test mode), and its hint is the why. GGUF `active.guesser` says
paired helper or found file, and the load notes name it. While a model
uses its own head, the "Download helper for faster replies?" line is not
shown and the Helper button says the model uses its built-in guesser.
All new words are in the five locale files.

**Known limits.**

- The head path keeps no chat memory between turns (Day 17 design), so in
  a long multi-turn chat each reply reads the whole chat again. The
  first-load check and Auto-tune's long prompt are single-turn, so they do
  not measure that cost.
- When Auto-tune keeps Native MTP, it reloads in the Settings test mode
  until the next load (existing Day 18 behavior); the next normal load
  reads the saved verdict and uses the head through Auto.
- Nothing here was run on a Mac: the Linux dev node has no Apple Silicon.

Tests: `tests/test_day33_shipped_guesser.py`.

## Chat with Ollama Cloud models (v0.9.16)

Built on the local branch `day33-cloud` (a worktree, started off
`d686067` / v0.9.14 and rebased onto the v0.9.15 wrap `8bc9512`). Claude
reviewed the uncommitted work and approved it on 2026-11-24 with no
issues found (full suite 2,359 of 2,359 with the review command). Merged
to `main` fast-forward only. The Macs were not updated; Brenden updates
them himself.

Released as [v0.9.16](https://github.com/linuxbren/caravan/releases/tag/v0.9.16):
source `269d58d`, pin `963798d`; tag v0.9.16 on the wrap commit. Notes:
[release-notes/day33-v0.9.16.md](release-notes/day33-v0.9.16.md).

Day 32 saved the Ollama Cloud key and made cloud rows say **Load**, but
chats still only went to the Macs. Now **Load** on a CLOUD model in
Models sends the chat to that model on Ollama Cloud.

**Ollama's API.** Checked against Ollama's docs on 2026-11-24
(`docs.ollama.com/cloud/api`, `/api/authentication`, `/api/chat`,
`/api/streaming`, `/api/errors`, `/cloud/models`):

- `POST https://ollama.com/api/chat` with `Authorization: Bearer <key>`.
  It streams newline-delimited JSON. Each line has `message.content`, plus
  `message.thinking` when thinking is on. The last line has `done: true`,
  `done_reason`, the token counts and the durations in nanoseconds. An error
  in the middle of a stream comes as a line with `error`.
- `GET https://ollama.com/api/tags` lists the names that direct requests
  use, such as `gpt-oss:120b`. The `-cloud` and `:cloud` names are only for
  a signed-in local Ollama. Day 32's static list used those names
  (`gpt-oss:120b-cloud`) and listed models that are no longer on the list,
  so Models → Cloud now reads `/api/tags`, which needs no key. If that list
  can't be read, Models shows a short fallback (`gpt-oss:120b`,
  `gpt-oss:20b`, `gemma4:31b`, all on the list on 2026-11-24). Older
  `…-cloud` ids still map to the direct name.
- Errors are JSON `{"error": "…"}` with the status codes 400, 401/403,
  404, 429, 500 and 502.

**How it works.**

- `proxy/cloud_chat.py` (new) turns the page's chat body into Ollama's
  `/api/chat` body. It keeps the messages, maps `temperature` and
  `max_tokens` to `options.num_predict`, and sends the Thinking button as
  `think`: `low`/`medium`/`high` for gpt-oss, `true` or `false` for others.
  If a model answers 400 saying it does not support thinking, Caravan asks
  once more without `think`. Each NDJSON line becomes an OpenAI-shaped
  stream chunk, so the page reads a cloud reply exactly like a Mac reply.
  The reply ends with the usual `caravan.meta` event, which now carries a
  `cloud` block.
- `POST /api/cloud/use {provider, model}` picks the cloud model.
  `POST /api/cloud/stop` goes back to the Macs. `/api/status` has
  `cloud` (model, label, CLOUD). The choice is saved in
  `<state_dir>/cloud-choice.json` (0600, provider and model only, never the
  key), next to `last-model.json`, so a restart comes back the way it was
  (Brenden: "If it was cloud, it should be cloud"). Unload and loading a
  model on the Macs clear it. The start-up restore of the last Mac model
  (`/api/models/load` with `_restore_token`) leaves it alone. If the key is
  missing or rejected after a restart, the pick stays cloud and the status
  pill and the reply show the plain error; Caravan does not fall back to the
  Macs, the same way `web_restore` never swaps in a different model.
- When a cloud model is picked, `/api/chat` and `/v1/chat/completions`
  go to Ollama Cloud even with no model loaded on the Macs. They are not
  counted as Mac work for Auto-tune. **Stop** uses the same request id and
  closes the HTTPS connection, which ends the reply at Ollama and keeps the
  words so far. The queue needs no changes: the page sends the next message
  when a reply ends, as before.
- Cloud chats are **not** written to the request journal, because a replay
  after a restore would send them to the Macs.

**Labels.** The status pill reads "ready · gpt-oss:120b · CLOUD (Ollama
Cloud)" with a blue dot. Each cloud reply's name line carries a
"CLOUD · Ollama Cloud · model" tag. The first cloud message on a browser
asks once: "This message leaves your Macs. It goes over the internet to …
on Ollama Cloud, and so does the rest of this chat. Send it?" If you
answer no, a queued message goes back to the front of the queue and the
queue waits until you send again. The speed line under a cloud reply
uses Ollama's token counts and its own write time (`eval_duration`), plus
the first-word and total time measured at Caravan. It is not added to the
Macs' speed average. **Unload** on a cloud model goes back to the Macs.

**The key.** `cloud_keys.resolve` (environment first, then the 0600
file). Caravan puts the key only in the `Authorization` header to
Ollama. It is never logged, never in an error (any echo is scrubbed),
never sent to the page, and never in the journal or a saved chat.
Picking a cloud model and cloud chats always work from this Mac and over
Tailscale. **Local network (Brenden: "Some people may not have tail
scale").** They work there too, but only after a warning and an explicit
OK. The warning names the real risk: anyone on the same Wi-Fi or local
network who can open the page can chat through your Ollama Cloud account,
using up your plan and its limits, and what they type goes to Ollama's
servers; Tailscale is safer if you have it. Without the OK the server
answers 403 `cloud_lan_needs_ok` with the warning, and `/api/status` tells
a local-network viewer `lan_needs_ok`. The page shows the warning when
local network access is turned on while a cloud key or pick exists, and
on a local-network viewer's first cloud pick or chat. OK posts
`/api/lan {"cloud_ok": true}`, saved as `[lan] cloud_ok = true` in
`~/.caravan/config.toml` beside `enabled` (commit 9137fd8's setting).
Turning local network access off clears it. The key itself stays hidden
from the local network (`/api/cloud-keys` still answers `show: false`).

**Plain errors.**

| Case | Caravan answers |
| --- | --- |
| No key | 400 "Add your Ollama Cloud API key in Settings → Cloud API keys first." |
| Bad key (401/403) | 401 "Ollama Cloud didn't accept the API key. Check it in Settings → Cloud API keys." |
| Unknown model (404) | 404 "Ollama Cloud has no model named …" |
| Rate or usage limit (429) | 429 "…too many requests, or your usage limit is reached…" |
| Ollama down (5xx) | 502 "Ollama Cloud couldn't answer right now (HTTP n)…" |
| No internet / timeout | 502 / 504 "Couldn't reach Ollama Cloud…" / "didn't answer in time…" |
| Error mid-reply | Words so far kept, plus "Ollama Cloud stopped mid-reply: …" |

All new text is in all five locales (en, es, ru, ja, zh-Hans). Five Day 32
strings it replaced are gone: the "isn't built yet" and "framework only"
texts, and the "ends in" text that only they used.

**Tests.** `tests/test_day33_cloud_chat.py` has 46 tests against a local
mock of Ollama's API. No test reaches the network or uses a real key;
`tests/conftest.py` keeps the Models → Cloud list offline unless a test
points it at the mock. The tests cover the body mapping (thinking effort,
on and off), legacy names, scrubbing the key, missing numbers staying
missing, picking and clearing, Mac load clearing the pick, a restart keeping cloud
or Macs as it was (file 0600 with no key; missing or bad key after a
restart shows the error and does not fall back; broken files ignored), the
local network refused until the OK with the plain risk warning, the OK
saved and then working with the key still hidden, `lan_needs_ok` in
status, turning the local network off taking back the OK, a streamed reply (text, thinking, CLOUD meta, Ollama's
token counts, the `Authorization` header), chat with no Mac model, a
non-streamed reply, the retry without thinking, 401, 404, 429, 500, the
network being down, the key being removed after picking, an error
mid-stream, a cut stream, Stop mid-reply, two chats in a row, the live
list, the fallback list, the download route refusing cloud, and the page
contract. One older guard check (`test_web_server`) now expects
`!chatOk` instead of `st !== "ready"`.

**Checked live.** From the dev node on 2026-11-24, without a real key:
`GET https://ollama.com/api/tags` returned 25 models, with
`gpt-oss:120b`, `gpt-oss:20b` and `gemma4:31b` sorted first. A
`POST /api/chat` with a made-up key returned 401, which Caravan shows as
"didn't accept the API key". The made-up key did not appear in the
message.

**Still needs a live test by Brenden (real key, on the Macs).** No Ollama
key is saved on the dev node, so no real cloud chat was sent. Still to
try: a streamed cloud reply in the browser, Stop in the middle of a cloud
reply over HTTPS, Thinking on and off (and gpt-oss effort), and a real
usage-limit 429 if one comes up.

## A GGUF split pick downloads each Mac's part (CAR-9, v0.9.17)

Built on the local branch `day33-gguf-split-pick` (from the v0.9.16 wrap
`cff7e2c`). Logged by Claude as CAR-9 on 2026-11-24 from Brenden's report.
Reworked the same night after Brenden's rule (below); the first cut (whole
file on every Mac in a split) was replaced before anything was committed.
Claude reviewed the reworked, uncommitted work and approved it on
2026-11-25 with no issues found (full suite 2,403 of 2,403 with the review
command). Merged to `main` fast-forward only. The Macs were not updated;
Brenden updates them himself.

Released as [v0.9.17](https://github.com/linuxbren/caravan/releases/tag/v0.9.17):
source `2dfb65d`, pin `94559e5`; tag v0.9.17 on the wrap commit. Notes:
[release-notes/day33-v0.9.17.md](release-notes/day33-v0.9.17.md).

**Next (CAR-10).** Brenden, 2026-11-25: a split pick must split in the
download, not download everything and split later, because without
Thunderbolt that can take a long time. So for single-file `llama`/`qwen2`
GGUFs, a missing build toolchain should no longer push a split pick to the
cable split: the installer and `caravan update` should put the own-part
engine on every configured Mac. Several-file GGUFs and other architectures
need engine work first; that's on the roadmap further out.

**The bug.** A GGUF that fits on one Mac. Step 2 recommended a split across
2 Macs, because only the split holds the model's full trained chat window
(Day 31 placement). Brenden accepted the recommendation, and only the 1st
Mac downloaded anything. He won't re-split a model after it's downloaded,
so the split has to happen at download time.

**Root cause (v0.9.16, `proxy/web_server.py`, `_api_picker_download`).**
The own-part download (`web_gguf_shares`) ran only when the pick was a
split **and** the model did not fit on one Mac (`... and not one_ok`). A
split chosen for the full window is exactly the case where the model *does*
fit on one Mac with a shorter window, so it skipped the own-part path. The
targets were then cut to the 1st Mac, and the whole file went there only.
An unsupported layout (`UnsupportedLayout`) or a missing own-part engine
(`gguf_runtime.current()` raising `FileNotFoundError`) fell through to the
same 1st-Mac-only download, without a word.

**Brenden's rule.** If you pick a split, it is split: each Mac downloads
only its own part, and the model runs only as that split. If you pick one
Mac, that Mac downloads the whole file and it isn't a split. If per-Mac
parts can't happen, Caravan says so before downloading and gives the real
options. It never quietly does something else.

**What it does now.**

- **Split across N Macs (GGUF):** always the own-part download, whether or
  not the model also fits on one Mac. Each Mac downloads only its layers
  (`web_gguf_shares.preview` with that split's Macs, then
  `web_files.start`). The model is registered as `gguf-shards/<repo>/<file>`
  with a single placement, that split, so Settings shows it as
  "Split-only: each of the N Macs keeps only its part". This also covers 3
  or more Macs, and a GGUF split never reaches the MLX N-stage planner.
- **Before any byte moves,** every picked Mac is asked whether it has the
  own-part engine, or the tools to build it (below). If a Mac can't, or
  can't be reached, the download stops with a 409 that names the Mac and
  what it needs: "Nothing was downloaded."
- **One Mac:** unchanged. Only that Mac downloads the whole file. Not a
  split.
- **Copy to all:** unchanged. Every online Mac downloads the whole file.
- **When per-Mac parts can't work for this file** (the model comes in
  several files, its architecture isn't one the own-part engine reads, or
  this Mac has neither the engine nor the tools to build it), Step 2 says
  so: the own-part split is greyed out with the reason, and a separate,
  labeled choice appears: "Split across N Macs over the cable". That one
  downloads the whole file to the 1st Mac only, and the other Macs get
  their part over the cable at each load (standard llama.cpp RPC, what the
  official engine does). Step 2 picks it as the default only where the
  greyed split would have been the default, and the warning above the
  choices also points to one Mac. Picking the greyed split anyway is
  refused (400).
- **Older saved splits** (whole file on the 1st Mac, from before this
  change) still load as before: `gguf_saved_placement_id` and the worker
  launch are unchanged.

**The own-part engine (what Brenden needs to know).**

- It is a separate llama.cpp build, not the official engine. It is pinned
  to llama.cpp `76a67730…` plus Caravan's patch
  (`runtime/gguf-shards/apply.py`), and built from source on each Mac by
  `gguf_runtime.ensure()`: git fetch, patch, then cmake with
  `GGML_RPC=ON` (build timeout 1800 s). It needs Apple's Command Line
  Tools, git and cmake on every Mac. It lives in
  `~/.caravan/runtimes/gguf-shards/<pin>/`.
- The first own-part download on a Mac builds it there
  (`gguf_share_download._fetch_locked` calls `ensure()`), the way Day 22
  ran it. When this Mac doesn't have it yet, Step 2 adds "The first split
  download also builds the own-part engine on each Mac, which takes a
  while."
- It reads single-file GGUFs with the `llama` or `qwen2` architecture and
  standard tensor names only. Anything else (for example the `qwen3` or
  `gpt-oss` architectures) gets the cable split or one Mac. Inkling 2
  Mini's architecture wasn't checked here.
- The installer and `caravan update` don't install it. Day 23 chose a
  prebuilt official llama.cpp (b12283) with no toolchain build on a clean
  install, and `scripts/install.sh` doesn't install cmake. To make per-Mac
  parts the norm, the installer/update would have to install cmake and run
  `gguf_runtime.ensure()` on each Mac, or Caravan would have to ship a
  pinned prebuilt own-part engine. Neither is in this change. Brenden
  chose to reverse Day 23 here; that is CAR-10 (above).
- Day 22 is the only live run of the own-part path (Qwen2.5-3B-Instruct
  Q5_K_M, shares 1:1): the 1st node fetched 1,248,806,912 assigned bytes in
  457.572 s, the 2nd node 1,183,977,472 bytes in 303.464 s (including its
  first-use native prep), and it served at 35.8 tok/s. See
  [DAY22](DAY22.md).

**Full context.** Day 31 sums each picked Mac's memory budget for a split,
and the default is the smallest placement that holds the model's full
trained window. With per-Mac parts, each Mac holds only its layers, so the
memory a split frees on each Mac goes to the chat window, and the window
the recommendation promised is there on the first load, with no re-split.
The Day 31 table shows the pattern: Llama 3.1 8B 4-bit (MLX) gets 64K on
one Mac and the full 128K on two; Qwen3 30B-A3B Q4_K_M (GGUF) doesn't fit
on one Mac and gets the full 32K on two
([DAY31](DAY31.md#check-against-real-models-before-publishing)). That Qwen3
model is a `qwen3` GGUF, so today it would get the cable split, not
per-Mac parts.

**What you see.**

- **Step 2:** one line under each choice says where the download goes:
  "This Mac downloads the whole file and runs it on its own, not split.",
  "Each Mac downloads only its own part. The model then runs only as this
  split, on these Macs.", "Every Mac downloads the whole file." The cable
  choice says "Only the 1st Mac downloads the whole file. At every load,
  the other Macs get their part over the cable. Not a split download." When per-Mac parts can't
  work, a warning above the choices says why, before you start.
- **Download card:** one row per Mac. Own-part rows say "Only its part:
  layers 0–16, 2.1 GB" (layers and size from the plan). A cable split says
  "Whole file · the other Macs get their part over the cable at each
  load".
- **Topology → On disk:** split-only models are listed (where each part is
  held) and can be deleted. Delete removes each Mac's part
  (`~/.caravan/gguf-shares/...` only, never a symlink) and then the
  registry record; if a Mac is off, the record stays and the page names
  the Mac that still has its part. A loaded model or an older own-part
  tree outside `gguf-shares` is refused. A plain GGUF is deleted on every
  Mac that has a copy (`gguf_split.py --delete`), with the same warning.

### Files

`proxy/gguf_split.py` (download notes, own-part status, the engine check
script, the cable option, `delete_local` and `--delete`),
`proxy/web_server.py` (the download fix, the engine check on every Mac,
On disk rows, delete routes), `proxy/web_gguf_shares.py` (split-only note,
`disk_rows`, `delete_deployment`), `proxy/web_files.py` and
`proxy/web_picker.py` (per-Mac row text, GGUF delete on every Mac),
`proxy/web/index.html`, `locales/*.json` (18 new strings in en, es, ru, ja
and zh-Hans; the first cut's strings removed).

### Tests

`tests/test_day33_gguf_split_pick.py`, 44 tests, all mocked (no network,
no Macs). The regression is first: a GGUF that fits on one Mac, Step 2
recommends 2 Macs for the full window, the recommendation is accepted,
and each Mac downloads only its part (the own-part planner gets both Macs,
the whole-file download is never called, and the result is saved
split-only). Also: one Mac and copy to all unchanged; 3 Macs; missing
engine or tools, a Mac that can't be reached, an unsupported layout or not
enough memory all refuse before anything downloads; the greyed split and
the cable choice; download notes; per-Mac rows; Settings split-only;
older splits; own-part and GGUF delete; strings in all 5 languages.
`test_day22_share_download`, `test_day23_clean_install` and
`test_day31_context_fit` were updated for the rule (no silent fallback; the
old `and not one_ok` check is asserted gone). Full suite: 2,403 passed
(v0.9.16: 2,359).

### Still needs a real run on the Macs

1. Brenden's case: a GGUF that fits on one Mac, accept the 2-Mac split for
   the full window, and check that each Mac downloads only its part, that
   Settings shows it split-only, and that it loads with the full window.
2. The first own-part download on a Mac without the engine: the build
   (CLT, git, cmake present), its time, and how the card shows it.
3. A Mac without cmake: Step 2 and the 409 message name it.
4. A `qwen3` or `gpt-oss` GGUF: the greyed split, the cable choice, and a
   cable download.
5. Delete of a split-only model with both Macs on, and with one off.
6. An older lead-only split still loads.
