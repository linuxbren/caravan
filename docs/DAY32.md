# Day 32 — localization; part A: version label

Day 32 runs Nov 22 2026 (America/Chicago). Part A is released as
[v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4), its fix as
[v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5).

1. [Status of every Day 32 request](#status-of-every-day-32-request)
2. [Plan: localization](#plan-localization)
3. [Part A: version label](#part-a-version-label)
4. [Part A fix: daily update check (v0.9.5)](#part-a-fix-daily-update-check-v095)
5. [Proposal: API keys for cloud models](#proposal-api-keys-for-cloud-models)

## Status of every Day 32 request

| Request | Status |
|---|---|
| Part A: version label next to Settings ([v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4)) | Done, released, on both Macs |
| Daily-check-off fix and daily check audit ([v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5)) | Done, released, on both Macs, checked live with the switch on and off |
| Header layout: model/status pill above and outside the chat card's top-left corner (just outside its border, where the CHAT label was); **Update available** right of the theme picker; nothing wraps at narrow widths (long model names end in "…", full name on hover) | In progress on a local branch; waiting on Brenden's approval before release |
| Chat message queue: Send reads **Queue** while the model answers; queued messages send in order when the answer finishes (also after an error or Stop); a small strip along the bottom of the answer, one chip per message with a × to cancel; a queued message is journaled only when it sends; Stop still works | In progress on a local branch; waiting on Brenden's approval before release |
| API keys for cloud models in Settings: a place to enter keys for cloud model providers ([findings and proposal](#proposal-api-keys-for-cloud-models)) | Waiting on approval; not built |
| Localization (main theme): one English strings file keyed by name, English fallback, then Spanish, Simplified Chinese, Japanese, then German | Not started |

## Plan: localization

- Pull every piece of text the web page, the `caravan` command and the
  installer show into one English strings file, keyed by name.
- Look text up by key, with English as the fallback for a missing key or
  language, so a half-translated language never shows a blank.
- First languages: Spanish, Simplified Chinese and Japanese. Then German,
  to test long words in buttons and narrow layouts.

## Part A: version label

Brenden: "Lets first do the version for 32 so that I can use it now."

- Settings now shows the installed version, small and dim, right next to
  its title, for example `v0.9.4 · up to date`.
- The status comes from the existing daily update check: "up to date"
  when the last check found nothing newer, "update available" when a newer
  release is out or another Mac is behind (click it to go to **Update
  now**). With no check yet, daily checks off, or no internet, only the
  version shows. On the local network (no update view), only the version
  shows.
- Where the number comes from: a new `VERSION` file in each release's
  source commit (`0.9.4`), read from the installed copy, plus the
  installed pin (`.caravan-package`) as the build (hover the version to
  see it). Nothing is written into the page. A source checkout uses
  `VERSION` and its git commit.
- `caravan --version` (also `caravan version`) prints
  `Caravan v0.9.4 (<build>)`, `caravan status` says
  `Caravan v0.9.4 is running`, and `caravan doctor` lists
  `Installed: Caravan v0.9.4 (<build>).`
- `/api/status` has a new `version` field: `version`, `label`, `ref`,
  `short`, `packaged`.
- The label uses the theme's `--mono` font and `--muted` color; "update
  available" uses the accent color, like other links in Settings.
- Release steps: set `VERSION` in the source commit
  ([RELEASES](RELEASES.md)).

### Tests

- `tests/test_day32_version_label.py` (13 tests): the version and build
  from a fake install, unknown when `VERSION` is missing or malformed (never
  guessed), a bad pin ignored, `VERSION` matches the newest CHANGELOG
  entry, no version written into the page or server, the `/api/status`
  field, the label's place and theme styles, the state rules (also run in
  Node: hidden view, source checkout, newer, other Mac behind, checked,
  offline, never checked), and `caravan --version` / `doctor`.
- `tests/test_day23_clean_install.py`: the one-line `caravan status` now
  includes the version.
- Full suite: 2,051 tests, OK.

### Release

- Source `61d6c09`, pin `33caff0`; tag
  [v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4) on the
  wrap commit. Notes: [release-notes/day32-v0.9.4.md](release-notes/day32-v0.9.4.md).

### Live update

- Before updating: nothing was downloading or tuning, Qwen3 32B 4-bit was
  ready, and the last chat request had been many hours earlier.
- `caravan update --yes` on the 1st Mac updated the 2nd Mac first, then
  itself. Both Macs: `caravan --version`, `caravan status` and
  `caravan doctor` all say v0.9.4 (`61d6c09`).
- The update only restarted the page. The model process kept running, and
  Qwen3 32B 4-bit stayed loaded and ready.
- Settings shows `SETTINGS v0.9.4 · up to date` in the dim mono style next
  to the title.

## Part A fix: daily update check (v0.9.5)

A review of v0.9.4 found that turning **Check for updates daily** off did
not do what this page says: once a check had run, the label kept saying
"up to date" (and the **Update available** badge and the Mac lines stayed
too) after the switch was turned off. Brenden also asked whether the daily
check works as intended at all, so the whole check was audited.

Confirmed and fixed:

- **Daily off now hides the status.** With the switch off, the server sends
  no update status: no badge, no Mac lines, no "checked" time, so the label
  shows just the version. **Check now** (or `caravan update --check`) used
  after turning it off still shows its answer. An update that is running is
  always shown. The current switch setting now always wins over the one
  saved with the last check.
- **Live, no reload.** Turning it off clears the label, badge and Mac lines
  at once. Turning it on shows the last answer if it is less than a day
  old, or checks right away instead of up to an hour later.
- **One error stopped daily checks until a restart.** The hourly loop sat
  inside one `try`, so any unexpected error ended it for good. Now each
  round is caught and logged, and the loop goes on (`run_daily_loop`).
- **A broken reply counted as an error, not offline.** A cut-off HTTP reply
  (`http.client.HTTPException`, e.g. `IncompleteRead`) was not caught by
  the fetches. Now it is treated like being offline.
- **Offline kept saying "up to date".** When a check failed, the older
  answer was returned but not saved as offline, so the page and the label
  kept showing "up to date" from an old check. Now the offline state and
  the time of the try are saved (the last good check time is kept), and it
  is retried hourly, also after a failed Check now.
- **A check time in the future blocked checks.** If the clock was wrong
  when a check was saved, no check ran until that time came. Such a check
  is now always due.

Checked and fine as it was:

- It runs about 4 seconds after the page starts, then every hour, and only
  fetches when the switch is on and the saved check is a day old (or this
  Mac's version changed, e.g. right after an update).
- The saved check survives restarts (`~/.caravan/web-ui/update-check.json`),
  so restarting the page does not cause an extra fetch.
- It compares the installed pin (`.caravan-package`) with the published
  `packaging-version` on `main`, and the page re-checks against the
  installed pin, so a check saved before this Mac's own update never says
  "update available" afterwards.

Tests: `tests/test_day32_daily_check.py` (27 tests): daily off hides a
newer and an up-to-date answer, Check now while off still shows, a check
from before turning off stays hidden, the current setting wins, a running
update still shows, turning back on uses a fresh answer without a fetch or
checks a stale one right away (through `/api/update`), once a day,
restarts, the future clock, offline saved and retried hourly, a broken
HTTP reply, the pin comparison, the loop surviving a failed round and
honoring the switch, and `versionState` in Node.

Full suite: 2,078 tests, OK.

Release: source `7251223`, pin `f5b6842`; tag
[v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5) on the
wrap commit. Notes: [release-notes/day32-v0.9.5.md](release-notes/day32-v0.9.5.md).

### Live update (v0.9.5)

- Before updating: nothing downloading or tuning, Qwen3 32B 4-bit ready,
  the last chat finished minutes earlier and nothing was running.
- `caravan update --yes` on the 1st Mac updated both Macs; all three
  commands say v0.9.5 (`7251223`). The model process was not restarted by
  the update and Qwen3 32B 4-bit stayed loaded and ready.
- On the live page, with the switch on the label read
  `v0.9.5 · up to date` with both Mac lines; switching off cleared the
  status to `v0.9.5` and the Mac lines at once, with no page reload; on
  again brought them back within a few seconds. The switch was left as it
  was found (off).

## Proposal: API keys for cloud models

Brenden: Settings needs a place to enter API keys for cloud models, if one
doesn't exist yet. Status: **waiting on approval, not built.**

What Caravan has today (checked in the code, nothing changed):

- **No working cloud provider.** Chats only go to the model on your Macs
  (`/api/chat` → the local worker). There is no OpenAI, Anthropic or
  OpenRouter client.
- **Ollama Cloud is listed but "framework-only".** The Models picker has a
  **Cloud** source with a fixed list of Ollama Cloud models labeled CLOUD
  (`proxy/web_picker.py`). Choosing one shows "Ollama Cloud is
  framework-only for now. Set OLLAMA_API_KEY in config/env", and the server
  refuses to "download" it. The key is read only from the
  `OLLAMA_API_KEY` (or `CARAVAN_OLLAMA_API_KEY`) environment variable at
  start, and is used only to report "key configured".
- **The only key Settings stores is the Hugging Face token.** It is saved
  to `~/.caravan/hf_token` with 0600 permissions, copied to the other Macs
  over SSH, never sent back to the page (only "set / not set"), and
  removable from Settings. A webhook key for alerts
  (`CARAVAN_ALERT_WEBHOOK_KEY`) is environment-only.

Proposal (to approve before any work):

- **Providers, first:** OpenAI, Anthropic and OpenRouter (OpenRouter covers
  many models with one key), plus the existing Ollama Cloud entry. Later,
  any OpenAI-compatible endpoint (base URL + key).
- **Settings → "Cloud models" card:** one row per provider with a masked
  key field (shows only "set · ends in …abcd"), **Save**, **Test** (one
  tiny request, plain result) and **Remove**. Only from this Mac or
  Tailscale, like Update now; not from the local network.
- **Storage:** one file per provider under `~/.caravan/keys/`
  (directory 0700, files 0600), written atomically, on the 1st Mac only
  (cloud calls don't need the other Macs). Environment variables still win,
  as today.
- **Never shown or logged:** the API never returns a key, logs and errors
  redact it, it is not in the request journal, saved chats, crash reports
  or `caravan doctor` output (only "set / not set").
- **Plain consent:** cloud models stay labeled CLOUD, and the first chat
  with one says the message goes to that provider (docs/SECURITY.md
  already says optional cloud features send data to the provider you
  choose).
