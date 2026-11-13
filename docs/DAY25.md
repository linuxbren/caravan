# Day 25 — GGUF Self-tuning, Chat window, Two chats, and a speed comparison

Day 25 is **published** (Nov 12 2026, America/Chicago). There is no
`day25` tag yet; that waits for a wrap-up. Day 24 remains tagged
(`day24-2026-11-12`). The 1st Mac and 2nd Mac were not changed for
this work: Brenden updates those Macs with `caravan update`.

This follow-up does not change `agent/`, `runtime/`, or the
requirements files, so a `caravan update` from the Day 24 pin keeps a
loaded model running. The web page still restarts.

## What shipped

### Self-tuning from real chats

When Self-tuning is on and a GGUF model is loaded, Caravan learns from
everyday chats, not from Auto-tune's canned prompts. After a few
replies it proposes one quiet trial — Prompt batch, then Memory
compression, then Flash attention, one at a time. Pinned choices stay
yours. When you are not mid-reply, the model reloads with a short
status: "Trying a different Prompt batch. The model is reloading." The
first reply after a reload is skipped, because it is often a cold
start. After a few more chats, Caravan keeps the change only if it is
faster, or reloads back to the previous settings. The same Before and
After lines Auto-tune uses are filled, in the same wording as the
stats under a reply. One completed trial is enough; it does not keep
experimenting. Reset tuning clears the saved result, including the
GGUF winner store.

Chat window and Two chats are not flipped automatically. They change
how much conversation and how many chats fit, which a single-reply
score would not judge fairly.

### Chat window

Settings has a **Chat window** row for GGUF (under Advanced, with
Apply and restart): Auto, 4096, 8192, 16384, 32768, and 65536. Auto
picks a size that fits this model and this Mac. When the file or
memory cannot be measured, Auto is 8192, the same trusted default as
before. Auto never jumps to a much larger window. If the model was
trained for less, Auto uses that shorter window. Sizes that will not
fit, or that are longer than the model was trained for, stay listed
but cannot be chosen, with a short plain reason. The total context
passed to the model is the per-chat window times the number of chats.

### Two chats

**Two chats** is available for GGUF: Auto, 1, or 2. Auto keeps one
chat. Set 2 and apply to let two chats share the model at the same
time, including on one Mac. The page no longer treats this as locked
off. Guess-ahead and Prompt lookup stay off for GGUF.

### `caravan models`

Lists the models already downloaded and ready to load, one line each:
the friendly name, whether it is GGUF or MLX, and the id to copy.
The currently loaded model is marked. The list comes from a running
Caravan, and GGUF files on this Mac's disk are included even if the
page's own list omitted them. If Caravan is not running, the command
says so and lists what it can see on this Mac's disk.

    caravan models

### `caravan bench`

Compares a GGUF model to its MLX counterpart and prints a compact
chart of reading speed, writing speed, and time to the first token.
Full model names are at the top; the bars are labeled GGUF and MLX.
Each size that was run (Short, ~1k, ~4k, ~8k) has a GGUF bar and an
MLX bar, the measured value at the end, and a small marker on the
winner (for example `* +22%`). Sizes that were not run are left out.
The chart fits 80 columns. On a terminal the bars use block
characters (█ ▌) in subtle amber (GGUF) and green (MLX); with
`--ascii`, when output is not UTF-8, or with `NO_COLOR`, the bars
are plain '#' and without color.

`--details` (also `--text`) also prints each side in the same wording
as the stats under a reply:

    Read X tok at Y tok/s · Write Z tok at W tok/s · first token A s · total B s

and a note about the unique openings. `--from-averages` draws the
same kind of chart from already-saved chat averages, without loading
or unloading a model.

It does not invent numbers. Pass a plain name, and Caravan finds the
matching GGUF and MLX among downloaded models (it ignores case,
punctuation, and quant suffixes). If none, one, or several match on a
side, it lists the candidates with their ids and how to pick with
`--gguf` or `--mlx`. Those flags still work on their own.

By default it runs five short prompts (the two Auto-tune has always
used, plus a short code, explanation, and list prompt) and a
long-prompt series at about 1k, 4k, and 8k tokens (two prompts at
each size, reported as medians). Sizes that will not fit the model's
chat window are skipped. `--short` or `--long` runs just one of
those. Each prompt starts with a unique opening so a shared-start
cache does not make later prompts look faster.

