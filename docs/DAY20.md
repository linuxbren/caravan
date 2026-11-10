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

## Hermes real-use speed (Brenden, 2026-11-09 ~18:42–18:48 CT)

After the cache fix and diagnostic bench above, Brenden used Hermes Agent
normally (full configured toolset, same Huihui EXO2/EXO1 24/40 split). Source:
EXO1 `~/.caravan/web-ui/lead.log` session `90716b1a257d8461`. Proxy
`~/.caravan/logs/proxy.log` shows the matching warm/cold turns. No model
reload or service restart for this measurement.

Disk restore of the shared system/tool prefix happened first:
`restored agent_p13182_4d50f8b37ae3529f from disk: 13182 tokens in 0.05s`,
then `agent-prefix hit 13182 tokens`.

| CT | Kind | Prompt | Cached | Prefill s | First token s | Write tok/s | Generated | Total s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 18:42:30 | Main turn 1 | 13,192 | 13,182 | 1.17 | 1.47 | 6.14 | 55 (42 reason + 11 answer) | 10.26 |
| 18:42:36 | Title | 258 | 0 | 4.27 | 4.55 | 5.57 | 7 (0 reason) | 5.63 |
| 18:43:52 | Main turn 2 | 13,242 | 13,182 | 1.21 | 1.51 | 6.21 | 269 (111 reason + 25 answer) | 44.64 |
| 18:43:59 | Title | 284 | 0 | 4.29 | 4.57 | 6.08 | 13 (0 reason) | 6.55 |
| 18:45:04 | Main turn 3 | 13,291 | 13,182 | 2.24 | 2.54 | 6.19 | 154 (81 reason + 71 answer) | 27.24 |
| 18:46:03 | Main turn 4 | 13,381 | 13,182 | 3.85 | 4.15 | 6.23 | 260 (97 reason + 0 answer) | 45.73 |

Main turns 2–4 hit `agent-prefix-hit-memory` after the usual one-token
template-tail divergence (same mechanism as the diagnostic follow-ups). Title
calls stayed on separate fingerprints and kept `reasoning_effort:none`
(0 hidden reasoning). Writing stayed ~6.1–6.2 tok/s.

After turn 4, three exact-append retries reused **13,380 / 13,381** cached
tokens (`hit-memory`, prefill **0.02 s**, first token **0.32 s**, write
**6.24 tok/s**, total ~41.8 s each, 97 reason + 0 answer). Client cancelled at
18:48:41 (`generation stopped … cancelled`; rewound). Those retries are
recorded for completeness; they are not separate user prompts.

Compared with the pre-fix full request (13,192 / 0 cached, **207.87 s**
prefill): the first real Hermes turn after disk restore prefilled in **1.17 s**
with **13,182** cached tokens. Output rate is unchanged (~6.1 tok/s). Longer
totals on turns 2–4 are generation length and hidden reasoning, not a cold
13k-token reread.

## Self-tune clip (approved pause of Huihui)

Brenden approved pausing Huihui briefly to capture a ~5s Caravan web UI
self-tune clip (`Go ahead and pause it now`). Exact pre-pause Huihui state
was saved first:

- model: `mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit`
  (`huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit`)
- Balance split **24/40**, stage order **EXO2 → EXO1**
- settings: `self_tune=off`, `pipeline_chats=1`, guess-ahead/prompt-lookup off

Demo load (Day 10 story): `mlx-community/Qwen3-30B-A3B-4bit` split **24/24**
EXO2/EXO1. The historical Day 10 trap is `pipeline_chats` **1 vs 2** on that
spanned Qwen3 (~37.2 vs ~67.8 aggregate in the original write-up). For this
clip the bad setting was seeded on purpose and measured live on EXO1
`127.0.0.1:8194` (two concurrent chats; web FIFO alone serializes):

| Setting | Mean aggregate tok/s | Pair samples | Approx write tok/s each |
|---|---:|---|---:|
| `pipeline_chats=1` (bad) | **41.53362073990969** | 41.451, 41.532, 41.505, 41.589, 41.592 | ~45.3 |
| `pipeline_chats=2` (fixed) | **69.70341284830742** | 68.263, 70.254, 70.170, 70.126 | ~39.2 |

Clip numbers shown on screen (two decimals, not rounded toward 37/68):
**41.53 → 69.70** tok/s across two concurrent chats. Payoff climbs inside
the first ~3 s; total length **5.000 s**. No narration, no slides, no dates.
Optional one-line caption: `self-tuner lifts pipeline_chats 1 → 2`.

- File: `/workspace/caravan-selftune-5s.mp4` (also
  `~/day19-video/selftune/clip/caravan-selftune-5s.mp4` on Omarchy)
- Size: 408,054 bytes
- Raw UI captures + probe JSON under `~/day19-video/selftune/`
- EXO1 evidence: `~/.caravan/day20-hermes/` (pre-pause backups) and
  `~/day19-video/selftune/numbers.json`

Temporary EXO1-only demo patch to `proxy/web_pipeline.py` (Balance had
hardcoded `--no-learn` / `pipeline_chats=1`) was reverted from
`web_pipeline.py.bak-selftune` before restore. Not committed.

### Huihui restore + Hermes check

| Event | America/Chicago |
|---|---|
| Huihui ready again (24/40 EXO2/EXO1) | **2026-11-09 19:13:39 CST** |
| First :8090/:18090 reply start | **2026-11-09 19:13:54 CST** |
| First reply end | **2026-11-09 19:14:00 CST** (~6 s wall) |

First reply returned a valid chat completion (finish `length` at
`max_tokens=32` while still in hidden reasoning). Immediate follow-up with
`max_tokens=128` finished `stop` with visible content containing `hermes-ok`
(ttft 0.301 s, total 11.926 s, `hit-memory`, split true). Status after restore:
`ready`, counts `[24, 40]`, `node_ids: ["exo2","exo1"]`, `pipeline_chats=1`,
`self_tune=off`. Hermes tunnel path Omarchy `:18090` → EXO1 `:8090` → lead
`:8194` works.


## Self-tune clip v2 (re-cut from existing assets)

Re-cut only — no unload, no re-record, Huihui left loaded. Source: Omarchy
`~/day19-video/selftune/raw/01-start.png` UI still + live means in
`numbers.json`. Readout is a **re-rendered overlay**; endpoints **41.53** and
**69.70** are the real measured means; **in-between frames are interpolated**
(hold 41.53 for 1.0 s, ease to 69.70 by 3.0 s, hold through 5.0 s).

