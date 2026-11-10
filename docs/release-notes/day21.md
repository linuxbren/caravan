# Day 21 (Nov 10 2026)

Published Nov 10 CST; development-day tag `day21-2026-11-10`.

## Changed
- Clearer Topology Balance: Auto by default, one memory bar per Mini, Adjust
  reveals N−1 layer-boundary sliders, live preview, explicit Apply and Back
  to auto. Model/shard jargon stays behind Details. Preview, Adjust and Back
  to auto do not download or reload anything.
- Apply is solid black only for a ready actual change, and gray when the
  change is a no-op, unsafe/stale, or the model is reloading. Plain-language
  reload banners, per-Mini steps, and chat/Enter locked until a healthy new
  PID/model/split/KV is confirmed. Active KV is retained across reload.
- Trusted Thunderbolt inventory and a source-routed candidate graph, plus
  explicit bounded link checks from every actual source. Kernel-bound private
  TCP 22 and strict existing SSH host-key/nonce/hostname/endpoint proof.
  Per-edge verified/unverified/failed states, with latency scope, expire after
  30s. No MLX socket is probed.
- Opt-in N-Mini peer/listen/upstream suggestion, preview only. It preserves
  order and ports, requires fresh directed identity proof including
  lead-to-every-packer reachability, and fails closed without Wi-Fi/Tailscale
  fallback. There is no apply endpoint and no automatic routing rewrite.
- GGUF no-capacity presentation is unchanged; actual applied shares are
  exposed for reload/no-change comparison. Independent GGUF splitting remains
  Day 22 work.

## Operational checks
- Two physical M4 Minis. Ordinary switch/unload/restore: Huihui 24/40 → Orvena
  9.173s, Orvena reply 0.369s, unload 1.782s, restore Huihui 9.016s. One
  controller-slug/proxy-ID mistake returned 502 and is recorded, not counted
  as success.
- One UI Apply restored a user 27/37 split back to Huihui 24/40 KV16: backend
  Ready in 8.82s, chat usable in 12.93s including polling.
- Live Thunderbolt readout: EXO1→EXO2 en2 verified (TCP 0.279ms, SSH hello
  158.980ms). Reverse TCP reachable in 0.712ms, but SSH identity remains
  unverified; no keys were enrolled and no weaker route was tried. The opt-in
  preview matched the current two-Mini peer and applied nothing.
- Physical auxiliary title-worker reboot check, November 10 17:17–17:20 CST.
  Brenden issued the documented EXO2-then-EXO1 reboots from Omarchy. EXO1
  auto-logged in. **EXO2 did not actually reboot** (last boot November 9
  20:07 CST); its packer was relaunched at 17:17:59 as part of EXO1 restore.
  This is not a dual-machine cold start. Day 20 already proved two-Mini
  main-model restore.
- EXO1 boot 17:17:30.876 CST → Huihui 24/40 KV16 ready at 17:18:08 (37.3s;
  worker load 4.9s). Aux waited for primary health and RAM (budget 0.9GB +
  reserve 1.75GB), then listened at 17:18:18 (~47.1s), health 200, launchd
  once with no exit. Title through :18090: HTTP 200, `X-Caravan-Aux:
  title-sidecar`, finish stop, 0.135s wall. Full 19-tool medium Hermes replay
  through :18090: HTTP 200, finish stop, visible answer “I'm online and ready
  to help.”, 11.504s wall, 0.421s TTFT, 6.2 tok/s, 11310 prompt tokens.
  Saved Huihui 24/40 KV16, EXO2→EXO1, confirmed after the probes. Evidence
  remains on Omarchy at `~/day21-checks/reboot/`. Private request bodies are
  not in the repo.
- Two-Mini physical reboot, November 10 17:29–17:32 CST. Brenden rebooted
  EXO2 directly, then EXO1. EXO2 **did reboot** (kern.boottime 17:30:10 CST;
  previous boot was November 9 20:07). Automatic Huihui 24/40 KV16 restore
  **failed**. Restore blocked at 17:30:36 because Thunderbolt en2 did not yet
  have one unambiguous IPv4, and that error is not in the pre-worker retry
  list. By 17:31:04 both en2 links had a single new link-local address
  (EXO1 169.254.217.10, EXO2 169.254.125.22). Aux never reached health 200
  (it correctly waited for the primary). Title and the full 19-tool Hermes
  replay through :18090 both returned HTTP 502 (`mlx_lm.server upstream
  unreachable`) with no `X-Caravan-Aux` header. last-model preference was
  preserved, not loaded. No Load, restart or further reboot was issued.
  Evidence: Omarchy `~/day21-checks/reboot2/`. The earlier 17:17 EXO1-only
  aux check still stands; this two-Mini cold start did not auto-restore.

## Install
Download either `caravan-day21.zip` or `caravan-day21.tar.gz`, extract, then
follow [INSTALL.md](https://github.com/linuxbren/caravan/blob/day21-2026-11-10/INSTALL.md).
For the native Mac installer and optional per-user auto-start follow
[docs/SERVICES.md](https://github.com/linuxbren/caravan/blob/day21-2026-11-10/docs/SERVICES.md).
Review an installer dry-run first; weights, Python dependencies and compiled
runtimes are not bundled. Source packages are not signed installers. Existing
clones: clean tracked tree, then `git pull --ff-only`. Docs-only pulls need
no restart. Preserve unrelated local files. If only the web service must
restart, use `CARAVAN_WEB_KEEP_WORKERS=1`.

## Checks and limits
**907 tests passed in 45.871 s**, zero failures/skips
(`PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`). Full
results are in [DAY21.md](https://github.com/linuxbren/caravan/blob/day21-2026-11-10/docs/DAY21.md)
and [BENCHMARKS.md](https://github.com/linuxbren/caravan/blob/day21-2026-11-10/docs/BENCHMARKS.md).
Verified SSH/TCP 22 is not MLX service authentication, throughput, or
direct-cable adjacency proof. Two Minis do not prove physical N-Mini scaling,
arbitrary bridges, cable unplug, or automatic path application. Concrete
preview IPs do not replace reboot-safe `tb://` configuration. The Day 21
video is handled separately and is not part of this tag.
