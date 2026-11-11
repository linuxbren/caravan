# Caravan

Run a big AI model across your Macs at home. Your chats run on your own Macs, not a cloud AI service.

**For the simple version:** see [How to install Caravan](INSTALL.md) — a few easy steps, no tech know-how needed.

## What you need

- A Mac with an **Apple Silicon chip** (M1 or newer), running **macOS 14 or newer**. Intel Macs are not supported.
- More memory lets you run bigger models. Adding Macs pools their memory. Caravan checks what fits for you.
- At least **8 GB free space** for setup, plus room for your models. Models can take tens of GB.
- An internet connection for setup and model downloads. More than one Mac? Keep them on a trusted home network.

**Caravan is experimental.** It has been tested on two M4 Mac minis. The new easy-install package still needs fresh-account and FileVault testing. It is not a signed Mac app.

## Install

Open **Terminal** (find it with Spotlight), paste this, and press **Return**:

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/caravan-v3-mlx-split/install | bash)
```

Setup checks your Mac, downloads Caravan and its own Python, and opens your browser. You do not need Homebrew, Git, an administrator password, or developer tools. The command downloads and runs a script; [read it first](install) if you prefer. Downloads need internet access.

In the browser, open **Models**, pick a small model that fits, download it, then choose **Load** and chat. No model is included. Some publishers require you to accept their terms first.

Caravan starts when you log in. After a reboot, unlock your Mac and log in. It brings back the last model you successfully loaded. Choose **Unload** first if you do not want that model to come back.

## Add another Mac

1. On the new Mac, run the **same install command** above. Open **Add Macs** in its Caravan page.
2. Click **Open the right Mac setting** and turn on **Remote Login** for your account. Return to Caravan and click **Show a new code**.
3. On your first Mac, open **Add Macs**, click **Find nearby Macs**, then **Add this Mac**. Enter the code shown on the new Mac.

Caravan saves the connection. Repeat for each extra Mac. You do not need to edit settings files or check long fingerprints. Unload your model before using **Remove this Mac**. [Help with adding Macs](INSTALL.md#add-minis).

Pairing is new and experimental. Only connect Macs and accounts you trust. Your Mac may ask an administrator to allow Remote Login; Caravan cannot bypass that permission.

## Stop, remove, or get help

Use **Unload** in the browser to free the model's memory. To stop the browser service until your next login, open Terminal and run:

```sh
~/.caravan/bin/caravan stop
```

Start it again with `~/.caravan/bin/caravan start`, then `~/.caravan/bin/caravan open`.
To remove its automatic startup: `~/.caravan/bin/caravan uninstall`. This removes only the browser service. Your downloaded models, settings and files stay safe. Optional extra services must be removed separately; see [the install guide](INSTALL.md#remove-caravan-safely).

Need help? Run `~/.caravan/bin/caravan doctor`, read [installation help](INSTALL.md#troubleshooting), or [open an issue](https://github.com/linuxbren/caravan/issues). Do not include passwords, tokens or private chats in reports.

## For developers / details

Current code includes Day 21 Balance controls, read-only Thunderbolt checks, the post-release readiness-retry fix, Day 22 per-Mac model-share work, and the experimental Add Macs flow. The immutable Day 21 tag does **not** contain that later fix. See [Day 21 evidence](docs/DAY21.md), [package status](docs/PACKAGING.md), [configuration](docs/CONFIGURATION.md), and [roadmap](docs/ROADMAP.md).

The browser service binds to this Mac only by default. There is no built-in login: never expose it to the public internet. Model downloads contact their publishers; optional cloud features send data to the provider you choose. Local chat itself does not require a cloud AI provider.

### Technical documentation

[Documentation index and node names](docs/README.md) · [Developer setup](docs/DEVELOPMENT.md)

[Configuration](docs/CONFIGURATION.md) · [Services](docs/SERVICES.md) ·
[Web UI](docs/WEB.md) ·
[Architecture](docs/ARCHITECTURE.md) · [MLX split](docs/MLX-SPLIT.md) ·
[File placement](docs/FILES.md) · [Measurements](docs/BENCHMARKS.md) ·
[Changelog](CHANGELOG.md) · [Daily releases](docs/RELEASES.md).

The current source branch also includes [Day 22 GGUF own-part downloads](docs/DAY22.md):
**each Mac downloads only its part** directly from the publisher, then loads
those verified pieces from its own disk. Split models appear in the normal
model picker, with Load, Unload, Switch, Balance and saved restore. No full
model is passed over the cable; the cable still carries chat activations.
The first download prepares an isolated optional native backend (Apple build
tools and CMake required). Unsupported sources stop with a clear error; the
old full-file download is an explicit advanced fallback, never automatic.
This work is not yet a Day 22 release or an update to the published installer
channel. N-stage planning is tested; physical inference has been verified on
two Macs. Thunderbolt inventory/link checks remain read-only. The separate
[short-code pairing flow](docs/PAIRING.md) establishes trust and saves node configuration.

Developers can run the portable suite without models or Macs:

```sh
python3 -m pip install -r requirements-test.txt
PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests
```
