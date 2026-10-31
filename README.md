# Caravan

**Local LLM serving for a small group of Apple Silicon Macs: as robust as
llama.cpp, for both GGUF and MLX models, with one model split across two
Macs when it doesn't fit on one.**

Caravan is the layer between an OpenAI-compatible client (for example, a
personal assistant gateway) and the model servers on your Macs. It started
as a way to run a GGUF model that is too big for one 24 GB Mac mini across
two of them, using llama.cpp's RPC backend over a Thunderbolt cable. It has
since grown into the everyday backend that keeps each conversation's cache
warm, saves it to disk so it survives restarts, and serves MLX models
through the same entry point. Since v3 it can also split one MLX model
across two Macs.

> **Status: early, experimental.** `main` is v2.1. v3 (one MLX model
> split across two Macs) is on the `caravan-v3-mlx-split` branch, waiting
> for review. Caravan runs one personal assistant on a pair of Mac minis
> (M4, 24 GB each). It isn't packaged, and it hasn't been tested on other
> setups. The launchd plists still contain machine-specific paths. See
> [docs/CHANGELOG.md](docs/CHANGELOG.md) for what changed in each version
> and [docs/ROADMAP.md](docs/ROADMAP.md) for what's next.

## Names: lead, packers, string

When a model is split across Macs, the **lead** is the Mac you talk to:
it serves the API, runs the last layers and picks each token. The other
Macs are **packers**, numbered in layer order (Packer 1 runs the first
layers). The whole group is the **string**. Older docs and flags said
"head", "front" or "tail"; those flag and config names still work but
are deprecated (see [docs/CONFIGURATION.md](docs/CONFIGURATION.md#deprecated-names)).

## Why

- **Ollama** is easy, but it is single-machine by design and treats
  conversation caches as disposable.
- **exo** splits models across Macs, but only MLX models. In our tests on
  one 24 GB Mac mini it wrote fastest, but it used the most memory, its
  runner crashed on long Qwen prompts, and it doesn't save conversation
  caches to disk (see [docs/BENCHMARKS.md](docs/BENCHMARKS.md)).
- **llama.cpp** is solid, covers the large GGUF ecosystem, and its RPC
  backend can put part of a model on another Mac's GPU. But on its own it
  moves conversations between slots, throwing their cache away, and it
  doesn't know about MLX.

Caravan keeps llama.cpp's robustness and adds what daily use needs. Each
conversation keeps its own warm cache, which is saved to disk and loaded
back after a restart. Requests run one at a time. MLX models are served
next to GGUF models. Each Mac works out its own role.

## Features

- **One entry point** (`proxy/slot_pin_proxy.py`, port 8090): an
  OpenAI-compatible proxy. Each request goes to llama.cpp or MLX based on
  its `model` field.
- **Per-session caches.** Each conversation is recognized by a fingerprint
  (a hash of its first real message), and its cache is reused from one
  message to the next: a llama-server slot for GGUF, or a session cache in
  the Caravan MLX worker.
- **Chat save and restore on both backends.** After a reply, the session's
  cache is saved to disk (`<fingerprint>.bin` for llama.cpp,
  `<fingerprint>.safetensors` for MLX). After a restart it's loaded back,
  so the next message reads only what's new.
- **MLX backend** (`agent/mlx_worker.py`): Caravan's own MLX server. It
  keeps per-session caches that also work for sliding-window models
  (Gemma 4, GPT-OSS), returns GPT-OSS's reasoning separately from the
  answer, and locks the model in GPU memory at startup.
- **Two-Mac split for GGUF**: llama.cpp RPC. The lead Mac serves the model
  and the packer Mac lends its GPU. Over Thunderbolt the packer loads its part
  in 29–39 s, and `rpc-server --cache` keeps the packer's part on its own
  disk so a restart loads in about 53 s instead of 7–11 min.
- **Two-Mac split for MLX (v3, branch `caravan-v3-mlx-split`)**: Caravan's
  own layer-by-layer split over one TCP connection on the Thunderbolt
  cable. Each Mac holds about half the model, so bigger models and longer
  chats fit; writing is slower. Chat memory is kept and saved on both
  halves. See [docs/MLX-SPLIT.md](docs/MLX-SPLIT.md).
- **Automatic KV cache type**: f16 when it fits under the GPU memory
  limit, otherwise 8-bit (q8_0). The decision and its estimate are logged.
- **Saved-chat cleanup and a per-Mac cap**: saves older than 30 days are
  removed, and the saves that remain are capped at 200 files / 50 GB,
  least recently used first. Active sessions are never evicted.
- **Requests run one at a time**, first come first served. A request whose
  client hangs up is cancelled.
- **Self-organizing agent** (`agent/caravan_agent.py`): finds peers over
  mDNS and Tailscale, picks the fastest link (Thunderbolt, then Tailscale,
  then LAN), decides lead or packer (or MLX), and supervises the server.
- **launchd services** so everything survives crashes and reboots.

## Supported backends

| backend | models | runs on | cache reuse | saved across restarts |
|---|---|---|---|---|
| llama.cpp `llama-server` (+ `rpc-server` on the packer) | GGUF, from the local Ollama store | one Mac, or split across two over RPC | per-session slot | yes, llama-server slot files |
| Caravan MLX worker | MLX safetensors (`mlx-community/...`) from `~/.exo/models` or `~/.caravan/models/mlx` | one Mac, or split across two (v3, started by hand) | per-session cache, sliding-window layers included | yes, `.safetensors` per session (one per Mac when split) |
| plain `mlx_lm.server` (optional, `mlx.server = "mlx_lm"`) | MLX | one Mac | Qwen-style models only | no |

## Headline numbers

All measured; method and full tables are in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md). Single 24 GB Mac mini M4 unless
noted.

| what | before | after |
|---|---|---|
| Two Macs over Thunderbolt vs Wi-Fi/LAN, generation (Sep, 16 GB model) | ~3.8–4.5 tok/s | 6.1 tok/s |
| Packer model load, cold cache, Thunderbolt vs LAN | 7–11 min | 29–39 s |
| llama.cpp, 16k chat, first message after a restart (v0 → v1) | GPT-OSS 46.3 s, Gemma 4 56.1 s | 0.65 s, 0.93 s |
| llama.cpp reading speed, 4k prompt (v0 → v1) | GPT-OSS 403, Gemma 4 355, Qwen3 338 tok/s | 454, 380, 356 tok/s |
| MLX, turn 2 of a 4k chat (v1 → v2) | Gemma 4 10.76 s, GPT-OSS 9.16 s | 0.49 s, 0.50 s |
| MLX, first message after a restart, 4k chat (v1 → v2) | 12.7–16.0 s | 0.52–0.64 s |
| MLX, 16k chat, turn 2 (v1 → v2) | Gemma 4 55.1 s, GPT-OSS 37.3 s | 0.72 s, 0.59 s |
| MLX Qwen3 reading speed, 4k, side by side (v1 / v2 / v2.1) | 395.9 / 393.4 tok/s | 395.6 tok/s |
| MLX peak memory per Mac, one Mac → split across two (v2.1 → v3) | Qwen3 19.04, Gemma 4 17.14, GPT-OSS 13.41 GB | 10.49, 9.28, 7.05 GB |
| MLX Qwen3 30B, 16k chat (v2.1 → v3) | out of memory | fits (first read 81.9 s, turn 2 0.72 s) |
| MLX writing speed, one Mac → split (v2.1 → v3) | Qwen3 51.0, Gemma 4 41.3, GPT-OSS 36.5 tok/s | 29.5, 26.9, 26.1 tok/s (28–42% slower) |
| 8-bit models that don't fit one Mac, split (v3) | – | Qwen3 30B 20.6, Gemma 4 26B 18.1, GPT-OSS 20B 19.8 tok/s, all with a 16k chat |

## Quick start

Requirements:

- Apple Silicon Macs. Tested on M4 with 24 GB. Two are needed only for
  the GGUF split, ideally linked by a Thunderbolt/USB4 cable; a LAN or
  Tailscale also works, much more slowly.
- Python 3.10+ for the agent (Homebrew's `/opt/homebrew/bin/python3`). The
  proxy is stdlib-only and runs on 3.9+.
- For GGUF: llama.cpp built from source with `GGML_RPC=ON` and
  `GGML_METAL=ON` at `~/dev/llama.cpp` (Homebrew's build has no RPC), and
  [Ollama](https://ollama.com) on the lead as the model store.
- For MLX: a venv with `mlx-lm` (tested with 0.32.2) at
  `~/.caravan/venvs/mlx`, and the model downloaded locally. The agent,
  proxy and worker never download models (the v3 split-download tool,
  `agent/mlx_split_fetch.py`, is a separate command you run yourself).

```sh
git clone https://github.com/linuxbren/caravan ~/dev/caravan
git clone -b caravan-patches https://github.com/linuxbren/llama.cpp ~/dev/llama.cpp
cd ~/dev/llama.cpp && cmake -B build -DGGML_RPC=ON -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
python3 -m venv ~/.caravan/venvs/mlx && ~/.caravan/venvs/mlx/bin/pip install mlx-lm
```

`caravan-patches` is upstream llama.cpp (`5047748f`) plus Caravan's RPC
patch. That base also restores Gemma and GPT-OSS chats after a restart,
and it's what the v1+ numbers were measured on. The older base used for
the v0 benchmarks is kept on the `caravan-patches-v0` branch.

**GGUF, split across two Macs.** Pull the model on the lead, then run the
agent on both Macs, starting with the packer:

```sh
ollama pull <model>
cd ~/dev/caravan/agent
/opt/homebrew/bin/python3 caravan_agent.py --model <model>           # dry run: prints the role and command
/opt/homebrew/bin/python3 caravan_agent.py --model <model> --apply   # start and supervise it
```

**MLX, one Mac.** With the model in `~/.exo/models/mlx-community--<name>`
or `~/.caravan/models/mlx/mlx-community--<name>`:

```sh
/opt/homebrew/bin/python3 caravan_agent.py --model mlx-community/<name> --apply
```

**MLX, split across two Macs (v3).** Each Mac needs its own copy of the
model (or just its own part, from `agent/mlx_split_fetch.py`). Start
Packer 1 first, then the lead; the agent doesn't start a split yet:

```sh
# on the packer Mac
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role packer \
  --split-listen <packer-thunderbolt-ip>:5560 --model <local model dir>
# on the lead Mac
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role lead \
  --split-peer <packer-thunderbolt-ip>:5560 --model <local model dir> --port 8092
```

Details: [docs/MLX-SPLIT.md](docs/MLX-SPLIT.md).

**Then the proxy, on the lead**, and point your client at it:

```sh
python3 ~/dev/caravan/proxy/slot_pin_proxy.py        # 127.0.0.1:8090
curl http://127.0.0.1:8090/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/<name>","messages":[{"role":"user","content":"Hello"}]}'
```

> **Before you start the proxy on a Mac that already has saved chats**,
> know that cleanup runs at startup in `delete` mode. Check first with
> `python3 -m proxy.slot_cleanup --dry-run` (from the repo root), or set
> `CARAVAN_SLOT_CLEANUP=archive`. See
> [docs/CONFIGURATION.md](docs/CONFIGURATION.md#saved-chat-cleanup-and-the-per-mac-cap).

To run everything under launchd, see [launchd/README.md](launchd/README.md).
Nothing needs configuring: every setting has a default. See
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Operations

```sh
curl http://127.0.0.1:8090/health          # through the proxy (to llama-server)
curl http://127.0.0.1:8080/slots           # llama-server slots
curl http://127.0.0.1:8092/caravan/cache   # MLX worker: sessions in memory
curl http://127.0.0.1:8092/caravan/split   # MLX split (v3, on the lead): both halves, link stats
curl http://127.0.0.1:8091/health          # caravan-agent: node id, stats, fast paths
tail -f ~/Library/Logs/caravan/*.log
```

- **Never restart the packer's `rpc-server` while the lead's `llama-server`
  is running**: llama-server holds a live RPC session and crashes. Use
  `scripts/restart-rpc-server.sh` (it checks the slots are idle, then
  stops, restarts and starts in order).
- After a launchd plist's arguments change: `bootout` then `bootstrap`
  (`kickstart` doesn't re-read the file). For a Python-only change,
  `launchctl kickstart -k gui/$(id -u)/com.caravan.<name>` is enough.
- Tests: `python3 -m unittest discover -s tests -v` (stdlib only; 126
  tests on the v3 branch).

## Documentation

| doc | what |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | components, request flow, sessions, save/restore, cache choices, diagrams |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | every flag, env var and config key, with defaults |
| [docs/MLX.md](docs/MLX.md) | how the MLX worker works, GPT-OSS reasoning, limits |
| [docs/MLX-SPLIT.md](docs/MLX-SPLIT.md) | v3: one MLX model split across two Macs, lead / packer names, split download |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | how we measure, and the results by version |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | what changed in each version (v0 → v3) |
| [docs/ROADMAP.md](docs/ROADMAP.md) | done by version, next in order, ideas, parked items, known limits |
| [docs/LOG.md](docs/LOG.md) | the dated build log: every measurement and dead end |
| [agent/README.md](agent/README.md), [launchd/README.md](launchd/README.md), [cpp/README.md](cpp/README.md), [bench/improvements/README.md](bench/improvements/README.md), [bench/v3/README.md](bench/v3/README.md) | per-directory notes |

## Repository layout

| path | what |
|---|---|
| `agent/` | caravan-agent (discovery, role, supervision, settings, auto KV), the MLX worker and its launcher, the MLX split (`mlx_split.py`) and split download (`mlx_split_fetch.py`), plist renderers |
| `proxy/` | the proxy, backend routing, saved-chat cleanup |
| `launchd/` | launchd plists and how to install them |
| `bench/` | benchmark scripts: `improvements/` (v0 → v1), `v2/`, `v2.1/` (same-session A/B), `v3/` (one Mac vs split) |
| `cpp/` | experimental single binary (lead or packer in-process) |
| `scripts/` | safe packer restart |
| `tests/` | stdlib `unittest` suite |
| `docs/` | the documentation above |

*(Formerly "llama-shard"; the early history is in [docs/LOG.md](docs/LOG.md).)*
