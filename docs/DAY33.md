# Day 33 — A Guess-ahead helper for MLX on one Mac

Day 33 started Nov 23 2026 (America/Chicago). ROADMAP #1 (a Guess-ahead
helper for MLX on one Mac) shipped as
[v0.9.13](https://github.com/linuxbren/caravan/releases/tag/v0.9.13).
ROADMAP #2 — first-token timing in Auto-tune — shipped as
[v0.9.14](https://github.com/linuxbren/caravan/releases/tag/v0.9.14).

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

Released as [v0.9.14](https://github.com/linuxbren/caravan/releases/tag/v0.9.14)
(source and pin commits are recorded after publishing). Notes:
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
