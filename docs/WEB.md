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

1. **Model picker.** Lists models already on disk. Load starts Packer 1 on
   EXO2 over Thunderbolt SSH, then the lead worker on EXO1 (ports **5560** /
   **8194**). Progress lines stream into the left rail until status is
   `ready`.
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
| Panic stop test workers | On each Mini: `pkill -f 'mlx_worker.py'` (only our test workers; leave launchd / exo / Hermes alone) |

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
| `proxy/web/journey.json` | Real v0→Day 13 numbers for the strip |
| `tests/test_web_server.py` | Endpoint + timing unit tests |

## Safety

- Binds `0.0.0.0` on purpose so Tailscale/LAN can reach it; do not port-forward it to the public internet.
- Only starts/stops `mlx_worker.py` on the Day 12/13 test ports. Never touches `main`, tags, Talaria Hub, exo, or Hermes.