- File: `/workspace/caravan-selftune-5s-v2.mp4` (Omarchy
  `~/day19-video/selftune/clip/caravan-selftune-5s-v2.mp4`)
- Length: **5.000 s**
- No ghost number (single draw per frame; mid-frame pixel-identical to a
  fresh `55.62` redraw). No model name, no jargon caption.
- Unit line: `tokens a second · two chats at once`
- Checked frames: 0.2 s → **41.53**; 0.9 s → **41.53**; 2.0 s → **55.62**;
  3.2 s → **69.70**; 4.8 s → **69.70**

## Day 19 video v2

- File: `/workspace/caravan-day19-v2.mp4` (~**56.8 s**)
- No test counts. Captions are plain, benefit-led; jargon left out.
- Test card replaced with real Topology footage (Huihui live 24/40).
- Stats only in the closing “For the nerds” line.
- X videos go to review before Brenden (standing rule).

## Restore-last-model reboot test — 2026-11-09 19:46–19:55 CST (America/Chicago)

Ran this evening: Brenden rebooted **both Minis at once**. Result: **partial fail**.

launchd brought `com.caravan.v3.web` (`:8190`) and `com.caravan.v3.proxy`
(`:8090`) back on their own. Restore-last-model started at **19:47:05.163 CST**
and blocked at **19:47:06.735 CST**:

> Could not restore last model: live free memory is unknown for exo2. Check Minis/files/memory, then press Load. No automatic retry or download.

No retry during the five-minute no-touch window after SSH returned (EXO2 LAN
**19:46:40**, EXO1 LAN **19:47:04**, both Tailscale SSH up by **19:47:11**).
EXO2 memory was known again by **19:53:14**. A manual Load at **19:54:24**
made the same Huihui **24/40 EXO2/EXO1** split ready at **19:54:38** (12.1 s).

First Hermes-path reply through Omarchy `:18090` at **19:55:03** (stream, wall
TTFT **0.487 s**, wall total **2.917 s**). Follow-up official timings
**19:55:16–19:55:26**: `ttft_s=0.314`, `total_s=9.844`, `hit-memory`,
read **34.5** tok/s, write **6.61** tok/s. `:8090` `GET /v1/models` remains
502 (llama upstream) even when MLX chat works — same as before the reboot.
`exo2-via-exo1` stayed down; `exo2` and `exo2-lan` were fine.

Full table, poller paths, and tunnel note: `docs/DAY19.md` (reboot test + video v4).
Watchers stopped **19:55:50 CST**. Huihui 24/40 left loaded for Hermes.

## Day 19 video v4

`/workspace/caravan-day19-v4.mp4` (Omarchy `~/day19-video/caravan-day19-v4.mp4`),
**32.000 s**. Big type, complete wrapped fruits answer, simple switchover
status from the real fallback log, honest reboot beat (computers/web came
back on their own; the model needed a Load). Captions in
`handoff/lab/videos/day19_captions_v4.txt`. X videos still go to review
before Brenden.

## Deferred (still open)

- Restore-last-model **retry** after "live free memory is unknown" (the
  2026-11-09 dual-Mini reboot proved services come back, but the model
  restore blocked with no retry).
- Live switch / unload / KEEP-web-restart checks beyond the self-tune pause
  and path-switchover already done.
- `exo2-via-exo1` jump path was still down after this reboot; direct and LAN
  paths were not.
- Balance clearer UI mockup → code (one-line explanation, per-Mini memory bars, Auto default with Adjust revealing the slider, live preview, Apply / Back to auto, jargon behind details).
- Day 19 video v4 at `/workspace/caravan-day19-v4.mp4` (32.000 s). X drafts under Omarchy `~/Pictures/x-posts/day19/` — review before Brenden posts.
- Day 20 tagged release and main fast-forward (not cut yet).


## Reboot follow-up correction and readiness fix — Nov 9, 2026 CST

**Automatic restore FAILED.** At 19:47:05 CST the web's initial restore POST
returned 400: `live free memory is unknown for exo2`; the previous controller
blocked permanently, with no automatic retry. A different executor manually
loaded Huihui at 19:54:24; ready about 19:54:38. The follow-up executor's earlier
“eventual automatic restore” inference was wrong and is superseded here.

Omarchy's unmanaged :18190 SSH tunnel also died in the reboot and was manually
restarted at 19:54:12. Thus tunnel HTTP failure did not establish local-web
failure. Launchd web and proxy had started at 19:47:04. SSH milestones from the
watcher: EXO2 down 19:46:18, both down 19:46:30; EXO2 primary back 19:46:53,
EXO1 primary back 19:47:11 (row timestamps precede sequential probes).

The verified synthetic Hermes-style POST via :18090 at 19:58:35–56 CST completed
with `Caravan is back online.` HTTP 200, 21.350 s wall; worker 18.656 s,
TTFT .805 s, prefill .525 s, write 6.55 tok/s. This was not an actual Hermes
application/full-tool-prefix benchmark. GET `/v1/models` 502 predates reboot:
that discovery GET goes to the absent default llama backend; model-bearing MLX
chat POSTs route correctly. No proxy discovery change is included in this fix.
Thunderbolt inference uses EXO2 169.254.195.205 via EXO1 en2; the stale IPv6
`exo2-via-exo1` SSH alias does not indicate failed inference transport.

Fix: restore readiness preflight retries offline/unknown-free-memory errors
with 2, 4, 8, 16, then up to 30 s backoff, bounded to ten minutes. Each attempt
reuses the same saved model, exact N-Mini placement/counts/settings and guarded
UI load endpoint. Missing files, insufficient known free RAM, busy unadopted
workers and ambiguous transport timeouts still fail closed without retries or
downloads. User Stop/switch cancels backoff immediately and invalidates the
restore token; unload retains its durable null intent. Existing ready workers
are adopted without reload on a KEEP_WORKERS web restart.

Omarchy tunnels are managed by systemd user services with Restart=always,
ExitOnForwardFailure, SSH server keepalives and five-second restart delay.
Fresh reboot-watch2 probes distinguish local web, local MLX, packer, tunnels,
process/reconnect state and model-bearing proxy chat. A second Brenden-issued
reboot is REQUIRED to prove the fix. No reboot is issued by this executor.
First-run evidence remains in `~/day19-video/reboot-watch/logs/` and frames/.

