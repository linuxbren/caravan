# Historical Hermes integration — not in the current plan

## Historical installation boundary (Day 21)

Brenden paused Hermes work on November 10. This file is retained only as a
development record, not a user setup guide. Caravan's simple Mac installer
does **not** install Hermes, create its tunnel,
change its tools, download the optional tiny title model or install its aux job.
The existing Omarchy/EXO1 recipe below is a lab example, not a Mac prerequisite.
Keep the full toolset enabled (current reboot replay: 19 tools).

The shared-prefix fix avoids title calls replacing the main chat cache.
Optional title-sidecar routing and adaptive lookup remain opt-in. The auxiliary
Qwen2.5-0.5B worker waits for primary health plus spare memory; a successful
routed title has `X-Caravan-Aux: title-sidecar`. Check primary, aux health and a
full-tool chat after setup; a tiny chat alone does not prove full-tool behavior.
Day 21 both-Mini reboot restored main and aux without manual loads; see
[DAY21](../DAY21.md). FileVault-on/fresh-account startup is still untested.

## Setup (Omarchy -> EXO1)
Hermes Agent v0.23.0 stable, installed user-only with the official installer
(`--non-interactive`, no sudo), source `~/.hermes/hermes-agent`, launcher
`~/.local/bin/hermes`. Start a full-tool chat with `hermes`.

`~/.hermes/config.yaml` selects:
```yaml
model:
  provider: custom
  base_url: http://127.0.0.1:18090/v1
  default: mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit
  api_mode: chat_completions
streaming:
  enabled: true
```
No real provider key is required by Caravan; no credential belongs in this doc.
The configured full toolset is preserved. Optional external tool providers need
their own setup; this change does not pretend to supply missing credentials.

Enabled user service `hermes-caravan-tunnel.service` runs an SSH local forward:
127.0.0.1:18090 -> EXO1 127.0.0.1:8090, BatchMode, ExitOnForwardFailure,
15-second keepalives, restart after 5 seconds. Starts in the user's systemd
session; no lingering/system service. Check with:
```sh
systemctl --user status hermes-caravan-tunnel.service
```
The model remains split inside Caravan; Hermes itself does not shard it.
The web UI stays on 8190 and its lead worker on 8194. Keep 8090 loopback-only.

## Cache fix
See [DAY20.md](../DAY20.md) for evidence and measured results. The first large
prompt must still be read once. Follow-ups keep the conversation checkpoint;
new chats sharing exactly the same system/tool tokens can seed from a saved
pre-user checkpoint, even after worker restarts. Every split stage stores its
own file. No arbitrary rewind of Qwen3.5's recurrent state is attempted.

Hermes's background title call repeats the first user message with a different
system prompt and no tools. Old proxy fingerprinting let it replace the main
chat cache. MLX sessions are now namespaced by template inputs as well as the
first user message. Tools and system content are not stripped or reordered.
Hermes's stable system prompt/date needs no config patch.

`usage.prompt_tokens_details.cached_tokens` and `usage.caravan` distinguish
cached prefix, prefill time and model TTFT from visible-answer delay, reasoning
and FIFO queue time. A cold first turn is not an instant-response promise;
output still runs at the dense split model's natural decoding rate.

## Proxy auto-start
On the lead Mac, after its repository has been cleanly pulled:
```sh
~/.caravan/venvs/mlx/bin/python tools/caravan_service.py install \
  --kind proxy --name proxy --port 8090 --lead-port 8194
~/.caravan/venvs/mlx/bin/python tools/caravan_service.py status --name proxy
```
Do not start this over an occupied manual proxy. Wait for requests to finish,
stop only that verified manual process, then install. LaunchAgent
`com.caravan.v3.proxy` starts at user login, restarts on exit, and does not load
or change a model. Log: `~/.caravan/logs/proxy.log`. No reboot was used to test it.

## Historical setup smoke test caveat
The original installer smoke test said “Caravan connected.” but ran with only
`--toolsets clarify`, reporting 589 input / 125 output tokens and ~210 s wall
time. It was queued behind other work; this is NOT a full-tool prefill
measurement. The native worker's 589-token request took 28.20 s (9.01 s read),
while an earlier full-tool 12,175-token request took 199.53 s (190.65 s read).
Hermes doctor also reported three moderate npm web-workspace advisories; the
cache patch does not remediate those dependencies.

Hermes title calls explicitly send `reasoning_effort: none`; the MLX worker
now honors that as thinking off unless `thinking` is explicitly supplied.
Main Hermes `medium` reasoning remains unchanged. Previously the ignored
opt-out let short titles consume hundreds of hidden reasoning tokens.

