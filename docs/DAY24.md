# Day 24 — quieter page, Advanced sections, and model filters

Day 24 work is on the `day24-ui` branch and is **not published**. Day 23 live
testing and the `day23` tag come first. Nothing on the 1st node or 2nd node
was changed for this work.

## What changed

The page is cleaned up from a list Brenden dictated, panel by panel.

### Settings

Self-tuning stays visible and on by default. Every other optimization
(Guess-ahead, Prompt lookup, Shared start, Two chats, Fused kernels, Memory
compression, GPU keep-warm) and **Optimize now** sit under an **Advanced**
section that is closed until you open it. Apply & restart stays visible next
to Self-tuning.

When self-tuning or Optimize now finishes for a model, Caravan records the
speed from before the run and the speed with the chosen winners, and shows
both in the Self-tuning section (still visible, not inside Advanced):
"Before: 31 words/s, first word in 2.1 s. After: 42 words/s, first word in
1.2 s." The rate is the measured token rate, shown as words/s; the line
never says tok/s. It is hidden until a run has finished for the loaded
model. The pair is stored per model in `~/.caravan/speed_averages.json`
next to the chat averages (under a `tuning` key), so it describes these
Macs and survives a page refresh. Optimize now uses the existing chat
average if there is one; otherwise Before and After come from the trial
replies already sent during the run (incumbent replies at the starting
settings, then replies measured with the winning settings), so the run
does not add extra prompts. Self-tuning uses real-chat replies: those
before winners exist become Before; once winners are chosen and any
trial has settled, the next replies become After, and the pair is frozen.
A later Optimize now run replaces it.

The **Helper download…** button on the Guess-ahead row (inside Advanced)
is reserved in that row and only rewritten when its state actually
changes. Status and helper polls that return the same result leave the
button, and the other Settings rows, in place so the section does not
jump.

### Models

The **Reasoning** filter is renamed **Thinking**, so it matches the chat
Thinking button. The default chips are Chat, Coding, Thinking, Tools, and
Vision (image-text-to-text). Specialized types sit behind a closed Advanced
control and stay available, not removed: Embedding, Any-to-any, Text-to-image,
Text-to-video, Text-to-speech, and Decision.

**Decision** is Ollama's name for models that classify text, answer yes or no
with a probability, or score text against a rubric (System One models such as
Nimble, Tev, and Clef). They are not chat models.

These Advanced types stay in the picker because Caravan can sit as a middle
layer between an agent app (Hermes, OpenClaw, and similar) and a model those
apps may need, including models that do not chat.

The older API name `reasoning` is still accepted and treated as Thinking.
Cloud remains a source tab, not a type chip. An image-to-image search still
works if requested, but it is not a chip of its own (the list asked for
text-to-image).

The summary above the list follows the selected **fits-on** chip and counts
only matching models: with FITS-ON-1 selected it says "fit on 1 Mac", not
"fit on 2 nodes". It says Mac or Macs, never "nodes", and it does not show a
question mark when the number of online Macs is missing. The list and the
quant buttons are filtered to models that actually fit on that many Macs.

A **Family** dropdown on its own row, styled like the size filter, lists
Qwen, Llama, Gemma, Mistral, DeepSeek, gpt-oss, and Phi, but only those
with a match in the current catalog results. Matching is by repo and model
name, case-insensitive. QwQ is treated as Qwen, Mixtral as Mistral,
CodeLlama as Llama. Phi uses a start-boundary so a name like "sophia" is
not a false match. The known set is that list; the menu is derived from
what the search actually returned.

Hovering a model row shows a short tooltip built on the server:
maker (the Hugging Face org), release month and year, context length in
plain words ("Handles long chats (about 128k)."), and capabilities
("Can use tools, reads images."). Unknown fields are omitted, never shown
as a question mark. Speed is not included. Context tags that already say
"128k" stay in thousands; raw token counts such as 32768 are shown as
32k (1024-based).

Two downloads at once used to share one progress card, which flipped
between them on each refresh (an MLX job on a machine hostname next to a
GGUF job on "My Mac"). Each active download now has its own stacked card,
keyed by job id, so the bar, size, speed, waiting time, and Stop / Resume
/ Load-when-ready controls stay with that job and do not flicker. MLX and
GGUF use the same friendly Mac name from the configured inventory; a
hostname or a leftover EXO1/EXO2 label is replaced with "My Mac",
"1st Mac", or "2nd Mac". The "Load now?" dialog only appears when no other
download is still running, so two finishing jobs do not fight over it.

### Topology

Balance and Thunderbolt stay collapsed until you click them. The Balance
idle status is plain, quiet text, not a bold bordered box, and is split into
clear messages: "This split is already applied.", "This split is not safe to
apply.", and "Ready to apply a new split." Reload progress still uses the
banner.

### Main chat

- **Clear chat** is renamed **New session**.
- The running-option chips sit in a light boxed group titled **Current
  optimizations**, in the same order as Settings, with Self-tuning first.
  Each chip has a plain-words hover hint. They stay read-only labels.
- The Specifications box is removed (each reply already shows its own
  numbers). In its place, a quiet line directly under the input box and above
  Current optimizations shows the average for this model and this set of
  optimizations, for example "Usually 42 words/s, first word in 1.2 s". The
  line is hidden until at least one reply has been recorded for that setup.
  Averages are stored on the 1st node in `~/.caravan/speed_averages.json`
  (not only in the browser) so they describe these Macs and this setup, and
  they are shared if the page is opened from another device. The rate is the
  model's measured token rate, shown as words/s in plain language.

### Tagline

The "Built in the open" message is removed from the page. The title is
**Caravan**. The short line under the mark is **Your Macs. One model.**
There is no journey or public-build phrase on the page header. Pairing
already had a plain title and was left as it is.

## Docs

[WEB.md](WEB.md) and [MODEL_PICKER.md](MODEL_PICKER.md) describe the Advanced
sections, each filter, the middle-layer use case (as "agent apps", without
lab names), the average-speed line, New session, and the quieter Topology
status. This file and the Obsidian Day 24 note record the same decisions.

## Tests

Portable tests cover the page structure, filter tags and the Reasoning →
Thinking alias, family matching (including QwQ, Mixtral, CodeLlama, and the
Phi boundary), row tooltips, stacked per-job download cards and friendly
Mac names, speed-average math and separate slots per model and
optimization set, before and after auto-tune specs, the Helper download
button staying still across repeated identical polls, the start-message
wording (a related Day 23 fix, committed on its own), Balance status
wording, and the Models fit-summary line. The full suite is run on the
development node checkout. Counts are recorded at commit time.

## Not in this branch

- No publish, no `day23` or `day24` tag, no push. Day 23 testing finishes
  first.
- The 1st node and 2nd node were not touched.
- Brenden will review the page live after Day 23 testing.
