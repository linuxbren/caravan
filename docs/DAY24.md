# Day 24 — quieter page, Advanced sections, and model filters

Day 24 is **published** (Nov 12 2026, America/Chicago). There is no `day24`
tag yet; that waits for live review. Day 23 remains published (tag
`day23-2026-11-11`, pin `5717c4a`, source `940cbec`). The 1st node and 2nd
node were not changed for this work: Brenden updates those Macs with
`caravan update`.

Caravan is open source under the MIT License. Copyright (c) 2026 Brenden
Dawson. See [LICENSE](../LICENSE).

## What changed

The page is cleaned up from a list Brenden dictated, panel by panel.

### Settings

Self-tuning stays visible and on by default, with its On/Off switch and
the hint "Caravan learns from your chats and remembers faster settings
for each model. Pinned choices stay yours." A thin divider sits below
it, then a new **Auto-tune** heading, outside Advanced, with the hint
"Tries different settings on the loaded model right now and keeps the
fastest." Under that, an indented block holds **Start** (or **Tune
again**, once this model has been tuned) and
**Reset tuning**, the note "Tune again runs fresh trials. Reset tuning
forgets saved results for this model. The model stays loaded," and the
Before and After lines. Auto-tune works whether Self-tuning is On or
Off. Press Tune again for a fresh trial on the loaded model, even if a
trial already ran — you do not need to remove or redownload the model.
Reset tuning clears the saved results for this model and this setup; the
model stays loaded. Pause and Cancel appear in that same block during a
run. Every other optimization (Guess-ahead, Prompt lookup, Shared start,
Two chats, Fused kernels, Memory compression, GPU keep-warm) sits under
an **Advanced** section that is closed until you open it, along with
**Apply & restart** and the "Auto = Caravan decides" note. There is no
Tune or Optimize button inside Advanced. Toggling Self-tuning On or Off
saves and takes effect immediately on a loaded model, with no reload:
learning is a live flag on the running worker. A plain one-line notice
confirms the change. The On/Off switch does not show a conflicting
"now: off" line. Apply & restart is only needed for the other
optimization options, which still require a reload to apply.

When Self-tuning or Auto-tune finishes for a model, Caravan records the
speed from before the run and the speed with the chosen winners, and shows
them as two lines in the Auto-tune section (still visible, not inside
Advanced, and not under Self-tuning), for example "Before · Write 88.4 tok/s · first token 0.29s"
and "After · Write 94.5 tok/s · first token 0.15s". The wording, units,
and rounding match the stats under each reply and the average under the
chat input (tok/s, first token, and any extra fields that were recorded).
Self-tuning results feed the same Auto-tune lines. If a run finds nothing
faster, or the two sides would look the same, the page shows one plain
line instead: "Already at its fastest settings. Nothing faster found."
The slot is reserved at two-line height so the Settings rows below do
not jump when the text appears. The lines stay empty until a run has
finished for the loaded model. The pair is stored per model in
`~/.caravan/speed_averages.json` next to the chat averages (under a
`tuning` key), so it describes these Macs and survives a page refresh.
Auto-tune uses the existing chat average if there is one; otherwise
Before and After come from the trial replies already sent during the run
(incumbent replies at the starting settings, then replies measured with
the winning settings), so the run does not add extra prompts. Self-tuning
uses real-chat replies: those before winners exist become Before; once
winners are chosen and any trial has settled, the next replies become
After, and the pair is frozen. A later Auto-tune run replaces it.

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
  optimizations. The wording, units, and rounding match the stats under
  each reply, with a leading Average label, for example "Average · Read 165
  tok at 200 tok/s · Write 10 tok at 20.7 tok/s · first token 0.34s ·
  total 0.78s". A field with no data yet is left out. The line is hidden
  until at least one reply has been recorded for that setup. Averages are
  stored on the 1st node in `~/.caravan/speed_averages.json` (not only in
  the browser) so they describe these Macs and this setup, and they are
  shared if the page is opened from another device.

### Tagline

The "Built in the open" message is removed from the page. The title is
**Caravan**. The short line under the mark is **Your Macs. One model.**
There is no journey or public-build phrase on the page header. Pairing
already had a plain title and was left as it is.

## Docs

[WEB.md](WEB.md) and [MODEL_PICKER.md](MODEL_PICKER.md) describe the Advanced
sections, each filter, the middle-layer use case (as "agent apps", without
lab names), the average-speed line, New session, and the quieter Topology
status. Short release notes are in [release-notes/day24.md](release-notes/day24.md).
This file and the Obsidian Day 24 note record the same decisions. The
repository also carries the [MIT License](../LICENSE).

## Tests

