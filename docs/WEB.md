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
| Unload model from UI | Unload button, or `curl -X POST http://127.0.0.1:8190/api/models (disk inventory; no static phantoms)/stop` |
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
`Read 71 tok/s · Write 50.9 tok/s · 25→50 tok · first token 0.41s · total 1.39s`.

EXO2-only check (read-only, `/api/models`, 21:40): Astrea-R8-Chat-9B-OptiQ-4bit, Orvena-4B-MLX-4bit
and the test Qwen2.5 on EXO2 all `usable: true, run_mode: single`, placement `EXO2`. Not loaded.

## Chat: Read / Write tok/s
Under each reply: `Read N tok/s · Write M tok/s · in→out tok · first token Xs · total Ys`.
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
