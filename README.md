# Caravan

**Run one large GGUF model across two Apple Silicon Macs.**

Caravan splits a llama.cpp model's layers between two Macs using
llama.cpp's RPC backend, ideally over a direct Thunderbolt/USB4 cable. On
top of that it adds the pieces needed for daily use as the backend of an
OpenAI-compatible assistant:

- a session-pinning proxy that keeps each conversation's KV cache warm in
  its own llama-server slot and saves/restores it to disk;
- an agent that works out on each machine whether it should be the
  **head** (serves the model) or a **tail** (lends its GPU over RPC), and
  supervises the right process;
- launchd services so everything survives crashes and reboots.

> **Status: early, unreleased, experimental.** The repo is public but not
> announced. It has served as the everyday model backend for a personal
> assistant on one pair of Macs, but hasn't been packaged or tested
> anywhere else, and paths in `launchd/` are still specific to that
> setup. Expect rough edges -- see [Limitations](#limitations-and-known-issues).

*(Formerly "llama-shard"; see [docs/LOG.md](docs/LOG.md).)*

## Why

Ollama is single-machine by design, and [exo](https://github.com/exo-explore/exo)
shards models across Macs but only for MLX. The engine underneath Ollama,
llama.cpp, has an RPC backend (`GGML_RPC`) that can put part of a model on
another machine's GPU -- which covers the much larger GGUF ecosystem,
including models that don't fit in one Mac's unified memory. Caravan is an
experiment in making that usable day to day: stable, self-configuring, and
fast enough for a real assistant.

## Hardware and measured numbers

Developed and run on **2x Mac mini (Apple M4, 24 GB unified memory each)**,
connected by a **Thunderbolt 4/USB4 cable (40 Gb/s link)** and also on the
same LAN. The model used throughout is an ~18 GB Ollama model (16 GB of
weights) that doesn't fit comfortably on one 24 GB Mac.

Measured during development (details and context in
[docs/LOG.md](docs/LOG.md); single runs, not a formal benchmark):

| what | over Wi-Fi/LAN (incl. Tailscale) | over Thunderbolt |
|---|---|---|
| Generation | 4.23 tok/s (first run); ~3.8-4.5 tok/s typical | 6.1 tok/s manual; 6.09 via the Python agent; 6.03 via the C++ binary |
| Prompt processing | 15.5 tok/s (first run); ~65-100 tok/s on long real prompts | 48.5 tok/s on a 149-token prompt |
| Model load, tail cache cold | 7-11 min | 29-39 s |
| Model load, tail cache warm (`rpc-server --cache`) | 53 s; 34 s for a full scripted tail restart | -- |

RDMA over Thunderbolt was not available: it needs Thunderbolt 5 (M4 Pro/Max
or M3 Ultra), so the Thunderbolt numbers are plain TCP. The 2026-10-30
llama-server flag changes (flash attention, 8-bit KV cache) have **not**
been benchmarked yet.

## How it works

```
                  OpenAI-compatible client (e.g. an assistant gateway)
                                     |
                                     v  :8090
 node-a (head) ------------------------------------------------------------
   slot_pin_proxy.py   one request at a time (FIFO); pins each session to a
        |              slot (LRU); saves/restores slot KV to disk
        v  :8080
   llama-server  -m <GGUF from the local Ollama store>
        |        --rpc <node-b>:50052 --device MTL0,RPC0 --tensor-split 1,1
        |        --parallel 4 --no-kv-unified ...
        |  RPC over Thunderbolt (fallback: Tailscale / LAN)
 node-b (tail) ------------------------------------------------------------
   ggml-rpc-server -H 0.0.0.0 -p 50052 --cache    (half the layers, on Metal;
                                                   stores nothing but a cache)
```

- **Head and tail.** The head needs the full GGUF file locally (llama.cpp's
  RPC design); the tail needs nothing -- tensors are sent over RPC and
  cached on its disk (`--cache`) so restarts are fast.
- **Agent** (`agent/`). Runs identically on every node. A node whose local
  Ollama store has the target model becomes head; others become tails. Peers
  are found via mDNS/Bonjour and Tailscale, confirmed by calling the peer
  agent's `/health` (so unrelated machines are ignored), and the fastest
  path is picked automatically: Thunderbolt > Tailscale > LAN. The agent
  then builds and supervises the `llama-server` or `rpc-server` command.
  See [agent/README.md](agent/README.md).
- **Proxy** (`proxy/`). llama-server's own slot choice moves conversations
  between slots and throws away their cached prompt. The proxy fingerprints
  each session, keeps it in one slot, serializes requests, and persists each
  slot's KV cache to disk so it survives a llama-server restart.
- **launchd** (`launchd/`). Plists for the proxy, the agent, and the
  manual per-role setup (`llama-server`, `rpc-server`). See
  [launchd/README.md](launchd/README.md).
- **C++ binary** (`cpp/`, experimental). One executable that links
  llama.cpp and runs the head or tail role in-process. Proven end to end but
  not production-ready. See [cpp/README.md](cpp/README.md).

Full design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- Two Apple Silicon Macs (tested: M4, 24 GB each), ideally linked by a
  Thunderbolt/USB4 cable (macOS gives each end a 169.254.x.x link-local
  address). A shared LAN or Tailscale also works, much more slowly.
- llama.cpp built from source on both, with `GGML_RPC=ON` and
  `GGML_METAL=ON` (Homebrew's build has no RPC), at `~/dev/llama.cpp`.
  We run the `caravan-patches` branch of
  [RookiOS72/llama.cpp](https://github.com/RookiOS72/llama.cpp); flag names
  in this repo were checked against it.
- [Ollama](https://ollama.com) on the head, used as the model store
  (`ollama pull <model>`; its blobs are plain GGUF files).
- Python: the proxy is stdlib-only and runs on 3.9+; the agent needs
  **3.10+** (use Homebrew's `/opt/homebrew/bin/python3`, since some macOS
  versions ship 3.9).
- macOS **Local Network** permission for whatever launches `llama-server`
  (System Settings > Privacy & Security > Local Network). A `llama-server`
  launched directly by launchd can't reach the tail at all; launched by the
  Python agent (with Python allowed) it can. See docs/LOG.md.
- The RPC protocol has no authentication or encryption: only expose port
  50052 on a private link or network.

## Quick start

On both Macs:

```sh
git clone https://github.com/linuxbren/caravan ~/dev/caravan
git clone -b caravan-patches https://github.com/RookiOS72/llama.cpp ~/dev/llama.cpp
cd ~/dev/llama.cpp
cmake -B build -DGGML_RPC=ON -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

On the head, pull a model:

```sh
ollama pull <model>
python3 ~/dev/caravan/agent/ollama_store.py --list       # what's available locally
```

**Option A -- let the agent decide** (start the tail first):

```sh
cd ~/dev/caravan/agent
/opt/homebrew/bin/python3 caravan_agent.py --model <model>          # dry run: prints role + command
/opt/homebrew/bin/python3 caravan_agent.py --model <model> --apply  # run and supervise it
```

**Option B -- by hand:**

```sh
# node-b (tail)
~/dev/llama.cpp/build/bin/ggml-rpc-server -H 0.0.0.0 -p 50052 --cache

# node-a (head)
mkdir -p ~/.caravan/llama-server/slots
BLOB=$(python3 ~/dev/caravan/agent/ollama_store.py <model>)
~/dev/llama.cpp/build/bin/llama-server -m "$BLOB" \
  --rpc <node-b-ip>:50052 --device MTL0,RPC0 --tensor-split 1,1 --port 8080 \
  -c 262144 --parallel 4 --no-kv-unified --slot-save-path ~/.caravan/llama-server/slots/ \
  -ngl 999 -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 -b 2048 -ub 512
```

(`agent/render_llama_plist.py --model <model> --rpc <node-b-ip>:50052`
prints the same arguments as a launchd plist.)

Then, on the head, start the proxy and point your client at it:

```sh
python3 ~/dev/caravan/proxy/slot_pin_proxy.py      # listens on 127.0.0.1:8090
curl http://127.0.0.1:8090/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hello"}]}'
```

To run everything under launchd, see [launchd/README.md](launchd/README.md).

## Configuration

Nothing has to be configured. Every setting has a default, and precedence
is always **command-line flag > environment variable > config file >
default**. The config file is optional JSON at `~/.caravan/config.json`
(change the path with `CARAVAN_CONFIG` or the agent's `--config`):

```json
{
  "model": "qwen3:30b-a3b",
  "llama_server": { "n_slots": 4, "ubatch_size": 512, "rpc": "169.254.104.38:50052" },
  "proxy": { "slot_save_every": 1, "slot_idle_save_seconds": 0 },
  "slot_cleanup": { "mode": "delete", "max_age_days": 30 }
}
```

### Model (agent, render tool)

| flag | env | config key | default |
|---|---|---|---|
| `--model NAME` | `CARAVAN_MODEL` | `model` | `muse-glimmer` |

Any model in the local Ollama store: `name`, `name:tag`,
`namespace/name:tag`, `hf.co/user/repo:tag`.

### llama-server (agent, render tool)

Used by `agent/caravan_agent.py`, `agent/supervisor.py` and
`agent/render_llama_plist.py`. Config keys are under `"llama_server"`.

| flag | env | config key | default | llama-server flag |
|---|---|---|---|---|
| `--n-slots` | `CARAVAN_N_SLOTS` | `n_slots` | `4` | `--parallel N` (and `-c`) |
| `--ctx-per-slot` | `CARAVAN_CTX_PER_SLOT` | `ctx_per_slot` | `65536` | `-c n_slots × ctx_per_slot` |
| `--flash-attn` | `CARAVAN_FLASH_ATTN` | `flash_attn` | `on` | `-fa on\|off\|auto` |
| `--cache-type-k` | `CARAVAN_CACHE_TYPE_K` | `cache_type_k` | `auto` | `-ctk` (`auto` = f16 if it fits, else q8_0) |
| `--cache-type-v` | `CARAVAN_CACHE_TYPE_V` | `cache_type_v` | `auto` | `-ctv` (quantized V requires flash attention) |
| `--cache-ram` | `CARAVAN_CACHE_RAM_MIB` | `cache_ram_mib` | `0` | `--cache-ram` MiB (0 = off) |
| `--n-gpu-layers` | `CARAVAN_N_GPU_LAYERS` | `n_gpu_layers` | `999` | `-ngl` |
| `--batch-size` | `CARAVAN_BATCH_SIZE` | `batch_size` | `2048` | `-b` |
| `--ubatch-size` | `CARAVAN_UBATCH_SIZE` | `ubatch_size` | `512` | `-ub` |
| `--rpc` (render tool only; `auto` = discover) | `CARAVAN_RPC_ADDR` | `rpc` | `169.254.104.38:50052` | `--rpc` |
| `--swa-full` | `CARAVAN_SWA_FULL` | `swa_full` | off | `--swa-full` (full-size sliding-window cache) |

Always passed as well: `--no-kv-unified` (each slot gets its own KV
region), `--slot-save-path ~/.caravan/llama-server/slots/`, `--port 8080`,
and for each peer `--device MTL0,RPC<n>` with an even `--tensor-split`.

Why these defaults:

- **`-fa on`**: deterministic instead of `auto`, and required for an 8-bit
  V cache.
- **`auto` K/V** (since 2026-10-30): f16 when
  `weights + f16 KV (n_slots × ctx_per_slot) + compute reserve + margin`
  fits under the GPU working-set limit (× devices with RPC), else `q8_0`
  (half the KV memory). f16 was 4–6% faster on the Oct 30 benchmarks.
  The KV estimate reads the GGUF header (layers, KV heads, head sizes,
  sliding-window layers); the limit is Metal's
  `recommendedMaxWorkingSetSize` (asked once via `swift`, cached in
  `~/.caravan/agent/gpu_limit.json`), else `iogpu.wired_limit_mb`, else
  18186.25 MiB (llama.cpp prints this as "19069.67 MB", decimal). The
  decision and every term of the estimate are logged:
  `[caravan] KV cache -ctk f16 -ctv f16: f16 fits (…)`. Tune under
  `"kv_auto"`: `gpu_working_set_mib` (`CARAVAN_GPU_WORKING_SET_MIB`),
  `compute_reserve_mib` (default: ubatch × n_vocab × 4 B + 64 MiB, which
  matches llama.cpp's measured Metal compute buffers;
  `CARAVAN_COMPUTE_RESERVE_MIB`), `safety_margin_mib` (256,
  `CARAVAN_KV_SAFETY_MARGIN_MIB`). An unreadable model means `q8_0`. The
  production shape (4 × 64K) still resolves to `q8_0`. Switching cache types
  makes existing disk slot files unrestorable; each session reprocesses
  once and is saved again.
- **`--cache-ram 0`**: llama.cpp's default 8 GiB host-RAM prompt cache
  copies every idle slot on each new task. Caravan already pins sessions
  to slots and saves them to disk, so the RAM cache only duplicates memory
  and adds copy time.
- **`-ngl 999`**: keep every layer on Metal/RPC devices, and stop
  `--fit` from choosing fewer.
- **`-b 2048 -ub 512`**: llama.cpp's own defaults, now explicit. A larger
  `-ub` may speed up prompt processing on Metal at the cost of memory --
  benchmark first, e.g.
  `llama-bench -m <blob> -fa 1 -ctk q8_0 -ctv q8_0 -ub 512,1024,2048 -p 4096 -n 0`.
- **`rpc`**: the tail's Thunderbolt link-local address on the reference
  setup. It's only a fallback for the hand-managed plist; the agent and
  `--rpc auto` discover it.

### Proxy

`n_slots` is shared with llama-server and must equal its `--parallel`.
Other keys are under `"proxy"`.

| flag | env | config key | default | meaning |
|---|---|---|---|---|
| `--n-slots` | `CARAVAN_N_SLOTS` | `llama_server.n_slots` | `4` | slots to spread sessions over |
| `--slot-save-every` | `CARAVAN_SLOT_SAVE_EVERY` | `proxy.slot_save_every` | `1` | save a session's KV to disk every N completed turns |
| `--slot-idle-save-seconds` | `CARAVAN_SLOT_IDLE_SAVE_SECONDS` | `proxy.slot_idle_save_seconds` | `0` (off) | if > 0: no saves after each reply; save once a session has been idle this long (60 is reasonable) |
| `--prompt-fingerprint-chars` | `CARAVAN_PROMPT_FINGERPRINT_CHARS` | `proxy.prompt_fingerprint_chars` | `2048` | prompt-style calls: prefix length that identifies a session |
| -- | `CARAVAN_UPSTREAM_HOST` / `CARAVAN_UPSTREAM_PORT` | -- | `127.0.0.1` / `8080` | llama-server |
| -- | `CARAVAN_PROXY_PORT` | -- | `8090` | listen port (127.0.0.1 only) |
| -- | `CARAVAN_PROXY_STATE_FILE` | -- | `~/.caravan/proxy/session_slots.json` | slot occupancy |
| -- | `CARAVAN_SLOT_SAVE_DIR` | -- | `~/.caravan/llama-server/slots` | must match `--slot-save-path` |

MLX backend (since 2026-10-30, step a). Completions whose `model` is an
MLX id go to an `mlx_lm.server` on the same Mini; everything else still
goes to llama-server. Same FIFO, same session fingerprint, but no slot:
the log says `backend=mlx … cache=mlx-noop` (MLX prompt-cache persistence
is step b, see `proxy/backends.py`). Keys are under `"mlx"`.

| flag | env | config key | default | meaning |
|---|---|---|---|---|
| `--mlx-host` / `--mlx-port` | `CARAVAN_MLX_HOST` / `CARAVAN_MLX_PORT` | `mlx.host` / `mlx.port` | `127.0.0.1` / `8092` | mlx_lm.server |
| `--mlx-prefixes` | `CARAVAN_MLX_PREFIXES` | `mlx.model_prefixes` | `mlx-community/` | model ids routed to MLX |
| -- | -- | `mlx.models` | `{}` | explicit `{"alias-or-id": "/local/dir"}` (also routed to MLX) |
| -- | `CARAVAN_MLX_MODEL_DIRS` | `mlx.model_dirs` | `~/.exo/models, ~/.caravan/models/mlx` | where `org/name` is looked up as `org--name/` |
| `--no-mlx` | `CARAVAN_MLX_ENABLED=0` | `mlx.enabled` | on | route everything to llama-server |

The request's `model` is rewritten to the local directory, so mlx_lm never
downloads anything. To start the server: `caravan_agent.py --model
mlx-community/<name> --apply` (role MLX), or render a launchd job with
`python3 agent/render_mlx_plist.py mlx-community/<name>` (writes
`launchd/com.caravan.mlx-server.plist`; loading it is manual). Python:
`mlx.python` / `CARAVAN_MLX_PYTHON`, default
`~/.caravan/venvs/mlx/bin/python` (`python3 -m venv ~/.caravan/venvs/mlx &&
~/.caravan/venvs/mlx/bin/pip install mlx-lm`).

Known limits with mlx-lm 0.32.2 on a 24 GB Mini (measured 2026-10-30, see docs/LOG.md):
- Qwen3-30B-A3B 4-bit needs `mlx.extra_args` such as `["--prompt-cache-size", "1", "--prompt-cache-bytes", "536870912", "--prefill-step-size", "512"]`. The default prompt cache keeps 10 sequences on the GPU and runs out of Metal memory.
- GPT-OSS replies come back with raw harmony markup (`<|channel|>analysis…`) in `content`. Clients must send back only the final channel, or mlx_lm fails the next turn.
- Gemma 4 and GPT-OSS (sliding-window models) got no in-memory reuse between chat turns. Qwen did (0.44 s turn 2).

How the proxy behaves:

- **Sessions.** Chat requests are identified by a hash of their first
  non-system message (skipping a synthetic, timestamped "session bootstrap"
  marker that some clients insert). Raw-prompt requests (`/completion`,
  `/v1/completions`) use a hash of the prompt's first 2048 characters, since
  a growing conversation keeps its prefix. Shorter or batched prompts are
  one-shots: they get a slot but are never pinned, saved or restored. Two
  different prompts sharing the same first 2048 characters would share a
  session.
- **Slots.** A returning session gets its slot back. A new session takes an
  empty slot or else the least recently used one.
- **Serialization.** Completions run one at a time, first come first served,
  instead of competing for the same GPUs and evicting each other's cache. If the client
  disconnects, the upstream request is cancelled.
- **Disk saves.** After a reply, a session's KV cache is saved to
  `<fingerprint>.bin` (about 1 GB for a long session). A save is skipped if
  the slot's token count hasn't changed. You can save every N turns instead,
  or switch on the idle saver to take saves out of the response path. A
  session with unsaved turns is always saved before its slot is given to
  another. With N > 1 or the idle saver, a llama-server crash can lose a
  few turns of *cache* (the session just reprocesses).
- **Restores.** On a session's first request after a restart, its saved
  cache is restored, unless llama-server still holds that session warm in
  that slot.
- **Streaming.** Response chunks are passed on as they arrive. Responses
  without a Content-Length are re-chunked for HTTP/1.1 clients (so
  keep-alive works); HTTP/1.0 clients get `Connection: close`.

### Slot-file cleanup (proxy)

The proxy deletes stale slot files at startup and then periodically,
waiting its turn in the request queue so it never overlaps a save or
restore. Config keys are under `"slot_cleanup"`.

| proxy flag | standalone flag | env | config key | default |
|---|---|---|---|---|
| `--slot-cleanup` | `--mode` | `CARAVAN_SLOT_CLEANUP` (`delete`/`archive`/`off`) | `mode` | `delete` |
| `--slot-max-age-days` | `--max-age-days` | `CARAVAN_SLOT_MAX_AGE_DAYS` | `max_age_days` | `30` |
| `--slot-archive-dir` | `--archive-dir` | `CARAVAN_SLOT_ARCHIVE_DIR` | `archive_dir` | `~/.caravan/llama-server/slots-archive` |
| `--slot-cleanup-interval-hours` | `--interval-hours` | `CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS` (`<= 0` = startup only) | `interval_hours` | `6` |
| -- | `--slot-dir` | `CARAVAN_SLOT_SAVE_DIR` | `slot_dir` | `~/.caravan/llama-server/slots` |

Age is the file's modification time (last save). `archive` moves files
instead of deleting them; the archive is never pruned automatically.

## Operations

**Check status:**

```sh
launchctl list | grep caravan
curl http://127.0.0.1:8080/health     # llama-server
curl http://127.0.0.1:8090/health     # through the proxy
curl http://127.0.0.1:8080/slots      # per-slot state
curl http://127.0.0.1:8091/health     # caravan-agent (node id, stats, fast paths)
tail -f ~/Library/Logs/caravan/*.log
```

**Slot-file cleanup by hand** (from the repo root):

```sh
python3 -m proxy.slot_cleanup --dry-run                   # what would go, and total size
python3 -m proxy.slot_cleanup --mode archive --max-age-days 30
python3 -m proxy.slot_cleanup                              # delete files older than 30 days
```

Cleanup also runs as soon as the proxy starts. To review first, set
`CARAVAN_SLOT_CLEANUP=off` and use `--dry-run`.

**Switching models:**

```sh
python3 agent/ollama_store.py --list                # models in the local Ollama store
python3 agent/ollama_store.py qwen3:30b-a3b         # -> GGUF blob path for llama-server -m
CARAVAN_MODEL=qwen3:30b-a3b python3 agent/caravan_agent.py   # agent dry run with that model
```

The agent resolves the model itself. For the hand-managed plist,
regenerate it:

```sh
python3 agent/render_llama_plist.py --model qwen3:30b-a3b --rpc auto \
    --output launchd/com.caravan.llama-server.plist
```

`--rpc auto` discovers the tail (it needs `caravan-agent` running there);
otherwise pass `--rpc host:port`. Any llama-server setting above can be
given as a flag too. The tool only writes the file; re-bootstrap the job
yourself ([launchd/README.md](launchd/README.md)).

**Restarts.** After a plist's arguments change, `bootout` + `bootstrap`
(`kickstart` doesn't re-read the file). After a Python-only change,
`launchctl kickstart -k gui/$(id -u)/com.caravan.<name>` is enough.
**Never restart the tail's `rpc-server` while the head's `llama-server`
is running** -- llama-server holds a live RPC session and crashes. Stop
llama-server first, or use `scripts/restart-rpc-server.sh`, which checks
that slots are idle and does the stop/restart/start sequence (set
`CARAVAN_NODE_B_HOST` / `CARAVAN_NODE_B_USER` for your tail).

## Limitations and known issues

- **The Thunderbolt address can change.** macOS self-assigns 169.254.x.x
  link-local addresses, which can change after re-cabling or an interface
  reset. The plist's `--rpc` fallback is a literal address; prefer the
  agent or `render_llama_plist.py --rpc auto`, which discover it.
- **New llama-server flags are unbenchmarked.** Flash attention over the
  RPC backend, the q8_0 KV cache and larger `-ub` values need a restart
  and a benchmark on real hardware before they count as proven.
- **The C++ binary hardcodes the model** (`cpp/main.cpp`), and lacks
  `--cache`, the health server, identity and crash supervision.
- **The agent needs Python 3.10+**; the proxy and tests run on 3.9+.
- **The launchd plists contain absolute paths** for one user's home
  directory; edit them for your machine. The proxy plist's
  `CARAVAN_PINNED_SLOT` is a leftover the proxy no longer reads.
- **The agent doesn't run the proxy yet**; it's a separate service.
- **Head selection is "whoever has the model"**: no leader election, and no
  handling of two nodes that both have it.
- **Only tested with two nodes**, both Apple Silicon Macs.
- **RPC is unauthenticated**: keep it on a private link.

## Repository layout

| path | what |
|---|---|
| `agent/` | caravan-agent: discovery, role detection, supervision, config, plist renderer |
| `proxy/` | slot-pinning proxy and slot-file cleanup |
| `launchd/` | launchd plists and how to install them |
| `cpp/` | experimental single-binary head/tail |
| `scripts/` | operational scripts (safe tail restart) |
| `tests/` | stdlib `unittest` suite: `python3 -m unittest discover -s tests -v` |
| `docs/` | [ARCHITECTURE.md](docs/ARCHITECTURE.md), [PLAN.md](docs/PLAN.md), and [LOG.md](docs/LOG.md), a dated engineering log with all the measurements and dead ends |
