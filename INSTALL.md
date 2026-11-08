# Install Caravan

Caravan is experimental source software, not a signed Mac app. Release packages
contain code and these instructions, not models or a bundled Python runtime.

## One-command install + auto-start (Day 19 development)

On a **new Apple Silicon Mac** with macOS 14+, native Python 3.10+ and Git:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/scripts/install.sh | bash -s -- --role lead)
```

Review the script first; this follows a moving development branch and is not yet
in the Day 18 release package. It sets up a dedicated source copy, the MLX venv,
tested dependencies and a user-login web service. It never downloads models or
replaces existing settings. Default UI bind is localhost. On another Mini use
`--role worker`; without a model plan it prepares the environment but starts no
worker. Repeats do not restart unchanged jobs or reset dirty checkouts.

From an existing source copy, preview with
`bash scripts/install.sh --dry-run --repo "$PWD"`, then remove `--dry-run` when
ready. Explicit per-node single/N-stage model auto-start, install/uninstall/status
commands and ownership rules: **[SERVICES.md](docs/SERVICES.md)**. Fixed auto-start
model jobs and UI-controlled model switching are separate modes; do not mix
controllers. LaunchAgents start at **user login**, not before login. Native
dry-runs and temporary three-stage launchd startup/recovery were tested on
two M4 Minis on Nov 8. A clean-Mac actual install, permanent service migration
and login/reboot remain pending; no permanent jobs were installed in the test.
Use the **venv Python path itself**, e.g. `~/.caravan/venvs/mlx/bin/python`, not
its resolved Homebrew binary. Regenerate plans made before the Day 19 venv-path
fix; do not hand-edit their JSON. See [live results](docs/DAY19.md).

The current branch also adds per-Mini selective downloads and disk accounting
in the Balance view; see [FILES.md](docs/FILES.md). The `gguf` dependency reads
metadata only: this installer does not build llama.cpp or make a partial GGUF
usable on the lead.

## Requirements

- Apple Silicon Macs (tested on M4 Mac minis with 24 GB). One Mini works;
  splitting needs more. Use a trusted LAN or Thunderbolt/USB4 link.
- Python 3.10+ for the agent and MLX environment. The stdlib web server works
  on Python 3.9+. Use a current Apple Silicon Python for MLX.
- Git for cloning (not needed for a release ZIP), and enough disk/RAM for models.
- For a manual MLX setup, after getting the source below, install on every Mini that will run a worker:

```sh
python3 -m venv ~/.caravan/venvs/mlx
# Current development checkout:
~/.caravan/venvs/mlx/bin/python -m pip install -r requirements-mac.txt
# Older Day 18 package (no requirements file):
# ~/.caravan/venvs/mlx/bin/python -m pip install 'mlx-lm==0.32.2' huggingface_hub
```

This is the tested mlx-lm version, not a fully locked dependency set. A clean
Mac installation has not been tested for this release. Model access may require
accepting the publisher's terms and a Hugging Face token in Settings.

## Get the source

Download `caravan-day18.zip` or `caravan-day18.tar.gz` from
[Day 18](https://github.com/linuxbren/caravan/releases/tag/day18-2026-11-07).
Unpack it and open a terminal in the `caravan-day18` directory. Or:

```sh
git clone https://github.com/linuxbren/caravan.git ~/.caravan/src/caravan
cd ~/.caravan/src/caravan
git checkout day18-2026-11-07
```

To follow development rather than this release, use `caravan-v3-mlx-split`.
Release archives omit `handoff/lab/videos/` (74 MB of media); it stays in Git.

## First run: one Mini

The defaults point at the author's two-Mini lab. Before loading a model, create
`~/.caravan/config.toml` (or add this section to your existing file; do not erase
other settings):

```toml
[web.nodes.local]
label = "My Mini"
role = "lead"
host = "local"
```

From the source directory:

```sh
python3 proxy/web_server.py --host 127.0.0.1 --port 8190
```

Open http://127.0.0.1:8190/. In Models choose an MLX model that fits your Mini,
download it to the local Mini, then Load and chat. Downloads can be large.
The UI starts the worker using `~/.caravan/venvs/mlx/bin/python`.
For another device to reach the UI, bind `--host 0.0.0.0` and use the lead's
LAN address. There is no login: never expose this port to the public internet.
See [WEB.md](docs/WEB.md) for controls and troubleshooting.

## Add Minis

Install the same source and MLX environment on each Mini. Enable macOS Remote
Login on peers and set up SSH from the lead so it works without an interactive
prompt. Check `ssh YOUR_USER@PEER_IP` yourself first. Only use trusted peers.

Add a table for each peer to the lead's `~/.caravan/config.toml`, replacing all
example addresses and the repository path with your own:

```toml
[web.nodes.mini2]
label = "Mini 2"
role = "packer"
host = "YOUR_USER@PEER_IP"
ssh = "YOUR_USER@PEER_IP"
repo = "~/cv3"
peer = "PEER_IP:5560"
order = 1
```

Use a unique table name and order for each extra Mini. Restart the web process
after changing config. To preserve workers on a later web restart, start the
web server with `CARAVAN_WEB_KEEP_WORKERS=1` set before its command; that process
will then keep its workers when it exits. Check Topology before loading. Peers need a reachable
worker link (MLX TCP 5560); keep it on your private network.

Topology and GGUF support multiple Minis. The experimental **Topology → Balance**
path now plans and launches N-stage MLX pipelines, with a live memory/file preview
and an explicit reload button. Existing picker downloads and Optimize now remain
two-stage; do not run Optimize on an N-stage Balance load. Extra stage shards can
be fetched directly on each Mini with `mlx_split_fetch.py --split-counts ...
--stage-index ...`. No files are copied from the lead. Three/four-stage behavior
is covered by fake-node socket tests; Apple Silicon inference is not yet live
verified. See [Day 19 setup/testing](docs/DAY19.md) and [MLX-SPLIT.md](docs/MLX-SPLIT.md).
Some older two-Mini paths still use lab defaults; if a load targets EXO2 instead
of your configured peer, stop and inspect [WEB.md](docs/WEB.md) rather than
assuming this release is a turnkey installer for every network.

## Optional: GGUF

Install CMake and Apple command-line build tools. On each participating Mini,
build the project's patched llama.cpp (Homebrew's build lacks RPC):

```sh
git clone -b caravan-patches https://github.com/linuxbren/llama.cpp ~/dev/llama.cpp
cd ~/dev/llama.cpp
cmake -B build -DGGML_RPC=ON -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

The UI expects binaries at `~/dev/llama.cpp/build/bin`; use
`CARAVAN_LLAMA_BIN` for a different location (the same path must work on peers).
Download a GGUF quant through Models on the lead. The lead holds the GGUF file
and sends peer tensors over SSH-tunnelled RPC; peers do not yet load their own
GGUF share from disk. Ollama is needed for the older Ollama-store CLI workflow,
not for picker GGUF downloads. The llama.cpp branch is not pinned by this source
package; its upgrade is still an open item.

## Check the source package

From its root (no models or Minis needed):

```sh
PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests
```

Node.js enables an optional UI assertion; it may skip if Node is absent.
See [DAY17.md](docs/DAY17.md) for live lab results and known limits, including
partial-file downloads that restart from zero.
