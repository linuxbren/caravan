# Day21 — DRAFT release notes (NOT RELEASED / NOT TAGGED)

**Release hold:** Brenden's physical auxiliary title-worker reboot check on
**November10,2026, around5–6pm CST**. No reboot or release/tag has been issued
by this work. Do not turn manual service health checks into reboot proof.

## Highlights

- Clearer Balance: Auto by default, one memory bar per Mini, Adjust reveals
  N−1 layer-boundary sliders, live preview, explicit Apply and Back to auto;
  model/shard jargon remains behind Details. Existing preview/load APIs reused.
- Apply is solid black only for a ready actual change; gray/disabled for no-op,
  unsafe/stale preview or reload. Obvious plain-language reload banners,
  stopping/per-Mini/ready steps, chat/Enter and controls locked until confirmed
  healthy new PID/model/split/KV; clear success or error. Active KV is retained.
- Trusted TB inventory and candidate graph, plus explicit bounded link
  validation from every actual source. Kernel-bound private TCP22 + strict
  existing SSH host-key/nonce/hostname/endpoint proof. Per-edge states and
  latency scope/freshness are visible in API/UI. No MLX socket is probed.
- Opt-in N-Mini peer/listen/upstream suggestion, PREVIEW ONLY. Preserves order
  and ports; requires fresh directed identity proof, including the current
  runtime's lead-to-every-packer preflight requirement. Fails closed without
  Wi-Fi/Tailscale fallback. No apply endpoint, routing rewrite or new service.
- GGUF no-capacity presentation preserved; actual applied shares exposed for
  reload/no-change comparison. This is not Day22 independent GGUF splitting.

## Operational checks and scope

- Two physical M4 Minis only. Ordinary model switch/unload/restore checked;
  Huihui24/40 KV16 restored and saved. See DAY21 for timings and the initial
  controller-slug/proxy-ID mistake (not hidden or counted as reply success).
- Apply flow recorded ready/reloading/done:8.82s backend Ready/saved and12.93s
  to completed UI/chat usable, including polling. The actual19-tool medium
  request through Hermes18090 returned HTTP200, visible content and finishstop.
- Full regression and live TB readout details are in DAY21/BENCHMARKS and
  `handoff/lab/day21/`. Private request bodies are not part of the release.
- Deployment uses ff-only pulls and keep-workers web-only restart; no cloud
  agents, reboot, automatic route application or forced Git update.

**Limits:** verified SSH/TCP22 is not MLX service authentication, throughput or
direct-cable adjacency proof. Existing model transports are unchanged.
N-Mini algorithm fixtures are not physical3+ Mini scaling evidence. Cable
unplug/replug, mixed bridges and reboot/address changes were not tested here.
Concrete preview IPs do not replace reboot-safe tb:// configuration.

## Required before tagging

Run the exact observer/reboot recipe in [DAY21](../DAY21.md#auxiliary-title-worker-physical-reboot-check--brenden-runs-this).
Brenden issues the reboots and unlocks/logs into both Macs when required.

1. Confirm saved Huihui24/40 KV16; start the Omarchy observer before reboot.
2. Record main model recovery and aux recovery separately, including any
   manual unlock/login; require the aux primary-health/RAM-gate logs from
   THIS boot, not old history.
3. Confirm title response HTTP200, `X-Caravan-Aux: title-sidecar`, relevant
   valid title JSON; a main-model fallback alone is NOT an aux pass.
4. Replay the existing full19-tool, medium-effort payload through18090;
   inspect actual returned JSON for visible content/finishstop (not just the
   probe's process exit). Reconfirm loaded and saved24/40 KV16.
5. If anything fails, keep logs and leave this release draft/untagged. If all
   passes, append exact reboot evidence and obtain Brenden's release go-ahead
   before publishing/tagging. Nothing is automatically scheduled.
