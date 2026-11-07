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

**CLI agent (`caravan_agent.py`, packer role).** `supervisor.build_tail_command`
no longer uses 0.0.0.0. It runs `agent/rpc_gate.py`: rpc-server on
127.0.0.1:50053 and a small stdlib gate on this Mini's Thunderbolt address
(first 169.254.x.x, or `CARAVAN_RPC_BIND` with a warning) port 50052 that
accepts only IPs in `CARAVAN_RPC_ALLOW` (comma list of peer addresses) and
closes everything else. It fails closed: no link address, an empty allowlist,
or 0.0.0.0 → refuses to start with a clear error. Unit-tested (allow/refuse
end to end on loopback); a full live CLI split through the gate was **not**
re-run tonight. Moving the CLI to the SSH-tunnel design is the simpler next
step.

Not changed: llama.cpp stays at b10819 on both Minis (matched upgrade later).
