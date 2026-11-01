# Configuration

Every setting has a default, so Caravan runs with no configuration at all.
Where a setting can be given more than one way, the order is:

**command-line flag > environment variable > `~/.caravan/config.json` > default**

The config file path can be changed with `CARAVAN_CONFIG` (the agent and
the standalone cleanup also take `--config`). A missing file is fine. An
unreadable file is reported with a warning and ignored.

All names below were checked against the v3 code (branch
`caravan-v3-mlx-split`). Everything except the MLX split section is the
same on `main` (v2.1).

## The config file

Every section is optional:

```json
{
  "model": "gpt-oss-20b",
  "llama_server": {
    "n_slots": 4, "ctx_per_slot": 65536, "flash_attn": "on",
    "cache_type_k": "auto", "cache_type_v": "auto", "cache_ram_mib": 0,
    "n_gpu_layers": 999, "batch_size": 2048, "ubatch_size": 512,
    "swa_full": false, "rpc": "auto"
  },
  "kv_auto": { "safety_margin_mib": 256 },
  "proxy": {
    "slot_save_every": 1, "slot_idle_save_seconds": 0,
    "prompt_fingerprint_chars": 2048, "mlx_save_min_turns": 1
  },
  "mlx": {
    "enabled": true, "host": "127.0.0.1", "port": 8092,
    "model_prefixes": ["mlx-community/"],
    "models": { "qwen3-30b-mlx": "~/.exo/models/mlx-community--Qwen3-30B-A3B-4bit" },
    "model_dirs": ["~/.exo/models", "~/.caravan/models/mlx"],
    "cache_dir": "~/.caravan/mlx/prompt-cache",
    "server": "caravan", "python": "~/.caravan/venvs/mlx/bin/python", "extra_args": [],
    "split": { "packer": "169.254.x.y:5560", "packer_layers": 24 }
  },
  "slot_cleanup": {
    "mode": "archive", "max_age_days": 30, "interval_hours": 6,
    "max_count": 200, "max_gb": 50, "protect_minutes": 30
  }
}
```

After a change, restart whatever reads the setting: the agent (or
`launchctl kickstart -k`) for `model`, `llama_server`, `kv_auto` and the
MLX launch keys; the proxy for `proxy`, `mlx` routing and `slot_cleanup`.
A launchd plist only changes when it's re-rendered and bootstrapped again.

## Agent: `agent/caravan_agent.py`

| flag | env | config | default | what |
|---|---|---|---|---|
| `--model` | `CARAVAN_MODEL` | `model` | `muse-glimmer` | Model to serve. An Ollama-store name (`name`, `name:tag`, `namespace/name:tag`) for GGUF, or an MLX id (`mlx-community/...`) for the MLX role. |
| `--config` | `CARAVAN_CONFIG` | – | `~/.caravan/config.json` | Config file path. |
| `--apply` | – | – | off | Start and supervise. Without it, the agent only prints its role and the command (a dry run). |
| `--serve-for SECONDS` | – | – | – | Dry run only: keep the health endpoint and mDNS advertisement up for N seconds after printing the plan, so another Mac's dry run can discover this one. |

### llama-server settings (lead)

The agent, `agent/render_llama_plist.py` and the proxy (for `n_slots`)
all read these.

| flag | env | config `llama_server.` | default | what |
|---|---|---|---|---|
| `--n-slots` | `CARAVAN_N_SLOTS` | `n_slots` | `4` | Parallel slots (`--parallel`). Each conversation in memory needs one. |
| `--ctx-per-slot` | `CARAVAN_CTX_PER_SLOT` | `ctx_per_slot` | `65536` | Context per slot. The total is `-c n_slots × ctx_per_slot`, with `--no-kv-unified` so each slot owns its share. |
| `--flash-attn` | `CARAVAN_FLASH_ATTN` | `flash_attn` | `on` | `on`, `off` or `auto`. A quantized V cache needs `on` or `auto`. |
| `--cache-type-k` | `CARAVAN_CACHE_TYPE_K` | `cache_type_k` | `auto` | `auto`, `f32`, `f16`, `bf16`, `q8_0`, `q4_0`, `q4_1`, `iq4_nl`, `q5_0`, `q5_1`. `auto` = f16 if it fits, else q8_0 (see kv_auto below). |
| `--cache-type-v` | `CARAVAN_CACHE_TYPE_V` | `cache_type_v` | `auto` | Same choices. |
| `--cache-ram` | `CARAVAN_CACHE_RAM_MIB` | `cache_ram_mib` | `0` | llama-server's host prompt cache in MiB. 0 = off, -1 = unlimited. Off by default because it competes with the GPU for the same unified memory. |
| `--n-gpu-layers` | `CARAVAN_N_GPU_LAYERS` | `n_gpu_layers` | `999` | Layers on the GPU (all). |
| `--batch-size` | `CARAVAN_BATCH_SIZE` | `batch_size` | `2048` | Logical batch. |
| `--ubatch-size` | `CARAVAN_UBATCH_SIZE` | `ubatch_size` | `512` | Physical batch. Larger reads long prompts faster but costs compute memory. |
| `--swa-full` | `CARAVAN_SWA_FULL` | `swa_full` | off | Full-size cache for sliding-window layers. Uses much more memory; not needed on the rebased llama.cpp. |
| `--rpc` (render tool only) | `CARAVAN_RPC_ADDR` | `rpc` | `169.254.104.38:50052` | Comma-separated `host:port` list, or `auto` to discover. The running agent always discovers. This default is a link-local address that can change, so prefer `auto`. |

