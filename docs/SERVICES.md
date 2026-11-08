# Install and auto-start on a Mac

Day 19 development feature. Native dry-runs and temporary real launchd
three-stage startup/recovery passed on two M4 Minis on Nov 8; **clean-Mac
installation and permanent login/reboot testing remain pending**. No permanent
jobs or reboot were used for those checks. See [DAY19.md](DAY19.md).
Everything below runs as the logged-in user: no sudo, no LaunchDaemons, no
pre-login boot service, and no automatic changes to macOS privacy settings.

Use the **venv path** (`~/.caravan/venvs/mlx/bin/python`) when generating plans;
do not resolve its symlink to the base Homebrew interpreter. Older plans made
before the Day 19 fix must be regenerated explicitly. Restarting only a worker
child does not refresh its already-running agent code; restart the corresponding
owned service when deploying agent changes, at a safe time. The web can be
restarted separately with KEEP_WORKERS without reloading models.

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

## Two ownership modes — do not mix model controllers

1. **Web-managed (normal interactive use):** auto-start the web service only.
   Models/Balance starts its workers as before. A web-only restart adopts them
   and preserves them. A full machine reboot does **not** automatically reload
   a model in this mode; choose it again in the UI.
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

## N-Mini split auto-start

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

Documentation checked 2026-11-08. Actual launchctl/Metal/login/reboot behavior
still needs verification on the Minis; mocks are not proof of macOS behavior.
