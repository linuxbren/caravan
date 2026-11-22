# Day 31 — placement counts the chat window; Settings and Topology list what is on disk

Day 31 ran Nov 21 2026 (America/Chicago) and is released as
[v0.9.1](https://github.com/linuxbren/caravan/releases/tag/v0.9.1).

1. [Part A: placement counts the chat window](#part-a-placement-counts-the-chat-window)
2. [Part B: the Settings load list shows only downloaded models](#part-b-the-settings-load-list-shows-only-downloaded-models)
3. [Part C: Topology agrees with Settings](#part-c-topology-agrees-with-settings)
4. [Code folder shown for each Mac](#code-folder-shown-for-each-mac)
5. [Follow-up: the app says "context" (v0.9.2)](#follow-up-the-app-says-context-v092)

## Part A: placement counts the chat window

Brenden asked whether Caravan could count a model's size **plus** the
memory its default chat window takes when it decides between one Mac and
a split. Since Day 30, Chat window Auto runs GGUF models as close to their
trained window as memory allows, so the files alone no longer say whether a
model really fits.

### What it did before

- **GGUF:** a placement fit if the file plus a flat 1.5 GB fit in 75% of
  each Mac's memory. The chat window was sized only after the Macs were
  picked, so a model could land on one Mac with a shorter window when a
  split would give it the full one.
- **MLX:** the fit check counted chat memory for an 8K window only, and
  the real search, download and Settings paths never sent the model's
  config, so it guessed 8% of the file size.
- **Unknown memory:** a GGUF placement on a Mac whose memory could not be
  read counted as a fit. That broke the "unknown capacity fails closed"
  rule.

### What it does now

One rule for both formats: a placement fits when the model's files, the
chat memory for its window, working memory and the safety margin all fit
that placement's memory budget.

- **The window** is the model's trained window: the GGUF header's
  `context_length`, or MLX `max_position_embeddings` (also inside
  `text_config` for wrapped models like Qwen3.5). 8K when the model does
  not say. A pinned Chat window (GGUF) is used instead.
- **Fits at all** means it holds at least an 8K window (or the whole
  trained window when that is shorter). A model that does not fit even
  then behaves as before.
- **The default** is the smallest placement that holds the full window.
  A model that holds it on one Mac stays on one Mac, with no split talk.
  When one Mac holds the files but only a shorter window, the split is
  recommended and the one-Mac choice stays available. When no placement
  holds the full window, the one with the longest window wins.
- **Plain text** on the page:
  - "Fits on 1 Mac with the full 128K window."
  - "Fits on 1 Mac with a 64K window. Split across 2 Macs for the full 128K window."
  - Each choice in Settings and in the download step says the window it holds.
  - Windows are shown in steps of 1,024 tokens, as in the Chat window menu:
    65,536 tokens is "64K" and 131,072 is "128K".
- **GGUF uses Chat window Auto's own math** (`auto_ctx`, `ctx_estimate`,
  `kv_auto`): 8-bit chat memory unless 16-bit is pinned, sliding-window
  layers counted at their real size, the window-sized working memory, the
  compute reserve and the safety margin. Pins that change Auto's window
  (Chat window, 16-bit Memory compression, Flash attention off, Prompt
  batch, Two chats) change the plan the same way. The lead Mac's budget is
  the one Auto uses; another Mac's is that scaled by its memory, so two
  matching Macs plan exactly like Auto across two devices.
- **GGUF before download:** Caravan reads the header from the first few
  MB of the file at the download source (never the weights) to learn the
  window and the chat-memory layout. If the header cannot be read, it uses
  the old rule.
- **GGUF download:** a split chosen only for a longer window still
  downloads the whole file to the 1st Mac, since the model can also run on
  one Mac. Per-Mac share downloads stay for models that cannot run on one.
- **MLX uses the real config** in the download step, the fit check, the
  download itself and the Settings list (the downloaded `config.json`).
  Search results use a config only when one was already fetched, so search
  never waits on one fetch per row.
- **Unknown memory fails closed:** a GGUF placement that includes a Mac
  whose memory cannot be read is not offered.
- **Fix found on the way:** the chat-memory estimate counted only the first
  part of a multi-part GGUF download (`name-00001-of-00003.gguf`). It now
  adds up every part, for Auto as well as placement.

### Check against real models (before publishing)

Real GGUF headers and MLX configs from the download source, the two Macs'
live memory from `/api/nodes`, and the 1st Mac's Auto limit:

| Model | Trained window | One Mac | Two Macs | Default |
|---|---|---|---|---|
| Llama 3.1 8B Q4_K_M (GGUF) | 128K | full 128K | full 128K | 1 Mac |
| gpt-oss 20B Q4_K_M (GGUF) | 128K | full 128K | full 128K | 1 Mac |
| Qwen3 30B-A3B Q4_K_M (GGUF) | 32K | does not fit | full 32K | 2 Macs |
| Qwen3 14B Q4_K_M (GGUF) | 32K | full 32K | full 32K | 1 Mac |
| Qwen2.5 Coder 7B Q4_K_M (GGUF) | 32K | full 32K | full 32K | 1 Mac |
| Llama 3.2 3B 4-bit (MLX) | 128K | full 128K | full 128K | 1 Mac |
| Llama 3.1 8B 4-bit (MLX) | 128K | 64K | full 128K | 2 Macs |
| Qwen3 30B-A3B 4-bit (MLX) | 40K | 16K | full 40K | 2 Macs |
| Qwen3 14B 4-bit (MLX) | 40K | full 40K | full 40K | 1 Mac |

The GGUF windows match what Chat window Auto picked on Day 30.

### Tests

- `tests/test_day31_context_fit.py` (31 tests): GGUF weights fit on one
  Mac but the window does not, so the default is a split and the text names
  the window; the full window on one Mac stays on one; 64K vs 128K drives
  the default; placement and Chat window Auto pick the same window; pinned
  16-bit memory and a pinned Chat window; too-big models; unknown trained
  window (8192); unreadable header (old rule); multi-part weights; unknown
  memory fails closed (GGUF and MLX); MLX uses the trained window and real
  config, not 8K / 8%; nested `text_config`; the Day 20 nested Qwen3.5
  guard; the MLX placement default; config and header fetches (header read
  in growing ranges); the Settings list sends the real config; server and
  page wiring; Balance shares and split budgets agree.
- Full suite: 1,993 tests, OK (was 1,962).

### Limits

- MLX chat memory for hybrid models (for example Qwen3.5, where only some
  layers keep full chat memory) is still counted as if every layer did.
  That is the cautious side: such a model may be recommended for a split a
  little early.
- Macs with different memory: GGUF placement sizes each Mac by its memory,
  but Chat window Auto at load still assumes the other Mac matches the 1st
  Mac. With matching Macs (the tested setup) they agree exactly.
- The Guess-ahead helper is not counted in the plan; at load it is left off
  if it does not fit with the chosen window, as before.

### Live check after publish

Published as source `24c7a9b`, pin `ece5456`, and installed with
`caravan update` on the 1st Mac. The Settings list (`/api/models`) then
showed the new placement notes, matching the table above:

- Llama 3.2 1B and Llama 3.1 8B GGUF: "Fits on 1 Mac with the full 128K
  window."
- gpt-oss 20B GGUF: 1 Mac, full 128K window.
- Qwen3 30B-A3B GGUF: "Split across 2 Macs for the full 32K window."
- MLX: Qwen3 30B-A3B 4-bit was the only MLX model still on disk (the
  others were deleted from the page during the check), so the MLX rows
  above come from the pre-publish check with the real configs.

## Part B: the Settings load list shows only downloaded models

Brenden saw many models in the Settings list of models to load, including
ones that were not downloaded. Rule: a model whose files are not complete
on the Mac or Macs that will run it never appears there.

### Cause

Not the installed-models cache: the server builds the list live from each
Mac's disk on every request. The list came from the full catalog, built
with "include models that can't load" turned on so the page could show a
reason. That kept rows whose files were **not** complete:

- partial downloads (any weight file present, others missing);
- a split whose other Mac's half was missing or deleted, and a saved
  one-Mac placement whose Mac no longer had the files;
- the loaded model, kept even after its files were gone;
- saved GGUF share records whose part or Mac was missing.

They showed greyed out, which still looks like "this is here". A GGUF file
whose later parts were still downloading could also be listed. After a
delete, the page refreshed only the disk panel, so the deleted model stayed
in the list until the next 5-second refresh (which only runs while the page
is visible).

### Fix

- Each catalog row now says whether its files are complete on every Mac
  its load plan needs. The Settings list keeps only those rows. A
  downloaded model that can't run (too big, unsupported) still shows with
  its reason.
- The loaded model stays only if its folder is really there (so a slow
  inventory from the other Mac doesn't hide it).
- GGUF share records show only when every part and Mac is ready; a GGUF
  file with a part still downloading is skipped.
- Deleting a model refreshes the Settings list right away.

### Live check

Read only: nothing was deleted to test. The list was compared with each
Mac's model folders.

| Mac | Before (list / on disk) | After (list / on disk) |
|---|---|---|
| 1st Mac | 13 / 13 (during Brenden's deletes), then 9 / 9 | 9 / 9 |
| 2nd Mac | 1 / 1 | 1 / 1 |

Published as source `f72bdd7`, pin `e3ad09c`, installed with `caravan
update` on both Macs.

At the time of the check every listed model was on disk: the models that
had shown up without files were gone after the deletes, so the bug was
fixed from the code paths above and covered by tests rather than
reproduced live.

### Tests

- `tests/test_day31_load_list.py` (14 tests): a complete model is listed; a
  partial download, a split missing its other half, a one-Mac placement
  without its copy, a folder with only metadata, the loaded model without
  files and the built-in catalog are not; the loaded model missed by a slow
  inventory stays; a downloaded but too-big model still shows with its
  reason; GGUF share records with a missing part and GGUF files still
  downloading are not listed; delete refreshes the list; the server filters
  the list.
- Full suite: 2,007 tests, OK.

## Part C: Topology agrees with Settings

After part B, Brenden saw that Topology and the Settings load list still
disagreed.

### What the two showed (read only, before the fix)

| Mac | Settings load list | Topology "On disk" |
|---|---|---|
| 1st Mac | 9: Qwen3 30B-A3B (MLX) and 8 GGUF models | 2: Qwen3 30B-A3B (MLX) and "caches" (0 GB) |
| 2nd Mac | 1: Qwen3 30B-A3B (MLX) | 2: Qwen3 30B-A3B (MLX) and "caches" (0 GB) |

### Cause

Topology's On disk list was built by an older scan than Settings:

- It looked for GGUF files in `~/.caravan/gguf` and `~/.ollama/models`.
  Caravan downloads GGUF models to `~/.caravan/models`, which is where the
  Settings list looks, so none of the GGUF models showed in Topology.
- It listed every folder under `~/.exo/models` as a model, including exo's
  own `caches` folder (shown as a 0 GB model) and empty leftovers.
- The Balance "Model to inspect" list still said "including incomplete
  downloads", but since part B it is the Settings list.

### Fix

- Topology now reads GGUF models with the same scan as Settings (all parts,
  finished downloads only), and counts only real model folders (weights or
  `config.json`) under the MLX folders, the same test each Mac's disk scan
  uses.
- A model that is on disk but not in the Settings list (for example a
  partial download) is still shown in Topology, so it can be deleted, with
  "Not in Settings: files incomplete".
- Delete now works for GGUF models too: it removes every part of that
  model from the 1st Mac (GGUF models live only there) and refuses the
  loaded model, symlinks and anything outside Caravan's GGUF folder.

### Tests

- `tests/test_day31_topology_models.py` (15 tests): GGUF models from
  Caravan's folder are listed with the same ids as Settings; a multi-part
  GGUF is one row with its full size; a GGUF still downloading and exo's
  `caches`, `drafts` and empty folders are not listed; the Settings flag and
  note; GGUF delete removes every part, keeps other models in the folder,
  refuses the loaded model and symlinks; server and page wiring.
- Full suite: 2,022 tests, OK.

## Code folder shown for each Mac

Topology listed this Mac's code folder as `~/cv3` on both Macs. That was
an old fallback: a Mac without a `repo` line in `config.toml` got the path
of a developer checkout that installs never create. A fresh install writes
no `repo` for this Mac, and pairing writes the real path only for the
other Macs, so every install showed it.

- This Mac now shows the folder its code really runs from
  (`~/.caravan/src/caravan` for an install).
- Another Mac without a saved `repo` now falls back to the install folder,
  `~/.caravan/src/caravan`, in every remote command (stats, model files,
  workers, updates, Thunderbolt checks), instead of `~/cv3`. Saved paths
  are kept as they are. No config file needed changing.
- `tests/test_day31_repo_default.py` (6 tests): this Mac's folder, the
  fallback for another Mac, saved paths kept, the stats command, the old
  default node list, and no code left that falls back to `~/cv3`.
- Full suite: 2,028 tests, OK.

## Release

- Tag [v0.9.1](https://github.com/linuxbren/caravan/releases/tag/v0.9.1)
  on commit `7ff9afe` (main; source pin `fecf488`). Notes:
  [release-notes/day31.md](release-notes/day31.md).
- Check: the tag's source download from GitHub, extracted fresh, has
  INSTALL.md and passes the full suite (2,028 tests, OK, about 65 s).
- Website: the Caravan page shows v0.9.1 with a "new in v0.9.1 · Day 31"
  section, and the install command with a Copy button under the top
  buttons (it wraps on phones).

## Follow-up: the app says "context" (v0.9.2)

Brenden: "Let's just keep it consistent." The placement lines, Settings
and the video said "window" for what most people call the model's
context. Wording only; placement, fit and launch math are unchanged.

| Where | Before | After |
|---|---|---|
| Placement (GGUF and MLX) | Fits on 1 Mac with a 64K window. Split across 2 Macs for the full 128K window. | Fits on 1 Mac with a 64K context. Split across 2 Macs for the full 128K context. |
| Placement choice | Fits on 2 Macs with the full 128K window. | Fits on 2 Macs with the full 128K context. |
| Placement, too big | Won't fit on this Mac, even with the shortest chat window (8K). | Won't fit on this Mac, even with the shortest context (8K). |
| Settings row label | Chat window | Context |
| Settings help | Auto uses the longest window that fits in memory, up to the full window the model was trained for. Native is that full window. | Auto uses the longest context that fits in memory, up to the full context the model was trained for. Native is that full context. |
| Settings help (Auto) | its full trained window / Its full trained window is 131072. | its full trained context / Its full trained context is 131072. |
| Memory compression help (GGUF) | …with the longest chat window. Pinning 16 can make Auto pick a shorter chat window. | …with the longest context. Pinning 16 can make Auto pick a shorter context. |
| Greyed-out sizes | This model was trained for a shorter window (131072). / This window will not fit in memory with this model. / …how long a window it was trained for. / The full trained window (…) will not fit… | This model was trained for a shorter context (131072). / This context size will not fit in memory with this model. / …how much context it was trained for. / The full trained context (…) will not fit… |
| Settings chip | chat window 65536 | context 65536 |
| Load log | …with this chat window / Kept the full chat window of … | …with this context / Kept the full context of … |
| Auto-tune skip | needs a shorter chat window | needs a shorter context |
| `caravan bench` | this model's chat window is 8192… / they would not fit the chat window. / …the model's chat window are skipped | this model's context is 8192… / they would not fit the model's context. / …the model's context are skipped |

- The saved setting is still `chat_window` (and the API fields
  `window_note`, `window_ctx`, `full_window`), so pinned values and old
  configs keep working.
- Not changed: "Terminal window" in the installer, sliding-window model
  internals, code names and comments.
- `tests/test_day31_context_wording.py` (5 tests) pins the exact line
  "Fits on 1 Mac with a 64K context. Split across 2 Macs for the full 128K
  context." for GGUF and MLX, the **Context** label with the old key, and
  the page's help copy. Old-string asserts in three test files updated.
- Full suite: 2,033 tests, OK.
