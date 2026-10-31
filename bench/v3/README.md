# v3 bench: one Mac vs one MLX model split across two

`split_client.py` produced the Oct 31 numbers in
[docs/BENCHMARKS.md](../../docs/BENCHMARKS.md#v21-vs-v3-one-mac-vs-two-macs-oct-31-mlx)
(v2.1 on one Mac vs v3 split across two, and the 8-bit "bigger
brothers"). It talks straight to an MLX worker, either a v2.1 worker on
one Mac or the v3 lead, with an `X-Caravan-Session` header, so both take
the same path. The proxy isn't in the loop (the proxy path was
smoke-tested separately).

```sh
python3 split_client.py bench  URL MODEL OUT.json [no_think]   # warm-up, writing x2, reading 512 x2 and 4k x2, quality 3/3
python3 split_client.py chat   URL MODEL OUT.json TOKENS TAG   # turns 1 and 2 of a TOKENS-long chat (state kept next to OUT)
python3 split_client.py resume URL MODEL OUT.json TAG          # turn 3, after you restart the worker(s)
```

- `URL` is the worker, for example `http://127.0.0.1:8194` for a test
  lead. Use test ports, not the production ones.
- Each request appends one JSON line to `OUT.jsonl` with reading and
  writing speed, time to first word, peak memory and, on the split, the
  per-request link cost (`usage.caravan.split`).
- Prompts, filler text and scoring are shared with
  `bench/improvements/common.py`.
- `/no_think` is added only for Qwen3 30B (Qwen3.6 has no such switch).
  The quality checks allow 200 reply tokens for Qwen3 30B and 1,536 for
  the others, because Gemma 4 and GPT-OSS think before answering.

Start the workers yourself (packer first, then the lead; see
[docs/MLX-SPLIT.md](../../docs/MLX-SPLIT.md#running-it)) and stop them
afterwards. The script starts and stops nothing.

Before you run it, check that **Low Power Mode is off on both Macs**
(`pmset -g | grep lowpowermode` should print `0`). The first v3 numbers
were taken with it on for the packer; turning it off made reading
16–30% faster. See the rerun in
[docs/BENCHMARKS.md](../../docs/BENCHMARKS.md#v3-rerun-with-low-power-mode-off-oct-31-mlx-v31).
