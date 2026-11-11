# Install and auto-start on a Mac

## Current Mac package and reboot behavior

For everyday setup use [INSTALL](../INSTALL.md), not the historical lab commands
below. The bootstrap provides private Python, installs a web-only per-user
LaunchAgent, and opens the page. Worker-only preparation creates no fixed-model
job. The `~/.caravan/bin/caravan` command supplies start/stop/status/doctor/update/
uninstall/add-mini/open. Stop/uninstall affect one owned service, not all model
workers; Unload in the page first to free model memory. Settings/models are kept.

Login restore uses the last successful load, retries temporary node/memory/link
readiness for up to ten minutes, and fails visibly rather than looping forever.
The Day 21 follow-up (`51d697a`) and both-Mini reboot at 17:44 CST passed: main
ready 39.110 s after EXO1 boot, aux health at about 45.8 s. This was on existing
FileVault-off auto-login accounts, **not** a fresh-account/FileVault-on proof.
The published Day 21 tag is immutable and predates the follow-up fix.

No service starts before login. FileVault must be unlocked by its owner; setup
does not change auto-login, security settings or SSH trust. Default new installs
bind only to localhost. Optional proxy and aux title helper are separate setup,
not automatic package contents. See [PACKAGING](PACKAGING.md) for current gates.

Historical Day 19 implementation notes. Native three-stage startup/recovery, isolated-HOME
installation/idempotence and permanent two-Mini Qwen login/reboot recovery passed
on Nov 8 after the recorded fixes **in the earlier fixed-model mode**. The
revised web-owned mode loaded/saved Qwen24/40 and answered correctly, but its
EXO2 reboot test lost SSH for the full360s monitor. That historical gap is now
closed by the Day20/Day21 restore checks summarized above.
Both existing accounts had automatic login
enabled and FileVault off already. A separate clean Mac/account and FileVault-on
behavior remain untested. See [DAY19.md](DAY19.md).
Everything below runs as the logged-in user: no sudo, no LaunchDaemons, no
pre-login boot service, and no automatic changes to macOS privacy settings.

Use the **venv path** (`~/.caravan/venvs/mlx/bin/python`) when generating plans;
do not resolve its symlink to the base Homebrew interpreter. Older plans made
before the Day 19 fix must be regenerated explicitly. Restarting only a worker
child does not refresh its already-running agent code; restart the corresponding
owned service when deploying agent changes, at a safe time. The web can be
restarted separately with KEEP_WORKERS without reloading models.

## Default: restore the last model, owned by the web

**Preferred normal mode (Brenden's Nov 8 design): install the web LaunchAgent,
not a model-specific worker job.** Every successful load saves the actual model,
MLX/GGUF engine, placement/ordered Minis, Balance counts or GGUF shares and
settings in `~/.caravan/web-ui/last-model.json`. It is atomically replaced before
ready is advertised. User Stop saves an explicit empty selection; next login
then loads nothing. A failed load keeps the prior successful choice.

On login, the web uses the normal load path for that selection, with current
topology and fresh files/free-memory checks. Temporary Mini/memory/Thunderbolt
readiness failures retry within a bounded ten-minute window. Permanent invalid
state or exhausted retries leave a readable warning in the idle UI; there is no
infinite crash loop or automatic model download. Fix missing files explicitly,
then press Load.
Normal model switching and Balance reload stay unlocked and update the selection.
A user operation cancels a pending auto-restore. A healthy KEEP_WORKERS restart
adopts owned workers and keeps the selection rather than loading it twice.

Use stable already-trusted SSH control hosts in `[web.nodes.*]`. For changing
Thunderbolt data IPs, configure an explicit packer e.g.:

```toml
[web.nodes.worker2]
role = "packer"
host = "USER@STABLE_CONTROL_HOST"
ssh = "USER@STABLE_CONTROL_HOST"
repo = "~/cv3" # choose that Mini's actual clone
peer = "ssh+tb://USER@STABLE_CONTROL_HOST/en2:5560"
listen = "tb://en2:5560"
```

Verify the actual hardware interface first. No SSH trust, interface, route,
auto-login or FileVault setting is created/changed. Every stage's data endpoint
is resolved on its own Mini; private TB traffic does not fall back to Wi-Fi.
Remote MLX stages are web-owned via existing SSH/ownership commands; no permanent
fixed-model worker LaunchAgent is needed, for any number of Minis.

For old fixed-model installations, explicitly uninstall just the model worker
jobs (keep web). The lab migration removes only `day19-qwen-lead` on EXO1 and
`day19-qwen-packer` on EXO2. This stops those owned model workers; run it at a
safe time. It keeps models, cache and logs. Then load once through the web so the
successful placement becomes the saved selection. Do not hand-create a saved
record from a partial running process or fabricate a successful load.

Advanced opt-out: set `CARAVAN_WEB_RESTORE_LAST=0` in the web's environment.
Successful choices are still saved, but startup stays empty/adopts existing
workers without replay. Fixed model service plans described later are retained
for explicit advanced compatibility, **not the default auto-start design**.

## Prepare the next login without taking over today's workers

For a deliberately deferred migration, append **`--no-start --stage-login`**
to each explicit `tools/caravan_service.py install` command. It writes a real
per-user LaunchAgent, but does not bootstrap/restart a job. Configs are kept in
`~/.caravan/services/login/NAME.json`; status/uninstall/restart find them by name.
The current web keeps control until launchd actually loads the fixed-model job
on the next login. Unknown launchctl errors fail closed. Do not hand-edit plans.
Normal `--no-start` without `--stage-login` still reserves model ownership
immediately. This staging option is intended for an agreed fixed-model reboot
migration, not automatic resumption of whichever model was selected last.

No logout/reboot is performed by installing a staged job. Check model paths,
counts, peer/listen addresses and logs first; after reboot, each Mac must log in.
Until then the log may not exist because the job has never run. If you change
your mind, `uninstall --name NAME` removes only that owned definition and keeps
models/cache/logs. A manual `restart` still refuses an occupied endpoint rather
than killing an existing worker.

## One-command setup

Requires **macOS 14+, Apple Silicon, native Python 3.10+ and Git**. The installer
checks these and explains missing prerequisites; it does not install Homebrew,
Python, Xcode, llama.cpp or models, and never asks for a password/token.

On a **new lead Mini**:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/scripts/install.sh | bash -s -- --role lead)
```

This is a moving development branch. Review the script before running it; a
published release tag should be used for a reproducible release installation.
The script defaults to `~/.caravan/src/caravan`, creates/reuses
`~/.caravan/venvs/mlx`, installs `requirements-mac.txt` (`mlx-lm==0.32.2` plus
Hugging Face Hub; transitive dependencies are not fully locked), checks imports,
creates a **single-local-node** web config only if none exists, and installs the
web LaunchAgent. Open `http://127.0.0.1:8190/` and choose/download a fitting model
in Models. No model is loaded merely by installing the web service.

