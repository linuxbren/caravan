# Caravan web UI (Day 15)

A small browser UI so you can *use* what Days 1–13 built: switch models
already on the Minis, chat with live streaming, and see honest timestamps
and tok/s from the real worker — never invented numbers.

## Open it

On EXO1 (lead):

```sh
cd ~/dev/caravan-v3
# Low Power Mode must be off on both Minis for any timing.
pmset -g | awk '/lowpowermode/{print}'
python3 proxy/web_server.py --host 0.0.0.0 --port 8190
```

Then open one of:

- Tailscale: `http://100.68.62.20:8190/` (EXO1)
- LAN / `.local`: `http://prf-hays-exo01-2.local:8190/`

The page is reachable on your home network and Tailscale only (same posture
as the agent `/health` endpoint). There is no login.

## What it does

1. **Model picker.** The **Models** drawer (left dock, like Topology) searches
   HF / GGUF / Cloud, color-codes **capacity-based** fit (unload RAM + disk),
   downloads MLX shards per Mini in parallel (placement: 1 / K-split / all; truthful progress under hf_xet via nettop fallback; loads respect placement — one-Mini skips the packer), and lists on-disk models plus HF
   cache / guess-ahead drafts with delete-all. Full design, bugs found, and
   gaps: [MODEL_PICKER.md](MODEL_PICKER.md). Settings still lists models
   already on disk. Load starts Packer 1 on EXO2 over Thunderbolt SSH, then
   the lead worker on EXO1 (ports **5560** / **8194**).
2. **Chat.** OpenAI-shaped `/v1/chat/completions` under the hood, streamed
   word by word. Session key is sticky per browser tab so shared-start and
   the prompt cache can help.
3. **Timestamps to 0.01 s.** Browser → Caravan received → first word → done,
   with gaps. The UI syncs clocks with an NTP-style `/api/time` exchange and
   shows the offset and uncertainty.
4. **Per-reply stats.** Total time, tokens read + tok/s, tokens written +
   tok/s, and which features fired (shared start hit, guess-ahead accept
   rate, tuned settings) — all from the worker’s `usage.caravan` block.
5. **The string.** Live lead / packer view (layers, GB) plus a “how far
   we’ve come” strip fed by `proxy/web/journey.json` (Days 1–13 lab numbers).

## Start / stop

| Action | Command |
|---|---|
| Start UI | `python3 proxy/web_server.py --host 0.0.0.0 --port 8190` |
| Stop UI (keeps workers) | Ctrl-C in that terminal, or `curl -X POST http://127.0.0.1:8190/api/shutdown` |
| Unload model from UI | Unload button, or `curl -X POST http://127.0.0.1:8190/api/models/stop` |
| Panic stop test workers | On each Mini: Use `python3 proxy/worker_ownership.py --worker /absolute/repo/agent/mlx_worker.py --pid-file ~/.caravan/web-ui/lead.pid --port 8194` on that Mini; never sweep by process name |

Env knobs (optional):

- `CARAVAN_WEB_PORT` (default 8190), `CARAVAN_WEB_LEAD_PORT` (8194)
- `CARAVAN_WEB_PACKER_PEER` (`169.254.103.191:5560`)
- `CARAVAN_WEB_PACKER_SSH` (`brenden@169.254.103.191`)
- `CARAVAN_WEB_NO_DRAFT=1` to force `--no-split-draft`

## Layout in the repo

| Path | Role |
|---|---|
| `proxy/web_server.py` | HTTP server + chat proxy + timing stamps |
| `proxy/web_workers.py` | Lead/packer start/stop + log progress |
| `proxy/web_catalog.py` | Models already on the Minis |
| `proxy/web_timing.py` | Clock-offset + gap + reply-stat math |
| `proxy/web/index.html` | The page |
| `proxy/web_picker.py` | Model picker catalog, fit, download jobs |
| `proxy/picker_disk_sizes.py` | On-disk / cleanup sizes (lead + SSH packer) |
| `proxy/web/journey.json` | Real v0→Day 13 numbers for the strip |
| `tests/test_web_server.py` | Endpoint + timing unit tests |

## Safety

- Binds `0.0.0.0` on purpose so Tailscale/LAN can reach it; do not port-forward it to the public internet.
- Only starts/stops `mlx_worker.py` on the Day 12/13 test ports. Never touches `main`, tags, Talaria Hub, exo, or Hermes.

## Day 15 bugfixes (send state + Gemma stall)

- Chat/stop always drain the POST body before answering so HTTP/1.1 keep-alive cannot glue the next request onto leftover JSON (`Bad request syntax`).
- SSE chat responses send `Connection: close`.
- UI clears in-flight chat on Load/Unload/Clear (`AbortController`), so Send re-enables whenever status is `ready`.
- Chat shows a `thinking…` placeholder immediately, enforces a 45s first-token / 180s total timeout with a visible error, and strips end markers (`<|im_end|>`, `<turn|>`, …) in the proxy and the page.



## Topology

Left drawer (mutually exclusive with Models). Polls `/api/nodes` every
**500 ms** while open and the tab is visible. Mac mini silhouette cards
(variant A), sticky last stats, temperature bar 20–100 °C, Heat / Theme bar
colors (Settings). GPU % comes from ioreg utilization — macmon can read 100%
under keepalive. Chat history is sent in full (not only the latest message).
Memory-guard trims show as “Moved N…” under replies; notes live on EXO1 only
(`~/.caravan/memory`). Details that overlap the picker are in
[MODEL_PICKER.md](MODEL_PICKER.md).

## Optimization toggles (Day 15)

The **Optimizations** card (right column) sets how the current model runs.
Each option is **Auto** (Caravan decides, using what it learned for that model)
or pinned. **Apply & restart** reloads the current model on both Minis with
those choices (same path as Load model, about 10–40 s). Every option maps to a
real `agent/mlx_worker.py` flag; nothing else is changed.

