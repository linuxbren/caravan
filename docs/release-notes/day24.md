# Day 24 (Nov 12 2026)

Published Nov 12 CST. No development-day tag yet; that waits for live review.

## Changed
- Settings: Self-tuning stays visible. Other optimizations, Optimize now,
  and Apply & restart sit under a closed Advanced section. Self-tuning
  On/Off takes effect immediately on a loaded MLX model, without a reload.
  After a self-tuning or Optimize now run, that model's starting and ending
  speed is shown as two lines, for example "Before · Write 88.4 tok/s ·
  first token 0.29s" and "After · Write 94.5 tok/s · first token 0.15s",
  using the same wording as the reply stats. The same two lines also
  appear next to the control that produced them (Optimize now when that
  was the source). The slots are reserved so Settings does not jump.
- Models: the Reasoning filter is renamed Thinking. Default chips are Chat,
  Coding, Thinking, Tools, and Vision. Specialized types stay available
  behind Advanced, so Caravan can sit between an agent app and a model.
  A Family menu, a fits-on summary that says Macs, a clearer row hover
  (maker, date, context, capabilities), and one progress card per download
  with a consistent friendly Mac name.
- Topology: Balance and Thunderbolt stay collapsed until clicked. Balance
  status is quiet plain text: already applied, not safe to apply, or ready
  to apply a new split.
- Chat: Clear chat is renamed New session. Option chips sit in a Current
  optimizations box, in Settings order, with Self-tuning first. The
  Specifications box is replaced by a quiet average under the input
  that uses the same wording as the stats under each reply, with a
  leading Average label ("Average · Read 165 tok at 200 tok/s · Write
  10 tok at 20.7 tok/s · first token 0.34s · total 0.78s"). Fields
  with no data yet are left out. The title is Caravan; the
  line under the mark is "Your Macs. One model."
- Models, live review: a download of any repo with no top-level
  `config.json` (image, video, text-to-speech, speech-to-text/ASR, or
  another non-LLM layout) now fetches the whole tree, including
  subfolders. Advanced types stay downloadable, with a quiet "Download
  only, Caravan can't run image models yet" line (and the same shape for
  video and speech — including speech-to-text — as well as embedding,
  Decision, and any-to-any). After download, Load is not offered.
  Download cards use friendly Mac names and a short plain error
  ("Download stopped. Press Resume to try again."); traces, hostnames,
  and internal ids stay in the log.
- Load, live review: after an update that keeps the model, the web page
  restarts and may leave Caravan's SSH forward in place. The next load
  reuses that forward when it still works, or stops only that process
  and opens a new one when it does not. A process that is not Caravan's
  is never killed. Unload, a model switch, a web stop that stops the
  workers, and an update that reloads workers clean up Caravan's own
  forwards. Load status says "2nd Mac" (never a hostname or a file
  path). If a tunnel error still happens, the page shows "Couldn't
  start the model on the 2nd Mac. Try loading again." and the full
  detail goes to the log.

- GGUF, live review: the web Load path now uses flash attention,
  automatic memory compression (16-bit or 8-bit only, never 4-bit),
  a default prompt batch, and saved slots. Settings shows the matching
  rows (Self-tuning, Memory compression, Shared start, Flash attention,
  Prompt batch) with plain-word hints, hides Fused kernels and GPU
  keep-warm, and keeps Guess-ahead and Prompt lookup off. Optimize now
  (and self-tuning) compares 16-bit vs 8-bit memory compression and
  scores read speed, first-token time, and write speed. The two Before
  and After lines work for GGUF too.
- Self-tuning and Optimize now, live review: a trial that stops (for
  example a Memory compression trial whose measurement is rejected)
  shows a short plain reason next to Self-tuning, and under Optimize
  now — not only "stopped (error)" in the closed Advanced section, and
  not a raw request error. Friendly Mac names only; no hostnames or
  paths. The full detail goes to the log only.
- Tune again, live review: the button sits next to Self-tuning, outside
  Advanced, labeled Tune again, with Reset tuning beside it. Pressing it
  always runs a fresh trial on the loaded model; you do not need to
  remove or redownload the model. If nothing is faster, Settings shows
  one line ("Already at its fastest settings. Nothing faster found.")
  instead of two identical Before and After lines. The conflicting
  "now: off" next to On is gone. The Self-tuning hint is for each
  model, not only MLX.
