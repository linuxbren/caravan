# Day 23 (Nov 11 2026)

Published Nov 11 CST; development-day tag `day23-2026-11-11`.

## Changed
- Official llama.cpp engine on every Mac install and update, complete
  multi-part downloads, and clearer status, doctor, PATH, and uninstall.
- Add a Mac from Topology and from the placement screen.
- Opt-in access from other devices over Tailscale, off by default.
- `caravan update` is a single step: it restarts what is needed, leaves a
  loaded model running when model-running code did not change, and on
  failure restores the previous version.
- `caravan start` says "Caravan started" or "Caravan is running",
  whichever is true.

## Operational checks
- Live testing on both Minis passed: update, remote access from another
  device, one-Mac and split MLX and GGUF downloads, Add a Mac from
  placement, reboot, and uninstall then reinstall.
- 1,240 tests passed in 52.988 s.

Details: docs/DAY23.md.
