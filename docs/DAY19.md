# Day 19 — Balance, easy install and each Mini’s own files

Real date: **2026-11-08 (America/Chicago / CT)**. Box-side checkpoint only.
No EXO1, EXO2, M3 MacBook or Omarchy commands were run for this work. No model
was stopped, loaded, copied or downloaded on a Mini. Waiting for Brenden to
confirm Dark Champion's state and the Qwen3.5-27B download before live work.

Brenden's order is (1) Balance + 3+ Mini MLX split, (2) easy install + auto-start,
(3) each Mini keeps its own files. The original checkpoint below addresses (1);
themes (2) and (3) are appended chronologically later in this log. All three
are **experimental until live checks pass**; strict GGUF independence remains
partial. Earlier checkpoint limits below are historical where superseded by the
later theme 3 section. Current operational guide: [FILES.md](FILES.md).

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

### Theme 1 checkpoint gates / limits (historical)

- At this first checkpoint the new **Balance/CLI execution path supports N**;
  the old picker placement,
  picker download totals and Optimize sweeps still have their old two-stage
  gate. We did **not** blindly raise `MAX_SPLIT_STAGES` and let the old downloader
  fetch Packer 1's shards for every middle packer. Use the per-stage fetch CLI
  below when Balance says files are missing. The UI only previews missing
  downloads; it does not yet offer a one-click per-stage download job.
  **Superseded by theme 3 below:** picker/download/catalog bridge and explicit UI Fetch.
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
can copy this checkpoint there after machine access is cleared. At this first
checkpoint, themes (2)/(3),
main fast-forward, Day 19 tagged/package release, real-UI video and date-free X
draft remain end-of-day/coordinator work. Theme 2 is superseded by the later
checkpoint below. Do not publish a Day 19 release just
for this intermediate checkpoint.

---

## Theme 2 — easy install and auto-start (box-side checkpoint)

Implemented after the theme 1 checkpoint on 2026-11-08 (CT). Still **box-side
only**: no Minis/Omarchy touched, no actual macOS installer/launchctl run, no
models downloaded and no existing model processes restarted. Theme 3 and the
end-of-day release remain coordinator work.

### Implementation

- `scripts/install.sh`: one-command, per-user install entrypoint, macOS Bash
  3.2-compatible syntax. Checks macOS 14+, Apple Silicon, native Python 3.10+,
  non-root user and Git readiness. Explains missing prerequisites instead of
  silently installing Homebrew/Python/Xcode or changing macOS privacy settings.
- Sets up a dedicated clone (default `~/.caravan/src/caravan`), matching branch
  or tag, and `~/.caravan/venvs/mlx`. Dependencies come from
  `requirements-mac.txt` (`mlx-lm==0.32.2`, Hugging Face Hub). Runs pip check and
  import verification. This is not a complete transitive dependency lockfile.
- Reuses a matching clean checkout/venv without restarting unchanged jobs.
  Explicit `--update` uses clean `git pull --ff-only`; no reset, scp, branch
  switch, forced update or replacement of unrelated folders/settings. Existing
  release archives can use `--use-existing`. A fresh lead gets a local-only web
  config, not the author's lab peer. Fresh single-node loads now also skip the
  old default-packer SSH stop path when that peer is not configured.
- `--dry-run` is portable and writes/downloads/starts nothing. `--role worker`
  without a model prepares the environment only, with a clear next step. The
  installer never guesses a model or downloads weights in the background.
- `agent/service_config.py` builds validated single/N-stage argv and per-user
  absolute-path plists. No machine names or two-Mini limit. Unique names support
  multiple simulated packers on one host; every stage owns its local model and
  separate session directory.
- `tools/caravan_service.py`: owned `install`, `uninstall`, `status`, `restart`,
  `--dry-run`, `--no-start`. Plists live in `~/Library/LaunchAgents/`, plans in
  `~/.caravan/services/`, logs in `~/.caravan/logs/`. Changed/unowned definitions,
  corrupt ownership records and busy/reserved ports fail closed. Repeated
  identical installs do not restart an already-loaded job. Uninstall removes
  only owned service definitions; models/caches/logs/venv/source are kept.
- Web LaunchAgents set `CARAVAN_WEB_KEEP_WORKERS=1` and
  `AbandonProcessGroup=true` to preserve workers across a web-only service
  restart/uninstall. Worker jobs do not abandon their group. Restart uses
  owned `bootout` → `bootstrap`, not process-name sweeps or `kickstart -k`.
