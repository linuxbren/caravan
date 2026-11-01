# Bench methodology (MLX split)

How we measure write speed on the two-Mini Thunderbolt split so numbers stay
comparable. Idea 3 guess-ahead and other split benches follow this.

## Machines and ports

- **EXO1** = lead (serves HTTP). **EXO2** = Packer 1.
- Thunderbolt packer address: `169.254.104.38:5560`.
- Lead test port: **8194** (never the production 8092 during benches).
- Low Power Mode **off** on both Minis (`pmset -g lowpowermode` → `0`).
- Keepalive **on** unless the run is explicitly testing `--no-split-keepalive`.

## Sync before a run

1. Commit (or at least save) the code under test on Omarchy
   `~/Projects/caravan` (branch `caravan-v3-mlx-split`).
2. Sync that tree to:
   - box: `/workspace/caravan`
   - EXO1: `~/dev/caravan-v3`
   - EXO2: `~/cv3`
3. Confirm tip SHAs match. Do **not** push or tag unless Brenden asked.

## Start packer, then lead

Packer first (EXO2), then lead (EXO1). Same `--split-packer-layers` on both
(even cuts for idea 3). Example for Qwen 4-bit:

```sh
# EXO2 packer
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py \
  --model ~/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit \
  --split-role packer --split-listen 169.254.104.38:5560 \
  --split-packer-layers 24 --host 127.0.0.1 --port 8195

# EXO1 lead (auto-pair picks the guesser when present)
~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py \
  --model ~/.caravan/mlx-models/mlx-community--Qwen3-30B-A3B-4bit \
  --split-role lead --split-peer 169.254.104.38:5560 \
  --split-packer-layers 24 --host 127.0.0.1 --port 8194
```

`--no-split-draft` forces baseline. `--split-draft-model PATH` overrides the
pairing table. `--split-draft-skip-first-load` skips the one-time gate when
you already trust the pair (or are measuring something else).

## Warm-up

The worker runs a short Metal warm-up at load. After `/health` is up, send one
throwaway completion (or use `speculate_bench.py`, which warms itself) before
recording timed runs.

## Quality gate

Three fixed prompts (2+2, capital of France, ice cream hot/cold). Expect
**3/3**. Matching uses `guess_ahead.answer_ok`: strip think/channel
blocks (Qwen `</think>`, GPT-OSS `<|channel|>…`, Gemma-4
`<|channel>thought…<channel|>ANSWER<turn|>`) and score only the **final
answer** (last line / last sentence, whole-word). Thought-only output
fails. Idea 3 also runs these once per model+guesser on first load
(max 256 tokens) and caches under `~/.caravan/mlx/guess-ahead-state.json`.

## Speed runs by prompt type

Client: `bench/v3/speculate_bench.py URL MODEL OUT.json [tag] [mode]`.

| mode | what |
|---|---|
| `standard` | warm + count/tg128 ×2 + quality 3/3 |
| `suite` | also edit / code / repetitive (prompt-lookup-friendly) prompts |

Report **write tok/s** from `usage.caravan` (`(completion_tokens - 1) /
(total_s - ttft_s)`). Never invent numbers.

## Same-session baseline

For idea 3 A/B, baseline and speculative runs use the same lead process when
possible (toggle draft via restart with `--no-split-draft`, or trust the
first-load A/B). Prefer restarting the lead between baseline and speculative
full benches so KV/cache state does not leak across modes; keep packer up.

## k sweep

When exploring a new draft, sweep `--split-speculate-k` (1..8). Ship the k
from `agent/guessers.json` that won on the Minis. Auto-pair uses that k
unless `--split-speculate-k` / env set it explicitly.

## Medians

Medians of **at least 2** timed runs (tg128). Say so in the table. Raw JSON
lives on EXO1 under `~/.caravan/bench-YYYY-MM-DD/` (or the path passed as
`OUT.json`). Copy summaries into `docs/BENCHMARKS.md` and `docs/LOG.md`.

## Stop when done

Kill the test packer/lead processes. Leave production workers alone.
