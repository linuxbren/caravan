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
