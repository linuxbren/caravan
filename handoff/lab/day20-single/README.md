# Day20 single versus split evidence

Read `docs/DAY20.md` (repo root) for full interpretation, failures and safeguards.
`matrix.csv` is normalized metrics; `matrix.md` is the paired view. Never call
failed Huihui full or Astrea's empty-visible short medium output a successful
reply. `raw/paired-input-output-proof.json` verifies the8 new-model medium
pairs. Supplemental Astrea thinking-none short pairs also match input hash/output.

Only explicit successful source rows form the tables. Invalid identity controls,
namespace/storage rejections, original GPU OOM log and invalid monitor are kept
for honesty. `memory-watch-real.jsonl` is valid; `memory-watch.jsonl` is NOT.
Huihui split reference predates this phase; original timestamps are preserved.
Text diagnostic logs have normalized line endings/trailing blanks; JSON metrics
are retained. No private full system/tools payloads or model weights are included.

`bin/` retains actual lab scripts, including aborted controls for audit. Use
strict current control.py and normal stop.py, not the old run-pairs.sh sequence.
These are Omarchy-specific operational helpers, not production automation.
Always stop/release the previous model, require actual loaded identity and
restore Huihui24/40 even on failure. Helpers assume the same frozen private
prefix available locally via ~/day20-single/private; do not regenerate it and
pretend it is the same dataset. All model loads used existing normal safety guards.
