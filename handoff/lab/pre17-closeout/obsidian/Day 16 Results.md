---
title: Caravan Day 16 results
tags: [caravan, day16, web-ui, topology, self-tune]
created: 2026-11-06
updated: 2026-11-06
---

# Day 16 — Topology N-node, self-tune verify, non-lead load (America/Chicago)

Back to [[Projects/Caravan/Caravan]]. Day 15 closeout (picker / placement / `d60c983`) is in [[Projects/Caravan/Day 15 Results|Day 15 Results]].

## Shipped (commits on `caravan-v3-mlx-split`)

| Hash | What |
|---|---|
| `898ce42` | Topology N-node cards; remote single-Mini start+tunnel; optimize `:single` key; skip `caches` in disk sizes |
| `e66af4c` | Adopt sets `split=false` for `--split-role none` |
| `f5359d5` | Wire `GET /api/nodes` (was 404); skip `shared_prefix` in single-Mini Quick |
| `0ef8db8` | Load from N-node inventory (EXO2-only placements) |
| `28a895f` | Remote wait ignores stale local `lead.log` |

## Topology
- Drawer builds one Mac mini card per configured node from `/api/nodes`
- Handles 1 / 2 / 3+ and offline (unit tests: `tests/test_topo_n_nodes.py`)
- Live: EXO1 + EXO2 both online; CPU ~5% each after restore

## Self-tune / Deep / Quick
- Bug: Deep/Quick read `:spanned` while JevK5 ran `:single` → coverage stuck at 0/3 for 30 prompts
- After fix: Deep showed **kv_bits 16-bit have=46, 8-bit=12, 4-bit=3**, fuse off=61; **1 reload in ~4.8 s**; Cancel left model ready
- Quick on single Mini: live options unavailable → coverage missing=0, done immediately; Cancel OK
- Open: cancel mid-reload can briefly drop the worker (recovered by reload); shared_prefix stats still empty on non-split explore

## Non-lead single Mini
- Placed `mlx-community/Qwen3-0.6B-4bit` on EXO2 only; load started worker on EXO2 + SSH `-L 8194`
- Chat via tunnel: ttft **0.111 s**, model path on EXO2 confirmed in remote log
- Reverted: removed EXO2 copy; JevK5 4-bit back on EXO1

## Caches ghost
- `~/.exo/models/caches` filtered via `_looks_like_model` in `picker_disk_sizes.py` (and existing inventory SKIP)

## Polish found
- `/api/nodes` was never routed (404) — fixed
- Adopt marked single as split — fixed
- Topology can show previous model name until next gather — minor
- Chatterbox incomplete folder briefly selectable earlier in Day 15 stretch — out of scope here

## Left loaded
**JevK5 chat mlx 4bit** on EXO1, `--split-role none`, web `:8190`, lead `:8194`. Chat ttft ~0.14 s, ~38 write tok/s.

## Browser fake configs
- 1-node fake `/api/nodes` → **1** Topology card (`Lead · EXO1`)
- 3-node fake (middle offline) → **3** cards, **1** `.offline` (`Packer 1 · EXO2`)
- Shots: `/tmp/topo-fake/topo-1node.png`, `topo-3node.png`