Deployment detail: the existing `hermes-caravan-tunnel.service` already had
Restart=always and recovered at 19:47:05 CST (3 restarts); left untouched.
Added/enabled `caravan-web-tunnel.service` for :18190, replacing only the
verified unmanaged web SSH process. No model/network/security settings changed.


## Both-Mini reboot #2 — unattended restore PASS, Nov 9, 2026 CST

Brenden rebooted both Minis after the READY baseline on **9242f21**. The
executor observed only: **no manual Load, service restart, network edit, or
reboot command** during recovery. Saved Huihui 24/40 returned automatically.
The previous failed first reboot remains a failure; this separate run is the
first proven successful web-owned last-model both-Mini restore in this session.

### Native evidence timeline (all CST)

| Milestone | Timestamp | Evidence / qualification |
| --- | --- | --- |
| First EXO1 proxy-over-SSH probe failure | 20:06:44.009 | `exo1-chat8090.jsonl`; last baseline green before shutdown |
| Both Omarchy tunnels down / systemd auto-restart | 20:06:45.517 | `tunnels.jsonl` |
| EXO1 local-status SSH probe down | 20:06:47.506 | `exo1-local.jsonl` |
| EXO2 SSH probe down | 20:06:51.506 | `exo2-packer.jsonl` |
| EXO1 kernel boot time | 20:07:01 | native `sysctl kern.boottime` |
| EXO2 kernel boot time | 20:07:05 | native `sysctl kern.boottime` |
| EXO1 LAN SSH back | 20:07:15.226 | `lan-paths.jsonl` |
| EXO1 launchd web / proxy processes started | 20:07:15 | native `ps lstart`, PIDs 661 / 647; launchctl snapshots retained |
| Both supervised tunnel processes successfully restarted | 20:07:19 | systemd `ExecMainStartTimestamp`; PIDs 1616346 / 1616347 |
| EXO2 LAN SSH back | 20:07:20.369 | `lan-paths.jsonl` |
| EXO1 primary SSH / local :8190 HTTP 200 | 20:07:21.301 | worker idle, restore preparing; :8194 not ready yet |
| Both Omarchy tunnel endpoints HTTP 200 | 20:07:23.546 | :18190 status / :18090 proxy-status, NOT model-readiness proof |
| EXO2 primary SSH back | 20:07:24.646 | :5560 not yet listening |
| Automatic restore starting packer | 20:07:38.178 | local status; packer process start 20:07:38, PID 1151 |
| EXO2 packer port listening | 20:07:42.831 | local lsof; no extra client connected to single-head protocol |
| EXO2 24-layer packer ready | 20:07:42.709 | worker progress timestamp |
| Saved 24/40 split fully loaded / healthy | 20:07:48.742–.744 | native worker progress; durable intent saved .744 |
| First model-bearing :8090 chat probe HTTP 200 | 20:07:50.302 | 1 output token; route/inference check, not complete human reply |
| First full :18090 MLX chat request sent | 20:07:51.664 | synthetic Hermes-style request, not an actual Hermes app turn |
| Full :18090 assistant reply complete, HTTP 200 | 20:08:03.913 | `Caravan recovered automatically.` / finish_reason=stop |
| Probe watchers stopped / capture stop requested | 20:08:42.774 | surviving capture loop finally stopped 20:09:43.347; tunnels/services left running |

The model was loaded about **64.7 s after the first observed EXO1 transport
failure** (or 57.2 s after the first EXO2 SSH-down sample). These are sampled
observations, not exact power-off times: probe timestamps mark completion,
SSH/connect timeouts can add seconds, and the LAN watcher started while both
were already down at 20:06:54.197. It cannot supply earlier LAN-down times.

### What recovered and what this run does not prove

- Exact model: `mlx-community/Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-4bit`;
  EXO2 front 24 / EXO1 head 40, pipeline_chats=1, self_tune=false. Lead PID 1375.
  Thunderbolt peer refreshed automatically to **169.254.99.64:5560**.
- Restore phase was preparing by 20:07:21 and **restored** by the first ready
  samples at 20:07:49.572 (tunnel) / 20:07:49.941 (local). Native load completion
  was 20:07:48.744. Post-boot web audit contains a single successful
  `POST /api/models/load` HTTP 200, no 400, with no manual control call.
- **No retry/backoff phase was observed in this physical reboot.** Initial
  guarded preparation waited for inventory and succeeded once peers were up.
  This run proves unattended recovery on the retry-enabled build and both
  supervised tunnels; the specific transient 400→backoff→200 branch is covered
  by focused unit/guarded HTTP tests, not independently forced on hardware here.
- Both tunnel services retried automatically three times during this reboot:
  web NRestarts 0→3, Hermes 3→6. Their final process start was 20:07:19; actual
  HTTP reachability was proven separately at 20:07:23.546. No manual SSH tunnel
  was launched during recovery. The systemd services remain enabled/running.
- Full :18090 reply: **12.249 s wall**, worker **12.201 s**, **TTFT 0.815 s**,
  prefill **0.530 s**, **6.50 write tok/s**, 26 prompt / 75 completion tokens,
  cold cache. No full-tool 13k-prefix Hermes performance claim is inferred.
- During that full reply, 1.5-second web-status probes and a 6-second concurrent
  synthetic chat probe timed out briefly, then recovered without intervention
  by 20:08:04–05. The completed user-visible reply did not fail. These strict
  probe deadlines should not be misreported as a second reboot/service outage.
- No further reboot is required to establish this run's pass. No video made.

Raw evidence on Omarchy: `~/day19-video/reboot-watch2/logs/` contains
`exo1-local.jsonl`, `exo2-packer.jsonl`, `exo1-chat8090.jsonl`,
`lan-paths.jsonl`, `tunnels.jsonl`, per-host `*-service-starts.jsonl`,
`*-launchd-*.txt`, `final-status.json`, `restore-request-audit.txt`,
`automatic-recovery-chat18090.json`, and `stopped.txt`. Frames remain in
`~/day19-video/reboot-watch2/frames/`. The capture log's raw ISO timestamps
are UTC; the timeline above is converted to America/Chicago CST.


### Day 19 video v5 — verified automatic-recovery beat

