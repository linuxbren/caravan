# Day 31 — placement counts the chat window

Day 31 started Nov 21 2026 (America/Chicago). One dev session is one Day;
this page grows as the Day goes on.

1. [Part A: placement counts the chat window](#part-a-placement-counts-the-chat-window)

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
