# launchd services

Supervises the three plain background processes this project depends on, so
they survive a crash or reboot instead of needing to be started by hand.
See [docs/PLAN.md](../docs/PLAN.md) (stage 2) and
[GitHub issue #1](https://github.com/RookiOS72/caravan/issues/1).

| plist | machine | what |
|---|---|---|
| `com.caravan.llama-server.plist` | node-a | the sharded `llama-server` |
| `com.caravan.slot-pin-proxy.plist` | node-a | `proxy/slot_pin_proxy.py` |
| `com.caravan.rpc-server.plist` | node-b | `ggml-rpc-server` |

All are user-level LaunchAgents (not LaunchDaemons) -- they run in the
logged-in user's session, matching how openclaw's own gateway is set up.
Paths inside the plists are absolute and specific to this machine pair
(both currently have user `brenden` at `/Users/brenden`); there's no
templating since this project isn't at the "package it for other people"
stage yet (see PLAN.md stage 3).

Logs go to `~/Library/Logs/caravan/*.log` on each machine.

**All plists are bootstrapped directly from this repo's checkout path** —
there is no copy step into `~/Library/LaunchAgents/`. That was the original
approach (see the old version of this doc) but it left two sources of
truth that could silently drift; the repo path is now the only one that
matters on both nodes. Clone/place the repo at the same path
(`~/dev/caravan`) on each machine, or adjust the paths below accordingly.

## Install (node-a: llama-server + slot-pin-proxy)

```sh
mkdir -p ~/Library/Logs/caravan
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.llama-server.plist
launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.slot-pin-proxy.plist
```

## Install (node-b: rpc-server)

```sh
ssh brenden@<node-b-ip> 'mkdir -p ~/Library/Logs/caravan'
# repo must already be checked out at ~/dev/caravan on node-b
ssh brenden@<node-b-ip> 'launchctl bootstrap gui/$(id -u) ~/dev/caravan/launchd/com.caravan.rpc-server.plist'
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

See the main [README's Usage section](../README.md#usage) for
machine/service specifics and restart caveats (e.g. never restart
`rpc-server` while `llama-server` is mid-load).

## Switching the model

`com.caravan.llama-server.plist` passes a literal Ollama blob path to
`-m` (currently `muse-glimmer`'s). Nothing in the plist is templated, so
to serve another model from the local Ollama store, resolve its blob path
and put that in the plist, then re-bootstrap (see "Restart after editing
a plist" above):

```sh
cd ~/dev/caravan
python3 agent/ollama_store.py --list              # what's pulled locally
python3 agent/ollama_store.py qwen3:30b-a3b       # -> /Users/brenden/.ollama/models/blobs/sha256-...
# with no argument it resolves the configured model
# (--model > $CARAVAN_MODEL > "model" in ~/.caravan/config.json > muse-glimmer)
```

`caravan_agent.py` (the eventual replacement for these plists) needs no
plist edit -- it takes `--model` / `CARAVAN_MODEL` / the config file
directly and resolves the blob itself.

## Slot cleanup settings for the proxy

`slot_pin_proxy.py` now cleans up stale disk KV slot files on startup and
every 6 hours (see the main README, "Configuration"). To change that
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
