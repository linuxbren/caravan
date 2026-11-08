# Day 19 — Balance and an N-Mini MLX pipeline

Real date: **2026-11-08 (America/Chicago / CT)**. Box-side checkpoint only.
No EXO1, EXO2, M3 MacBook or Omarchy commands were run for this work. No model
was stopped, loaded, copied or downloaded on a Mini. Waiting for Brenden to
confirm Dark Champion's state and the Qwen3.5-27B download before live work.

Brenden's order is (1) Balance + 3+ Mini MLX split, (2) easy install + auto-start,
(3) each Mini keeps its own files. This change addresses (1), not (2) or GGUF
file ownership. It is **experimental until the live checks below pass**.

## What changed

- `agent/mlx_split.py`: one contiguous range contract, positive integer counts
  adding up to all model layers, no stage count hard-coded. Existing two-stage
  flags and cache labels remain compatible. A middle packer runs only its own
  layers on the previous stage's hidden states, not embeddings or final logits.
- The lead serves HTTP, runs the **last** layers and samples tokens, as before.
  Requests travel **lead → last packer → … → first packer**; hidden states return
  **first packer → … → last packer → lead**. This is a serial layer pipeline,
  not tensor parallel or a claim that three Minis write faster than two.
- Commands/checkpoints/save/restore/drop propagate through the chain. Every
  process owns its own sessions and disk files. Restore requires matching token
  digests across the chain. Aggregate epochs invalidate warm sessions after any
  upstream restart. Epoch checks happen before prepare/restore, not recursively
  on every generated token. Transport failures fail the request rather than
  quietly using half a cache; the next prepare rechecks the chain.
- `agent/mlx_split_fetch.py`: `plan_stage_files` and `--split-counts` /
  `--stage-index` replan **whole** safetensors shards for every stage. A boundary
  shard may be needed on several Minis. Tied embeddings belong only on first
  packer and lead; final norm/lm_head/native MTP belong on the lead. Each Mini
  fetches its own files from Hugging Face; no lead-to-packer weight transfer.
- `proxy/split_balance.py`: one pure preview contract for web and a future TUI.
  Auto max-min balances estimated free memory with a **1.75 GB safety margin**
  and **1.3 GB/stage overhead**. Uses live available RAM plus the retiring
  worker's reclaimable footprint; does not pretend `total RAM − OS` is all free.
  Duplicate workers on one host share its budget (`physical_id` for aliases).
  The preview shows per-node ranges, estimated use, remaining headroom, missing
  shards and byte totals when known. Unknown RAM/files/tokenizer blocks reload.
  Full weight size comes from index metadata or the full recorded shard sizes,
  not the bytes in a partially downloaded local folder.
- `POST /api/balance`: read-only preview. Browser/TUI submits model ID, optional
  node IDs and counts; the server supplies RAM, metadata and file inventory.
- `POST /api/models/load` with `balance: true`: explicit reload, fresh node
  stats, per-stage shard/header/size checks **before** stopping the current
  model. No implicit downloads. Failed readiness returns 409 without switching.
- `proxy/web_pipeline.py`: start packers in layer order, then the lead; use each
  node's own repo/model folder; check upstream ranges; record owned workers in
  `~/.caravan/web-ui/pipeline.json`. Cleanup is PID + exact script/listen identity,
  never `pkill`. `pipeline-balance.json` preserves node mapping on web adoption.
- Topology's existing N-node cards now have a Balance panel: Auto, N−1 sliders
  (one layer per step), live memory/download preview and explicit reload. Real
  write tok/s and first-token time appear from a completed reply, never from
  a made-up prediction. Stale asynchronous previews cannot re-enable Reload.
- `tools/simulate_mlx_pipeline.py`: fake 3/4/N-node pipeline on real framed
  socketpairs, separate local cache folders, save/restore and warm reuse.
  It does not touch the Minis or import MLX.

### Deliberate gates / limits

- The new **Balance/CLI execution path supports N**; the old picker placement,
  picker download totals and Optimize sweeps still have their old two-stage
  gate. We did **not** blindly raise `MAX_SPLIT_STAGES` and let the old downloader
  fetch Packer 1's shards for every middle packer. Use the per-stage fetch CLI
  below when Balance says files are missing. The UI only previews missing
  downloads; it does not yet offer a one-click per-stage download job.
