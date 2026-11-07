# Day 16 — web interface closeout

Recorded 2026-11-06 (America/Chicago). Branch: `caravan-v3-mlx-split`.
This is a historical record, not the current feature/status report. Day 17 is excluded.

## What shipped

| Commits | Work |
|---|---|
| `898ce42` | N-node Topology cards; remote single-Mini start and SSH tunnel; self-tune uses `:single`; ignore cache folders in model sizes |
| `e66af4c`, `f5359d5` | Adopt single workers correctly; route `/api/nodes`; skip shared-prefix trials in single-Mini Quick |
| `0ef8db8`, `28a895f` | Load EXO2-only inventory; ignore stale local worker log while awaiting remote health |
| `726b468` | Original Day 16 lab diary |
| `e42a945`, `8d3b6ee` | Guard removed legacy node elements; per-node model labels and ready-model empty state |
| `bede2d2`, `b98befe` | Meadow theme, Settings/phone layout; “To first token” wording |
| `4ce57be`, `bb3f8a5`, `ed91b06`, `1dd0102`, `b8a232f` | Nebula theme, Cosmic Cliffs imagery/assets/credit, phone overflow and credit placement |

The earlier web UI, picker and placement work belongs to Day 15. The Day 16 tour
shows that accumulated interface. At this snapshot the web UI did **not** split
GGUF models; MLX splitting had a two-stage implementation limit. Configured node
counts and inventory/topology were N-node, not proof of an N-stage split runtime.

## Recorded verification (not re-run for this archive)

Source: [original Obsidian Day 16 note](../handoff/lab/pre17-closeout/obsidian/Day%2016%20Results.md)
and the opening Day 16 section of [experiments.md](../handoff/lab/experiments.md).

- Deep optimize was reading `:spanned` for a `:single` worker: coverage stayed
  0/3 across 30 prompts. After fixing the key: KV 16/8/4-bit sample counts
  **46/12/3**, fuse-off **61**, **one reload in about 4.8 seconds**; Cancel left
  the model ready. These are coverage observations, not speed claims.
- Single-Mini Quick had no applicable live options: missing coverage **0**,
  finished immediately, Cancel worked.
- `mlx-community/Qwen3-0.6B-4bit`, EXO2-only: worker ran remotely through SSH
  forwarding to port 8194, chat first token **0.111 seconds**; remote model path
  checked. Test model removed and JevK5 restored on EXO1.
- Restored JevK5 chat MLX 4-bit: single worker, first token about **0.14 seconds**,
  writing about **38 tok/s**. Both nodes online, approximately **5% CPU** each.
- Fake 1-node browser configuration: **1 card**. Fake 3-node configuration with
  middle node offline: **3 cards, 1 offline**. Unit source:
  `tests/test_topo_n_nodes.py`. These were simulations; live hardware was two Minis.
- Known issue at that point: cancel during reload could drop the worker until a
  reload; single-Mini shared-prefix explore statistics empty. Node-label freshness
  was subsequently addressed by `8d3b6ee`.

Exact prompts, seeds, raw traces and a full test-suite total were not present in
the recovered Day 16 note; they are not reconstructed. Temporary fake-topology
shots originally under `/tmp/topo-fake/` were not recovered in this audit.

## Video / screenshot archive

[Day 16 assets](../handoff/lab/pre17-closeout/day16/) contains both original and
Meadow tour MP4s, all eight recovered stills, and `d16.txt` (a draft caption,
**not a publication record**). Both videos are under 5 MB; existing lab MP4s use
ordinary Git, with no tracked `.gitattributes`/LFS policy. They are kept unchanged.
The “now in Meadow” caption question remains an editorial question; this archive
neither edits nor posts it. Generation scripts were not recovered for these tours.

See [Days 1–16 audit](DAY1-16-AUDIT.md) for the source manifest and historical gaps.
