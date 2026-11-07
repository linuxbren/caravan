# Compile-each-half prototype attempt (Oct 31 2026, ~9:05–9:10 PM CDT)

## Goal
Wrap each stage forward (`Stage.front_forward` / lead `run_layers`+`logits`) in `mx.compile` (shapeless) so the Metal graph is built once per half and reused every decode step.

## What we tried (mlx 0.32.4)
1. `@partial(mx.compile, shapeless=True)` on a no-cache layer stack for Gemma 4 packer half.
2. Same for a single layer with an explicit mask arg.
3. `@partial(mx.compile, inputs=cache_state, outputs=cache_state, shapeless=True)` around `run_layers` with live KV/RotatingKV caches.
4. Repeated on Qwen3 30B packer half.

## Results — could not enable compile
All attempts raised before a usable compiled forward existed:

- `ValueError: [Primitive::output_shapes] Slice cannot infer output shapes.`
  (attention / sliding-window mask path; also with cache=None)
- `ValueError: [compile] Attempting to compile a function with uncaptured inputs is not allowed.`
  (module weights / cache objects captured via closure but not listed in `inputs=`)

No split writing benchmark was run for this prototype: there was no working compiled path to compare to the even-cut baseline (Gemma 27.6 / GPT-OSS 26.8 / Qwen3 30.0). Quality N/A.

## Why (evidence)
These models update dynamic KV caches and build masks with data-dependent slices. `mx.compile` needs fixed/inferable shapes and explicitly captured array inputs. Making that work would mean rewriting the stage forward to pass every weight and cache tensor as plain `mx.array` args with fixed decode shapes — not a small wrap. mlx_lm itself only compiles small helpers (e.g. residual clips), not the full decode step with cache.

## Patch
No code change was left in the tree. This note is the record of the attempt. Helper smoke lived only in ephemeral `python -` sessions.
