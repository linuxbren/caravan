# Day 19 — Balance, easy install and each Mini’s own files

Real date: **2026-11-08 (America/Chicago / CST)**. This is a chronological
log: the original box-only checkpoints come first, followed by the authorized
live checks starting at **15:22 CST**. Brenden's "do the live checks" clearance
was received before contacting Omarchy or the Minis. The original 27B Qwen
workers were preserved during the early smoke/install checks. A later explicit
reboot authorization allowed the Qwen interruption and migration to permanent
services; later the fixed-model jobs were removed for web-owned restore.
**Latest checkpoint: the new-mode EXO2 reboot lost SSH and did not return within
the 360-second monitor. EXO1 was NOT rebooted; see the blocked result at the end.**

Brenden's order is (1) Balance + 3+ Mini MLX split, (2) easy install + auto-start,
(3) each Mini keeps its own files. All three now have two-Mini native smoke
coverage, including a three-stage simulation on two GPUs. **Still experimental**:
three physical Minis, GUI usability and a truly separate fresh-account install
remain unverified; strict GGUF independence remains partial. Permanent user-login
reboot recovery of the **earlier fixed-model mode** passed on both existing
FileVault-off accounts after the fixes below; this does not validate the newer
last-model restore mode. No login/security settings were changed and no release was made.
Older "pending/no Mini touched" statements below describe the checkpoint at
that time, not the final result. See the final live-validation summary at the
end, [BENCHMARKS.md](BENCHMARKS.md), and [FILES.md](FILES.md).

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


Seventh real issue: SIGTERM of our temporary first packer logged a save but
never exited while the next stage kept its idle TCP connection open. The
90-second recovery check failed; the original production packer was untouched.
Frame reads now poll the stop event while preserving incomplete headers and
payloads, so idle connections also terminate cleanly. The service port probe
uses the same SO_REUSEADDR policy as the worker: TIME_WAIT is not mistaken for
an active listener, while a live listener still blocks a conflicting start.
Five regressions cover idle/partial-frame stops, fragmented-frame integrity,
an actual connected idle server shutdown, and closed-versus-live TCP ports.

Validation after the shutdown fix: **655 tests passed in 39.648 s**.


Eighth issue: normal-web refresh preserved the production workers, but reading
its shutdown HTTP response raised IncompleteRead (headers advertised 12 bytes,
body was cut off). Restored the normal web immediately; its original Qwen lead
was still PID 57464 and healthy. Shutdown now writes and flushes the complete
JSON response **before** starting server shutdown, and still shuts down if the
client has disconnected. Two ordering/disconnected-client regressions added.

Validation after response fix: **657 passed, 40.290 s**.

Temporary native launchd checks passed after the fixes: all three stages started
from local agents, waiting for upstreams without downloading. Initial readiness
observation was 16.976 s (single observation, includes the retry interval).
Web kickstart with KEEP_WORKERS kept the exact lead PID and warm sessions.
Managed Load/Stop/Optimize all returned 409 without touching the services.
After the idle-read fix, first-packer graceful restart recovered in **16.746 s**
with the same agent. The old-session reply safely resynchronized cold (0/23
cached), answered four, TTFT 0.220 s, total 0.406 s.

An older already-running lead agent still used its pre-fix port probe: child
crash recovery took **47.249 s**, including false TIME_WAIT busy retries. After
launchd recreated the agent, the fixed-agent child crash recovered in **17.306 s**;
launchd recovery after killing only our temporary agent took **2.547 s**, with
its old child confirmed gone. Both recovered replies restored 22/23 prompt
tokens from disk and answered four. Fixed child recovery reply: TTFT 0.072 s,
total 0.255 s, 32.79 tok/s; agent-crash reply: TTFT 0.077 s, total 0.262 s,
32.43 tok/s. These are single short checks, not medians. All temporary labels
were booted out and worker plans archived under day19-live/retired-service-plans;
no permanent LaunchAgent was installed and no reboot was attempted.


GGUF live integration exposed an unnecessary legacy step: even after Balance
verified all peer-only files, reload scanned the peer's already-existing full
GGUF and seeded a padded layer on either side. The native assignment itself
was correct: preview [19,37), legacy padded seed [18,37). No missing model layer
or wrong answer was observed. The initial 12.094 s load included **5.8 s** of
this optional scan; it reported 55 already-cached tensors / 940,038,144 B,
versus the exact own-files requirement of 901,994,496 B.

A freshly verified, safe and complete Balance plan now explicitly chooses the
peer-only tensor-cache path and skips the legacy full-GGUF scan/padded seed.
Normal legacy loads keep their compatible optional seeding. The lead still
requires the complete GGUF; small tensors and real cache misses can cross RPC.
Four regressions cover complete/unsafe readiness gating, N-peer no-full-copy
launch, legacy fallback, and rejecting a truthy nonboolean flag.


The first new own-file launcher test run caught a missing local import in the
extracted legacy-seed helper (two regressions failed); corrected before commit.
A tenth live issue affected **reported GGUF speed**, not generated answers:
the UI divided seven output tokens by native timing for six decode intervals
(45.22 displayed vs llama.cpp **38.75 tok/s**) and divided all 38 warm prompt
tokens by the one-uncached-token prefill time. The proxy/UI now preserve native
`predicted_per_second` and `prompt_per_second`, with finite/nonnegative checks
and the existing calculation as fallback. Native cold/warm and invalid-rate
regressions added. All benchmark GGUF speed figures use native rates, not the
inflated pre-fix display. GGUF `ttft_s` remains a prefill-time estimate; it is
not a measured end-to-end streaming first-token latency.

Validation after GGUF integration/telemetry fixes: **663 passed, 39.501 s**.


## Final live validation — Nov 8, 2026, 16:14 CST

### What passed

- Before changes, recorded both loaded models, worker PIDs and download state.
  Original **Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit**, EXO2 24 /
  EXO1 40 layers; Dark Champion was on disk, not loaded. No active download was
  found. Correct branch on both; tracked trees clean, with the pre-existing
  untracked `proxy/web/index.html.bak-pre-amber` preserved, not erased.
- Read-only production Auto/16–48/48–16 Balance previews; no production reload
  or production shard fetch. Explicit isolated MLX reload, correct four/six
  answers, identical-prompt warm reuse, Save/Restore and web restart adoption.
- Actual three-stage **11/11/10** chain on ports 5591/5592/8196, including normal
  saved-picker reload and own model roots. Two packers shared EXO2; this is not
  a third GPU or a throughput claim. Simulations and unit fixtures cover 3/4+
  nodes; Optimize/concurrency/speculation remain gated.
- MLX own-files Fetch/Stop/Resume, duplicate-fetch refusal, download rediscovery
  across web restart, completion and reload. Boundary moves replanned missing
  and retained files; no model/cache pruning. The live MLX test model is one
  whole safetensors shard, so it cannot prove multi-shard download savings.
- Both Macs' installer dry-runs and native service/plist plans. Real temporary
  launchd three-stage startup with upstream-order retry, managed-control 409s,
  web KEEP_WORKERS, graceful peer restart and child/agent crash recovery.
  All test labels unloaded; plans/logs/models retained outside LaunchAgents.
- GGUF source-verified peer Range fetch/stop/resume, retained-key replanning,
  native split inference, warm reuse and web adoption. Final verified-own-cache
  reload **5.951 s**, metadata `file_mode=balance-verified-peer-cache`, **no legacy
  full-peer-GGUF seed scan**. The legacy full GGUF already on EXO2 was untouched.
  Aggregate en2 load delta: **1,376,105 B received / 91,657,390 B sent** (SSH,
  probes, small tensors and other link traffic included; not exact model bytes).
  Native output: **40.00 tok/s cold / 44.30 warm**, correct answer four;
  0/38 then 37/38 cached prompt tokens. UI rates exactly matched native timings.
  Web-only restart preserved all three lead/RPC/tunnel PIDs and reused 37/38:
  **40.04 tok/s**, prefill 33.782 ms, total 0.1836 s.

