# Hermes Agent with Caravan

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
See [DAY20.md](DAY20.md) for evidence and measured results. The first large
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
full per-request table in [DAY20.md](DAY20.md).

## Self-tune clip pause (2026-11-09 evening CT)
Brenden approved a short Huihui unload to film the Day 10 self-tune climb.
Exact Balance state (Huihui 24/40 EXO2/EXO1) was restored afterward.
Restore ready **19:13:39 CST**; first Hermes-path reply through `:18090`/`:8090`
**19:13:54–19:14:00 CST**. Follow-up reply confirmed visible `hermes-ok` content.
See DAY20.md self-tune clip section for measured **41.53 → 69.70** tok/s and
clip path `/workspace/caravan-selftune-5s.mp4`.

