# Day 32 — Caravan lives on `main`

Day 32 ran Nov 19 2026 (America/Chicago). Owner: "Let's just get it into
main and update all of the code that requires a change to be made for a
successful update to be had." The working branch name
`caravan-v3-mlx-split` no longer described Caravan. From now on everything
is on `main`, under the plain name Caravan.

## Install line

```sh
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

## What changed

- **Install and update read `main`.** The curl installer (`install`) reads
  `packaging-version` from `main`; `caravan update` and Update now fetch
  the installer from `main`; the daily update check reads the pin from
  `main` (`tools/caravan_update_check.py`: `CHANNEL_BRANCH = "main"`, one
  `INSTALL_URL` shared with `caravan update`). `scripts/install.sh`
  defaults to `--ref main`.
- **Older installs keep updating.** An install from before Day 32 reads
  the pin and installer from `caravan-v3-mlx-split` (older ones from
  `clean-install-fixes`). Every release now fast-forwards both branches to
  the same commit as `main` ([release steps](RELEASES.md), step 3), so
  they get the same release. After that first update their new code
  follows `main`. No branch is deleted. A source checkout still on an old
  branch keeps pulling that branch with `scripts/install.sh --update`
  instead of being refused; `--ref` given by hand is still strict.
- **Docs and website.** README, INSTALL, DEVELOPMENT, RELEASES,
  ARCHITECTURE, CONFIGURATION, MLX, MLX-SPLIT and FILES, the pairing page's
  help link, and the project website (install command, doc links, video
  links) point at `main`. "v3" was dropped where it was only the branch or
  a legacy label (for example "MLX split across two Macs (Caravan v3)" is
  now "MLX split across two Macs").
- **Tests.** `tests/test_day32_main_channel.py`: the update check, `caravan
  update`, the curl installer, `scripts/install.sh`, README and INSTALL all
  point at `main`; no live code or current guide names an old branch
  outside the documented transition list; old-branch checkouts keep
  updating without a branch switch.

## Kept on purpose

- `caravan-v3-mlx-split` and `clean-install-fixes` stay on GitHub and are
  fast-forwarded with every release until the owner says older installs
  are gone. They are named only in `LEGACY_CHANNEL_BRANCHES`, the
  old-checkout case in `scripts/install.sh`, the release steps,
  DEVELOPMENT (how to move an old checkout), and the Day 32 test.
- Compatibility names are unchanged: LaunchAgent labels
  `com.caravan.v3.*`, the uninstall marker "Caravan managed service v3",
  and the `~/cv3` default checkout path for paired Macs. Renaming them
  would leave old services behind on every Mac.
- History is unchanged: dated day notes, LOG, CHANGELOG, BENCHMARKS,
  `handoff/`, `docs/history/`, the page's journey chart (v0 … v3 labels)
  and video file names.

## Checks

- Full test suite: 1,910 tests, OK (`PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`).
- The new install line resolves: the `install` script and
  `packaging-version` on `main` both fetch over HTTPS on the development
  node (fetch only, not run).
- Live check (after publishing): `caravan update` on the 1st Mac updates
  the 2nd Mac and then itself from the old-branch pin (old code), and the
  update check on both Macs then reads `main`. This file ships in that
  release, so the live result is recorded in the Obsidian diary.
