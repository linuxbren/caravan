# Days 1–16 archive audit

Audit date: 2026-11-06 (America/Chicago). Scope: history before Day 17 on
`caravan-v3-mlx-split`; no code changes, model activity or service restarts.

The code and most narratives/videos were already committed. A missing
`docs/DAYN.md` does not mean a missing day: historically the diary was
`handoff/lab/experiments.md`, with detailed tables in `docs/BENCHMARKS.md`,
`docs/LOG.md`, `docs/CHANGELOG.md`, per-experiment lab folders, and
`handoff/lab/videos/index.md`. Only Day 17 used `bench/results/dayN` at audit start.

## Per-day accounting

“Added” below refers to this closeout, not newly performed experiments.
All seven pre-Day-17 Obsidian day notes are preserved byte-for-byte under
[obsidian/](../handoff/lab/pre17-closeout/obsidian/).

| Day | Already in repository | Added / recovered now | Remaining limitations |
|---|---|---|---|
| 1 | Oct 30 runtime compare/v1 diary, BENCHMARKS; `handoff/lab/bench-2026-10-30`; videos v1–v4, scripts and data | Obsidian `Day 1 Results.md` | EXO1 Oct 30 bench directory no longer present; use committed raw files and note, not a fabricated rerun |
| 2 | Early MLX/v2 story in Oct 30–31 diary and BENCHMARKS | Obsidian `Day 2-6 Early Experiments.md` | That note calls v2 “Day 2”, but v6/video index calls it “Day 3”; retain both source labels, do not silently renumber |
| 3 | v2/v2.1 diary, benchmark tables; v5/v6 data/scripts and videos | Same early-experiment note, cross-day source manifest | EXO1 Oct 31 raw v2/v2.1 directories absent; no distinct Day 3 Obsidian note |
| 4 | v3 split, LPM rerun, cable/GPU-wait experiments; v7/v8 videos | EXO2 surviving v3.1 packer logs; box overhead JSON, probes and rejected overlap/compile notes; early note | No live 3+ Mini benchmark; missing EXO1 old raw dumps are not reconstructed |
| 5 | Uneven cuts and keepalive diary/BENCHMARKS; v9 video | EXO2 uneven-cut/split-tax logs; box keepalive JSONL, microbench, lead logs and probe sources; early note | Original prompts/settings/commit retained only where source records them |
| 6 | Pipeline/fairness stall-fix diary and tables; v10–v12 videos | Surviving packer logs, box original run scripts/failed-run log and plan; early note | Old EXO1 pipeline result dumps absent; aggregate tables remain |
| 7 | Guess-ahead diary/quality gate, BENCHMARKS; v13 video | Surviving EXO1/EXO2 speculate, speculate2, strict/guess-ahead/download-test logs, results and scripts | No separate Obsidian day note; retain rejected/failed modes without promotion |
| 8 | Llama/Qwen2.5/Distill suites and scoreboard diary; v14/v15 videos | Surviving full-suite, download and packer artifacts | No separate Obsidian day note; no new performance claims |
| 9 | Auto-settings diary/BENCHMARKS; v16 video | Surviving autotune results, driver/start scripts and worker logs | No separate Obsidian day note |
| 10 | Learn-from-chats diary, all-model scoreboard, `day10-learn-results`, drivers; v17a video | Surviving driver/worker logs and historical tuned-settings; v22 cross-day recap assets | Source metadata preserved as recorded; no hindsight commit IDs assigned |
| 11 | Same learn-from-chats run/quality-fix section; v17b alternate video | Same recovered learn-run provenance and cross-day recap | Numbering is shared Day 10–11 in v22; no separate Day 11 experiment/note recovered |
| 12 | `day12-speedups`, `day12-fused`, original orchestrators, diary; v18–v20 and remeasure data | Obsidian Day 12 note; surviving EXO1/EXO2 raw logs/results/scripts not already tracked | Duplicates reuse their existing repository path in manifest |
| 13 | `day13-gemma-prefix`, `day13-spc-learn`, diary and v21 video | Obsidian Day 13 note; surviving packer logs/start script | Shared-prefix off/on and negative results unchanged |
| 14 | Diary explicitly planned a break and v0→now recap; v20 already tracked | Previously untracked v22 MP4, renderer, JSON data and eight stills (Day 1–13 recap) | No independent Day 14 benchmark or Obsidian day note recovered; do not invent one |
| 15 | Web/picker/topology/memory work, docs WEB/MODEL_PICKER/CHANGELOG, `day15-web/RESULTS.md`, screenshots and chat JSON | Both Obsidian Day 15 notes; six untracked EXO1 bug-reproduction files, identical paths also present EXO2 | `proxy/web/index.html.bak-pre-amber` is a source backup, deliberately not imported over active UI |
| 16 | `898ce42` through `726b468`, subsequent model-label/Meadow/Nebula fixes through `b8a232f`; diary and changelog | `docs/DAY16.md`, Obsidian Day 16 note, two tour videos, eight stills and caption draft | Exact benchmark prompts/traces, fake-config temporary shots and tour generator not recovered; see Day 16 record |

## Provenance / recovery method

[manifest.json](../handoff/lab/pre17-closeout/manifest.json) lists every captured
source path, byte length, SHA-256 and repository destination, including files
already committed. Hash-identical files are linked to the existing copy rather
than duplicated. Newly recovered raw sources are under
[raw/](../handoff/lab/pre17-closeout/raw/) grouped by originating machine and
original relative directory. Failed/poisoned/interrupted results and logs were
kept, not filtered to winners. Original result JSON/JSONL and scripts retain
whatever model, prompt, settings, timestamp and commit metadata was recorded.
**Missing historical metadata is unknown**, not inferred from today's HEAD.

Examined: box `/workspace/caravan` status/tracked files and `/workspace` videos,
`/workspace/caravan-notes` raw results/archives; both Mini checkouts and surviving
`~/.caravan/bench-*` sources; Omarchy Obsidian day notes. EXO1 had surviving Nov
1–3 raw source directories; EXO2 had Oct 31 and Nov 1–4 sources. Existing Oct 30
repo raw files remain the source for that day. This is an archive of recoverable
small text/data artifacts, **not a claim that every original runtime dump exists**.

Excluded intentionally: Day 17; model weights, KV/slot/MLX cache payloads,
credentials; unrelated source-code backup snapshots and obsolete Git bundles (historical benchmark instruments retained); generated
Python bytecode; log/text files at least 2,000,000 bytes. Existing MP4 convention
is ordinary Git: tracked lab videos are roughly 1–4 MB, no tracked LFS attributes.
The three newly archived MP4s are each under 5 MB (well below the requested 50 MB
review threshold). Ignored historical log/text artifacts were added explicitly to keep the manifest complete; no size limit was overridden.

## Verification

Archive validation checks manifest hashes and sizes, parses JSON/JSONL where
applicable (pre-existing malformed artifacts are reported, not rewritten), and
probes the three newly committed MP4s. No model benchmark was rerun and no test
number from Day 17 is assigned to an earlier day. See `validation.json` beside
the manifest for exact archive-check results.

Archive check totals: **688 source entries**, **608 unique destinations**,
**283 successful JSON/JSONL source checks across 213 unique files**, zero hash,
size or JSON parse failures. The original archive commit contains all manifest
destinations; it adds/updates **548 files** including documentation and media.
