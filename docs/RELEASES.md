# Daily releases

At the end of each development day, commit the day's work and publish a source
release with install instructions. This is a work checkpoint, not a timed job.
Use `dayN-YYYY-MM-DD` (America/Chicago date), starting with
`day17-2026-11-07`. Title: `Day 17 (Nov 7 2026)`. Never move a published tag.
If a correction needs a new release, append `-fix1`, `-fix2`, and explain it.

1. Finish docs, CHANGELOG and the Obsidian day note. Keep every test result,
   including failures. Update INSTALL.md if setup changes.
2. Run `PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`.
3. Commit as linuxbren. Push `caravan-v3-mlx-split`, then fast-forward `main`
   to the same commit. Check ancestry first; never force or rewrite history.
   Keep the working branch on `caravan-v3-mlx-split`.
4. Build clean packages from the committed tree (not the working directory):

```sh
# Set DAY, TAG and COMMIT for this release first.
git archive --format=zip --prefix="caravan-day${DAY}/" "$COMMIT" > "caravan-day${DAY}.zip"
git archive --format=tar --prefix="caravan-day${DAY}/" "$COMMIT" | gzip -n > "caravan-day${DAY}.tar.gz"
gh release create "$TAG" --target "$COMMIT" --title "Day ${DAY} (DATE)" --notes-file release-notes.md "caravan-day${DAY}.zip" "caravan-day${DAY}.tar.gz"
```

5. Notes must say what changed, link the install guide, report checks and limits.
   `handoff/lab/videos/` is export-ignored to keep source downloads small; media
   remains in Git. Models, dependencies and compiled runtimes are not bundled.
6. Download the published asset to a fresh directory, extract it, check
   INSTALL.md exists and rerun the full test command there. Record counts,
   duration, failures and skips in the day log. If verification fails, disclose
   it immediately; do not silently replace an existing release asset/tag.
7. Pull with `git pull --ff-only` on EXO1 `~/dev/caravan-v3` and EXO2 `~/cv3`.
   Check tracked changes first. Never use scp or touch EXO2 `~/dev/caravan`.
   Docs-only updates need no service restart. Preserve unrelated local files.
8. Record the release URL, tag, commit, asset sizes and verification in the repo
   day log and Obsidian diary. A later documentation-only commit may record the
   completed publication checks without moving the release tag.

A GitHub release source download is not a signed installer. Do not claim that
passing the stdlib suite proves a clean Mac installation or hardware speed.
