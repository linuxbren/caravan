# Each Mini keeps its own files

## Current package layout

| Package file | Purpose |
|---|---|
| `install` | Mac bootstrap: preflight, verified source/runtime, browser |
| `packaging-version` | Channel's exact source commit and archive SHA-256 |
| `requirements-mac.lock` | Exact versions for easy-package Python wheels |
| `scripts/install.sh` | Source/environment and owned login-service installation |
| `tools/caravan.py` | User command and safe single-service controls |
| `tools/caravan_doctor.py` | Read-only checks and human-readable fixes |
| `scripts/package.sh` | Committed-tree source archive and checksum |


The simple Mac package keeps its source at `~/.caravan/src/caravan`, Python and
uv under `~/.caravan/runtime`, the MLX environment under `~/.caravan/venvs/mlx`,
and its command at `~/.caravan/bin/caravan`. Models are downloaded separately.
Source updates retain the previous source folder. Uninstall removes only a
selected owned login service and preserves models, settings, caches and source.
See [INSTALL](../INSTALL.md) for recovery and [PACKAGING](PACKAGING.md) for limits.

MLX shard placement and Balance disk accounting are current through Day 21.
The GGUF lead still needs the full file; independent per-Mac tensor loading is
Day 22 work, not a package feature. No installer copies lab models or SSH keys.

Box-side experimental checkpoint; **not yet run on the working Macs**. No new
inference-speed claim. [Day 19 test record/live checklist](DAY19.md).

## What the UI does

In Topology → **Balance · each Mini’s files**, press **Auto / refresh**. The
separate model selector includes incomplete installed models (Settings still
blocks loading incomplete models). Choose a model, then adjust a layer boundary:

- Every MLX stage has an exact contiguous layer range, required **whole** shard
  list, missing list/known download bytes, estimated RAM/headroom, and local
  logical/allocated disk bytes. A shard crossing a boundary is necessarily
  stored by every stage needing a tensor in it. Tied embeddings and shared
  weights also legitimately require copies; this is not tensor-level repacking.
- Files **not needed for this proposed plan** are listed and kept. This does
  **not** mean they are safe to delete: another split, a fixed service, or an
  alternate model plan may use them. There is no automatic pruning or per-shard
  delete button. Existing explicitly requested whole-model cleanup is separate.
- **Fetch missing files on each Mini** is explicit. It freezes the chosen counts,
  rechecks the server's configured nodes/inventory, and starts per-node jobs.
  Each node gets its bytes from Hugging Face, using **its own** credentials.
  Only small JSON plans travel by SSH; no weights are relayed by the lead.
- Fetch does not stop/reload workers, change launchd plans, or start inference.
  After success, inspect the refreshed plan, then explicitly reload. A normal
  preview never fetches weights. Unknown files/RAM cannot make Reload green.
- Stop targets unique recorded transfer PIDs after checking the command/UUID,
  not every process for a repository. Partial files remain resumable. Downloads
  also appear in the normal job list. A missing process/SSH error is not success.
  Detached transfers survive a web-only restart; owned running transfers are
  rediscovered from verified PID/UUID records. Duplicate writers are refused.
  Each MLX stage persists its placement itself on success, even if web went away.
  After stopping a rediscovered transfer, refresh the same Balance counts and
  Fetch again to resume; completed job history is not rebuilt after a restart.

All participating nodes need this branch and a working Caravan Python/HF setup.
Unchanged jobs are blocked from racing a second download for the same repo.
Disk usage includes metadata and partial/cache files below the model folder;
allocated bytes dedupe hard links, and symlinks are listed, not followed. Linked
model folders/files need their real, own-folder paths before selective fetching.

## MLX: N-stage picker, storage and safety

The legacy picker can now select 3+ configured stages. This bridges to the same
Balance/file planner, rather than fetching the old front half on every packer.
It saves ordered `node_ids`, `split_counts`/`layer_plan`, and paths on each Mini;
inventory/catalog/normal Load preserve that N-stage plan. There is no default
two-node cap; `CARAVAN_MAX_SPLIT_STAGES` remains an explicit operator cap.
N-stage Optimize, speculative/concurrent features remain gated as in theme 1.
The two-stage legacy downloader remains for compatibility (custom model roots
use the new bridge). Do not mistake its older download records for cryptographic
proof of a revision.

The new fetch path pins **one immutable Hub revision across the whole job**.
It validates config/index against the preview before changing the model folder,
refuses incompatible existing metadata, and verifies published LFS SHA256s
where present. Correct-size corrupt shards are not silently accepted or removed:
the error asks you to inspect/move them aside. Worker startup still performs its
own header/size validation. A source update cannot quietly mix new shards with
old ones. New fetches record `caravan-source.json`; subsequent Balance fetches
prefer that installed revision. Legacy models without that record must match
current source metadata/checksums; mismatches require an explicit migration.

Default new model folder on each node: `~/.caravan/mlx-models/owner--repository`.
Existing inventory paths are retained. Optional per-node settings:

```toml
[web.nodes.sim3]
# Keep the existing host/SSH/repo/listen/upstream settings from theme 1.
model_root = "~/.caravan/mlx-models-sim3"
python = "~/.caravan/venvs/mlx/bin/python"
physical_id = "same-physical-Mini-as-the-other-worker"
```

