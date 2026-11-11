# Day 22 — GGUF weights from each Mini's own disk

## Status

**A real two-Mini prototype now works. It is not the default web/picker path yet.**

Each Mini loaded only its assigned tensor pieces, including the small tensors
that the older RPC-cache path still sent over the link. The lead did not open
the original full GGUF to load the prototype. All existing GGUFs were kept,
unchanged. Huihui stayed loaded throughout; no production service was restarted.
No reboot, release, or post was made.

This is a storage-independence result, **not a speedup claim**. The new path
loaded slightly slower in this small check and wrote at about the same speed.

## What changed

- `agent/gguf_shards.py`: partition every tensor by the exact llama.cpp layer
  assignment, with any number of positive Mini shares. Input/global tensors
  stay on the lead; output tensors follow the output-layer slot. No padded,
  overlapping layer ranges and no small-tensor cutoff.
- New, exclusive-create per-Mini trees contain only that Mini's weight pieces
  in `rpc/<native-FNV-key>`. Every piece has a byte count and SHA256 in the
  manifest; FNV is used only to address llama.cpp's existing native cache.
- Every tree also contains `model.cvgg`, `weights.tsv`, and `manifest.json`.
  **`.cvgg` is a new, explicitly metadata-only Caravan catalog, not a fake or
  sparse GGUF.** It wraps GGUF metadata and the tensor directory. It contains
  no tensor payloads and cannot be loaded by stock llama.cpp.
- `runtime/gguf-shards/apply.py` creates a separate local llama.cpp worktree at
  pinned revision `76a67730ffc7d650dffa4db04d96be84a59e7ef3`. Production sources
  and binaries are not patched in place. The additions use the upstream
  `llama_model_init_from_user` API to keep tensor types and initialize weights
  from the catalog, rather than the full-file loader.
- The RPC backend exposes a local-load procedure using the **existing**
  `SET_TENSOR_HASH` message for every tensor size. The lead supplies only the
  known key, not weight bytes. A miss is an error; there is no `SET_TENSOR`
  weight-transfer fallback. Peer strict mode checks size and FNV on each hit.
- `lead` / `peer` foreground commands verify all local SHA256s, reject links,
  unexpected pieces, a mismatched role, and unmarked runtime builds before
  exec. RPC listeners and endpoint arguments are loopback-only for SSH tunnels.
- `bench/gguf_shards_live.py` measures direct streaming chat. No Hermes, tool
  schema, special prefill, or prompt-cache reuse is involved.

Ordinary `.gguf` loading is unchanged. This is an opt-in native experiment;
Caravan does not silently switch existing web loads to it.

## Real Mini check — November 10, 2026, 6:20–6:23 PM CST

Model: the already-downloaded **Qwen2.5-3B-Instruct Q4_0**,
`Qwen--Qwen2.5-3B-Instruct-GGUF/qwen2.5-3b-instruct-q4_0.gguf`.
Its original file is **1,997,879,712 bytes** on each Mini; both copies still
hash to `670d82d0fbee6289b661eb323612c65bd2e97ec8c65cdbd9131aa44d30e9816a`.

The plan used `1,1` shares, local Metal first and one RPC peer. The experiment
ran alongside the existing MLX split, on separate ports: native chat `18224`,
peer loopback RPC `50062`, lead loopback SSH tunnel `50072`. SSH crossed the
Thunderbolt IPv4 link and retained the already-configured peer's host-key
identity with strict checking; no new host key was accepted. None of the
existing tunnels was changed.

### Disk: separate required footprint from actual retained files

| Model-specific measurement (bytes) | EXO1 / lead | EXO2 / peer |
|---|---:|---:|
| Original full GGUF, before | 1,997,879,712 | 1,997,879,712 |
| Weight pieces actually loaded | 999,225,344 | 992,698,368 |
| New shard tree, including catalog/manifests | 1,005,304,514 | 998,777,538 |
| Actual originals + new shard tree, after | **3,003,184,226** | **2,996,657,250** |
| New shard tree, filesystem-allocated bytes | 1,005,432,832 | 998,895,616 |

The runtime now needs roughly half the model's weight data per Mini, but
**disk usage increased for this test because the originals were deliberately
retained**. No disk space was reclaimed. These figures exclude unrelated
models/caches, runtime build files, and logs; they are not whole-disk usage.

Native callback evidence records all **435 tensors**: 229 local and 206
peer-local. Of the peer-local tensors, **154 are at or below the old 10 MiB
cutoff**. Their bytes were read on the peer, not sent as weights by the lead.
All local pieces were SHA256-verified before launch and again after testing.

### Load and chat

Both modes used the same isolated native build, model, split, context 2048,
flash attention on, one chat slot, temperature zero, and a normal direct chat
request (55 input tokens, 128 generated tokens). The original MLX worker
remained loaded but was not being benchmarked. Three requests per mode:

| Mode | One observed process-to-health load | Median write tok/s | Median wall TTFT | Median request wall time |
|---|---:|---:|---:|---:|
| Full lead GGUF + ordinary RPC, cache disabled | 2.288 s | 41.77 | 0.150 s | 3.192 s |
| Own-piece-only catalog + verified peer disk | 3.149 s | 41.29 | 0.137 s | 3.228 s |

