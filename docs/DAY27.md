# Day 27 — Measured Guess-ahead, a helper offer, and GGUF closer to MLX

Day 27 ran Nov 13 2026 (America/Chicago), overnight. There is no `day27`
tag yet; it waits until the work has been tried on real Macs. Every
number below was measured on the 1st Mac with Qwen2.5 Coder 7B.

## At a glance

- **Guesses kept.** When a reply used Prompt lookup or Guess-ahead, the
  line under it ends with how many guessed words were kept, for example
  "guesses kept 88%".
- **`caravan bench --speedups`** measures Off, Prompt lookup,
  Guess-ahead and Auto on short chats, code edits and long prompts.
- **Guess-ahead on a GGUF model is now a real win** with a small helper:
  about 93% faster writing on code edits and 34% faster on short chats.
- **Download helper for faster replies?** When the loaded model has a
  known small helper that is not on this Mac, Settings offers it in one
  line under the model. Nothing downloads without your click.
- **GGUF Auto-tune now tries Guess-ahead** when a helper is on this Mac,
  and keeps it only when it measures faster.
- **GGUF Prompt lookup uses a better guesser**: about 95% faster on
  code edits (it was about 40%), no change on short chats.

None of the Day 27 changes touch `agent/`, `runtime/`, or the
requirements files, so `caravan update` keeps a loaded model running.
The web page restarts.

## Guesses kept

Prompt lookup and Guess-ahead both guess the next few words and let the
main model check them. Kept guesses are words the model did not have to
write one by one. Under a reply:

- A GGUF reply shows "guesses kept N%": how many of the guessed words
  the model kept.
- An MLX reply shows "N% of words guessed": the share of the reply that
  came from kept guesses.
- A reply with no guesses shows nothing new.

## `caravan bench --speedups`

```
caravan bench "qwen2.5 coder 7b" --speedups --yes
```

loads the model once per mode (Off, Prompt lookup, Guess-ahead when a
helper is on this Mac, and Auto) and runs the five short prompts, five
code-edit prompts ("change this file, return the whole file") and the
long-prompt series. Each row is the median of its prompts, with the
change against Off, the first-token time and the guesses kept. The model
that was loaded before is put back with its settings. `--only gguf` or
`--only mlx` measures one side; `--short`, `--edits` and `--long` pick
prompt sets. Without `--yes` it only explains what it would do.

On one Mac, an MLX model does not use a helper (that needs a split
model), so the MLX Guess-ahead row is skipped and says why.

## Measured: Qwen2.5 Coder 7B GGUF (Q4_K_M), 1st Mac

`caravan bench --speedups --only gguf`, with the small Qwen2.5 Coder
0.5B helper (Q8_0) on this Mac. Write speed in words per second
(tokens/s), median of each set.

| Mode | Short (5) | Code edits (5) | Long ~1k | Long ~4k | Long ~8k |
|---|---|---|---|---|---|
| Off | 22.3 | 22.3 | 21.6 | 19.2 | 16.8 |
| Prompt lookup (old guesser) | 22.3 (+0%) | 31.5 (+42%) | 21.3 (−1%) | 19.1 (−1%) | 16.9 (+1%) |
| Guess-ahead | 29.9 (+34%) | 42.9 (+93%) | 25.0 (+16%) | 20.3 (+6%) | 18.0 (+8%) |
| Auto (before Auto-tune) | 22.1 | 22.1 | 21.2 | 18.9 | 16.8 |

Guesses kept: Guess-ahead kept 55% on short chats, 97% on code edits
and 46–48% on long prompts. Prompt lookup kept 9% on short chats and
53% on code edits, and made no guesses on the long prompts.

The cost: with Guess-ahead the first word on a long prompt came about
8–11% later (Long ~4k: 25.4 s against 22.8 s), because the helper reads
the prompt too.

Auto ran with both off: Auto stays off until a test finds a winner, and
this run had not tuned the model yet. See Auto-tune below.

### Tuning the guessers (temporary server, short chats and code edits)

| Setting | Short | Code edits | Kept (short / edits) |
|---|---|---|---|
| Off | 22.2 | 22.2 | — |
| Guess-ahead, 3 words ahead (default) | 29.8–30.2 | 42.7–43.7 | 58% / 97% |
| Guess-ahead, 6 words ahead | 28.8 | 56.7 | 41% / 94% |
| Guess-ahead, 10 words ahead | 19.4 (slower) | 54.9 | 28% / — |
| Guess-ahead, 16 words ahead | 12.0 (slower) | 49.9 | 19% / — |
| Prompt lookup, old guesser | 22.2 | 31.1 | 9% / 53% |
| Prompt lookup, new guesser | 22.3 | 43.5 | 23% / 76% |
| Prompt lookup (new) + Guess-ahead | 28.5 | 55.8 | 54% / 80% |

Guessing more words at once helps code edits but hurts ordinary chats,
so Guess-ahead keeps 3 words ahead. The new Prompt lookup guesser was
the same on short chats, about 2% slower on a ~4k prompt (18.6 against
19.1) and much better on code edits, so it replaces the old one.

### Auto-tune with a helper on this Mac

The real GGUF Auto-tune, run against a temporary server (it did not
change the saved tuning on the Mac):

| Trial | Kept | Result |
|---|---|---|
| Flash attention on vs off | on | the same |
| Read size 512 vs 256 | 512 | the same |
| Memory f16 vs 8-bit | f16 | the same |
| Prompt lookup off vs on | off | the same on Auto-tune's prompts |
| Guess-ahead off vs on | **on** | write 22.1 → 27.5 tokens/s (+25%), total time 8.9 → 6.0 s |