Portable tests cover the page structure, filter tags and the Reasoning →
Thinking alias, family matching (including QwQ, Mixtral, CodeLlama, and the
Phi boundary), row tooltips, stacked per-job download cards and friendly
Mac names, speed-average math and separate slots per model and
optimization set, before and after auto-tune specs, the Helper download
button staying still across repeated identical polls, the start-message
wording (a related Day 23 fix, committed on its own), Balance status
wording, and the Models fit-summary line. Later tests cover whole-repo fetch for
models without a top-level `config.json`, download-only notices for
Advanced types Caravan cannot serve, plain download errors with
friendly Mac names, leftover SSH-forward reuse (only Caravan's own
forward is reused or replaced), plain load errors with friendly
Mac names and no paths, and GGUF Settings and Optimize now
(trusted load flags, f16 vs q8_0 trials, and before/after lines). The full suite is run on the
development node checkout. Counts are recorded at commit time.

## Publication

Published to the install channel and main. No `day24` tag yet — that waits
for Brenden's live review. The 1st node and 2nd node were not touched for
this publication. A `caravan update` from the Day 23 pin picks up this
release. Model-running code in `agent/` changed (`mlx_worker.py`, so
Self-tuning can apply without a reload), so a loaded model is reloaded
and Caravan says so. The same model is restored after the update.

During live review, the average line under the chat input was changed to
use the same wording as the stats under each reply (this section above).
That follow-up is only page, proxy, and docs — not `agent/`, `runtime/`,
or the requirements files — so a `caravan update` from the first Day 24
pin keeps a loaded model running. The web page still restarts. See
[release notes](release-notes/day24.md).

### Live review: image downloads, honesty, and plain errors

A download of a repo without a top-level `config.json` (image, video,
text-to-speech, speech-to-text/ASR, or any other non-LLM layout, with
files in subfolders such as `transformer/`, `voices/`, or `whisper/`,
and maybe a `model_index.json`) used to fail after the fetch looked
only for an LLM layout. The fetch now downloads the whole tree whenever
those LLM index files are not at the top level — the layout does not
have to be a diffusion repo — and Resume continues from the files
already on disk. There is no need to delete a partial folder.

The picker is honest about what Caravan's chat can run. Advanced types
(embedding, any-to-any, text-to-image, text-to-video, text-to-speech,
speech-to-text, and Decision) stay available for download, with a quiet
line on the row and in the hover: "Download only, Caravan can't run
image models yet", "Download only, Caravan can't run video models yet",
or "Download only, Caravan can't run speech models yet" (the same
speech line covers text-to-speech and speech-to-text, including ASR).
After download, the card does not offer Load. A Load request returns a
short line such as "Caravan can't run image models yet."

Download cards use friendly Mac names (1st Mac / 2nd Mac / My Mac) and a
short plain error, for example "Download stopped. Press Resume to try
again." They never show a machine hostname, an internal paired id, or a
Python traceback. The full detail goes to the log on that Mac.

This follow-up changes `agent/mlx_split_fetch.py`, so a `caravan update`
from the previous Day 24 pin reloads a loaded model; the same model is
restored. The portable suite on a fresh clone on the development node:
**1,296 tests passed** in 54.024 s. The 1st node and 2nd node were not
touched for this publication. No `day24` tag yet — that still waits for
Brenden's live review. Source and pin SHAs are recorded at publication
time.

### Live review: before/after lines by the button that produced them