Output `/workspace/caravan-day19-v5.mp4`, copied to Omarchy
`~/day19-video/caravan-day19-v5.mp4`: 32.000 s, 1280×720, 24 fps.
Build: `handoff/lab/videos/make_day19_v5.py`; captions beside it. Only the
20–28 s reboot beat is replaced; all other footage comes directly from v4,
including its two 2-second end cards. At 24 s the caption is now
“About a minute later, the model is back and answering.” Status summary:
“Automatic restore: done” / “Same split ready: about a minute later”.

The real unreachable capture is reboot-watch2 frame f000044. Reloaded UI
captures still show STARTING before asynchronous hydration, so they are not
misrepresented as ready-model proof: the recovered status is explicitly a
readable native-log summary. Actual measurement is64.735 s from first failed
EXO1 probe to fully loaded. On-screen numeric facts remain Huihui27B4-bit,
split24/40, EXO2 then EXO1; no new speed/test-count/date overlay. Captions
single-line, checked within1280px; preview stills manually inspected.

Send v5 and its real numbers to X Engagement for review before showing it to
Brenden. No post/send performed by this executor.


### Day 19 video v6 — reviewer trims, no new footage

Output `/workspace/caravan-day19-v6.mp4`, copied to Omarchy
`~/day19-video/caravan-day19-v6.mp4`; **22.000 s**, 1280×720,24fps,528frames.
Source-only frame edit of v5: answer retained through7.5s (~1s after completion);
three status cards52frames each (~2.17s). End cards remain2s each.
Typing label is YOU throughout, fixed position/color; recovery value now
**64.7 s** (rounded from64.735s, first failed EXO1 probe to load complete),
not a power-off stopwatch or reply-latency claim. Other numbers remain
Huihui27B4-bit,24/40,EXO2 thenEXO1. No speed/test-count/date overlays.

Build `handoff/lab/videos/make_day19_v6.py`; frame-exact source ranges and
caption timings recorded in script and `day19_captions_v6.txt`. New captions:
0.000 /2.208 /7.500 /9.667 /11.833 /15.833 /18.000 /20.000s.
All unchanged wording preserved, including the recovery caption “About a minute
later, the model is back and answering.” Corrected typing/recovery stills
visually inspected, single-line bottom captions intact, no cropped text.
Parent must obtain X Engagement review before showing Brenden. No external
post/message or service restart performed by this executor.

## Expanded Day 20 comparison and speedup trials — Nov 9, CST

### Scope, provenance and interpretation

No cloud agents, release/tag, video, reboot or Hermes configuration changes in
this phase. Model loads used the normal guarded web API, never bypassed memory
guards or fetched weights. Main model was restored to **Huihui 27B, EXO2 first
24 layers / EXO1 40 layers, KV16**, with all currently configured Hermes tools.
Experiments intentionally switched models; only the proxy was restarted for
proxy changes. The web was not restarted.

The historical **207.87 s prefill → 1.17–1.76 s, 13,182 cached tokens** belongs
to the earlier actual Hermes run with 21 configured tools and fixes
`367cbc9` / `6efecbf` / `ad07c13`. Main and title sessions were isolated; exact
pre-user checkpoints were captured during prefill, cloned with recurrent
snapshots on every stage and saved durably. This avoids unsafe arbitrary
recurrent rewinds and title/main checkpoint collisions. Cold compute did not
magically get faster; retained system/tool state removed repeated compute.

The old capture directory was no longer present. For the expanded matrix we
froze the **current offline Hermes CLI inspection prefix**, from the home cwd:
**19/19 currently configured tools**, system 13,108 characters, tool JSON 34,487
bytes; frozen-prefix SHA256
`e0218dd991e351fb3ee4b6ab240bcdc47e146c371dea458c2b6abd230b690575`.
Current native shared prefixes are **11,287 tokens on Huihui** and **11,196 on
Qwen3**. Do not relabel these as the historical 13,182-token run. Hermes itself
had been reinstalled/changed and its configured default model was now Opus;
we did not change that setting or make an Opus request. These are **inference-only
full-prefix replays through :18090**, not measured Hermes CLI/tool execution.

Both routes use the same realistic user task: three brief local-service
recovery checks, under 45 visible words, no executed tools. Short/direct uses
:18190/v1/chat/completions; full/system+tools uses :18090. Temperature 0,
medium reasoning. Successful baseline rows below finish `stop`, not truncation.
Huihui full rows used a 256-token cap and stopped naturally; corrected short
and Qwen rows use 512. Warm full requests add a small user suffix; Huihui's
corrected short warm request repeats exactly. Cached counts, not labels, are
authoritative. Output lengths differ, so reply wall-time differences are not a
pure measurement of Hermes wrapper overhead or equal-length generation.
**Native/wire TTFT includes reasoning tokens**; first visible answer is separate.
Raw times carry CST offsets. All table times are seconds.

### Phase A: baseline matrix, KV16 / serial / speculation off

| Model / placement | Route | Cache | Prompt / cached | Generated | TTFT native / wire (s) | First visible answer (s) | Write tok/s | Full wall (s) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Huihui 27B 24/40 | direct | cold | 54 / 0 | 275 | 1.275 / 1.795 | 36.712 | 6.62 | 42.748 |
| Huihui 27B 24/40 | direct | warm | 54 / 53 | 275 | 0.298 / 0.925 | 35.754 | 6.63 | 41.785 |
| Huihui 27B 24/40 | hermes | cold | 11,322 / 0 | 226 | 177.438 / 177.684 | 195.202 | 6.30 | 213.413 |
| Huihui 27B 24/40 | hermes | warm | 11,326 / 11,287 | 183 | 1.436 / 3.090 | 19.019 | 6.30 | 32.043 |
| Qwen3 30B-A3B 24/24 | direct | cold | 52 / 0 | 174 | 0.387 / 0.548 | 3.766 | 44.94 | 4.308 |
| Qwen3 30B-A3B 24/24 | direct | warm | 56 / 47 | 181 | 0.127 / 0.246 | 3.919 | 44.87 | 4.170 |
| Qwen3 30B-A3B 24/24 | hermes | cold | 11,229 / 0 | 238 | 36.269 / 36.366 | 43.898 | 29.20 | 44.449 |
| Qwen3 30B-A3B 24/24 | hermes | warm | 11,233 / 11,196 | 415 | 0.569 / 1.097 | 14.623 | 29.20 | 15.241 |