| Option | Choices | What it does | Worker flag |
|---|---|---|---|
| Guess-ahead | Auto / On / Off | A small helper model guesses a few words; the big model checks them in one pass. | Off `--no-split-draft`, On `--pin-guess-ahead` (learn can't turn it off) |
| Self-tuning | Auto / Off | Tries settings on real chats and keeps the faster ones per model. | Off `--no-learn` |
| Shared start (trim / rebuild) | Auto / On / Off | Reuses the already-read start of a repeated system prompt — trims memory back to it, or rebuilds it on both Minis for models that can't be trimmed (Gemma). | On `--split-shared-prefix-cache`, Off `--no-split-shared-prefix-cache` |
| Two chats | Auto / 1 / 2 | Overlaps two chats across the Minis. | `--split-pipeline-chats N` |
| Fused kernels | Auto (off) / On | Experimental combined GPU steps. | `--fuse-kernels all` (both Minis) |
| Memory compression | Auto (16-bit) / 8 / 4 | Stores chat memory in fewer bits (less RAM, slightly lower quality). | `--kv-bits N` (both Minis) |
| GPU keep-warm | Auto (on) / Off | Keeps the lead's GPU warm while waiting on the packer. | `--no-split-keepalive` |

What's actually running is shown three ways:

- **Next to the model** ("running with …" chips), read from the lead's new
  `GET /caravan/settings` endpoint (`/api/status` → `active`).
- **Under every reply**: `ran with: …` is what the worker used *for that reply*
  (guess-ahead shows how many words came from the helper), and `chosen: …`
  is what you picked. "(pinned)" means self-tuning can't change it.
- **In the lead log**: one `active settings: {...}` line at startup
  (`~/.caravan/web-ui/lead.log` on EXO1).

With Auto, self-tuning may flip guess-ahead, shared start, or two chats
between replies while it explores — the per-reply line shows when it did.

Fix that came with this: with two chats on, a learned "guess-ahead off" was
ignored (the two-chat path always used the helper). It's honored now.

### How to test it yourself

1. Open http://100.68.62.20:8190/ and refresh. Load a model with everything on **Auto**.
2. Send the same short message twice (e.g. "Name one planet."). Note *To first word*,
   *Write* tok/s, and the `ran with:` line under each reply.
3. Set one option (say Guess-ahead **Off**), click **Apply & restart**, wait for *ready*.
4. Send the same message twice again. The `ran with:` line should now say
   `guess-ahead off (pinned)`; compare the speeds with step 2.
5. Put it back to **Auto** and Apply. Repeat for any other option.
   Tip: compare the *second* reply of each pair (the first pays a one-time warm-up),
   and keep Low Power Mode off on both Minis.

## Page layout (Day 15)

Most important first, top to bottom: **Chat → Last reply → Settings** (model
picker, Load/Unload, "running with" chips, Optimizations) **→ Clock sync |
Milestones → How far we've come → Load progress | The string** (the
lead/packer diagram: which layers sit on EXO1 and EXO2). On wide screens the
paired cards sit side by side in that order; under 820 px everything is one
column in the same order. `tests/test_web_server.py::PageOrderTest` guards it.

## Self-tuning for every option + Deep optimize (Day 15)

- With Self-tuning on Auto, the learner now also tries **memory compression,
  fused kernels and GPU keep-warm**. These only change on a model load, so a
  trial is queued, used on the next Load / Apply & restart, scored over 3
  replies, then kept or rolled back. Pinned values (On/Off/8/4) are never
  touched.
- Under the Optimizations list the page says what is going on, e.g. "Self-tuning
  wants to try memory compression 8-bit — click Apply & restart" or "trying …:
  2 replies left".
- **Optimize this model**: pick **Deep** (default; all options, reloads itself
  between trials, only when no chat is in flight) or **Quick** (live options
  only), press Start, and walk away. Progress shows the phase, prompts, reloads,
  option values tested and a time-left estimate built from measured reply and
  reload times. Cancel stops after the current step. The final winners stay
  saved for that model (`~/.caravan/mlx/tuned-settings.json`).
- A tip appears when a model has fewer than 10 learned replies.
- Each run uses a fixed prompt set (short, long, predictable, and a >512-token
  shared opening) in fresh sessions, plus a pair sent together every 5th
  prompt so "two chats" gets concurrent samples. Caps: Quick 60 prompts, Deep
  180, and it stops early if 30 prompts add no new coverage.
- The web server now re-adopts a lead it started earlier after a web-only restart.


### Model picker API (`/api/picker/*`)

See [MODEL_PICKER.md](MODEL_PICKER.md) for behavior. Short map:

- `GET /api/picker/search?q=&source=&filter=&newer=1&limit=` — catalog + capacity fit
- `GET /api/picker/disk` — installed + cleanup rows (HF cache, drafts)
- `POST /api/picker/download` `{repo_id, packer_layers?}` — parallel lead+packer fetch
- `GET /api/picker/jobs[/id]` — byte progress; `POST .../download/cancel` kills fetches
- `POST /api/picker/delete` `{id|kind, confirm:true}` — models or `hf-cache` / `drafts`
- `POST /api/picker/fit` — ad-hoc fit check

GGUF catalog: Hugging Face (`bartowski`, `unsloth`, `lmstudio-community`).

## Settings model list