- N-stage Optimize is explicitly rejected by the API. New Balance launches pin
  one concurrent chat, guess-ahead off and learning off. Existing two-Mini
  launches are unchanged. Promote concurrency/speculation/Optimize only after
  measuring correctness and performance with N-stage inference.
- Memory figures are estimates, not a bound on arbitrary growing KV/context.
  The worker's runtime memory guard remains necessary. No new inference speed,
  load-time, Thunderbolt bandwidth or physical-Mini RAM numbers were measured.
- Indexed, text-only MLX checkpoints with known full size are required. Checks
  verify local shard sizes/headers, not cryptographic hashes. Model/tokenizer
  identity agreement across machines is still an existing roadmap item.
- Direct split TCP remains unauthenticated. Use trusted private links only.
  GGUF RPC's loopback + SSH tunnel lockdown is unchanged.

## API examples (on the lead after deployment)

Counts and returned node IDs use **forward layer order: packers, then lead**.
Default node selection is all configured nodes; explicitly pass `node_ids` to
choose a subset. Offline configured nodes are refused, not silently dropped.

```sh
# Read-only Auto preview. Use an installed MLX model ID from /api/models.
curl -s http://127.0.0.1:8190/api/balance -H 'Content-Type: application/json' \
  -d '{"model_id":"MODEL_ID"}'

# Read-only manual preview, example for a 32-layer model on three stages.
curl -s http://127.0.0.1:8190/api/balance -H 'Content-Type: application/json' \
  -d '{"model_id":"MODEL_ID","node_ids":["exo2","exo3","exo1"],"counts":[10,10,12]}'

# Explicit reload; checks RAM/files again. Does NOT start downloads.
curl -s http://127.0.0.1:8190/api/models/load -H 'Content-Type: application/json' \
  -d '{"model_id":"MODEL_ID","balance":true,"node_ids":["exo2","exo3","exo1"],"counts":[10,10,12]}'
```

Auto preview returns `counts`, `auto_counts`, `safe`, `ready`, `stages`,
`margin_gb`, `node_ids`, `reload_required` and `speed: null`. Each stage includes
`range` (half-open), `estimated_use_gb`, `headroom_gb`, `downloads` (`null` means
unknown), `download_bytes` and `metadata_ready`. Speed comes only from actual
reply stats. Client-supplied memory/file claims are ignored.

## No third physical Mini needed for box tests

```sh
PYTHONPATH=.:proxy:tests python3 -m unittest tests/test_day19_balance.py
python3 tools/simulate_mlx_pipeline.py --nodes 3
python3 tools/simulate_mlx_pipeline.py --nodes 4
```

Observed: 3-stage forward order `[0,1,2]`; 4-stage `[0,1,2,3]`. Both cold turns
reused **0** tokens; second turns reused **2** tokens; **3** / **4** separate
stage-local cache files saved and restored with agreement. This uses fake
layers, **not an MLX performance benchmark**. Additional tests cover uneven
memory, unsafe/manual counts, unknown inventory/tokenizer, boundary download
changes, tied embeddings, missing-stage restores, epoch invalidation, session
resync, HTTP read-only behavior, fresh reload checks and owned launcher cleanup.

## Live deployment steps — pending, do not run until cleared

First ask whether Dark Champion is still loaded and Qwen3.5-27B is downloading.
Do not interrupt either. From Omarchy, use its existing `ssh exo1` / `ssh exo2`
aliases; do not try to resolve `exo2` from EXO1.

1. Clean git pull only (no scp, no reset, no dirty-worktree overwrite):

   ```sh
   ssh exo1 'cd ~/dev/caravan-v3 && test -z "$(git status --porcelain)" && git pull --ff-only origin caravan-v3-mlx-split'
   ssh exo2 'cd ~/cv3 && test -z "$(git status --porcelain)" && git pull --ff-only origin caravan-v3-mlx-split'
   ```

   **Never use `~/dev/caravan` on EXO2.** If either worktree is dirty, stop and
   inspect; do not "fix" it with a reset. Check branch first if not already on
   `caravan-v3-mlx-split`.