- `caravan_agent.py --service-config ... --apply` takes an early local MLX
  route (no legacy GGUF discovery/health advertisement/SSH). The local agent
  validates shards, checks upstream protocol/layer ranges and supervises only
  its own child. Missing peers/failed starts retry every 15 s, so login order
  need not be coordinated. Graceful stop allows 15 s for its child to flush
  caches, then escalates only that child if necessary.
- Web status polling adopts a service-owned lead that becomes ready after web
  startup or restarts later. Runtime records are separate from web-owned
  `lead.pid`; alternate-port experiments do not overwrite that marker.
  Exact worker path/port identity is checked before adoption.
- **Ownership is explicit:** installing only web retains normal interactive
  model switching. Installing fixed worker auto-start plans reserves their
  ports; conflicting UI Load/Stop/Balance reload/Optimize is refused with the
  service name and uninstall instruction. Remote managed packers are also
  protected from web-managed launch/stop. No launchd-vs-web restart fight.

### Scope and known limits

- These are **user-login LaunchAgents**, not before-login boot daemons. The
  installer does not enable auto-login, disable sleep, set up SSH/Remote Login,
  assign Thunderbolt addresses or grant Local Network permission.
- Web-only mode preserves a running model on web restarts but does not reload
  it after a full reboot. For model auto-start, install an explicit local worker
  plan on each node; dynamic “resume last UI model” is not implemented.
- Fixed auto-start model plans are initially a separate controller mode. Remove
  the lead and packer model jobs before returning to UI-driven split changes.
  Editing Balance does not silently rewrite launchd plans on other machines.
- Agent-owned proxy orchestration/automatic role discovery remains a roadmap
  follow-up. This implementation runs web directly in its own LaunchAgent and
  single/N-stage MLX workers through the local agent. Existing GGUF services and
  loopback/SSH RPC lockdown are unchanged.
- macOS job lifecycle, clean dependency install, privacy prompts and real Metal
  inference remain **unverified**. Unit mocks and Linux dry-runs are not evidence
  of a successful Mac install or reboot. No new inference benchmark measured.

Full usage and requirements sources: [SERVICES.md](SERVICES.md).

### Theme 2 test record (all Linux box)

| Check | Result |
|---|---|
| First full compatibility run | 529 tests, 37.906 s; **2 failures** |
| First new installer/service tests | 34 tests, 0.088 s; **1 error** |
| Corrected installer/service tests | 34 passed, 0.082 s |
| Full regression after initial corrections | 563 passed, 36.979 s |
| Expanded targeted tests | 37 passed, 0.087 s |
| Full regression after single-node SSH fix | 566 tests, 37.436 s; **1 failure** |
| Final targeted installer/service suite | 41 passed, 0.145 s |
| Full regression before peer-fixture correction | 570 tests, 37.963 s; **1 failure** |
| Full regression after peer-fixture correction | 570 passed, 38.059 s |
| Targeted suite with CLI zero-port validation | 42 passed, 0.131 s |
| **Final full regression** | **571 passed, 37.444 s; 0 failures/errors/skips** |

Theme 2 adds **42 tests** (Day 19 total: 84 new above the original 487).
A final review also corrected CLI `--port 0` so it is refused rather than
silently replaced by the default port, and added a regression test.
Failures were retained, not hidden:

1. The stricter adoption check rejected an old fake command with neither the
   repository path nor port. Corrected that fixture to represent the actual
   tracked worker; did not weaken the ownership check.
2. The first remote reservation guard mislabeled all SSH failures as managed
   service conflicts (409). Corrected it to use a dedicated reservation code;
   real/unreachable transport failures retain a 502 stop response.
3. One new test helper passed duplicate repo/Python keyword arguments; corrected
   the fixture (the 34-test error above).
4. The existing HTTP stop-failure fixture used a fake SSH target not present in
   configured nodes. After the deliberate “never contact an unconfigured lab
   peer” fix, no SSH was correctly attempted. Made the fixture explicitly
   configure its own fake peer, then verified unreachable-stop JSON/keep-alive.

Coverage includes plist round trips, absolute paths with spaces, KEEP_WORKERS
and process-group flags, 2/3/4/7-stage command generation, missing model/links,
unknown/tampered definitions, idempotent install, busy/conflicting ports, GUI
session errors, graceful restart, uninstall retention, owned-child stop,
missing-peer retry, runtime replacement safety, late adoption, corrupt-plan
fail-closed behavior, dirty checkout refusal, dry-run no-writes and Linux
platform refusal. No real launchctl, SSH or MLX worker was started by tests.

Additional smoke checks passed: shell syntax, Python compileall, git diff check,
new-lead installer preview, worker service JSON/plist preview, and the real
agent CLI's early `--service-config` preview without `--apply` (no child spawned).

