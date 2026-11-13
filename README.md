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

Setup checks your Mac, prepares what Caravan needs, and opens your browser. Open a new Terminal window afterward to use `caravan status`. You do not need Homebrew, Git, an administrator password, or developer tools. The command downloads and runs a script; [read it first](install) if you prefer. Downloads need internet access.

In the browser, open **Models**, pick a small model that fits, click **Download**, then choose **Load** and chat. No model is included. Some publishers require you to accept their terms first.

Caravan starts when you log in. After a reboot, unlock your Mac and log in. It brings back the last model you successfully loaded. Choose **Unload** first if you do not want that model to come back.

## Add another Mac

1. On the new Mac, run the **same install command** above. Open **Topology → Add a Mac** in its Caravan page.
2. Click **Open the right Mac setting** and turn on **Remote Login** for your account. Return to Caravan and click **Show a new code**.
3. On your first Mac, open **Topology → Add a Mac**, click **Find nearby Macs**, then **Add this Mac**. Enter the code shown on the new Mac.

Caravan saves the connection. Repeat for each extra Mac. You do not need to edit settings files or check long fingerprints. Unload your model before using **Remove this Mac**. [Help with adding Macs](INSTALL.md#add-minis).

Pairing is new and experimental. Only connect Macs and accounts you trust. Your Mac may ask an administrator to allow Remote Login; Caravan cannot bypass that permission.

## Stop, remove, or get help

Use **Unload** in the browser to free the model's memory. To stop the browser service until your next login, open Terminal and run:

```sh
caravan stop
```

Start it again with `caravan start`, then `caravan open`.
Caravan checks once a day for a newer version. When one is ready, an
**Update available** badge appears on the page, and **Update now** in
Settings runs the same update as `caravan update`. From another
device, update on this Mac, or run `caravan update` in Terminal.
Remove paired Macs first. `caravan uninstall` asks before removing all Caravan services, models, settings and files. [Uninstall help](INSTALL.md#remove-caravan-safely).

Check whether Caravan is running with `caravan status`. Need help? Run `caravan doctor`, read [installation help](INSTALL.md#troubleshooting), or [open an issue](https://github.com/linuxbren/caravan/issues). Do not include passwords, tokens or private chats in reports.

## For developers / details

[Developer setup](docs/DEVELOPMENT.md) · [Clean-install fixes and verification](docs/DAY23.md) · [Package status](docs/PACKAGING.md) · [Documentation index](docs/README.md) · [Changelog](CHANGELOG.md).

The browser page is for your own Mac. Do not expose it to the public internet.

## License

Caravan is open source under the [MIT License](LICENSE). Copyright (c) 2026 Brenden Dawson. One adapted file keeps its own MIT notice: [agent/native_mtp.LICENSE](agent/native_mtp.LICENSE).
