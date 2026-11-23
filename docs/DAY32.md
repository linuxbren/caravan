# Day 32 — localization; part A: version label; part B: chat and header

Day 32 runs Nov 22 2026 (America/Chicago). Part A is released as
[v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4), its fix as
[v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5). Part B (header layout, chat
queue, Ollama Cloud key, Stop a reply) is a mid-day release,
[v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6). Localization step 1 (all
user-facing text in one English strings file) is another mid-day release,
[v0.9.7](https://github.com/linuxbren/caravan/releases/tag/v0.9.7). GGUF placement is another mid-day release,
[v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8). Spanish is another mid-day release,
[v0.9.9](https://github.com/linuxbren/caravan/releases/tag/v0.9.9). Russian is another mid-day release,
[v0.9.10](https://github.com/linuxbren/caravan/releases/tag/v0.9.10). Japanese is another mid-day release,
[v0.9.11](https://github.com/linuxbren/caravan/releases/tag/v0.9.11). Day 32 stays open: Simplified
Chinese can drop in later.

1. [Status of every Day 32 request](#status-of-every-day-32-request)
2. [Plan: localization](#plan-localization)
3. [Localization step 1: English strings file](#localization-step-1-english-strings-file)
   (release: [v0.9.7](#localization-step-1-release-v097))
4. [Part A: version label](#part-a-version-label)
5. [Part A fix: daily update check (v0.9.5)](#part-a-fix-daily-update-check-v095)
6. [Part B: header layout (v0.9.6)](#part-b-header-layout-v096)
7. [Part B: chat message queue (v0.9.6)](#part-b-chat-message-queue-v096)
8. [Part B: Ollama Cloud API key (v0.9.6)](#part-b-ollama-cloud-api-key-v096)
9. [Part B: Stop a reply (v0.9.6)](#part-b-stop-a-reply-v096)
10. [Part B: tests and release (v0.9.6)](#part-b-tests-and-release-v096)
11. [Superseded: first proposal for cloud API keys](#superseded-first-proposal-for-cloud-api-keys)
12. [GGUF placement (ROADMAP #9)](#gguf-placement-roadmap-9)
    (release: [v0.9.8](#gguf-placement-release-v098))
13. [Spanish (v0.9.9)](#spanish-v099)
14. [Russian (v0.9.10)](#russian-v0910)
15. [Japanese (v0.9.11)](#japanese-v0911)

## Status of every Day 32 request

| Request | Status |
|---|---|
| Part A: version label next to Settings ([v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4)) | Done, released, on both Macs |
| Daily-check-off fix and daily check audit ([v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5)) | Done, released, on both Macs, checked live with the switch on and off |
| Header layout: model/status pill above and outside the chat card's top-left corner (just outside its border, where the CHAT label was); **Update available** right of the theme picker; nothing wraps at narrow widths (long model names end in "…", full name on hover) | Done, released in [v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6) (part B); Brenden updates the Macs himself |
| Chat message queue: Send reads **Queue** while the model answers; queued messages send in order when the answer finishes (also after an error or Stop); a floating strip just above the prompt box, one chip per message (full text on hover) with a × to cancel; a queued message is journaled only when it sends; Stop still works | Done, released in [v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6) (part B); Brenden updates the Macs himself |
| API keys for cloud models: a **Cloud API keys** section in Settings (Ollama Cloud only, the one cloud source Models can search; masked, editable, removable); an inline key prompt when a cloud model's provider has no key; cloud models say **Load**, not Download ([details](#part-b-ollama-cloud-api-key-v096)) | Done, released in [v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6) (part B); Brenden updates the Macs himself |
| Chatting with Ollama Cloud models (routing `/api/chat` to Ollama Cloud) | Not for Day 32 (Brenden); the key is saved now, cloud chat comes later. On the [ROADMAP](ROADMAP.md) as a future item |
| Stop a reply while it is written: a **Stop** button under Send/Queue that really stops the model (the request to the model is closed, the split workers stop and are free for the next message), keeps the words so far marked "(stopped)", closes the journal job as stopped (never run again) and still sends queued messages next ([details](#part-b-stop-a-reply-v096)) | Done, released in [v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6) (part B); Brenden updates the Macs himself |
| Localization step 1: move all user-facing text into one English strings file keyed by name, English fallback, no other languages yet (Brenden: "start with compartmentalization first with English. Then we'll decide on additional languages.") | Done (fully compartmentalized: page, CLI, installers, server and worker messages), reviewed (Claude: approved), released in [v0.9.7](https://github.com/linuxbren/caravan/releases/tag/v0.9.7) (mid-day); Brenden updates the Macs himself ([details](#localization-step-1-english-strings-file)) |
| Spanish: CLDR plurals, `locales/es.json`, Settings language picker, locale formatting, layout screenshots, beta until native-reviewed | Done, reviewed (Claude: approved 09:05 CST), released in [v0.9.9](https://github.com/linuxbren/caravan/releases/tag/v0.9.9) (mid-day); Brenden updates the Macs himself ([details](#spanish-v099)) |
| Russian: `locales/ru.json`, glossary column, picker + installer, formatting, Cyrillic layout, plurals one/few/many/other, beta until native-reviewed | Done, reviewed (Claude: approved 11:05 CST), released in [v0.9.10](https://github.com/linuxbren/caravan/releases/tag/v0.9.10) (mid-day); Brenden updates the Macs himself ([details](#russian-v0910)) |
| Japanese: `locales/ja.json`, glossary column, picker + installer, formatting, CJK line breaking, `_other`-only plurals, beta until native-reviewed | Done, reviewed (Claude: approved 12:25 CST), released in [v0.9.11](https://github.com/linuxbren/caravan/releases/tag/v0.9.11) (mid-day); Brenden updates the Macs himself ([details](#japanese-v0911)) |
| A confirmation step before every download (ROADMAP Next candidates #9; raised in the step 1 review): GGUF should use the same Step 2 placement chooser as MLX, for every fit color | Done, reviewed (Claude: approved), released in [v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8) (mid-day); Brenden updates the Macs himself ([details](#gguf-placement-roadmap-9)) |

## Plan: localization

- Pull every piece of text the web page, the `caravan` command and the
  installer show into one English strings file, keyed by name.
- Look text up by key, with English as the fallback for a missing key or
  language, so a half-translated language never shows a blank.
- First languages: Spanish, Simplified Chinese and Japanese. Then German,
  to test long words in buttons and narrow layouts.

## Localization step 1: English strings file

Brenden: "start with compartmentalization first with English. Then we'll
decide on additional languages."

Every piece of text the web page, the `caravan` command and the installers
show now comes from one file, `locales/en.json`, keyed by name. The English
text is the same as before; no other language is added.

**The file.** `locales/en.json` holds 2,299 strings in six groups:

| Group | Strings | Used by |
| --- | --- | --- |
| `web.*` | 707 | the page (`index.html`, `pairing.html` and the page scripts) |
| `cli.<command>.*` | 351 | the `caravan` command and its tools (`tools/caravan*.py`) |
| `server.<module>.*` | 800 | web server messages that reach the page or the CLI (`proxy/*.py`: errors, statuses, progress lines) |
| `agent.<module>.*` | 338 | worker messages that reach the page or the CLI (`agent/*.py`: raised errors, status lines, worker CLI errors) |
| `fmt.*` | 16 | number, unit, list and ordinal formats (decimal mark, `{n} GB`, `{n} tok/s`, `{n}%`, `, `, ` and `, `1st`…) |
| `install.*` | 87 | the bootstrap (`install`) and `scripts/install.sh` |

Step 1 first moved the page, CLI and installer text (1,127 strings); the
finish-up moved the server and worker messages and the grammar below.

Values with `{name}` take values, filled with Python `str.format` rules
(`{{` and `}}` are literal braces, only in strings that take values).
Keys ending in `_html` hold markup and go into the page as-is; all other
text is escaped.

**How lookup works.**

- **Page:** markup uses `{{web.key}}`, filled by the server when it sends
  the page (`caravan_i18n.render_page`). The server also puts the page's
  strings into a small script (`window.CARAVAN_STRINGS`), and
  `/i18n.js` defines `T("web.key", {values})` for the scripts. A missing
  key shows English, then the key itself. The function is `T`, not `t`,
  because many page functions already use `t` as a local name.
  `<html lang>` is the active language (`en` today).
- **CLI, server, workers:** `from caravan_i18n import T`, then
  `T("server.web_workers.x", name=...)` (`tools/caravan_i18n.py`). Modules
  that already had a `T` alias renamed it (`GT` for `gguf_tune`, `WT` for
  `web_tunnels`).
- **Installers:** the bootstrap is downloaded on its own, before the rest
  of Caravan, so it can't read the strings file. Each installer carries a
  generated block of small shell functions (`S_name arg...` prints one
  string) between `# >>> caravan strings` markers. After editing
  `locales/en.json`, run `python3 tools/caravan_i18n.py --sync-shell`; a
  test fails if a block is out of date.

**Grammar, numbers and lists go through helpers** (the same names in
Python and on the page):

- **Plurals:** `T.plural("web.n_macs", n)` reads `web.n_macs_one` /
  `web.n_macs_other` and fills `{count}` (19 pairs, for example "1 Mac" /
  "2 Macs", "tried 1 change" / "tried 3 changes"). English picks `one`
  only for 1; another language adds its forms in `plural_form` /
  `T.pluralForm`.
- **Numbers and units:** `T.num(x, 1)` is `x` to one decimal with the
  language's decimal mark (`fmt.decimal`); `T.unit("gb", x, 1)` uses
  `fmt.gb` ("{n} GB"), likewise `tok_s`, `pct`, `mb`, `mb_s`, `seconds`.
  On the server, `{x:.1f}` inside a string also gets the decimal mark.
- **Lists and ordinals:** `T.join(items)` (", "; "clause" "; ", "and",
  "or"), `T.and_list` / `T.andList` ("a, b and c"), `T.ordinal(2)` ("2nd").
- **Sentences around a bold name** are one `_html` key with a placeholder
  ("No model is loaded. Load <b>name</b> now?").

**Code no longer reads English words.** Places that decided something by
matching English text now use a code, with the text looked up separately:

| Was matched | Now |
| --- | --- |
| saved replies starting "(no reply" / "(error:" | `data-bad="1"` on Caravan's own error bubbles (the two English starts only for chats saved before) |
| status pill text ("ready…") | `data-status` with the status code |
| errors containing "404" | the HTTP status on the thrown error |
| progress lines with "error"/"failed" (Caravan's own) | a `problem` flag on the progress line (worker output, always English, still matched) |
| split status "… layers ready" | a `stage_ready` code with label and count |
| download notes starting "can't read" | `msg_code: "cant_read"` |
| download stage text (retrying…) | `stage_code` (`starting`, `network_retry`, …) |
| Settings note /takes effect when you load/ | `notice_code: "on_load"` |
| "download only, …" notices → refusal text | a table from notice key to refusal key |
| model pair messages ("not found", "more than one") | a `blocked` flag from where the side is missing |
| thermal level ("nominal") and the worker's "layers 24-63 of 64" | looked up from the code / numbers (`web.thermal_*`, `web.layers_a_b_of_n`) |
| the saved default label "My Mac" | matched as English or the current language |

The speed journey (`proxy/web/journey.json`) is data; a translated copy
`journey.<lang>.json` is used when present.

**Adding a language later** is adding `locales/<code>.json` with some or
all of the same keys (missing ones show English), plural/ordinal rules if
they differ from English, plus choosing it. The hooks are in place but
off: `CARAVAN_LANG`, a Settings override (`_saved_language`, not built)
and the Mac's language (`mac_language`, returns nothing yet). There is no
picker yet.

**Nothing changed in English.** The page was captured before (main at
`f809d4f`) and after in seven states (main, Settings, Models, Models with
cloud results, Topology, a reply being written, a stopped reply) at 1280
and 375 px, from a freshly restarted offline mock. Page text is the same;
the markup differs only by the new `data-status` / `data-kind`
attributes and two blank lines where the strings script goes;
screenshots match pixel for pixel. 42 CLI and installer runs on Linux
(`caravan --help`, every subcommand and tool `--help`, `status`, `stop`,
`open`, `start`, `doctor`, `update --check`, `models`, `jobs`, `remote`,
`lan`, `bench`; installer `--help`, a bad option, `--dry-run`, `--check`,
and macOS-shimmed runs) print the same text, apart from the commit hash,
free disk space and a bash line number in a `sw_vers: command not found`
message on Linux.

**Pseudo-language check.** A throw-away `xx` language wrapping every
string in ⟦ ⟧ was loaded in the mock: every text on the page came out
wrapped except model, Mac and product names, numbers, addresses and
messages baked into the mock's recorded replies. It found five leftovers
(the thermal level, the layers range, the fit chip label, two option
labels), now fixed.

**Tests.** `tests/test_day32_localization.py` (24 tests): every key used
exists, no key is unused, values match placeholders (plural forms
included), a second language falls back to English, installer blocks
match the file, and lints that no hard-coded words are left in the page
markup, page scripts, CLI output, installer messages, or in server and
worker messages (`test_server_and_worker_messages`: raised errors,
progress notes and the `error`/`message`/`note`/`label`/… fields of
replies in `proxy/` and `agent/`). A short allowlist gives the reason for
each exception. Older tests that look for a phrase in the source read the
English back through `tests/i18n_check.py`. Full suite: 2,144 tests, OK.
The browser tests (`test_day32_header_queue`, `test_day32_stop_reply`)
now start a plain headless Chromium: the distro launcher had been adding
the user's own Chromium flags (extensions, renderer accessibility), which
slowed the page enough that `test_stop_flow` failed on and off, also on
`f809d4f`.

**Left as code, and why:**

- **Logs and developer tools:** server and worker logs, the request
  journal, `scripts/package.sh`, `scripts/restart-rpc-server.sh`,
  benchmark prompts, model prompts and the lab-only tools
  (`aux_worker.py`, `pairing_smoke.py`, `simulate_mlx_pipeline.py`,
  `tb_ssh_proxy.py`). Not shown to people using Caravan.
- **Technical values:** config names and TOML keys, launchd labels,
  command lines, model and family names, protocol tokens, and worker
  output from llama.cpp / MLX (English, passed through as it comes).
- **Times** show as 24-hour numbers (`HH:MM:SS.cc` milestone stamps),
  the same in any language; no month or day names are shown.
- **CLI text looked up once at start-up:** a few module-level messages
  are read when the command starts. Fine while the language is fixed per
  run.

### Localization step 1: release (v0.9.7)

Built on the local branch `day32-localization` (on `f809d4f`), reviewed
by Claude (approved: full suite 2,144 of 2,144 twice, string counts
checked against this page) and merged to `main` fast-forward only.
Released as a mid-day release: source `fcfdc35`, pin `deb0e52`; tag
[v0.9.7](https://github.com/linuxbren/caravan/releases/tag/v0.9.7) on the
wrap commit.
Notes: [release-notes/day32-v0.9.7.md](release-notes/day32-v0.9.7.md).

Nothing looks or reads differently in English; the update only moves where
the words live. No other language is added and there is no language
picker yet. The Macs were not updated as part of the release; Brenden
updates them himself with `caravan update`.

Still open in Day 32:
- Choosing and adding languages, then a language setting.


## GGUF placement (ROADMAP #9)

Brenden (2026-11-23): GGUF downloads should act exactly like MLX.

**Before:** GGUF downloads in Models skipped Step 2 unless the fit was
red, and even then only showed the automatic recommendation. The
download API ignored a chosen placement and always sent the file to the
lead Mini. At load, a one-Mini placement could be turned into a split.

**After ([v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8)):** every GGUF
download, any fit color, opens the same Step 2 chooser as MLX: 1 Mini /
split across K Minis / copy to all, for any number of Macs from the
config. Unfit options stay visible and disabled with the reason. The
default is the smallest placement that fits (for GGUF, the smallest that
holds the full chat window, as in Day 31). The choice is saved as
`caravan-placement.json` and honored at download and at load: only the
needed files go to the chosen Mini(s), and a one-Mini choice is not
turned into a split. New strings go through `locales/en.json` and `T()`.

Tests: `tests/test_day32_gguf_placement.py` (green/yellow/red all open
the chooser and send the placement, default is the smallest that fits,
the choice is honored at download and at load). Full suite: 2,161 passed,
97 subtests, with
`XDG_CONFIG_HOME="" PYTHONPATH=.:proxy:tests uv run --with pytest
--with spake2==0.9 --with cryptography==46.0.3 python -m pytest tests -q`.
The Macs were not updated (Brenden updates them himself).

The version-label test requires the first CHANGELOG heading to contain
`(v{VERSION})`. In-progress work stayed in this page and in ROADMAP
until this release (a premature "unreleased" top section in `127d957`
was dropped in `d9f6408` after review). The v0.9.8 CHANGELOG entry lands
in this release's source commit.

### GGUF placement: release (v0.9.8)

Built on the local branch `day32-localization` (on `7905018`), reviewed
by Claude (approved 2026-11-23 06:36 CST: full suite 2,161 of 2,161 with
the review command) and merged to `main` fast-forward only.
Released as a mid-day release: source `0a9097a`, pin `84d1b2a`; tag
[v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8) on the
wrap commit.
Notes: [release-notes/day32-v0.9.8.md](release-notes/day32-v0.9.8.md).

The Macs were not updated as part of the release; Brenden updates them
himself with `caravan update`. Day 32 stays open for choosing and adding
languages.

## Spanish (v0.9.9)

Brenden (2026-11-23): start Spanish, built so later languages can drop in.

**After ([v0.9.9](https://github.com/linuxbren/caravan/releases/tag/v0.9.9)):** Spanish is
the first language after English. Work was on the local branch
`day32-spanish` (from `main` at v0.9.8, `2e49275`). Claude approved the
uncommitted tree (09:05 CST); two non-blocking nits were fixed in a
follow-up commit. The Macs were not updated (Brenden updates them
himself).

What this adds:

- A CLDR plural engine (`one`/`other` for Spanish and English;
  `one`/`few`/`many`/`other` for Russian; `other` only for Japanese and
  Chinese). Keys use `_one` / `_few` / `_many` / `_other`, and fall back
  to `_other` then English.
- `locales/es.json` for every current English key (neutral Latin American
  / universal Spanish, casual *tú*). Model names, **Caravan**, **Mini**,
  **GGUF**, **MLX**, and commands stay in English. Glossary:
  [docs/i18n/GLOSSARY.md](i18n/GLOSSARY.md).
- A checker: every key present, `{name}` placeholders identical, `_html`
  tags identical, no empty strings. The installer shell block is
  regenerated from the language files.
- A Settings language picker (English, Español; others later) that
  switches the page live and persists. Default order: `CARAVAN_LANG`,
  then the saved Settings choice, then the Mac's language, then English.
  The `caravan` command and the installers follow the same setting.
  Spanish is marked **beta** in the picker until a native speaker reviews
  it. All picker strings go through `T()`.
- Locale formatting for Spanish: decimal comma, thousands separator,
  units, "y" / "o" lists, and dates like "13 de noviembre".
- Layout: Spanish is longer, so each main screen is screenshotted in
  English and Spanish with the mock server (1280 and 375 px) and overflows
  are fixed. Shots live in `~/Projects/caravan-day32-results/spanish/`
  (not in the repo).
- Tests: `tests/test_day32_spanish.py`, plus updates to the localization
  tests now that a second language exists.

Full suite after the review nits: 2,176 passed, 97 subtests, 82.05 s, with
`XDG_CONFIG_HOME="" PYTHONPATH=.:proxy:tests uv run --with pytest
--with spake2==0.9 --with cryptography==46.0.3 python -m pytest tests -q`.
(The review run was 2,175; the extra test is the `CARAVAN_LANGUAGES`
script-close check.) Screenshots (English before / Spanish after, 1280
and 375 px; chat, Models, placement, Settings with the language picker,
Topology): `~/Projects/caravan-day32-results/spanish/{before,after}/`
(not in the repo). An overflow check on those screens found none; longer
Spanish labels wrap in the chat header buttons, chips, and Mac mini
cards.

### Spanish: release (v0.9.9)

Built on the local branch `day32-spanish` (on `2e49275`), reviewed
by Claude (approved 2026-11-23 09:05 CST: full suite 2,175 of 2,175 with
the review command; two nits fixed afterward) and merged to `main`
fast-forward only.
Released as a mid-day release: source `8b449aa`, pin `9f23e16`; tag
[v0.9.9](https://github.com/linuxbren/caravan/releases/tag/v0.9.9) on the
wrap commit.
Notes: [release-notes/day32-v0.9.9.md](release-notes/day32-v0.9.9.md).

The Macs were not updated as part of the release; Brenden updates them
himself with `caravan update`. Day 32 stays open for other languages.

## Russian (v0.9.10)

Brenden (2026-11-23): start Russian, same process as Spanish.

**After ([v0.9.10](https://github.com/linuxbren/caravan/releases/tag/v0.9.10)):** Russian is
the next language after Spanish. Work was on the local branch
`day32-russian` (from `main` at v0.9.9, `bd46a24`). Claude approved the
uncommitted tree (11:05 CST). The Macs were not updated (Brenden updates
them himself).

What this adds:

- `locales/ru.json` for every current English key (natural Russian,
  informal *ты*). Model names, **Caravan**, **Mini**, **GGUF**, **MLX**,
  and commands stay in English. One / few / many / other plural keys
  everywhere counts appear. Glossary: [docs/i18n/GLOSSARY.md](i18n/GLOSSARY.md)
  (Russian column).
- A Settings language picker and installer shell block that include
  **Русский (beta)**. Default order is unchanged (`CARAVAN_LANG`, then
  the saved Settings choice, then the Mac's language, then English).
  Russian is marked **beta** until a native speaker reviews it. All
  picker strings go through `T()`.
- Locale formatting for Russian: a space as the thousands separator, a
  decimal comma (1 234,5), "и" / "или" lists, and dates like "13 ноября"
  (genitive month) and "ноябрь 2026".
- Layout: Russian (Cyrillic) runs long, so each main screen is
  screenshotted in English and Russian with the mock server (1280 and
  375 px) and overflows are fixed. Shots live in
  `~/Projects/caravan-day32-results/russian/` (not in the repo). An
  overflow check on those screens found none; longer Russian labels wrap
  in the chat header buttons, chips, and Mac mini cards, using the same
  rules as Spanish.
- Tests: `tests/test_day32_russian.py` (parity, placeholders, `_html`
  tags, plural forms in real strings). Full suite: 2,187 passed, 97
  subtests, 82.08 s, with
  `XDG_CONFIG_HOME="" PYTHONPATH=.:proxy:tests uv run --with pytest
  --with spake2==0.9 --with cryptography==46.0.3 python -m pytest tests -q`.

### Russian: release (v0.9.10)

Built on the local branch `day32-russian` (on `bd46a24`), reviewed
by Claude (approved 2026-11-23 11:05 CST: full suite 2,187 of 2,187 with
the review command) and merged to `main` fast-forward only.
Released as a mid-day release: source `6b87dae`, pin `d025be8`; tag
[v0.9.10](https://github.com/linuxbren/caravan/releases/tag/v0.9.10) on the
wrap commit.
Notes: [release-notes/day32-v0.9.10.md](release-notes/day32-v0.9.10.md).

The Macs were not updated as part of the release; Brenden updates them
himself with `caravan update`. Day 32 stays open for other languages.

## Japanese (v0.9.11)

Brenden (2026-11-23): start Japanese, same process as Spanish and Russian.

**After ([v0.9.11](https://github.com/linuxbren/caravan/releases/tag/v0.9.11)):** Japanese is
the next language after Russian. Work was on the local branch
`day32-japanese` (from `main` at v0.9.10, `b5eb31f`). Claude approved the
uncommitted tree (12:25 CST). The Macs were not updated (Brenden updates
them himself).

What this adds:

- `locales/ja.json` for every current English key except non-`other`
  plural forms (natural, polite-casual Japanese; です/ます in help text
  and sentences; short button labels). Model names, **Caravan**,
  **Mini**, **GGUF**, **MLX**, and commands stay in English. Plural keys
  use `_other` only. Glossary: [docs/i18n/GLOSSARY.md](i18n/GLOSSARY.md)
  (Japanese column).
- A Settings language picker and installer shell block that include
  **日本語 (beta)**. Default order is unchanged (`CARAVAN_LANG`, then
  the saved Settings choice, then the Mac's language, then English).
  Japanese is marked **beta** until a native speaker reviews it. All
  picker strings go through `T()`.
- Locale formatting for Japanese: dates like 2026年11月13日 and
  2026年11月, lists with 、 and と, and numbers like 1,234.5.
- Layout: CJK line breaking (`line-break: strict`, `word-break: normal`,
  `overflow-wrap: anywhere`) and fonts that cover Japanese
  (`Hiragino Sans`, `Noto Sans CJK JP`, and the usual Mac gothic faces).
  Each main screen is screenshotted in English and Japanese with the mock
  server (1280 and 375 px) and overflows are fixed. Shots live in
  `~/Projects/caravan-day32-results/japanese/` (not in the repo).
- Tests: `tests/test_day32_japanese.py` (parity except non-`other`
  plurals, placeholders, `_html` tags, `_other`-only plural forms in
  real strings). Full suite: 2,198 passed, 97 subtests, 83.29 s, with
  `XDG_CONFIG_HOME="" PYTHONPATH=.:proxy:tests uv run --with pytest
  --with spake2==0.9 --with cryptography==46.0.3 python -m pytest tests -q`.
  An overflow check on the English/Japanese screenshots found none.

### Japanese: release (v0.9.11)

Built on the local branch `day32-japanese` (on `b5eb31f`), reviewed
by Claude (approved 2026-11-23 12:25 CST: full suite 2,198 of 2,198 with
the review command) and merged to `main` fast-forward only.
Released as a mid-day release, tag
[v0.9.11](https://github.com/linuxbren/caravan/releases/tag/v0.9.11) on the
wrap commit (source and pin commits are recorded after publishing).
Notes: [release-notes/day32-v0.9.11.md](release-notes/day32-v0.9.11.md).

The Macs were not updated as part of the release; Brenden updates them
himself with `caravan update`. Day 32 stays open for other languages.

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

## Part B: header layout (v0.9.6)

Brenden asked for a tidier header that never wraps.

- The model/status pill (for example `● READY · QWEN3 32B 4BIT`) moved out
  of the header. It now sits above and outside the chat card's top-left
  corner, just outside its border, where the CHAT label was. The CHAT
  heading is still there for screen readers.
- **Update available** moved to the right of the theme picker, on the
  same row.
- Nothing wraps at any width (checked at 375, 768, 1024 and 1280 px). A
  long model name ends in "…", and hovering the pill shows the full name.
  On phones (480 px and narrower) the theme buttons and the update badge
  get a little smaller so they fit on one row.

Code: `proxy/web/index.html` (the `.top-right` group, `#statusPill` as its
own grid row, `setStatus` sets the pill's tooltip).

## Part B: chat message queue (v0.9.6)

Brenden asked to keep typing while the model answers.

- While a reply is written, the prompt box stays typeable and **Send**
  reads **Queue**.
- Each queued message shows as a chip in a small strip floating just
  above the prompt box: the start of the text, the full text on hover,
  and a **×** to cancel it. The strip disappears when the queue is empty,
  and the button reads **Send** again.
- Queued messages send in order when the current reply ends, also after
  an error, a cut-off reply or Stop.
- A queued message is not sent to the server, or written to the request
  journal, until its turn comes. Cancelling one with × means it never
  leaves the page.
- Unload, switching models and New session don't throw the queue away.
  It waits while the model changes, sends when the model is ready again,
  and items can still be cancelled with ×.

Code: `proxy/web/index.html` (`queue`, `enqueueMessage`, `cancelQueued`,
`drainQueue`, `renderQueue`; `sendChat` queues while a reply streams and
drains the queue when it ends).

## Part B: Ollama Cloud API key (v0.9.6)

Brenden approved the cloud keys request with three parts, then trimmed it
to Ollama Cloud only. All three parts shipped in v0.9.6.

1. **Settings → Cloud API keys.** One row: **Ollama Cloud**. Ollama Cloud
   is the only cloud source the Models picker can search, so it is the
   only key needed (Brenden trimmed OpenAI, Anthropic and OpenRouter).
   Adding a provider later is one entry in `PROVIDERS` in
   `proxy/cloud_keys.py`; Settings shows one row per entry. The row shows
   "Not set" or "Set · ends in abcd", has a password field with **Save**,
   and has **Remove** for a key saved from Settings. A key set by
   `OLLAMA_API_KEY` (or `CARAVAN_OLLAMA_API_KEY`) shows "From
   OLLAMA_API_KEY". It can't be edited from the page, because the
   environment variable wins. The section's note says: "The key is saved now;
   chatting with cloud models comes in a later update."
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

Differs from the proposal: Ollama Cloud only (no OpenAI, Anthropic or
OpenRouter), one file rather than one per provider, and no **Test**
button yet.

**The key is saved, but cloud chat comes later.** Chatting with Ollama
Cloud models is not part of Day 32 (Brenden). It would route `/api/chat`
to Ollama Cloud and add a first-chat notice that the message leaves your
Macs; it is listed on the [ROADMAP](ROADMAP.md) under Next candidates.
Until then, after the key is
saved the picker says so plainly: "Ollama Cloud key ready (ends in abcd).
Chatting with cloud models isn't built yet, so … can't load in chat yet."

Code: `proxy/cloud_keys.py` (new), `GET/POST /api/cloud-keys` in
`proxy/web_server.py`, the key flag in `proxy/web_picker.py`, and the
Settings section and picker prompt in `proxy/web/index.html`.

Tests: `tests/test_day32_cloud_keys.py` has 13 tests. They cover 0600
storage, last 4 only, replace and remove, refusing a bad key without
echoing it, the environment winning, a broken file, the API never
returning or logging a key, the local network getting no access, other
providers (OpenAI, Anthropic, OpenRouter) being refused as unknown, picker
rows, and the page contract.

## Part B: Stop a reply (v0.9.6)

Brenden asked for a Stop button for chat output. Before this, nothing
stopped a reply while it was being written. The only stop controls were
**Unload** (unload the model) and stopping a download. A reply left
behind (for example after a model switch) only ended in the browser; the
model kept writing until it noticed the page had gone. Shipped in v0.9.6.

What it does:

- While a reply is written, a **Stop** button sits under **Send/Queue**,
  next to the prompt box. It says "Stopping…" until the reply ends and
  hides when nothing is being written.
- Stop asks the web server to end that reply (`POST /api/chat/stop` with
  the reply's request id, sent as `X-Caravan-Request`, or its journal job
  id). The server shuts down its connection to the model, so:
  - the MLX lead sees its client gone and stops generating. The split
    helper only works when the lead asks it to, so it stops too, and both
    are free for the next message. The lead now watches its client socket,
    so this also works while it is still reading a long prompt, when
    nothing has been written yet (before, it noticed only at its next
    word);
  - llama-server (GGUF) cancels the task when its client goes away.
- The words written so far stay in the chat, marked **(stopped)**, and in
  the chat history the model sees next time.
- The request journal closes the job as **stopped** (a new final state,
  "stopped by you" in `caravan jobs`), so it is never run again after a
  restart or power loss.
- Queued messages still send next, in order.
- If the server can't answer within 5 seconds, the page ends the request
  itself (the old behavior). Unload and switching models also ask the
  server to stop the reply that is being written.

Code: `proxy/web_server.py` (`/api/chat/stop`, live replies by request
and job id, the stopped ending), `agent/mlx_worker.py` (the client-gone
watcher), `proxy/request_journal.py` (`stop`, "stopped" status),
`tools/caravan_jobs.py`, `proxy/web/index.html`.

This changes the worker code (`agent/mlx_worker.py`), so updating to
v0.9.6 reloads the model once.

Tests: `tests/test_day32_stop_reply.py` has 16 tests:
- the journal keeps the partial reply and never runs a stopped job again;
- the watcher fires when the client closes and stays quiet after a
  normal reply;
- the worker ends a cancelled reply without an error;
- a real web server with a slow fake model is stopped mid-reply, and
  again while the model is still reading the prompt (using the real
  watcher);
- bad and unknown ids are refused;
- a reply that finishes normally is still "done";
- the page contract;
- a headless-browser run: Stop shows while streaming and hides after,
  "(stopped)" is shown, the queued message sends next, and the server is
  asked with the request id.

Checked live on the Macs before release, without changing their install
(Nov 22, 18:10 CST). The branch's web server ran on the dev node and talked to the 1st
Mac's running lead through an SSH tunnel, with the split model already
loaded.
- A long reply was stopped after about 40 pieces. The stream ended right
  away and the job was saved as "stopped" with the partial words.
- The lead logged `generation stopped (KeyboardInterrupt('cancelled'));
  rewound` in the same second.
- The next message got its first word in 0.37 s.
- Not checked live: stopping while the lead is still reading the
  prompt. That needs the new worker running on the Macs; it is covered
  by the tests and can be checked once Brenden has updated the Macs.

## Part B: tests and release (v0.9.6)

Built on a local branch, reviewed (Claude) and approved by Brenden, then
merged to `main` (fast-forward only).

Tests:
- `tests/test_day32_header_queue.py` (13): the header layout at four
  widths in a headless browser, and the queue (fake page and browser).
- `tests/test_day32_cloud_keys.py` (13).
- `tests/test_day32_stop_reply.py` (16).
- Two older tests were updated on purpose: the Send guard in
  `tests/test_web_server.py` (Send now queues while a reply streams) and
  the Download button text in `tests/test_day23_clean_install.py`
  (cloud rows say Load).

Full suite: 2,120 tests, OK. `test_queue_flow` failed once in about six runs (Send still read "Queue" when its 20 s wait ran out under load); its wait is now 45 s.

Screenshots for the review (header at 375/768/1024/1280 px, the queue,
Settings → Cloud API keys, the inline key prompt, the Load button, Stop)
are not in the repo.

Release: source `44a67e8`, pin `6f874c5`; tag
[v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6) on the
wrap commit. Notes: [release-notes/day32-v0.9.6.md](release-notes/day32-v0.9.6.md).
A mid-day release; Day 32 stays open for localization.

Updating reloads the model once (the MLX worker changed for Stop). The
Macs were not updated as part of the release; Brenden updates them
himself with `caravan update`.

Still open in Day 32 after v0.9.6: localization (step 1 since released
in [v0.9.7](#localization-step-1-release-v097); languages not chosen yet).

## Superseded: first proposal for cloud API keys

Brenden: Settings needs a place to enter API keys for cloud models, if one
doesn't exist yet. **Superseded:** this was the first proposal, written
before any work, with four providers. Brenden trimmed it to Ollama Cloud
only (the one cloud source Models can search), and what shipped in v0.9.6
is described in [Part B: Ollama Cloud API key](#part-b-ollama-cloud-api-key-v096).
It is kept here as written, for the record.

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
