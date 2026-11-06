# Model picker

The **Models** drawer on the web UI (EXO1 `:8190`) is how you search, check
fit, download, and delete models. It docks on the left like Topology so chat
stays usable. Phases 1–2 are live on `caravan-v3-mlx-split`; later phases are
listed at the end.

Code: `proxy/web_picker.py`, `proxy/web_nodes.py` (config-driven node list),
`proxy/web_server.py` (`/api/picker/*`), `proxy/web/index.html` (drawer),
`proxy/picker_disk_sizes.py` (on-disk sizes / cleanup),
`agent/mlx_split_fetch.py` (split-aware shard download).

## Design decisions

### Drawer and sources

- Own left drawer, mutually exclusive with Topology.
- **HF / MLX** — `mlx-community` first; other HF repos that look convertible
  (safetensors / transformers). Marked `needs_conversion` when not already MLX.
- **Ollama (GGUF)** — Brenden’s “Ollama” means llama.cpp / GGUF. Catalog from
  Hugging Face publishers `bartowski`, `unsloth`, `lmstudio-community`. Runs on
  **one Mini for now**; GGUF split across Minis is later (llama.cpp RPC).
- **Ollama Cloud** — static labeled list (`CLOUD`). Shows as green fit (token
  use, not Mini RAM). Key framework only (`OLLAMA_API_KEY`); untested live.

### Fit colors

| Color | Meaning |
|---|---|
| green | Fits on 1 Mini with comfortable margin |
| yellow | Tight on 1, or needs 2+ Minis |
| red | Won’t fit (or disk blocks) |
| gray | Size unknown — never treated as OK |

Reasons are plain English on the row and in the quant tooltip, e.g.
“Fits on 2 Minis, about 10 GB RAM each (capacity ~16 GB)” or
“Not enough disk on EXO1 (need ~15.0 GB, 12.0 GB free)”.

### Capacity-based fit (why not free RAM)

Fit used to read each node’s `ram.available_gb` — free RAM **right now**. With
Qwen3 30B loaded, EXO1 often shows ~8–11 GB free even though unloading the
worker would free ~9 GB more. That made a ~15 GB MLX coder look “tight on 2
Minis” when the real limit was current free RAM, not unload capacity.

**Now:** each Mini’s capacity is roughly
`available_gb + (active_gb or weights_gb)` (what frees when the current worker
unloads), compared with `total_gb − OS_BASELINE_GB` (default 4 GB). The more
conservative of the two is used. Need ≈ weights + rough KV + `memory_safety_gb`
(default 1.75). Disk free is checked separately and named when it is the
limiter (`limit: "disk"` vs `"ram"`).

Live example (Nov 5 2026, Qwen3 30B loaded, capacity ~17 / ~16 GB):

| Model | Weights | Result |
|---|---|---|
| `Qwen2.5-Coder-7B-Instruct-4bit` | 4.28 GB | green — fits on 1 |
| `Qwen2.5-Coder-7B-Instruct-8bit` | 8.09 GB | green — fits on 1 |
| `Qwen2.5-Coder-7B-Instruct-MLX` / `-bf16` | 15.23 GB | yellow — fits on 2 (~10 GB RAM each) |
| `Qwen3-30B-A3B-4bit` | 17.17 GB | yellow — fits on 2 (~11 GB RAM each) |

### N nodes (not hard-coded EXO1/EXO2)

The picker used to assume exactly two Minis labeled EXO1/EXO2. That broke
other users' setups (one Mini, or three+).

**Now:**

- Node list comes from `~/.caravan/config.toml` `[web.nodes.<id>]` (see
  [CONFIGURATION.md](CONFIGURATION.md)). Missing section → Brenden's default
  two-Mini string (EXO1 local lead, EXO2 SSH) so existing labels stay put.
- A node with **no `host`** is omitted (does not exist). A configured node that
  fails gather is shown **offline** and skipped by fit.
- Fit loops over online nodes only. Capacities are measured per Mini (mixed
  RAM sizes are fine). With 1 online node: only green/red — never “fits on 2”.
- Download / progress / Stop / Delete / on-disk sizes iterate every configured
  node. Shard planning is still per node from the `weight_map`.
- **Runtime limit:** `mlx_split.py` is still 2-stage (lead + one packer).
  Constant `web_nodes.MAX_SPLIT_STAGES` (env `CARAVAN_MAX_SPLIT_STAGES`,
  default `2`). Fit may report fits-on-3 when three Minis are online, but
  download/load use at most `MAX_SPLIT_STAGES` nodes and surface a clear note
  like “3-Mini split coming later; runtime loads on 2 today”. Raise the
  constant when N-stage lands.

Findings (Nov 5 2026): unit tests cover 1 / 2 / 3 fake nodes (mixed RAM, one
offline). Live 2-Mini path on EXO1 `:8190` kept EXO1/EXO2 labels with no
config.toml. Mock picker views exercise 1-node and 3-node chip sets.

