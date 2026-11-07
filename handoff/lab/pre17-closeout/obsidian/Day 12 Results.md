---
title: Caravan Day 12 results
tags: [caravan, benchmarks, day12]
created: 2026-11-04
updated: 2026-11-04
---

# Day 12 — five easy speedups (Nov 3, split across two Minis)

Back to [[Projects/Caravan/Caravan]]. Commit `e652708`. Video v18 (1:25).

| Idea | Result | Verdict |
|---|---|---|
| Shared start of chats (`--split-shared-prefix-cache`) | New chat with same ~4k system prompt: Llama 17.5 → 8.9 s, Qwen3 9.3 → 5.0 s to first word. Gemma no gain (packer reuse mismatch) | Go, off by default until Gemma's packer trim is fixed |
| Guess-ahead, one chat | Llama 22.6 → 49.7 (+120%), Qwen3 45.4 → 59.0 (+30%); Gemma ~+2% (skipped, inconsistent) | Go |
| Two chats + guess-ahead | Total fell: Llama 39.4 → 19.0, Qwen3 72.5 → 24.9 (guesses accepted dropped to 0.09–0.27). Two chats alone still ~1.6–1.8× | No-go |
| Look-back per message | Qwen3 copy-text 62 → 66, hurt one code prompt | Mixed, off by default |
| Fused kernels | ~0% on one Mini and on the split (MLX already fuses the easy ones) | Parked |
| Built-in guesser (MTP) | 0/6 of our models ship one | Blocked, waiting on e.g. Qwen3-Next |

Sources: `handoff/lab/day12-speedups/`, `handoff/lab/day12-fused/`, experiments.md Day 12.