### Exact pending live steps

**First get Brenden's clearance for current Dark Champion/download activity.**
Do not run the full installer, pip, launchctl or any restart on the working Minis
before that. Keep all sync Git-only; never scp or reset a dirty tree.

From Omarchy after clearance:

```sh
ssh exo1 'cd ~/dev/caravan-v3 && test "$(git branch --show-current)" = caravan-v3-mlx-split && test -z "$(git status --porcelain)" && git pull --ff-only origin caravan-v3-mlx-split'
ssh exo2 'cd ~/cv3 && test "$(git branch --show-current)" = caravan-v3-mlx-split && test -z "$(git status --porcelain)" && git pull --ff-only origin caravan-v3-mlx-split'
```

Never use `~/dev/caravan` on EXO2. If either command refuses, inspect without
throwing away work. Do not run the fresh-clone default installer against these
existing lab paths.

1. **New-Mac smoke test** (prefer a spare Mac/account, not the active cluster):
   run the installer dry-run, then actual one-command install. Verify Python
   architecture/version, venv import/pip checks, single-local-node config,
   http://127.0.0.1:8190/, `status`, logs, and a small local model. Repeat the
   identical installer; confirm unchanged job/PID and retained config/model.
   Test dirty/unrelated folders are refused. Run once with `--no-start` and
   confirm no immediate job, then start/restart explicitly. No such live run
   has happened yet.

2. **Existing EXO1 web migration only** (do not restart the model workers):

   ```sh
   # On EXO1, ~/dev/caravan-v3; existing venv, no pip/install changes needed.
   ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install --kind web \
     --repo "$PWD" --python ~/.caravan/venvs/mlx/bin/python \
     --host 0.0.0.0 --port 8190 --lead-port 8194 --dry-run
   ```

   Preserve the existing trusted-private bind (use loopback/private IP instead
   of `0.0.0.0` if appropriate). Verify the old web process was launched with
   `CARAVAN_WEB_KEEP_WORKERS=1`; then shut down **only web** with
   `curl -s -X POST http://127.0.0.1:8190/api/shutdown -d '{}'`. Wait for its old
   listener to exit; remove `--dry-run` from the install command. If the old
   KEEP_WORKERS setting is unknown, identify/stop only its verified web PID as
   described in theme 1; never sweep worker processes. A busy port is refused,
   not automatically killed.

   Check `tools/caravan_service.py status --name web`, UI adoption, same current
   model/worker PIDs and clean chat. Then `restart --name web`; confirm workers
   and a running download stay up. Test `uninstall --name web` keeps workers;
   restore the same web job or the previous manual KEEP_WORKERS=1 command.
   Web restart alone does not require EXO2 worker restart.

3. **Fixed-model job test on isolated ports**, after workloads are cleared:
   use the same small already-installed 12-layer model on both nodes (or adapt
   counts to the actual layer count). No new downloads implied. Use each node's
   own path; two packers share EXO2 RAM/GPU and are not a third-GPU benchmark.

   ```sh
   # EXO2, ~/cv3. Substitute its actual local MODEL and private TB address.
   ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install --kind worker \
     --name sim-p1 --repo "$PWD" --model MODEL --counts 4,4,4 --stage-index 0 \
     --listen 127.0.0.1:5591 --dry-run
   ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install --kind worker \
     --name sim-p2 --repo "$PWD" --model MODEL --counts 4,4,4 --stage-index 1 \
     --listen EXO2_TB:5592 --upstream 127.0.0.1:5591 --dry-run

   # EXO1, ~/dev/caravan-v3. MODEL is EXO1's own folder.
   ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install --kind worker \
     --name sim-lead --repo "$PWD" --model MODEL --counts 4,4,4 --stage-index 2 \
     --peer EXO2_TB:5592 --port 8196 --dry-run
   ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install --kind web \
     --name sim-web --repo "$PWD" --port 8192 --lead-port 8196 --dry-run
   ```

   Inspect first; remove `--dry-run` only for the chosen isolated test. Start the
   lead before packers once to prove retry/late adoption; then start the packers.
   Verify health, non-gibberish output, ranges, warm reuse, local cache files,
   managed Load/Stop/Optimize refusal, peer restart cold resync, agent/child
   crash recovery and graceful stop/save. Read `~/.caravan/logs/sim-*.log` on the
   corresponding host. Local Network permission may need approval on each Mac.
   Choose a very small model: service jobs use keepalive by default, so two
   packer processes are deliberately sharing one GPU.

   Cleanup is explicit: EXO1 `uninstall --name sim-lead`, then
   `uninstall --name sim-web`; EXO2 `uninstall --name sim-p2`, then
   `uninstall --name sim-p1`. All with `tools/caravan_service.py`. Keep model and
   cache files. Never kill unrelated workers or restart the GGUF RPC services.

