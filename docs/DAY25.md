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
Caravan. If Caravan is not running, the command says so and lists
what it can see on this Mac's disk.

    caravan models

### `caravan bench`

Compares a GGUF model to its MLX counterpart and prints each side in
the same wording as the stats under a reply:

    Read X tok at Y tok/s · Write Z tok at W tok/s · first token A s · total B s

It does not invent numbers. Pass a plain name, and Caravan finds the
matching GGUF and MLX among downloaded models (it ignores case,
punctuation, and quant suffixes). If none, one, or several match on a
side, it lists the candidates with their ids and how to pick with
`--gguf` or `--mlx`. Those flags still work on their own.

Without `--yes` it shows which two models it would compare and the
exact command, and does not load anything. `--from-averages` prints
already-saved chat averages without loading or unloading a model.
`--yes` loads each model in turn on a running Caravan and measures
with the same prompts Auto-tune uses. When the comparison finishes, or
if a measurement fails, Caravan puts the original model back, if one
was loaded, and says so.

On the 1st Mac, with both models already downloaded:

    caravan models
    caravan bench "qwen2.5 coder 7b" --yes

Without `--yes`, the same command only prints the pair it would
compare and the exact command. To pick a specific file when several
match:

    caravan bench --gguf <gguf-id> --mlx <mlx-id> --yes

Live GGUF vs MLX numbers from this command are not in this note. They
wait for Brenden to run it on the Macs.

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
`caravan models`, plain-name matching for `caravan bench` (unique,
several, none, and `--gguf`/`--mlx` still work), putting the original
model back after a live comparison even when a measurement fails, and
bench wording and steps. Existing tests were updated for the new
Settings rows.
