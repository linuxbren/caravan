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

A second observed failure mode (18:17:50 CT): same-session prompt diverged at
13,223 of 13,224 cached tokens, and the hybrid cache again reread from scratch.
Even a one-token template/history-tail change cannot rewind recurrent state.
The exact pre-user checkpoint also addresses this case: discard the unsafe
conversation tail and seed its unchanged system/tool prefix, rather than paying
another full ~13k-token prefill. Namespace isolation alone would not solve it.

## Deployment
Both Minis clean tracked trees pulled `6efecbf` with `git pull --ff-only`;
existing `proxy/web/index.html.bak-pre-amber` untracked backups were preserved.
Waited for Brenden's inference to finish. At 18:23 CT, normal web Stop +
Balance load restored the **same Huihui 24/40 split** in **14.607 s**, including
1.829 s Stop. No web restart, model substitution, file download or machine reboot.
Migrated only the verified idle manual proxy into `com.caravan.v3.proxy`;
port 8090 remains loopback-only.

Extra regression cases reproduce a one-token tail divergence, a changed
system/tool prefix, and wrapped recurrent state on three stages. Final suite:
**767 tests passed in 43.446 s** (29 new); no MLX hardware claimed for fake
N-stage tests.

## Live full-tool Hermes results (2026-11-09, CT)

Same Huihui 27B 4-bit model and EXO2/EXO1 24/40 split; all **21 configured
Hermes tools** retained. Main reasoning stays `medium`. A diagnostic-only
relay bounded these synthetic replies to 160 generated tokens; none hit the
cap, no tool was removed, and no user config was changed. Each prompt asked
for READY without executing tools. The benchmark yielded automatically if
another request queued (no contention/cancellation occurred in this run).

| Turn | Prompt | Cached | Prefill s | Model TTFT s | First visible Hermes text s | Write tok/s |
|---|---:|---:|---:|---:|---:|---:|
| Cold first | 13,206 | 0 | 212.553 | 212.856 | 223.570 | 6.14 |
| Follow-up 1 | 13,229 | 13,182 | 1.174 | 1.473 | 11.572 | 6.14 |
| Follow-up 2 | 13,253 | 13,182 | 1.728 | 2.027 | 9.229 | 6.10 |
| Follow-up 3 | 13,276 | 13,182 | 1.760 | 2.058 | 9.778 | 6.09 |
| Independent new chat | 13,206 | 13,182 | 0.683 | 0.982 | 13.554 | 6.17 |

Model TTFT is the worker's first generated token (including hidden reasoning).
Visible Hermes time includes CLI startup, the loopback relay/SSH tunnel and
hidden reasoning before READY. Wire-only visible times were 222.939,
11.025, 8.686, 9.255 and 12.850 s respectively. No assertion that all workloads
will answer in ten seconds: real tool execution, longer histories, memory
changes, reasoning and model output remain additional work.

Before the fix, a comparable full request was 13,192/0 cached, **207.87 s
prefill**, 208.17 s model TTFT and 217.45 s total. A true cold prefill still
costs roughly the same (~62–64 tok/s). The improvement is keeping 13,182
system/tool tokens instead of rereading them: warm prefill now **0.68–1.76 s**,
with full reasoning/tools left on. The three resumed turns genuinely hit
`agent-prefix-hit-memory` after one-token template-tail divergence, not merely
a favorable exact-history append. Independent new chat proved cross-session
reuse, too.

The auxiliary title has a distinct fingerprint and now honors
`reasoning_effort:none`: measured **272 prompt / 11 generated / 0 reasoning**,
6.24 s model total (6.49 s relay wall), versus a previous 254-prompt /
271-generated, mostly-reasoning title at 44.96 s. Title generation still
happens; it is not disabled to manufacture these results. The first diagnostic
CLI returned fully after its title at 230.38 s; subsequent CLI totals were
11.85, 9.50 and 10.05 s. New chat CLI total including its title was 20.30 s.

Real prefix files (same token key, own tensors on each Mini):
- EXO1: `agent_p13182_4d50f8b37ae3529f.safetensors`, **636,238,790 bytes**.
- EXO2: same basename, **381,772,715 bytes**.

Persistence after eviction/restart and missing-stage fail-closed behavior are
unit-tested; real files and successful saves are verified. No extra live
worker restart or machine reboot was done just to demonstrate disk restore.
A different/changed system block must be read once to seed its own checkpoint.

Evidence stays private on Omarchy under `~/.hermes/caravan-bench/`:
`live-metrics.json`, `live-turn1.log` through `live-turn4.log`,
`newchat-metrics.json`, wire captures and diagnostic scripts. Synthetic capture
responses were mocked only for byte-stability diagnosis; all timings in this
table came from real Caravan inference. Deployment evidence on EXO1 is under
`~/.caravan/day20-hermes/`; live worker log `~/.caravan/web-ui/lead.log`.
