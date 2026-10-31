# Cable timing: how long one exchange over the Thunderbolt cable takes

`cable_timing.py` is the "first test, before building anything" for
idea 4 in [docs/ROADMAP.md](../../docs/ROADMAP.md#beating-the-turn-taking-in-the-split)
(split each layer across both Minis). That idea needs two exchanges
between the Minis per layer, so the time of one small round trip decides
whether it can pay off. No models are loaded; it only sends bytes.

It times a round trip (send N bytes, get N bytes back) two ways:

- **caravan**: Caravan's own split link. Same framing
  (`encode_frame` / `read_frame`), same client (`FrontClient`, TCP_NODELAY)
  and same server loop (`serve_front`) as the v3 lead and packer, with a
  stand-in state that echoes the bytes.
- **raw**: plain TCP with TCP_NODELAY and an 8-byte length, no JSON
  header. Shows what Caravan's framing costs on top.

Sizes: each model's per-layer exchange, `hidden_size × batch × 2` bytes
(bf16) for batch 1, 4 and 16 (Qwen3 30B-A3B 2,048 × 48 layers, Gemma 4
26B-A4B 2,816 × 30, GPT-OSS 20B 2,880 × 24, read from each model's
`config.json`), plus 1 KB to 1 MB. Each size: 100 warm-up round trips,
then `--repeats` timed ones (default 2,000; 200 for 1 MB). It prints the
median, 95th and 99th percentile, a one-way bulk speed (1 MiB frames),
and writes the cable cost per token (`layers × 2 × round trip`) to the
JSON.

`--gpu-sync` (needs MLX on both Macs, so use the MLX venv): before each
send, each side turns the bytes into an MLX array and waits for one tiny
GPU op. The two waits happen one after the other, not at the same time,
so this is a pessimistic upper bound for a real exchange.

```sh
# on the packer (EXO2), test port, not 5560; the raw server uses port+1
~/.caravan/venvs/mlx/bin/python bench/cable/cable_timing.py serve --listen <EXO2 Thunderbolt IP>:5570 [--gpu-sync]
# on the lead (EXO1)
~/.caravan/venvs/mlx/bin/python bench/cable/cable_timing.py run --peer <EXO2 Thunderbolt IP>:5570 [--gpu-sync] --json out.json
```

Stop the server afterwards (Ctrl-C, or `pkill -f "cable_timing.py serve"`).
Find the Thunderbolt address with `ifconfig | grep 169.254` and check
the route with `route -n get <IP>` (it should say the Thunderbolt port,
`en2` on EXO1).

Results from Oct 31, 2026 are in `results/` and in
[docs/BENCHMARKS.md](../../docs/BENCHMARKS.md#cable-timing-oct-31-thunderbolt-4).