4. **Login/reboot test** only when Brenden agrees it is safe: confirm generated
   jobs return after user login, peer start order is tolerated, logs are useful,
   web adopts the correct lead and current models/SSH keys/config remain intact.
   No pre-login or sleeping-Mac availability is promised.

Record all live failures, model/counts, service startup/recovery times, PIDs,
cache reuse and real reply timings here and in the diary/BENCHMARKS as relevant.
The Obsidian diary remains untouched by this box-only task. No Day 19 final tag,
release package, video, X draft or main fast-forward was made at this checkpoint.

## Theme 3 — each Mini keeps its own files (box-only checkpoint)

Implemented after themes 1/2, still without contacting EXO1, EXO2 or Omarchy.
Direct edits only; no cloud agents. This is not a release/main fast-forward.
[File guide/API/limits](FILES.md) is the operational reference.

### What changed

- New `agent/model_files.py` and shared `web_files.py`: required/missing/retained
  file plans, per-Mini logical and allocated disk accounting, symlink-safe paths,
  pinned stage fetches, checksum/metadata validation and owned transfer lifecycle.
- Balance now offers **Fetch missing files on each Mini**, Stop, byte progress,
  retained files and disk use. Its own model selector includes incomplete models,
  without weakening Settings' normal “cannot load incomplete models” guard.
  Moving one MLX boundary replans every stage's needed shards; Fetch freezes
  those counts, and Reload remains a separate freshly checked action.
- Every node downloads directly from the source, with its own HF access. Only
  JSON plans/commands travel via SSH. Config/index must match the preview before
  a model folder changes; one immutable source revision covers the whole job.
  Published LFS SHA256s are checked, including correct-size existing files.
  Detected corrupt headers, same-size checksum failures and incompatible
  metadata produce inspect/move-aside errors, not falsely complete jobs.
- Transfer PID/exit/plan/log records under `~/.caravan/transfers`; Stop verifies
  a UUID and script identity. No repo-wide kill for new file jobs. A vanished
  process without a real exit result is an error. Stop failures explicitly warn
  that a transfer may still run. Detached jobs survive a web-only restart; active
  owned jobs are rediscovered, duplicate writers blocked, and each MLX agent
  persists its own successful placement even if the web coordinator went away.
- The legacy **3+ Mini picker/download/catalog/load** path is now connected to
  that N-stage planner. It no longer downloads the same “front half” on every
  packer. Saved ordered counts/IDs and per-stage inventory readiness survive
  catalog serialization. Optional `model_root`/`python` node config supports
  distinct simulated stores. Shared physical RAM is still one budget, not two.
  N-stage Optimize/speculation/concurrency remain gated as in theme 1.
- New `gguf_files.py` / `web_gguf_files.py`: verified direct-source tensor ranges
  for N physical RPC peers. Initial lead-file/LFS SHA256 binding, cached tensor
  offsets/checksums, strict bounded 206 responses, resume, per-tensor SHA256,
  native FNV cache seeding and retained-cache-key accounting. GGUF controls show
  device **shares**, lead first; explicit reload uses the previewed shares.
- GGUF picker now downloads the complete GGUF **only on the lead**, not every
  online Mini. New installs include the `gguf==0.19.0` metadata reader. Existing
  llama.cpp `gguf-py` works too; no llama.cpp binary/source was changed.

### Deliberate limitations / remaining work

**The full GGUF goal is NOT achieved by Caravan-only Python changes.** The stock
lead loader requires the complete GGUF. RPC's hash-cache threshold means tensors
<=10 MiB still cross the cable, and cache misses still transfer. Peers can avoid
whole-GGUF downloads and prefetch their large assigned tensors; eliminating all
weight transfers / the complete lead file requires llama.cpp loader/protocol work.
No sparse pretend-GGUF workaround is used. Single-file known-SHA sources only;
peer manifests over 80 KB are refused. No live cold/warm-load or tok/s claim.

Old extra MLX shards, complete peer GGUFs and old caches are **not** automatically
removed. Lists mean “not needed for this proposed plan,” not “safe garbage.”
Another split or fixed service may still need them. The existing explicit whole-
model delete action is separate; there is no new per-shard delete/prune action.
RPC usage is the whole cache on that node, labeled with its path; retained-key
lists cover this path's previously recorded tensors, not unknown cache contents.
Disk snapshots do not reserve disk; GGUF seeding needs one extra staged tensor
on disk and transient RAM for the native seeder. Verify actual RPC `LLAMA_CACHE`.

