# Day 33 — A Guess-ahead helper for MLX on one Mac

Day 33 started Nov 23 2026 (America/Chicago). This file describes the
first item (ROADMAP #1). The work is uncommitted on
`day33-mlx-1mac-helper` pending Claude review. VERSION and CHANGELOG
stay at 0.9.12 until approval (to ship as v0.9.13). ROADMAP #2 — first
token with Guess-ahead in Auto-tune — is queued next.

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
- ROADMAP #2 (first-token timing in Auto-tune) is not in this tree.