Before: write 22.2 tokens/s. After: 27.5 tokens/s. Auto-tune's long
read was about 4% slower with the helper, and Auto-tune still kept it
because the whole reply finished sooner.

## Measured: Qwen2.5 Coder 7B MLX (4-bit), 1st Mac

`caravan bench --speedups --only mlx`, one Mac. Write speed in tokens/s,
median of each set.

| Mode | Short (5) | Code edits (5) | Long ~1k | Long ~4k | Long ~8k |
|---|---|---|---|---|---|
| Off | 23.4 | 23.5 | 23.0 | 21.9 | 20.5 |
| Prompt lookup (adaptive) | 23.6 (+1%) | 28.0 (+19%) | 22.3 (−3%) | 21.0 (−4%) | 18.7 (−9%) |
| Guess-ahead | skipped: on one Mac an MLX model does not use a helper yet | | | | |
| Auto | 23.4 | 23.4 | 23.0 | 21.7 | 20.4 |

Prompt lookup made 38% of the words on code edits and almost none on
the other prompts. It was slower on long prompts, so Auto keeping it
off is right. First token: 0.46 s short, 20.9 s on ~4k, 45.9 s on ~8k.

### GGUF against MLX, same model, one Mac

| | GGUF Off | GGUF best (Guess-ahead) | MLX Off | MLX best |
|---|---|---|---|---|
| Short chats, write | 22.3 | **29.9** | 23.4 | 23.6 |
| Code edits, write | 22.3 | **42.9** (55.8 with Prompt lookup too, temporary server) | 23.5 | 28.0 |
| Long ~8k, write | 16.8 | 18.0 | **20.5** | 20.5 |
| First token, short | **0.28 s** | 0.28 s | 0.46 s | 0.43 s |
| First token, ~8k | 52.1 s | 56.4 s | **45.9 s** | 45.9 s |

Without a helper, MLX writes about 5% faster than GGUF. With the small
helper, GGUF now writes about 28% faster than MLX on short chats and
about 50% faster on code edits. MLX still reads long prompts sooner
(about 12% on ~8k) and writes faster on very long ones.

## Download helper for faster replies?

When the loaded model has a known small helper that is not on this Mac,
Settings shows one line under the model:

> Download helper for faster replies? (531 MB) **Download** **Not now**

- A GGUF model gets a GGUF helper. A split MLX model gets its MLX
  helper. On one Mac an MLX model does not use a helper yet, so no line
  appears for it.
- **Download** shows its progress in that same line (with Stop), then
  puts Guess-ahead on Auto. Auto still decides by measurement: Auto-tune
  keeps the helper only when replies get faster. A Guess-ahead you set
  to On stays On.
- **Not now** is remembered for that model and Caravan never asks again
  for it.
- Nothing downloads without a click on Download.
- The line is hidden when the page is opened from another computer on
  your network, the same rule as Update now. It shows on this Mac and
  over Tailscale.
- `caravan bench` asks the same question in a terminal:
  `Download helper for faster replies? (531 MB) [y/N]`. Only "y"
  downloads; anything else is remembered as Not now. Without a terminal
  it prints a note and does not download.

Known helpers:

| Main model | Helper | Size | Measured |
|---|---|---|---|
| Qwen2.5 Coder 1.5B–32B | Qwen2.5 Coder 0.5B Instruct (Q8_0) | 531 MB | Yes, Day 27 (7B) |
| Qwen2.5 3B–72B | Qwen2.5 0.5B Instruct (Q8_0) | 531 MB | Not yet; Auto-tune decides |
| Qwen3 4B–32B | Qwen3 0.6B (Q8_0) | 805 MB | Not yet; Auto-tune decides |
| Llama 3.1 / 3.3 8B and 70B | Llama 3.2 1B Instruct (Q8_0) | 1.3 GB | Not yet; Auto-tune decides |

A helper must be the same model generation as the main model (Qwen2.5
with Qwen2.5, Qwen3 with Qwen3), so a helper from another generation on
this Mac is never used by mistake.

## GGUF closer to MLX: which settings apply

| Setting | MLX | GGUF | Day 27 |
|---|---|---|---|
| Guess-ahead (helper) | split models only | yes, one Mac | measured; Auto-tune tries it; helper offer |
| Prompt lookup | adaptive | on / off | new guesser, measured |
| Two chats | yes | yes | — |
| Shared start | yes | yes | — |
| Chat window | yes | yes | — |
| Memory compression | 8-bit and 4-bit | 8-bit only | 4-bit is not offered for GGUF on purpose |
| Flash attention, read size | does not apply | yes | Auto-tune tries them |
| Fused kernels | yes | does not apply (llama.cpp has its own) | — |
| GPU keep-warm | split MLX only | does not apply on one Mac | — |
| Threads | does not apply | does not apply (the whole model runs on the GPU) | — |

On one Mac, GGUF can now use a helper and MLX cannot, so for Qwen2.5
Coder 7B on one Mac the fastest Caravan setup measured tonight is the
GGUF model with Guess-ahead.

## Updating

`caravan update` keeps a loaded model running for every Day 27 change:
none of them touch `agent/`, `runtime/`, or the requirements files. The
web page restarts; press Cmd-R if a tab does not reload. A changed
Prompt lookup or Guess-ahead takes effect on the next model load.
