# Day 12 Idea 2 — Per-message adaptive prompt-lookup

**Setup.** Same split models; helper draft on; adaptive adds `--split-prompt-lookup 3 --split-prompt-lookup-adaptive`. Suite prompts: count / repeat / code_edit / code_cont. Quality 3/3.

**Helper-only vs adaptive (write tok/s medians)**

| Model | Mode | count | repeat | code_edit | code_cont |
|---|---|---|---|---|---|
| Llama | helper | 51.3 | 51.4 | 64.4 | 46.5 |
| Llama | adaptive | 51.4 | **53.1** | 64.7 | 46.6 |
| Gemma | helper | 43.9 | 46.2 | 44.6 | 37.8 |
| Gemma | adaptive | 41.0 | 46.6 | 43.5 | 36.9 |
| Qwen3 | helper | 59.1 | 62.0 | 71.2 | 57.5 |
| Qwen3 | adaptive | 59.2 | **66.2** | 72.0 | 35.6 |

**What worked.** Gate + mid-turn `note_context` engage PL on true echo: Qwen3 repeat **+6.8%** (PL hits, accept ~0.88); Llama repeat +3.3%. Normal count stays flat when overlap stays low (Llama/Qwen3).

**What hurt.** False-positive `force_on` (overlap threshold 0.25) on Gemma count (−6.6%) and Qwen3 code_cont (−38%) when PL accept stayed poor. Defaults tightened after the run to `overlap_on=0.50`, `window=4`, and low accept overrides force_on. Flag remains **off by default**.

**Verdict.** Prototype **lands behind `--split-prompt-lookup-adaptive`**; not a blanket ≥5% win. Re-bench with tighter defaults before calling GO. Helper-only remains the safe default for split guess-ahead.

Raw: `~/.caravan/bench-2026-11-03/day12-speedups/idea2/` on EXO1 (v1 poisoned / v2 threshold archives kept).
