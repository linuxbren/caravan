Day 33: failed updates say why (CAR-13). Fixes a silent update rollback.

- **Fixed: a silent update rollback.** `caravan update` could finish its install, then undo the whole update because the page was slow to answer, and tell you only "The update failed. Caravan is back on the previous version." The page now gets 2 minutes to come back (5 minutes when a saved model is coming back), up from 30 seconds. These limits are generous guesses, not measured times; a healthy page still returns as soon as it answers.
- **Fixed: a failed engine step no longer fails the whole update.** If building the own-part engine hit a failing git, patch or cmake step, or ran out of time, the install exited with an error and the update rolled back. Now it prints the same "Hey, I'm sorry…" note, with a plain reason, and the rest of setup finishes. This came from v0.9.18 (CAR-10): that release only covered missing tools.
- **Added: when an update does fail, it says why.** One short line before the failure message ("Why the update failed: …"), saved to `~/.caravan/logs/update-failure.log`, and shown on the Mac's line in Settings. The rollback's reinstall now logs to `update-rollback.log`, so `update.log` keeps the failed attempt.
- Not run on real Macs as part of this release; the tests use stand-ins. The exact error from the failed update that prompted this was never captured, so this release makes the next one visible rather than claiming to have found it. All five locales.
- Source and pin commits: see [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md#failed-updates-say-why-car-13-v0919). Tests: 2,454 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
