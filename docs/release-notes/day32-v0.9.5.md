Day 32 part A fix. The **Check for updates daily** switch now does what it says, and the daily check is sturdier.

- **Daily off means no update status.** With the switch off, Settings shows just the version (for example `v0.9.5`), with no "up to date", no Update available badge and no Mac lines, until you click **Check now**. Before, an answer from when it was on kept showing.
- **Works at once.** Flipping the switch updates the page right away, no reload. Turning it back on shows the last answer if it's less than a day old, or checks right away.
- **Sturdier daily check.** One unexpected error no longer stops the daily check until Caravan restarts. A cut-off reply counts as offline. When offline, the page stops saying "up to date" from an old answer and tries again every hour.
- 2,078 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#part-a-fix-daily-update-check-v095).