Single-Mini attempts were actually submitted, but did not launch a worker:
- **Huihui EXO1:** HTTP400, required complete model files missing; no download
  started. Its EXO1 folder has only the split subset (missing shard 1), so this
  is a missing-files failure, **not a measured OOM**. Inventory fit estimate
  also exceeded the approximately 16.4 GB safe capacity (~19.1 GB need).
- **Qwen3 EXO1:** HTTP400, insufficient free memory with 1.75 GB headroom.
  Complete local weights exist (~17.17 GB), but estimated load need ~20.3 GB
  exceeds safe capacity. **No single-Mini TTFT/write/reply result and no OOM
  were measured.** Do not invent a speed comparison for these cells.

### Phase B: before/after and decisions

| Change | Before | After / result | Kept? |
|---|---|---|---|
| Explicit prefix prewarm after load, genuinely unseen real user suffix | TTFT 1.762; request wall 1.864 | Dummy prefix request cost .668; real TTFT 1.699, wall 1.972; both real requests reuse 11,287 tokens | **No automatic warm-up**: negligible/no end-to-end benefit over existing durable prefix recovery; could contend with real work |
| Automatic title sidecar, real incoming Hermes title schema | Main cold title walls 6.752 / 6.458 / 6.445 | Same incoming Caravan/garden/Rust requests .213 / .110 / .114 through :18090, validated JSON and relevant titles | **Yes, local opt-in**; median 6.458 → .114 s (~57×), titles only; no main-chat speed claim |
| Explicit thinking none, short checks | Short cold 42.748 s / 275 generated with medium | 9.68 s / 54 generated, same write speed (~6.5 tok/s); full-prefix warm ~32.04 →16.40 s with shorter output | Existing request-level `reasoning_effort:none` works; **main stays medium**. No automatic general tool-turn suppression: safety/quality not established |
| Adaptive n-gram lookup, paired warm copy task, 3 each | Median 44.26 tok/s, 1.295 s wall | 70.69 tok/s, .858 s wall; 43/50 proposed tokens accepted = **86%**; 8 copied lines equal after outer whitespace | Keep existing **opt-in** lookup plus true token acceptance readout; **not default** |
| Lookup on realistic full-prefix Qwen task | 29.34 tok/s | 28.48 tok/s; 0/3 proposals accepted, different output lengths (238 vs344 generated) | **Off** for general/Huihui work; copy benchmark is not a Hermes-wide win |
| Qwen KV8 vs KV16, full-prefix cold | Prefill 36.200, write29.20, lead peak10.26 GB | Prefill49.151, write22.68, peak11.98 GB; warm write also22.68 vs29.20 | **KV16 retained**; observed compute/peak allocation regressed this workload. Short write42.11 vs44.94; warm wall12.005 vs15.241 is not a win because output238 vs415 tokens |

#### Sidecar implementation, negative trials and operation

Generic proxy settings (no fixed number of Minis): `CARAVAN_AUX_MODEL` unset
means **disabled by default**; loopback `CARAVAN_AUX_PORT=8196`, bounded per-I/O
`CARAVAN_AUX_TIMEOUT_S=2` (.05–10 allowed), `CARAVAN_AUX_COMPACT_PROMPT=1`
(default for an opted-in sidecar; 0 forwards original title instructions).
Only nonstreaming, <=128-token, no-tool, exactly system+user requests with
Hermes's `session_title` schema and exact title marker qualify. General
summaries/compaction/agent state are **not** guessed or redirected.

The opted-in sidecar uses concise equivalent **title-only** instructions,
preserving the user message and original language rule. It never edits main
system prompts, tools or thinking. Strict JSON titles, or short one-line quoted/
`Title:` titles in compact mode, are normalized to the required JSON object.
Newlines, code/Markdown, malformed JSON, length failures, missing topic overlap,
non-stop finish, unhealthy/slow service or memory errors all fall back to the
unchanged main request. Topic overlap is conservative, not a proof of semantic
correctness; broader title quality testing is still warranted.

Negative trials were retained, not hidden: Qwen3-0.6B returned the unrelated
few-shot title “Fix login button on mobile” for Caravan and was **rejected**.
Qwen2.5-0.5B with the original long prompt got Caravan right but garden prefixed
its JSON with `Good:` and Rust emitted truncated code; those are invalid and
would fall back. Compact equivalent title instructions plus narrow formatting
normalization produced relevant valid titles on all three measured requests:
“Review Caravan after reboot and improve Hermes speed”, “Plan garden irrigation
for hot weather”, “Learn Rust borrow checker lifetime errors”. This is a
three-case pilot, not comprehensive quality certification.

EXO1 now has `com.caravan.v3.aux`, local already-installed
`~/.caravan/mlx-models/drafts/Qwen2.5-0.5B-Instruct-4bit`, port8196. Startup wrapper
`tools/aux_worker.py` waits up to10min for primary health and known free RAM
>=soft MLX budget +**1.75 GB reserve**. Defaults are conservative2 GB; this small
worker was measured within an explicit **.9 GB** budget, .25 GB cache pool,
256 MiB session-cache budget, no persistence, no learn/draft, no wired-limit
changes. Actual measured peak **.58 GB**. The default2 GB and initial1 GB
admission waits were recorded: available RAM was ~2.74–2.91 GB, not enough for
3.75 GB / briefly2.75 GB thresholds. No main context/tools were reduced to fit
it. Limits are MLX soft caps, not hard OS reservations; the main model's normal
memory guard remains authoritative. No automatic sidecar eviction/lifecycle
integration for future larger main models is claimed.

Only the idle proxy was booted out and bootstrapped to pick up explicit local
aux environment settings; its pre-aux plist is backed up under
`~/.caravan/logs/day20-proxy-before-aux.plist`. Aux log:
`~/.caravan/logs/day20-aux.log`. One rapid aux bootout/bootstrap got transient
launchd EIO; after confirming the old job was gone, retrying the same bootstrap
succeeded. No root workaround or primary restart was used.

Live fallback was tested by stopping only the auxiliary service: :18090 returned
a correct Huihui Rust title in **2.305 s**, no auxiliary header, then aux was
restarted. This fallback was a cached main title (261/262 tokens), not a new
cold title benchmark. The temporary Omarchy :18196 measurement tunnel was
stopped; production18090/18190 supervised tunnels remain.

#### Other requested fixes

- `f0a389e`: GET8090 `/v1/models` aggregates live MLX/llama discovery and
  canonicalizes MLX names; a dead GGUF upstream no longer turns a live MLX list
  into502. Live18090 GET returns200 with the loaded Huihui HF model id.