Without `--yes` it shows which two models it would compare and the
exact command, and does not load anything. `--yes` loads each model
in turn on a running Caravan. When the comparison finishes, or if a
measurement fails, Caravan puts the original model back, if one was
loaded, and says so. On a terminal, a small campfire animation shows
the current step in plain words (for example "Loading Qwen2.5 Coder
7B (GGUF)…", "GGUF · short prompt 3 of 5", "MLX · long prompt ~4k,
1 of 2", "Putting the original model back…") and the elapsed time,
on one line. When output is piped, or with `NO_COLOR` or `--quiet`,
that is a plain step line or is silent. Ctrl-C stops the animation
and still puts the original model back.

On the 1st Mac, with both models already downloaded:

    caravan models
    caravan bench "qwen2.5 coder 7b" --yes

Without `--yes`, the same command only prints the pair it would
compare and the exact command. To pick a specific file when several
match:

    caravan bench --gguf <gguf-id> --mlx <mlx-id> --yes

### First measured results (1st Mac)

Brenden's first real `caravan bench` on the 1st Mac, Qwen2.5 Coder 7B,
using the two short Auto-tune prompts of that build (before the five
short prompts and the long-prompt series):

    GGUF Q4_K_M: Read 46 tok at 157 tok/s · Write 166 tok at 22.3 tok/s · first token 0.22s · total 7.65s
    MLX 4bit: Read 46 tok at 182 tok/s · Write 172 tok at 23.5 tok/s · first token 0.33s · total 7.61s

On those short prompts, MLX was faster at reading (16% faster, 182 vs
157 tok/s) and at writing (5% faster, 23.5 vs 22.3 tok/s). GGUF's
first token was sooner (33% sooner, 0.22s vs 0.33s). Total time was
about the same (7.61s vs 7.65s).

### Full series on the 1st Mac

Brenden's first `caravan bench` of the five short prompts and the
long-prompt series, on the 1st Mac, Qwen2.5 Coder 7B. Figures are as
printed by the command with `--ascii`:

```
GGUF  Qwen2.5 Coder 7B (GGUF Q4_K_M)
MLX   Qwen2.5 Coder 7B (MLX 4bit)

Reading (tok/s, higher is better)
Short  GGUF  ###################################                   182
       MLX   #######################################               204  * +12%
~1k    GGUF  ##############################################        239
       MLX   #################################################     257  * +8%
~4k    GGUF  #########################################             215
       MLX   ##############################################        242  * +13%
~8k    GGUF  #####################################                 195
       MLX   ##########################################            218  * +12%

Writing (tok/s, higher is better)
Short  GGUF  ##############################################       22.2
       MLX   #################################################    23.4  * +5%
~1k    GGUF  #############################################        21.5
       MLX   ################################################     22.9  * +7%
~4k    GGUF  ########################################             19.1
       MLX   ##############################################       21.8  * +14%
~8k    GGUF  ###################################                  16.7
       MLX   ###########################################          20.4  * +22%

First token (s, lower is better)
Short  GGUF  #################################################   0.28s  * +39%
       MLX   ##############################                      0.46s
~1k    GGUF  ##############################################      5.30s
       MLX   #################################################   5.01s  * +5%
~4k    GGUF  ############################################       23.40s
       MLX   #################################################  20.96s  * +10%
~8k    GGUF  ############################################       52.15s
       MLX   #################################################  46.74s  * +10%
```

On those runs, MLX was faster at reading and at writing at every
size (the largest writing lead was 22% on the ~8k prompts, 20.4 vs
16.7 tok/s). GGUF's first token was sooner on the short prompts
(39% sooner, 0.28s vs 0.46s); MLX's first token was sooner on the
long prompts.

### Auto-tune prompts and scoring

Auto-tune (MLX and GGUF) uses the same five short prompts as bench,
plus one long prompt of about 2k tokens, skipped if it will not fit
the chat window. Each prompt has a unique opening so a shared-start
cache does not skew a trial. The winner is picked from medians, and
the score includes long-prompt read speed as well as write speed and
total time, so a setting that hurts reading is not picked. Before and
After stay in the same wording as the stats under a reply. A garbled
trial still loses, and the memory-check probe is still required.
Shared start and Two chats keep their own measurements, because those
knobs are about a cached prefix and two chats at once.

### Auto-tune progress

While Auto-tune is running, the Start or Tune again button becomes a
disabled busy state, **Tuning…**, with a small campfire flicker that
matches the theme (a static spark if you prefer reduced motion). A
live step line under it says what is happening, in plain words, with
the elapsed time, for example "Measuring the current setup · short
prompt 3 of 5", "Trying Memory compression 8 · long prompt", or
"Reloading with the winner…". The previous Before and After lines are
hidden for the length of the run — only the busy state and the step
line are shown — and are replaced by the new result when it finishes.
If the run fails or is cancelled, the previous lines come back. Reset
tuning is disabled while a run is in progress. A small **Tuning…**
badge sits next to the model name and in the chat header, so the run
is visible from the chat page even if Settings is closed. When
Self-tuning runs its quiet trial, a subtler **Self-tuning a setting…** note appears in the same place. When Auto-tune finishes,
a brief **Done** highlight (or **Nothing faster found**, when that
is the result) shows for a few seconds.


## What is in Settings for a GGUF model

Self-tuning stays visible. Under Advanced: Guess-ahead and Prompt
lookup (still off), Shared start, Two chats, Chat window, Memory
compression (Auto, 16, 8), Flash attention, and Prompt batch. Apply
and restart is inside Advanced. Fused kernels and GPU keep-warm stay
hidden.

## What is still ahead

- **GGUF Phase 3:** prompt lookup and a draft model, off by default,
  measured per model.
- **Voice:** a microphone in the chat box and a listen worker.
- Later: vision and voice models, a security review, FileVault and
  separate-account testing, and more than two Macs.

## Tests

New tests cover the launch flags, Auto Chat window (fallback, cap,
fit, and shorter trained windows), Settings pins, Self-tuning's one
quiet trial (keep, revert, pins, and a reload only when idle),
`caravan models` (including GGUF files the running page omitted),
plain-name matching for `caravan bench`, putting the original model
back, five short prompts and the long-prompt series (sizing, skip
when the window is too small, unique openings, `--short`/`--long`,
and a summary from measured numbers only), the default ASCII chart
(from the 1st Mac Qwen2.5 Coder 7B figures, including `--ascii`,
`--details`, skipped sizes, and `--from-averages`), and Auto-tune's
same five short prompts plus one long prompt (a faster write that
hurts long-prompt reading loses). The live Auto-tune progress (the
Tuning… button, the step line, hiding previous Before and After
lines, restoring them on cancel, and the chat-header badges) is
tested from measured wording only. The live progress animation is
tested on the non-TTY path, for step wording, and that the
background thread stops, including on Ctrl-C (the original model is
still put back). Existing tests were updated for the new prompt
counts.
