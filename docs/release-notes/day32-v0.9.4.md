Day 32 part A. Settings now tells you which Caravan you're running and whether it's current.

- **Version in Settings.** Next to the Settings title you'll see the installed version, for example `v0.9.4 · up to date`. If a newer release is out (or another Mac is behind), it says `update available`; click it to get to Update now. With no update check yet, daily checks off, or no internet, it shows just the version.
- **Same version everywhere.** `caravan --version` (or `caravan version`), `caravan status` and `caravan doctor` show it too.
- **Always the real one.** The number comes from a `VERSION` file shipped with each release, and the build from the installed pin. Nothing is written into the page.
- Day 32's main work is localization: all the app's text in one English strings file, then Spanish, Simplified Chinese, Japanese and German. That comes next. 2,051 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md).