### Filters in the drawer

- Category chips (chat, coding, reasoning, vision, image-to-image, voice,
  cloud): each runs a real HF query (`pipeline_tag` / name keywords), not a
  client filter of a tiny chat catalog.
- **New** — HF `createdAt` / `lastModified`, roughly last 30 days; combinable
  with search and other chips (`newer=1`).
- **Max download** — dropdown Any / 5 / 10 / 20 / 50 GB; hides oversized
  quants; unknown sizes stay visible (gray).
- **fits-on-1 … fits-on-N** — chips generated from the count of **online**
  nodes (N). Client-side after fit attach. With one Mini online, only
  fits-on-1 appears and fit never suggests splitting.
- Search updates as you type (≈300 ms debounce; stale requests aborted).

### Split download

- Each Mini downloads only the safetensors shards for its layers, using the
  `weight_map` in `model.safetensors.index.json` (`mlx_split_fetch.py`).
- Border / shared shards stay on both Minis.
- A split change should download or delete only the extra shards (best-effort
  today; full prune polish still open).
- Lead and packer fetches run **in parallel**. Progress is byte-based
  (finished shards + `.incomplete` under
  `<model>/.cache/huggingface/download`), with MB/s and ETA per Mini.
- **Stop** kills `mlx_split_fetch` on EXO1 and EXO2 (local pkill + packer pid
  file). **Delete** stops any fetch for that model first, then removes trees
  on all Minis. Never deletes the currently loaded model.

### Conversion and cloud (decided, not all built)

- HF without an MLX build: convert via `mlx_lm.convert` (phase 3) or hide if
  conversion isn’t possible.
- Cloud: token-use stats instead of Topology system stats; key framework only
  until phase 5.

## Bugs found (and causes)

| Symptom | Cause | Fix |
|---|---|---|
| 111.5 GB Flash-Next showed OK / green | Unknown size fell back to a **4 GB guess** in `attach_fit` | Real sizes from HF `blobs=true`, then `metadata.total_size` in the index; unknown → gray, never green |
| Download bar stuck at ~10% while ~13 MB/s flowed | Progress only advanced when a whole file finished (`subprocess.run` + coarse pct) | Watch `.incomplete` + finished shard bytes; show MB/s and ETA |
| Only EXO1 downloaded; EXO2 idle | Packer fetch started **after** lead finished | Parallel lead + packer threads |
| Stop / Delete left `mlx_split_fetch` running | Cancel only set a flag; Popen/SSH child not killed | Stop/Delete pkill on both Minis; Delete stops fetch before `rm` |
| Coding / reasoning / vision / voice / cloud chips empty | Client AND-filter over a chat-only catalog; wrong/missing HF tags | Each chip issues its own HF query; cloud uses a static list |
| ~15 GB coder “tight on 2 Minis” with Qwen3 loaded | Fit used **current free RAM**, not unload capacity | Capacity = available + worker footprint (see above) |
| Chat had no memory of earlier turns | Page sent only the latest user message | Full history from the UI; verified second prompt token count |
| Topology GPU 100% on EXO2 while idle | `macmon` `gpu_usage` reads 100% under keepalive | Prefer ioreg “Device Utilization %” for GPU % |
| Stats cards stuck on “loading” | `state` out of scope in node render | Module-level `nodeLast` / `nodeFreshAt`; sticky last stats |

## Disk layout (EXO1 / EXO2)

| Path | What |
|---|---|
| `~/.caravan/mlx-models/<org>--<name>/` | Installed MLX trees (split shards per role) |
| `~/.caravan/mlx-models/drafts/` | Guess-ahead helper models; re-downloaded when needed |
| `~/.caravan/mlx-models/*/.cache/huggingface/` | Leftover download scratch next to a model |
| `~/.cache/huggingface/hub/` | Hugging Face hub cache (often duplicates installed trees) |
| `~/.exo/models/` | Legacy / exo trees still scanned |
| `~/.caravan/gguf/`, `~/.ollama/models/` | GGUF roots (phase 4 load) |
| `~/.caravan/memory/<date>/<session>.md` | Memory-guard archive (EXO1 only) |

On-disk section of the picker lists:

1. **Download cache (Hugging Face)** — hub + leftover model `.cache` (skips
   the loaded model). Sizes example Nov 5 2026: EXO1 ~30.6 GB, EXO2 ~0.3 GB.
2. **Guess-ahead helper models** — `drafts/`. Example: EXO1 ~5.1 GB, EXO2
   ~0.3 GB.
3. **Installed models** — per-Mini GB; Delete = all Minis.

## API sketch