Fetch never rewrites fixed launchd model plans or stops/reloads workers. Their
ownership guard still blocks interactive model reconfiguration; use web-only mode
or explicitly reinstall fixed jobs with new counts after approval. Historical
job history is not reconstructed after web restart; active jobs are rediscovered,
and partial files resume through a fresh same-count Fetch. Automatic multi-link
Thunderbolt discovery remains open; triangle wiring alone does not configure it.

### Tests and real box-only measurements

All unit tests use fake nodes/temporary directories and loopback HTTP or mocks;
no SSH to a Mini, live model download, or registered-computer tool was used.

| Run | Result |
|---|---|
| Baseline | 571 passed, 38.122 s |
| First compatibility suite | 571 tests, 37.530 s; **4 failures** |
| First new file suite | 41 passed, 0.535 s |
| Files + Balance + picker targeted run | 100 passed, 4.620 s |
| Native cache/UI/lifecycle additions | 49 passed, 1.108 s |
| First full green expanded suite | 620 passed, 38.490 s |
| Files + Balance + inventory targeted run | 109 passed, 5.186 s |
| Inventory/revision/cache full suite | 627 passed, 38.496 s |
| Restart-ownership target suite | 61 passed, 1.104 s |
| Full suite before final orphan/stop reporting review | 632 passed, 38.903 s |
| Verified orphan/stop-reporting suite | 632 passed, 39.006 s |
| Final cache-log/runtime-cap review | 632 passed, 39.030 s |
| **Final verified full suite (two-stage save regression included)** | **633 passed, 39.078 s; 0 failures/errors/skips** |

The initial four failures were three old Balance HTTP fixtures lacking an HF
identity/real on-disk files, and the old fit test explicitly expecting three
stages to be “coming later.” Updated the fixture to contain config/index/tokenizer
and actual named files, and the runtime expectation to N stages; did not bypass
the new disk checks. Subsequent review caught missing new fields in inventory's
JSON projection, per-node revision drift, and transfer survival/duplicate-writer
risks; added regressions before the final suite. The last review also preserved
`packer_layers` alongside the new two-stage counts, so normal legacy Load cannot
forget a newly saved Balance after a restart.

Theme 3 adds **62 tests**. Day 19 cumulative: **146 new** above the original 487.
Coverage includes 3/4-node plans, whole boundary shards, missing/corrupt files,
no-write retained-file previews, logical/allocated/hardlink/symlink accounting,
pinned snapshots/ranges/checksums, saved N-stage catalog plans, custom roots,
exact GGUF range/length/resume/response failures, actual native C cache seeding,
source identity, isolated process ownership, vanished/failed/unconfirmed-stop
jobs, restart discovery and explicit preview-vs-fetch HTTP behavior.

Additional smoke on an isolated **box-only** venv with `gguf==0.19.0`: generated a
real-format 12-layer synthetic GGUF with three >10 MiB tensors, read its actual
metadata, bound its SHA256 to mocked Hub metadata, served a real loopback HTTP
Range response, and seeded an actual compiled native FNV cache. Results:

- Complete source: **37,748,992 bytes**.
- Middle peer required/fetched: **12,582,912 bytes**, only `blk.5.weight`.
- Exact source range: **12,583,168–25,166,079**, inclusive.
- One native cache file; zero remaining missing tensors; no peer GGUF copy.

These are synthetic storage/transfer measurements, **not** real model inference,
Mini network throughput, or speed benchmarks. No new entries pretending otherwise
were added to inference BENCHMARKS. Logs live on the box under
`/workspace/day19-theme3-*.log`; no model weights were downloaded for these tests.
Shell/Python/JavaScript syntax and git diff checks also passed.

### Exact pending live steps (do not execute without clearance)

1. **Wait for Brenden to clear Dark Champion / Qwen download activity.** These
   are future instructions, not actions performed by this checkpoint.
   From Omarchy, clean branch-checked Git-only updates:

   ```sh
   ssh exo1 'cd ~/dev/caravan-v3 && test "$(git branch --show-current)" = caravan-v3-mlx-split && test -z "$(git status --porcelain)" && git pull --ff-only origin caravan-v3-mlx-split'
   ssh exo2 'cd ~/cv3 && test "$(git branch --show-current)" = caravan-v3-mlx-split && test -z "$(git status --porcelain)" && git pull --ff-only origin caravan-v3-mlx-split'
   ```

   **Never `~/dev/caravan` on EXO2.** Refuse dirty/unexpected branches; no reset/scp.