Measured MLX and recovery tables, artifacts and caveats are in BENCHMARKS.
The fixes and intermediate failures are recorded above, not hidden. A final
post-cleanup service `status` reported **No managed services installed** on both
Macs. Asking the uninstall dry-run to use an already-archived test plan correctly
refused **Owned config is missing**; no bypass or reinstallation was attempted.
That is a fail-closed refusal, not a permanent install/uninstall migration test.

### Final Mini state

At **16:14 CST**, both correct checkouts were at code fix `76d3c44` (the final
numbers/docs commit follows), branch `caravan-v3-mlx-split`:

| Host | Left running | Preserved state |
|---|---|---|
| EXO1, `~/dev/caravan-v3` | normal web **69242**, port 8190, `CARAVAN_WEB_KEEP_WORKERS=1`; original lead **57464**, port 8194 | Qwen 27B, layers 24–63, ready/healthy |
| EXO2, `~/cv3` | original packer **54170**, Thunderbolt port 5560 | same Qwen 27B, layers 0–23 |

No test listeners on 5591/5592/8192/8193/8196/5596/5606; no temporary launchd
labels, no permanent test plists, no active transfer processes, and the normal
web's live-fetch list was empty. Own scratch/model/cache/log files remain under
`~/.caravan/day19-live`; test worker plans are archived in
`retired-service-plans`, and stopped web PID marker is `web-stopped.pid`.
No existing model/cache files or the unrelated backup were deleted. No scp,
EXO2 `~/dev/caravan`, Omarchy app changes, cloud agent, release, tag, reboot or
permanent LaunchAgent install was used.

### Remaining checks / plain-language decisions for Brenden

1. **May we use a spare Mac/account for an actual fresh install and repeated
   install, then install permanent user-login services and test logout/reboot?**
   Current checks used dry-runs and temporary launchd only. Do not reboot or
   migrate the normal jobs without that approval. Keep the venv path, not its
   resolved Homebrew binary; regenerate old service plans explicitly.
2. **Third physical Mini and cable routes:** run the same saved ranges on three
   separate GPUs. A Thunderbolt triangle is physically possible, but automatic
   multi-link discovery/routing is not implemented; configure each peer/listen/
   upstream address explicitly. GUI slider/download interaction and longer
   throughput/low-memory runs still need human-observed testing.
3. **How strict should “own files” be next?** MLX whole-shard duplication is
   unavoidable for the present loader; run a multi-shard model from partial
   stores to verify real transfer savings. GGUF still needs a complete lead
   file and sends <=10 MiB tensors/cache misses over RPC. Eliminating those
   needs llama.cpp loader/protocol work. Existing files stay until an explicit
   approved per-file cleanup design; nothing is silently pruned.
4. **Auto-start control:** should fixed launchd model plans become editable from
   Balance, or keep interactive web-managed workers separate? Today fixed plans
   deliberately block UI Load/Stop/Optimize rather than fight another controller.

Safe source update only (already performed throughout this work; no worker
restart needed for a documentation-only final commit):

```sh
# Run from Omarchy; these are the only approved working checkouts.
ssh exo1 'cd ~/dev/caravan-v3 && git diff --quiet && git diff --cached --quiet && test "$(git branch --show-current)" = caravan-v3-mlx-split && git pull --ff-only origin caravan-v3-mlx-split'
ssh exo2 'cd ~/cv3 && git diff --quiet && git diff --cached --quiet && test "$(git branch --show-current)" = caravan-v3-mlx-split && git pull --ff-only origin caravan-v3-mlx-split'
```

These tracked-tree checks deliberately preserve the known untracked backup.
Never use `~/dev/caravan` on EXO2. For a future approved worker-code activation,
wait until the current model/reply/download is idle, check a fresh Balance plan,
then explicitly reload the selected model; a web-only restart does not update
already-running worker or agent code. Keep **CARAVAN_WEB_KEEP_WORKERS=1** for
web-only restarts. No production worker reload was done by these live checks.


Final exact full-suite command after live cleanup and all fixes:

```sh
PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests
```

**663 tests passed in 40.133 s** (30 more than the 633-test pre-live checkpoint).
No code changed after that run; the final commit records measurements and docs.


## Follow-up clearance — Nov 8, 2026, 18:08 CST

Brenden approved the remaining install/service preparation. The follow-up
explicitly forbids reboot/logout now. Initial checks found original lead 57464,
packer 54170 and normal web 69242 still running, both correct checkouts at
b1e5410, and the same preserved untracked backup. `sudo -n -l` required an
interactive password on both Macs, so no test user was created or password
collected. Used the approved closest equivalent: a fresh clone, HOME, venv,
config, state and dependencies on EXO1, with GUI user 501 shared. This is **not**
a separate-account/macOS-permission or FileVault/login test.

Fresh root: `~/.caravan/day19-fresh-20261108-1808`, its own `home` subdirectory.
Installer used role lead, `--name day19-fresh-web --host 127.0.0.1 --port 8197
--lead-port 8198`. First install exited successfully in **95.897 s**, actual web
HTML/status ready **96.189 s** from start. Repeat exited successfully **1.441 s**,
UI verified **1.449 s**; **same web PID 73454**, unchanged local-only config and
same isolated venv sys.prefix. No model was downloaded/loaded by the installer.
Both returned a working 159,019-byte web page and idle worker state.

Two follow-up issues:
- Installer's final message still printed 8190 despite `--port 8197`; corrected
  to report the selected port, with a portable shell regression.
- Ordinary installed fixed-model plans reserve web control immediately, even
  when installed with `--no-start`. Installing them for the live Qwen split
  would therefore take over the existing UI. Added explicit **--stage-login
  --no-start**: owned configs live under `~/.caravan/services/login`, outside
  the old running web's canonical scan. Real plists still go in the user's
  `~/Library/LaunchAgents`, pointing at those configs. Nothing is bootstrapped
  now. After login loads a job, the updated web/worker guards recognize and
  protect its staged plan. Job-not-found releases only an inactive staged plan;
  unknown launchctl failures remain fail-closed. Existing plan schema and
  normal install behavior are unchanged; original web need not restart.

Ten added tests cover staging without launchctl, actual plist/config location,
inactive-versus-loaded ownership, duplicate/port conflict guards, explicit
uninstall, lookup failures, corrupt plans and chosen-port output. An initial
new test fixture used REPO instead of the file's ROOT constant (eight errors);
corrected before commit, and targeted staging/installer tests passed.

Follow-up code validation: **673 tests passed in 39.892 s**.


### Follow-up native results and permanent service state — 18:18 CST

Updated installer repeat (`--update`, code a59760c) passed in **1.552 s**,
still PID **73454**, and printed the correct 8197 URL. Native `status` reported
that isolated LaunchAgent loaded/running. Explicit native `uninstall` then
removed only its owned job/config/plist; the isolated fresh HOME/clone/venv were
removed after saving results and version evidence outside that HOME.

Fresh dependencies really installed and imported: native arm64 Python **3.14.7**,
MLX **0.32.4**, mlx-lm **0.32.2**, huggingface_hub **2.4.0**, GGUF **0.19.0**.
Pip check passed. The original user's environment/dependencies were not changed.
A separate tiny staged-web test on 8197/8198 exercised actual staged install,
inactive/loaded launchctl detection, activation, status, real stdout log,
restart and uninstall. Single readiness observations: **0.135 s** start,
**0.132 s** restart; no model involved. Logs were preserved as
`staged-web-start.log` / `staged-web-restart.log`. A first harness attempt had
an SSH/heredoc quoting SyntaxError before any execution; corrected, then all
native checks passed. Both temporary HOMEs and test labels were removed.

**Real permanent LaunchAgents are now installed, deliberately NOT loaded:**

| Mini | Label / name | Fixed next-login purpose |
|---|---|---|
| EXO1 | `com.caravan.v3.web` / `web` | normal web, 0.0.0.0:8190 → lead 8194, KEEP_WORKERS=1 |
| EXO1 | `com.caravan.v3.day19-qwen-lead` / `day19-qwen-lead` | existing local Qwen 27B, counts 24,40, last 40 layers, peer 169.254.103.191:5560 |
| EXO2 | `com.caravan.v3.day19-qwen-packer` / `day19-qwen-packer` | same model's existing local partial store, first 24 layers, listen 169.254.103.191:5560 |