On each **new worker Mini**, use the same command with `--role worker`. Without
`--model`, it only prepares the source/environment and explains the next step;
there is no imaginary default model or automatic multi-gigabyte download.

From an existing checkout:

```sh
# Preview only: portable, no writes/network/package installs/launchctl changes.
bash scripts/install.sh --dry-run --repo "$HOME/.caravan/src/caravan"

# Actual install. Point at the intended clone; do not create another lab copy.
bash scripts/install.sh --repo "$PWD" --role lead
# Worker-only environment:
bash scripts/install.sh --repo "$PWD" --role worker
```

Options:

- `--python /absolute/path/python3`: choose native Python 3.10+.
- `--repo /absolute/path`, `--ref BRANCH_OR_TAG`: choose source location/version.
- Repeats reuse matching clean checkouts and venvs. Existing settings are never
  replaced. Dirty trees, different origins/branches and unrelated existing
  folders are refused; no reset, force, branch switching or scp.
- `--update`: explicit clean `git pull --ff-only` on the selected branch; no
  tag rewriting. Plan service restarts separately after a code update.
- `--use-existing`: use an extracted source archive (no Git operations).
- `--no-start`: write the owned LaunchAgent but do not load it now. It will still
  start at the **next user login**. Use `uninstall` to remove auto-start entirely.
- Worker stage options can be passed through the installer: `--model`, `--name`,
  `--counts`, `--stage-index`, `--listen`, `--upstream`, `--peer`, `--port`.
  For a lead, install web first and configure a model job separately below.

The installer does not alter existing SSH keys/Remote Login, approve Local
Network access, configure Thunderbolt routes, disable sleep or enable auto-login.
Resolve those explicitly on the Macs. A sleeping/logged-out Mini is not promised
available. No new-Mac install success is claimed until the live checklist passes.

## Reboot-safe Thunderbolt endpoints

macOS can choose a different link-local IPv4 address after a reboot. Do not
assume that yesterday's `169.254.x.x` address will still belong to the Mini.
For an explicit, verified Thunderbolt hardware interface, use:

