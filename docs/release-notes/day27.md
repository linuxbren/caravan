# Day 27 (Nov 15 2026)

Published Nov 15 CST; development-day tag `day27-2026-11-15`.

## Changed
- When a reply used Prompt lookup or Guess-ahead, the line under it
  ends with how many guessed words were kept, for example
  "guesses kept 88%".
- `caravan bench --speedups` measures Off, Prompt lookup,
  Guess-ahead, and Auto on short chats, code edits, and long
  prompts.
- GGUF Auto-tune tries Guess-ahead when a helper is already on this
  Mac, and keeps it only when it measures faster. Nothing is
  downloaded for you.
- When the loaded model has a known small helper that is not on this
  Mac, Settings offers it in one line under the model: "Download
  helper for faster replies?" with Download and Not now. Nothing
  downloads without a yes.
- GGUF Prompt lookup uses a better guesser.
- Guess-ahead and Prompt lookup help is model-neutral: it says what
  they are usually good at, not results from one particular model.
- Cancel Auto-tune shows Cancelling…, then a plain cancelled line.
  Load or Apply & restart while Auto-tune runs offers one
  "Cancel Auto-tune and apply" action. More buttons show a busy
  word and a result.
- With only one live Mac, Topology hides the Balance and Thunderbolt
  sections. They come back when a second Mac joins. A Mac whose
  Caravan is off, or whose numbers have not updated in 15 seconds,
  shows as offline with a grey light.

An update from the Day 26 tag keeps a loaded model running. The web
page still restarts.

## First measured results (1st Mac)

On the 1st Mac, Qwen2.5 Coder 7B GGUF with the 0.5B helper. Write
speed, median of each set:

- Short chats: 29.9 tok/s with Guess-ahead, +34% vs Off (22.3), and
  faster than MLX at 23.4.
- Code edits: 42.9 tok/s with Guess-ahead, +93% vs Off (22.3), and
  faster than MLX at 23.5.
- Auto-tune kept Guess-ahead: write 22.1 → 27.5 tok/s (+25%).

The first word on long prompts came about 8–11% later with the
helper. Full tables are in DAY27.md.

## Operational checks
- Day 27 was approved after live review.

Details: [DAY27.md](https://github.com/linuxbren/caravan/blob/day27-2026-11-15/docs/DAY27.md). Install: [INSTALL.md](https://github.com/linuxbren/caravan/blob/day27-2026-11-15/INSTALL.md). Benchmarks: [BENCHMARKS.md](https://github.com/linuxbren/caravan/blob/day27-2026-11-15/docs/BENCHMARKS.md).
