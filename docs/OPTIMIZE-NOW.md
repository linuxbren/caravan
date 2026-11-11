# Optimize a model

**Optimize now** runs real comparisons to find settings that help the loaded
model on the participating Macs. It is not a synthetic progress animation or
a guarantee that every model gets faster.

## Before starting

- Load the intended model and confirm a normal reply works.
- Finish important chats; trials can reload the model and take time.
- Leave the participating Macs available and avoid unrelated heavy workloads.
- Keep the model, prompts, placement and power settings consistent when comparing.
- Use only supported one-/two-stage paths. Do not Optimize an N-stage Balance
  load; broader optimization support is still limited.

Use the UI's progress, Pause and Cancel controls. Tests distinguish prompt
reading, token generation and end-to-end chat delay. Only a supported winner
should be retained; no winner is a valid result. A good result on one model or
workload does not prove the same result on another.

## Settings and safety

MLX and optional GGUF use different tuning paths. Not every model supports
compressed chat memory, guess-ahead or a proposed setting. Unknown capacity,
missing files, load failure or changed topology should stop a trial safely.
Do not bypass a guard or delete active files to make a run appear successful.
The ordinary chat path must remain usable after a cancelled/failed trial.

Saved results are scoped to model/hardware configuration; current runtime
settings and defaults are described in [CONFIGURATION](CONFIGURATION.md).
Use [the measurement method](METHODOLOGY.md) for repeatable comparisons and
report negative results too. Current limitations are in [ROADMAP](ROADMAP.md).

Detailed implementation review, real deployment measurements and unsuccessful
runs remain in [the optimization development record](history/OPTIMIZE-NOW-LAB.md).