| Method | Path | Notes |
|---|---|---|
| GET | `/api/picker/search?q=&source=&filter=&newer=1&limit=` | Catalog + capacity fit |
| GET | `/api/picker/disk` | Models + cleanup rows (all configured nodes) |
| POST | `/api/picker/download` | `{repo_id, packer_layers?}` parallel fetch (≤ MAX_SPLIT_STAGES) |
| GET | `/api/picker/jobs[/id]` | Byte progress |
| POST | `/api/picker/download/cancel` | Stop + kill fetches |
| POST | `/api/picker/delete` | `{id, confirm}` or `{kind: hf-cache\|drafts, confirm}` |
| POST | `/api/picker/fit` | Ad-hoc fit |

## Related web UI (same session)

### Topology

- Polls `/api/nodes` every **500 ms** while the drawer is open and the tab is
  visible; stops when closed/hidden.
- Stays open beside chat (not a modal).
- Sticky last stats (cards don’t collapse to empty).
- Temperature bar **20–100 °C**; color modes **Heat** (green/yellow/red) and
  **Theme** (dark/medium/bright of the active theme) — switch in Settings.
- Mac mini silhouette cards, variant **A**, with a power LED that goes stale.
- GPU %: ioreg utilization, not macmon’s keepalive-inflated reading.
- Models-on-disk and the Thunderbolt drawing were removed from Topology
  (models live in the picker).

### Memory guard

- Before generate: estimate KV vs reclaimable RAM minus `memory_safety_gb` on
  lead and packer.
- Trim oldest turns into Obsidian-style Markdown under
  `~/.caravan/memory/<date>/<session>.md` on **EXO1 only** (no EXO2 copy).
- BM25 recall injects a short system note; an archive note always tells the
  model N turns were moved.
- UI shows “Moved N…”; `caravan.meta.memory_guard` reports counts.
- Config: `--memory-dir`, `--memory-safety-gb`, `--memory-recall-tokens`
  (see [CONFIGURATION.md](CONFIGURATION.md)).

### Chat history

- The page must send the **full** conversation, not only the latest user
  message (fixed when Qwen appeared to forget prior turns). History is kept
  in `localStorage`.

## Remaining phases and known gaps

| Phase | Status |
|---|---|
| 1 Catalog + fit + chips + sizes | Done |
| 2 Split-aware MLX download + load + Stop/Delete | Done |
| 3 HF → MLX conversion (`mlx_lm.convert`) | Open |
| 4 GGUF via llama-server on one Mini | Open (catalog + fit only) |
| 5 Live Ollama Cloud | Framework only |

**Known gaps**

- Shard prune on split change is best-effort.
- Download-then-load works cleanly for repos already in `web_catalog`; others
  may need a Settings/catalog add.
- Some GGUF multi-file sizes can look odd until per-file quants are fully
  expanded in every path.
- Capacity follows current non-model RAM; a 15 GB model can read “fits on 2”
  rather than “tight on 1” when unload capacity is ~17 GB.
- HF-cache delete skips the loaded model’s hub folder but may leave shared
  blobs; drafts re-download when guess-ahead needs them.
- “You pick” theme, GGUF split, re-enabling self-tune on gpt-oss — later.
- N-stage split runtime (3+ Minis) still needs `mlx_split.py` changes; picker
  fit/chips already generic (see ROADMAP).

See also [WEB.md](WEB.md), [MLX-SPLIT.md](MLX-SPLIT.md), [ROADMAP.md](ROADMAP.md).

## Settings model dropdown (load list)

**Finding (Nov 5 2026):** The Settings `<select>` was fed by `web_catalog.list_models()`,
which returned the **static** `CATALOG` (Qwen3 4-bit, Gemma 4 4-bit, GPT-OSS MXFP4)
whether or not those folders existed. Missing models showed as disabled `○` rows —
Brenden’s phantom **gpt-oss** and **gemma**. On disk that day: EXO1 had
`mlx-community--Qwen3-30B-A3B-4bit` under `~/.exo/models` (loaded) and an 8-bit tree
under `~/.caravan/mlx-models`; EXO2 had Qwen3 4/8-bit. Gemma/gpt-oss were **not**
complete lead trees on EXO1 (only leftover fetch logs / packer-side copies), yet the
static catalog still listed them.

**Fix:** `/api/models` builds the list from N-node on-disk inventory
(`model_inventory.py` + `picker_disk_sizes.py --inventory`). A row appears only if
some configured Mini has a real MLX tree. It is **selectable** only when every stage
the load needs has complete shards (config + tokenizer, no `.incomplete`, weight_map
files present), capacity fit is not red, and the format can run (MLX today).
Partially present models stay in the list **disabled** with a short reason
(e.g. `missing shards on EXO1`) — clearer than hiding EXO2-only downloads.
The currently loaded model is always kept selectable. Picker downloads call
`refreshModels()` when the job finishes so Settings updates without a restart.
`CATALOG` remains metadata only (pretty name / default `packer_layers`).
