# Cleanup inventory — keep everything for now

The owner chose to **keep all listed clutter for now**. This is an inventory,
not approval to archive or delete anything. Only the C++ experiment has been parked, at `docs/history/cpp/`. Nothing listed
below has been moved or removed. Sizes are **tracked working-tree bytes**, not
Git history size, model storage, or guaranteed space savings. Deleting a tracked
file does not shrink old Git history; no history rewrite is proposed.

| Candidate | Files | Bytes | Why review it / caution |
|---|---:|---:|---|
| `handoff/lab/videos/` | 225 | 81,995,502 | Render/edit assets and duplicate screenshots dominate the repository. Archive approved source assets separately from current docs; preserve published evidence and original source projects. |
| `handoff/lab/pre17-closeout/` | 528 | 13,319,333 | Captured raw logs/results, with personal machine paths and redundant experiments. Park as a historical dataset after checking links and provenance. |
| `handoff/lab/day15-web/` | 22 | 4,495,934 | Old browser mockups/captures; not the served app under `proxy/web/`. Keep a representative screenshot and linked evidence before parking the rest. |
| `handoff/lab/bench-2026-10-30/` | 276 | 2,171,139 | Old benchmark dumps, scripts and environment-specific paths. Preserve cited results/methodology; archive rather than treat as maintained tools. |
| `handoff/lab/v19-remeasure/` | 60 | 131,847 | Repeated scripts/results, including nested copies. Compare hashes before deduplicating; filenames alone do not prove duplication. |
| `handoff/lab/day10-all-models-scoreboard.json` and the copy under `day10-learn-results/` | 2 | 19,450 | Same-sized historical scoreboard copies; verify content and links before choosing one canonical copy. |
| `launchd/com.caravan.llama-server.plist` + `com.caravan.rpc-server.plist` | 2 | 3,670 | Legacy manual-role examples, not installed by the new package. **Not clearly unused:** renderer tests, config docs and `scripts/restart-rpc-server.sh` still reference them. Audit those consumers before parking; do not remove the active renderer/runtime. |

The whole `handoff/lab/` tree is 1,586 tracked files / 106,649,512 bytes. Table
rows are subsets, **not additive** to that total. `bench/` is 113 files /
1,560,540 bytes and contains methodology/tooling as well as old results; a
blanket deletion is not recommended. Current `docs/history/` is intentional
history, not automatically clutter. No model files, live services, private keys,
or machine checkouts belong in this cleanup.

Approval should name the exact paths and whether to archive, deduplicate or
remove. Refresh these counts at that point; concurrent development can change
them. Never rewrite repository history just to make a source download smaller.
