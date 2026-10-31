# launchd services

Keeps Caravan's background processes running across crashes and reboots.
See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) and
[GitHub issue #1](https://github.com/linuxbren/caravan/issues/1).

There are two ways to run the model processes. Use one or the other on a
node, never both:

- **Agent (recommended):** `com.caravan.agent.plist` on every node. The
  agent works out its role and spawns `llama-server` or `rpc-server
  --cache` itself. Spawning `llama-server` from the agent's Python also
  avoids macOS's Local Network permission problem; see "Local Network
  permission" below.
- **Manual per role:** `com.caravan.llama-server.plist` on the lead and
  `com.caravan.rpc-server.plist` on the packer.

The proxy plist is needed on the lead in both cases.

| plist | machine | what |
|---|---|---|
| `com.caravan.agent.plist` | every node | `agent/caravan_agent.py --apply` (Homebrew Python 3.10+) |
| `com.caravan.llama-server.plist` | node-a, the lead (manual mode) | the sharded `llama-server` |
| `com.caravan.rpc-server.plist` | node-b, the packer (manual mode) | `ggml-rpc-server --cache` (keeps the packer's part on its own disk) |
| `com.caravan.slot-pin-proxy.plist` | node-a, the lead | `proxy/slot_pin_proxy.py` |

All are user-level LaunchAgents (not LaunchDaemons) -- they run in the
logged-in user's session, matching how openclaw's own gateway is set up.
Paths inside the plists are absolute and specific to the original machine
pair (the same user name and home directory on both). launchd doesn't
expand `~`, so **edit the `/Users/...` paths to match your home
directory** before bootstrapping. Nothing is templated yet (packaging is on
[docs/ROADMAP.md](../docs/ROADMAP.md)). Two plists can be generated:
`com.caravan.llama-server.plist` with `agent/render_llama_plist.py`
(below), and `com.caravan.mlx-server.plist` (the MLX worker) with
`agent/render_mlx_plist.py`. There's no plist for the v3 two-Mac MLX
split yet; its two workers are started by hand (see
[docs/MLX-SPLIT.md](../docs/MLX-SPLIT.md)).

Logs go to `~/Library/Logs/caravan/*.log` on each machine.

**All plists are bootstrapped directly from this repo's checkout path** —
there is no copy step into `~/Library/LaunchAgents/`. That was the original
approach (see the old version of this doc) but it left two sources of
truth that could silently drift; the repo path is now the only one that
matters on both nodes. Clone/place the repo at the same path
(`~/dev/caravan`) on each machine, or adjust the paths below accordingly.

## Install with the agent (every node)

```sh
mkdir -p ~/Library/Logs/caravan
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.agent.plist
# lead only:
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.slot-pin-proxy.plist
```

## Install by hand (node-a, the lead: llama-server + slot-pin-proxy)

```sh
mkdir -p ~/Library/Logs/caravan
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.llama-server.plist
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.slot-pin-proxy.plist
```

## Install by hand (node-b, the packer: rpc-server)

```sh
ssh <user>@<node-b-ip> 'mkdir -p ~/Library/Logs/caravan'
# repo must already be checked out at ~/dev/caravan on node-b
ssh <user>@<node-b-ip> 'launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.rpc-server.plist'
```

## Check status / logs

```sh
launchctl list | grep caravan
tail -f ~/Library/Logs/caravan/llama-server.log
```

## Restart after editing a plist

Editing `ProgramArguments` (flags, paths) requires a full re-read — `kickstart`
alone won't pick it up:

```sh
launchctl bootout gui/$(id -u)/com.caravan.<name>
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.<name>.plist
```

If only the underlying script changed (e.g. `slot_pin_proxy.py`, not its
plist), a plain kickstart is enough:

```sh
launchctl kickstart -k gui/$(id -u)/com.caravan.<name>
```

See the main [README's Operations section](../README.md#operations) for
restart caveats (for example, never restart `rpc-server` while
`llama-server` is loading the model; restart the lead after the packer).

## Local Network permission (macOS)

macOS blocks LAN connections from processes that don't have the "Local
Network" privacy permission. A `llama-server` started directly by launchd
can't be granted it, so it fails to reach a packer on a LAN or Thunderbolt
address (Tailscale addresses aren't affected). The agent's Python can be
granted the permission, and the `llama-server` it spawns inherits it. This
is one reason the agent is the recommended setup. Background: docs/LOG.md,
"The actual root cause".

## Switching the model

`com.caravan.llama-server.plist` passes a literal Ollama blob path to
`-m` (currently `muse-glimmer`'s). Nothing in the plist is templated, so
to serve another model from the local Ollama store, resolve its blob path
and put that in the plist, then re-bootstrap (see "Restart after editing
a plist" above):

```sh
cd ~/dev/caravan
python3 agent/ollama_store.py --list              # what's pulled locally
python3 agent/ollama_store.py qwen3:30b-a3b       # -> ~/.ollama/models/blobs/sha256-...
# with no argument it resolves the configured model
# (--model > $CARAVAN_MODEL > "model" in ~/.caravan/config.json > muse-glimmer)
```

`caravan_agent.py` needs no
plist edit -- it takes `--model` / `CARAVAN_MODEL` / the config file
directly and resolves the blob itself.

## Regenerating the llama-server plist (flags, RPC address, model)

As of 2026-10-30 the plist passes `-ngl 999 -fa on -ctk q8_0 -ctv q8_0
--cache-ram 0 -b 2048 -ub 512` explicitly (see
[llama-server settings](../docs/CONFIGURATION.md#llama-server-settings-lead)
for what each one does), and its `--rpc` points at node-b's Thunderbolt Bridge link-local
address (`169.254.x.x:50052`) instead of a Tailscale address.

**Link-local caveat:** `169.254.x.x` addresses are self-assigned by each
Mac and can change (re-cabling, interface reset, macOS update). If
llama-server starts failing to reach RPC0, check node-b's
`ipconfig getifaddr en2` (or whichever bridge interface it is). Better:
derive it instead of hand-editing --

```sh
cd ~/dev/caravan
python3 agent/render_llama_plist.py --model-path <blob> --rpc auto     # print, review
python3 agent/render_llama_plist.py --model-path <blob> --rpc auto \
    --output launchd/com.caravan.llama-server.plist
git diff launchd/com.caravan.llama-server.plist
```

`--rpc auto` runs caravan-agent's peer discovery (Tailscale + mDNS,
upgraded to the Thunderbolt path when it answers) -- it needs
caravan-agent's health endpoint running on node-b. Otherwise pass
`--rpc host:port`, or set `CARAVAN_RPC_ADDR` / `"llama_server": {"rpc":
...}`. Every tuning flag (`--n-slots`, `--ubatch-size`, ...) is accepted
too, and the plist is rendered by the same `supervisor.build_head_command()`
(the lead's command; internal name) the agent uses, so they can't drift. The tool never touches launchd or
`~/Library/LaunchAgents`; after writing the file, re-bootstrap as in
"Restart after editing a plist" above. Note that changing `-ctk/-ctv`
makes existing disk slot files unrestorable (they're reprocessed cold
once and re-saved).

If you change the slot count, change it for both: `--n-slots` here and
`CARAVAN_N_SLOTS` in `com.caravan.slot-pin-proxy.plist`'s
`EnvironmentVariables` -- or set `"llama_server": {"n_slots": N}` in
`~/.caravan/config.json`, which both read.

## Slot cleanup settings for the proxy

`slot_pin_proxy.py` cleans up stale disk KV slot files on startup and
every 6 hours (see [docs/CONFIGURATION.md](../docs/CONFIGURATION.md#saved-chat-cleanup-and-the-per-mac-cap)).
The default mode is `delete`; run `python3 -m proxy.slot_cleanup --dry-run -v`
first on a Mac with saved chats you care about.

`com.caravan.slot-pin-proxy.plist` also sets `CARAVAN_PINNED_SLOT`. That's
a leftover from the single-pinned-slot design; current code ignores it. To change that
under launchd, add to `com.caravan.slot-pin-proxy.plist`'s
`EnvironmentVariables` e.g.:

```xml
<key>CARAVAN_SLOT_CLEANUP</key>        <string>archive</string>  <!-- or delete / off -->
<key>CARAVAN_SLOT_MAX_AGE_DAYS</key>   <string>30</string>
```

or put the same settings in `~/.caravan/config.json` (no plist edit or
re-bootstrap needed, just a proxy kickstart).

## Uninstall

```sh
launchctl bootout gui/$(id -u)/com.caravan.<name>
```

(No file to remove — nothing was copied to `~/Library/LaunchAgents/`.)
