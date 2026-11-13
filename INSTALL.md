# Install Caravan on a Mac

Caravan is experimental. You need an Apple Silicon Mac (M1 or newer), macOS 14
or newer, internet, and room for setup and your models. More memory, or adding
Macs, lets you run bigger models. Caravan checks what fits.

## Easy install

1. Press **Command–Space**, type **Terminal**, and press **Return**.
2. Paste this command and press **Return**:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install | bash)
```

3. Wait for the browser to open. Setup gets everything Caravan needs. No Git,
   Homebrew, developer tools, or administrator password needed.
4. Open **Models** and click **Download** on a small model that fits. If a model
   has several parts, Caravan downloads all of them. Choose **Load** when asked,
   then chat. No model comes included. Some publishers require you to accept
   their terms first.
5. Open a **new Terminal window** to use the commands below.

The command downloads and runs a script. You can [read it first](install).
Caravan is not a signed Mac app. Never turn off your Mac's security settings
to install it. Setup keeps your existing models and settings.

## Everyday commands

| Command | What it does |
|---|---|
| `caravan status` | Says whether Caravan is running; shows the problem if not |
| `caravan open` | Opens Caravan in your browser |
| `caravan stop` | Stops the browser service until your next login |
| `caravan start` | Starts it again |
| `caravan doctor` | Shows detailed checks when something goes wrong |
| `caravan update` | Updates Caravan and brings the page back |
| `caravan models` | Lists downloaded models, with a friendly name, GGUF or MLX, and the id to copy. Marks the currently loaded one |
| `caravan bench` | Compare a GGUF model to its MLX counterpart by a plain name or by ids. Default: five short prompts and a long-prompt series (~1k, ~4k, ~8k); `--short` or `--long` for just one. Prints reply-stats wording and a short summary. Without `--yes` it shows the pair and the exact command. After a live run it puts the original model back. On a terminal, a small campfire shows the current step and elapsed time (`--quiet` turns it off). Run `caravan bench --help` for details |

Use **Unload** in the browser to free the model's memory before stopping.
After restarting your Mac, unlock it and log in. Caravan starts and brings
back the last model you successfully loaded. Choose **Unload** first if you
want it to start without a model.

## Open from your other devices

The page normally opens only on the Mac where Caravan is installed. If
Tailscale is already on that Mac and you are signed in, setup asks:

Open Caravan from your other devices over Tailscale? (y/N)

It defaults to no. You can also turn this on later in **Settings**, or by
running `caravan remote on`. Only devices on your Tailscale network can
open the page. `caravan remote status` shows the address to use. Turn it
off in Settings, with `caravan remote off`, or when you uninstall.

## Open on your local network

You can also open the page from other devices on the same network.
Setup asks, with No as the default:

Open Caravan on your local network? (y/N)

Anyone on the same network can use Caravan, and there is no login.
You can change this later in **Settings**, or with `caravan lan on`
and `caravan lan off`. `caravan lan status` shows the address to
open (`http://<lan-ip>:<port>`), and a clickable link appears under
the Settings switch. This can be on at the same time as the Tailscale
share; both addresses stay reachable. When this is off, the page stays
only on this Mac (the Tailscale share is unchanged). Your Mac may ask whether to allow incoming
connections; that is expected. Uninstall turns this off.

## Add Minis

Each extra Mac is **the new Mac**. The Mac you started with is **your first Mac**.

1. On **the new Mac**, run the same install command. Open **Topology → Add a Mac**.
2. In the left column, **On the new Mac**, click **Open the right Mac setting**.
   Turn on **Remote Login** for your account, then return to Caravan. If needed,
   find it in **System Settings → General → Sharing → Remote Login**.
3. On **the new Mac**, click **Show a new code**.
4. On **your first Mac**, open **Topology → Add a Mac**. In the right column,
   **On your first Mac**, click **Find nearby Macs**, then **Add this Mac**.
   Enter the code shown on **the new Mac**.
5. Choose your next model. Caravan works out where it fits. Adding a Mac does
   not interrupt a model that is already running.

Keep both Macs on the same trusted home network or connect them with a
Thunderbolt cable. Only add Macs and accounts you trust. A managed Mac may
need an administrator to allow Remote Login. Never expose it to the internet.

To remove a Mac, **Unload** first, then click **Remove this Mac** on its card
in **Topology** on **your first Mac**. Keep both Macs online until removal
finishes. Model files are kept.

Can't open setup? Run `caravan add-mini` on the Mac where you want to open it.

## Update or reuse an existing install

In Terminal:

```sh
caravan update
```

Do not update during a chat. The page comes back on its own. If the code that
runs the model changed, the last model is reloaded and Caravan says so.
Previous source files are backed up; models and settings stay. If an update
fails, Caravan goes back to the previous version, starts it, and tells you.

## Remove Caravan safely

Remove paired Macs first, then run `caravan uninstall` and confirm: it turns off the Tailscale share and local-network access and removes all Caravan services, models, settings and files (use `--yes` to skip confirmation).

## Troubleshooting

- **Not sure it is running?** Run `caravan status`. Follow the fix it shows.
  Run `caravan doctor` for more detail.
- **Download failed?** Check your internet and free disk space. Press **Resume**.
- **Model won't load?** Read the reason shown in Caravan. Try a smaller model
  or close other apps. Do not force it to fit.
- **Old startup files found?** Nothing is deleted. Setup explains how to keep
  a backup and replace the old files. See [safe recovery](docs/DEVELOPMENT.md#clean-install-runtime-and-recovery).
- **No browser after reboot?** Unlock your Mac, log in, then run `caravan open`.
- **Cannot add a Mac?** Check Remote Login on **the new Mac**, show a fresh code,
  and try again from **your first Mac**.
- **Apple security warning?** Do not bypass it. Report the exact message.

[Developer setup and advanced recovery](docs/DEVELOPMENT.md) ·
[Package and test status](docs/PACKAGING.md).
Report problems at https://github.com/linuxbren/caravan/issues. Leave out
passwords, tokens, private paths and chats.