- `f0a389e` / `82fa186`: dynamic TB SSH proxy helper resolves the peer's current
  en2 IPv4 through the lead, rather than retaining stale link-local IPv6.
  Initial discovery consumed SSH stdin; explicit DEVNULL fixed packet corruption.
  Omarchy `exo2-via-exo1` now successfully reports EXO2's hostname. Host-key policy
  was retained; old alias block is in raw evidence. No fixed two-node assumption
  was added to application inference code; physical benchmarks here are N=2 only.
- `6112ae6`: conservative auxiliary-route prototype and token-level PL telemetry;
  `03cd47b`: RAM/primary-health startup guard; `49379aa`: topic/timeout safety;
  `59e78f6`: measured compact-title prompt and strict output normalization.

### Honest controls, evidence, verification and final state

Raw results and reusable helpers: `handoff/lab/day20-speedups/` (`matrix.csv`,
`matrix.md`, `raw/`, `bin/`). Omarchy originals: `~/day20-speedups/`.
Private frozen instructions and request bodies stay only in its chmod700
`private/` folder; **not committed**. Capturing again may change the prefix;
use the retained hash to distinguish datasets. No endpoint/tool was invoked by
Hermes during offline inspection, and no model-emitted tool call was executed.

Failed controls are kept separately:
- Initial short Huihui cold cap256 ended `length`; its supposed warm request
  had changed prompt/random web session and0 cached. Both are excluded from
  the successful short baseline table; corrected persistent-session512-token
  requests both ended `stop`.
- Initial model-load poll accepted the previous model's stale `ready` before
  asynchronous switch progress. Resulting incomplete/error streams and busy
  load rejections are in `raw/invalid-load-polling-control/`, **excluded**.
  Controller now requires matching model, changed lead PID, requested KV bits,
  healthy lead and intended counts. Streams without usage/finish are failures.
- Initial “reload on-demand” prewarm comparison reused the exact future user
  task from durable session state; this is not an unseen first-chat control.
  Corrected `prewarm-unseen-*` calls have distinct never-before-used suffixes,
  share only11,287 system/tool tokens and intentionally generate1 token. They
  measure TTFT only, not complete-answer time.

Final regression: **792 unit tests passed in43.596 s**, plus compile/whitespace
checks. Existing N-stage cache tests include1/2/3/5 fake stages, not unmeasured
hardware claims. Both Minis pull commits `--ff-only`; no scp or cloud agent.

Final real full-prefix :18090 reply: **19 tools, medium reasoning**,11,310 prompt /
11,287 cached, native TTFT **.999 s**, write **6.22 tok/s**, wall **11.872 s**,
`stop`: “I'm online and ready to help.” Huihui24/40 KV16 ready, lead PID12425.
Aux health200, GETmodels200, Thunderbolt SSH works. Main guess-ahead/lookup/
self-tuning remain off for these controlled settings. Existing boot auto-restore
still saves Huihui, not the temporary Qwen model. No new reboot was performed;
auxiliary boot ordering has not been reboot-tested. No Day20 tag or video made.

## Resumed single-Mini versus split comparison — Nov 9, CST

### Same-family selection, inputs and interpretation

Completed the requested **Qwen3.5-family** comparison, not a Qwen3 fallback:
- Huihui Qwen3.5-27B Claude4.6 Opus abliterated4bit, full weights16.05GB.
- `mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit`, a Qwen3.5-9B fine-tune.
  Its “4bit” label is **mixed4/8-bit text**,7.10GB, plus a .91GB bf16 vision
  sidecar. It is NOT uniform4-bit. Model-card source:
  https://huggingface.co/mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit/raw/main/README.md
- `Orvena/Orvena-4B-MLX-4bit`, Qwen3.5-4B fine-tune,4-bit/group64,3.03GB.
  Both smaller models were already downloaded on EXO2; no HF weights downloaded.

Actual frozen Day20 Hermes prefix/user task reused:19/19 configured tools,
temperature0, medium reasoning, KV16, serial pipeline1, learn/draft/lookup off.
Single is EXO1; smaller split models are EXO2→EXO1,16/16 layers. Both physical
Minis are24GiB (25.77 decimalGB). The auxiliary title worker was stopped for
all measurements, then restored. No other models were deleted or forced through
an admission failure. No reboot/cloud agent/Hermes config change/release/video.

Each new-model pair has **identical request SHA256, generated-token count and
visible output** for each corresponding route/cache condition; see
`paired-input-output-proof.json`. All admitted successful rows are untrimmed
and finish `stop`. Short warm repeats exactly; full warm adds the same “Use
plain language.” suffix on both placements and reuses the system/tool checkpoint.
Every new-pair cold row has0 cached tokens; warm short has53, warm full11,400.
Tokenization differs from Huihui's11,287-token prefix, not tool removal.
Smaller-model cap1024 rather than earlier512 avoids censored results; all actual
outputs are below512 tokens (largest505), so no larger-cap speedup is claimed.
Huihui single cap512; split reference full cap256 ended naturally, not truncated.

**TTFT includes reasoning**, not necessarily the first visible answer. Wall is
full completion time only when a visible response exists. This is inference-only
replay, not Hermes CLI/tool execution. The Huihui two-Mini reference is the
earlier same-evening, same frozen-prefix run, explicitly preserved with original
timestamps, not represented as a new cold run. Other pairs are fresh measurements.

### Short / direct route

| Model | Placement | TTFT cold / warm s | Write cold / warm tok/s | Wall cold / warm s |
|---|---|---:|---:|---:|
| Huihui Qwen3.5-27B 4-bit | 1× EXO1 | 1.403 / 0.295 | 6.730 / 6.750 | 42.169 / 40.884 |
| Huihui Qwen3.5-27B 4-bit | 2× 24/40 | 1.275 / 0.298 | 6.620 / 6.630 | 42.748 / 41.785 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 1× EXO1 | 0.387 / 0.107 | 16.090 / 16.050 | 3.192 / 2.865 † |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 2× 16/16 | 0.401 / 0.108 | 15.510 / 15.520 | 3.308 / 2.971 † |
| Orvena Qwen3.5-4B 4-bit | 1× EXO1 | 0.220 / 0.054 | 38.680 / 39.070 | 13.323 / 12.993 |
| Orvena Qwen3.5-4B 4-bit | 2× 16/16 | 0.217 / 0.051 | 36.200 / 36.180 | 14.216 / 14.036 |

