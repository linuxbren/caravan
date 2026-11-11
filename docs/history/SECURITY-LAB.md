# Historical development record

These notes describe an earlier test environment, not installation defaults.
For current instructions use the [documentation index](../README.md).
Older machine names are explained there.

# Security

## llama.cpp rpc-server (GGUF split) — Day 17, Nov 6 2026

`ggml-rpc-server` has no authentication; llama.cpp says never expose it to an
open network. Found in a check: `agent/supervisor.py` started it with
`-H 0.0.0.0` on 50052. llama-server (8080) and MLX workers already bound
127.0.0.1.

**Web UI split (what runs today).** On every peer Mini rpc-server binds
**127.0.0.1:50052 only**. The lead reaches it through an SSH local forward
(`ssh -N -L 127.0.0.1:5006i:127.0.0.1:50052 <peer>`, BatchMode, aes128-gcm).
So the allowlist is SSH itself: only machines holding Caravan's key — the
topology Minis — can talk to it, and the traffic is encrypted. No open port,
no sudo, no pf, works for any number of Minis.

Verified Nov 6, 11:30 PM CT, with the split loaded and serving:
- EXO2 `lsof`: `ggml-rpc-server … TCP 127.0.0.1:50052 (LISTEN)` — nothing else.
- From Omarchy (not a peer) to EXO2's LAN 192.168.1.38:50052 and Tailscale
  100.90.134.95:50052: **Connection refused**.
- From EXO1 to EXO2's Thunderbolt 169.254.103.191:50052 and LAN: refused.
- Split still ran: 34.7 tok/s write (DAY17-BENCHMARKS.md).

**CLI agent (`caravan_agent.py`, `agent/gguf_split_cli.py`).** Same design as
the web UI, one mechanism: the packer runs rpc-server on `127.0.0.1:50052`
only (`supervisor.build_tail_command`), and the lead opens SSH tunnels
`127.0.0.1:5006i → peer 127.0.0.1:50052` (`CARAVAN_RPC_SSH_USER`). The old
`agent/rpc_gate.py` allowlist gate was removed (Nov 6, afcf070): SSH keys are
the allowlist, and nothing listens on a network address. Live CLI split
Nov 6 ~23:40 CT: ready 13.0 s, Write 34.30 / 34.49 / 34.66 tok/s, split
20.0:16.1 from free RAM; Stop left 0 processes on both Minis. Non-peer checks
re-run after: EXO1 → EXO2 Thunderbolt/LAN :50052 refused; Omarchy → EXO2
LAN/Tailscale/Thunderbolt :50052 refused; EXO2 `lsof` shows 127.0.0.1 only.

Not changed: llama.cpp stays at b10819 on both Minis (matched upgrade later).