2. **Web-only restart, workers/downloads preserved.** Follow theme 2's verified
   old-web shutdown/migration procedure above; no EXO2 worker restart just to
   update the UI. If the generated `web` job was installed, from EXO1's correct
   checkout: `~/.caravan/venvs/mlx/bin/python tools/caravan_service.py restart --name web`.
   Otherwise stop only the verified old web and relaunch with the same trusted
   private bind/ports and KEEP_WORKERS explicitly enabled:

   ```sh
   cd ~/dev/caravan-v3
   CARAVAN_WEB_KEEP_WORKERS=1 ~/.caravan/venvs/mlx/bin/python proxy/web_server.py \
     --host 0.0.0.0 --port 8190 --lead-port 8194
   ```

   Use the existing private/loopback bind instead of `0.0.0.0` where appropriate;
   never expose this unauthenticated UI publicly. Do not run a second web job on
   an occupied port. Verify current worker/download PIDs survived.

3. **MLX small-model ownership test.** First use a small already-installed model
   and the existing two nodes. In Balance, select that model, Auto/refresh,
   record each stage's files/bytes, move one boundary by one layer and confirm
   exactly the affected missing/retained lists change. No files should change
   until Fetch. Fetch, Stop midway, resume with the same counts, verify known
   sizes/checksums and no obsolete file removal. Explicit Reload only after ready;
   chat, verify real ranges/readable output and measure actual post-reload speed.
   Fixed worker services must be explicitly removed/reconfigured first if present.

4. **Third-store simulation on EXO2, not a speed benchmark.** Use the theme 1
   `sim3` second-worker/alternate-port config and the theme 2 isolated-port
   recipe, adding `model_root="~/.caravan/mlx-models-sim3"`. Set the same
   `physical_id="exo2-physical"` on both EXO2-backed node entries; retain distinct
   worker ports and correct order/upstream. Keep EXO1 `~/dev/caravan-v3` and both
   EXO2 entries' repo `~/cv3`. Choose a genuinely tiny model that fits both
   processes' shared GPU/RAM budget. Preview three counts, Fetch, and verify the
   normal EXO2 tree and sim3 tree contain only their own newly needed whole shards
   (shared/boundary files excepted). Verify UI/normal picker save and reload the
   exact N-stage plan. Do not use a large active model for this experiment.
   Repeat with three physical Minis when available.

5. **Transfer web-restart test.** During a small explicit fetch, restart only web
   with KEEP_WORKERS enabled. Verify the download survives, appears as a
   rediscovered transfer, a second writer is refused, Stop affects only that
   transfer, and same-count Fetch resumes its partial bytes. Test an unreachable
   peer / failed stop reports uncertainty rather than false success. Inspect
   `~/.caravan/transfers/<token>.log/.exit/.json/.pid` on the relevant Mini.

6. **GGUF two-/three-physical-Mini test, workloads cleared.** Use a small
   single-file GGUF already on the lead. Confirm the metadata reader is available
   (`requirements-mac.txt`, or existing llama.cpp `gguf-py`) and `cc` exists before
   any optional pip/build change. In Balance enter the original HF repository and
   exact filename if it was a manual/old copy. Verify source SHA match; review
   displayed cache paths and live RPC `LLAMA_CACHE`. Use shares `1,1` (lead first)
   initially. Fetch missing peer tensors, stop/resume once, then explicitly Reload
   that same preview. Inspect RPC cache hit/miss logs, readable chat, cold/warm
   load times and actual link bytes; **expect small-tensor traffic**, not zero.
   Repeat with three physical nodes/shares `1,1,1`; do not co-host GGUF RPC-device
   simulations. Verify no full peer GGUF appeared and old cache files remain.

7. Record real failures, ranges/counts/shares, per-node logical/allocated bytes,
   source revision/checksums, download/recovery bytes, startup/cache hits and actual
   speed here / BENCHMARKS only where measured. Clean up only the specifically
   installed simulation jobs; keep all model/cache files unless Brenden explicitly
   approves an exact deletion list. No blanket worker/RPC restarts or process kills.

### Open questions for Brenden (plain language)

- Is the current GGUF compromise useful enough to test now: full file on the
  lead, only large assigned tensors fetched on peers, small tensors still over
  RPC? Or should the next priority be changing llama.cpp to meet the strict rule?
- Should RPC caches move from `~/Library/Caches/llama.cpp` to a Caravan-owned
  location so macOS cleanup is less likely to evict them? No relocation happened.
- For cleanup, should the next UI let you review/approve exact files after checking
  all saved/running/service plans, or keep the current list-only policy for now?