- Packer `--listen tb://en2:5560` (this Mini's active Thunderbolt interface).
- Lead `--peer ssh+tb://USER@TRUSTED_CONTROL_HOST/en2:5560` (the upstream
  Mini's interface). A middle packer can use the same syntax for `--upstream`.

First inspect `networksetup -listallhardwareports` on each Mini; `en2` is an
example, not a universal interface name. The control host must already be
reachable by non-interactive SSH with an approved host key. SSH only reads the
peer's hardware/interface addresses; model traffic still uses its verified
private/link-local Thunderbolt address, with no Wi-Fi/data fallback. No keys,
login settings, addresses or routes are created or changed. Static `IP:PORT`
plans remain supported. Preview/dry-run does not contact the peer.

Agents resolve these explicit interfaces before starting a child, and check for
address changes every ten seconds. A changed address restarts only that agent's
own worker; a failed control lookup does not kill a healthy worker. Missing
interfaces/peers retry safely. Interface/routing setup for three physical Minis
or a Thunderbolt triangle is still manual; this is not automatic network or
model discovery. Regenerate existing fixed-IP plans explicitly when migrating.

## Advanced fixed-model compatibility — not the default

1. **Web-managed (normal):** auto-start only web. It restores the last successful
   selection at login through the normal UI load path, or nothing if explicitly
   unloaded. Web-only restarts adopt owned healthy workers and preserve them.
2. **Fixed model auto-start:** install one local worker plan per participating
   node (plus a web job on the lead). launchd starts `caravan_agent.py
   --service-config ... --apply`; the agent starts/supervises that Mini's local
   single/split worker, retries missing peers, and stops **only its own child**
   on shutdown. The web UI adopts the managed lead even if it starts later.
   **Model Load, Stop, Balance reload and Optimize are blocked while that lead
   plan is installed**, rather than fighting launchd's restart policy. Preview
   and chat remain available. Uninstall the lead and packer worker jobs before
   returning the cluster to web-controlled model switching. Files/caches stay.

The second mode is the initial implementation of the roadmap's “start the split
from agent/launchd.” It is an explicit saved stage plan, not automatic role
selection, service discovery or “resume the last UI model” persistence. The
agent's older GGUF discovery/apply path is unchanged and is not enabled by this
installer. Existing RPC/llama.cpp services are not installed, stopped or edited.

## Service commands

Use this Mini's **own clone**, venv and local model folder. Examples below use
`python3` for readability; prefer `~/.caravan/venvs/mlx/bin/python`.

```sh
python3 tools/caravan_service.py install --kind web --repo "$PWD" --dry-run
python3 tools/caravan_service.py install --kind web --repo "$PWD"
python3 tools/caravan_service.py status
python3 tools/caravan_service.py status --name web
python3 tools/caravan_service.py restart --name web
python3 tools/caravan_service.py uninstall --name web
```

Default web bind is loopback. Pass `--host PRIVATE_IP` (or `0.0.0.0` only on a
trusted private network) to expose it elsewhere. The UI has no login; never
publish it on the internet. `--port` defaults to 8190; `--lead-port` to 8194.

Every job has an owner-validated plan at `~/.caravan/services/NAME.json`, an
absolute-path plist at `~/Library/LaunchAgents/com.caravan.v3.NAME.plist`, logs at
`~/.caravan/logs/NAME.log`, and worker runtime records under
`~/.caravan/services/runtime/`. These are the generated services' only sources
of truth; no second editable template or copy inside the checkout. Names must
be unique on a Mini; use a different name for an extra simulated worker.

`RunAtLoad`/`KeepAlive`, a 15 s launchd throttle and 30 s exit allowance are set.
Web jobs set `CARAVAN_WEB_KEEP_WORKERS=1` **and** `AbandonProcessGroup=true` so
launchd itself does not kill surviving web-owned workers. Worker agent jobs do
**not** abandon their child group; they forward graceful termination and allow
up to 15 s for local cache flush before escalation. `restart` uses owned
`bootout` then `bootstrap`, not an ungraceful process-name kill sweep.

Repeated identical installs do not restart a loaded job. Changing arguments
requires `uninstall --name NAME` followed by a new install; different plans or
unowned/edited plists are not overwritten. Busy ports and malformed ownership
records fail closed. `status` is read-only and prints launchd's own output;
“loaded” is not an inference readiness guarantee. Check `/health` and logs too.
Uninstall keeps models, caches, logs, dependencies, source and unrelated jobs.
Uninstalling web also leaves its existing model workers running, deliberately.

## Single-Mini model auto-start

Choose a model already present locally; no service command downloads weights.
Use Balance/fit checks first; install checks file completeness, not a guarantee
that a long context will fit in memory.

```sh
python3 tools/caravan_service.py install --kind worker --name lead \
  --repo "$PWD" --model /absolute/local/model --port 8194 --dry-run
# Remove --dry-run only after checking the plan and clearing any current worker.
```

The web job can start before the worker: status polling adopts its exact
repository/port/PID once healthy. Service-owned runtime records are distinct
from the web-owned `lead.pid` marker, so an alternate-port test does not overwrite
the production lead's ownership. Stop/restart/uninstall the model with
`--name lead`, not the web UI's Stop button.

## Advanced fixed N-Mini split plans (legacy opt-in)

All nodes must use **the same positive layer-count list**, in forward order
(packers first, lead last). Every stage owns at least one layer, counts sum to
the model's layer count, and each Mini already has its required shards/tokenizer.
Use Day 19 Balance/`mlx_split_fetch.py --split-counts ... --stage-index ...` to
plan/fetch missing local files first. No weights are sent by the lead.

Example: a 32-layer model, `10,10,12`, three physical Minis:

```sh
# First packer, on its own Mini / own clone:
python3 tools/caravan_service.py install --kind worker --name packer1 \
  --repo "$PWD" --model /its/local/model --counts 10,10,12 --stage-index 0 \
  --listen PACKER1_PRIVATE_IP:5591 --dry-run

# Middle packer, on its own Mini / own clone:
python3 tools/caravan_service.py install --kind worker --name packer2 \
  --repo "$PWD" --model /its/local/model --counts 10,10,12 --stage-index 1 \
  --listen PACKER2_PRIVATE_IP:5592 --upstream PACKER1_REACHABLE_IP:5591 --dry-run

# Lead, on its own Mini / own clone:
python3 tools/caravan_service.py install --kind worker --name lead \
  --repo "$PWD" --model /its/local/model --counts 10,10,12 --stage-index 2 \
  --peer PACKER2_REACHABLE_IP:5592 --port 8194 --dry-run
```

Remove `--dry-run` to install/start only after validating each local plan. Any
number of packers is supported; no “EXO2” host or common clone path is embedded
in these jobs. Add more count entries, stage indices and upstream links.
Middle/lead agents check upstream protocol/ranges before spawning; missing peers
are retried every 15 s without downloading, killing another worker or giving up
after one boot-order race. Keep direct TCP on trusted private links only.
N-stage concurrency is pinned to one chat, learning/guess-ahead off as in theme 1.
Automatic triangle networking and dynamic Balance-to-launchd reconfiguration
remain follow-ups. See [DAY19.md](DAY19.md) for the two-Mini/three-worker live test.

## launchd sources checked

- Apple launchd plist manual: `AbandonProcessGroup`, `ExitTimeOut`, `KeepAlive`:
  https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5
- Current launchctl manual (`bootstrap`, `bootout`, GUI domains):
  https://man.freebsd.org/cgi/man.cgi?manpath=macOS+26.3&query=launchctl&sektion=1
- MLX 0.32.4 install requirements (macOS 14+, native Python 3.10+):
  https://ml-explore.github.io/mlx/build/html/install.html

Documentation checked 2026-11-08. Native launchctl/Metal and existing-account
login/reboot passed on the two lab Minis; see measured results in DAY19.md.
Mocks alone are not proof of behavior on another Mac/account/security setup.

Native restart note: macOS may acknowledge `bootout` before the old job is fully
unloaded. The CLI retries only transient bootstrap error 5 for up to 35 seconds,
checking job absence and a free port. Other errors fail normally; it never
escalates to root or kills a port occupant. Inspect status/logs on failure.

Use a stable already-trusted SSH control hostname/address for `[web.nodes.*]`
inventory too; legacy lab defaults containing a self-assigned TB IP can go stale.
Explicit UI topology can now use reboot-safe `ssh+tb://` peers and `tb://`
listen interfaces too; both normal split loads and last-model restore resolve
them before starting stages. Arbitrary network/interface discovery is not
implemented; the operator still chooses the trusted hosts/interfaces/routes.

## Independent remote-access recovery

See [REMOTE-ACCESS.md](REMOTE-ACCESS.md) for verified LAN SSH aliases, the
Tailscale-independent EXO2 Thunderbolt jump, per-user Tailscale guards,
manual recovery limits and the current model-restoration status. These are
access safeguards, not Caravan model/service restarts.

## Optional OpenAI-compatible client proxy

The lead may also run the separately owned `com.caravan.v3.proxy` LaunchAgent.
It does not pin a model, load weights or interfere with web-owned switching.
It starts at user login, uses KeepAlive, and listens only on loopback 8090;
MLX requests go to the normal lead worker on 8194. Remote clients use SSH
forwarding, not a public bind. Install/status/restart use the same ownership,
port-collision and no-sudo protections as web/worker plans:

```sh
~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install \
  --kind proxy --name proxy --port 8090 --lead-port 8194
~/.caravan/venvs/mlx/bin/python tools/caravan_service.py status --name proxy
```

A pre-existing manual proxy must finish its requests and be stopped explicitly
before install; the installer never kills an unowned listener. Logs are in
`~/.caravan/logs/proxy.log`. Cache cleanup is off (no automatic deletions).
The lead installer still installs the web service by itself; add this plan
when an OpenAI client needs it. EXO1's plan was installed live without reboot
or web restart. Its subsequent Day21 login/reboot recovery passed on the
existing lab accounts; see the historical measurements in [DAY21.md](DAY21.md).