Each real plist is in that user's `~/Library/LaunchAgents`; owned JSON is
`~/.caravan/services/login/NAME.json`. All three passed `plutil -lint`, model
shard/tokenizer validation, and native status **installed, not loaded**.
The live original web remained **69242**, lead **57464**, packer **54170**;
Qwen stayed ready, no change to its 24/40 split. Updated service guards also
confirmed the unloaded staged jobs do not own those live workers. No job was
bootstrapped for the real model; logs for those never-started jobs may not yet
exist. Their configured destinations are `~/.caravan/logs/web.log`,
`day19-qwen-lead.log` and `day19-qwen-packer.log`. Do not call this a passed
permanent Qwen startup/login test: that is the next approval-gated test.

At **18:17:54–18:17:55 CST**, original three PIDs were unchanged and healthy,
no model transfers were running, and test ports 5591/5592/8196/8197/8198 and
fresh/staged-test labels were absent. The only new persistent operational
state is the three deliberately staged real login services above. Test results,
install logs and exact versions remain in
`~/.caravan/day19-fresh-20261108-1808` on EXO1; temporary environments are gone.

### Historical 18:18 CST reboot plan — superseded by the authorized results below

**No reboot or logout was performed. Brenden must approve the interruption.**
No further install/migration command is needed: the real login plists are staged.
They start at **user login**, not before FileVault unlock/login, and will retry
if their upstream/interface is not ready. This is a fixed Qwen model plan,
not automatic last-selected-model resume.

What a reboot interrupts:
- EXO2 reboot terminates packer **54170**; the entire two-Mini Qwen split cannot
  generate while it is down, even if EXO1's web remains open.
- EXO1 reboot terminates web **69242** and lead **57464**; the normal UI/API and
  Qwen requests go offline. In-flight replies fail; in-memory/KV state is lost.
  Finish/save active chats first. New services use separate per-service cache
  directories, so warm chat reuse is **not** promised. Model files, old cache
  files, saved chat history/config are not deleted or re-downloaded.
- Reboot also closes that Mac's SSH sessions and interrupts its other running
  applications/services. Brenden should save unrelated work; this task did not
  restart or change those apps.

After explicit downtime approval:
1. Finish/save active chats and confirm no downloads/new work. Use the Mac's
   normal **Restart** action on **EXO2**, then log in as Brenden. Wait for its
   staged packer to report loaded/listening on 5560.
2. Restart **EXO1**, then log in. Its staged web and lead start automatically;
   agents tolerate peer startup order. No manual worker start is required.
3. From Omarchy, run read-only status checks:

```sh
ssh exo2 'cd ~/cv3 && ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py status --name day19-qwen-packer'
ssh exo1 'cd ~/dev/caravan-v3 && ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py status --name web && ~/.caravan/venvs/mlx/bin/python tools/caravan_service.py status --name day19-qwen-lead'
ssh exo1 'curl -fsS http://127.0.0.1:8190/api/status'
```

Expect new PIDs, healthy Qwen, 24/40 ranges, managed service ownership and a
sensible short reply. Inspect the three logs above, then warm reuse and web-only
restart with KEEP_WORKERS. If the Thunderbolt address changed from
169.254.103.191 or privacy/login permissions block launch, stop and inspect;
regenerate owned plans explicitly, never hand-edit JSON or kill unknown port
owners. Permanent fixed workers intentionally block conflicting UI model control
once active. A cold first chat after reboot is expected, not cache corruption.