All three themes now have box-side checkpoints, but **GGUF's strict rule and all
live Mac checks remain open**. Obsidian diary, final release packaging/tag/video/
X draft and main fast-forward remain untouched coordinator work.

## Live checks started — Nov 8, 2026, 15:22 CST

Brenden cleared live checks. Access is through Omarchy, then separate `ssh exo1`
/ `ssh exo2` (EXO2 does not resolve from EXO1). No scp or wrong EXO2 checkout.

Initial state: Huihui Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit was ready,
64 layers split **24 on EXO2 / 40 on EXO1**. Lead PID **57464**, packer PID
**54170**, original web PID **7067**. Dark Champion was on disk, not loaded.
No active fetch/download process was found. Original workers were not ours;
they are being preserved while small-model tests use isolated ports/stores.

Both correct checkouts were on `caravan-v3-mlx-split` at `1ccdb15`, tracked files
clean but with the same sole untracked `proxy/web/index.html.bak-pre-amber`.
Preserved that backup and fast-forwarded both to `5ee90bc`; Git did not overwrite
it. Native installer correctly refused an existing checkout with that untracked
local change (safety behavior, not a reason to erase the backup).

Restarted only the verified EXO1 web (new PID 64049) with KEEP_WORKERS=1;
original lead PID/health survived, original packer remains untouched. Isolated
web uses loopback 8192, lead 8196 and `~/.caravan/day19-live` state/config/stores.

**First live bug:** normal Balance preview showed safe Auto **32/32**, with
zero missing shards, but `metadata_ready=false` on both Minis. The inventory JSON
projection omitted `has_config`, `has_index`, `has_tokenizer`, even though the
on-disk inspector knew them. That also prevented saved N-stage catalog rows
from becoming usable. Added these booleans to the real serialized contract and
extended its regression test. Full box suite: **633 passed, 38.751 s**.
No production model reload/fetch was performed to work around this bug.

Second live bug caught safely before loading: picker assembled execution nodes
from the live-statistics projection; that projection drops configured custom
model roots. A custom **two-stage** request therefore fell back to the legacy
paths instead of the own-files bridge. Stopped only the newly created Orvena
job. Existing EXO2 Orvena weights/one-Mini placement stayed intact; the partial
EXO1 default-root download is retained, not silently removed. Execution nodes
now merge live RAM with authoritative configured roots/SSH/Python/physical IDs.
Added an HTTP-level regression with projected/misleading live root fields.
Full box suite: **634 passed, 39.552 s**.

After metadata fix, production Auto preview was **33/31**, safe and ready (free
RAM changes the recommendation). Read-only boundary previews demonstrated real
replanning: **16/48** requires EXO1 shard 1, **5,343,269,992 bytes**; **48/16**
requires EXO2 shard 3, **5,357,088,982 bytes**. The opposite Mini lists shard 2 as
not needed for that proposed plan. No files were deleted/downloaded and no
production reload was applied. Existing on-disk totals were EXO1
**10,731,498,067 bytes**, EXO2 **10,717,679,207 bytes** (metadata included).

Native new-destination installer dry-runs passed on both Macs without creating
the destination. Generated web plist preview passed; a temporary web job was
also bootstrapped successfully from `~/.caravan/day19-live`, **outside**
`~/Library/LaunchAgents`, on loopback 8193. No permanent LaunchAgent installed.

Pre-load isolation audit found a third safety issue: legacy packer cleanup was
scoped to SSH host only, not the configured endpoint. A fresh alternate-port
N-stage web instance on the same host could otherwise reach the normal 5560
worker's marker. **Caught before any test load; original PIDs stayed alive.**
Cleanup now requires the configured peer/listen endpoint as well as SSH host.
Two new regressions cover isolation and preservation of legitimate legacy
cleanup. An existing stop-error fixture was updated to contain the real peer
field. First intermediate suite failed that incomplete fixture (200 vs expected
502), then **636 passed, 39.548 s**. While auditing, the isolated web also used
an explicit non-matching legacy SSH name; N-stage execution uses configured
nodes, not that legacy fallback. Do not rely on a new lead port alone for
isolation of old code.

Own-file transfer checks so far: explicit stop/resume passed, web restart
rediscovered both UUID-owned transfers, a duplicate Fetch returned HTTP 400
("untracked download ... still running"), and stopping that rediscovered job
affected only its transfers. Same-count Balance Fetch resumed retained partial
bytes; lead partial measured **407,896,064 bytes** before that stop. An observation
script expecting the old in-memory job ID received 404 after web restart, as
expected; verification switched to rediscovered records and actual readiness,
not a false completion claim. No production worker was restarted.

