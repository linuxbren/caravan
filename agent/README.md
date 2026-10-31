# caravan-agent

The self-organizing part of Caravan (design:
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)). The same script
runs on every node, and each instance decides for itself whether its
machine is the **lead** or a **packer** (the whole group is the
**string**):

- **Lead**: the target model is in this node's local Ollama store. The
  agent discovers live packers and runs `llama-server` with `--rpc`
  pointed at them.
- **Packer**: the model isn't here. The agent runs `rpc-server --cache`
  and waits to be used. With more than one, packers are numbered in layer
  order (Packer 1 runs the first layers).
- **MLX**: the target is an MLX model. The agent runs the Caravan MLX
  worker on this node (one Mac). The v3 two-Mac MLX split isn't started by
  the agent yet; see [`../docs/MLX-SPLIT.md`](../docs/MLX-SPLIT.md).

Internally the code still calls the llama.cpp roles `head` and `tail`
(`supervisor.build_head_command()`, `build_tail_command()`); the log
lines say lead and packer.

Either way it supervises the process (restarting it if it exits) and
serves a small health endpoint on port 8091 for the other agents.

**Requires Python 3.10+** (the code uses `X | None` annotations). On
macOS use Homebrew's `/opt/homebrew/bin/python3`; some systems'
`/usr/bin/python3` is 3.9.

## Modules

| file | what |
|---|---|
| `caravan_agent.py` | Entry point: role detection, peer discovery, address selection, supervision. |
| `config.py` | Paths and ports. Settings resolved as flag > env > `~/.caravan/config.json` > default: the target model and the llama-server tuning settings. |
| `ollama_store.py` | Resolves an Ollama model name to its GGUF blob. Also a CLI: `--list`, or `<name>` to print the blob path. |
| `supervisor.py` | Builds the lead (`llama-server`, `build_head_command()`) and packer (`rpc-server --cache`, `build_tail_command()`) commands, and the restart loop. |
| `kv_auto.py`, `gguf_meta.py` | Automatic KV cache type: reads the GGUF header and picks f16 or q8_0. |
| `render_llama_plist.py` | Renders `launchd/com.caravan.llama-server.plist` from the same command builder. |
| `mlx_backend.py` | MLX launch side: settings, the worker command, and for the v3 split `build_lead_command()` / `build_packer_command()` (deprecated: `build_head_command()` / `build_front_command()`). |
| `mlx_worker.py` | The Caravan MLX worker (per-session caches saved to disk; `--split-role lead\|packer` for v3). Runs in the MLX venv, not the agent's Python. |
| `mlx_split.py` | v3: the layer split, the `caravan-split-1` link protocol, and each half's session caches. |
| `mlx_split_fetch.py` | v3 prototype: download only this Mac's part of an MLX model. |
| `render_mlx_plist.py` | Renders `launchd/com.caravan.mlx-server.plist` (one-Mac worker). |
| `health_server.py` | `GET /health` on :8091: node id, system stats, `fast_paths`. |
| `identity.py` | Persistent node id in `~/.caravan/agent/`. |
| `discovery/mdns.py` | `_caravan._tcp` advertise and browse via `dns-sd`. |
| `discovery/tailscale.py` | Peers from `tailscale status --json`. |
| `discovery/thunderbolt.py` | This node's own addresses on up Thunderbolt Bridge interfaces (reported as `fast_paths`). |
| `system_stats.py` | CPU, memory and disk stats for `/health`. |

## How peers are chosen

1. Collect candidates from mDNS and Tailscale (this node itself excluded).
2. Keep only machines whose Caravan agent answers `/health`, so unrelated
   machines on the same LAN or tailnet are never used.
3. Merge sightings of the same machine by normalized hostname. Node-id
   reconciliation over mDNS TXT records isn't implemented.
4. For each peer, try its reported Thunderbolt `fast_paths` first, then
   its Tailscale address, then its LAN address. The first one that answers
   becomes its `--rpc host:50052` target.

## Running it

```sh
python3 caravan_agent.py                          # dry run: prints role, peers, and the command
python3 caravan_agent.py --apply                  # spawn and supervise it (blocks)
python3 caravan_agent.py --model qwen3:30b-a3b    # different target model
python3 caravan_agent.py --n-slots 2 --ubatch-size 1024   # llama-server tuning
python3 caravan_agent.py --serve-for 60           # dry run, but keep /health up so the other node can see this one
python3 ollama_store.py --list                    # models in the local Ollama store
python3 render_llama_plist.py --model qwen3:30b-a3b --rpc auto   # plist for the manual launchd setup
```

The settings (model, `--n-slots`, `--ctx-per-slot`, `--flash-attn`,
`--cache-type-k/-v`, `--cache-ram`, `--n-gpu-layers`, `--batch-size`,
`--ubatch-size`) and their env vars and config keys are listed in
[`../docs/CONFIGURATION.md`](../docs/CONFIGURATION.md). The
config file path can be changed with `--config` or `CARAVAN_CONFIG`.

Dry run is the default so the agent can be run safely next to a live
setup. Don't run `--apply` on the lead while another `llama-server` is
already bound to port 8080.

Under launchd the agent runs from `../launchd/com.caravan.agent.plist`
(see [`../launchd/README.md`](../launchd/README.md)). The slot-pinning
proxy is not part of the agent; it runs as its own service.

## Known gaps

- Lead is "whoever has the model"; two nodes with the same model aren't
  handled.
- Peers are merged by hostname, not node id.
- When Tailscale's App-bundled CLI can't reach its GUI app under launchd,
  discovery relies on mDNS.
- `llama-server` must be spawned by a process that has macOS's Local
  Network permission (the agent's Python does, once allowed), or it can't
  reach the packer. See docs/LOG.md.
- The MLX split (v3) is configured (`mlx.split`) but not launched by the
  agent; start both halves by hand.