Always passed, not configurable: `--slot-save-path
~/.caravan/llama-server/slots/`, `--no-kv-unified`, `--port 8080`, and
`--rpc`/`--device`/`--tensor-split` (even split) on a lead with peers.

`render_llama_plist.py` also takes `--model`, `--model-path` (use a GGUF
path directly), `--config` and `--output/-o` (default: stdout). It never
loads anything into launchd.

### Automatic KV cache type: `kv_auto`

Used only when a cache type is `auto`.

| env | config `kv_auto.` | default | what |
|---|---|---|---|
| `CARAVAN_GPU_WORKING_SET_MIB` | `gpu_working_set_mib` | Metal's `recommendedMaxWorkingSetSize`, cached in `~/.caravan/agent/gpu_limit.json`; if that's unavailable, `iogpu.wired_limit_mb`, then 18186.25 | GPU memory budget per device, MiB. |
| `CARAVAN_COMPUTE_RESERVE_MIB` | `compute_reserve_mib` | ubatch × vocabulary × 4 B + 64 MiB | Room for llama.cpp's compute buffers. |
| `CARAVAN_KV_SAFETY_MARGIN_MIB` | `safety_margin_mib` | `256` | Extra headroom. |

To check what a model name resolves to in the Ollama store:

```sh
python3 agent/ollama_store.py --list           # models in the local store
python3 agent/ollama_store.py qwen3:30b-a3b    # GGUF blob path (for llama-server -m)
```

### Fixed paths and ports (agent)

| what | value |
|---|---|
| llama.cpp binaries | `~/dev/llama.cpp/build/bin/llama-server`, `ggml-rpc-server` |
| ports | llama-server 8080, rpc-server 50052, agent health 8091 |
| Ollama store | `~/.ollama/models` (`OLLAMA_MODELS` overrides) |
| node id, GPU limit cache | `~/.caravan/agent/` |
| child logs | `~/.caravan/agent/logs/{llama-server,rpc-server,mlx-server}.log` |
| packer's tensor cache | `~/Library/Caches/llama.cpp/rpc` (from `rpc-server --cache`) |

**The packer's tensor cache (GGUF split download, stage 1).** The packer
runs `ggml-rpc-server -c` / `--cache` (the agent passes it by default,
and so does `launchd/com.caravan.rpc-server.plist`). The packer then keeps the
weights it receives on its own disk, keyed by hash, so only the first load
sends them over the cable; a restart loads in about 53 s instead of 7–11
min over LAN. The lead still needs the whole GGUF on its own disk. A fork
patch that lets the packer load its own part from its own disk (stage 2)
is planned, not built; see [ROADMAP.md](ROADMAP.md).

## Proxy: `proxy/slot_pin_proxy.py`

### Connections and files (environment only)

| env | default | what |
|---|---|---|
| `CARAVAN_PROXY_PORT` | `8090` | Port to listen on. It always binds 127.0.0.1. |
| `CARAVAN_UPSTREAM_HOST` | `127.0.0.1` | llama-server host. |
| `CARAVAN_UPSTREAM_PORT` | `8080` | llama-server port. |
| `CARAVAN_PROXY_STATE_FILE` | `~/.caravan/proxy/session_slots.json` | Session → slot table. |
| `CARAVAN_SLOT_SAVE_DIR` | `~/.caravan/llama-server/slots` | Where llama-server writes slot files (must match its `--slot-save-path`). |

### Sessions and saving

