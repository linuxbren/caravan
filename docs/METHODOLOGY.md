# Measure Caravan fairly

Use the same model, quantization, prompts, generation length and settings for
both sides of a comparison. Measure real serving behavior, not test-suite speed.
See [node names](README.md#names-used-in-these-guides) for older logs.

## Prepare and record

1. Commit the source under test on the development node. Sync intended Mac
   checkouts with fast-forward-only pulls; preserve local changes and record SHA.
2. Record every participating Mac's chip, operating system, available resources,
   power mode, connection type and selected placement. Do not assume equal Macs.
3. Use unused ports and a separate test plan. Do not interrupt a production model
   or another person's experiment. Reboots/SSH trust changes require approval.
4. Keep load, warm-up, cold prompt, warm follow-up and writing times separate.

`lead-mac` and `helper-mac` are example SSH names that you configure yourself.
Use actual paths/endpoints from your own inventory, never a prior lab address.
Prefer the normal UI load path so placement and ownership checks remain active.
When testing low-level split workers, start the earlier helper stages before
later stages/the lead and use matching counts; see [MLX-SPLIT](MLX-SPLIT.md).

## Quality before speed

Compare outputs and completion reasons. Reject garbled, truncated, changed or
failed output rather than reporting a misleading fast number. Check session
cache identity, model compatibility and ordinary chat after each setting change.
A correct short smoke does not prove maximum-context or sustained reliability.

Use several prompt types: prose, code, repeated text and ordinary assistant
conversations. Prompt lookup can favor repetition and lose on mixed prompts.
Speculative decoding needs a compatible matching model/helper; one model's
result cannot be generalized to another family.

## Repeatable speed runs

- Use independent matching cold and warm runs; label cache state explicitly.
- Include prompt-reading time and time to usable/visible reply, not only tokens/s.
- Repeat each condition, alternate order to limit temperature/cache bias, and
  report medians plus spread, failures and cancelled runs.
- Compare engines through their own server endpoints with the same external
  timer and equivalent workloads. Keep server queues and client overhead visible.
- Keep each request's raw timing/usage and exact parameters. Redact credentials,
  private chats, real user paths and addresses before sharing records.

Measure on actual participating Macs. Socket simulations and unit tests prove
logic, not GPU throughput or three-or-more-Mac scaling. Do not turn a favorable
single run into a general speed promise. Stop only the owned test processes;
leave unrelated services and model files alone.

Original commands, guess-ahead family trials and specific lab observations are
preserved in [the earlier measurement runbook](history/METHODOLOGY-LAB.md).
