# Install Caravan on a Mac

Start with the [simple guide](README.md). This page covers checks, extra Macs and recovery.
Caravan is experimental, not a signed or notarized Apple app. Do not turn off
Gatekeeper, FileVault or SIP to install it. No administrator password is needed
for the normal one-Mac setup.

## Easy install

You need an Apple Silicon Mac (M1 or newer), macOS 14+, enough free disk for
setup and your models, and internet. More memory lets you run bigger models;
adding Macs pools their memory. Caravan works out what fits for you. Setup
reserves 8 GB of free disk space before downloading; models need extra.
The installer rejects Intel/Rosetta, old macOS, root/sudo and low disk/memory.
A non-admin user can install in their own home folder. Managed Macs may need
an administrator to permit downloads or Remote Login for extra Macs.

Open Terminal, paste this, press Return:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install | bash)
```

This follows the development channel. [Read the bootstrap](install) before
running it. It fetches a specific source commit and checks its SHA-256 before
extracting it. GitHub supplies the bootstrap and manifest over HTTPS; the
checksum is an integrity check, **not an Apple signature**. For an immutable
source package, see [package status](docs/PACKAGING.md).

What happens:
1. Check the Mac without changing its security settings.
2. Download Caravan to `~/.caravan/src/caravan`. No Git or Xcode required.
3. Install a checksum-verified, pinned uv utility and private Python 3.12 under
   `~/.caravan/runtime/`. System Python and shell profiles stay untouched.
4. Create `~/.caravan/venvs/mlx`, install dependencies, and check imports.
5. Create a one-Mac configuration **only if no configuration exists**.
6. Install a per-user browser service, starting at login, and open your browser.
7. In Models, download a small model that fits, Load, and chat. No model ships
   with Caravan. Some downloads require a publisher agreement/token.

Setup uses wheels where available; dependencies are not yet completely locked.
If a dependency unexpectedly asks for compiler tools, stop and report it rather
than installing arbitrary developer tools. Interrupted setup can be rerun;
existing models/settings are not removed. Checks happen before service changes.

For checks without downloading or installing anything:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install | bash -s -- --check)
```

Use `--port 8290` if another app already uses the default browser address;
`--no-start` installs without opening/starting it. Services need a logged-in
Mac desktop session. SSH-only setup without one should use `--no-start`, then
log in on the Mac and run `~/.caravan/bin/caravan start`.

## Everyday commands

All commands below start with `~/.caravan/bin/caravan`. This full path works
without changing your Terminal settings. Advanced users can add
`~/.caravan/bin` to PATH themselves.

| Command | Result |
|---|---|
| `open` | Open the browser page |
| `status` | Show owned Caravan services and log paths |
| `doctor` | Read-only platform, disk, environment and port checks |
| `stop` | Stop only the web service until next login/start; model workers stay running |
| `start` | Start the installed web service; never reboot the Mac |
| `update` | Download/verify the channel's pinned source; requires web stopped; leaves it stopped |
| `uninstall` | Remove only the web login service; keep source, models, runtime and settings |
| `add-mini` | Show extra-Mac setup instructions (not automatic pairing) |

Use Unload in the page **before stop** to free the model's memory. An Unload
also saves “restore nothing.” Otherwise the last successful model and its exact
split are restored at next login. Day 21's follow-up fix retries temporary
Mini/memory/link readiness failures for up to ten minutes, then shows a warning.
It does not silently download missing model files. Both-Mini restore was proven
on the existing auto-login, FileVault-off lab accounts; a new user/FileVault-on
installation is still untested. See [DAY21.md](docs/DAY21.md).

## Update or reuse an existing install

For an easy-package installation, Unload if desired, then:

```sh
~/.caravan/bin/caravan stop
~/.caravan/bin/caravan update
~/.caravan/bin/caravan start
~/.caravan/bin/caravan open
```

Updates do not overwrite a Git checkout or source files with local edits.
The previous package source is kept in `~/.caravan/src/caravan-backup-*`.
If setup fails, keep the backup and logs; do not delete models or settings.
A failed update may leave the new source on disk with the service stopped;
inspect doctor and rerun setup, or restore the previous source folder while
stopped. Dependency rollback is not automatic. Do not update during a chat.
This is not yet a fully transactional, signed application updater.

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

## Add Minis

