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
requests. Native MTP remains explicitly experimental; no complete quality gate
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