Built from real MLX trees on configured Minis (`model_inventory`), not the static
catalog. See [MODEL_PICKER.md](MODEL_PICKER.md#settings-model-dropdown-load-list).


## Topology (N Minis)

The Topology left drawer reads `/api/nodes`, which gathers every Mini listed
under `[web.nodes.*]` in config (default: EXO1 lead + EXO2 packer). Each node
gets a card with CPU / GPU / RAM / Disk / Temp, layers held, and live/offline.
Offline Minis keep a card with an error; last-good metrics are not blanked by
a failed poll. Single-Mini loads on a non-lead Mini (placement `mode: one` on
EXO2) run the worker there; the web host tunnels `lead_port` so chat and
health keep using `127.0.0.1`.


### Per-node model label and chat empty state
- `/api/nodes` sets `model` only on nodes that host the loaded model (`gather_all(..., running_on=[ids])`). Idle nodes get `model: ""` and `layers: null`; the card shows "idle · no model". Split runs list the model on every stage with its layers.
- The cache is keyed on (ready, model_name, split). On a change, the request waits up to 5 s for a fresh gather instead of serving the stale one.
- `#emptyState[data-kind="intro"]` is repainted from status: "<model> is ready." when ready, otherwise the pick-a-model hint.


### Themes: Amber, Green, Meadow
- `html[data-theme]` selects the theme; the choice is saved in localStorage `caravan-theme`.
- **Meadow** is a light, calm theme meant as a way to "digitally touch grass". The `.meadow-bg` layer is an inline SVG painting (sky, clouds, trees, fields, a misty river) with no photos or outside files. It is blurred heavily (`filter: blur(34px)`) so it gives an impression of nature without pulling attention from the chat. It drifts very slowly (120 s, about ±1.2%), and the drift stops under `prefers-reduced-motion: reduce`.
- Meadow turns off the CRT layers (`body::before/after`, `.crt-wash`) and text glow. Panels, drawers and Mini cards use frosted glass (`backdrop-filter: blur(18px)`) with dark text for WCAG AA. Fonts are a rounded sans stack, with `--statmono` used for stats and logs. Bars: in Theme mode lo/mid/hi are leaf green, green and sky blue; Heat mode is unchanged.
- Layout: `.drawer #optRows` uses `auto-fit, minmax(300px, 1fr)`, so the 380px Settings drawer shows one column. Under 820px, `.empty` gets a top margin so it clears the stacked chat buttons.

- **Nebula** uses the real JWST "Cosmic Cliffs" image of the Carina Nebula as a fixed, unblurred `background-size: cover` layer (`.nebula-bg`), positioned at `50% 82%` so the cliffs sit along the bottom. It has a very slow 180 s drift and zoom (about 3%) that stops under `prefers-reduced-motion`. The image is `proxy/web/assets/nebula-cosmic-cliffs.webp` (2400×1390, about 282 KB), with `nebula-cosmic-cliffs.jpg` (1920 wide, about 323 KB) as the fallback via `image-set()`. `web_server.py` serves `/assets/<file>` from `proxy/web/assets/` with the right image MIME types and a one-day cache. Dark frosted panels (`backdrop-filter`) keep the text readable; the accents are copper `#e0893a` and ice blue `#7cc4ff`.
  - Credit, shown as a small bottom-right caption only in Nebula: "Image: NASA, ESA, CSA, STScI". Source: https://esawebb.org/images/weic2205a/ (file: https://cdn.esawebb.org/archives/images/large/weic2205a.jpg). Webb images released by ESA/Webb are CC BY 4.0, and NASA-produced imagery is generally not copyrighted; both ask for the credit line above.

## Day 17 performance experiments

- **Guess-ahead → Native MTP · test** appears only for an inventory entry with an
  installed `caravan-mtp` head. This is a matching dense Qwen3.5/Orvena checkpoint
  experiment, not an interchangeable helper for Qwen3 30B-A3B. Single Mini only,
  temperature 0, no repetition penalty, fresh request caches; no shared-start or
  persistence benefit is claimed for this path. It disables learning during the
  experiment. Selecting it requires a load/restart, not a hot toggle.
- **Prompt lookup (experimental)** is separate from two chats: Adaptive uses
  `--split-prompt-lookup 3 --split-prompt-lookup-adaptive` and overlap_on=0.50.
  Auto/off retains the off default. Adaptive pins one split chat and refuses
  an explicit Two chats=2 combination (the pipeline does not implement PL).
  Split only; rejected before unloading a
  single-Mini model. Existing workers need a reload to enable it.
- Two chats overlaps stages only in a split. Single-Mini requests remain serial.
  Split draft block verification is experimental and unit-tested; live benchmark
  awaits approval. Chips report actual capability when the worker exposes it.
- Numbers, exact prompts/settings, negative results and CT times live in
  [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md), not inferred from UI settings.

### Day 17 concurrency caution
The first EXO2-only MTP benchmark was interrupted by a separate UI load/stop.
Current worker cleanup includes broad `pkill -f mlx_worker.py`, so do not run
independent experiments while another browser/agent switches or stops models.
[Raw data and state evidence](DAY17-BENCHMARKS.md) preserve all eight failed
requests. Native MTP remains explicitly experimental; its completed small quality gate
or validated speed gain is claimed. PL and two-chat defaults are unchanged.

### Scoped worker ownership (Day 17 follow-up)
UI stop/replacement now validates the tracked PID's exact repository script and
endpoint before SIGTERM, and rechecks identity before any SIGKILL escalation.
Local lead, remote single-Mini lead and packer each have separate PID markers,
repo paths and endpoints. A missing/stale marker fails closed; no process-name
sweep or arbitrary old-PID kill is used. An EXO2 worker on :8294 survives a stop
of the UI-owned :8194 or packer :5560. Historical lab sweeps were removed (no-op
cleanup); those old scripts now require explicit scoped cleanup before reuse.

Serial rewindable models (including single-Mini Qwen3) now support adaptive
prompt lookup; HTTP requests can select `prompt_lookup: "off" | "adaptive"`
without changing saved UI choices. Overrides restore in finally on error/cancel.
Adaptive still pins one chat. Two-chat overlap remains a split-only capability;
two requests to a single-Mini worker are queued, not batched decode.

### Day 17 clean native-head results
Native MTP stays labelled **test**, visible only for installed matching heads.
On EXO2 Orvena4B, OFF/ON/ON/OFF measured36.95→54.13 median Write tok/s,
98.21% proposal acceptance. Count/exact answers match; sorting code passes its
3 asserts+7 extra cases, but assertion examples differ across modes. This is not
a Qwen30B upgrade and not a general quality guarantee. Full TTFT, all individual
runs, initial failures and commands: [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md).
The initial adaptive Qwen comparison was slower and exposed one-miss poisoning;
the full-window high-overlap fix raises repeated copy50.11→72.37tok/s, but mixed prompts50.24→47.31. Default remains off. Experimental modes disable learning and skip learned reload trials; native refuses compressed caches and simultaneous adaptive PL.

## Picker: placement step, honest progress, On disk in Topology (Day 17 follow-up)

**Placement step.** Picking a quant opens "Step 2 · Choose where it lives" right under
it, with the recommended option pre-selected. The button says what it will do:
"Download 0.28 GB to EXO2", "… split across EXO1 + EXO2", "… to each: EXO1, EXO2". Works for
any node count; no sort menu.

**Progress — what was wrong (found Nov 6, 2026).**
1. Remote Minis never reported anything. The measure script was sent over ssh quoted with
   `repr()`, which is not valid shell → `SyntaxError` on every poll → fallback
   `{have_bytes:0, source:"starting"}`, which `_watch` passed through without pct/msg.
   Fix: `shlex.quote`, `~/` → `$HOME/`, and `measure_error` surfaces as "can't read progress: …".
2. hf_xet single-file downloads are invisible on disk until the file lands (no growing
   `.incomplete`, hook file says 0). Fix: find the fetch's process tree with `ps`
   (excluding the probe itself), sum per-process `nettop -x` `bytes_in`, and prefer the
   network count when it is ahead of disk.
3. Progress is folded monotonically (`monotonic_snap`): bytes/pct never go backwards, pct
   capped at 99 until done; each Mini ends Done / Stopped / Failed. The job card is per
   Mini with bytes, MB/s, ETA and an All-Minis total, and is re-adopted from
   `/api/picker/jobs` when the drawer reopens. A finished download offers Load instead of
   auto-loading over a ready model.

**Placement saving.** Remote runners now write `caravan-placement.json` on their own Mini
(ssh). Before, it was written locally on EXO1, leaving placement-only folders there and
none next to EXO2's weights, so an EXO2-only model showed "not on EXO1".

**Single-Mini on any node.** `web_catalog` accepts a full copy on any configured node
(placement file or not) and targets that node; `_resolve_worker_node` routes the load to
the remote single-Mini worker.

**On disk** moved from Models to the bottom of the Topology drawer: one combined list,
each row with size per Mini and a location note (`EXO2`, `split EXO1+EXO2`, `all`,
`partial on …`). Delete (stop-then-delete) and the HF cache / guess-ahead rows stay. Models
has a small "On disk → Topology" link.

### Test record (Nov 6, 2026, CST)
| Run | Model | Size | Placement | What happened | UI / API |
|---|---|---|---|---|---|
| Before (Brenden's job `ed0cbfa32943`) | mlx-community/Astrea-R8-Chat-9B-OptiQ-4bit | 8,012,768,155 B | one: EXO2 | disk 2.7 GB @ ~20:44, 5,441,048,548 B @ ~20:48, done ~20:52 (7.85 GB) ≈ 11 MB/s | API `have_bytes 0`, source "starting", no pct for the whole run, then "100% done" |
| After fix 1 | mlx-community/Qwen2.5-0.5B-Instruct-4bit | 278,064,920 B | one: EXO2 | started ~21:01, done at 33 s ≈ 11 MB/s | starting… 0–9 s, 2 MB/278 MB at 12 s (0.5 MB/s, ETA 9m52s), stuck at 2 MB (xet), Done at 33 s |
| After fix 2 (process-tree nettop), 21:31 | Qwen2.5-0.5B-Instruct-4bit | 278,064,920 B | one: EXO2 | done in ~27 s ≈ 10 MB/s | API every ~2.5 s: 0 → 32 KB → 65.7 MB (23%, 10.9 MB/s) → 145.4 MB (52%, 13.2 MB/s) → 179.6 MB (64%) → Done 278 MB. Late measure briefly reopened Done as 99% → fixed (sticky final state) |
| Copy to all #1, 21:33 | same | 2 × 278 MB | all (EXO2 + EXO1) | EXO2 moved 0→130 MB; EXO1 showed **851.20 GB** | local nettop parse took the biggest number on any row → fixed (only the requested pid, `-x`) |
| Copy to all #2, 21:36 | same | 2 × 278 MB | all | EXO2 live to 145 MB; EXO1 stuck at 4 MB until Done | local Mini used the in-process hook, blind to xet → local now uses the same process-tree measure |
| Copy to all #3, 21:38 | same | 2 × 278 MB | all | both done in ~48 s; All Minis 556 MB | both bars live and monotonic: EXO1 4→15→29→51→73→97→121→148→157→174 MB, EXO2 0→42→82→106→135→164 MB, 3–9 MB/s each, then Done 278/278 on both |

Known limit: hf_xet moves compressed/deduped chunks, so network bytes reach only ~55–65% of
the file size before the files land; the bar then jumps to Done. It never stalls at 0 or goes
backwards. Updates arrive every ~2.5 s (one `nettop` sample per measure).

Read/Write live check (21:41 CST, Qwen3 30B-A3B on EXO1, chat only):
`Read 25 tok at 71 tok/s · Write 50 tok at 50.9 tok/s · first token 0.41s · total 1.39s`.

EXO2-only check (read-only, `/api/models`, 21:40): Astrea-R8-Chat-9B-OptiQ-4bit, Orvena-4B-MLX-4bit
and the test Qwen2.5 on EXO2 all `usable: true, run_mode: single`, placement `EXO2`. Not loaded.

## Chat: Read / Write tok/s
Under each reply: `Read <in> tok at N tok/s · Write <out> tok at M tok/s · first token Xs · total Ys`. Unknown counts/rates/times are dropped from the line.
Read = prompt tokens / prefill seconds, falling back to time-to-first-token when the worker
doesn't report prefill (`web_timing.reply_stats`).

### Day 17 single-Mini two-request result and limits
Two chats only overlaps stages in a split. Qwen single/EXO1 still serializes
requests: median server Write50.51 vs50.48tok/s (one vs two queued requests),
harness aggregate46.08 vs46.52. No default change or split-overlap claim.
Worker TTFT excludes queue wait; harness wall includes state guards. The UI
shows **single Mini, serial**, and prompt-lookup help shows both copy speedup
and mixed-prompt regression. Approved split block verification is now labelled
**Qwen N2 tested, helper slower**. Raw prompts, all successful/partial attempts and
negative exact-format checks: [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md).

### Approved split results shown in the controls
- **Two chats** help: Qwen30B4-bit split, baseline aggregate one→two chats
  **41.54→70.49tok/s**. Single-Mini requests still queue.
- **Guess-ahead** help: split one-chat aggregate**41.54→52.11tok/s**, but
  two-chat**70.49→49.77tok/s** (helper slower). N2 remains experimental; no
  global default promoted on these short tests. Active chip says
  `split block verify · Qwen N2 tested, helper slower`, not “awaiting benchmark”.
- Measured with helperQwen3-0.6B4-bit, k3, KV16, learning/shared-start/PL off,
  count/code/exact prompts.36/36 uncapped replies; count and sorting3+7 pass,
  strict exact-format fails all configurations (trailing spaces). Aggregate
  counts each concurrent wave once; worker TTFT is not client queue latency.
- Concurrent HTTP memory guards now queue packer stats to the socket-owner thread
  between fully drained pipeline rounds. Mutating jobs still wait for idle.
- Final singleEXO1 Qwen ready PID89648, preferences allAuto, helper/PL off,
  pipeline1, self-tuning on. Auto applies an existing queued**KV4 trial** with
  incumbentKV16; this is not the pinnedKV16 benchmark setting. No model reload
  for label-only changes; web help refreshed with KEEP_WORKERS=1. An already
  loaded worker may retain its older literal status-description string until
  next normal load; UI labels/help use the completed result.
- Orvena experiment and EXO2 packer stopped; matching Orvena target/head and
  existing EXO2 Qwen kept. All raw prompts/settings/commits/CT times,12 errors,
  and152-test+4subtest validation: [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md).
  Screenshot capture still requires parent browser tools.

Final served-UI proof (10:08:53 PM CT): webPID87870→89854, unchanged QwenPID89648,
ready/singleEXO1/allAuto/KV4 trial; both chip and help verified over HTTP:
[`split-final-ui-proof.json`](../bench/results/day17/split-final-ui-proof.json).

## GGUF split from the web UI (Day 17, Nov 6 2026)

**Gap found.** The command line has split GGUF models across Minis since
Sep 5 (ae838f1, 4.23 tok/s): `rpc-server` on each packer, `llama-server --rpc`
on the lead. The web UI could not load a GGUF at all: the workers were
MLX-only (preflight required `config.json`), the picker answered "GGUF /
llama-server load is phase 4", GGUF downloads returned 400, and fit never
allowed a GGUF split.

**What changed.**
- Settings → Model lists every GGUF on the lead (`~/.caravan/models`,
  shards 2+ and mmproj skipped). Choosing one shows **Where it runs**:
  *One Mini · EXO1*, then *Split across K Minis* for K = 2..N online Minis.
  Default = smallest option that fits (≈75% of each Mini's RAM is usable by
  the GPU; weights + 1.5 GB headroom).
- Load (`proxy/web_workers.py` `_load_gguf`, helpers in `proxy/gguf_split.py`):
  for each peer, SSH starts `ggml-rpc-server -d MTL0 -H 127.0.0.1 -p 50052 -c`
  (PID recorded in `~/.caravan/web-ui/rpc-server.pid`), the lead opens an SSH
  tunnel `127.0.0.1:5006i → peer 127.0.0.1:50052`, then runs
  `llama-server --rpc 127.0.0.1:50062,... --device MTL0,RPC0,... --tensor-split`
  shares proportional to RAM. Everything started is tracked in
  `~/.caravan/web-ui/gguf.json`; Stop / a new load kills only those PIDs after
  checking their command line (no pkill).
- **Peers don't need the file.** llama.cpp ships each peer its tensors over the
  link at load; `-c` keeps them in the peer's cache. Measured: 18.6 s
  page-to-ready for the 17.46 GB Qwen3 30B Q4_K_S split (14.1 s llama-server load).
- A failed load cleans up the remote rpc-server and tunnel and leaves the page
  **idle** with one plain line (e.g. "Couldn't reach EXO2 for the split. Try
  again.") and the log tail under a collapsed **Details**.
- Status carries `gguf: {nodes, labels, mode}` so Topology shows the model on
  every Mini in the split. llama-server `timings` feed the same Read / Write /
  first-token line as MLX.
- MLX-only Settings (guess-ahead MTP, keep-warm, KV bits…) are ignored by the
  GGUF path; llama-server runs with `-c 8192 -ngl 999 -fa on --jinja`.
- Picker search: GGUF fit allows a split across all online Minis.
- **Picker downloads (Nov 7, b2b2c26).** Picking a GGUF quant downloads that one
  file to the lead Mini only (`~/.caravan/models/<owner>--<repo>/`): llama.cpp
  sends each peer its share at load, so peers need no copy. It reuses the
  regular job system (network-byte progress, Stop, Resume, auto-retry); the
  placement is fixed to "GGUF to EXO1 · runs on one Mini or split at load" and
  where it runs is chosen in Settings. A finished download auto-loads only
  when nothing is loaded (via its `load_id`, `gguf/<file stem>`); otherwise it
  offers Load. Live test 00:00–00:03 CT Nov 7, Llama-3.2-1B-Instruct-Q4_K_M.gguf
  (807,694,464 B): 49 s at ~13 MB/s, listed as `gguf/Llama-3.2-1B-Instruct-Q4_K_M`,
  worker stayed idle (API path, no auto-load). Stop at 19 % → cancelled, no
  fetch process left; **Resume restarted from 0 %** (the partial was 16 KB after
  Stop — hf's single-file partial isn't kept), finished in 74 s. Known limit.
  Test file deleted afterwards.
- **Hardening (Nov 6 late, afcf070 / 2e1f6b5).** MLX-only Settings rows are
  labelled and disabled when a GGUF is selected (theme parity 24/24). After a
  web restart (KEEP_WORKERS) the server re-attaches to llama-server, tunnels
  and rpc-servers from `~/.caravan/web-ui/gguf.json`, reopening dead tunnels.
  `--tensor-split` comes from each Mini's live free RAM (e.g. 20.3:15.6). A
  watchdog cleans everything up and goes idle ("Lost EXO2 during the split.
  Load it again.") if llama-server dies; chat answers a plain 502. Topology
  labels Minis by name ("EXO1 · lead", "EXO2").

**Live numbers** (Qwen3-30B-A3B-Q4_K_S.gguf, 17.46 GB, EXO1+EXO2, llama.cpp
b10819, 3 prompts × 3 runs, max_tokens 256, temp 0.6; raw rows in
`bench/results/day17/gguf-split.jsonl`, script `bench/gguf_split_bench.py`):

| CT | commit | placement | load s | Write tok/s median (min–max) | Read tok/s median | first token s median |
|---|---|---|---|---|---|---|
| 23:28 | 2dcca97 | split EXO1+EXO2 (first, cold) | 18.6 | 34.52 (34.20–35.08) | 96.06 | 0.255 |
| 23:31 | 8007789 | split EXO1+EXO2 (warm) | 18.6 | 34.72 (34.13–35.09) | 105.51 | 0.256 |
| 23:32 | 8007789 | one Mini EXO1 | 13.3 | 42.86 (41.61–43.66) | 111.99 | 0.241 |

Split is ~19% slower than one Mini for a model that fits on one — the split is
for models that don't fit (that's why one Mini is the default here). Manual
check before wiring: 33.2 tok/s write through the SSH tunnel.

**Failed runs (kept for the record).**
- 23:14 CT, 8a29227: bench saw the old MLX "ready" before the switch began
  (bench race, fixed); the load was then cut off by a web-server restart from
  parallel work. 9 chats failed (409 / connection closed). Not a measurement.
- 23:16 and 23:18 CT, d326874: `llama-server` aborted
  `ggml-rpc.cpp:547: Failed to connect to 169.254.103.191:50052` (rc −6). The
  peer listener never saw the connection; the same command run from an SSH
  shell connected. Same symptom llama.cpp's own `transport.cpp` comment notes
  for launchd-supervised processes (macOS local-network restrictions). A direct
  rpc-server with no gate failed the same way, so it was not the allowlist gate.
  Fixed by tunnelling over SSH to loopback (2dcca97).

## Day 18 (Nov 7, 2026)

- After a download, with no model loaded: dialog "No model is loaded. Load <name> now?" → Load now / Not now.
- Resume uses HTTP Range on `.cache/huggingface/download/<file>.incomplete` (`agent/range_fetch.py`).
- Progress: `.incomplete` beside a finished file counted once; per-Mini total from the fetcher's `my_gb`; capped; stall = no growth on any signal.
- `caravan-placement.json` now has `packer_layers` and `n_stages`.
- GGUF: downloads go to every online Mini; split loads seed peers' rpc cache from their own copy (`agent/gguf_rpc_seed.py`). Notes show "EXO2 loads its share from its own disk: N tensors, X GB".
- Records: [DAY18.md](DAY18.md).

## Tests
Full suite (no Minis needed): `PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests` (350 OK, 2026-11-06 11:30 PM CT; 340 OK earlier).
HTTP tests stub SSH and node probes. If stopping the packer fails, `/api/models/stop` now answers 502 with `{"error", "worker"}` instead of dropping the connection.

### Settings drawer visual alignment (Nov 6, 2026, 10:46 PM CT)

Settings now uses the Models/Topology drawer vocabulary: shared section panels
(the same border/background as model rows), uppercase section captions, monospace
labels, muted help text, and a shared compact control tier. The three drawer Close
buttons share that tier too. There are no setting, API, or JavaScript changes.

Audit before: the 390px Meadow preview mixed 16px action type with 11.52px toggle
type and 10.4px bar-switch type. Action padding was 10×12px, toggle padding
4×10px, bar-switch padding 6×10px. Controls ranged from 24px to 66px high;
experimental labels wrapped to three lines, and adjacent labels squeezed/clipped
the segmented controls. Section captions, Optimize-now bold text, helper text,
notes and chips had unrelated sizing and 6/8/10/12px spacing. Sections had no
consistent panel grouping. The 280px phone drawer left too little content width.

After: controls share 32px height, 6×10px padding and .72rem type; captions use
.65rem, labels .72rem/600, help .7rem with 1.5 line height. Label/control rows stack
so every option remains legible, long help wraps, sections use 12px inner padding
and 16px gaps, and the sticky header stays readable when scrolling. Settings is
440px on desktop and at most 92vw on phones (never a forced minimum width).
Primary/selected/disabled treatments remain theme-aware; every setting and action
is retained, including experimental choices, HF-token controls and topology bars.

Validation: actual headless `/usr/bin/google-chrome` local previews in Amber,
Green, Meadow and Nebula at 1280×900 and 390×900. All eight after checks passed:
no document or drawer horizontal overflow, no controls outside the drawer, all
8 option rows present, and changing Self-tuning Off/Auto still updates local
selection and resets all choices to Auto. All visible Settings buttons measured
32px high. JavaScript compared byte-for-byte unchanged against the before file.
Full suite: **340 tests passed in 28.570s**, exit 0, Nov 6, 2026,
10:45:54 PM CT (base `5928ea7`, final Settings patch). Command:
`PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`.

These screenshots use **local layout fixtures**, not a live inference session:
real `web_settings.OPTIONS`, one explicitly named layout-preview model with native
MTP capability to exercise long labels, empty worker status and placeholder token
status. They do not read, reveal or alter the user's HF token, load a model, apply
settings, or contact the live web server. The token-status label in these previews
is not a report of the Minis' actual token state.

Evidence on the box:
- `/workspace/dbg/shots/settings-before-{amber,green,meadow,nebula}-{1280,390}.png`
- `/workspace/dbg/shots/settings-after-{amber,green,meadow,nebula}-{1280,390}.png`
- Additional `-bottom.png` views show lower sections in every theme/width.
- `/workspace/dbg/shots/settings-compare.png`: actual Meadow phone before/after
  screenshots, upper and lower views.
- `/workspace/dbg/shots/settings-{before,after}-checks.json`: measured typography,
  control heights and overflow diagnostics (before includes the observed issues).

No worker or server restart is needed; `index.html` is served from disk.

### Plain Settings hints and source mapping (Nov 6, 2026, 10:52 PM CT)

Option help is now plain copy: no development-day labels, named-model scores,
raw token rates or benchmark jargon. Percentages are qualified observations, not
promises for every model. Every hint below is paired with its source row; raw
results remain unchanged in the linked records. Positive rates use
`100 × (on / off − 1)`. “Combined output” is total output across both chats, not
the speed of each individual reply.

| Option | Final explanation and hint | Source row / qualification |
| --- | --- | --- |
| Self-tuning | Caravan learns from your chats and remembers the faster settings for each MLX model. | [Self-tuning for every option](#self-tuning-for-every-option--deep-optimize-day-15), per-model learning behavior; no isolated speed claim. |
| Guess-ahead | A smaller model guesses upcoming words for the main MLX model to check. Needs a matching helper; up to ~33% faster writing one reply on a split model in our tests, but slower with two chats. | [DAY17-BENCHMARKS](DAY17-BENCHMARKS.md), final split matrix rows **N1 baseline/helper**, median Write 45.0429 → 60.0063 = +33.22%. **N2 baseline/helper** 39.8074 → 27.8321 = −30.08%; aggregate 70.4915 → 49.7656 = −29.40%. This is specifically one-chat split writing, not a general +33% promise or aggregate gain. |
| Native MTP (only shown for a capable model) | Native MTP uses the model's built-in predictor instead of a separate helper. Up to ~46% faster writing replies in our tests; needs a matching MTP head and one chat at a time. | [DAY17-BENCHMARKS](DAY17-BENCHMARKS.md), **Completed native-head ABBA**, “All 6 responses per mode” row: 36.9483 → 54.1346 = +46.51%, conservatively abbreviated ~46%. Test had a matching native head, one chat, fresh 16-bit caches; output was not claimed bit-identical. |
| Prompt lookup | Reuse words from your prompt to help the MLX model write repeated text. Up to ~44% faster in our tests on repeated text, but slower on mixed chats; one chat at a time. | [DAY17-BENCHMARKS](DAY17-BENCHMARKS.md), corrected adaptive prompt-lookup table: **Repeated passage**, 50.1149 → 72.3685 = +44.41%; **All 8 replies per mode**, 50.2398 → 47.3128 = −5.83%. No all-chat speedup implied. |
| Shared start | Reuse the beginning of repeated system prompts so the model has less to read. MLX models only. | Existing option behavior / worker flags in the [options table](#optimizations); no isolated shared-start A/B number is used. Broader cache reuse results are not attributed to this toggle. |
| Two chats | Let two chats use different Minis at the same time when an MLX model is split. Up to ~70% more combined output in our tests without a helper; no gain on one Mini, and slower with a helper. | [DAY17-BENCHMARKS](DAY17-BENCHMARKS.md), final split matrix **N1 baseline/N2 baseline**, aggregate 41.5415 → 70.4915 = +69.69%; with helper **N1/N2** 52.1061 → 49.7656 (slower). Single-Mini table: median Write 50.5126 / 50.4830; aggregate 46.0763 / 46.5226 (+0.97%, explicitly not a stage-overlap gain). |
| Fused kernels | Combine small GPU steps when running an MLX model. Experimental — no meaningful speed gain in our tests; some models are incompatible. | [ROADMAP item 17](ROADMAP.md): one-Mini 23.75 → 23.7 and 50.6 → 50.8; split follow-up within about ±0.5%, some modes crashed on an incompatible model. No positive percentage marketed. |
| Memory compression | Store MLX chat memory more compactly to save RAM; 16 leaves it uncompressed. May lower quality and slow reading; not supported by every model or Native MTP. | [BENCHMARKS, v1 → v2](BENCHMARKS.md#v1--v2-oct-31), “Other v2 measurements”: 8-bit reading 380 → 325 (−14.47%), still did not fit 16k. [CONFIGURATION](CONFIGURATION.md) `--kv-bits`: quantizes full-attention layers, not all RAM. [DAY17-BENCHMARKS](DAY17-BENCHMARKS.md): native mode rejects compressed caches. No invented measured RAM-saving percentage. |
| GPU keep-warm | Keep the main GPU warm while it waits for another Mini. Split MLX models only; up to ~50% faster writing replies in our tests. | [BENCHMARKS, GPU keepalive](BENCHMARKS.md#gpu-keepalive-while-waiting-on-the-peer-oct-31-mlx), 4-bit table **Qwen3 30B off/on** 30.4 → 45.6 = +50%. Other rows show smaller gains; no single-Mini benefit claimed and no wattage measurement implied. |

The server's `web_settings.OPTIONS` is the canonical option copy. An equal
presentation-only `SETTINGS_HELP_COPY` mirror in `index.html` lets an already
running UI show the new wording without restarting the web process or disrupting
an active remote worker. A regression test requires exact equality. Only the
rendered help text is overridden; identifiers, values, defaults, endpoints,
settings payloads and runtime behavior are unchanged. The existing server process
retains its imported help strings in `/api/settings` until its next normal
restart, while the visible page uses the new text immediately after refresh.

Fit check: all four themes at 390px and 1280px, including the longer native-MTP
variant, using the same local layout fixtures documented above; no horizontal
overflow. `/workspace/dbg/shots/settings-hints.png` is the actual 390px Meadow
upper view; `settings-hints-bottom.png` shows the remaining options. Fixture token
status is not a report of the user's actual HF-token status. No worker or web
restart was needed.

Verification record (base `2842988` plus hint patch): full suite
`PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests` passed **348 tests
in 31.670s**, exit 0, Nov 6, 2026, **10:53:47 PM CT**. Four focused hint tests
also pass, including copy equality, qualified gains and retained negative results.
An earlier concurrent-tree run at 10:50:56 PM CT ran 347 tests in 31.660s with
one error, `test_resume_retry.Retry.test_retries_network_then_succeeds`,
`KeyError: 'retry'`, while picker retry code was being edited; after the picker
commit and restored hint edits, the final full run is green. No benchmark rerun
was performed or needed for this copy-only change.

### Theme parity (Nov 6, 2026, ~11:30 PM CT)

Report: the theme labels were different sizes, and Meadow/Nebula moved buttons.

Causes:
1. Theme variable blocks used bare `[data-theme="meadow"] { ... }`. The theme-switch
   buttons carry `data-theme` too, so each button took its own theme's font and
   radius: MEADOW/NEBULA labels rendered in Nunito (73/65px wide, 27px high) while
   AMBER/GREEN were SF Mono (61px, 24px high).
2. Meadow and Nebula set `--mono: var(--sans)` and `body { font-family: var(--sans);
   letter-spacing: normal }`, and the title dropped uppercase/letter-spacing. Every
   control got a proportional font, so widths changed and rows reflowed (phone
   theme switch moved 11px up; title 320px vs 275px).

Fix: all theme blocks are `html[data-theme="x"]`; Meadow/Nebula keep the shared
monospace for layout and use their own face only inside chat messages (`.msg`).
Themes now change colour, background, blur and shadow only.

Check: `node tools/theme_parity.js` (puppeteer-core, Chrome) opens Chat, Settings,
Models and Topology in each theme at 1280px and 390px and compares every visible
button/select/input/textarea/heading/pill/tag/label rect and font size with Amber.

| Run | Result |
|---|---|
| Before fix | 8/24 combos match (Green OK everywhere; Meadow and Nebula FAIL, 50 of 57 elements off in each) |
| After fix | 24/24 combos match within 1px (57 elements each) |

Static guard: `tests/test_theme_parity.py` (no bare theme blocks, no `--mono: var(--sans)`,
no letter-spacing/text-transform/padding/font-size in theme rules except theme-only
backgrounds and credits). Suite: 350 OK.


### Guess-ahead helpers: consent and disk inventory (2026-11-06)

The web UI now offers a missing known helper after a split MLX load with guess-ahead enabled. The prompt uses `agent/guessers.json` sizes (pairing-table estimates, explicitly labelled), e.g. “A 335 MB helper can make qwen3-30b-a3b-4bit write faster. Download it?” Download / Not now are explicit; Escape/Close only dismiss this visit. Settings → Guess-ahead → Helper download… lets you reconsider Not now. Old silent non-interactive declines do not hide web offers. A non-interactive worker no longer records a decline without an answer.

Helpers download with the regular picker jobs (HF authentication, measured bytes, Stop, Resume and network retry), as full copies into the lead Mini's `~/.caravan/mlx-models/drafts/<name>`. They apply on the next model load; no running worker is reloaded. Off, single-Mini, native-MTP mode and unpaired models do not prompt. The existing pairing-table vocabulary compatibility gates still apply.

Topology → On disk lists individual draft names and native MTP heads (`caravan-mtp` inside model directories), sizes per Mini and paired main models. HF cache remains separate. Individual deletions are conservatively refused whenever a model is loaded, including helpers retained after automatic shutoff; unload first. Helper identities resolve through inventory, not user-provided filesystem paths.

Validation: six new consent/inventory/deletion tests pass. Initial full suite: 365 tests, 1 error in concurrent GGUF work (`test_single_skips_packer`, missing `state_dir`); subsequent full suite: 371 tests, all pass in 32.576 seconds. JavaScript syntax and Python compilation pass. Live preflight: EXO1 Qwen3 30B ready on one Mini; did not reload, stop, download or delete anything. Live UI screenshots and end-to-end helper download remain to be captured.

### Validated Hugging Face token Settings

Settings checks Hugging Face `whoami-v2` server-side (5-second timeout,
60-second digest-keyed cache). An accepted token hides the password field and
shows “Hugging Face token accepted” plus its source. “Use a different token”
opens a blank editor with Cancel. Remove only clears Caravan’s saved file;
environment/CLI tokens retain their source explanation. HTTP 401/403 shows
a rejected-token replacement field; network errors and rate limits say
“Saved, couldn’t check right now”, never “accepted” or “rejected”. No secret
or upstream exception is returned. Save still propagates to every configured
Mini, warning when any node fails. Coverage: `test_hf_token_validation.py`.

Validation record (2026-11-06 CT): first full suite 376/376 passed in 32.489s; final full suite including JS state assertions 377/377 passed in 32.517s. Focused token suite 6/6 passed twice (0.030s each); inline JavaScript syntax check passed. No failed runs. Browser screenshots pending (no desktop agent available to this executor).

Helper follow-up validation: final full suite **377/377 passed in 32.652s** (includes concurrently added tests). Case-sensitive helper IDs are preserved end to end; deletion test exercises `picker_disk_sizes.delete_kind`. Live `/api/helpers` correctly returned no offer for the loaded single-Mini Qwen3. Live disk inventory reported Qwen3 helper 0.35 GB on EXO1, Qwen2.5 helper 0.29 GB on each Mini, Llama helper 0.71 GB on EXO1, Gemma helper 0.19 GB on EXO1, and Orvena native MTP head 0.24 GB on EXO2. An older manually installed Gemma draft (3.58 GB, EXO1) has no catalog pairing, explicitly labelled rather than inventing one. Sizes are rounded actual disk bytes, not advertised download estimates.

## Picker: Resume, auto-retry, the Nov 6 "stall" (Day 17 follow-up)

**What the stall was (22:35–22:52 CST, Brenden's split download of
mlx-community/Llama-3.2-8X4B-MOE-V2-Dark-Champion-…-21B-Q_6-MLX, 9.15 GB per Mini).**
Not a network stall. hf_xet buffers a whole shard before it writes it, so `.incomplete` files stood
still while data kept arriving. Raw samples from the follow-up 21B-MLX job:
EXO1 22:52:34 → 22:53:05 had 0 bytes on disk while the fetch's open flows went 965,498,666 →
1,138,735,665 B (about 5.6 MB/s). EXO2's open-flow counter dropped (412,561,019 → 386,083,006)
while its `.incomplete` jumped 101,125,627 → 197,477,218. At 23:09 EXO1 still had 2,881,923,520 B
on disk and the net counter went 256 → 325 MB in 30 s (about 2.3 MB/s). The measure preferred the
disk number, and nettop only sums open flows, so the card said "0.0 MB/s · stalled?".
Fix: bytes = what was on disk at the start + accumulated positive network deltas (or disk if more).

**Second bug: restart after Stop was killed at once.** Remote runners obeyed `cancel=True` from *any*
job for the repo, including the old stopped one. When the job was started again at 22:44, EXO2's
fetch log was empty and its process was gone. Now only a live job's Stop counts.

**HF token.** The fetch runs under `~/.caravan/venvs/mlx/bin/python` (huggingface_hub 2.4.0,
hf_xet). `mlx_split_fetch._resolve_token()` imports `hf_auth` and passes `token=` to
`snapshot_download` and `model_info`. Checked on both Minis the way the fetch is launched (not
printing the token): token resolved, `~/.caravan/hf_token` present, `whoami` → Chalk-Outline,
access_token. Brenden's 22:35 job started before the token was added at 22:41.

**Resume.** Stopped or failed cards show **Resume** (primary) next to Dismiss.
`POST /api/picker/download/resume {job_id}` reruns the stored request (same repo, files, placement,
destinations). `snapshot_download` skips finished files. The card says "Resuming…" and "kept X
already on disk" until new bytes arrive. Delete still clears partials. Jobs live in memory: after a
web restart the card re-attaches to the running fetch (`live-*` job) instead of freezing.

**Auto-retry.** Network-type errors (timeouts, connection reset, 5xx/429) retry up to 3 times per
Mini, after 5, 15 and 45 s. The card shows "network error — retry n/3". Auth, 404, disk-space and
cancel errors fail at once.

**Max download** defaults to **Any size**. The value was never saved in the browser, so there is
nothing to migrate.

### Stop / Resume test record (Nov 6, 2026, CST)
| Run | Model | Placement | Stop | On disk after Stop | Resume |
|---|---|---|---|---|---|
| A 23:41 | Qwen2.5-0.5B-Instruct-8bit (525,045,902 B/Mini) | all | at 38 s (EXO1 52% / 277 MB, EXO2 30% / 161 MB received) | both: 0 B safetensors, 45,821 B partials | started from 0: hf_xet does not keep partial files. 400 s wall clock because another worker restarted the web server at 23:43:36; the card froze (fixed, `b944186`) while the fetch still finished: 525,045,902 B on both |
| B 23:50 | Qwen2.5-0.5B-Instruct-4bit (278,064,920 B/Mini) | all | at 43 s, when EXO1 had finished and EXO2 had not | EXO1 278,064,920 B (done); EXO2 0 B + 2,329,427 B partial | 30 s to Done. **EXO1 fetched 0 bytes** (net never moved, file reused). EXO2 resume base 2,329,427 B, then 18 KB → 62.8 MB → 141.6 MB → 182.5 MB on the network → Done 278,064,920 B |

So Resume reuses finished files on each Mini. Partly downloaded single files restart from 0 under
hf_xet. Run B also showed EXO1 as "0 MB" at Done (it finished before the first reading); it now
falls back to the planned size.

## Helper Download / Not now — live end-to-end (Nov 7, 12:20–12:24 AM CT)

Setup: Qwen3 30B-A3B 4-bit MLX split EXO1+EXO2 (both Minis have the files; placement file
temporarily set to split), guess-ahead on. To simulate a missing helper, EXO1's
`~/.caravan/mlx-models/drafts/Qwen3-0.6B-4bit` (343,236 KB, sha1 list saved) was moved aside.
Split load ready in ~16 s.

- **Prompt: PASS.** `/api/helpers` offered `Qwen3-0.6B-4bit`; the page opened "A 335 MB helper can
  make qwen3-30b-a3b-4bit write faster. Download it?" with Download / Not now / Close
  (`day17-final-helper-ask.png`). 335 MB is the pairing-table estimate (labelled so); real
  download 0.34 GB, 343,228 KB on disk.
- **Not now: PASS.** Dialog closed, `guess-ahead-state.json` → `web_download_answers.qwen3-30b-a3b: false`,
  no job started, a fresh page load did not reopen it.
- **Change mind: PASS.** Settings → Guess-ahead → "Helper download…" reopened it → Download:
  0.34 GB in 36 s (~13 MB/s steady, brief 1 MB/s dip at 27 s), live progress "0.15/0.34 GB · 14.1 MB/s · ETA 12s",
  then "Downloaded. It will be used on the next model load." Answer flipped to true; offer gone.
  Weight files matched the original byte-for-byte (only README/.gitattributes vs local
  caravan-*.json metadata differ).
- **Applies next load: PASS.** Reload ready in 13 s; log "split speculate: draft Qwen3-0.6B-4bit, k=3, vocab=exact".

Effect (one run each, max_tokens 200, temp 0, `/no_think`; Write tok/s):

| Prompt | No helper | Helper | Change | Helper acceptance |
|---|---|---|---|---|
| Count 1–60 | 44.98 | 56.13 | +24.8% | 74.5% |
| Python prime function | 45.00 | 48.98 | +8.8% | 71.0% |
| 150-word prose | 45.07 | 27.18 | −39.7% | 48.3% |

Mixed, matching the earlier matrix: helps predictable text, hurts free prose. Single runs, not a benchmark.

Restored: original helper folder moved back (sha1 list identical), test download removed, state
file removed (did not exist before), placement back to `one · EXO1`, Qwen3 30B MLX single on EXO1 ready.

Noticed, not fixed: the helper dialog is an unstyled white box in Amber (not themed); the chip
row showed "GUESS-AHEAD OFF" while the split ran without a helper.

## Optimize now: one-option A/B scheduler

Start in Settings → Optimizations → Optimize now. One option at a time is compared
with the saved best, using matched 3-reply arms; already-lost values are skipped
for that model/hardware. Pinned/unavailable options are listed as skipped.
Pause/Resume waits at the next safe reply/reload boundary. Cancel finishes the
current operation and restores saved winners (possibly one recovery reload).
Wait for it to stop before loading/unloading another model. Everyday Auto probes
are suspended only while the sweep owns the worker.

`POST /api/optimize/start`, `GET /api/optimize`,
`POST /api/optimize/pause` with `{"paused":true}` (false to resume), and
`POST /api/optimize/cancel` control the run. The status reports the schedule and
raw per-arm results, not Deep/Quick coverage. Worker-side
`POST /caravan/sweep` accepts `{"pause":true}`, `{"hold":{"guess_ahead":false}}`,
`{"commit":{"fingerprint":"...","name":"kv_bits","winner":16,"lost":8}}`,
and `{"release":true}`. Controls are internal to the selected MLX worker/tunnel;
reload-only values are switched by the manager, not hot-swapped by hold.

Losses are grouped by actual participating Mini identities/chips/total RAM,
not free RAM or load. Missing hardware telemetry stops a run safely. This is
MLX-only, respects config pins, and does not extend the existing two-stage MLX
backend or interfere with arbitrary-Mini GGUF loads. Details, migration notes
and verification ledger: [OPTIMIZE-NOW.md](OPTIMIZE-NOW.md).
