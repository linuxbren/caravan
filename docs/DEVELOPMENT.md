# Developer setup

For everyday use, use the [Mac installer](../INSTALL.md). This page is for
people changing Caravan's source. See [node names](README.md#names-used-in-these-guides)
if you are reading older build logs.

## Get a separate working copy

Use a folder you own. Do not point development work at an active installation.

```sh
git clone --branch caravan-v3-mlx-split https://github.com/linuxbren/caravan.git "$HOME/projects/caravan"
cd "$HOME/projects/caravan"
```

On an Apple Silicon Mac with a native Python, preview before installing:

```sh
bash scripts/install.sh --repo "$PWD" --use-existing --python /absolute/path/to/python3 --dry-run
```

Remove `--dry-run` when ready. Source installation supports native Python
3.10+; the easy package supplies its own tested Python and exact-version wheels.
Use `--no-start` if the Mac has no logged-in desktop session. A running custom
service is never silently adopted or replaced. See [SERVICES](SERVICES.md).

## Test without models

```sh
PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests
```

Portable tests can run on a development node that is not a Mac. MLX imports,
GPU inference, launchd, reboot recovery and FileVault require separate Mac
checks. For an isolated Mac smoke, use a fresh HOME, unused ports and a unique
`--name`; never reuse a production service label. No live model is needed.

## Work across Macs safely

`lead-mac` and `helper-mac` are example SSH aliases you configure yourself.
Use the actual source path on each Mac, not somebody else's build-log path.
Commit and push reviewed changes, then use `git pull --ff-only` in each intended
checkout. Check for local changes first; never reset or copy over them. Do not
clone another copy to work around an access problem.

Restart only what changed, at a safe time. A web restart must preserve model
workers (`CARAVAN_WEB_KEEP_WORKERS=1`, set by generated service plans). Do not
reboot, change SSH trust, delete model files or alter another person's services
as a documentation step. Follow [daily release checks](RELEASES.md).

## Legacy compatibility boundaries

The source still contains original-test-environment fallbacks in
`web_nodes.DEFAULT_NODES`, `web_catalog.DEFAULT_PACKER_SSH` /
`DEFAULT_PACKER_PEER`, and older picker/worker alias matching. Their inventory
IDs, display labels, default SSH address and remote checkout path have **not**
been renamed in this documentation pass, because existing installations may
rely on them. Use an explicit `[web.nodes.*]` inventory with your own trusted
names, endpoints and repository paths. The easy installer creates a local-only
entry and does not install the old remote defaults. Changing those fallbacks
safely is a separate migration, not a find-and-replace of documentation.

Several older remote gather, download, discovery, adoption and cleanup paths
also retain a legacy helper source-path fallback. In particular, the worker
manager has older direct launch/cleanup commands as well as inventory-aware
paths. Those behavioral assumptions are intentionally unchanged here and still
need a separate portability/migration audit before calling arbitrary multi-Mac
networks turnkey. Explicit inventory is the supported documented starting point;
it does not erase every legacy fallback in the source.


## Manual extra-Mac setup

For normal installs use **Add Macs** and its one-use code; see [INSTALL](../INSTALL.md#add-minis).
The following is the manual recovery/source route, not a required user step.

Enable Remote Login on the helper for the intended account. From the lead, run
`ssh YOUR_USER@PEER_PRIVATE_ADDRESS`, verify its fingerprint through a separate
trusted channel, and establish key-based login without disabling host checks.
Keep the lead's existing local node and settings; append a unique node table:

```toml
[web.nodes.helper]
label = "Helper Mac"
role = "packer"
host = "YOUR_USER@PEER_PRIVATE_ADDRESS"
ssh = "YOUR_USER@PEER_PRIVATE_ADDRESS"
repo = "~/.caravan/src/caravan"
peer = "PEER_PRIVATE_ADDRESS:5560"
order = 1
```

Each helper needs a unique name and order. Use its actual installed source path.
Back up the config before editing. Restart only the browser service with workers
kept, then inspect Topology. Never copy a private key into chat or an issue.
New installs get a local browser service even with `--role worker`; supplying a
fixed `--model` remains the developer-only direct worker setup.


## Open from other devices (Tailscale)

The installed web service stays bound to `127.0.0.1`. It is never changed to
`0.0.0.0`. Opt-in access uses Tailscale's own `serve` forward:

```sh
tailscale serve --bg --tcp <web-port> tcp://127.0.0.1:<web-port>
```

`caravan remote on` runs that command and records `[remote] enabled = true`
in `~/.caravan/config.toml`. It never passes `--funnel`. `caravan remote off`
runs `tailscale serve --tcp=<web-port> off` only, and only when the forward
target is this Mac's loopback web port. Other Tailscale serve entries are
left alone. `caravan uninstall` does the same cleanup before it deletes
files.

`caravan remote status`, the Settings switch, and `GET /api/remote` read
the live serve table. A hand-made serve on the same port and loopback
target is treated as on and written into the config (adopted). Doctor
reports the same state without writing.

The installer asks the one optional question only on a fresh install, only
when Tailscale is installed and signed in, and only when a terminal can be
read (`/dev/tty`, including under `curl | bash`). Otherwise it skips
silently. Updates never ask. The CLI binary lookup checks the Tailscale
app bundle, Homebrew (`/opt/homebrew/bin` and `/usr/local/bin`), then
`PATH`. Settings talks to `GET`/`POST /api/remote`. The web process does
not re-bind the page.

## Clean-install runtime and recovery

Every install, including a new paired Mac and `caravan update`, prepares the
SHA256-pinned official macOS arm64 llama.cpp release in
`~/.caravan/runtime/llama/<version>`. The source manifest is
`runtime/llama-release.json`. Keep the shipped dylibs beside the executables.
The standard engine supports full GGUF sets and RPC. The custom Day 22
own-share engine remains isolated at its original source revision; the official
release does not implement Caravan's custom shard format. Clean installs
use standard full-GGUF RPC when that optional custom engine is unavailable.

For an old verified startup plan, rerun the same installer with
`--replace-old-services`. It preserves copies in `~/.caravan/service-backups/`
before unloading the matching job and replacing the files. Unrelated labels,
commands and linked files are refused. Models and application settings are not
removed. Do not run this during inference. `caravan doctor` retains detailed
service information; `caravan status` is deliberately one line.

The installer manages a marked PATH block in `.zprofile` (and `.bash_profile`
for bash login shells). Open a new Terminal after setup. `caravan uninstall` removes all verified local Caravan jobs, owned local workers,
its marked PATH/SSH entries, and the entire `~/.caravan` tree, including models,
settings, keys, source and runtimes. It first turns off Caravan's Tailscale
serve entry if one is present. It previews the total bytes and asks once;
`--yes` skips the prompt. Remove paired Macs first. Unverified startup files and
the unrelated remote-access watchdog stay untouched. Only exact known repository
workers and recorded engine/tunnel PIDs are stopped; no commands are sent to
another Mac.


For a developer/source installation, keep using the **same repo, role, Python,
ports and service names**:

```sh
cd /your/existing/caravan
# Check/commit your own edits first. Never reset them.
git pull --ff-only origin caravan-v3-mlx-split
bash scripts/install.sh --use-existing --repo "$PWD" --python /absolute/path/to/python3
```

Python must be native Apple Silicon 3.10+. `scripts/install.sh --dry-run`
previews commands without writing; `--check` runs read-only doctor checks.
The source installer still needs Git to clone an absent repo; use the easy
bootstrap if you have no Git/Python. Never point a new installer at a live lab
checkout with different service plans. It refuses differing owned plans rather
than replacing them. No automatic migration of custom services is claimed.