| flag | env | config | default | what |
|---|---|---|---|---|
| `--n-slots` | `CARAVAN_N_SLOTS` | `llama_server.n_slots` | `4` | Must match llama-server. |
| `--slot-save-every` | `CARAVAN_SLOT_SAVE_EVERY` | `proxy.slot_save_every` | `1` | Save a session every N turns (both backends). |
| `--slot-idle-save-seconds` | `CARAVAN_SLOT_IDLE_SAVE_SECONDS` | `proxy.slot_idle_save_seconds` | `0` (off) | llama.cpp only: also save a session after N idle seconds. |
| `--prompt-fingerprint-chars` | `CARAVAN_PROMPT_FINGERPRINT_CHARS` | `proxy.prompt_fingerprint_chars` | `2048` (min 64) | Raw-prompt requests: how many leading characters identify the session. Shorter prompts aren't pinned. |
| `--mlx-save-min-turns` | `CARAVAN_MLX_SAVE_MIN_TURNS` | `proxy.mlx_save_min_turns` | `1` | MLX only: first turn that gets saved. `2` skips saving one-off chats. |

### MLX routing (proxy) and launch (agent)

| flag | env | config `mlx.` | default | what |
|---|---|---|---|---|
| `--no-mlx` | `CARAVAN_MLX_ENABLED` (`0`/`1`) | `enabled` | on | Route MLX models at all. |
| `--mlx-host` | `CARAVAN_MLX_HOST` | `host` | `127.0.0.1` | MLX worker host. |
| `--mlx-port` | `CARAVAN_MLX_PORT` | `port` | `8092` | MLX worker port (the agent starts the worker on it). |
| `--mlx-prefixes` | `CARAVAN_MLX_PREFIXES` | `model_prefixes` | `mlx-community/` | Model ids with these prefixes are MLX. Comma-separated (a list in JSON). |
| – | – | `models` | `{}` | Explicit `alias → local directory` map. Aliases are MLX too. |
| – | `CARAVAN_MLX_MODEL_DIRS` | `model_dirs` | `~/.exo/models`, `~/.caravan/models/mlx` | Where to find `org--name/` or `org/name/` model directories (they must contain `config.json`). |
| – | `CARAVAN_MLX_CACHE_DIR` | `cache_dir` | `~/.caravan/mlx/prompt-cache` | Saved MLX sessions (`<fingerprint>.safetensors`). Read by the worker, the proxy and cleanup. |
| – | `CARAVAN_MLX_SERVER` | `server` | `caravan` | `caravan` (the MLX worker) or `mlx_lm` (plain `mlx_lm.server`: no saved sessions, and sliding-window models don't reuse their cache). |
| – | `CARAVAN_MLX_PYTHON` | `python` | `~/.caravan/venvs/mlx/bin/python` | Python with `mlx-lm` installed. |
| – | `CARAVAN_MLX_EXTRA_ARGS` | `extra_args` | none | Extra arguments for the worker: a list in JSON, space-separated in the env var, e.g. `--kv-bits 8 --prompt-cache-size 2`. |

If the model isn't found locally, the request fails rather than
downloading anything.

### Saved-chat cleanup and the per-Mac cap

> **Warning: the default mode is `delete`.** At startup, and every 6 hours
> after that, the proxy permanently deletes saved chats (llama.cpp `.bin`
> and MLX `.safetensors`) that are older than 30 days. If the remaining
> saves are over 200 files or 50 GB, it also deletes the least recently
> used ones. Deleted conversations still work; they just start cold next
> time. Before the first start on a Mac with saves you care about, run
> `python3 -m proxy.slot_cleanup --dry-run -v` from the repo root to see
> what would go. To keep the files, use `archive` (it moves them and
> never deletes) or `off`.

| proxy flag | standalone flag | env | config `slot_cleanup.` | default | what |
|---|---|---|---|---|---|
| `--slot-cleanup` | `--mode` | `CARAVAN_SLOT_CLEANUP` | `mode` | **`delete`** | `delete`, `archive` or `off`. Applies to both the age rule and the cap. |
| `--slot-max-age-days` | `--max-age-days` | `CARAVAN_SLOT_MAX_AGE_DAYS` | `max_age_days` | `30` | Age rule, by the file's last-write time. |
| `--slot-archive-dir` | `--archive-dir` | `CARAVAN_SLOT_ARCHIVE_DIR` | `archive_dir` | `~/.caravan/llama-server/slots-archive` | Where `archive` moves files (MLX files go into its `mlx/` subfolder). Never pruned. |
| `--slot-cleanup-interval-hours` | `--interval-hours` | `CARAVAN_SLOT_CLEANUP_INTERVAL_HOURS` | `interval_hours` | `6` | How often the proxy re-runs cleanup. 0 or less = only at startup. |
| `--slot-max-count` | `--max-count` | `CARAVAN_SLOT_MAX_COUNT` | `max_count` | `200` | Cap on saved files, both kinds together. 0 = no count cap. |
| `--slot-max-gb` | `--max-gb` | `CARAVAN_SLOT_MAX_GB` | `max_gb` | `50` | Cap on total size in GB (10^9 bytes). 0 = no size cap. |
| `--slot-protect-minutes` | `--protect-minutes` | `CARAVAN_SLOT_PROTECT_MINUTES` | `protect_minutes` | `30` | The cap never removes a session with a turn this recent, one that's in a slot now, or one with unsaved turns. |

Standalone run: `python3 -m proxy.slot_cleanup` from the repo root. It also takes:

| flag | env | default | what |
|---|---|---|---|
| `--slot-dir` | `CARAVAN_SLOT_SAVE_DIR` | `~/.caravan/llama-server/slots` | llama.cpp saves. |
| `--mlx-dir` | `CARAVAN_MLX_CACHE_DIR` | not scanned | MLX saves (the proxy always passes its MLX cache dir). |
| `--state-file` | `CARAVAN_PROXY_STATE_FILE` | `~/.caravan/proxy/session_slots.json` | So cap protection knows the sessions in slots. |
| `--config` | `CARAVAN_CONFIG` | `~/.caravan/config.json` | |
| `--dry-run` | – | off | Report only. |
| `-v` | – | off | List each file. |

If the proxy is running, the standalone tool can't see which sessions
are live in memory. Use `--dry-run`, or let the proxy do it.

## MLX worker: `agent/mlx_worker.py`

The agent starts the worker with `--model <local dir> --host --port
--cache-dir` from the `mlx` settings, plus `mlx.extra_args`. To run it
by hand: `~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --model <dir>`.

| flag | default | what |
|---|---|---|
| `--model` | required | Local model directory (or id). |
| `--host` / `--port` | `127.0.0.1` / `8092` | Listen address. |
| `--prompt-cache-size` | `4` | Sessions kept in memory. |
| `--prompt-cache-bytes` | `2G` | Memory budget for all sessions' caches; accepts `512M`, `2G`. The session in use is never evicted. |
| `--prefill-step-size` | `2048` | Prompt tokens read per step. |
| `--max-tokens` | `512` | Default reply limit when a request sets none. |
| `--cache-dir` | `$CARAVAN_MLX_CACHE_DIR` or `~/.caravan/mlx/prompt-cache` | Saved sessions. |
| `--no-persist` | off | Never read or write cache files. |
| `--kv-bits` | off | `4` or `8`: quantize the full-attention cache layers. Smaller memory and files, somewhat slower reads (Qwen3 4k: 380 → 325 tok/s with 8). |
| `--kv-group-size` | `64` | Group size for `--kv-bits`. |
| `--cache-limit-gb` | off | Cap MLX's pool of freed GPU buffers. |
| `--wired-limit` | `startup` | `startup`: raise Metal's wired limit once and hold it. `per-request`: raise and drop it around each request (v2 behaviour). `off`: never touch it. |

Split flags (v3; see the next section):

| flag | default | what |
|---|---|---|
| `--split-role` | `none` | `lead` (serves the API, runs the last layers, picks each token) or `packer` (runs the embeddings and the first layers; no HTTP). `head` / `front` are deprecated aliases. |
| `--split-peer HOST:PORT` | – | Lead only: Packer 1's address, normally its Thunderbolt address, port 5560. |
| `--split-listen HOST:PORT` | – | Packer only: where to listen (its Thunderbolt address). |
| `--split-packer-layers K` | half (the odd layer goes to the lead) | How many layers Packer 1 runs. Use the same value on both Macs; the lead refuses to start if the two disagree. `--split-front-layers` is a deprecated alias. |
| `--split-keepalive` / `--no-split-keepalive` | on | Keep Metal warm with a tiny eval on a short-lived thread while waiting for the peer (cuts ~5 ms/half cool-down). Env `CARAVAN_MLX_SPLIT_KEEPALIVE=0` / `false` / `off` / `no` also disables. |
| `--split-pipeline-chats N` | 1 | Idea 1: overlap packer/lead across up to N concurrent split chats (1 = off). Env `CARAVAN_MLX_SPLIT_PIPELINE_CHATS`. |

`python3 agent/render_mlx_plist.py <model> [--port] [--host] [--python]
[-o PATH]` writes `launchd/com.caravan.mlx-server.plist` (label
`com.caravan.mlx-server`, log `~/.caravan/logs/mlx-server.log`) from the
same settings. Loading it into launchd is a manual step.

## MLX split across two Macs (v3)

One MLX model can run across two Macs: Packer 1 runs the first layers and
the lead runs the rest. How it works: [MLX-SPLIT.md](MLX-SPLIT.md).

| env | config `mlx.split.` | default | what |
|---|---|---|---|
| `CARAVAN_MLX_SPLIT_PACKER` | `packer` | none (no split) | Packer 1's `HOST:PORT`. Setting it turns the split on. |
| `CARAVAN_MLX_SPLIT_PACKER_LAYERS` | `packer_layers` | half | Layers on Packer 1 (1 or more). |
| `CARAVAN_MLX_SPLIT_KEEPALIVE` | (flag only) | on | `0` / `false` / `off` / `no` disables GPU keepalive while waiting on the peer. |
| `CARAVAN_MLX_SPLIT_PIPELINE_CHATS` | (flag only) | 1 | Idea 1 max concurrent pipelined chats (1 = off). |

Order: flag > env > config, as everywhere else. The split needs the
Caravan worker (`mlx.server = "caravan"`); with `mlx_lm` it's an error.

**What reads these today.** Only the helpers in `agent/mlx_backend.py`:
`build_lead_command()` adds the lead's split flags to the normal worker
command, and `build_packer_command()` gives the matching command for the
packer Mac. `caravan_agent.py --apply` and `render_mlx_plist.py` still
start a one-Mac worker, so for now start both halves by hand with the
flags above (packer first). Wiring the split into the agent is on the
[roadmap](ROADMAP.md).

### Split download: `agent/mlx_split_fetch.py`

A prototype command that downloads only one Mac's part of an MLX model
from Hugging Face, instead of the whole model on every Mac:

```sh
python3 agent/mlx_split_fetch.py <hf repo> <local dir> --role lead|packer [--packer-layers K] [--dry-run]
```

| flag | what |
|---|---|
| `--role` | `lead` or `packer` (`head` / `front` are deprecated aliases). |
| `--packer-layers K` | Same cut as the workers (default half). `--front-layers` is a deprecated alias. |
| `--with-vision` | Also fetch vision or audio parts (skipped by default; the split is text-only). |
| `--dry-run` | Print the plan (files and sizes) without downloading the weights (it still fetches the small `config.json` and index file). |

Files that hold layers on both sides of the cut go to both Macs. After a
real download it saves the shard sizes Hugging Face lists in
`caravan-split-sizes.json` in the model folder. The worker refuses to start
a stage whose files are missing or the wrong size (checked against that
file when it's there, and always against each shard's own safetensors
header), and tells you which file and which command to run. It needs
`huggingface_hub` in the Python you run it with. Nothing is ever deleted;
leftover `.incomplete` files from an interrupted download stay on disk.

### Deprecated names

The split roles were renamed on Oct 31, 2026: **lead** (the Mac you talk
to), **packers** (the others, numbered in layer order; Packer 1 runs the
first layers), and the **string** (the whole group). The old names still
work, but new setups should use the new ones. When both are given, the
new one wins.

| New | Deprecated |
|---|---|
| `--split-role lead` / `packer` | `--split-role head` / `front` |
| `--split-packer-layers` | `--split-front-layers` |
| `mlx.split.packer` / `packer_layers` | `mlx.split.front` / `front_layers` |
| `CARAVAN_MLX_SPLIT_PACKER` / `_PACKER_LAYERS` | `CARAVAN_MLX_SPLIT_FRONT` / `_FRONT_LAYERS` |
| `mlx_backend.build_lead_command()` / `build_packer_command()` | `build_head_command()` / `build_front_command()` |
| `mlx_split_fetch.py --role lead\|packer --packer-layers` | `--role head\|front --front-layers` |

Names that are internal only and weren't renamed: the role values inside
the code (`head`, `front`, `tail`), `supervisor.build_head_command()` and
`build_tail_command()` (the llama.cpp lead and packer commands), and the
stage id saved inside split caches (for example `head 24-47 of 48`), so
existing caches still load. `GET /caravan/split` reports `lead` and
`packers` and still includes the old `head` / `front` keys.

## Scripts

`scripts/restart-rpc-server.sh` restarts the packer safely. It checks that
the lead's slots are idle, stops the lead, restarts the packer, then starts
the lead. Set `CARAVAN_NODE_B_HOST` and `CARAVAN_NODE_B_USER` to reach the
packer.