The Settings before/after result is now two lines, using the same wording
as the reply stats and the chat average ("Before · Write 88.4 tok/s ·
first token 0.29s" and "After · Write 94.5 tok/s · first token 0.15s"),
not words/s. The same two lines appear under Self-tuning and, when
Optimize now produced the result, under that button as well. The slots
are reserved so the page does not jump. This follow-up is only page,
proxy, and docs — not `agent/`, `runtime/`, or the requirements files —
so a `caravan update` from the previous Day 24 pin keeps a loaded model
running. The web page still restarts. The portable suite on a fresh
clone on the development node: **1,296 tests passed** in 54.517 s. The
1st node and 2nd node were not touched. No `day24` tag yet. Source and
pin SHAs are recorded at publication time.

### Live review: leftover SSH tunnel after an update

After an update that keeps the model, the web page restarts and leaves
the SSH forward that chat uses, so the model can stay loaded. The next
load — for example, switching to a smaller model on the 2nd Mac — used
to try to open the same forward again and fail with a raw SSH message,
because the leftover process was no longer tracked.

The load now checks whether the process holding that port is Caravan's
own forward to the same Mac and port (by matching the command line). If
it still works, it is reused. If it is ours but no longer works, only
that process is stopped and the forward is opened again. A process that
is not Caravan's is never killed. Unload, a model switch, a web stop
that actually stops the workers, and an update that reloads workers
also clean up Caravan's own forwards, so they are less likely to be
left behind. When the update keeps the model, the forward is left for
the new page to pick up.

User-facing load status uses a friendly Mac name and never a hostname
or a file path — for example, "starting single-Mini worker on 2nd Mac".
If a tunnel error still happens, the page shows a one-line message such
as "Couldn't start the model on the 2nd Mac. Try loading again." The
full detail goes to the log only.

This follow-up is only proxy, the update tool, tests, and docs — not
`agent/`, `runtime/`, or the requirements files — so a `caravan update`
from the previous Day 24 pin keeps a loaded model running. The web page
still restarts. The portable suite on a fresh clone on the development node:
**1,312 tests passed** in 55.774 s. The 1st node and 2nd node were
not touched. No `day24` tag yet. Source and pin SHAs are recorded at
publication time.

### Live review: GGUF Settings and Optimize now

The web Load path for a GGUF model now uses the same trusted options
Caravan already uses on its other llama-server path: flash attention
on, automatic memory compression (the full 16-bit option when it fits,
otherwise the lighter 8-bit option — never 4-bit), a default prompt
batch, saved slots for later turns, and no extra host-memory cache
copy. The chat window size is unchanged.

Settings no longer greys out the whole panel with an "MLX only" note.
For a GGUF model, Self-tuning, Memory compression, Shared start, Flash attention, and Prompt batch are available, with plain-word hints.
Memory compression offers Auto, 16, and 8 only. Guess-ahead, Prompt
lookup, and Two chats stay off until a later test says otherwise.
Fused kernels and GPU keep-warm are hidden, because they have no
GGUF equivalent. Self-tuning on a GGUF model is a saved preference:
a change reloads the model when you are not mid-reply.

Optimize now (and the same self-tuning trial) also compares 16-bit and
8-bit memory compression, with flash attention kept on, and scores
read speed, first-token time, and write speed — not write speed alone.
The Before and After lines under Self-tuning (and under Optimize now
when that produced the result) work for GGUF models too.

This follow-up is only proxy, tests, and docs — not `agent/`,
`runtime/`, or the requirements files — so a `caravan update` from the
previous Day 24 pin keeps a loaded model running. The web page still
restarts. The portable suite on a fresh clone on the development node:
**1,329 tests passed** in 57.055 s. The 1st node and 2nd node were not
touched. No `day24` tag yet. Source and pin SHAs are recorded at
publication time.

### Live review: Self-tuning error with no reason on the page

After the GGUF Settings update, a split MLX model (Qwen2.5 Coder 7B
Instruct 4bit, on the 1st Mac and the 2nd Mac) loaded fine. Turning
Self-tuning on started a trial run. Shared start was tried and kept.
The next trial, Memory compression, reloads the model and then
measures. That measurement was rejected, and the run stopped. The
model was put back on the previous settings and stayed ready.

The page did not explain. The only visible sign was "stopped (error)"
under Optimize now, which sits in the closed Advanced section, and
the recorded reason was a raw request error with no useful wording.
The full worker reply was not kept for the log, because the restore
reload replaced the worker log.

Self-tuning and Optimize now errors now show a short plain reason
next to Self-tuning (and under Optimize now), for example "Self-tuning
stopped while trying Memory compression. A trial setting was rejected.
The model is back on the previous settings." Friendly Mac names only;
no hostnames or paths. The full detail goes to the log only.

This follow-up is only proxy, tests, and docs — not `agent/`,
`runtime/`, or the requirements files — so a `caravan update` from the
previous Day 24 pin keeps a loaded model running. The web page still
restarts. The portable suite on a fresh clone on the development node:
**1,339 tests passed** in 55.862 s. The 1st node and 2nd node were not
touched. No `day24` tag yet. Source and pin SHAs are recorded at
publication time.

### Live review: Tune again, next to Self-tuning

A later live review on the same split model (Qwen2.5 Coder 7B Instruct
4bit, on the 1st Mac and the 2nd Mac) found that pressing the old
Optimize now control did not measure anything new. Every option was
skipped (already tried, or pinned on the page), so the run finished
in no time with no prompts. The Before and After lines were an older
record of the same numbers on both sides, which looked like a proof
the model got faster when it had not. Self-tuning showed On, and a
conflicting "now: off" next to it, with a leftover notice that
Self-tuning "takes effect when you load a model" even though a model
was already loaded. The Self-tuning hint also said it was for each
MLX model; it also covers GGUF.

**Tune again** now sits next to the Self-tuning switch, outside
Advanced, with a smaller **Reset tuning** beside it. There is no
duplicate inside Advanced. Pressing Tune again always runs a fresh
trial on the loaded model: earlier losses and page pins do not skip
the run, and you never need to remove or redownload the model. Reset
tuning clears the saved winners, losses, and the speed lines for this
model; the model stays loaded. If a run finds nothing faster, the page
shows one line, "Already at its fastest settings. Nothing faster
found," not two identical Before and After lines. The conflicting
"now: off" line next to On is gone. The leftover "takes effect when
you load a model" notice is cleared once a model is ready. The
Self-tuning hint is for each model, not only MLX. A split load with
Self-tuning on no longer starts the lead with learning paused.

This follow-up is only proxy, tests, and docs — not `agent/`,
`runtime/`, or the requirements files — so a `caravan update` from the
previous Day 24 pin keeps a loaded model running. The web page still
restarts. The portable suite on a fresh clone on the development node:
**1,356 tests passed** in 56.131 s. The 1st node and 2nd node
were not touched. No `day24` tag yet. Source and pin SHAs are recorded
at publication time.

### Live review: Auto-tune section

A later layout follow-up, approved from a mockup, moves Tune again and
Reset tuning out of the Self-tuning block and into their own **Auto-tune**
section, still outside Advanced. Self-tuning keeps only the On/Off
switch and its hint. A thin divider, then the Auto-tune heading and
hint, then an indented block with a left border holds the buttons, a
short note, and the Before and After lines (or the one-line "already
fastest" message). Pause and Cancel appear in that block during a run.
Auto-tune works whether Self-tuning is On or Off. The Before and After
lines no longer appear under Self-tuning; Self-tuning results still
feed the Auto-tune slot. There is no Tune or Optimize button inside
Advanced. The page and the docs say Auto-tune where they used to say
Optimize now; the API routes are unchanged.

This follow-up is only proxy, tests, and docs — not `agent/`,
`runtime/`, or the requirements files — so a `caravan update` from the
previous Day 24 pin keeps a loaded model running. The web page still
restarts. The portable suite on a fresh clone on the development node:
**1,357 tests passed** in 57.188 s. The 1st node and 2nd node
were not touched. No `day24` tag yet. Source and pin SHAs are recorded
at publication time.

### Live review: Campfire theme, and Start until a model is tuned

Campfire replaces Nebula in the theme switch: Amber, Green, Meadow,
Campfire. It is the approved Moonlit mockup, drawn in SVG and CSS with
no photos — a cool blue night sky, a soft moon, crisp stars, a dark
tree line, and a campfire glowing low in the lower-left. Panels are
frosted and dark, with amber accents, and the text stays readable. The
logo, chips, dialogs, helper prompt, drawers, Topology bars in Theme
mode, the model picker, download cards, and the phone layout all follow
the theme. Anyone who had Nebula saved opens Campfire instead. The
Webb image asset and its credit are removed.

In Auto-tune, the primary button says **Start** when the loaded model
has never been tuned (no saved result for it), and **Tune again** once
a run has finished. After Reset tuning clears the saved results, it
says **Start** again. Either label runs the same fresh trials. The
label stays correct after a run finishes and after a page reload. The
rest of the Auto-tune layout is unchanged.

This follow-up is only proxy, tests, tools, docs, and the removal of
the unused Nebula images — not `agent/`, `runtime/`, or the
requirements files — so a `caravan update` from the previous Day 24
pin keeps a loaded model running. The web page still restarts. The
portable suite on a fresh clone on the development node:
**1,365 tests passed** in 57.304 s. The 1st node and 2nd node
were not touched. No `day24` tag yet. Source and pin SHAs are recorded
at publication time.

### Live review: Open on the local network

Brenden asked for an option to open Caravan on the local network, in
addition to the Tailscale share. A new Settings switch, **Open on my
local network**, sits next to **Open from my other devices**. A short
warning is always visible beside it: "Anyone on the same network can
use Caravan, and there is no login." When the switch is on, the status
line shows the address to open (`http://<lan-ip>:<port>`).

The same choice is available from the command line: `caravan lan on`,
`caravan lan off`, and `caravan lan status` (status prints the
address). A fresh install asks, with No as the default:

Open Caravan on your local network? (y/N)

and shows the same warning. Updates never ask. The option is off by
default. When it is off, the page stays only on this Mac. Uninstall
turns it off before files are removed. Turning the switch on or off
does not unload a model that is already loaded; the page comes back
in a few seconds.

This follow-up is only tools, proxy, scripts, tests, and docs — not
`agent/`, `runtime/`, or the requirements files — so a `caravan
update` from the previous Day 24 pin keeps a loaded model running.
The web page still restarts. The portable suite on a fresh clone on
the development node: **1,396 tests passed** in 56.919 s.
The 1st node and 2nd node were not touched. No `day24` tag yet.
Source and pin SHAs are recorded at publication time.

