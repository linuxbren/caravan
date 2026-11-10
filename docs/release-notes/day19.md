# Day 19 (Nov 8 2026)

Published Nov 9 CST; development-day tag `day19-2026-11-08`.

## Changed
- Balance Auto/manual layer controls and fresh per-node safety/file preview; arbitrary-stage MLX split, simulated 3/4-node coverage and two-physical-Mini live checks.
- Idempotent Mac install and per-user launchd web service. Last successful model, engine, exact placement/split and settings restored through the normal load path; explicit Unload restores nothing.
- Each MLX stage fetches its own pinned/checksummed files. GGUF peers use native RPC cache; strict independence remains partial.
- LAN/Thunderbolt SSH fallback and non-root Tailscale recovery guards documented in REMOTE-ACCESS.md (8ff3852).
- Kept Huihui Qwen3.5-27B Claude 4.6 Opus abliterated 4-bit on EXO2/EXO1 24/40. Correct short web/proxy replies: ~0.8 s first token, ~5.4 tok/s writing. Not sustained performance claims.

## Install
Download either `caravan-day19.zip` or `caravan-day19.tar.gz`, extract, then follow [INSTALL.md](https://github.com/linuxbren/caravan/blob/day19-2026-11-08/INSTALL.md). For the native Mac installer and optional per-user auto-start follow [docs/SERVICES.md](https://github.com/linuxbren/caravan/blob/day19-2026-11-08/docs/SERVICES.md). Review installer dry-run first; weights, Python dependencies and compiled runtimes are not bundled. Source packages are not signed installers. Existing clones: clean tracked tree, then `git pull --ff-only`; docs-only pulls need no restart. Preserve unrelated local files.

## Checks and limits
**738 tests passed in 42.600 s**, zero failures/skips (`PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`). Full results are recorded in docs/DAY19.md. 5/5 SSH paths, 16/16 mocked guard and 3/3 fallback cases passed. **Restore-last-model reboot test: pending, deferred to the next dev day.** No reboots in this closeout. Earlier fixed-model launchd reboot results do not prove revised last-model replay. Separate-account/FileVault-on install, three physical Minis, N-stage Optimize, true GGUF independence and sustained performance remain open. User-session recovery cannot run before login. No Day 19 video or X draft now.