- Auto-tune, live review: Tune again and Reset tuning move out of the
  Self-tuning block into a new Auto-tune section, still outside
  Advanced, with a heading, a hint, an indented button block, and the
  Before and After lines (or the one-line "already fastest" message).
  Auto-tune works whether Self-tuning is On or Off. The page and docs
  say Auto-tune where they used to say Optimize now; the API routes
  are unchanged.
- Campfire, live review: Campfire replaces Nebula in the theme switch
  (Amber, Green, Meadow, Campfire). It is a cool night sky with a
  soft moon, crisp stars, a dark tree line, and a campfire glowing
  low, drawn in SVG and CSS with no photos. Frosted dark panels and
  amber accents; the text stays readable. A saved Nebula choice opens
  as Campfire. The Webb image and credit are removed.
- Auto-tune Start, live review: the primary button says Start when
  the loaded model has never been tuned, and Tune again once a result
  is saved. After Reset tuning it says Start again. The action is the
  same fresh trials either way. The rest of the Auto-tune layout is
  unchanged.
- Local network, live review: an **Open on my local network** switch
  sits next to the Tailscale option in Settings, with the warning
  "Anyone on the same network can use Caravan, and there is no login."
  `caravan lan on|off|status` does the same; status prints the
  address (`http://<lan-ip>:<port>`). A fresh install asks, default
  No. Off by default; when off, the page stays only on this Mac.
  Uninstall turns it off. Toggling does not unload a loaded model.

## Operational checks
- Portable suite results are recorded at publication time in DAY24.md and
  the Obsidian Day 24 note.
- The 1st node and 2nd node were not changed for this publication.
  Update them with `caravan update`. From the Day 23 pin, a loaded model
  is reloaded because model-running code changed; the same model is
  restored. A later live-review follow-up (the chat average line matching
  reply stats) does not change model-running code, so an update from the
  first Day 24 pin keeps a loaded model running. A later live-review
  follow-up (image-repo fetch, download-only honesty, and plain download
  errors) changes `agent/mlx_split_fetch.py`, so a `caravan update` from
  this pin reloads a loaded model; the same model is restored. A later
  live-review follow-up (two-line before/after in tok/s, shown under
  Self-tuning and by the button that produced the result) does not
  change `agent/`, `runtime/`, or the requirements files, so an update
  from that pin keeps a loaded model running. The web page still restarts.
  A later live-review follow-up (reuse or replace Caravan's leftover
  SSH forward after a web restart, plain load errors, and friendly
  Mac names on load status) does not change `agent/`, `runtime/`, or
  the requirements files, so an update from that pin keeps a loaded
  model running. The web page still restarts.
  A later live-review follow-up (GGUF Settings rows, trusted web load
  flags, and Optimize now scoring of read speed and first-token time
  as well as write speed) does not change `agent/`, `runtime/`, or
  the requirements files, so an update from that pin keeps a loaded
  model running. The web page still restarts.
  A later live-review follow-up (Self-tuning and Optimize now errors
  show a short plain reason next to Self-tuning; full detail in the
  log only) does not change `agent/`, `runtime/`, or the requirements
  files, so an update from that pin keeps a loaded model running.
  The web page still restarts.
  A later live-review follow-up (Tune again next to Self-tuning, a
  fresh trial every press, one line when nothing is faster, and a
  generic Self-tuning hint) does not change `agent/`, `runtime/`, or
  the requirements files, so an update from that pin keeps a loaded
  model running. The web page still restarts.
  A later live-review follow-up (Auto-tune section, independent of
  Self-tuning On or Off, Before and After only in Auto-tune) does not
  change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (Campfire replaces Nebula; Auto-tune
  says Start until this model has been tuned, then Tune again) does
  not change `agent/`, `runtime/`, or the requirements files, so an
  update from that pin keeps a loaded model running. The web page
  still restarts.
  A later live-review follow-up (opt-in local-network access next to
  Tailscale, with a warning that anyone on the same network can use
  Caravan and there is no login; `caravan lan on|off|status`; install
  question default No; off by default; uninstall cleans it up;
  toggling keeps a loaded model) does not change `agent/`,
  `runtime/`, or the requirements files, so an update from that pin
  keeps a loaded model running. The web page still restarts.

Details: [DAY24.md](../DAY24.md). Install: [INSTALL.md](../../INSTALL.md).
