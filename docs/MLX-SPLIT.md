# MLX split across two Macs (Caravan v3)

*Design note, 2026-10-31. Code: `agent/mlx_split.py`, `agent/mlx_worker.py`
(`--split-role`), `agent/mlx_backend.py` (`mlx.split`),
`agent/mlx_split_fetch.py` (split download, prototype).*

## What it does

One MLX model runs across two Macs, cut by layers, the way llama.cpp RPC
splits a GGUF:

```
 client ──HTTP──► proxy ──► LEAD (Mac A)                      PACKER (Mac B)
                            HTTP API, sessions, sampling       embeddings
                            layers K..N-1, norm, lm_head  ◄──  layers 0..K-1
                                    ▲   tokens ───────────►        │
                                    └── hidden states ◄────────────┘
                                         one TCP connection over Thunderbolt
```

- The **packer** holds the embeddings and the first K layers. It gets token
  ids, runs its layers and sends back the hidden states (bf16 bytes).
- The **lead** holds the remaining layers, the final norm and the output
  layer. It runs the OpenAI-style HTTP API, sampling and the session
  bookkeeping, so the proxy talks to it exactly as it talks to a one-Mac
  worker. No proxy change was needed.
- Default cut: half the layers on each Mac (the odd layer goes to the
  lead). `--split-packer-layers K` / `mlx.split.packer_layers` moves it.

## Naming: lead, packers, string

- The **lead** is the Mac you talk to. It serves the API (the proxy points
  at it), runs the last layers and picks each token.
- The **packers** are the other Macs, numbered in layer order: Packer 1
  runs the first layers, then Packer 2, and so on, and the lead finishes.
  v3 has exactly one, Packer 1.
- The **string** is the whole group (lead plus packers).

Earlier drafts called these "head" and "front" (and the llama.cpp RPC
helper a "tail"). The old names still work as deprecated aliases:

| New | Deprecated alias |
|---|---|
| `--split-role lead` / `packer` | `--split-role head` / `front` |
| `--split-packer-layers K` | `--split-front-layers K` |
| `mlx.split.packer` / `mlx.split.packer_layers` | `mlx.split.front` / `mlx.split.front_layers` |
| `CARAVAN_MLX_SPLIT_PACKER` / `CARAVAN_MLX_SPLIT_PACKER_LAYERS` | `CARAVAN_MLX_SPLIT_FRONT` / `CARAVAN_MLX_SPLIT_FRONT_LAYERS` |
| `mlx_backend.build_lead_command()` / `build_packer_command()` | `build_head_command()` / `build_front_command()` |
| `mlx_split_fetch.py --role lead\|packer --packer-layers K` | `--role head\|front --front-layers K` |

When both are given, the new name wins. `GET /caravan/split` reports
`lead` and `packers` (a list) and still includes the old `head` / `front`
keys. Internally the code keeps the role values `head` / `front`, and the
stage id saved with each session cache (for example `head 24-47 of 48`)
is unchanged, so caches saved before the rename still load. Logs show
the new names (`lead: layers 24-47 of 48`, `packer 1: layers 0-23 of 48`).

## Why this approach

In short: MLX itself works fine and runs the model on each Mac. What we
skipped are MLX's ready-made ways of *linking* two Macs. Its standard
link breaks on messages of about 2 MB or more over our Thunderbolt 4
cable, its fast direct-memory link needs Thunderbolt 5 (our M4 minis have
Thunderbolt 4), and mlx-lm's built-in splitting only covers Qwen models.
So Caravan links the Macs itself, with a plain TCP connection.

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
bytes. The lead sends one op at a time and waits for the reply.

| Op | Meaning |
|---|---|
| `hello` | protocol, model, layer range, number of layers, **epoch** (random per packer start) |
| `prepare` | make the packer's cache for a session ready; returns how many tokens it already holds |
| `fwd` | tokens in, hidden states out (ctx `session` or `scratch`) |
| `checkpoint` / `rewind` / `reset` | keep the packer's cache in lockstep with the lead's |
| `restore` / `save` / `drop` / `evict` / `flush` | per-stage disk persistence |
| `describe` | memory and session stats for `/caravan/split` |

## Per-session caches, save and restore

Each Mac keeps a `SessionStore` for **its own layers** and saves its own
safetensors file for a session (the metadata identity includes the stage,
so a lead file can never be loaded as a packer file).

- **Lockstep.** Every reuse, checkpoint and rewind on the lead is mirrored
  on the packer before the forward pass.
- **Restore rule.** A saved chat counts as restored only when *both* halves
  are on disk with the same token digest. If one half is missing or they
  disagree, both are dropped and the chat is read cold. Never mix halves.
- **Evictions** are decided by the lead (it has the memory budget) and
  mirrored to the packer (`evict` = save if dirty, then drop).
- **Packer restart.** The lead notices a new epoch on reconnect and drops its
  in-memory sessions; the next turn restores both halves from disk.