To **cancel before reboot**, `uninstall --name day19-qwen-lead` and
`uninstall --name web` on EXO1, and `uninstall --name day19-qwen-packer` on EXO2
(using each repo's `tools/caravan_service.py` and existing venv). These unloaded
jobs can be removed without touching today's original workers. Do not use
`restart` on these production worker plans now: their ports are occupied by the
unmanaged workers, and the CLI correctly refuses rather than killing them.
Never use `~/dev/caravan` on EXO2. Nothing here authorizes reboot execution yet.


### Actual reboot follow-up — first failure and recovery, Nov 8

Preflight on both Minis: automatic login is `brenden`, FileVault is off, and
`sudo -n true` needs a password. The approved System Events restart succeeded on
EXO2 first. It came back to the logged-in `brenden` GUI and launchd started its
agent, but initial model startup failed safely: macOS changed Thunderbolt en2
from `169.254.103.191` to `169.254.35.180`; the saved fixed listen address was no
longer local. No unrelated worker, file, download, login or network setting was
touched. EXO1 was deliberately not rebooted until recovering this first stage.

Fix: explicit reboot-safe `tb://INTERFACE:PORT` local listen and
`ssh+tb://TRUSTED_CONTROL_HOST/INTERFACE:PORT` upstream discovery, strict existing
SSH host-key trust, no LAN data fallback, and owned-child rebind on an actual
address change. See SERVICES.md. Eleven new tests cover validation, private
hardware/address checks, failed control lookups, changed addresses and N-stage
plan persistence; full suite **684 passed in 38.669 s**. Final live timings and
state are recorded below; the first EXO2 automatic model startup failed safely.


Post-reboot inspection also caught two display/telemetry issues: the normal web
status still showed the old configured packer IP even though the live lead used
the new address; and MLX's short-reply UI write rate counted six tokens over five
decode intervals (6.51 tok/s), disagreeing with the native timing line (5.43).
Status now prefers the actual live peer. MLX structured usage supplies the same
native rates as its log (uncached read tokens, generated tokens minus the first
for decode), which the UI already honors. Five new timing/HTTP regressions cover
cold/cached/one-token replies and static/live peer fallback.

The old fallback UI inventory SSH target also used the pre-reboot TB address.
EXO1's application config now explicitly names the already-trusted stable
EXO2 SSH control address `brenden@100.90.134.95`, the current Thunderbolt data
endpoint and the correct node repo paths. Existing model preferences were kept;
backup: `~/.caravan/config.toml.day19-pre-stable-control`. No SSH trust, OS login,
security, network address or route setting was changed. The fixed launchd model
plans resolve changing TB addresses themselves; future UI-driven model switching
still needs an up-to-date explicit node data endpoint (automatic UI discovery is
not implemented).


Deploying that telemetry fix exposed one more real native issue: the owned
service CLI's immediate `bootout` → `bootstrap` sometimes returned launchd error
5 (Input/output error) while the previous job was still unloading. The lead
remained installed but unloaded; no unrelated process was killed. Fixed with a
bounded 35-second retry **only** for native bootstrap error 5, checking the job
is absent and its socket free before retrying. Other errors are not retried;
there is no sudo/root fallback or PID killing. Five new mocked regressions cover
transient success, unloading state, occupied ports, other errors and timeout.
The first isolated timing-test command lacked `agent` on its import path; that
harness was corrected before its targeted/full test passes.


### Completed authorized reboot test — 18:22–18:40 CST, Nov 8

Brenden explicitly authorized restarting the Minis and interrupting Qwen.
Both automatic-login users were already `brenden`, FileVault was already **off**,
and noninteractive sudo required a password. System Events Restart worked
without a prompt. **No auto-login, FileVault, SSH-trust, privacy or network
settings were changed.** EXO2 was restarted first; after its address fix it was
restarted again to prove unattended recovery, then EXO1 was restarted once.

Observed readiness times (seconds from that restart request; polling/control
queries make these upper bounds, not exact internal launch timestamps):

| Run | Request CST | SSH + logged-in GUI | launchd jobs loaded | Web HTML ready | Model stage ready |
|---|---|---:|---:|---:|---:|
| EXO2 original fixed-IP plan — failed model startup | 18:22:34 | ~60.5 | ~60.5 | n/a | not ready by 300 s |
| EXO2 fixed explicit-interface plan | 18:29:40 | 40.105 | 40.105 | n/a | packer 48.533 |
| EXO1 fixed explicit-interface plan | 18:30:41 | 42.960 | 42.960 | 42.960 | lead/split 59.815 |

The first EXO2 monitor had an uncaught expected SSH-disconnect timeout; continued
read-only monitoring recorded the ~60.5 s upper bound from a whole-second start
stamp. It did not issue an extra reboot. The failed original model startup was
real: launchd/automatic login worked, but the stale bind address did not. After
the code/plan correction the second reboot independently changed en2 from
`169.254.35.180` to **169.254.201.113**, and its saved `tb://en2:5560` plan found
that new address automatically. The lead's saved `ssh+tb://.../en2:5560` peer
resolved it without manual worker startup or a data-path LAN fallback.

First post-reboot web chat replied **“Two plus two equals four.”** at 18:32:00
CST: **79.569 s after EXO1's restart request**, including inspection before
sending the prompt at 77.790 s. Thus this is an observed verification time, not
a minimum time-to-answer benchmark. It was **140.649 s after EXO2's second
restart**, including EXO1's subsequent restart and that inspection. Request wall
time **1.7794 s**, native total **1.722 s**, TTFT **0.801 s**, cold prompt 26/0
cached tokens, six answer tokens, **49.9 read / 5.43 write tok/s**. Native line
(Mini log clock, CST):

```text
18:32:00 [mlx-worker] session 7e246f9658244905: timing (split): read 26 tok (0 cached) at 49.9 tok/s, write 6 tok at 5.43 tok/s, first token 0.80 s, total 1.72 s
```

After deploying the telemetry/restart fixes, real owned-service tests passed:
- Disk cache restore after lead restart: **25/26 prompt tokens cached**,
  **5.04 write tok/s**, TTFT **0.403 s**, total **1.396 s**. Correct answer.
- The instrumented normal CLI actually reproduced native bootstrap error 5,
  observed the old job still loaded twice, then absent (113), then successfully
  bootstrapped it. **6.041 s** to ready; no root escalation or unknown-PID kill.
- Web-only owned restart: **1.190 s** to ready, KEEP_WORKERS=1; lead **2490** and
  packer **1037** unchanged. Next reply was **hit-memory**, 25/26 cached,
  **5.02 write tok/s**, TTFT **0.349 s**, total **1.346 s**; correct answer.
- Native structured rates, web stats and timing-log rates now agree on every
  post-fix reply. The earlier short MLX UI rates were inflated; their historical
  BENCHMARKS table is explicitly labeled, not silently presented as native speed.
- Omarchy reached the normal network web address with HTTP **200**, 159,019-byte
  HTML. Topology reported **2/2 online**. Read-only Balance preview at the
  unchanged 24/40 split was **safe=true, ready=true**, zero missing/download
  bytes; no download or reload was started by preview. EXO2 logical disk bytes
  **10,717,679,207**, EXO1 **10,731,498,067**, unchanged from the earlier run.

Final audited state at **18:40:39 CST** (post-reboot `pmset -g` also read
`lowpowermode 0` on both; read-only, no power-setting changes):
- **EXO1 `~/dev/caravan-v3`**: permanent launchd web **2517**, port **8190**;
  lead agent **2487** (PPID 1), its Qwen worker **2490**, localhost **8194**,
  layers **24–63**. Web is launchd-owned too; KEEP_WORKERS=1 in all generated
  jobs. The normal web adopts the fixed model and reports the actual new peer.
- **EXO2 `~/cv3` only**: permanent launchd packer agent **632** (PPID 1), its
  Qwen worker **1037**, **169.254.201.113:5560**, layers **0–23**. Packer stayed
  unchanged throughout the later lead/web restart tests.
- Three intended permanent jobs are running; logs remain under
  `~/.caravan/logs/{web,day19-qwen-lead,day19-qwen-packer}.log` on their own Mini.
  Configs remain under `~/.caravan/services/login`; loaded-job guards recognize
  them. No downloads or isolated test services/processes/listeners remained on
  **5591/5592/8196/8197/8198/5596/5606**. Existing unrelated login apps were not
  edited or individually killed; the approved reboots naturally restarted them.
- Both correct clones are on `caravan-v3-mlx-split`, tracked trees clean. The
  pre-existing untracked `proxy/web/index.html.bak-pre-amber` is preserved.
  Code commits: **4c4e128** (TB resolution), **4cb8951** (native telemetry/live
  peer), **1479fcf** (safe native restart race). Final docs are pushed/pulled too.
- Exact requested suite: **694 passed in 40.143 s**, 21 new reboot-follow-up
  regressions over 673. No cloud agent, scp, wrong EXO2 clone, release or tag.

Raw reboot/probe/error-5 traces, response JSON, final native process/job/plist
snapshots and timing results are retained on Omarchy under
`~/day19-reboot-20261108/`; EXO1 also keeps reply/post-fix JSON under
`~/.caravan/day19-reboot-20261108/`. The two native worker/web logs are the source
for the timing lines. No extra approval/action is needed to complete this reboot
test. Remaining coverage: a genuinely separate Mac/account, FileVault-on/manual
unlock, three physical Minis, GUI usability and sustained throughput runs.

**Operating mode left deliberately:** fixed Qwen auto-start. It is answering
normally, but UI Load/Stop/Balance reload/Optimize are blocked to avoid fighting
launchd. To return to interactive model switching, explicitly uninstall only
`day19-qwen-lead` on EXO1 and `day19-qwen-packer` on EXO2 using their intended
repos' service CLI; keep the web service. Do that only at a safe time, and check
current explicit UI node endpoints. UI editing of fixed auto-start plans and
automatic last-model/triangle discovery remain separate design work.


### Brenden's last-model auto-start design — Nov 8, after 18:44 CST

Brenden asked for the model used before reboot, not a permanently pinned Qwen
service. This supersedes the fixed-model operating mode documented above.

- The web owns models again. A successful MLX/GGUF load atomically writes
  `~/.caravan/web-ui/last-model.json` (schema 1, user-only permissions), before
  advertising ready. It records the actual model/engine, ordered Mini IDs,
  placement, exact Balance counts or GGUF shares and effective settings/tune.
  It stores no worker commands, PIDs, RAM/file claims, download flag or transient
  network addresses. Failed loads do not replace the last successful selection.
- Explicit user Stop writes a durable null selection. Startup then restores
  nothing. Shutdown/test cleanup does not masquerade as an explicit unload.
  Cancelling an in-flight load cannot later re-save/resurrect an unloaded model.
- The launchd **web only** restores once through `/api/models/load`, the exact
  normal UI path. Split loads use fresh Balance/files/free-memory checks and
  resolve explicit TB interfaces from the current topology. Single placements
  are rechecked against real node inventory/free memory; unknown RAM is blocked.
  There are no automatic weight downloads, fallback Mini/split changes or
  automatic retries/crash loops. The idle UI explains a missing Mini/file or
  memory shortage and remains usable for Load/another choice.
- Healthy existing owned workers are adopted on a KEEP_WORKERS web restart,
  rather than reloaded. Remote single-Mini adoption additionally verifies the
  configured SSH target, remote worker identity/model and exact local tunnel
  identity; reused/unowned PIDs are never adopted or killed.
- Model switching and Balance reload are unlocked: there is no fixed worker
  LaunchAgent in the normal mode. Remote stages are started/stopped over the
  configured already-trusted SSH control path with owned PID records. No extra
  permanent per-Mini model agent is required by that path; EXO2 must be awake,
  reachable and (for Metal) logged in. `CARAVAN_WEB_RESTORE_LAST=0` disables only
  startup replay, not saving successful choices.
- Normal Settings/Models split loads also go through the N-node planner rather
  than the obsolete two-node IP defaults. The explicit legacy force escape
  hatch remains manual-only and is never saved/replayed by restore.

Regression coverage includes atomic persistence/failure, explicit unload,
failed-load preservation, exact 3/4-stage counts/placements, engine/settings,
missing Mini/files/unknown or insufficient memory, corrupt intent, no download
or command replay, user cancellation/late-token races, KEEP adoption, remote
worker/tunnel PID reuse and the actual shared HTTP load/Stop routes. Older HTTP
fixtures now use temporary state folders, not durable preferences inside the
repository. Native migration/reboot/switch results follow after validation.

Box validation of the revised design: **737 tests passed in 43.429 s**, 43 new
regressions over 694. Native migration/reboot checks begin after this commit.


### Web-owned migration: native success, reboot blocked — 19:12 CST

Implementation commit: **e0928ad** was pushed and pulled to EXO1
`~/dev/caravan-v3` and EXO2 **`~/cv3`** before migration. The trees were clean
apart from the preserved, pre-existing web HTML backup. No cloud agent, scp,
release/tag, login/security/network setting change or automatic weight download.

Completed:

- Explicitly uninstalled only our `day19-qwen-lead` on EXO1 and
  `day19-qwen-packer` on EXO2. Their jobs/configs/plists were removed; model
  shards/cache/logs kept. Kept the real EXO1 web job and its
  `CARAVAN_WEB_KEEP_WORKERS=1`. Remote MLX stages now belong to the web, not a
  fixed-model launchd job. No extra per-Mini permanent model agent is needed.
- Backed up EXO1's config as `~/.caravan/config.toml.day19-pre-last-model`.
  Explicit EXO2 inventory uses the existing trusted control host and `~/cv3`,
  `peer="ssh+tb://brenden@100.90.134.95/en2:5560"`,
  `listen="tb://en2:5560"`. No host-key/trust/routing changes.
- Restarted only the owned web service. Normal web/UI load API (not a manually
  fabricated saved file or model-specific agent) loaded Qwen3.5-27B **24/40**
  on ordered Minis **EXO2, EXO1** in **10.121 s**. It wrote a private `0600`
  `~/.caravan/web-ui/last-model.json` with engine MLX, exact IDs/counts, split
  placement and UI settings. No managed-service lock remained. Fresh Balance
  preview was safe/ready, zero missing downloads. Existing own-shard stores:
  EXO2 **10,717,679,207 B**, EXO1 **10,731,498,067 B**.
- Actual inference answered **“Two plus two equals four.”** at 19:05:56 CST.
  Six output tokens / 26 cold prompt tokens; wall **1.7471 s**, native total
  **1.720 s**, TTFT **0.802 s**, prefill **0.522 s**, read **49.8 tok/s**,
  write **5.45 tok/s**, lead peak **9.51 GB**. Native and UI rates matched.
  This is a short correctness/timing smoke test, not sustained throughput.
- The first two harness requests were safely rejected before starting workers:
  it incorrectly used `fuse_kernels=off` (and would also have used unsupported
  `keepalive=on`). These UI choices are `auto/on` and `auto/off` respectively;
  corrected to Auto for both. Actual runtime remained fused-off / keepalive-on.
  Added a regression that both bad inputs return HTTP 400, start no worker and
  leave the previous successful saved intent byte-for-byte unchanged.

**Reboot result — blocked, not a restore pass:**

- Before EXO2 restart, `autoLoginUser=brenden`, FileVault **Off**, and the
  System Events restart call returned **0**. Request time
  **2026-11-08 19:05:56.320 CST**. Previous kernel boot was 18:29:56 CST.
- The bounded **360 s** monitor never observed SSH returning through Omarchy;
  it exited failed after roughly 6 minutes. An independent final check at
  **19:12:33 CST** still returned SSH exit 255 / connection timed out.
  No SSH-up, GUI/TB-ready, restored-service or post-reboot answer times exist.
  Do not substitute the earlier fixed-model reboot measurements for these.
- **Stopped before rebooting EXO1.** Did not send another EXO2 restart, force
  power, change login/security settings or attempt another access route.
  The cause is unknown: SSH absence does not prove whether EXO2 is powered off,
  at a login screen, stalled during restart or only missing its network service.
- EXO1 remains reachable: web LaunchAgent **6835**, owned Qwen lead **7134**,
  logs `~/.caravan/logs/web.log` and `~/.caravan/web-ui/lead.log`.
  Only the web permanent job remains; neither old fixed plist/job nor test
  listeners 5591/5592/8196 exists on EXO1. Saved intent still says Qwen MLX
  split EXO2/EXO1 24/40. No explicit Stop was sent (which would erase that
  preference). The local lead health check still says ready, but split status
  reports **“Remote end closed connection without response”**: this is **not a
  working two-Mini split** while EXO2 is unreachable. EXO2's current process,
  login and download state cannot be verified remotely; fixed-job removal was
  confirmed before reboot.

Brenden needs to check EXO2 locally: power/display, completed restart, logged-in
session and normal network/Tailscale availability. No security changes are
requested. After ordinary `ssh exo2` works again, resume (not a release):

1. Through Omarchy, inspect EXO2 boot time/login/TB and clean tree/branch, then
   `ssh exo2 'cd ~/cv3 && git pull --ff-only origin caravan-v3-mlx-split'`.
   **Never use `~/dev/caravan` on EXO2.** EXO2 had e0928ad before restart; the
   final docs/test-only follow-up cannot be pulled while SSH is down.
   EXO1 sync is `ssh exo1 'cd ~/dev/caravan-v3 && git pull --ff-only origin caravan-v3-mlx-split'`.
2. Reload Qwen in normal web Balance with ordered nodes EXO2/EXO1, counts24/40
   (or the prepared `ui_check.py qwen recovered-qwen`), answer a prompt and
   verify saved intent. This resolves fresh TB addresses and replaces only
   owned stages; it does not reinstall the removed fixed jobs.
3. Recheck EXO1 automatic login/FileVault, then approved EXO1 reboot monitor
   `reboot_check.py exo1 exo1`. The web must replay the saved request itself;
   do not manually start the model after reboot. Record SSH/web/ready times
   and a correct native timing line. Stop on a failed return.
4. Only after that succeeds, normal UI load Orvena 4B, answer, check the saved
   single-EXO1 intent and replay it without another reboot. KEEP web restart
   should adopt the same PID. Explicit Unload should save null; web restart
   should remain idle. Finally load/answer Qwen24/40 and leave it selected.
   These live switch/replay/unload/restart checks remain **deferred**, not passed.

Prepared monitors and full migration/load/response/error JSON are on Omarchy:
`/home/brenden/day19-lastmodel-20261108/`; EXO1 response/status artifacts are
under `~/.caravan/day19-lastmodel-20261108/`. Relevant files include
`migration.json`, `migrated-qwen.json`, `migrated-qwen-answer.json`,
`exo2-reboot.json`, `blocked-final-connectivity.json`, and
`blocked-after-exo2-reboot.json`. These are retained evidence, not test services.

Final box validation: **738 tests passed in 44.459 s**, **44 new** over 694.
The additional case protects failed-input persistence. Full log:
`/workspace/day19-lastmodel-final-tests.log`. Implementation and native API
migration passed; **unattended last-model reboot restoration has not yet been
proved**. The final docs/regression commit changes no live runtime code, so
EXO1 does not need another web restart just to pull it.

## 2026-11-09 remote-access recovery (CST)

Brenden found EXO2 Tailscale off and needing an update. Only the Tailscale
`/etc/hosts` alias had been tried previously; LAN SSH was not tested then.
After today's move/boot, EXO2 returned. Added known-key LAN aliases on Omarchy,
a verified Tailscale-independent `exo2-via-exo1` Thunderbolt ProxyJump, an
on-demand fallback helper, and non-root two-minute Tailscale recovery guards
on both Minis; auto-update/start-at-login were already enabled. **5/5 real
SSH paths**, **16/16 mocked guard cases**, **3/3 fallback-order cases** passed.
No Caravan restart/reboot/model load; EXO1 web/lead remain 6835/7134, while EXO2
has no Caravan packer listener. The Day 19 restoration/reboot test remains
pending. Both Mini repos have an existing untracked HTML backup; no pull or
cleanup was attempted. Box regression: **738 tests passed in 43.514 s**.
Full inventory, installation paths, rollback/manual steps and limitations: [REMOTE-ACCESS.md](REMOTE-ACCESS.md).

## Day 19 closeout — 2026-11-09 CST (no reboots)

Brenden approved wrapping up without reboots so he can use Hermes. **Restore-last-model reboot test: pending, deferred to the next dev day.** Live model-switch/replay/unload semantics remain unverified; no such extra test or web restart was run. No Day 19 video or X draft now.

- EXO2 `~/cv3` clean tracked tree pulled ff-only from e0928ad to 8ff3852; EXO2 `~/dev/caravan` never touched. Existing untracked HTML backups left alone on both Minis.
- Web status, lead process arguments and saved intent all identified the same **mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit** (not plain Qwen). Kept that model and ordered EXO2/EXO1 **24/40** split.
- Initial saved-request reload safely returned HTTP 409: stale lead retained memory and preview showed insufficient EXO1 headroom (9.1 GB capacity vs 11.33 GB estimate). No guard bypass. Normal UI Stop removed only the stale owned stages (8.353 s), then normal Balance load restored the **same Huihui** model in **11.583 s**, with refreshed Thunderbolt peer 169.254.155.4:5560 and durable last-model intent. No weights downloaded, no machine reboot, no web restart.
- Web `/v1/chat/completions`: “Two plus two equals four.” 6 output tokens / 26 prompt; TTFT **0.799 s**, read **50.0 tok/s**, write **5.40 tok/s**, native total **1.725 s** (HTTP wall 1.7523 s), peak 9.51 GB.
- Proxy :8090 was not running (connection refused). Started only the existing stdlib proxy on **127.0.0.1:8090**, MLX target **127.0.0.1:8194**, prefixes `mlx-community/,huihui-`, with `CARAVAN_SLOT_CLEANUP=off` (no deletion). Log `~/.caravan/logs/day19-proxy.log`. This is a manual background process, not a new auto-start service; Hermes should use its SSH tunnel, not a public bind.
- Proxy chat: “Three plus three equals six.” 6 output / 23 prompt tokens; TTFT **0.798 s**, read **44.3 tok/s**, write **5.41 tok/s**, native total **1.723 s**, peak 9.62 GB. These are tiny correctness smoke tests, not sustained benchmarks. No further model load for release work.
- Remote access commit **8ff3852**: LAN and Thunderbolt SSH fallbacks plus two-minute non-root Tailscale recovery guards; 5/5 real SSH paths, 16/16 mocked guard and 3/3 fallback-order cases. Guards cannot guarantee recovery before login or from power/hardware/auth failures; see REMOTE-ACCESS.md.

Evidence: Omarchy `/home/brenden/day19-lastmodel-20261108/day19-pre-wrap-status.json`, `day19-wrap-stale-stop.json`, `day19-wrap-huihui-load.json`, `day19-wrap-web-chat.json`; native API records on EXO1 `~/.caravan/day19-lastmodel-20261108/`. Initial rejected load retained in `day19-wrap-huihui-load-output.log` only until the successful harness run replaced that output; the 409 details above preserve its result.

Release tag is **day19-2026-11-08** (development-day date; publication Nov 9 CST). Source packages exclude models, dependencies, compiled runtimes and exported video media. Install instructions: INSTALL.md and docs/SERVICES.md. Separate-account/FileVault-on install, three physical Minis, strict GGUF file independence, N-stage Optimize and sustained GUI/performance checks remain open. Historical results above are checkpoints, not evidence that the deferred reboot test passed.

Closeout full box suite: **738 tests passed in 42.600 s**, zero failures/skips. Log `/workspace/day19-release-tests.log`. `git diff --check` passed. Obsidian updated on Omarchy: `~/Documents/obsidian/Projects/Caravan/Day 19 Wrap-up.md` and `Day 18 Wrap-up.md` (existing v25 video metadata recovered, not new media work).

### Published release and package verification — 2026-11-09 CST

- Release: https://github.com/linuxbren/caravan/releases/tag/day19-2026-11-08
- Immutable annotated tag `day19-2026-11-08` targets **7267325a33d2c1a0990322773b33621ccad36beb**. Development branch pushed; main fast-forwarded from 1ccdb15 to the same commit, no rewrite. Working branch remains `caravan-v3-mlx-split`.
- Published clean-tree ZIP **18,826,133 B**, SHA256 `adf9247eefd99b684ca37e198908773a5cb0c3315ced4202b507330b8185a93c`; tar.gz **17,942,822 B**, SHA256 `92e31ed10d622f56b9ef0727112849426228e2e667253b36fca82660e4ee4446`. ZIP integrity passed, INSTALL.md and SERVICES.md present.
- Downloaded the published tar.gz to fresh `/workspace/day19-release/verify/`; SHA256 matched, extracted INSTALL.md checked. Full extracted suite: **738 tests passed in 42.081 s**, zero failures/skips; log `/workspace/day19-release-package-tests.log`. Original full suite: **738 passed in 42.600 s**. No failed suite in this closeout; earlier failures remain documented above.
- Both Minis clean tracked trees pulled ff-only to release commit, existing untracked HTML backups preserved. Docs-only changes: no service restart, no reboots. Same Huihui 24/40 model left selected for Hermes.
- This follow-up documentation records publication without moving the release tag/assets. Restore-last-model reboot test remains **pending, deferred to the next dev day**; no Day 19 video or X draft.

## Day 19 video + X draft

Real UI tour (Huihui stayed loaded; read-only Chromium screencast via Omarchy
tunnel `:18190` → EXO1 `:8190`):

- File: `/workspace/caravan-day19.mp4` (also staged under Omarchy
  `~/day19-video/` after copy)
- Length: **54.2 s**, 1280×720 H.264, silent, 14 single-line bottom captions
- No dates or times on screen (generator asserts this)
- Captions: `handoff/lab/videos/day19_captions.txt` (and `/workspace/d19v/day19_captions.txt`)
- Generator: `handoff/lab/videos/make_day19_video.py`
- Footage: home (Huihui ready), Models, Topology/Balance 24/40 EXO2/EXO1,
  Settings, plus cards for remote-access hardening and 738-test release

X draft only (Brenden posts): Omarchy
`~/Pictures/x-posts/day19/draft.md` and `draft-long.md`. Date-free.

Related self-tune short: `/workspace/caravan-selftune-5s.mp4` (**5.000 s**,
on-screen **41.53 → 69.70** tok/s). Huihui restored afterward; see DAY20.md.

## Day 19 video v2

`/workspace/caravan-day19-v2.mp4` (~56.8 s). Real UI only; no test counts.
Captions are plain and benefit-led (no launchd / pipeline / shard jargon).
Closing “For the nerds” line only: Huihui 24/40 on EXO2 then EXO1.
Generator: `handoff/lab/videos/make_day19_video_v2.py`. Captions:
`handoff/lab/videos/day19_captions_v2.txt`. X draft still review-before-Brenden.

## Day 19 video v3

`/workspace/caravan-day19-v3.mp4` (also Omarchy `~/day19-video/caravan-day19-v3.mp4`).
**31.6 s**, 1280×720, silent, human benefit-led captions, no dates, no test counts.

Real motion in the first 3 s: a live chat on the Caravan web UI (headless
Chromium viewport 1280×720 via Omarchy `:18190` → EXO1 `:8190`). Question:
“Name three fruits that are usually red.” The reply streamed live (Apples…).
Tight crops hide the model name, feature pills, MODELS list, and Settings
“in our tests” copy.

Path switchover is a real demo (2026-11-09 **19:34:46–19:35:16 CST**,
America/Chicago). LAN and Thunderbolt paths were confirmed up first. Tailscale
was taken down on EXO2 via the LAN path; `exo2` became unavailable;
`caravan-ssh` fell through to `exo2-lan` (`reached_via_fallback`). Tailscale
was brought back with `tailscale up`; final paths all OK (`exo2`, `exo2-lan`,
`exo2-via-exo1`). Huihui was not unloaded for this demo. Terminal footage is
the real log with timestamps stripped so the clip stays date-free.

**Reboot / pull-the-plug test: not run.** `sudo reboot` on EXO1/EXO2 requires
an admin password this session could not supply (`sudo: a password is required`;
`reboot: Operation not permitted`). Restore-last-model and `:8090` launchd
recovery remain deferred. Prefs already saved for Huihui 24/40 EXO2/EXO1.

Window capture: v3 chat is a **headless page-viewport** screencast at exactly
1280×720 (not a Hyprland-tiled window). A temporary `hyprctl keyword windowrulev2`
attempt failed (non-legacy parser) and did not change running rules. Headed
v3 tries earlier were **1265×720** and could look cut off on the desktop.
**Day 19 v2 / earlier self-tune UI stills were already 1280×720 headless** and
were not clipped the same way; what Brenden saw was the on-desktop headed
window, not the v2 file.

Generator: `handoff/lab/videos/make_day19_video_v3.py`. Captions:
`handoff/lab/videos/day19_captions_v3.txt`. X videos still go to review
before Brenden.


## Restore-last-model reboot test — 2026-11-09 19:46–19:55 CST (America/Chicago)

Brenden rebooted **both Minis at once**. Result: **partial fail**. launchd brought
the web UI (`com.caravan.v3.web` on `:8190`) and the `:8090` proxy
(`com.caravan.v3.proxy`) back on their own. Restore-last-model **did run**, then
**blocked** and **did not retry**. Huihui was not loaded again until a manual
Load after the five-minute no-touch window. After that Load, the same
**24/40 EXO2 then EXO1** split was ready and a Hermes-path reply through
Omarchy `:18090` succeeded.

All times below are America/Chicago (CST), from the 1-second reachability
poller (`~/day19-video/reboot-watch/logs/reachability.log` on Omarchy), EXO1
`who -b` / web uptime, and worker progress timestamps.

### Timeline

| Event | Time (CST) |
|---|---|
| Both Minis, `who -b` boot stamp (minute resolution) | 19:46 |
| EXO2 SSH down on every path (`exo2`, `exo2-lan`, `exo2-via-exo1`) | **19:46:18** |
| EXO1 web vanished from the Omarchy `:18190` tunnel; EXO2 ping down | **19:46:24** |
| EXO1 SSH down on every path | **19:46:30** |
| EXO2 LAN SSH back | **19:46:40** (22 s after EXO2 SSH down) |
| EXO2 Tailscale SSH (`exo2`) back | **19:46:53** (35 s) |
| EXO1 LAN SSH back; EXO1 ping back | **19:47:04** (34 s after EXO1 SSH down) |
| EXO1 Tailscale SSH (`exo1`) back | **19:47:11** (41 s) |
| EXO1 web `:8190` actually listening (launchd) | **~19:47:05** (uptime back-calc at 19:52:36 was 331.1 s) |
| Auto-restore started (last model Huihui) | **19:47:05.163** |
| Auto-restore blocked | **19:47:06.735** |
| Five-minute no-touch after both SSH were up ended; still blocked, no model | **19:52:11** |
| Omarchy `:18190` web tunnel restarted (it is not a KeepAlive unit; it died with the reboot, so the poller kept reporting web down even while `:8190` was up) | **19:54:12** |
| Manual `POST /api/models/load` (same 24/40 EXO2/EXO1 split) | **19:54:24** |
| Huihui ready again, counts `[24, 40]`, `node_ids: ["exo2","exo1"]` | **19:54:38** (12.1 s load) |
| First Hermes-path reply through `:18090` (stream, HTTP 200) | start **19:55:03**, wall TTFT **0.487 s**, wall total **2.917 s** |
| Follow-up non-stream reply with official Caravan timings | **19:55:16–19:55:26**, `ttft_s=0.314`, `total_s=9.844`, `how=hit-memory`, read **34.5** tok/s, write **6.61** tok/s |

### What failed

Exact worker / restore message:

> Could not restore last model: live free memory is unknown for exo2. Check Minis/files/memory, then press Load. No automatic retry or download.

`restore.phase` stayed `blocked`. The attempt happened about one second after
the web process came up, while EXO2 was already SSH-reachable, but live RAM
for exo2 was not known yet. The code path does not retry. During the whole
five-minute no-touch window the model stayed unloaded.

By **19:53:14** `/api/nodes` showed both Minis online with known memory
(EXO2 `available_gb` 16.7, `free_gb` 17.6). A normal Load then succeeded.

### What still worked after the fix

- Same Huihui model, same **24/40** split, same order **EXO2 then EXO1**.
- Thunderbolt packer peer `169.254.195.205:5560`.
- `:8090` was listening from login (launchd). `GET /v1/models` on `:8090`
  still returns **502** `llama-server upstream unreachable` even when the MLX
  lead is healthy — the same before the reboot (the poller's `:8090` / `:18090`
  "health" was 502 while Huihui was ready at 19:45). Chat completions with the
  Huihui model id through the Hermes tunnel **do** work.
- First Hermes-path stream at 19:55:03 produced reasoning tokens (the probe
  used `max_tokens=16`). The 19:55:16 non-stream follow-up (`max_tokens=64`)
  finished `length` with visible content starting
  `The instruction is to "Say only: hermes-ok"...` — same shape as the earlier
  Day 20 Hermes check.
- Watchers (poller + 2 fps headless 1280×720 capture) were stopped at **19:55:50**
  after that confirmation. Frames and the reachability log remain under
  Omarchy `~/day19-video/reboot-watch/`.
- `exo2-via-exo1` stayed down for the whole watch and was still timing out
  after the test. Direct `exo2` and `exo2-lan` were fine.

No further model unload was done. Huihui 24/40 EXO2/EXO1 was still ready
after the v4 chat probe below.

## Day 19 video v4

`/workspace/caravan-day19-v4.mp4` (also Omarchy `~/day19-video/caravan-day19-v4.mp4`).
**32.000 s**, 1280×720, silent, H.264, SHA256
`545c6fd72f1114b40148c6e9675aeffd572251af26cb8ac92006dcd592a040c3`.

Phone-readable type. Full question and a complete wrapped answer with no raw
`**` markdown. Typing ~1 s; first reply words already on screen at 2.0 s.
Switchover is a big status view drawn from the real 19:34:46–19:35:16 CST
fallback log (`Main connection: off` / `Backup connection: on, switched by itself`).
End cards are 2 s each. Reboot beat uses the real "Caravan unreachable"
capture plus an honest status view: computers and the web service came back
on their own; automatic model restore was blocked; a Load brought the same
split back. The clip does **not** claim the model came back by itself.

The on-screen question is the same live v3 question, “Name three fruits that
are usually red.” The complete answer is a real post-restore Hermes-path
reply to that question at **19:58:19–19:58:37 CST** (`thinking` off, like the
v3 UI), markdown stripped for display:

> Here are three fruits that are usually red:
> 1. Apples (specifically varieties like Red Delicious or Fuji)
> 2. Strawberries
> 3. Cherries

Captions (`handoff/lab/videos/day19_captions_v4.txt`):

```
  0.0s  Ask a simple question. Watch it answer live.
  2.2s  The words show up as they're written.
 12.0s  If the main path drops, another way in is ready.
 16.0s  It switched on its own. Everything stayed reachable.
 20.0s  Pull the plug, the computers come back on their own.
 24.0s  The model needed a Load. Then the same split was ready.
 28.0s  Two Macs. One model. Built in the open.
 30.0s  For the nerds: Huihui 24/40 on EXO2 then EXO1.
```

Generator: `handoff/lab/videos/make_day19_v4.py`. X videos still go to review
before Brenden.


## Reboot follow-up correction and readiness fix — Nov 9, 2026 CST

**Automatic restore FAILED.** At 19:47:05 CST the web's initial restore POST
returned 400: `live free memory is unknown for exo2`; the previous controller
blocked permanently, with no automatic retry. A different executor manually
loaded Huihui at 19:54:24; ready about 19:54:38. The follow-up executor's earlier
“eventual automatic restore” inference was wrong and is superseded here.

Omarchy's unmanaged :18190 SSH tunnel also died in the reboot and was manually
restarted at 19:54:12. Thus tunnel HTTP failure did not establish local-web
failure. Launchd web and proxy had started at 19:47:04. SSH milestones from the
watcher: EXO2 down 19:46:18, both down 19:46:30; EXO2 primary back 19:46:53,
EXO1 primary back 19:47:11 (row timestamps precede sequential probes).

The verified synthetic Hermes-style POST via :18090 at 19:58:35–56 CST completed
with `Caravan is back online.` HTTP 200, 21.350 s wall; worker 18.656 s,
TTFT .805 s, prefill .525 s, write 6.55 tok/s. This was not an actual Hermes
application/full-tool-prefix benchmark. GET `/v1/models` 502 predates reboot:
that discovery GET goes to the absent default llama backend; model-bearing MLX
chat POSTs route correctly. No proxy discovery change is included in this fix.
Thunderbolt inference uses EXO2 169.254.195.205 via EXO1 en2; the stale IPv6
`exo2-via-exo1` SSH alias does not indicate failed inference transport.

Fix: restore readiness preflight retries offline/unknown-free-memory errors
with 2, 4, 8, 16, then up to 30 s backoff, bounded to ten minutes. Each attempt
reuses the same saved model, exact N-Mini placement/counts/settings and guarded
UI load endpoint. Missing files, insufficient known free RAM, busy unadopted
workers and ambiguous transport timeouts still fail closed without retries or
downloads. User Stop/switch cancels backoff immediately and invalidates the
restore token; unload retains its durable null intent. Existing ready workers
are adopted without reload on a KEEP_WORKERS web restart.

Omarchy tunnels are managed by systemd user services with Restart=always,
ExitOnForwardFailure, SSH server keepalives and five-second restart delay.
Fresh reboot-watch2 probes distinguish local web, local MLX, packer, tunnels,
process/reconnect state and model-bearing proxy chat. A second Brenden-issued
reboot is REQUIRED to prove the fix. No reboot is issued by this executor.
First-run evidence remains in `~/day19-video/reboot-watch/logs/` and frames/.

Deployment detail: the existing `hermes-caravan-tunnel.service` already had
Restart=always and recovered at 19:47:05 CST (3 restarts); left untouched.
Added/enabled `caravan-web-tunnel.service` for :18190, replacing only the
verified unmanaged web SSH process. No model/network/security settings changed.


## Both-Mini reboot #2 — unattended restore PASS, Nov 9, 2026 CST

Brenden rebooted both Minis after the READY baseline on **9242f21**. The
executor observed only: **no manual Load, service restart, network edit, or
reboot command** during recovery. Saved Huihui 24/40 returned automatically.
The previous failed first reboot remains a failure; this separate run is the
first proven successful web-owned last-model both-Mini restore in this session.

### Native evidence timeline (all CST)

| Milestone | Timestamp | Evidence / qualification |
| --- | --- | --- |
| First EXO1 proxy-over-SSH probe failure | 20:06:44.009 | `exo1-chat8090.jsonl`; last baseline green before shutdown |
| Both Omarchy tunnels down / systemd auto-restart | 20:06:45.517 | `tunnels.jsonl` |
| EXO1 local-status SSH probe down | 20:06:47.506 | `exo1-local.jsonl` |
| EXO2 SSH probe down | 20:06:51.506 | `exo2-packer.jsonl` |
| EXO1 kernel boot time | 20:07:01 | native `sysctl kern.boottime` |
| EXO2 kernel boot time | 20:07:05 | native `sysctl kern.boottime` |
| EXO1 LAN SSH back | 20:07:15.226 | `lan-paths.jsonl` |
| EXO1 launchd web / proxy processes started | 20:07:15 | native `ps lstart`, PIDs 661 / 647; launchctl snapshots retained |
| Both supervised tunnel processes successfully restarted | 20:07:19 | systemd `ExecMainStartTimestamp`; PIDs 1616346 / 1616347 |
| EXO2 LAN SSH back | 20:07:20.369 | `lan-paths.jsonl` |
| EXO1 primary SSH / local :8190 HTTP 200 | 20:07:21.301 | worker idle, restore preparing; :8194 not ready yet |
| Both Omarchy tunnel endpoints HTTP 200 | 20:07:23.546 | :18190 status / :18090 proxy-status, NOT model-readiness proof |
| EXO2 primary SSH back | 20:07:24.646 | :5560 not yet listening |
| Automatic restore starting packer | 20:07:38.178 | local status; packer process start 20:07:38, PID 1151 |
| EXO2 packer port listening | 20:07:42.831 | local lsof; no extra client connected to single-head protocol |
| EXO2 24-layer packer ready | 20:07:42.709 | worker progress timestamp |
| Saved 24/40 split fully loaded / healthy | 20:07:48.742–.744 | native worker progress; durable intent saved .744 |
| First model-bearing :8090 chat probe HTTP 200 | 20:07:50.302 | 1 output token; route/inference check, not complete human reply |
| First full :18090 MLX chat request sent | 20:07:51.664 | synthetic Hermes-style request, not an actual Hermes app turn |
| Full :18090 assistant reply complete, HTTP 200 | 20:08:03.913 | `Caravan recovered automatically.` / finish_reason=stop |
| Probe watchers stopped / capture stop requested | 20:08:42.774 | surviving capture loop finally stopped 20:09:43.347; tunnels/services left running |

The model was loaded about **64.7 s after the first observed EXO1 transport
failure** (or 57.2 s after the first EXO2 SSH-down sample). These are sampled
observations, not exact power-off times: probe timestamps mark completion,
SSH/connect timeouts can add seconds, and the LAN watcher started while both
were already down at 20:06:54.197. It cannot supply earlier LAN-down times.

### What recovered and what this run does not prove

- Exact model: `mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit`;
  EXO2 front 24 / EXO1 head 40, pipeline_chats=1, self_tune=false. Lead PID 1375.
  Thunderbolt peer refreshed automatically to **169.254.99.64:5560**.
- Restore phase was preparing by 20:07:21 and **restored** by the first ready
  samples at 20:07:49.572 (tunnel) / 20:07:49.941 (local). Native load completion
  was 20:07:48.744. Post-boot web audit contains a single successful
  `POST /api/models/load` HTTP 200, no 400, with no manual control call.
- **No retry/backoff phase was observed in this physical reboot.** Initial
  guarded preparation waited for inventory and succeeded once peers were up.
  This run proves unattended recovery on the retry-enabled build and both
  supervised tunnels; the specific transient 400→backoff→200 branch is covered
  by focused unit/guarded HTTP tests, not independently forced on hardware here.
- Both tunnel services retried automatically three times during this reboot:
  web NRestarts 0→3, Hermes 3→6. Their final process start was 20:07:19; actual
  HTTP reachability was proven separately at 20:07:23.546. No manual SSH tunnel
  was launched during recovery. The systemd services remain enabled/running.
- Full :18090 reply: **12.249 s wall**, worker **12.201 s**, **TTFT 0.815 s**,
  prefill **0.530 s**, **6.50 write tok/s**, 26 prompt / 75 completion tokens,
  cold cache. No full-tool 13k-prefix Hermes performance claim is inferred.
- During that full reply, 1.5-second web-status probes and a 6-second concurrent
  synthetic chat probe timed out briefly, then recovered without intervention
  by 20:08:04–05. The completed user-visible reply did not fail. These strict
  probe deadlines should not be misreported as a second reboot/service outage.
- No further reboot is required to establish this run's pass. No video made.

Raw evidence on Omarchy: `~/day19-video/reboot-watch2/logs/` contains
`exo1-local.jsonl`, `exo2-packer.jsonl`, `exo1-chat8090.jsonl`,
`lan-paths.jsonl`, `tunnels.jsonl`, per-host `*-service-starts.jsonl`,
`*-launchd-*.txt`, `final-status.json`, `restore-request-audit.txt`,
`automatic-recovery-chat18090.json`, and `stopped.txt`. Frames remain in
`~/day19-video/reboot-watch2/frames/`. The capture log's raw ISO timestamps
are UTC; the timeline above is converted to America/Chicago CST.