2. Restart **only the EXO1 web server** to expose the UI/API. Keep the existing
   lead/packer workers and downloads running. The existing web process was
   launched with KEEP_WORKERS=1; if that is confirmed, use its shutdown endpoint:

   ```sh
   # On EXO1, only after checking the old web process's launch configuration:
   curl -s -X POST http://127.0.0.1:8190/api/shutdown -d '{}'
   cd ~/dev/caravan-v3
   CARAVAN_WEB_KEEP_WORKERS=1 nohup ~/.caravan/venvs/mlx/bin/python \
     proxy/web_server.py --host 0.0.0.0 --port 8190 --lead-port 8194 \
     > ~/.caravan/web-ui/web_server.log 2>&1 &
   ```

   Wait for the old listener to exit before starting the replacement. Preserve
   any existing nondefault host/peer/SSH arguments. If KEEP_WORKERS on the old
   process cannot be confirmed, identify/stop **only its verified web PID**, not
   worker PIDs or process-name sweeps. Setting KEEP_WORKERS on the replacement
   does not retroactively change the old process's shutdown behavior.

3. Hard-refresh the browser. Open Topology → Balance, select an installed small
   MLX model, press Auto / refresh. **Preview must not stop a model or start a
   download.** Move a boundary one layer; confirm ranges still cover all layers
   exactly, headroom changes on both sides and newly needed shards change.
   Check an unsafe split, unknown inventory and an offline node block Reload.
   Only after clearance, reload a ready split. This restarts the chosen MLX
   stages and lead, not web, GGUF RPC or unrelated workers. Check clean text,
   turn-2 cache reuse, per-reply speed, stop/save/reload/restore and web-only
   restart adoption. Compare against the old two-stage path on the same model.

4. To fetch a missing shard set, run **on each participating Mini itself**, only
   after agreeing to the network/disk use. Substitute the same count list and
   the correct stage index; first packer = 0, middle = 1, lead = last.

   ```sh
   ~/.caravan/venvs/mlx/bin/python agent/mlx_split_fetch.py REPO LOCAL_MODEL_DIR \
     --role packer --split-counts 10,10,12 --stage-index 1 --dry-run
   # Remove --dry-run only when ready to fetch from Hugging Face.
   # Use --role lead --stage-index 2 for the lead in this example.
   ```

   `--dry-run` fetches the small config/index metadata if absent but not model
   shards (existing fetcher behavior). It is not an offline command. No files
   are fetched from the lead. Existing unneeded shards are **not deleted**.

### Third-stage MLX simulation on two Minis (pending)

After the current workloads are cleared, choose an already-installed **small**
12-layer indexed MLX model (or adapt counts to its actual layer count). Run two
packers on EXO2 using different ports and session folders; the lead can use an
unused HTTP port on EXO1. This is correctness testing, not a three-GPU benchmark.
The two packers share EXO2's physical RAM/GPU; do not use a large model or count
its RAM twice. These commands are foreground processes so each can be stopped
with Ctrl-C in its own terminal; no blanket kill commands needed.

```sh
# EXO2 terminal A, from ~/cv3. MODEL is EXO2's own model folder.
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --model MODEL \
  --split-role packer --split-counts 4,4,4 --split-stage-index 0 \
  --split-listen 127.0.0.1:5591 --cache-dir ~/.caravan/mlx/sim-p1 \
  --no-split-keepalive --no-learn --no-split-draft

# EXO2 terminal B, same clone/model; replace EXO2_TB with its private link IP.
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --model MODEL \
  --split-role packer --split-counts 4,4,4 --split-stage-index 1 \
  --split-upstream 127.0.0.1:5591 --split-listen EXO2_TB:5592 \
  --cache-dir ~/.caravan/mlx/sim-p2 --no-split-keepalive --no-learn --no-split-draft

# EXO1 terminal C, from ~/dev/caravan-v3. MODEL is EXO1's own folder.
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --model MODEL \
  --split-role lead --split-counts 4,4,4 --split-peer EXO2_TB:5592 \
  --host 127.0.0.1 --port 8196 --cache-dir ~/.caravan/mlx/sim-lead \
  --split-pipeline-chats 1 --no-split-keepalive --no-learn --no-split-draft
```

