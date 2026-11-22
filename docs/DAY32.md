# Day 32 — localization; part A: version label

Day 32 runs Nov 22 2026 (America/Chicago). Part A is released as
[v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4).

1. [Plan: localization](#plan-localization)
2. [Part A: version label](#part-a-version-label)

## Plan: localization

- Pull every piece of text the web page, the `caravan` command and the
  installer show into one English strings file, keyed by name.
- Look text up by key, with English as the fallback for a missing key or
  language, so a half-translated language never shows a blank.
- First languages: Spanish, Simplified Chinese and Japanese. Then German,
  to test long words in buttons and narrow layouts.

## Part A: version label

Brenden: "Lets first do the version for 32 so that I can use it now."

- Settings now shows the installed version, small and dim, right next to
  its title, for example `v0.9.4 · up to date`.
- The status comes from the existing daily update check: "up to date"
  when the last check found nothing newer, "update available" when a newer
  release is out or another Mac is behind (click it to go to **Update
  now**). With no check yet, daily checks off, or no internet, only the
  version shows. On the local network (no update view), only the version
  shows.
- Where the number comes from: a new `VERSION` file in each release's
  source commit (`0.9.4`), read from the installed copy, plus the
  installed pin (`.caravan-package`) as the build (hover the version to
  see it). Nothing is written into the page. A source checkout uses
  `VERSION` and its git commit.
- `caravan --version` (also `caravan version`) prints
  `Caravan v0.9.4 (<build>)`, `caravan status` says
  `Caravan v0.9.4 is running`, and `caravan doctor` lists
  `Installed: Caravan v0.9.4 (<build>).`
- `/api/status` has a new `version` field: `version`, `label`, `ref`,
  `short`, `packaged`.
- The label uses the theme's `--mono` font and `--muted` color; "update
  available" uses the accent color, like other links in Settings.
- Release steps: set `VERSION` in the source commit
  ([RELEASES](RELEASES.md)).

### Tests

- `tests/test_day32_version_label.py` (13 tests): the version and build
  from a fake install, unknown when `VERSION` is missing or malformed (never
  guessed), a bad pin ignored, `VERSION` matches the newest CHANGELOG
  entry, no version written into the page or server, the `/api/status`
  field, the label's place and theme styles, the state rules (also run in
  Node: hidden view, source checkout, newer, other Mac behind, checked,
  offline, never checked), and `caravan --version` / `doctor`.
- `tests/test_day23_clean_install.py`: the one-line `caravan status` now
  includes the version.
