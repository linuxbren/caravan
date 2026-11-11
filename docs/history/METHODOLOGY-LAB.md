# Historical development record

These notes describe an earlier test environment, not installation defaults.
For current instructions use the [documentation index](../README.md).
Older machine names are explained there.

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

### Auto-pick when flags are omitted (ROADMAP #13a)

Omit `--split-packer-layers` and/or `--split-pipeline-chats` to let the worker
choose. Explicit flags (and matching env) still win.

- **Layer cut:** packer reports `mem_total_gb` in the hello; the lead compares
  that to its own memory and the model's layer count / type
  (`choose_packer_layers`). Equal-RAM 24 GB Minis get the idea-5 balanced
  cuts (Gemma 16, GPT-OSS 13, Qwen3/Qwen2.5 24, Llama 16). Log line:
  `auto split: packer_layers=K (reason)`.
- **Pipeline chats:** from this side's free memory vs loaded weights
  (`choose_pipeline_chats`). Caps at **2** (Mini benches: N=3 wall ≈ N=2 for
  every family); never auto-picks 3; stays at 1 when headroom is tight so
  KV never risks swap. Log line: `auto pipeline: chats=N (reason)`.

For A/B vs hand-tuned, restart both roles with the same flags pinned; compare
medians of ≥2 under this methodology (ports 8194/5560, LPM off, warm-up,
quality 3/3).

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


## Guesser family map

`agent/guessers.json` maps popular open LLM families to a small same-vocabulary
draft. Pairings win over `no_pairing` skips (so Distill-Qwen is not swallowed
by a native DeepSeek-R1 skip).

| Family | Guesser (MLX 4-bit) | Size | Status |
|---|---|---:|---|
| Qwen3 | Qwen3-0.6B-4bit | 335 MB | **Mini-verified** (Nov 1; 45.9→59.7) |
| Gemma 4 | gemma-3-270m-it-4bit | 181 MB | **Mini-verified** (Nov 1; 38.4→44.5; remap) |
| Llama 3.x | Llama-3.2-1B-Instruct-4bit | 663 MB | **Mini-verified** (Nov 1; 22.7→51.5 count) |
| Qwen2.5 | Qwen2.5-0.5B-Instruct-4bit | 278 MB | **Mini-verified** (Nov 1; 12.4→33.8 count) |
| Gemma 3 | gemma-3-270m-it-4bit | 181 MB | vocab-checked (exact) |
| Gemma 2 | gemma-2-2b-it-4bit | 1403 MB | vocab-checked (exact; large draft) |
| DeepSeek-R1-Distill-Qwen | Qwen2.5-0.5B-Instruct-4bit | 278 MB | **Mini-verified** (Nov 1; 12.3→16.9 count) |
| SmolLM (1.7B) | SmolLM-360M-Instruct-4bit | 204 MB | vocab-checked (exact) |
| GPT-OSS | — | — | **skip** (no small o200k draft) |
| Mistral / Mixtral (v0.3 SPM) | — | — | **skip** (no small same-vocab draft) |
| Phi-4 / Phi-4-mini | — | — | **skip** (tokenizers diverge; no small draft) |
| DeepSeek-V3 / native R1 | — | — | **skip** (Distill-Qwen is separate) |

**Mini-verified** means the lead ran the first-load quality+speed gate on the
Minis. **vocab-checked** means published HF `tokenizer.json` files match
(exact or compatible specials remap) but the pair has not yet been gated on
EXO1. Sizes are the helper download prompt values (`size_mb` in the table).

## Download prompt (live check)

Nov 1 on EXO1 test ports (8194/5560), Qwen3 main, PTY yes/no: size prompt
("A 335 MB helper…"), yes → download + guess-ahead keep (gate baseline 36.98 /
spec 40.71 tok/s, quality keep), remembered yes on next load (auto-pair, no
prompt); no → baseline and remembered no. Original HF cache / drafts / state
restored afterward (no production stop). Raw:
`~/.caravan/bench-2026-11-01/guess-ahead-download-test/`.

Llama 3.1 8B (same ports, draft moved aside): size prompt
("A 663 MB helper… Download Llama-3.2-1B-Instruct-4bit?"), yes → download +
draft wired; remembered `llama3: true`. Draft restored from `.bak` after the
check. Raw: `~/.caravan/bench-2026-11-01/llama-suite/dl-prompt.log`.

## Stop when done

Kill the test packer/lead processes. Leave production workers alone.

Qwen2.5 14B and DeepSeek-R1-Distill-Qwen 14B (same ports, draft moved aside):
size prompt ("A 278 MB helper… Download Qwen2.5-0.5B-Instruct-4bit?"), yes →
download + draft wired; remembered `qwen25` / `deepseek-r1-distill-qwen`.
Draft restored from `.bak` after each check. Raw:
`~/.caravan/bench-2026-11-01/qwen25-suite/dl-prompt.log` and
`distill-suite/dl-prompt.log`.
