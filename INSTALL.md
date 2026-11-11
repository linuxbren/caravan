# Install Caravan on a Mac

One Mac? The easy-install steps below are all you need. Extra-Mac setup and
recovery details follow; you can skip them for now.
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

Press **Command–Space**, type **Terminal**, and press Return. Paste this into
Terminal, then press **Return**:

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

The easy package uses an exact-version dependency lock and binary wheels only.
If a required wheel is unavailable, setup stops rather than compiling or asking
for developer tools. Source/developer installs retain requirements-mac.txt. Interrupted setup can be rerun;
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
| `add-mini` | Open the Add Macs page with permission for this account |

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

The first Mac is the **1st node** (lead); the next is the **2nd node** (helper).
Your **development node** is the computer used to manage the project; it need
not be a Mac or use a particular operating system. See [names and placeholders](docs/README.md).

1. On **each extra Mac**, run the same Easy install command. Each Mac gets a browser page; no fixed model is started.
2. On that Mac, click **Add Macs**. Click **Open the right Mac setting**, turn on **Remote Login** for the current account, then return. If the button does not open it, use **System Settings → General → Sharing → Remote Login**. A managed/non-admin Mac may need its administrator. There is no need to give Terminal Full Disk Access.
3. Click **Show a new code** on the new Mac. On the first Mac, open **Add Macs → Find nearby Macs**. Check its name, click **Add this Mac**, and enter that code. Setup also prints an initial code in Terminal; it expires after five minutes.
4. Return to Caravan and choose your next model. Caravan suggests the order and works out the fit. Adding a Mac does **not** reload a running model. For a cable setup, use Balance to check the links before loading.

No hand-written connection settings, manual key copying, or fingerprint check is
needed. Repeat for additional Macs. The first Mac gets permission to start
Caravan programs in the new Mac's account: pair only accounts you trust. Never
forward Remote Login or Caravan to the public internet.

**Remove a Mac:** Unload the model, then open **Add Macs → Remove this Mac** on
the first Mac. Caravan removes its own connection settings and keys; model files
stay. Offline? It keeps a pending removal and retries when that Mac returns.
Until confirmed, do not assume its access has been revoked. Bring it back online
before uninstalling either side. It never removes unrelated SSH keys/settings.

**Can't open Add Macs?** Use `~/.caravan/bin/caravan add-mini` on that Mac. This
opens a private browser handoff for your account. The page deliberately refuses
other computers and other local accounts; do not copy its private handoff files.
Use the page on the first Mac itself, not a public/LAN browser address. VPN
access to the ordinary app does not grant permission to pair Macs.

Discovery looks for installed Caravan Macs over the home network/Thunderbolt or
an existing private tailnet; it does not create a VPN, change routes, or prove
cable bandwidth. Mac firewall permission may be needed. Automatic trust is a
separate encrypted short-code protocol, not trust in an advertised name.
Codes are single-use, expire quickly and allow only a few attempts. Security
review and a fresh-account test remain release gates; see [pairing details and
actual test coverage](docs/PAIRING.md). Old manual/source setup is preserved in
[the developer guide](docs/DEVELOPMENT.md#manual-extra-mac-setup).

Balance supports N-stage plans; physical inference is measured on two Macs, not
three or more. Older Optimize paths remain two-stage. See [MLX-SPLIT](docs/MLX-SPLIT.md).

## Optional integrations

- **Balance:** Auto chooses a split. Adjust shows a preview; Apply reloads the
  model. A reload banner shows each Mac's progress and locks chat until ready.
  Apply is black when usable, grey when reloading or no change is needed.
- **Tiny title helper:** optional and not downloaded by setup. It waits for
  the primary model and spare memory. It is not part of the normal package.
- **Adaptive lookup:** opt-in speed experiment, not a default or speed promise.
- **GGUF in the current source branch:** each Mac downloads only its part,
  directly from the publisher. The picker shows progress for each Mac and
  verifies the pieces before offering Load. Interrupted downloads can Resume;
  Balance reuses verified local pieces and fetches only missing ranges. No
  full copy or weight forwarding over the cable is needed. The cable still
  carries chat activations and control messages.
  Install Apple command-line build tools, Git and CMake on every participating
  Mac first; the first download then builds a pinned native backend in
  `~/.caravan/runtimes/gguf-shards/`, separate from existing runtimes. A missing
  prerequisite stops safely: install it, then Resume. Homebrew tools are found
  even when a login service has a short PATH. This is not bundled in the
  published Day 21 package, and no Day 22 installer channel has been released.
  Single-file qwen2/llama GGUF sources with HTTP Range support are supported.
  Other layouts stop rather than quietly sending weights between Macs. The
  advanced **full-file fallback** must be selected explicitly; it retains the
  older full-model-on-the-1st-node behavior and separately built runtime
  (`CARAVAN_LLAMA_BIN`). See [Day 22](docs/DAY22.md) for evidence and limits.

## Remove Caravan safely

Remove paired Macs first (bring both online and use **Remove this Mac**), then
Unload in the page and run `~/.caravan/bin/caravan uninstall`. This removes only
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