Run this on **each extra Mac**:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install | bash -s -- --role worker)
```

It prepares the software but starts no fixed-model service. On the helper,
enable **System Settings → General → Sharing → Remote Login** for your user.
From the lead Mac, establish SSH trust yourself: `ssh YOUR_USER@PEER_ADDRESS`.
Verify the fingerprint, then set up key-based login so that command works
without a password prompt. Caravan does not create trust or disable host checks.
Never paste a private key into an issue or chat.

On the lead, add a table to `~/.caravan/config.toml` (keep its existing local
table and other settings):

```toml
[web.nodes.mini2]
label = "Mini 2"
role = "packer"
host = "YOUR_USER@PEER_ADDRESS"
ssh = "YOUR_USER@PEER_ADDRESS"
repo = "~/.caravan/src/caravan"
peer = "PEER_PRIVATE_ADDRESS:5560"
order = 1
```

Use a unique name and order for every extra Mini. Restart only the browser
service (`caravan stop`, `caravan start`) after editing the file. Its generated
service keeps model workers when stopped. Check Topology before loading.
Balance supports N-stage plans; live inference is measured on two physical
Macs, not three or more. Some older picker/Optimize paths remain two-stage;
do not run Optimize on an N-stage Balance load. See [MLX-SPLIT](docs/MLX-SPLIT.md).

**Thunderbolt discovery is read-only.** It inspects trusted configured Macs,
checks links on request, and can preview a plan. It does not pair unknown Macs,
install SSH keys, apply routes or replace your config. Checks expire after
30 seconds. A reachable port does not prove peer identity. For reboot-safe
interface endpoints and trusted-host details, see [SERVICES](docs/SERVICES.md).

## Optional integrations

- **Balance:** Auto chooses a split. Adjust shows a preview; Apply reloads the
  model. A reload banner shows each Mac's progress and locks chat until ready.
  Apply is black when usable, grey when reloading or no change is needed.
- **Hermes:** separate installation/configuration; the easy package does not
  install Hermes or change its tools. Use the loopback proxy and [HERMES](docs/HERMES.md).
- **Tiny title helper:** optional and not downloaded by setup. It waits for
  the primary model and spare memory; proxy routing is opt-in. See [HERMES](docs/HERMES.md).
- **Adaptive lookup:** opt-in speed experiment, not a default or speed promise.
- **GGUF:** optional patched llama.cpp runtime must be built separately.
  Install Apple build tools and CMake, then build `caravan-patches` from
  https://github.com/linuxbren/llama.cpp with `GGML_RPC=ON`, `GGML_METAL=ON`.
  Set `CARAVAN_LLAMA_BIN` if not in `~/dev/llama.cpp/build/bin`.
  Today the lead still holds the complete GGUF; independent per-Mac tensor
  loading is Day 22 work. The easy package is not a bundled GGUF runtime.

## Remove Caravan safely

Unload in the page, then `~/.caravan/bin/caravan uninstall`. This removes only
the owned web login job. For optional proxy/worker jobs, inspect `status` then
use `uninstall --name NAME` for **each** owned job you intend to remove.
Uninstall retains downloaded models, chat/cache data, source, runtime, settings,
logs and the command. No “delete every model” switch is provided. Inspect those
folders yourself before deleting anything. Do not delete `~/.caravan` wholesale
unless you truly intend to lose its contents. Never sweep processes by name.

## Troubleshooting

- **No browser:** run `~/.caravan/bin/caravan doctor`, then `status`. Read the
  log path it prints. Try `open`. No need to reboot.
- **Address in use:** do not kill unknown apps. Choose another `--port` on first
  install. Existing service ports are deliberately not silently changed.
- **Download failed/offline:** reconnect, check disk/Wi-Fi/firewall, rerun.
  Setup is not offline-capable. GitHub, PyPI and model hosts must be reachable.
- **Apple says the app cannot be verified:** this is not a signed `.app` or
  `.pkg`. Do not bypass Gatekeeper or strip quarantine. Use reviewed source
  instructions or report the warning. An enterprise policy may require IT.
- **FileVault/reboot:** someone must unlock and log in. Login services cannot
  serve before login; setup never enables auto-login or stores a login password.
- **Spaces in a folder:** supported; quote paths in manual commands. Use an
  absolute `--repo` path, not a literal `~` inside quotes.
- **Another install running:** wait. A crash can leave `~/.caravan/install.lock`;
  confirm no installer is running before removing that empty lock directory.
- **Model won't load:** check free memory/files on every selected Mac. Start
  with a smaller model. Do not force a memory guard to pass.

Report errors at https://github.com/linuxbren/caravan/issues with macOS/chip,
command and relevant error text. Remove private paths, tokens and chat content.
For actual test coverage and remaining acceptance gates see [PACKAGING](docs/PACKAGING.md).
