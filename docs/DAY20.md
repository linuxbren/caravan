# Day 20 — Hermes full-power cache reuse (2026-11-09)

## Request and constraints
Keep Hermes's complete configured toolset and the selected Huihui Qwen3.5-27B
Opus abliterated 4-bit model, EXO2/EXO1 24/40. No reboots, cloud agents, posts,
or copying repo files to Minis. Minimize disruption while Brenden chats.

## Evidence / root cause
- Lead log: full request 13,192 tokens, zero cached, prefill 207.87 s
  (63.5 tok/s), model first token 208.17 s, total 217.45 s; decode 6.14 tok/s.
- Immediately afterward, Hermes's auxiliary title request reused the SAME
  session fingerprint `0841948625322810`, but changed the system prompt.
  Divergence at token 4 forced a full reset (hybrid recurrent state cannot
  arbitrarily rewind). The 254-token title request then took 44.96 s, including
  262 reasoning tokens, before overwriting that conversation checkpoint.
- Two isolated real Hermes wire captures (mock inference, NOT speed results)
  have 21 enabled tools; system and tools are byte-identical on the resumed
  second turn. Bodies 55,848 / 55,990 bytes. The daily date is pinned per
  conversation near the tail; no timestamp change between these turns.
- Old proxy key was only the first user message. Hermes titling repeats that
  user message, so it collided with the full-tool main turn.

## Implementation
- MLX-only session namespace includes system/developer messages, tools, model,
  template options and thinking mode, without including growing history.
  llama.cpp's existing slot fingerprint remains unchanged.
- Capture an exact pre-user system/tool checkpoint during the first prefill,
  rather than trying to trim recurrent state backward or re-prefilling the
  prefix a second time. Clone that checkpoint for new chats or a diverged
  session. Existing longer per-session LCP checkpoints still win.
- Exact boundary comes from the real tokenizer/chat template, including tools
  in their original order; no text or schemas are removed or normalized away.
- Each Mini retains its own bounded in-memory prefix and durable safetensors
  cache. Existing model/tokenizer/layout metadata and cross-stage token digest
  checks reject stale/missing halves; N-stage clone checks fail closed.
- Prefix cloning now includes checkpoint snapshots so its disk save is real,
  not the previous `empty` result. Works in serial and pipeline prefills.
- Managed `--kind proxy` launchd plan: loopback port 8090 -> MLX 8194,
  RunAtLoad + KeepAlive. No model pin, downloads, public listener or reboot.
  Cleanup disabled, preserving the previous manual proxy's no-delete policy.

## Verification
New tests exercise stable/changed wire inputs, title isolation, template
boundaries, chunk cuts, wrapped recurrent state, 1/2/3/5 stages, disk recovery,
missing-stage rejection, clone failure and launchd plans. Live deployment and
measurements are recorded below when completed; no speedup is claimed yet.

Hermes title calls explicitly send `reasoning_effort: none`; the MLX worker
now honors that as thinking off unless `thinking` is explicitly supplied.
Main Hermes `medium` reasoning remains unchanged. Previously the ignored
opt-out let short titles consume hundreds of hidden reasoning tokens.

Exact native tokenizer counts for the two captured full-tool requests:
13,204 / 13,230 tokens, longest common prefix **13,202 tokens**. The system
message is 14,922 UTF-8 bytes in each; all 21 tools and their serialized bytes
match exactly. Capture hashes: system `dc45797332eef77786e27a38ea4957ac147ffcf2c069eb1b179ac20ab4ff5f72`,
tools `9b92b2523ae7e3224464eacc23dec1548dd4ed6cd8e6c0f24c4f2d3acc9df0c3`.

A loopback-only `/caravan/proxy/status` reports FIFO active/waiting counts
without queuing a model request or revealing prompts. The diagnostic relay
uses it to decline a benchmark while busy and cancel if another request queues.

Regression gate: `PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`:
**764 tests passed in 42.600 s**, up from 738. Compile and whitespace checks pass.
