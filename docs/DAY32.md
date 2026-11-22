# Day 32 — localization; part A: version label

Day 32 runs Nov 22 2026 (America/Chicago). Part A is released as
[v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4), its fix as
[v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5).

1. [Status of every Day 32 request](#status-of-every-day-32-request)
2. [Plan: localization](#plan-localization)
3. [Part A: version label](#part-a-version-label)
4. [Part A fix: daily update check (v0.9.5)](#part-a-fix-daily-update-check-v095)
5. [Proposal: API keys for cloud models](#proposal-api-keys-for-cloud-models)
6. [Cloud API keys: built, waiting on review](#cloud-api-keys-built-waiting-on-review)

## Status of every Day 32 request

| Request | Status |
|---|---|
| Part A: version label next to Settings ([v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4)) | Done, released, on both Macs |
| Daily-check-off fix and daily check audit ([v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5)) | Done, released, on both Macs, checked live with the switch on and off |
| Header layout: model/status pill above and outside the chat card's top-left corner (just outside its border, where the CHAT label was); **Update available** right of the theme picker; nothing wraps at narrow widths (long model names end in "…", full name on hover) | Built and tested on a local branch (not pushed); waiting on Brenden's review before release |
| Chat message queue: Send reads **Queue** while the model answers; queued messages send in order when the answer finishes (also after an error or Stop); a floating strip just above the prompt box, one chip per message (full text on hover) with a × to cancel; a queued message is journaled only when it sends; Stop still works | Built and tested on a local branch (not pushed); waiting on Brenden's review before release |
| API keys for cloud models: a **Cloud API keys** section in Settings (one row per provider, masked, editable, removable); an inline key prompt when a cloud model's provider has no key; cloud models say **Load**, not Download ([what was built](#cloud-api-keys-built-waiting-on-review)) | Approved; built and tested on a local branch (not pushed); waiting on Brenden's review before release |
| Sending chats to a cloud model (routing `/api/chat` to the provider) | Not built; outside the approved scope; needs its own approval |
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
doesn't exist yet. Status: **approved and built on a local branch,
waiting on review** (see [below](#cloud-api-keys-built-waiting-on-review)).
The proposal below is kept as written; what was built differs in a few
places, listed in the next section.

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

## Cloud API keys: built, waiting on review

Brenden approved the cloud keys request with three parts. All three are
built on the local branch `day32-header-layout` (with the header layout
and the chat queue). Nothing is pushed or released and the Macs are not
changed until Brenden reviews it.

1. **Settings → Cloud API keys.** One row per provider: OpenAI,
   Anthropic, OpenRouter and Ollama Cloud. Each row shows "Not set" or
   "Set · ends in abcd", has a password field with **Save**, and has
   **Remove** for a key saved from Settings. A key set by an environment
   variable shows "From OPENAI_API_KEY" (for example). It can't be edited
   from the page, because the environment variable wins.
2. **Inline key prompt.** In Models → Cloud, pressing **Load** on a cloud
   model whose provider has no key opens a small box in that row: "… runs
   on Ollama Cloud. Add your Ollama Cloud API key to load it. It's saved
   only on this Mac." It has **Save and load** and **Cancel**. After
   saving, it carries on with the load.
3. **Load, not Download.** Cloud rows in the Models picker say **Load**.
   If a cloud model ever shows in the Settings model list, it says "cloud
   — open Models to Load" instead of "not downloaded".

How keys are kept:

- They are stored in `~/.caravan/cloud-keys.json` on the 1st Mac only,
  with 0600 permissions. The file is written atomically (temp file,
  chmod 0600, then rename). `CARAVAN_CLOUD_KEYS_PATH` can move it, and
  tests use that.
- The page and API only ever get the last 4 characters. Keys are never
  logged and never echoed in an error. A bad key gets "That doesn't look
  like an API key" with nothing repeated back. The page clears the field
  after Save, whether it worked or not.
- Keys can only be read or changed from this Mac or over Tailscale, the
  same rule as Update now. From the local network, GET returns
  `show: false` with no providers, and POST returns 403.
- A cached Models search refreshes each cloud row's "key set" flag, so it
  never shows an old "no key".

Differs from the proposal: there is one file, not one per provider, and
there is no **Test** button yet.

**Not built: sending chats to a cloud model.** That would route
`/api/chat` to the provider and add a first-chat notice that the message
leaves your Macs. It needs its own approval. Until then, after the key is
saved the picker says so plainly: "Ollama Cloud key ready (ends in abcd).
Chatting with cloud models isn't built yet, so … can't load in chat yet."

Code: `proxy/cloud_keys.py` (new), `GET/POST /api/cloud-keys` in
`proxy/web_server.py`, the key flag in `proxy/web_picker.py`, and the
Settings section and picker prompt in `proxy/web/index.html`.

Tests: `tests/test_day32_cloud_keys.py` has 13 tests. They cover 0600
storage, last 4 only, replace and remove, refusing a bad key without
echoing it, the environment winning, a broken file, the API never
returning or logging a key, the local network getting no access, picker
rows, and the page contract. The full suite on the branch passes: 2,104
tests.

Screenshots, for review only, are not in the repo: Settings section,
inline prompt, the Load button and the message after saving, at 375 and
1280 px.
