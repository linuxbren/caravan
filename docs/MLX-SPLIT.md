# MLX split across two Macs (Caravan v3)

*Design note, 2026-10-31. Code: `agent/mlx_split.py`, `agent/mlx_worker.py`
(`--split-role`), `agent/mlx_backend.py` (`mlx.split`),
`agent/mlx_split_fetch.py` (split download, prototype).*

## What it does

One MLX model runs across two Macs, cut by layers, the way llama.cpp RPC
splits a GGUF:

```
 client ──HTTP──► proxy ──► HEAD (Mac A)                      FRONT (Mac B)
                            HTTP API, sessions, sampling       embeddings
                            layers K..N-1, norm, lm_head  ◄──  layers 0..K-1
                                    ▲   tokens ───────────►        │
                                    └── hidden states ◄────────────┘
                                         one TCP connection over Thunderbolt
```

- The **front** holds the embeddings and the first K layers. It gets token
  ids, runs its layers and sends back the hidden states (bf16 bytes).
- The **head** holds the remaining layers, the final norm and the output
  layer. It runs the OpenAI-style HTTP API, sampling and the session
  bookkeeping, so the proxy talks to it exactly as it talks to a one-Mac
  worker. No proxy change was needed.
- Default cut: half the layers on each Mac (the odd layer goes to the
  head). `--split-front-layers K` / `mlx.split.front_layers` moves it.

## Why this approach

We checked the ready-made options first:

| Option | Result on two M4 Mac minis, Thunderbolt 4 |
|---|---|
| `mx.distributed` ring backend (mlx 0.32.4) | Connects, small all_sum works, but any transfer of ~2 MB or more aborts ("Receiving from socket … errno 60", peer lost). Same code works over localhost. Plain Python TCP moves 8 MB each way in ~2 ms on the same link. |
| `jaccl` (RDMA over Thunderbolt) | Needs Thunderbolt 5. Not available on the M4 (non-Pro) mini. |
| `mlx_lm` pipeline sharding (`sharded_load`) | Only qwen3_moe and qwen3_5 have `PipelineMixin` in mlx-lm 0.32.2; Gemma 4 and GPT-OSS don't. It also uses collectives, so a cancelled request can deadlock the other rank. |
| exo | Splits with its own ring/pipeline. Reference only; exo stays paused. |

So Caravan does its own pipeline over a single request/reply TCP
connection: no collectives, nothing to deadlock on cancel, works for all
three model families by reading layer attributes (linear-attention,
sliding-window and full layers each get the right mask), and each side can
keep its own per-session caches.

## Protocol (`caravan-split-1`)

Frames: `>IQ` header (JSON length, payload length), then JSON, then raw
bytes. The head sends one op at a time and waits for the reply.

| Op | Meaning |
|---|---|
| `hello` | protocol, model, layer range, number of layers, **epoch** (random per front start) |
| `prepare` | make the front's cache for a session ready; returns how many tokens it already holds |
| `fwd` | tokens in, hidden states out (ctx `session` or `scratch`) |
| `checkpoint` / `rewind` / `reset` | keep the front's cache in lockstep with the head's |
| `restore` / `save` / `drop` / `evict` / `flush` | per-stage disk persistence |
| `describe` | memory and session stats for `/caravan/split` |

## Per-session caches, save and restore

Each Mac keeps a `SessionStore` for **its own layers** and saves its own
safetensors file for a session (the metadata identity includes the stage,
so a head file can never be loaded as a front file).

- **Lockstep.** Every reuse, checkpoint and rewind on the head is mirrored
  on the front before the forward pass.
- **Restore rule.** A saved chat counts as restored only when *both* halves
  are on disk with the same token digest. If one half is missing or they
  disagree, both are dropped and the chat is read cold. Never mix halves.
- **Evictions** are decided by the head (it has the memory budget) and
  mirrored to the front (`evict` = save if dirty, then drop).
- **Front restart.** The head notices a new epoch on reconnect and drops its
  in-memory sessions; the next turn restores both halves from disk.
- **Mismatch.** If the two halves ever hold different lengths for a
  session, both are reset and the turn reads cold (`split-resync`).

## Running it

On the front Mac (Thunderbolt address of that Mac):

```
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role front \
  --split-listen <front-tb-ip>:5560 --model <local model dir> --cache-dir <dir>
```

On the head Mac:

```
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role head \
  --split-peer <front-tb-ip>:5560 --model <local model dir> --port 8092
```

or set `"mlx": {"split": {"front": "<front-tb-ip>:5560"}}` in
`~/.caravan/config.json` (env `CARAVAN_MLX_SPLIT_FRONT`), and
`mlx_backend.build_front_command()` prints the matching front command.
`GET /caravan/split` on the head shows both stages' memory and the link
stats; every reply's `usage.caravan.split` has the per-request network
cost (calls, MB each way, time waiting on the front, network time).

## How the weights get to each Mac

- **Today:** each Mac loads from **its own local copy** of the model.
  Nothing is streamed from the head at load time. Each stage reads only
  the weights for its layers (lazy load), but the copy on disk is
  normally the full model (for this sprint the front Mac's copies of the
  4-bit models were copied once over Thunderbolt from the head Mac).
- **Prototype split download** (`agent/mlx_split_fetch.py`): each Mac reads
  `model.safetensors.index.json`, maps its layer range to shard files and
  downloads only those from Hugging Face (`snapshot_download` with
  `allow_patterns`, plus config and tokenizer files). A shard that
  straddles the cut goes to both Macs. Embeddings go to the front (and to
  the head too when they're tied), `lm_head` and the final norm go to the
  head, and vision towers are skipped (the split is text-only). The stage
  refuses to start if one of its shards is missing, because loading
  without them would silently leave random weights.

## Limits

- The link is **unauthenticated**. Keep it on the Thunderbolt cable.
- Generation is a serial pipeline: per token, the head waits for the
  front, then runs its half. There's no overlap of the two halves yet.
- `--kv-bits` with the split is untested.
- Two Macs only (one front, one head). More stages are a roadmap item.
