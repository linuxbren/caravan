# GPU keepalive (Apple Metal cool-down) — already shipped

Joshua S. Warren / “Apple kernel” angle: Caravan already warms Metal on the lead
while blocked on the packer (`GpuKeepalive` in `agent/mlx_split.py`, default **on**
since Oct 31: `--split-keepalive` / `--no-split-keepalive`).

Prior A/B (BENCHMARKS + experiments Oct 31 / Day 7): writing rose ~28–50% vs
keepalive off on split models. No new Day 12 A/B; Idea 1/2/4 ran with keepalive
on. Deeper Apple-kernel / custom Metal fused matmul remains the parked #17
follow-up (oMLX-style), not a one-line tweak.