## Verified result
Full configured toolset retained (21 tools), same Huihui 24/40 model.
Full-tool cold first visible text: 223.57 s. Three resumed replies: **11.57,
9.23 and 9.78 s**, each reusing **13,182 tokens** (prefill 1.17–1.76 s).
An independent new chat reused the same prefix (0.683 s prefill, 13.55 s
visible including unchanged medium reasoning). Output remains ~6.1 tok/s.
A changed system/tool block still needs one cold read. See DAY20.md for exact
methodology, per-request token counts, title overhead and persistence caveats.

EXO1 now runs the proxy as `com.caravan.v3.proxy` (RunAtLoad/KeepAlive),
127.0.0.1:8090 -> 127.0.0.1:8194. Huihui was reloaded through normal web
Balance in 14.61 s, no web restart or machine reboot. Hermes user config,
tools and its tunnel service were not changed by the cache fix.

## Hermes real-use speed
Brenden's live Hermes chat after the fix (2026-11-09 ~18:42–18:48 CT, America/Chicago):
first main turn reused **13,182** cached tokens after a **0.05 s** disk restore,
prefill **1.17 s**, first token **1.47 s**, write **6.14 tok/s**, total **10.26 s**.
Later main turns kept the same 13,182-token prefix (prefill 1.21–3.85 s depending
on new tokens). Titles stayed cold/short (~4.3 s prefill, 0 reasoning). See the
full per-request table in [DAY20.md](../DAY20.md).

## Self-tune clip pause (2026-11-09 evening CT)
Brenden approved a short Huihui unload to film the Day 10 self-tune climb.
Exact Balance state (Huihui 24/40 EXO2/EXO1) was restored afterward.
Restore ready **19:13:39 CST**; first Hermes-path reply through `:18090`/`:8090`
**19:13:54–19:14:00 CST**. Follow-up reply confirmed visible `hermes-ok` content.
See DAY20.md self-tune clip section for measured **41.53 → 69.70** tok/s and
clip path `/workspace/caravan-selftune-5s.mp4`.


## Day20 opt-in auxiliary titles and comparison evidence (Nov9 CST)

See [expanded Day20 results](DAY20.md#expanded-day-20-comparison-and-speedup-trials--nov-9-cst)
and `handoff/lab/day20-speedups/`. Current offline prefix is19 configured tools,
11,287 cached tokens on Huihui; historical actual Hermes13,182/21-tool results
above remain a different dataset. No Hermes provider/config change was made;
its current default was Opus, so new matrix timings are explicit local replay,
not a claim that the current Hermes CLI was switched to Caravan.

EXO1 proxy opts in with CARAVAN_AUX_MODEL=mlx-community/Qwen2.5-0.5B-Instruct-4bit,
CARAVAN_AUX_PORT=8196, CARAVAN_AUX_TIMEOUT_S=2,
CARAVAN_AUX_COMPACT_PROMPT=1. Unset model disables routing globally by default.
Only exact no-tool nonstream session_title jobs qualify; summaries/compaction
and ordinary main chats stay on the requested model with full tools/reasoning.
Compact equivalent title instructions preserve user/language; narrow formatting
normalization produces JSON, with length/topic/code/finish/health gates and
unchanged-main fallback on failure. Titles pilot median6.458→.114s; not a main
model generation speedup or broad quality certification.

com.caravan.v3.aux runs tools/aux_worker.py with installed local Qwen2.5 weights,
loopback8196, explicit .9GB soft MLX budget (.58GB observed peak),.25GB cache pool,
no persistence or global wired-limit changes. Waits for primary8194 health and
available RAM >=budget+1.75GB (unknown memory fails closed), bounded10min per
startup; launchd retries later. Default launcher budget2GB is conservative.
This is not an OS reservation or automatic eviction scheme; larger future
main placements still need guarded capacity checks. Aux boot behavior not yet
reboot-tested. Service/profile log paths and negative model trials are inDAY20.

Missing-sidecar fallback was verified live: valid Huihui title2.305s from cached
main state, then aux restarted. No model unload, Hermes tool removal or global
thinking-off. Main final full19-tool medium request stopped successfully in
11.872s, native TTFT.999s,6.22tok/s. Main Huihui remains24/40 KV16.
GET8090 /v1/models now discovers the live MLX model even with dead GGUF upstream.

## Follow-up single-versus-split replay

See DAY20.md's resumed Qwen3.5-family comparison and handoff/lab/day20-single/.
Exact same19-tool replay payloads compared across actual placements; no Hermes
configuration changed. Orvena/ was added to the proxy's existing explicit MLX
prefix allowlist (otherwise it fell through to dead GGUF upstream). Sidecar
was unloaded during measurements, restored after main Huihui24/40 KV16.
Huihui full single GPU OOMed under stock admission;1976b7b fixes a nested decoder
layer-count underestimation in single-worker KV budgets, not a relaxed guard.
Astrea short medium emitted EOS-only reasoning; supplemental explicit-none short
results are separate. Full-prefix Astrea/Orvena produced valid matching replies.
Final19-tool medium Huihui reply: .405s native TTFT,6.21tok/s,11.372s wall,stop.