- **Mismatch.** If the two halves ever hold different lengths for a
  session, both are reset and the turn reads cold (`split-resync`).

## Running it

On the packer Mac (Thunderbolt address of that Mac):

```
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role packer \
  --split-listen <packer-tb-ip>:5560 --model <local model dir> --cache-dir <dir>
```

On the lead Mac:

```
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role lead \
  --split-peer <packer-tb-ip>:5560 --model <local model dir> --port 8092
```

Start the packer first. `--split-packer-layers K` must match on both
Macs (the lead checks and refuses to start otherwise).

`--split-keepalive` (default on) keeps Metal warm on a short-lived
side thread while this Mac waits for the peer, so the next half does
not pay ~5 ms of cool-down after the idle. Disable with
`--no-split-keepalive` or `CARAVAN_MLX_SPLIT_KEEPALIVE=0`. Measured

`--split-pipeline-chats N` (default 1, env `CARAVAN_MLX_SPLIT_PIPELINE_CHATS`) overlaps Packer 1's half for chat B with the lead's half for chat A when N≥2. Off by default so single-chat behavior stays the old path. Two chats ≈1.6× wall aggregate writing; a fair `(n_gen, t0)` packer pick keeps a third chat's wait before the first word ~0.6 s (was ~4 s). See [BENCHMARKS.md](BENCHMARKS.md#idea-1-several-chats-at-once-oct-31nov-1-mlx).
Oct 31: writing +28–50% vs off, reading and quality unchanged
([BENCHMARKS.md](BENCHMARKS.md#gpu-keepalive-while-waiting-on-the-peer-oct-31-mlx)).

Turn **Low Power Mode off on both Macs** (`pmset -g` should show
`lowpowermode 0`). The split runs at the pace of the slower Mac; with
Low Power Mode on for the packer, turning it off made reading 16–30%
faster.

`"mlx": {"split": {"packer": "<packer-tb-ip>:5560"}}` in
`~/.caravan/config.json` (env `CARAVAN_MLX_SPLIT_PACKER`, and
`CARAVAN_MLX_SPLIT_PACKER_LAYERS` for the cut) is read by the helpers
`mlx_backend.build_lead_command()` and `build_packer_command()`, which
return the two commands above. `caravan_agent.py --apply` and
`render_mlx_plist.py` don't use it yet: they still start a one-Mac
worker, so start both halves by hand for now. All flags and settings:
[CONFIGURATION.md](CONFIGURATION.md#mlx-split-across-two-macs-v3).
`GET /caravan/split` on the lead shows both stages' memory and the link
stats; every reply's `usage.caravan.split` has the per-request network
cost (calls, MB each way, time waiting on the packer, network time).

## Results in short

Measured Oct 31 on two Mac minis M4 24 GB, side by side with v2.1 on one
Mac. Full tables: [BENCHMARKS.md](BENCHMARKS.md#v21-vs-v3-one-mac-vs-two-macs-oct-31-mlx).

- Memory per Mac roughly halves (Qwen3 30B 19.04 → 10.49 GB, Gemma 4 26B
  17.14 → 9.28 GB, GPT-OSS 20B 13.41 → 7.05 GB), so Qwen3 30B now holds a
  16k chat on MLX.
- Writing is 28–42% slower and reading 16–25% slower (first run; EXO2
  was in Low Power Mode). Rerun with it off: writing 30.4 / 27.7 / 26.6
  tok/s (27–40% slower than one Mac), reading within about 6% of one Mac
  ([BENCHMARKS.md](BENCHMARKS.md#v3-rerun-with-low-power-mode-off-oct-31-mlx-v31)). Each half costs
  16–24 ms per token, about what the whole model costs on one Mac, while
  the cable adds under 1 ms and under 10 KB per token. The Macs take turns,
  so the time is per-pass overhead, not the cable. Uneven cut
  (`--split-packer-layers`, idea 5) tried Oct 31: no single-chat writing
  gain (serial pipeline); best balanced cuts Gemma K=16, GPT-OSS K=13,
  Qwen3 even ([BENCHMARKS.md](BENCHMARKS.md#uneven-layer-split-oct-31-mlx-idea-5)).
  GPU keepalive (idea 6, default on, `0f14e72`) removes Metal cool-down
  during the peer wait: writing 38.3 / 34.1 / 45.6 tok/s on Gemma 4 /
  GPT-OSS / Qwen3 vs 27.7 / 26.6 / 30.4 off; reading slightly up;
  quality 3/3 ([BENCHMARKS.md](BENCHMARKS.md#gpu-keepalive-while-waiting-on-the-peer-oct-31-mlx)).
- Chat reuse and restart resume work across the split, at +0.1–0.4 s.
- The 8-bit versions, which don't fit on one Mac, all run split with a 16k
  chat and pass 3/3: Qwen3 30B 8-bit (20.6 tok/s, 18.12 GB per Mac), Gemma
  4 26B 8-bit (18.1 tok/s, 15.58 GB), GPT-OSS 20B 8-bit (19.8 tok/s,
  12.13 GB). GPT-OSS 120B doesn't fit across two 24 GB Macs, even at 2-bit
  (parked; see [ROADMAP.md](ROADMAP.md#deferred--parked)).

## How the weights get to each Mac

- **Today:** each Mac loads from **its own local copy** of the model.
  Nothing is streamed from the lead at load time. Each stage reads only
  the weights for its layers (lazy load), but the copy on disk is
  normally the full model (for this sprint the packer Mac's copies of the
  4-bit models were copied once over Thunderbolt from the lead Mac; for
  Gemma 4 26B 8-bit and GPT-OSS 20B 8-bit the lead downloaded its own
  files plus the packer-only ones and copied only the packer's files over,
  so the packer holds a partial copy).
- **Prototype split download** (`agent/mlx_split_fetch.py`): each Mac reads
  `model.safetensors.index.json`, maps its layer range to shard files and
  downloads only those from Hugging Face (`snapshot_download` with
  `allow_patterns`, plus config and tokenizer files). A shard that
  straddles the cut goes to both Macs. Embeddings go to the packer (and to
  the lead too when they're tied), `lm_head` and the final norm go to the
  lead, and vision towers are skipped (the split is text-only). The stage
  refuses to start if one of its shards is missing or the wrong size
  (v3.1: checked against the shard's own header and the sizes Hugging
  Face lists), because loading without them would silently leave random
  weights. Tested on Qwen3 30B
  8-bit: the lead downloaded 16.65 GB and the packer 21.09 GB, instead of
  32.44 GB each, and the split loaded from those partial copies. It's a
  command you run yourself (see
  [CONFIGURATION.md](CONFIGURATION.md#split-download-agentmlx_split_fetchpy));
  the agent doesn't run it yet.
- **GGUF, for comparison.** With llama.cpp RPC the lead needs the whole
  GGUF on its own disk and sends the packer's part over the cable at load.
  Stage 1 of a GGUF split download is already in place: the packer runs
  `rpc-server --cache`, keeps its part on its own disk, and a restart
  loads in about 53 s instead of 7–11 min. Stage 2 (a fork patch so the
  packer loads its own part from its own disk, fetched by byte range or
  from `gguf-split` files) is planned; see [ROADMAP.md](ROADMAP.md).

## Limits

- The link is **unauthenticated**. Keep it on the Thunderbolt cable.
- Generation is a serial pipeline: per token, the lead waits for the
  packer, then runs its half. There's no overlap of the two halves yet.
  Moving the cut (`--split-packer-layers`) does not speed up a single
  chat (measured Oct 31). GPU keepalive (default on) removes the Metal
  cool-down during that wait and raises writing ~28–50%; it does not
  overlap the halves. Ideas for fixing the turn-taking, including
  several chats at once and guess ahead, are in
  [ROADMAP.md](ROADMAP.md#beating-the-turn-taking-in-the-split).
- Not started by the agent or launchd yet; both halves are started by hand.
- `--kv-bits` with the split is untested.
- Two Macs only (one packer, one lead). More stages are a roadmap item.
- The bench talked to the lead worker directly; the proxy path was only
  smoke-tested.


### Idea 3: guess-ahead (speculative decoding)

Shipped behind the speculate path: with `--no-split-draft` (or no pairing /
declined download) behaviour matches baseline. On the **lead only**, the
pairing table `agent/guessers.json` auto-selects a small draft when the
loaded model matches (Qwen3-30B-A3B → Qwen3-0.6B-4bit k=3; Gemma-4-26B →
gemma-3-270m-it-4bit k=2 with specials remap). GPT-OSS has no pairing and
stays at baseline.

```sh
# Auto-pair (asks once if the helper is missing; remembers in
# ~/.caravan/mlx/guess-ahead-state.json):
#   A 335 MB helper can make <model> faster. Download Qwen3-0.6B-4bit? [y/N]

# Override / force / disable:
--split-draft-model ~/.caravan/mlx-models/drafts/Qwen3-0.6B-4bit
--split-speculate-k 3
--split-draft-auto-download          # or CARAVAN_MLX_SPLIT_DRAFT_AUTO_DOWNLOAD=1
--no-split-draft
--split-draft-skip-first-load        # skip cached quality+speed gate
--split-prompt-lookup N              # draft-free n-gram (0=off)
```

At load: vocab must be exact or compatible (specials remap). First load on
a machine runs quality prompts + a short speed A/B and keeps the pair only
if quality passes and it is clearly faster (cached). During a chat, if the
accepted-guess rate stays below the measured break-even window, guessing
turns off for that chat and is logged. Packer needs no draft weights;
rejects trim packer KV over the existing link (`trim` op). Bench workflow:
[METHODOLOGY.md](METHODOLOGY.md). Numbers:
[BENCHMARKS.md](BENCHMARKS.md#idea-3-guess-ahead-speculative-decoding-nov-1-mlx).
