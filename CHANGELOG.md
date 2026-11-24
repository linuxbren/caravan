## Day 33 — First-token timing in Auto-tune (v0.9.14)

Released as [v0.9.14](https://github.com/linuxbren/caravan/releases/tag/v0.9.14).
Day 33 ROADMAP #2: Auto-tune weighs first-token time together with write
speed when it tries Guess-ahead or Prompt lookup.

See [DAY33](docs/DAY33.md).

- Changed: Auto-tune now compares a whole long-prompt reply (first word
  plus writing) when it scores Guess-ahead and Prompt lookup, on GGUF
  and on MLX. A helper that delays the first word is kept only when
  generation speed pays back the wait. If first-token time is missing,
  the older chat-only verdict is unchanged. The existing ~2k-token long
  Auto-tune prompt is used; Auto-tune does not run an extra long prompt.
- Tests: 2,273 tests pass.

## Day 33 — Guess-ahead helper for MLX on one Mac (v0.9.13)

Released as [v0.9.13](https://github.com/linuxbren/caravan/releases/tag/v0.9.13).
Day 33 starts with ROADMAP #1: an MLX model on one Mac can use the same
Guess-ahead helper as a split MLX model and as GGUF.

See [DAY33](docs/DAY33.md).

- Added: Guess-ahead helper support for MLX models running on one Mac.
  Auto / Off / On, helper matching (same family / tokenizer), a file and
  memory-fit check before load, "guesses kept" under replies and in
  `caravan bench --speedups`, Auto-tune scoring once a helper is loaded,
  and the "Download helper for faster replies?" offer when a known helper
  is not on this Mac yet. A missing, incompatible, or too-large helper
  fails closed (load continues without it; the log says why). A Balance
  split still does not use a helper.
- Changed: user-facing copy and all five locales no longer say that MLX
  only uses a helper when it is split across Macs.
- Fixed: Native MTP (experimental) does not load a conventional draft
  helper alongside the MTP head. Claude's review caught that Settings
  Guess-ahead = Native MTP emits `--native-mtp` without `--no-split-draft`;
  the worker now skips auto-pair, download, and load of a conventional
  helper when native MTP is on, including an explicit `--split-draft-model`.
- Source `baa8056`, pin `8a33cd6`. 2,247 tests pass.

## Day 32 — Simplified Chinese localization (v0.9.12)

Released as [v0.9.12](https://github.com/linuxbren/caravan/releases/tag/v0.9.12), a mid-day
release. This is the last planned Day 32 language (Spanish, Russian,
Japanese and Simplified Chinese are now in Settings; each is marked beta
until a native speaker reviews it).

See [DAY32](docs/DAY32.md#simplified-chinese-v0912).

- Added: Simplified Chinese as the last planned language after Japanese.
  `locales/zh-Hans.json` has every current English key except non-`other`
  plural forms (2,335 English keys; natural, idiomatic Simplified Chinese,
  你 rather than formal 您). Plural keys use `_other` only. Model names,
  Caravan, Mini, GGUF, MLX and commands stay in English. Download is 下载;
  Unload is 卸载. Glossary:
  [docs/i18n/GLOSSARY.md](docs/i18n/GLOSSARY.md).
- Added: **简体中文 (beta)** in the Settings language picker and the
  installer shell block. Default order is unchanged: `CARAVAN_LANG`,
  then the saved Settings choice, then the Mac's language, then English.
  `zh-Hans`, `zh-CN`, `zh-SG` and `zh` map to Simplified Chinese;
  `zh-Hant`, `zh-TW` and `zh-HK` do not. Simplified Chinese is marked
  beta until a native speaker reviews it.
- Added: Simplified Chinese number and date formatting (dates like
  2026年11月13日 and 2026年11月, lists with 、 and 和, numbers like
  1,234.5, ordinals like 第1 / 第2).
- Changed: CJK line breaking (`line-break: strict`, `word-break: normal`,
  `overflow-wrap: anywhere`) and fonts that cover Simplified Chinese
  (`PingFang SC`, `Hiragino Sans GB`, `Noto Sans CJK SC`,
  `Microsoft YaHei`). Longer Chinese labels wrap with the same rules as
  Spanish, Russian and Japanese.
- Source `969581b`, pin `2c070ad`. 2,213 tests pass.

## Day 32 — Japanese localization (v0.9.11)

Released as [v0.9.11](https://github.com/linuxbren/caravan/releases/tag/v0.9.11), a mid-day
release. Day 32 continues with other languages (Simplified Chinese can
drop in later).

See [DAY32](docs/DAY32.md#japanese-v0911).

- Added: Japanese as the next language after Russian. `locales/ja.json`
  has every current English key except non-`other` plural forms (2,334
  English keys; natural, polite-casual Japanese, です/ます where it
  suits the UI). Plural keys use `_other` only. Model names, Caravan,
  Mini, GGUF, MLX and commands stay in English. Glossary:
  [docs/i18n/GLOSSARY.md](docs/i18n/GLOSSARY.md).
- Added: **日本語 (beta)** in the Settings language picker and the
  installer shell block. Default order is unchanged: `CARAVAN_LANG`,
  then the saved Settings choice, then the Mac's language, then English.
  Japanese is marked beta until a native speaker reviews it.
- Added: Japanese number and date formatting (dates like 2026年11月13日
  and 2026年11月, lists with 、 and と, numbers like 1,234.5).
- Changed: CJK line breaking (`line-break: strict`, `word-break: normal`,
  `overflow-wrap: anywhere`) and fonts that cover Japanese
  (`Hiragino Sans`, `Noto Sans CJK JP`, and the usual Mac gothic faces).
  Longer Japanese labels wrap with the same rules as Spanish and Russian.
- Source `ff81dbe`, pin `2e778d8`. 2,198 tests pass.

## Day 32 — Russian localization (v0.9.10)

Released as [v0.9.10](https://github.com/linuxbren/caravan/releases/tag/v0.9.10), a mid-day
release. Day 32 continues with other languages (Japanese and Simplified
Chinese can drop in later).

See [DAY32](docs/DAY32.md#russian-v0910).

- Added: Russian as the next language after Spanish. `locales/ru.json`
  has every current English key (2,333; natural Russian, informal *ты*),
  plus one/few/many/other forms everywhere counts appear. Model names,
  Caravan, Mini, GGUF, MLX and commands stay in English. Glossary:
  [docs/i18n/GLOSSARY.md](docs/i18n/GLOSSARY.md).
- Added: **Русский (beta)** in the Settings language picker and the
  installer shell block. Default order is unchanged: `CARAVAN_LANG`,
  then the saved Settings choice, then the Mac's language, then English.
  Russian is marked beta until a native speaker reviews it.
- Added: Russian number and date formatting (decimal comma, a space as
  the thousands separator (1 234,5), "и" / "или" lists, dates like
  "13 ноября" and "ноябрь 2026").
- Changed: longer Russian (Cyrillic) labels wrap in the chat header
  buttons, chips and Mac mini cards, including at 375 px, using the same
  rules as Spanish.
- Changed: the split-status line `{label}: {count} layers ready` now
  goes through `T.plural`, so English says "1 layer ready".
- Source `6b87dae`, pin `d025be8`. 2,187 tests pass.

## Day 32 — Spanish localization (v0.9.9)

Released as [v0.9.9](https://github.com/linuxbren/caravan/releases/tag/v0.9.9), a mid-day
release. Day 32 continues with other languages (Japanese, Simplified
Chinese and Russian can drop in later).

See [DAY32](docs/DAY32.md#spanish-v099).

- Added: Spanish as the first language after English, built so later
  languages can drop in. A CLDR plural engine (`one`/`other` for Spanish
  and English; `one`/`few`/`many`/`other` for Russian; `other` only for
  Japanese and Chinese). `locales/es.json` has every current English key
  (2,331; neutral Latin American / universal Spanish, casual *tú*). Model
  names, Caravan, Mini, GGUF, MLX and commands stay in English. Glossary:
  [docs/i18n/GLOSSARY.md](docs/i18n/GLOSSARY.md).
- Added: a Settings language picker (English, Español (beta)) that
  switches the page live and persists. Default order: `CARAVAN_LANG`,
  then the saved Settings choice, then the Mac's language, then English.
  The `caravan` command and the installers follow the same setting.
  Spanish is marked beta until a native speaker reviews it.
- Added: Spanish number and date formatting (decimal comma, thousands
  separator, "y" / "o" lists, dates like "13 de noviembre"). English
  numbers stay ungrouped.
- Changed: longer Spanish labels wrap in the chat header buttons, chips
  and Mac mini cards, including at 375 px.
- Source `8b449aa`, pin `9f23e16`. 2,176 tests pass.

## Day 32 — GGUF placement (v0.9.8)

Released as [v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8), a mid-day
release. Day 32 continues with choosing and adding languages.

See [DAY32](docs/DAY32.md#gguf-placement-roadmap-9).

- Changed: GGUF downloads in Models use the same Step 2 placement chooser
  as MLX, for every fit color: 1 Mini / split across K Minis / copy to
  all, for any number of Macs from the config. Unfit options stay visible
  and disabled with the reason. The default is the smallest placement
  that fits (for GGUF, the smallest that holds the full chat window, as
  in Day 31). The choice is saved as `caravan-placement.json` and honored
  at download and at load: only the needed files go to the chosen Mini(s),
  and a one-Mini choice is not turned into a split.
- Source `0a9097a`, pin `84d1b2a`. 2,161 tests pass.

## Day 32 localization step 1 (v0.9.7) — all text in one English strings file

Released as [v0.9.7](https://github.com/linuxbren/caravan/releases/tag/v0.9.7), a mid-day
release. Day 32 continues with choosing and adding languages.

See [DAY32](docs/DAY32.md#localization-step-1-english-strings-file).

- Changed: every piece of user-facing text (the web page, the `caravan`
  command and its tools, the installers, and the web server and worker
  messages that reach the page or the command line) now comes from one
  file, `locales/en.json`: 2,299 strings keyed by name, English as the
  fallback. The English text is unchanged.
- Changed: the page and server no longer recognise messages by their
  English words; they use codes (status, problem flag, stage codes).
  Plurals ("1 Mac" / "2 Macs"), numbers with units, lists and ordinals go
  through locale helpers; `<html lang>` follows the language.
- No other language yet, and no language picker.
- Left as they are on purpose: logs, the request journal, lab and
  developer tools, benchmark and model prompts, config names, command
  lines, model names, and worker output from llama.cpp / MLX.
- Tests: a lint now also covers server and worker messages; the browser
  tests start a plain headless Chromium (a flaky Stop test is fixed,
  `176bfe6`).
- Source `fcfdc35`, pin `deb0e52`. 2,144 tests pass.

## Day 32 part B (v0.9.6) — Stop a reply, a message queue, a tidier header and the Ollama Cloud key

Released as [v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6), a mid-day
release. Day 32 continues with localization.

See [DAY32](docs/DAY32.md#part-b-header-layout-v096).

- New: **Stop** under Send while a reply is written. It really stops the
  model: the request to the model is closed, the Macs (including the
  split helper) stop writing, even while still reading a long prompt, and
  are free for the next message. The words so far stay, marked
  "(stopped)". The saved job is closed as "stopped" and never run again
  after a restart. `POST /api/chat/stop` for scripts.
- New: keep typing while the model answers. **Send** reads **Queue**;
  queued messages show as chips above the box (× to cancel) and send in
  order when the reply ends, also after an error or Stop. Nothing is sent
  or saved until its turn.
- Changed: the model and its status sit just above the chat card's
  top-left corner; **Update available** sits right of the theme switch;
  nothing in the header wraps (long model names end in "…", full name on
  hover).
- New: Settings → **Cloud API keys** for the Ollama Cloud key (masked,
  only the last 4 characters shown, editable, removable; saved in
  `~/.caravan/cloud-keys.json`, 0600). Picking a cloud model with no key
  asks for it right there. Cloud models say **Load**, not Download.
  Chatting with cloud models comes later.
- Updating reloads the model once (the MLX worker changed for Stop).
- Source `44a67e8`, pin `6f874c5`. 2,120 tests pass.

## Day 32 part A fix (v0.9.5) — the daily update check switch, and a sturdier daily check

Released as [v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5).

See [DAY32](docs/DAY32.md#part-a-fix-daily-update-check-v095).

- Fixed: with **Check for updates daily** off, Settings kept saying
  "up to date" (and the Update available badge and Mac lines stayed) from
  a check made while it was on. Now daily off shows just the version and
  no update status, until you use **Check now**. The switch works at once,
  without reloading the page; turning it back on shows a fresh answer or
  checks right away.
- Fixed: one unexpected error stopped the daily check until Caravan
  restarted. A cut-off reply from GitHub is now treated as offline. An
  offline result is saved, so the page no longer says "up to date" from an
  old answer, and it is retried hourly. A check saved with a wrong clock no
  longer blocks checks.
- Source `7251223`, pin `f5b6842`. 2,078 tests pass.

## Day 32 part A (v0.9.4) — the installed version in Settings

Released as [v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4).

See [DAY32](docs/DAY32.md#part-a-version-label).

- Settings shows the installed version next to its title, with the daily
  update check's status: "v0.9.4 · up to date", or "update available",
  which takes you to Update now.
- `caravan --version` (or `caravan version`), `caravan status` and
  `caravan doctor` show the same version.
- The number comes from a new `VERSION` file in each release and the build
  from the installed pin, so it always matches what is really installed.
  Source `61d6c09`, pin `33caff0`. 2,051 tests pass.

## Day 31 follow-up (v0.9.3) — 4-bit MLX models load when split across Macs

Released as [v0.9.3](https://github.com/linuxbren/caravan/releases/tag/v0.9.3).

See [DAY31](docs/DAY31.md#follow-up-4-bit-mlx-split-load-fix-v093).

- Fixed: Qwen3 32B (MLX, 4-bit) failed to load split across two Macs with
  `KeyError: 'model.layers.17.mlp.up_proj.weight'`. One piece of a layer
  the other Mac runs had its weight in a file only that Mac holds and its
  4-bit scales in a file both hold, and the loader needed both. That piece
  is now left alone (it is dropped after load anyway), and the load log
  names it. The fix was first made on the Macs during setup and is now
  part of Caravan.
- Older MLX loaders without that check load as before. Loads on one Mac
  and models that aren't pre-quantized are unchanged. Source `4b48b85`,
  pin `a0e8cfe`. 2,038 tests pass.

## Day 31 follow-up (v0.9.2) — the app says "context"

Released as [v0.9.2](https://github.com/linuxbren/caravan/releases/tag/v0.9.2).

See [DAY31](docs/DAY31.md#follow-up-the-app-says-context-v092).

- Every place the app meant the model's context and said "window" now says
  "context", so the page, the placement lines and the Settings help agree.
  The 1-Mac-or-split line reads, for example: "Fits on 1 Mac with a 64K
  context. Split across 2 Macs for the full 128K context."
- The Settings row **Chat window** is now **Context**. Its saved setting is
  still `chat_window`, so pinned values keep working.
- Wording only: placement, fit and launch math are unchanged. Source
  `12d82a4`, pin `640670d`. 2,033 tests pass.

## Day 31 (v0.9.1) — placement counts the chat window; Settings and Topology list what is on disk

Released as [v0.9.1](https://github.com/linuxbren/caravan/releases/tag/v0.9.1).

See [DAY31](docs/DAY31.md).

- Choosing between one Mac and a split now counts the memory for the
  model's chat window, not just its files. The window is the one the model
  was trained for (8K when it does not say). The recommended placement is
  the smallest one that holds the full window: "Fits on 1 Mac with the full
  128K window.", or "Fits on 1 Mac with a 64K window. Split across 2 Macs
  for the full 128K window." The one-Mac choice stays available.
- GGUF placement uses the same numbers as Chat window Auto, so the window
  after Load matches the plan. Before a GGUF download, Caravan reads the
  file's header from the download source to learn its window.
- MLX fit uses the model's real config (also inside `text_config`) instead
  of guessing 8% of the file size for an 8K window.
- A Mac whose memory cannot be read no longer counts as a fit for GGUF.
- Fixed: the chat-memory estimate counted only the first part of a
  multi-part GGUF download.
- Fixed: the Settings list of models to load showed models that were not
  downloaded (partial downloads, a split missing its other half, the loaded
  model after its files were gone, GGUF share records with a missing part).
  It now lists only models whose files are complete on the Mac or Macs
  that will run them. Deleting a model updates the list right away.
- Fixed: Topology's On disk list missed every GGUF model (it looked in old
  folders) and listed exo's `caches` folder as a model. It now uses the same
  scans as Settings, marks a model Settings can't load ("Not in Settings:
  files incomplete"), and can delete GGUF models.
- Fixed: Topology showed `~/cv3` as each Mac's code folder, and a Mac
  without a saved path got that old developer folder in remote commands.
  It now shows the real folder and falls back to `~/.caravan/src/caravan`.

## Day 30 (v0.9.0) — Power-loss resume, full GGUF chat window, one main branch

Released as [v0.9.0](https://github.com/linuxbren/caravan/releases/tag/v0.9.0).
See [DAY30](docs/DAY30.md).

### Finishing chats after a power loss or crash

- Second plug pull on both Macs during a busy Qwen3 30B split: Caravan
  restored the split and ran the chat the power loss cut off again by
  itself, from the start, and saved the whole reply for the client to
  fetch. The first pull was partial (the reply in flight was lost); see
  [DAY30](docs/DAY30.md#power-loss-resume-thunderbolt-wait-and-crash-series).
- New: Caravan saves each chat request on the 1st Mac before the model
  sees it and, after a power loss, crash or restart, runs unfinished ones
  again from the start (not mid-sentence) once the model is back. Get the
  answer with the `X-Caravan-Job` id from `GET /api/jobs/<id>` or
  `caravan jobs <id>`; the chat shows it with "Finished after a restart".
  Limits: 1 hour, 2 tries, 4 MB, kept 3 days. Turn off with
  `[jobs] resume = false`. See [WEB](docs/WEB.md#chats-after-a-power-loss-or-crash).
- After a power loss, a load waits up to 60 s for the Thunderbolt link to
  the other Mac (when it worked before) instead of settling for Wi-Fi
  because Thunderbolt comes up a little later. If a split still ends up on
  Wi-Fi and Thunderbolt starts working, a note says so and how to switch;
  Caravan does not reload by itself.
- While boot restore waits for another Mac, the page says "Waiting for your
  other Macs to start… trying again in 4s: The 2nd Mac is not reachable
  yet" instead of "Mini Mac is unavailable; bring it online and press Load".
- A restored GGUF model shows its Memory compression in Settings again.
- Crash series with medium prompts (2.5K–7.6K tokens): five chats cut by
  `kill -9` during prompt reading, early, mid or late in the reply all
  came back by themselves over Thunderbolt and finished ("Finished after a
  restart"). Averages: model ready 22.0 s after the crash, re-run 1.1 s
  later; each crash cost about 31 s over an uninterrupted run; same write
  speed.

### Caravan lives on main

- Install, `caravan update`, Update now and the daily update check read
  `main`. New install line:
  `(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)`.
- Installs from before Day 30 keep updating: each release also
  fast-forwards `caravan-v3-mlx-split` and `clean-install-fixes` to `main`.
  Source checkouts on an old branch keep pulling it.
- Docs, the pairing help link and the website point at `main`; "v3" is
  gone where it was only the branch or a legacy label. Compatibility names
  (`com.caravan.v3.*`, `~/cv3`) and history are unchanged.
  See [DAY30](docs/DAY30.md#caravan-lives-on-main).

### GGUF chat window at the model's full trained length

- Chat window Auto picks the longest window that fits in memory, up to
  the model's trained window, with no 32K cap. Llama 3.1 8B and gpt-oss
  20B now get 131072 on one Mac (they had 32768). Auto never picks less
  than before, and still uses 8192 when it cannot measure.
- Learned speed settings (16-bit chat memory, flash attention off, a
  bigger prompt batch, the Guess-ahead helper) never shorten the Auto
  window; a learned setting that would not fit falls back to the lighter
  one, and Auto-tune and Self-tuning skip those trials. Pinned settings
  still count.
- Chat window adds 131072, 262144 and Native; sizes past the trained
  window or that will not fit are greyed out with a plain reason.
- A window saved from an Auto load is sized again after a restart or
  Update now. The web chat keeps history up to the real GGUF window.
- Caravan waits up to 2 hours (was 30 minutes) for a model's first
  bytes, so a prompt near a 128K window is not cut off
  (`CARAVAN_REPLY_TIMEOUT_S`).
- Split loads that worked no longer show "Couldn't start the model on
  the other Mac"; load notes name the other Mac in plain words.
- `caravan bench` on the model that is already loaded waits for its
  restart instead of measuring a stopped server (HTTP 502) and then
  failing to put it back (HTTP 400).
- Measured cost: no change on short chats; Llama 3.1 8B writes about 7%
  slower on a ~29K prompt (its full window needs 8-bit chat memory);
  gpt-oss 20B unchanged. Near the full window one Mac is slow: Llama
  3.1 8B read a 115,593-token prompt in 44 minutes and wrote at 3.65
  tok/s. See [DAY30](docs/DAY30.md#gguf-chat-window-runs-at-the-models-full-trained-length).

### llama.cpp 1.0 and TensorFold

- llama.cpp v1.0.0 was benched against the pinned b12283 on four setups
  and was no faster (short writes within ±2%, first word on long prompts
  1–4% slower with the helper). Not rolled in; the pin stays b12283.
- TensorFold is shelved until it supports M4 Macs and Qwen3 MoE.

## Day 28 — Qwen3 30B 8k split write was the pre-fix Wi-Fi tunnel

- The first Day 28 shootout measured Qwen3 30B 8k split write at 17.5
  tok/s, slower than v0's 22.4. That run was before the Thunderbolt-first
  fix, when the GGUF split tunnel used the other Mac's `.local` name and
  went over Wi-Fi.
- After the fix, round 3 (`40b2bad`, Thunderbolt) measured 25.21 untuned
  / 25.18 tuned (raw 25.205 / 25.175 in
  `reliability3/split-qwen30b.json`), faster than v0's 22.4 (+12%). A
  matched v0-vs-current confirmation run is still pending.

## Day 28 — tuning round 3 results

- The Auto-tune reliability queue on source `40b2bad` / pin `9f95528`
  (1,869 tests) finished Nov 18, 5:46 PM CT (America/Chicago). The
  four 2-Mac cases, plus a 1-Mac Llama 8B recheck, all passed Auto-tune
  three times and kept their settings across a reload and a restart,
  with no prompt errors. The link between the Macs was Thunderbolt at
  about 0.3 ms.
- Short-prompt write tok/s, untuned vs tuned: 2 Macs Llama 8B 19.44 vs
  23.03 (helper + Prompt lookup kept 3 of 3); 2 Macs Qwen3 14B 11.15
  vs 14.90 (helper); 2 Macs gpt-oss 20B 33.41 vs 33.10 (no helper);
  2 Macs Qwen3 30B 34.62 vs 34.61 (no helper); 1 Mac Llama 8B recheck
  21.52 vs 25.27 (helper; other 1-Mac rows remain the round-2 figures).
  Full short/1k/4k/8k write, read and first-word tables are in the
  [experiment log](handoff/lab/experiments.md).
- The open item from round 2 is closed: Auto-tune now keeps a helper
  win on a 2-Mac split when the whole long-prompt reply is not slower
  than stock (hard stop at a 35% read drop). The tradeoff on 2-Mac
  Llama 8B at 8k is a later first word (39.6 s vs 30.7 s) and a slower
  read (241 vs 311 tok/s), in exchange for faster writing.
- The Qwen3 30B 2-Mac gap from round 2 (33.50 vs 34.50) was noise;
  round 3 is 34.61 vs 34.62.

## Day 28 tuning fix 3 — a measured helper win on two Macs is kept

- On two Macs, Llama 8B's Guess-ahead helper wrote 17% faster (19.3 to 22.7
  tok/s) but read a long prompt 16% slower. Self-tuning kept it (it only
  looks at chats), then Auto-tune threw it away on a hard 15% long-read cut,
  so the win disappeared. Past a 15% long-read drop the pick now has to make
  a whole long-prompt reply (read ~2k tokens, write 192) no slower than stock;
  past a 35% drop it is always rejected. Self-tuning and Auto-tune now agree
  on this case.
- Checked Qwen3 30B on two Macs (33.5 vs 34.5 tok/s): Auto-tune kept stock
  settings, so the gap was run-to-run noise, not a slower setting.
## Day 28 — tuning round 2 results

- The Auto-tune reliability queue on source `4bdbd79` / pin `9e612db`
  finished Nov 18, 4:14 AM CT (America/Chicago). All 7 cases passed
  Auto-tune three times and kept their settings across a reload and a
  restart, with no prompt errors.
- Short-prompt write tok/s, untuned vs tuned (final for this build,
  except 2-Mac Llama 8B tuned): 1 Mac Llama 8B 21.49 vs 25.97 (helper);
  1 Mac Qwen3 14B 12.09 vs 16.87 (helper); 1 Mac gpt-oss 20B 40.37 vs
  40.59 (no helper); 2 Macs Llama 8B 19.41 vs 19.38; 2 Macs Qwen3 14B
  11.22 vs 14.90 (helper); 2 Macs gpt-oss 20B 33.11 vs 33.01; 2 Macs
  Qwen3 30B 34.50 vs 33.50 (self-tune lost, within noise). Full
  short/1k/4k/8k write, read and first-word tables are in the
  [experiment log](handoff/lab/experiments.md).
- 2-Mac writing speed stayed around 19 tok/s on Llama 8B, not the 11
  seen when the split had drifted onto Wi-Fi. 2-Mac tuned now matches
  or beats untuned where a helper is kept. The round-1 2-Mac tuned
  column (Llama 8B 11.6 vs 19.0, and the slower Qwen figures) should
  not be used.
- Open: on 2 Macs, Llama 8B's helper won self-tune, but Auto-tune did
  not keep it. A fix is next, then a 2-Mac rerun (round 3) on the
  link-order build below. The Macs have not been updated to that build
  yet.
- Earlier fixes in this day (bugs A–E in the first tuning fix; the
  Thunderbolt tunnel, stock re-check, Qwen3 thinking replies, and the
  8k HTTP 502 in fix 2; then one link-order picker) are unchanged and
  described in the sections below.

## Day 28 link order — Thunderbolt, then wired, then Wi-Fi, everywhere

- One route picker (`proxy/peer_route.py`) now decides how this Mac reaches
  another one, in a fixed order: Thunderbolt, wired Ethernet, Wi-Fi, then
  anything else (Tailscale/VPN) last. Each link is checked (both Macs on
  it, a timed connection to the other Mac's SSH port over that interface,
  and an SSH login that shows the paired Mac's own host key and echoes a
  fresh code); the first that passes wins, even if a later one looks
  faster. It is re-checked on every model load or reconnect, so a cable
  plugged in later is picked up next load.
- Every path uses it: GGUF split tunnels (whole-file and per-Mac pieces),
  MLX split peer and listen addresses, the remote MLX worker tunnel,
  control SSH (start/stop, stats for Topology, health), update every Mac,
  Thunderbolt address discovery, the dev split CLI, the SSH hop proxy
  (now falls back to the next link instead of failing; `--tb-only` keeps
  the old behaviour) and pairing (records the link right after pairing).
- Model traffic never follows the other Mac's `.local` name any more: it
  connects to the picked address, binds this Mac's address on that
  interface, and keeps the paired SSH alias as the host-key check.
- Topology shows "Link: Thunderbolt · en2 · 0.6 ms" (or wired / Wi-Fi,
  marked slower) for each other Mac; `caravan status` prints the same.
  Falling back logs "Using Wi-Fi to reach 2nd Mac; Thunderbolt not found,
  splits will be slower".
- Why: Day 28 round 2 found the 2-Mac GGUF split tunnel going over Wi-Fi
  (15 ms, jittery) instead of Thunderbolt (0.6 ms), and writing speed
  drifted from about 19 to 11 tok/s. Fix 2 made that one tunnel prefer
  Thunderbolt; there was still no wired-vs-Wi-Fi rule and each path picked
  addresses its own way.

## Day 28 fix 2 — tuning never ends slower than stock; 2-Mac splits use Thunderbolt

- A GGUF model split across two Macs now sends its model traffic over the
  Thunderbolt link when the Macs are paired over it. It used to follow the
  other Mac's network name, which could resolve to the home network
  (Wi-Fi here: 15 ms and jittery, against 0.6 ms on Thunderbolt), so
  writing speed on 2 Macs swung from about 19 to 11 tok/s between loads,
  and Auto-tune measured on whichever it got. If the Thunderbolt route
  does not open, the split still starts over the network.
- Auto-tune now starts from stock settings and ends by measuring stock and
  its pick again in the same session, in turn (stock, pick, stock, pick).
  The pick is kept only when chat writing speed is within 3% of stock or
  better; otherwise everything goes back to stock and the losing options
  are noted.
- Qwen3 (a thinking model) no longer looks like a "garbled" reply when its
  thinking uses the whole test budget, and when both sides of a trial look
  the same the faster one wins. Before, Qwen3 14B never kept its helper
  even though it wrote about 40% faster with it.
- One chat now really is one llama-server slot (--parallel 1, as stock
  llama.cpp runs use). Without it llama-server opened 4 slots sharing one
  memory pool; on 2 Macs a long (8k) prompt after other long prompts could
  crash the other Mac's rpc-server (GPU address fault) and the reply came
  back as HTTP 502.

## Day 28 fix — tuning keeps the speed-ups that win, and never stalls

- Guess-ahead and Prompt lookup are now judged on what you feel: how
  fast the reply is written and how long the whole reply takes, on
  chats and on code edits. Long-prompt reading is only a guard (a drop
  of more than 15% loses). Before, a helper that wrote 9% faster lost
  because reading a long prompt was a bit slower. Auto-tune now also
  runs two code-edit prompts and two long prompts for these two options,
  so Prompt lookup can win on code edits without making chats slower.
- A kept Guess-ahead or Prompt lookup now stays on after a reload, a
  Caravan restart and Update now. Before, the next load quietly turned
  them off. If the helper file is gone, the model loads with Guess-ahead
  off instead of failing.
- The helper keeps its chat memory in the smaller q8_0 format, runs on
  the GPU, and its memory is counted when Caravan picks the chat window.
  On two Macs (GGUF) the helper stays on the lead Mac's GPU.
- A load now asks the model for one tiny test reply before it says
  Ready. If the reply fails with Guess-ahead or Prompt lookup on, the
  model starts again without them and Auto stops trying the helper
  until a fresh Auto-tune. Before, a 14B model with a 32k window and
  its helper said Ready and then failed every reply.
- Auto-tune counts an option that fails to load or reply as a loss and
  goes on to the next option, then leaves the winner running. A fresh
  Auto-tune retries options that lost before.
- Self-tuning keeps Guess-ahead and Prompt lookup through its reloads
  (they used to be dropped), tries the helper first when one is on this
  Mac and Auto-tune has not decided it, and a failed trial reload really
  puts the previous settings back.
- An MLX model split with Balance does not use a helper, so Caravan no
  longer offers to download one there and says why.
- caravan bench --speedups --only gguf (or mlx) needs only that model.

## Day 28 fix — GGUF split works on a freshly paired Mac

- A GGUF model split across a newly paired Mac failed with "Couldn't
  reach <Mac> for the split". Pairing gave the lead's key on the other
  Mac permission to reach Caravan's model port only, so the split's
  tunnel to that Mac's rpc-server (port 50052) was refused. The
  pairing key now also allows that one port. Nothing else changes: the
  key still only works from private networks, with no shell features,
  and can listen only on the model port.
- Macs paired before this fix are upgraded in place the next time
  Caravan starts on them (after Update). Only Caravan's own pairing
  lines with the old settings are changed; your other SSH keys are
  left alone. No need to pair again. MLX splits were not affected.

## Day 27 follow-up — one-Mac Topology, and a stopped Mac looks offline

- With only one live Mac in the group, Topology hides the Balance and
  Thunderbolt sections. They come back on their own when a second Mac
  is live again.
- Turning Caravan off on a Mac no longer leaves it looking live on the
  others. Those cards were still getting fresh CPU and temperature
  over SSH, even with the browser service stopped. A Mac whose
  Caravan is off, or whose stats have not updated for 15 seconds, now
  shows as offline (grey light). Offline Macs do not count toward the
  two-Mac Balance and Thunderbolt sections.
- A full "leave the group" action is not in this change: uninstalling
  on one Mac does not remove it from the others. Use Remove this Mac
  on its card after Unload, or leave it showing as offline.

## Day 27 fixes, round 3 — buttons say what they are doing

- Cancel Auto-tune now shows "Cancelling…" on the button and the Tuning
  badge right away, while the current step finishes. When it ends, the
  Auto-tune section says "Auto-tune cancelled — your settings are
  unchanged" (or that it kept the faster settings found before you
  cancelled), the badge says Cancelled for a few seconds, the campfire
  mark fades out, and the buttons come back. Nothing above the chat moves.
- Load model or Apply & restart while Auto-tune runs now asks once, with
  "Cancel Auto-tune and apply" doing both, instead of an error telling
  you to cancel first.
- More buttons show a busy word and a result: Reset tuning (Resetting…,
  then "Tuning reset"), Pause/Resume, Unload, Hugging Face token Save and
  Remove, Remote and LAN access, download Stop and Load, Delete in the
  disk list, the helper download Stop, the helper line buttons, and Stop
  this fetch.

## Day 27 fixes, round 2

- Guess-ahead and Prompt lookup help no longer quotes results from one
  particular model. It says what they are usually good at (code edits,
  repeated text), that the first word on long prompts can come a little
  later, and that gains vary by model and Mac.
- The Auto-tune animation no longer makes the chat move. The animated
  mark and the Tuning badge now keep a fixed size, and the chat header
  keeps room for the badge even when it is hidden.
- After Update now (or any web restart), a GGUF model that kept running
  is fully picked up again: Auto-tune Start works instead of saying it
  needs a GGUF model, and Reset clears that model's saved GGUF results.
- Self-tuning only counts chats that really ran with the setting it is
  trying. A trial whose reload never happened (for example the model was
  switched or the page restarted) is asked for again instead of measuring
  the old settings twice and finding nothing.
- When Auto-tune finds nothing faster, it says so plainly and keeps your
  settings, with one more line: how many changes were tried, that none
  was at least 3% faster, the current writing speed, and the closest try.
  Before, a little measuring noise could show Before/After lines that
  looked like tuning did nothing or made things slower.

## Day 27 fixes

- Update now no longer reloads the page the moment you click it. The page
  remembers which update run was already finished, so only the new run
  can reload the page or show Done, and Auto-tune or a reply no longer
  repaints the Updates card while an update is starting.
- GGUF models: Settings and the helper offer now find the GGUF file for
  the loaded model. Guess-ahead On can be picked when a helper is on this
  Mac (Settings names it), and the helper offer line works for GGUF.
- The Helper download button now says what is true for the loaded model:
  a GGUF model with its helper already on this Mac names the helper and
  says to set Guess-ahead to On (or Auto and run Auto-tune); a GGUF model
  without one offers the download; the split-MLX message shows only for
  MLX.
- Restarts (updates, LAN on or off) no longer leave a `dns-sd` process
  behind. The web server stops its own announcement when it is stopped,
  and on start it stops its own leftovers from earlier restarts.

## Day 27 — Measured Guess-ahead, and GGUF closer to MLX

- When a reply used Prompt lookup or Guess-ahead, the line under it now
  ends with how many guessed words were kept, for example
  "guesses kept 88%". GGUF reads this from llama.cpp; an MLX reply shows
  the share of words that came from guesses. Replies with no guesses
  show nothing new. See [Day 27](docs/DAY27.md).
- `caravan bench "<model>" --speedups --yes` measures Off, Prompt lookup,
  Guess-ahead (when a helper is on this Mac) and Auto on the five short
  prompts, five new code-edit prompts and the long-prompt series, with
  medians, the change against Off, first token, and guesses kept. The
  model that was loaded before is put back with its settings.
- GGUF Auto-tune now also tries Guess-ahead when a smaller same-family
  helper is already on this Mac (one chat, not pinned), and keeps it only
  when it measures at least 3% better. Nothing is downloaded for you.
- When the loaded model has a known small helper that is not on this
  Mac, Settings shows one line under the model: "Download helper for
  faster replies?" with Download and Not now. A GGUF model gets a GGUF
  helper; a split MLX model gets its MLX helper. Download shows its
  progress in that line and then puts Guess-ahead on Auto (Auto-tune
  still keeps the helper only if replies get faster). Not now is
  remembered for that model. Nothing downloads without your click, and
  the line is hidden when the page is opened from another computer on
  your network. `caravan bench` asks the same question (y/N) in a
  terminal.
- A GGUF helper must now be the same model generation as the main model
  (for example Qwen2.5 with Qwen2.5), not only the same family.
- GGUF Prompt lookup uses a better guesser: in our tests about 95%
  faster writing on code edits (the old one was about 42%), the same on
  short chats, and about 2% slower on a long prompt. Takes effect on the
  next model load.
- The GGUF Guess-ahead and Prompt lookup help now gives the measured
  numbers.
- The GGUF Prompt lookup chip says "on" or "off" (it no longer shows the
  MLX-only "adaptive" wording).
- Day 27 does not change `agent/`, `runtime/`, or the requirements, so
  `caravan update` keeps a loaded model.

## Day 26 — Download progress under the model you clicked

- In the Models list, the download progress card appears right under
  the model you clicked Download on. It stays visible there even if
  you close the file list, and moves to the top of the list only
  when that model is not currently shown. See [Day 26](docs/DAY26.md).

- The `caravan bench` First token bars now follow the printed seconds:
  a shorter bar is sooner, matching the label "First token (s, lower
  is better)". Reading and Writing bars are unchanged. `--ascii` uses
  the same scaling; `--details` is unchanged. The Day 25 sample chart
  was redrawn with the same numbers. See [Day 26](docs/DAY26.md).

- GGUF Prompt lookup and Guess-ahead are Auto, Off, or On under
  Advanced. Auto stays off until a test finds a winner. Auto-tune may
  try Prompt lookup last when only one chat is in use, and treats a
  garbled trial as a loss. Guess-ahead On needs a smaller same-family
  model already on this Mac; Caravan will not download one. See [Day 26](docs/DAY26.md).

- Voice design notes (listening first) are in [VOICE](docs/VOICE.md).
  No listening code is shipped. See [Day 26](docs/DAY26.md).

- Caravan checks once a day for a newer version. An **Update available**
  badge appears on the chat page, and Settings has an Updates section
  with **Check for updates daily**, **Check now**, and **Update now**.
  `caravan update --check` only checks. Update now is only available
  on this Mac itself; from the local network or Tailscale, the page
  asks you to update here. The 2nd Mac needs the same update after
  this Mac is done. See [Day 26](docs/DAY26.md).
- This follow-up does not change `agent/`, `runtime/`, or the
  requirements files, so a `caravan update` from the Day 25 pin
  keeps a loaded model running. The web page still restarts. Tagged
  `day26-2026-11-13`.

- **Update now** and `caravan update` on this Mac also update the
  other Macs Caravan already knows about (the 2nd Mac, 3rd Mac, and
  so on), over the existing connection. Those Macs are updated first,
  then this Mac, and the model comes back afterwards. If a Mac is off
  or the update doesn't finish, this Mac still updates, and Settings
  shows step-by-step help under that Mac, with **Try again**, or you
  can run `caravan update` on that Mac. The daily check also shows
  when another Mac is on an older version. **Update now** works over
  Tailscale when the page is reached through this Mac's Tailscale
  share, not just a name that looks like Tailscale. On the local
  network the button stays off; use Terminal there. This follow-up
  does not change `agent/`, `runtime/`, or the requirements files,
  so a `caravan update` from the previous Day 26 pin keeps a loaded
  model running. The web page still restarts. Tagged `day26-2026-11-13`.
  See [Day 26](docs/DAY26.md).

- Settings > Updates has **Check now** next to the title and one
  status line per Mac, such as "1st Mac: up to date" or "2nd Mac:
  update available". "A November 13 update is ready." appears only
  when a newer version is ready. No change to `agent/`, `runtime/`,
  or the requirements files, so the model stays loaded.
- `caravan bench --from-averages` prints a plain "No saved numbers"
  line instead of empty bars, and prefers the last bench run for the
  pair ("Last bench") over saved chat averages ("Saved").
- Fixed: updating the other Macs never ran the update there. The
  command sent to the 2nd Mac was a shell syntax error ("parse error
  near `if'"), so it showed failed and Try again failed too. Each
  Mac's last error is kept and shown under a small Details toggle.
- Settings > Updates is shorter: Check now, the daily switch, What's
  new when an update is ready, and one line per Mac (current, update
  available, or failed). Update now shows only when an update is ready,
  Try again only when a Mac failed. On the local network there is no
  Updates section or Update available badge at all.
- While an update runs, Settings > Updates shows a busy **Updating…**
  button with the campfire flicker, each Mac's "updating…" line, and a
  step line with elapsed time ("Updating the 2nd Mac… 0:42", then
  "1st Mac… restarting"). It reconnects after the restart and flashes
  "Done." Still not shown on the local network.
- Each Mac's line shows where that Mac is now, not how the last update
  went. When Check now finds a newer version, every Mac not on it reads
  "update available"; "failed" is only for a Mac whose last try at that
  version failed. "Done." is a short flash after a run, then "current".
  The "This Mac is updated" and "Some Macs failed" sentences are gone.
- A Mac that needs the newest version now reads "update needed". After
  this Mac updates itself, the page checks again once, so the lines no
  longer say "current" next to What's new and Update now. The Updates
  section no longer says "Your model stays loaded."
- After an update, open Caravan pages reload themselves, so the new
  page is the one running. The page that started the update reloads
  as soon as Caravan is back; other tabs (on this Mac or another one)
  reload once nobody is typing or waiting on a reply. Update now shows
  **Updating…** the moment it is clicked.
- A newly published version can take about 5 minutes to show up in
  Check now, because GitHub keeps a short copy of the published version
  file. Documented in the install, browser, and remote-access guides.

## Day 25 — GGUF Self-tuning, Chat window, Two chats, and caravan bench

- GGUF Self-tuning learns from real chats, proposes one quiet trial,
  and fills the same Before and After lines Auto-tune uses. A change
  reloads when you are not mid-reply.
- Chat window is a Settings row with a sane Auto default from the
  model and this Mac's memory. Two chats is available for GGUF; Auto
  keeps one chat. Guess-ahead and Prompt lookup stay off.
- `caravan models` lists downloaded models with a friendly name, GGUF
  or MLX, and the id to copy, and marks the currently loaded one.
- `caravan bench` compares a GGUF model to its MLX counterpart,
  without inventing numbers. The default output is a compact chart
  of reading, writing, and first-token speed (GGUF and MLX bars at
  each size, with the measured value and a marker on the winner).
  `--details` (also `--text`) adds the reply-stats lines; `--ascii`
  and `NO_COLOR` use plain '#' bars. A plain name finds the matching
  pair among downloaded models. `--gguf` and `--mlx` still work.
  Default: five short prompts and a long-prompt series (~1k, ~4k,
  ~8k); `--short` or `--long` for just one. `--from-averages` draws
  the same kind of chart from already-saved chat averages. After a
  live run, the original model is put back, even if a measurement
  failed. First measured result (1st Mac, Qwen2.5 Coder 7B, two short
  prompts of that build): GGUF Q4_K_M Write 22.3 tok/s, MLX 4bit
  Write 23.5 tok/s. A later full-series run on the same Mac is in
  [Day 25](docs/DAY25.md) and [BENCHMARKS](docs/BENCHMARKS.md).
- Auto-tune (MLX and GGUF) uses those same five short prompts plus
  one ~2k-token long prompt (skipped if it will not fit), scores on
  medians including long-prompt read speed, and still treats a
  garbled trial as a loss. The memory-check probe is still required.
- While Auto-tune is running, the Start or Tune again button becomes a disabled **Tuning…** state with a small campfire flicker, and a live step line says what is happening (for example "Measuring the current setup · short prompt 3 of 5"). Previous Before and After lines are hidden until the run finishes (and come back if it fails or is cancelled). A **Tuning…** badge is visible from the chat page; Self-tuning shows a subtler "Self-tuning a setting…" note. A brief **Done** or **Nothing faster found** highlight appears when the run finishes. See [Day 25](docs/DAY25.md).
- `caravan bench --yes` shows a small campfire animation on a
  terminal with the current step and elapsed time. Piped output,
  `NO_COLOR`, and `--quiet` use a plain step line or stay silent.
  Ctrl-C stops the animation and still puts the original model back.
- See [Day 25](docs/DAY25.md). This follow-up does not change
  `agent/`, `runtime/`, or the requirements files, so a `caravan
  update` from the Day 24 pin keeps a loaded model running. The web
  page still restarts. No `day25` tag yet.

### Day 21 release — day21-2026-11-10 (published 2026-11-10 CST)

## Day 24 — quieter page and Advanced sections (published; pending live review)

- Settings: Self-tuning stays visible; other optimizations, Optimize now,
  and Apply & restart sit under a closed Advanced section. Self-tuning
  On/Off takes effect immediately on a loaded MLX model, with no reload.
  After a self-tuning or Optimize now
  run, the Self-tuning section shows that model's before and after speed
  as two lines ("Before · Write 88.4 tok/s · first token 0.29s" and
  "After · Write 94.5 tok/s · first token 0.15s"), using the same wording
  as the reply stats, empty until a run has finished, stored with the
  speed averages. The same two lines also appear next to the control that
  produced them. The slots are reserved so Settings rows do not jump.
  The Helper download button on Guess-ahead stays in a reserved slot and
  is not rewritten when status or helper polls repeat the same result.
- Models: Reasoning is renamed Thinking. Default filter chips are Chat,
  Coding, Thinking, Tools, and Vision. Embedding, any-to-any, text-to-image,
  text-to-video, text-to-speech, and Decision stay available behind Advanced
  so Caravan can sit between an agent app and a model. The list summary
  follows the selected fits-on chip ("fit on 1 Mac") and says Macs, not
  nodes. A Family menu lists known families present in the results. Row
  hover shows maker, release date, context, and capabilities. Each
  download in progress has its own stacked card, and MLX and GGUF use the
  same friendly Mac name.
- Topology: Balance and Thunderbolt stay collapsed until clicked. Balance
  idle status is plain text, split into "already applied" and "not safe to
  apply".
- Chat: Clear chat is renamed New session. Option chips sit in a Current
  optimizations box, in Settings order with Self-tuning first, with hover
  hints. The Specifications box is replaced by a quiet per-model,
  per-optimization average under the input, stored on the 1st node. During
  live review the line was changed to use the same wording as the stats
  under each reply, with a leading Average label ("Average · Read 165 tok
  at 200 tok/s · Write 10 tok at 20.7 tok/s · first token 0.34s · total
  0.78s"); fields with no data yet are left out. The "Built in the open"
  title and tagline are removed; the line reads "Your Macs. One model."
- Published. No `day24` tag yet; that waits for live review. See
  [Day 24](docs/DAY24.md) and [release notes](docs/release-notes/day24.md).
  A `caravan update` from the Day 23 pin picks this up and reloads a
  loaded model (model-running code in `agent/` changed). A follow-up
  from the first Day 24 pin (chat average wording) does not reload the
  model. A later live-review follow-up (whole-repo fetch for any
  model without a top-level `config.json`, including image, video,
  text-to-speech, and speech-to-text/ASR; "Download only, Caravan
  can't run image models yet" and the same shape for video and
  speech, for every Advanced type Caravan cannot serve; plain
  download errors and friendly Mac names on every download card)
  changes `agent/mlx_split_fetch.py`, so an update from that pin
  reloads a loaded model; the same model is restored.
  A later live-review follow-up (two-line before/after in tok/s, shown
  under Self-tuning and by the button that produced the result) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running.
  A later live-review follow-up (reuse or replace Caravan's leftover
  SSH forward after a web restart that kept the model; never kill a
  process that is not ours; load status uses friendly Mac names and
  no paths; a remaining tunnel error is "Couldn't start the model on
  the 2nd Mac. Try loading again.", with detail in the log only) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (GGUF Settings rows and trusted web
  Load flags — flash attention, automatic 16- or 8-bit memory
  compression never 4-bit, prompt batch, and saved slots; Optimize now
  and self-tuning compare 16-bit vs 8-bit and score read speed,
  first-token time, and write speed; Before/After lines work for GGUF)
  does not change `agent/`, `runtime/`, or the requirements files, so
  an update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (Self-tuning and Optimize now errors
  show a short plain reason next to Self-tuning, for example that a
  trial of Memory compression was rejected; full detail in the log
  only; no hostnames or paths) does not change `agent/`, `runtime/`,
  or the requirements files, so an update from that pin keeps a
  loaded model running. The web page still restarts.
  A later live-review follow-up (Tune again sits next to Self-tuning,
  outside Advanced, and always runs a fresh trial on the loaded model;
  Reset tuning clears saved results without unloading; one plain line
  when nothing is faster instead of two identical Before and After
  lines; the Self-tuning hint is for each model, not only MLX) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (Auto-tune section: Tune again and
  Reset tuning sit under an Auto-tune heading outside Advanced, in an
  indented block with the Before and After lines; Auto-tune works
  whether Self-tuning is On or Off; the page says Auto-tune where it
  used to say Optimize now; API routes unchanged) does not change
  `agent/`, `runtime/`, or the requirements files, so an update from
  that pin keeps a loaded model running. The web page still restarts.
  A later live-review follow-up (Campfire replaces Nebula, drawn in
  SVG and CSS with no photos; saved Nebula opens as Campfire; Auto-tune
  says Start until this model has been tuned, then Tune again) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (opt-in local-network access: Settings
  switch **Open on my local network** next to Tailscale, with a warning
  that anyone on the same network can use Caravan and there is no
  login; `caravan lan on|off|status` prints `http://<lan-ip>:<port>`;
  install question default No; off by default; uninstall turns it off;
  toggling keeps a loaded model) does not change `agent/`,
  `runtime/`, or the requirements files, so an update from that pin
  keeps a loaded model running. The web page still restarts.
  A later live-review follow-up (garbled replies get a plain note and
  Memory compression is put back to 16; Auto-tune and Self-tuning
  count a garbled trial as a loss; Reset tuning puts Memory
  compression back to Auto and clears a leftover pin; an update
  records the version just applied; local-network access and the
  Tailscale share can both be on, each with a clickable link) changes
  the model process as well as the page, so an update from that pin
  reloads a loaded model. After the update, refresh the page.
  A later live-review follow-up (Memory compression 4 is disabled on
  models whose chat memory is too compact for 4 to work well, with a
  short reason in Settings; a leftover saved 4 is turned back to Auto;
  Auto-tune and Self-tuning never try 4 on those models; a short
  known-answer check after a load at 4 or 8 puts Memory compression
  back to 16 when the answer is wrong, with a plain note in chat and
  Settings; Auto-tune trials must pass the check to be kept) changes
  the model process as well as the page, so an update from that pin
  reloads a loaded model. After the update, refresh the page.

## MIT License (2026-11-12)

- Caravan is open source under the [MIT License](LICENSE). Copyright (c)
  2026 Brenden Dawson. One adapted file keeps its own MIT notice:
  [agent/native_mtp.LICENSE](agent/native_mtp.LICENSE).

## Day 23 — clean-install fixes (published; live testing passed)

- Live testing on both Minis passed on 2026-11-11 CST: single-step update,
  remote access from another device, one-Mac and split MLX and GGUF
  downloads with load and chat, Add a Mac from placement, reboot, and
  uninstall then reinstall.
- `caravan start` says "Caravan started" or "Caravan is running",
  whichever is true, instead of "Service started (or already running)".
- `caravan update` is now a single step: it stops what is needed, installs the
  verified package, and brings the page back. A loaded model stays running when
  the model-running code did not change; otherwise it is reloaded and Caravan
  says so. A failed update restores and starts the previous version. If Caravan
  is already current, it says so and changes nothing.
- Opt-in Tailscale access from other devices: `caravan remote on|off|status`,
  one optional install question, and an **Open from my other devices** Settings
  switch. The page stays on 127.0.0.1; only the user's Tailscale network can
  reach it. Uninstall turns the share off. Off by default.
- Live-install follow-up: visible-page automatic model-list refresh with selection preservation;
  hide metadata-only starter models; Add a Mac from placement with return to fresh options;
  one-third-width desktop drawers and full-width mobile drawers.
- Clarify the already-enabled self-tuning default as On, record it in fresh config,
  and preserve existing Off/pinned settings. Worker learning is enabled before saved winners.

- Supply a checksum-pinned official llama.cpp b12283 engine on every Mac install/update.
- Download complete multi-part GGUF sets, select whole-file/split behavior automatically,
  and show downloaded models and useful load errors in the normal picker.
- Simple status, detailed doctor, safe backed-up startup-file replacement, quiet discovery,
  and idempotent Terminal PATH setup.
- Add-a-Mac flow inside Topology, first-run invitation and themed two-column setup.
- Complete confirmed uninstall: all owned local jobs/workers/data and marked PATH/SSH entries.
- Beginner guide wording and portable regression tests. See [Day 23](docs/DAY23.md).
  Remaining untested gates (fresh account, Gatekeeper, FileVault, a finished
  new-Mac pairing, old-startup-file replacement, and some engine paths) are
  listed there.

## Day 21 follow-up — Mac installation and documentation

- Friendly Mac-owner README and current Day 20/21 setup, Balance, restore,
  auxiliary title-worker and read-only Thunderbolt guidance.
- Mac-only no-Git/no-Homebrew bootstrap, checksum-verified source and uv,
  private Python, read-only doctor, and safe per-user control command.
- Prepared repeatable checksummed source-package build and daily checklist.
- Experimental: no signed app/pkg, automatic pairing, fully locked dependencies
  or fresh-account/FileVault-on certification. Day 21 tag remains unchanged.

- Clearer Topology Balance (Auto default, per-Mini bars, Adjust sliders, live preview, explicit Apply / Back to auto) with black/gray Apply and locked reload state.
- Trusted Thunderbolt inventory, bounded interface-pinned TCP22/SSH identity checks, and an opt-in N-Mini plan preview with no apply endpoint. Live two-Mini proof: EXO1→EXO2 verified; reverse TCP reachable but SSH identity unverified.
- Physical aux title-worker reboot check passed on EXO1: Huihui 24/40 KV16 ready 37.3s after boot, aux health 200 at ~47.1s, title sidecar 0.135s, full 19-tool Hermes replay 11.504s. EXO2 itself did not reboot; its packer was relaunched during restore. Day 20 already proved two-Mini main-model restore.
- Full suite at tag: **907 tests passed in 45.871 s**, no failures/skips. Details and remaining limits: docs/DAY21.md, docs/BENCHMARKS.md. Install: INSTALL.md, docs/SERVICES.md.
- A later two-Mini cold reboot at 17:29 CST failed automatic restore on a Thunderbolt en2 IPv4 race. **Fixed after release in `51d697a`**: typed retryable unreadiness, bounded backoff, “Waiting for Thunderbolt link…”. Suite **912 passed in 46.264 s**. After a keep-workers web-only restart at 17:38:47 CST, Huihui 24/40 KV16 restored at 17:39:00; aux health 200; title sidecar 0.165s; 19-tool Hermes 11.132s wall / 0.316s TTFT / 6.26 tok/s.
- Physical two-Mini confirmation at 17:44–17:46 CST with `51d697a` deployed: both Minis took a new boot; Huihui 24/40 KV16 auto-restored in 39.110s (EXO1 boot-to-ready); aux health 200 at ~45.8s; title sidecar 0.154s; 19-tool Hermes 11.368s wall / 0.399s TTFT / 6.26 tok/s. The waiting-status retry was not observed on this pass (IPv4 was present before packer start). Tag `day21-2026-11-10` stays on `b6c9394`.

### Day 19 release — day19-2026-11-08 (published 2026-11-09 CST)
- Balance controls and arbitrary-stage MLX planning/transport; installer and native launchd services; per-stage pinned/checksummed own-file fetch. Strict GGUF independence remains partial; N-stage Optimize and three physical Minis remain unverified.
- Web restores the last successfully loaded model and exact split; explicit Unload saves no model. Fixed model jobs removed from default setup. **Restore-last-model reboot test: pending, deferred to the next dev day.** Earlier fixed-model reboot success does not validate the revised design.
- Full suite: **738 tests passed in 42.600 s**, no failures/skips.
- Remote access hardening 8ff3852: LAN/TB fallbacks and non-root Tailscale recovery guards (5/5 routes, 16/16 mocked guard cases, 3/3 fallback cases).
- Preserved Huihui Qwen3.5-27B Claude 4.6 Opus abliterated 4-bit, restored EXO2/EXO1 24/40; web/proxy correct short replies, ~0.8 s first token and 5.4 tok/s writing. No reboot or web restart; no video/X draft now. Install: INSTALL.md, docs/SERVICES.md. Details and remaining limits: docs/DAY19.md.

### Day 19 last-model auto-start design — 2026-11-08 (not a release)
- Replaces the normal fixed-model service mode with web-owned last-successful-model restore: atomic model/engine/placement/counts/settings persistence, explicit unload tombstone and one-shot normal UI-path replay. Failed loads keep the previous successful selection; missing Minis/files/memory give a clear idle warning, no auto-download/retry/crash loop.
- UI model switching and Balance remain unlocked. KEEP_WORKERS adopts existing owned local/pipeline/GGUF workers; remote single-Mini worker/tunnel adoption verifies identities and refuses reused PIDs. Normal split UI loads resolve explicit per-node Thunderbolt interfaces through the shared N-node planner.
- Removed only the two installed fixed Qwen jobs; kept web/model files/cache/logs. Normal UI-path Qwen24/40 load/save passed (10.121s), correct cold reply native5.45tok/s /1.7471s wall. New-mode EXO2 restart then failed to return to SSH within360s; EXO1 was NOT rebooted. Native automatic restore/switch/unload tests remain blocked, not passed. Last Qwen intent preserved; final split is not healthy while EXO2 is unreachable.
- **738 tests pass (44.459s), 44 new restore/HTTP/adoption regressions** including safely rejected unsupported UI settings preserving the last successful preference. Exact native evidence/state/recovery steps: DAY19.md and BENCHMARKS.md. No release/tag.

### Day 19 authorized reboot recovery — 2026-11-08 (not a release)
- Rebooted EXO2 first (then repeated after a fix), then EXO1. Existing auto-login/FileVault-off accounts returned unattended; permanent launchd Qwen/web services answered correctly. No login/security/network settings changed.
- Fixed changing Thunderbolt link-local IPs using explicit verified `tb://` / trusted-SSH `ssh+tb://` service endpoints, owned-child rebind and no LAN data fallback. Native EXO2 stage ready 48.533 s; EXO1 web 42.960 s / split 59.815 s; first correct reply observed 79.569 s after EXO1 restart, including inspection delay.
- Fixed stale live-peer display, inflated short MLX UI write rates/cached-read rates, and native launchd error-5 restart races with bounded safe retries (no root/unknown-process killing). Native cold 5.43 write tok/s; after web restart 5.02, warm cache retained. Historical inflated UI benchmarks are labeled, not silently reused.
- **694 tests pass (40.143 s), 21 new reboot regressions**. Permanent fixed-model services left healthy; full timings, raw-artifact locations, remaining account/hardware limits and UI ownership notes: [DAY19.md](docs/DAY19.md), [BENCHMARKS.md](docs/BENCHMARKS.md). No release/tag.

### Day 19 fresh install and next-login staging — 2026-11-08 (not a release)
- Native isolated-HOME fresh clone/venv/dependency install reached the web UI in 96.189 s; repeat 1.449 s, same PID/config. Explicit native status/restart/log/uninstall checks passed; temporary environments cleaned up. No separate account was created because noninteractive sudo required a password.
- Fixed selected-port installer output. Added explicit `--no-start --stage-login`: real LaunchAgents/configs prepared for next login without taking over today's unmanaged workers or web; loaded jobs are protected. Ten new regressions; **673 passed (39.892 s)**.
- Real EXO1 web/Qwen lead and EXO2 Qwen packer plists installed but deliberately not loaded. Original PIDs 69242/57464/54170 preserved. **No reboot or logout**; [DAY19.md](docs/DAY19.md) records the exact interruption/approval plan and [BENCHMARKS.md](docs/BENCHMARKS.md) the measured install results.

### Day 19 authorized live checks and fixes — 2026-11-08 (not a release)
- Two-Mini Balance/picker reload, actual three-stage 11/11/10 MLX simulation, correct answers, warm reuse, Save/Restore, web adoption, own-files fetch/stop/resume/restart and GGUF native split checks. Original Qwen3.5-27B 24/40 workers preserved; no permanent LaunchAgents/reboot.
- Fixed inventory metadata readiness, configured execution roots, endpoint-scoped legacy cleanup, verified custom-root adoption, recursive memory guard/nested model dimensions, preserved venv paths, idle-packer graceful stop/TIME_WAIT handling, complete web shutdown responses, verified peer-only GGUF reloads and native GGUF rate reporting.
- **663 tests pass (40.133 s)** in the final post-cleanup full suite (30 new live-fix regressions). Short-run real measurements and failure notes: [DAY19.md](docs/DAY19.md), [BENCHMARKS.md](docs/BENCHMARKS.md). Three physical Minis, GUI usability, multi-shard MLX savings, fresh-account install and permanent login/reboot remain unverified. Historical box-only checkpoints follow.

### Day 19 each Mini’s own files checkpoint — 2026-11-08
- Shared Balance/file preview + explicit Fetch UI/API, per-Mini logical/allocated disk usage, missing-shard replanning and retained-file lists. No automatic pruning or reload. Revision-pinned MLX stage downloads, published SHA256 checks, owned cancellation and restart-discoverable transfers.
- N-stage legacy picker bridge, saved stage-aware inventories/catalog/load plans, configurable own model roots and co-host simulation isolation. No default two-node cap; N-stage Optimize remains gated.
- Experimental GGUF peer-only, verified/resumable tensor Range downloads into the native RPC cache. Picker now fetches a complete GGUF only on the lead. **Strict independence remains incomplete:** llama.cpp needs that full lead file; small tensors/cache misses still cross RPC. [Limitations and API](docs/FILES.md).
- **633 tests pass (39.078 s), 62 new theme 3 tests**. A real-format synthetic GGUF/loopback HTTP/native-cache smoke fetched 12,582,912 peer bytes out of a 37,748,992-byte source, one required tensor only. Not a Mini/inference benchmark. No Mini or Omarchy touched; live steps and failed intermediate runs in [DAY19.md](docs/DAY19.md).

### Day 19 install + auto-start checkpoint — 2026-11-08
- One-command, idempotent native-Mac installer: platform/Python checks, dedicated clean source copy, reusable MLX venv/dependencies, plain output, portable no-write dry-run and safe config defaults.
- Generated per-user web and single/N-stage worker LaunchAgents; owned install/uninstall/status/graceful restart, logs under `~/.caravan`, no sudo or author-specific paths. Split workers run through `caravan_agent.py --service-config`, retry missing peers and stop only their own child.
- Web KEEP_WORKERS plus process-group preservation; late managed-lead adoption; fixed model jobs block conflicting web model control. Web-only auto-start keeps interactive model switching; fixed plans are a separate initial mode.
- **571 tests pass (37.444 s), 42 new theme 2 tests**. Failed intermediate runs and corrections are recorded in [DAY19.md](docs/DAY19.md). Mac install/launchd/login/reboot still pending; no Mini or Omarchy touched. [Guide](docs/SERVICES.md).

### Day 19 Balance + N-stage MLX checkpoint — 2026-11-08
- Experimental N-stage layer/shard plans and middle-packer transport; own per-stage caches, restore agreement and chain epoch invalidation.
- Topology Balance Auto/one-layer sliders, live memory/download preview and an explicit fresh-checked reload API, shared with a future TUI. No automatic downloads.
- N-stage launch/owned cleanup and web-restart node mapping. Serial, learning/guess-ahead off; N-stage Optimize is blocked. Old picker/download paths retain their two-stage gate until live verification.
- **529 tests pass (37.908 s), 42 new**; 3/4/7-stage socket simulations pass. No Mini contacted, no new inference benchmark. [Details and live steps](docs/DAY19.md).
- Easy install/auto-start, local-file ownership follow-up, diary sync and the final Day 19 release remain coordinator work.

### Day 18 release notes drafted — 2026-11-07
- Draft at `docs/release-notes/day18.md` (RELEASES.md doesn't name a location; this is the new home for notes). Not tagged or published. Planned tag `day18-2026-11-07`. Before publishing: final commit, test count, and the fresh-package check.

### Split point safety (balanced packer_layers) — 2026-11-07
Tonight's case: Dark Champion 21B 8-bit (32 layers, ~0.71 GB/layer) on two 24 GB Minis. The saved 24/8 split put 17.0 GB on EXO2, which left it 1.51–1.71 GB free against the 1.75 GB margin, and every chat got 507. 16/16 (~11.3 GB per Mini) worked.
- New `proxy/split_balance.py` (pure, any number of Minis): free_i = capacity_i − layers_i × GB/layer − 1.3 GB stage overhead (`CARAVAN_SPLIT_STAGE_OVERHEAD_GB`, calibrated on tonight's numbers: 24/8 → 1.66 GB on EXO2, 16/16 → 7.3 GB each). Capacity is `web_picker._node_capacity_gb` and the margin is `CARAVAN_MEMORY_SAFETY_GB` (1.75). `balanced_counts()` hands out layers one by one to the Mini with the most room left, so equal Minis split evenly and bigger Minis take more.
- **Download planning:** when no `packer_layers` is given, a split download now uses the balanced point for the chosen Minis' RAM instead of the fixed default of 24. The job note says so.
- **Picker:** split rows get `split_check` and `split_note`. When the saved point leaves a Mini under the margin, the row gets a ⚠ and a "⚠ Split:" line under the picker that names the tight Mini, the balanced point, and any extra files each Mini needs. Inventory rows now include `shards_present`, so Caravan can work out which files are missing.
- **Load:** if the balanced point's files are already on every Mini, `/api/models/load` loads at the balanced point and says so (`balance_note` plus an activity note). If files are missing, it returns 409 with the message listing them. **Nothing is downloaded automatically.** `force_split: true` keeps the saved point.
- Today the runtime has 2 stages, so the picker and load checks only run for 2-Mini splits. The math and tests cover N Minis. No Balance slider yet (future dev day).
- Tests: 13 new (`tests/test_day18_split_balance.py`) using tonight's numbers. Full suite 484 OK (33.8s).
- Live check later: the Minis need a pull before `shards_present` shows up in their inventory. Until then, the extra-files list is unknown and the picker just shows the warning.

### GGUF Optimize now wired to the button — 2026-11-07
- New `proxy/web_gguf_optimize.py` (`GgufOptimizer`) wraps `gguf_tune.GgufTuner` and reports in the same shape as the MLX Optimize now: phase, prompts, reloads, per-option schedule (pending/running/kept/skipped + winner), `reply_s`, `reload_s`, `eta_s`, summary. ETA = for each unsettled option, (2 − arms done) × (reload + 2 replies), plus one final reload of the winner.
- Endpoints: `POST /api/optimize/start` now picks the GGUF runner when the loaded model is llama.cpp (`backend == "llama"`); `POST /api/optimize/gguf/start` forces it. `GET /api/optimize`, `/pause`, `/cancel` follow whichever runner started last.
- Reloads go through `mgr.switch(..., entry={..., tune_override})`; the GGUF launcher uses `tune_override` instead of the saved best when present. Waits for your chats and honours Pause; Cancel finishes the current step, then reloads the best settings.
- UI: the Optimize now panel labels GGUF runs "(GGUF, each option reloads llama.cpp twice)".
- Tests: 4 new with a fake tuner/manager (`tests/test_day18_gguf_optimize_web.py`). Full suite 471 OK (32.8s). **Not run live yet.**
- Docs cleanup check: no duplicated "GGUF Optimize now runner" section exists in docs/DAY18.md or CHANGELOG.md (the earlier "duplicate" was two files' output printed back to back). Nothing to remove.

### Report this model + opt-in warning ping — 2026-11-07
- **Report this model:** the ⚠ line under the picker (`#modelWarn`) now has a "Report this model" link. It opens a new tab with a prefilled GitHub issue on linuxbren/caravan (label `model-report`). The body has only the HF repo id, the warning text, the Caravan version (short commit), `model_type`, and the `tie_word_embeddings` flag. No paths, hostnames, IPs, or tokens. The user reads, edits, and submits it themselves; Caravan sends nothing by itself. New `.github/ISSUE_TEMPLATE/model-report.md`; `model-report` label created on GitHub.
- `/api/models` rows now carry `model_type` and `tie_word_embeddings`; the response carries `caravan_version`.
- **Opt-in warning ping** (`proxy/web_alert.py`): off unless `CARAVAN_ALERT_WEBHOOK_URL` is set (default for everyone: off, no thread, no network). When set, the web server POSTs `{model, warnings, mini, caravan_version}` once per (model, warning set) when `/api/models` first shows it. Optional `CARAVAN_ALERT_WEBHOOK_KEY` goes out as both `Authorization: Bearer <key>` and `X-Webhook-Key: <key>`. Dedupe in `~/.caravan/alert-sent.json`; a failed POST isn't recorded, so it retries on the next picker refresh. Background daemon thread, 5 s timeout, never blocks the UI.
- Tests: 6 new (`tests/test_day18_model_report.py`): off when unset, payload shape, dedupe, new warning set re-pings, failed post retries, HTML link + template. Full suite 467 OK (32.3s).

### GGUF Optimize now runner (offline-tested) — 2026-11-07
- New `proxy/gguf_tune.py` (`GgufTuner`):
  - Follows `gguf_schedule()` one option at a time: reload, measure the incumbent, reload, measure the challenger.
  - Keeps the challenger only if it's more than 3% faster. Otherwise it records the challenger as a loser so it won't be retried.
  - Saves after every trial, and always leaves the winner running, including after an error.
- Store: `~/.caravan/gguf-tuned.json`, keyed by `<file>.gguf|<N>mini`.
- `measure_http()` reads llama-server's own `timings.predicted_per_second`, using 2 fixed prompts, temperature 0, 192 tokens.
- The web GGUF launcher now passes `best_tune()` to `llama_args(tune=...)`. Bad values are dropped, and with nothing learned the launch behaves as before.
- Not yet wired to the Optimize now button. That needs a web endpoint that calls `GgufTuner` with the launcher's restart. Next step.
- Tests: 5 new. Full suite 461 OK (32.8s). One failed test run: my test assumed ubatch 1024 is the first challenger, but the schedule picks 256 (a tie in distance from 512, so 256 comes first). The test was fixed; the code was unchanged.
- Live check: run the tuner against a small GGUF (Qwen2.5-3B q4_0) on 1 and 2 Minis. Expect about 6 reloads per run.

### Picker warnings for risky checkpoints — 2026-11-07
- `mlx_arch.model_warnings(config, weight_map)` flags four cases. It only warns and never blocks:
  - a top-level `*_text` model_type that isn't in the remap table
  - config ties embeddings but the files ship `lm_head` (the Dark Champion case)
  - config says untied but there's no `lm_head` (the output layer would be random)
  - `*_mtp`/`*_nextn` helper heads
- Carried through `inspect_tree` → node inventory → catalog rows (`warnings`). The model picker adds a ⚠ to the name, and the warnings show in its tooltip.
- Tests: 6 new. Full suite 456 OK (32.8s).
- Live check: after the Minis pull this, Dark Champion should show ⚠ with the tie note.

### MTP layers in split planning — 2026-11-07
- Checked HF indexes on Nov 7:
  - `mlx-community/Qwen3.6-35B-A3B-4bit`: 2090 keys, layers 0-39, `language_model.*`, no `mtp.*` keys.
  - `mlx-community/Qwen3.6-35B-A3B-MTP-4bit`: a standalone helper head. model_type `qwen3_5_mtp`, 46 keys, `fc`, `norm`, `pre_fc_norm_*`, a single `layers.0`, no embeddings. Its config still says 40 layers.
- Before: splitting the MTP repo would have planned 40 nonexistent layers. `mtp.*` keys inside a full checkpoint were fetched by both Minis, and `mtp.layers.0.*` was even counted as layer 0, which went to the packer.
- Now:
  - `mtp.*` keys go to the lead only.
  - Layers numbered at or above `num_hidden_layers` (DeepSeek/GLM nextn) go to neither stage. mlx_lm drops them at load, so neither Mini needs them.
  - `head_only_reason()` refuses to split helper heads (`*_mtp`/`*_nextn`, or no embeddings with fewer layers than config). Split downloads stop with a clear error, and inventory marks them not splittable.
- Tests: 5 new. Full suite 450 OK (32.3s). One failed run before the fix: `mtp.layers.0` was matched as layer 0, so its MTP check now runs first.
- Live check: none needed for the planner. For Qwen3.6 native MTP, confirm the lead still finds the MTP head.

### Rope scaling for classes that ignore it (mixtral etc.) — 2026-11-07
- Some mlx_lm classes ignore `rope_scaling` because they build a plain `nn.RoPE`. Examples: mixtral, qwen3_moe, phi3, gemma2, and about 40 more in mlx_lm 0.32.2.
- `proxy/mlx_arch.fix_rope_scaling()` swaps those for `mlx_lm.models.rope_utils.initialize_rope(...)` when config (or text_config) asks for scaling. Types covered: llama3, yarn, dynamic, and linear.
- Applied after load in the single-Mini worker and in split `Stage` (lead and packer). Classes that already scale (llama, qwen2/3, gpt_oss) are left alone. Site-packages is not edited.
- Tests: 5 new (fake RoPE/config). Full suite 445 OK (32.8s).
- Live check (testing window): load Dark Champion. Worker/packer logs should show `rope scaling: applied llama3 to N attention layer(s)`, and a long prompt should stay coherent.

### Releases — 2026-11-07
- First daily source release: `day17-2026-11-07`; main fast-forwarded to current work.
- Root INSTALL.md covers the web UI, dependencies, private-network setup and more Minis.
- Daily process: [RELEASES.md](docs/RELEASES.md). ZIP/tar.gz exclude lab video media.



### GGUF split hardening and picker downloads — 2026-11-06/07
- Picker downloads GGUF quants (one file, lead only) on the shared job system; finished downloads auto-load only when idle.
- Re-attach to a running GGUF split after a web restart; tensor-split from live free RAM; watchdog cleanup; plain 502 on peer loss mid-chat.
- CLI GGUF split moved to SSH tunnels; `agent/rpc_gate.py` removed (one mechanism). MLX-only Settings disabled for GGUF; Topology names Minis.
- Robustness: 5 cycles 20/20 OK, Stop mid-load and peer kill leave 0 processes. Known limit: GGUF Resume restarts from 0 %.

### Web helper consent and inventory — 2026-11-06
- Ask explicitly before downloading missing split-MLX guess-ahead helpers; allow reconsidering in Settings, and use normal resumable download jobs on the lead.
- No permanent silent decline for non-interactive loads; legacy silent declines no longer suppress the web prompt.
- Show individual draft helpers and native MTP heads in Topology disk inventory; protect helpers while any model is loaded.
- Tests: 6 new helper tests; full suite 371 passed (32.576s). Initial concurrent-work run: 365 tests / 1 GGUF fixture error, retained in WEB.md.

- Settings: validate HF tokens server-side, hide accepted-token input behind “Use a different token”, retain Cancel and saved-file removal, distinguish rejected credentials from unavailable checks.

### Optimize now scheduler (PR #9 replacement, 2026-11-07)

- Replace the hidden Deep/Quick coverage runner with paired, one-option A/B
  trials; keep everyday Auto learning separate.
- Add worker pause/hold/commit/release controls, web Pause/Resume, hardware-scoped
  losses and raw results, and cancel/error winner restoration.
- Preserve placement, config pins, PID ownership and web worker-keeping/adoption.
- See [OPTIMIZE-NOW.md](docs/OPTIMIZE-NOW.md) for the PR comparison and all test
  attempts, including failed runs and deployment status.
- Live testing also found/fixed an unnecessary single-Mini baseline reload and
  post-restart load-entry/recovery-release bugs. Final code passes 407 tests on
  box/EXO1/EXO2 (EXO1: one existing Node-only test skips), plus 24/24 theme parity.

## Day 20 — full-tool Hermes cache reuse (2026-11-09)

- Isolate MLX auxiliary prompts from the main conversation cache.
- Capture exact system/tool KV and recurrent-state checkpoints during prefill;
  reuse across chats and disk restores with stage-local files and N-stage
  digest checks, without reducing Hermes tools or changing the selected model.
- Add managed loopback OpenAI proxy launchd auto-start (`--kind proxy`).
- 767 tests pass (29 new). Evidence, setup and live validation: docs/HERMES.md
  and docs/DAY20.md. Reboot testing remains deferred.

  Live validation: same Huihui 24/40, 21 tools. Three full-tool follow-ups
  reused 13,182 tokens; prefill 1.17–1.76 s versus ~208 s cold, first visible
  Hermes text 11.57/9.23/9.78 s. A new chat also reused the prefix. Dense
  decode stays ~6.1 tok/s; cold/changed prompts are not instant. Proxy is now
  launchd-managed on EXO1. No reboot/web restart. Full methodology in DAY20.md.


## Mac pairing and paused C++ follow-up

- Add Macs page: nearby discovery, code-confirmed encrypted enrollment, dedicated
  SSH identity/host pin, backed-up node config and suggested N-node order.
- One-button authenticated removal; offline retries retain cleanup credentials.
  Native Remote Login remains an explicit Mac permission, not an installer sudo step.
- Per-account private browser permission plus local Host/Origin/CSRF checks;
  short-lived, one-use codes and durable guess budget. Experimental: security
  review and native Mac acceptance remain open; see `docs/PAIRING.md`.
- Each newly prepared helper gets a browser page. No running model is reloaded
  by pairing and no existing worker plan is migrated silently.
- Park C++ sources under `docs/history/cpp/`; inventory other clutter for approval.