† Astrea medium short generations reached EOS with45 tokens entirely classified
as reasoning: **no visible answer**, so these walls are generation/EOS times,
not successful completed-chat times. The same model with the full Hermes prefix
does produce visible answers. Supplemental short comparison explicitly disables
thinking for this nonthinking-chat fine-tune; main Hermes/Huihui stays medium:

| Astrea short, explicit none | Cold TTFT / write / wall | Warm TTFT / write / wall |
|---|---:|---:|
| 1× EXO1 | 0.394 / 16.04 / 3.334 | 0.104 / 16.04 / 2.988 |
| 2×16/16 | 0.399 / 15.44 / 3.450 | 0.109 / 15.48 / 3.108 |

The supplemental requests match across placements and both return the same
visible219-character reply,47 tokens. They are clearly separate from medium
results; no hidden promotion of reasoning text to an answer was implemented.

### Full Hermes-prefix route

| Model | Placement | TTFT cold / warm s | Write cold / warm tok/s | Wall cold / warm s |
|---|---|---:|---:|---:|
| Huihui Qwen3.5-27B 4-bit | 1× EXO1 | N/A / N/A | N/A / N/A | N/A (Metal OOM; failed after123.562s) |
| Huihui Qwen3.5-27B 4-bit | 2× 24/40 | 177.438 / 1.436 | 6.300 / 6.300 | 213.413 / 32.043 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 1× EXO1 | 50.443 / 0.447 | 15.410 / 15.400 | 60.763 / 10.193 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 2× 16/16 | 50.669 / 0.449 | 14.930 / 14.890 | 61.318 / 10.800 |
| Orvena Qwen3.5-4B 4-bit | 1× EXO1 | 28.638 / 0.259 | 33.850 / 33.880 | 33.104 / 5.083 |
| Orvena Qwen3.5-4B 4-bit | 2× 16/16 | 28.770 / 0.266 | 31.650 / 31.700 | 33.513 / 5.566 |

For valid small-model comparisons, the generated counts also match: Astrea
159 cold/149 warm; Orvena148 cold/160 warm. This avoids mistaking a shorter
answer for a placement speedup. Each condition is one observation, not a
statistically repeated performance study.

### Huihui single: complete weights, real OOM, stricter guard fix

EXO1 had171.204GB disk free before transfer,154.492GB afterward. Copied missing
Huihui shard1 (**5,343,269,992B**) over host-key-checked Thunderbolt SSH/rsync,
plus the already-present smaller model copies; all three indexed Huihui shards
are now present on EXO1. Total initial transfer ~16.7GB took51.2s. No scp/repo
copy, no deleted model, no guard override. EXO2 had~194GB free before transfers.

The stock normal load API **admitted Huihui single (HTTP200)** despite the
conservative catalog badge estimating19.09GB need versus~16GB displayed capacity.
Short54-token requests worked (6.73–6.75tok/s). The full11,322-token Hermes request
then failed **before first token** after123.562s. This was **a real Metal GPU OOM,
not a guard rejection or generic timeout**: lead log21:39:37 CST records
`kIOGPUCommandBufferCallbackErrorOutOfMemory`. Warm full was not attempted after
this failure. The Mini remained SSH-responsive; normal Stop released the model.
Do not infer that fitting~16GB of weights means the full prefilling workload fits.

This exposed a guard bug: standalone Qwen3.5 read decoder depth only from the
outer config, missing `text_config.num_hidden_layers`, then fell back to1 layer.
It advertised4096B/token instead of the intended conservative262144B/token
(64× undercount). **1976b7b** reads nested decoder depth consistently with nested
KV dimensions. Split already uses actual stage ranges and was not changed.
No safety was weakened; all subsequent smaller-model workers used the fix.
Regression: **794 tests passed in44.103s**. The original Huihui short guard
budgets1.66M/466k tokens are invalid and must not be advertised as context limits.
The performance samples themselves are real, untrimmed short replies.

No attempt was made to force the failed full-single workload past safety,
increase Metal limits or repeat the OOM. A smaller prefill batch could be a
future separate experiment, not a result in this table. Qwen3-30B-A3B4bit's
no-title-sidecar admission attempt was rejected while Huihui was resident;
it is NOT proof of intrinsic isolated-model failure. With suitable Qwen3.5
models already available, no Qwen3 fallback or new3-bit download was pursued.

### Memory and context: measured budget, not an invented maximum

All three config files specify architectural `max_position_embeddings=262144`.
That is not a promise that this hardware can hold that context. Below are the
actual conservative RAM-guard **input budgets**, already reserving1024 output
tokens on the new small-model runs and1.75GB RAM; they vary with live memory:

| Model / placement | Guard headroom cold →warm GB | Guard prompt budget cold →warm | Successfully tested full prompt |
|---|---:|---:|---:|
| Huihui / single | old metadata invalid; see below | not trustworthy before fix | 54-token short succeeds;11,322-token full OOM |
| Huihui Qwen3.5-27B 4-bit / 2× 24/40 | 2.676 →4.618 | 16,073 →27,927 | 11,322 / 11,326 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 / 1× EXO1 | 11.649 →9.833 | 87,849 →73,999 | 11,435 / 11,439 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 / 2× 16/16 | 5.427 →3.784 | 81,792 →56,714 | 11,435 / 11,439 |
| Orvena Qwen3.5-4B 4-bit / 1× EXO1 | 14.494 →12.736 | 109,554 →96,143 | 11,435 / 11,439 |
| Orvena Qwen3.5-4B 4-bit / 2× 16/16 | 7.150 →5.282 | 108,070 →79,574 | 11,435 / 11,439 |

These are dynamic guard ceilings, **not validated maximum-context sweeps**.
Only the shown~11.4k full prompts were capacity-tested successfully. Hybrids
are conservatively estimated as full KV on every decoder layer. The lead uses
all reclaimable inactive pages while peer telemetry counts half; the tighter
packer can therefore make split's advertised budget lower, not automatically
double it. No guard was relaxed to improve these numbers. Huihui single's
11.3k full OOM shows why its pre-fix optimistic limits must not be trusted.

### Preserved negative controls and operational repairs

- An old45,088,768B unopened EXO1 Orvena `.incomplete` marker blocked validation
  despite complete copied weights. `lsof` found no opener; moved it to
  `~/.caravan/day20-single/quarantine/orvena-old-model.safetensors.incomplete`,
  **not deleted**.