Third-stage scratch store was seeded by an **EXO2-local APFS clone** of its
already-installed Orvena file, not scp or a lead relay. Independent regular
file, no symlink, **3,034,300,629 weight bytes**; clone blocks can be shared by
APFS, so logical/st_blocks totals are not exclusive physical-volume usage.
Both initial stage stores are independently fetched from the immutable source.
Native dry-run of all three generated fixed-stage agent plans passed.

Fourth live bug: KEEP_WORKERS preserved the isolated two-stage model, but a web
restart showed **idle** because `adopt_running()` searched only default model
roots. It could not match the already-running custom-root lead; a same-ID row
from a default root was also unsafe to substitute. Added command/PID/count/
layer/ownership-verified pipeline adoption, including older Day 19 state files,
and persist the model identity with new Balance state. Four regressions cover
custom roots, same-ID shadows, stale PID/path/counts and missing stage ownership.
An initial new fixture forgot its lead.pid and failed; corrected the fixture,
then **640 passed, 39.546 s**. Workers were preserved during the failed live
adoption check; the UI was not allowed to reload an unknown worker as a workaround.

Two-stage Orvena 16/16 inference, reload and explicit disk cache restore worked.
Initial 48-token probes used an unsupported top-level `enable_thinking` field,
so they hit the reasoning token limit (not a visible-answer quality pass).
Correct `thinking:false`/`chat_template_kwargs` probes answered **four** and
**six**. Note: this model's rendered no-think conversation turn diverged and
safely cold-prefilled; do not label that turn a warm-cache hit. The repeated
saved prompt did reuse **52/53** tokens after restore. Full reply JSONs and
worker timing-log snapshots are retained under `~/.caravan/day19-live` on EXO1.

GGUF peer-only fetch Stop/Resume completed against the installed small Qwen2.5
3B Q4_0: source **1,997,879,712 bytes**, peer plan **901,994,496 bytes**,
shares 1:1, ranges **[0,19) / [19,37)** (36 blocks plus output-device accounting).
A 2:1 preview reduced peer-required bytes to **673,732,608**, listing **18**
retained cache files / **228,261,888 bytes**, without deleting any. Existing
all-model RPC cache stayed **23,474,650,624 bytes** (content-key deduplication).
The peer already had a complete legacy GGUF; it was preserved, not newly copied.
First immutable-source/hash/metadata preview took **5.085 s**, using the existing
llama.cpp gguf-py fallback; no pip install was needed.

The actual three-stage UI/picker run reached **[0,11), [11,22), [22,32)** on
5591/5592/8196 and answered four/six correctly. All three own stores passed the
revision-pinned file checker; normal picker reload preserved 11/11/10 and
three-stage cache Save/Restore worked. An initial live harness accepted the
*old* ready state immediately after an asynchronous Load and got a transition
409; corrected polling to require the new PID **and** requested counts. That
near-zero "ready" time is invalid and excluded from benchmarks.

Fifth real issue surfaced in reply telemetry: N-stage packer stats were nested,
so the old runtime guard read no peer free-RAM value. Qwen3.5 decoder dimensions
also live in `text_config`, causing a zero KV estimate. The guard now takes the
lowest known free RAM across all packers (never sums duplicated physical RAM),
conservatively budgets all preceding layers against it, reads nested decoder
sizes, and enforces the hard safety margin even for an unknown architecture.
Eight additional tests cover 3/4-stage peers, co-hosted RAM, missing/invalid/zero
telemetry, nested dimensions and low-memory rejection. **648 passed, 38.574 s**.
Hybrid KV sizing remains conservative; unknown peer telemetry is still reported
as unknown, not a guarantee of safety.

Sixth real issue was caught by **actual temporary launchd**, not plist tests:
the plans resolved the venv Python symlink to Homebrew's base interpreter.
Packer 1 repeatedly exited with `ModuleNotFoundError: mlx`; packer 2 and the
lead correctly waited/retried instead of downloading anything or killing other
workers. The 90-second readiness observation failed. Stopped only those test
jobs and archived their plans; the normal Qwen workers remained alive.

Service plans now keep an absolute **venv interpreter path without dereferencing
its symlink**, for both agent and child. Added a real temporary-venv subprocess
regression asserting `sys.prefix`, plus default-venv/PATH and plan round-trip
checks. **650 passed, 39.594 s**. No pip/dependency change was needed on either
Mini: MLX was already installed in the correct venv. Existing plans produced
by old code must be explicitly regenerated with the venv path; they are not
silently rewritten.
