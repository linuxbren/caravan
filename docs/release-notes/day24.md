# Day 24 (Nov 12 2026)

Published Nov 12 CST. No development-day tag yet; that waits for live review.

## Changed
- Settings: Self-tuning stays visible. Other optimizations, Optimize now,
  and Apply & restart sit under a closed Advanced section. Self-tuning
  On/Off takes effect immediately on a loaded MLX model, without a reload.
  After a self-tuning or Optimize now run, that model's starting and ending
  speed is shown in Self-tuning, for example "Before: 31 words/s, first
  word in 2.1 s. After: 42 words/s, first word in 1.2 s."
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
  ("Average 42 words/s, first word in 1.2 s"). The title is Caravan; the
  line under the mark is "Your Macs. One model."

## Operational checks
- Portable suite results are recorded at publication time in DAY24.md and
  the Obsidian Day 24 note.
- The 1st node and 2nd node were not changed for this publication.
  Update them with `caravan update`. A loaded model is reloaded because
  model-running code changed; the same model is restored.

Details: [DAY24.md](../DAY24.md). Install: [INSTALL.md](../../INSTALL.md).
