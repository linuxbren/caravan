# Day 12 #16 — built-in guesser / MTP research

## Probe (EXO1 MLX copies, 2026-11-03)

All local MLX 4-bit copies: **NO_MTP_IN_MLX_COPY** (no config MTP fields, no `mtp*` / `eagle*` / `draft_head*` weight keys).

| Model | Verdict |
|---|---|
| Qwen3-30B-A3B-4bit | NO_MTP |
| gemma-4-26b-a4b-it-4bit | NO_MTP |
| gpt-oss-20b-MXFP4-Q8 | NO_MTP |
| Meta-Llama-3.1-8B-Instruct-4bit | NO_MTP |
| DeepSeek-R1-Distill-Qwen-14B-4bit | NO_MTP (distill; not V3 MTP) |
| Qwen2.5-14B-Instruct-4bit | NO_MTP |

Raw: `~/.caravan/bench-2026-11-03/day12-speedups/mtp-research.json` on EXO1.

## Upstream reality

- **Qwen3-30B-A3B** (original) was **not** MTP-trained; 48 MoE layers, no MTP heads in the HF release / tech report.
- **Qwen3-Next** (e.g. 80B-A3B) **does** ship native MTP / NEXTN speculative decoding — different architecture (Gated DeltaNet hybrid). Not in our model set tonight.
- **GPT-OSS 20B**: no small same-family draft on mlx-community; MLX copy has no MTP tensors. Baseline writing ~34.0–34.3 tok/s with no helper path.
- **DeepSeek-style MTP**: lives on DeepSeek-V3-class checkpoints, not on the R1-Distill-Qwen we have.

## Feasibility tonight

**Not feasible as a same-evening prototype.** Cheap restore needs (1) MTP tensors on disk, (2) matching hidden/vocab with the MLX target, (3) attach-as-draft in the guess-ahead path. We have (1)=none for every model we run. Getting there means downloading a Qwen3-Next (or similar) MLX build that keeps NEXTN/MTP, or extracting MTP-only tensors from an original BF16 that actually has them — medium overnight job, not a flag flip.

## What to do instead for GPT-OSS

Keep helper-draft shut-off; track Qwen3-Next / future mlx-community MTP quants as the #16 unlock. Roadmap: leave #16 open, blocked on model availability.