- EXO2 Orvena's root was a symlink to `~/.caravan/day17/Orvena-target`. Normal
  split preflight returned409: storage readiness unknown through that link.
  Preserved the link at
  `~/.caravan/day20-single/quarantine/orvena-original-root-link`, left its
  original target untouched, and made a full independent physical copy from
  EXO1 over Thunderbolt. Normal16/16 admission then passed; no forced split.
- Initial Orvena :18090 full call got502 because proxy's explicit MLX prefix
  allowlist did not include `Orvena/`; direct :18190 worked. Added that namespace
  via the existing `--mlx-prefixes` configuration and reloaded **only idle proxy**.
  Current list `mlx-community/,huihui-,Orvena/`; no Hermes config edit. A rapid
  bootstrap got launchd EIO; after confirming the old job exited, the same
  bootstrap succeeded without root or another route.
- Original harness treated an intentional single-load400 as exit0, allowing
  two “Astrea” samples to run on still-loaded Huihui. Entire mislabeled control
  is retained under `invalid-model-identity-control/`, **excluded**. Controller
  now fails every non200 and requires model/changedPID/placement/KV/health match.
  Normal Stop before each load releases prior GPU allocations; this is not a
  memory override. Active bad client was canceled and owned harness stopped.
- Full single-Huihui Metal failure, namespace502 and storage409 are preserved
  separately, not silently converted to successful timings. The safe controller
  restored Huihui24/40 on both interrupted passes before continuation.
- First independent monitor used system Python3.9, which could not import
  union annotations and returned synthetic24/12GB fallback. Those samples are
  **discarded**. Native-venv real-vm-stat monitor produced226 valid samples,
  zero SSH errors,21:37:13–21:56:38 CST. Minimum reported available1.100GB;
  reported swap used1111.94–1312.00M, not runaway growth or a system hang.
  The watcher was stopped after final verification.

### Conclusion and final state

For **one active dense-model chat on these two M4s**, splitting does not deliver
2× speed. Astrea full decode15.41→14.93tok/s (~3% slower split); Orvena
33.85→31.65 (~6.5% slower), with essentially unchanged cold TTFT. Even Huihui
short decode is slightly faster single6.73 versus6.62. Fit-on-one models usually
benefit from avoiding the extra serial hop; repeated measurements would be
needed to distinguish very small timing differences confidently.

Splitting's demonstrated win is **capacity / per-process GPU working memory**:
Huihui full Hermes succeeds split, but OOMed single under the tested defaults.
Do not infer a doubled usable context: current live peer-limited guard budgets
above did not increase. Multi-chat pipelining or >2 physical Minis was not tested
here and could have a different aggregate-throughput result.

Final normal load restored **Huihui EXO2→EXO1 24/40, KV16**, saved as auto-restore.
Real :18090 full19-tool, medium-reasoning reply finished `stop`: “I'm online and
ready to help.” **.405s native TTFT,6.21tok/s,11.372s wall**,11,309/11,310 prompt
tokens reused (existing exact session restored, not a fresh-prefix speed claim).
Title sidecar restored and health200. No model deletions, release, tag or video.
Existing untracked backups remained untouched. Final docs/evidence commit is
recorded in Git; both Minis are synced by `git pull --ff-only`.

Raw provenance/scripts: `handoff/lab/day20-single/`; Omarchy originals
`~/day20-single/`. Frozen private system/tool requests remain uncommitted in
`~/day20-speedups/private/` (new private path is only a symlink to that dataset).

## Day20 wrap and release

Brenden approved release, main fast-forward, video and local X drafts. Tonight's
unreleased recovery work belongs to Day20; Day19 is already posted. The plain
experiment-by-experiment story and caveats are in [DAY20-RELEASE.md](DAY20-RELEASE.md).
Historical “not tagged/video pending” statements above describe their phase,
not the final wrap state. Measurements are not relabeled: prefilling is not a
visible answer, n-gram copy improvement was~60%, not2×, and helper boot ordering
was not physically reboot-proved. No extra reboot or main worker restart for
the wrap. Final tag: `day20-2026-11-09` on `caravan-v3-mlx-split`; main receives
the identical checkpoint by fast-forward. Public drafts and video sources are
under `handoff/lab/videos/day20/`; no private prefix or model weights included.

Fresh pre-release regression on box:794 tests passed in43.223s; no failures or skips. Video37.000s, real UI crops plus explicitly labeled historical summaries; no new model-load experiments or reboots. Film source/caption manifest: `handoff/lab/videos/day20/`.

### Published release / downloaded-package verification

- Published22:16:40 CST: https://github.com/linuxbren/caravan/releases/tag/day20-2026-11-09
- Immutable annotated tag points to `fdb894e`; working branch and main were fast-forwarded to that checkpoint. Later documentation-only verification does not move the tag.
- Assets: `caravan-day20.tar.gz`18,184,498B, SHA256 `d1c98a8d3a18705c36a32fa453194198b7ab8bdb16a5d96c30d82ecb30c11e15`; ZIP19,225,830B, SHA256 `5a9b3b027e49b3946b03167cd81736a1abf2d8a635c3d00595384596530c7387`.
- Downloaded the published tar asset, verified its digest/INSTALL.md, extracted into a fresh box directory, ran full stdlib suite there: Ran 794 tests in 44.277s; OK. Zero failures/skips; no clean-Mac install claim. Initial verifier invocation used a not-yet-created working directory and did not run; corrected to create/extract from the existing parent, then this complete verification passed.
- Video: `/workspace/caravan-day20.mp4`, Omarchy `~/day20-video/caravan-day20.mp4`,37.000s,1280×720/24fps,637,255B, SHA256 `0f67a9d41441b7b1bccedcefa1cf12d8e7acf535804cdcf2fdabf947bc32c76d`.
- Final wrap full-prefix19-tool, medium-reasoning reply ended22:17:03.636 CST: “I'm online and ready to help.” .314s native TTFT,6.24tok/s,11.255s wall,finish stop. Huihui EXO2→EXO1 24/40 KV16 ready and saved; no service restarts or model unloads for wrap. This is warm verification, not a new cold performance claim.
- Both draft files copied to `~/Pictures/x-posts/day20/`; nothing sent to X. X engagement tone/audience proofread remains for the parent to route; it was not available in this executor's tool surface.