`model_root` is inspected on that node and used for new fetches. Simulated nodes
sharing a physical Mini must use **distinct folders**; duplicate host/folder
plans are refused before a process starts. Set the same `physical_id` on those
nodes so Balance divides their RAM budget instead of inventing more RAM. This
simulates ownership/chain behavior, not another GPU or a speedup.

## GGUF: useful improvement, not complete independence

**Stock llama.cpp still needs the complete GGUF on the lead.** It parses/reads
that file to load the model and obtain hashes; this Caravan change does not
pretend a partial GGUF can replace it. The picker now fetches the complete file
**only on the lead**, instead of copying it to every online Mini.

For peers, the Balance file view supports experimental direct-source tensor
cache population for any number of physical RPC Minis:

1. Use an installed, single-file GGUF on the lead. Its picker download records
   the original repo/filename. For an older/manual copy, enter that source in
   the view. It must publish an LFS SHA256 and match the installed lead file.
2. The first preview hashes that local GGUF and its large tensors. It may take
   a while; it does not download model bytes. Offset/checksum plans are cached
   under `~/.caravan/file-plans`, bound to local inode/size/mtime and source SHA.
3. GGUF controls are **device shares**, lead first, not MLX layer counts.
   Changing a share replans exact assigned tensor ranges (including llama.cpp's
   output slot). Auto uses available RAM proportions; explicit reload uses the
   same previewed shares, rather than choosing another split after fetching.
4. Fetch reads only assigned tensors **over 10 MiB**, via bounded HTTP Range from
   a pinned source revision. Resume continues the remaining range; non-206,
   wrong Content-Range/length and checksum mismatch fail closed. No fallback
   full-file download on a peer. Verified bytes seed the native FNV RPC cache.
5. Completed transfer staging is removed only after a verified cache copy exists;
   interrupted staging is kept. Previously seeded but now unneeded cache keys
   are listed, never deleted. A SHA256 failure in an existing cache asks you to
   inspect/move that exact file aside; it is not silently overwritten.

6. A fresh safe/complete Balance reload uses those verified peer-only cache
   files directly; it does **not** scan a complete peer GGUF or seed padded
   extra layers. Legacy loads without that verified plan keep optional seeding
   from an existing full peer file. Nov 8 native equal-share fetch/reload,
   warm inference and web-restart checks passed; see [DAY19.md](DAY19.md) and
   [BENCHMARKS.md](BENCHMARKS.md). Existing full peer files were left untouched.

Limitations / remaining live verification and further llama.cpp work:

- **Small tensors still cross RPC**, as do cache misses; strict “no weights over
  the cable” is NOT achieved. The existing RPC hash protocol caches only tensors
  over 10 MiB. Eliminate that threshold / extend the protocol to meet the full
  rule, and change the lead loader to eliminate its full-file requirement.
- RPC placement is shares over `n_layers + 1` slots, not the MLX range contract.
  The final output slot is shown; do not interpret shares as layer counts.
- Only single-file GGUF sources with known SHA256 are supported here. Multi-file
  GGUFs and peer manifests over 80 KB are explicitly refused, not silently copied.
- `gguf==0.19.0` supplies metadata reading (included for fresh Mac installs).
  Existing llama.cpp `gguf-py` also works. The native seeder needs `cc`; it buffers
  one tensor in RAM. Allow disk for missing cache bytes **plus one staged tensor**.
- Usage is the **entire RPC cache on that Mini**, clearly labeled with its path;
  retained-key accounting covers files this path previously seeded for this GGUF.
  Pre-existing/unattributed cache files are not classified as garbage.
- Verify `LLAMA_CACHE` / the displayed cache path matches the running RPC server,
  especially if an existing launchd job overrides its environment. Cache location,
  automatic size caps and pruning are not changed. SSH tunnels/loopback-only RPC
  security are unchanged. Co-hosted GGUF-device simulations are refused.

## Shared API (future TUI uses the same contract)

- `POST /api/files/preview` or `/api/balance`:
  `{model_id, node_ids?, counts?, repo_id?, gguf_file?}`.
  Server owns hosts, paths, RAM and file claims; body paths/weight claims are not
  execution input. Returns per-stage file/storage lists and reload readiness.
- `POST /api/files/fetch`: same request, explicit action; freshly prepares a plan
  and returns a normal download job. Counts stay fixed for that transfer.
- Existing `/api/picker/jobs/<id>`, download cancel/resume endpoints handle it.
  Resume replans/revalidates, never trusts old client-side missing-file lists.
- `/api/models/load` with `balance: true` explicitly reloads a fresh ready plan.

Private execution requests are not returned in preview JSON. Transfer plans,
PID/exit records and logs live under `~/.caravan/transfers/`. No auto-start model
plan is silently rewritten: uninstall/reconfigure the fixed worker jobs first,
or use web-only ownership mode for interactive Balance. [Service modes](SERVICES.md).

References checked Nov 8, 2026: [Hub revision/download API](https://huggingface.co/docs/huggingface_hub/package_reference/file_download),
[Hub model metadata](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api),
[GGUF reader](https://github.com/ggml-org/llama.cpp/blob/master/gguf-py/gguf/gguf_reader.py),
[gguf package](https://pypi.org/project/gguf/).