All six completions were identical. Every request reported `cache_n = 0`.
TTFT is measured to first non-empty text; write speed is native predicted
throughput, not total request throughput. Filesystem/shader caches were warm;
these are small smoke measurements, **not reboot-cold or statistically strong
speed comparisons**. Shard creation and prelaunch SHA verification are excluded
from the process-to-health load timing. The catalog path uses the user-model
API (no mmap), so this is not an isolated loader-algorithm speed comparison.

Failed setup attempts are retained in the raw rows and excluded from this
table. The first tunnel used an alias unavailable on the lead. A subsequent
management-route load did not become ready within the deadline; after clearing
only experiment processes, a fresh peer and the verified Thunderbolt tunnel
completed successfully. A stale experimental RPC session also required a
clean peer restart. No production process was stopped for any retry.

### Missing-piece test: passed, with originals still present

A **new, empty** peer cache was created for a separate negative test; no piece
was removed or changed. The catalog load exited with status 1 in **1.176 s**:

> Caravan: missing/misplaced peer piece (no weight-transfer fallback): output_norm.weight

The complete original GGUFs were still on both Minis. The prototype did not
fall back to them or copy the missing weights from the lead.

### Final production state

The experiment lead, peer, and dedicated tunnel were stopped. The same
production Huihui lead PID **1055** remained ready with **24/40** layers,
EXO2 first, KV16; the saved restore model was unchanged. A direct Caravan
`/api/chat` readiness request succeeded. No Hermes test or prefill was used;
its setup and existing tunnels were left alone.

## Evidence and tests

- [Raw load, disk, chat, failure, and final-state records](../bench/results/day22/live.json)
- [All tensor offsets, sizes, SHA256s, native keys, and owners](../bench/results/day22/tensors.json)
- Mini detailed logs and PID records: `~/.caravan/day22-live/`.
- Shards retained on both Minis: `~/.caravan/day22-shards/qwen2.5-3b-1-1/`.
- **974 tests passed** (`python3 -m unittest discover -s tests`, 45.676 s).
  Includes 35 new tests for arbitrary Mini counts, ownership, bounded native
  hashing, read-only sources, exclusive output creation, corruption, links,
  missing/extra pieces, pinned runtime guards, and loopback launch arguments.
  A packaging-worker plist-placeholder regression seen during an earlier
  shared-tree run was corrected by that worker; the final full run is green.

## Developer reproduction (not everyday installation instructions)

Use a new output path for every plan. Existing paths are refused. These
commands prepare from an already-local source; they never erase or replace it.
`$PYTHON` means Caravan's Mac Python environment, with numpy and gguf available.

On each Mini, from its Caravan repository:

```sh
$PYTHON agent/gguf_shards.py create /path/to/model.gguf /new/stage/tree \
  --shares 1,1 --index 0
# Use --index 1 on the peer; add a share and a distinct index for each extra Mini.
$PYTHON agent/gguf_shards.py verify /new/stage/tree

python3 runtime/gguf-shards/apply.py /existing/llama.cpp /new/isolated/runtime
cmake -S /new/isolated/runtime -B /new/isolated/runtime/build \
  -DGGML_RPC=ON -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF
cmake --build /new/isolated/runtime/build --config Release -j 4 \
  --target llama-server ggml-rpc-server
```

On a peer, with its own tree, run the verified foreground role:

```sh
$PYTHON agent/gguf_shards.py peer /new/stage/tree \
  --binary /new/isolated/runtime/build/bin/ggml-rpc-server --port 50062
```

Create a normal strictly verified SSH local tunnel from the lead's
`127.0.0.1:50072` to that peer's `127.0.0.1:50062`, using its configured trusted
SSH identity. For more peers, use distinct ports and one tunnel per peer; list
endpoints in the same order as the positive shares after the lead's share.
Then on the lead:

```sh
$PYTHON agent/gguf_shards.py lead /new/stage/tree \
  --binary /new/isolated/runtime/build/bin/llama-server \
  --port 18224 --rpc 127.0.0.1:50072 --context 2048
# --dry-run verifies everything and prints arguments without starting a process.

python3 bench/gguf_shards_live.py --base http://127.0.0.1:18224 \
  --label own-piece-only --runs 3 --out /new/results.jsonl
```

Do not use production worker ports or replace production binaries. Stop only
the experiment processes afterward. The usual web `.gguf` path remains the
older full-lead/RPC-cache path until the follow-up integration is finished.

## Still to do before calling this finished/default

1. Wire catalog/shard plans into the picker, agent, recovery, and installer;
   record all process ownership and handle an interrupted/failed load cleanly.
2. Extend immutable-source Range downloads to **all** new shard tensors and
   transfer only catalog/manifest metadata to peers. Today's new CLI builds
   from an existing local full GGUF; it does not yet give a new peer a
   source-free/direct-download installation workflow. The live runtime itself
   does not depend on that original GGUF.
3. Exercise three or more physical Minis. N-way planning and argument building
   are tested, but only two physical Minis were available for this check.
4. Validate additional architectures, tied input/output embeddings, shared
   global tensors, tensor aliasing, CPU fallback, and very large tensors.
   Mismatched ownership fails closed rather than silently copying weights.
   Multi-file source GGUFs are explicitly rejected for now.
5. Repeat longer, randomized-order cold/warm load and generation comparisons;
   add native loader/protocol regression coverage, source mutation/failure
   cases, and clear progress reporting. Keep this experimental until then.

No Day 22 release has been cut. The package source pin and any release/main
advance should be coordinated after the final Day 22 changes are collected.