Send two requests to `http://127.0.0.1:8196/v1/chat/completions`, with the same
session key; inspect `/caravan/split` for two packers. Confirm layer ranges,
non-gibberish output, warm reuse and independent saved cache files on both
hosts. Restart Packer 1 between turns and require cold resync or a clear failed
request followed by a cold retry, never reuse of an orphaned cache. Test
Ctrl-C/save/restore and an intentional missing shard on a **scratch copy**, not
by deleting real model files. Record model/quant/counts, time to ready, RAM,
first-token/read/write/total timings, warm reused tokens and all failures here
and in BENCHMARKS.md. No such live numbers exist yet.

## Three physical Minis and Thunderbolt

Three Minis can be cabled as a triangle (rear Thunderbolt ports), without a hub.
Cables alone do not create a single routed subnet. Existing automatic link
selection/status still assumes one preferred link. This checkpoint supplies
explicit per-node endpoints but does **not** implement automatic triangle
address assignment, multi-link routing/failover or bandwidth probing.

Configure `[web.nodes.ID]` tables on the lead: lead `host="local"`; packers have
unique `id`/`order`, `ssh`, `repo` and a `peer="PRIVATE_IP:PORT"` reachable from
the lead. Optional `listen` selects a local bind address and `upstream_peer`
selects the previous packer's address reachable from this packer. It can differ
from the address the lead uses. `physical_id` identifies multiple simulated
workers on the same physical Mini, even when SSH aliases differ.

The launcher needs each packer's `peer` reachable from the lead for readiness;
each middle packer also needs its `upstream_peer` reachable. Plan explicit
private subnets/routes or use an already-routed trusted network. Verify every
required pair before loading; never fall back to a public unauthenticated port.
The Topology header's single link string is still a summary, not a full cable
map. Automatic multi-link discovery and a truthful per-edge cable map remain
follow-up work.

## Test record

All on the Linux box, no GPU or Minis. Zero intentional skips.

| Check | Result |
|---|---|
| Baseline full suite | 487 passed, 34.098 s |
| First split/fetch targeted suite | 36 passed, 0.087 s |
| First full regression after runtime edits | 487 passed, 33.968 s |
| Initial Day 19 fake-node suite | 26 passed, 0.081 s |
| Expanded Day 19 HTTP/launcher suite | 37 passed, 3.653 s |
| Full suite after HTTP/launcher integration | 524 passed, 37.475 s |
| Full suite with N-packer telemetry test | 525 passed, 37.430 s |
| Split + Day 19 targeted suite after epoch cost review | 64 passed, 3.723 s |
| Full suite with N-stage Optimize gate test | 526 passed, 37.437 s |
| Full suite with N-stage recovery command test | 527 passed, 37.933 s |
| **Final suite, including MLX CLI + GGUF regression checks** | **529 passed, 37.908 s; 0 failures, 0 errors, 0 skips** |

42 new tests total. A final review caught an over-broad edit that had inserted
MLX-only report variables into the GGUF fetch helper; removed it and added an
explicit no-network GGUF regression test before this final checkpoint. No failed
suite was hidden; all completed runs above passed. The parser's intentional
`--wired-limit bogus` error text in the full log is an existing passing test.
The seven-node simulator also passed: order `[0,1,2,3,4,5,6]`, cold reuse 0,
warm reuse 2, seven independent stage caches restored.

Syntax checks:
`python3 -m compileall -q agent proxy tools/simulate_mlx_pipeline.py`,
`node --check proxy/web/balance.js` and `git diff --check` pass.
Simulator outputs are correctness evidence only, not benchmark speeds.

## Follow-up / questions for Brenden

- Is Dark Champion still loaded, and is Qwen3.5-27B still downloading? That gates
  deployment/reloads, not box work.
- Which already-installed small model should be the first live 3-worker test?
  No third Mini purchase is needed for that correctness check.
- Proposed UX next step: an explicit **Download needed files** button that shows
  per-Mini sizes before starting source downloads. No automatic fetch on slider
  movement. Keep that rule, or choose another workflow?
- Keep serial/guess-ahead-off N-stage testing first; only widen performance
  controls once the real pipeline is correct.

The Omarchy Obsidian diary is **not updated by this box-only task**; the parent
can copy this checkpoint there after machine access is cleared. Themes (2)/(3),
main fast-forward, Day 19 tagged/package release, real-UI video and date-free X
draft remain end-of-day/coordinator work. Do not publish a Day 19 release just
for this intermediate checkpoint.
