# Day 21 — clearer Balance, loose ends and Thunderbolt discovery

## Current checkpoint — November10 CST (historical phases follow)

- Balance UI shipped, including explicit reload/chat locking.
- Bound TCP22/SSH forward link verified; reverse TCP reachable but identity
  unverified. Opt-in N-Mini plan preview matches current en2 endpoints; no apply.
- Physical auxiliary title-worker reboot check **passed** on November10,
  17:17–17:20 CST. EXO1 auto-login recovered Huihui24/40 KV16 (lead PID1036)
  in37.3s from boot; aux health200 at17:18:18 CST (~47.1s). EXO2 itself did
  not reboot; its packer was relaunched at17:17:59 as part of automatic restore.
- 907 tests passing (release gate45.871s). Screenshot:
  `/workspace/day21-tb-verified.png`.
- [Day21 release notes](release-notes/day21.md) finalized for tag
  `day21-2026-11-10`.

## Phase 1 approval checkpoint

Brenden approved this development order: Day21 loose ends + dynamic Thunderbolt;
Day22 true independent GGUF splitting; Day23 guess-ahead and other speed ideas;
Day24 safe cleanup, repeated timings and per-model profiles; Day25 TUI + packaging.
Rabbit holes remain allowed. Phase1 stops before building the Balance redesign or
automatic routing: show the mockup and plan first. No cloud agents, reboots,
release/tag or main fast-forward in this checkpoint.

## Balance mockup (not a live implementation)

- [Default Auto](mockups/day21/balance.html) and
  [Adjust open](mockups/day21/balance-adjust.html).
- Box PNGs: `/workspace/day21-balance-mockup.png` and
  `/workspace/day21-balance-mockup-adjust.png`.
- Uses the real amber UI stylesheet copied from `proxy/web/index.html`, plus
  scoped presentation rules. Standalone HTML, no API requests or actionable
  model controls. Nothing in the deployed UI is changed.
- One-line explanation, a memory bar per Mini, Auto default, Adjust reveals
  the layer slider, one-line preview, Apply / Back to auto, technical jargon
  hidden under Details. Apply explicitly warns that the model reloads.
- Numbers are a read-only Balance snapshot, not invented live measurements:
  Auto proposes EXO2/EXO1 **28/36**, estimated model use **8.32/10.33 GB**
  within usable budgets **14.48/16.46 GB**, headroom **6.16/6.13 GB**.
  Adjust shows the currently saved **24/40**, model use **7.32/11.33 GB**,
  headroom **7.16/5.13 GB**. Each Mini has 24GiB installed; bars explicitly
  use the usable model budget, not the physical total. These are estimates;
  **no throughput benefit is claimed**. Changing load elsewhere changes Auto.
- For N Minis, implementation should generate a card for every participating
  node and N−1 adjacent layer-boundary controls; do not hard-code two Minis.
  Invalid or stale memory/file previews disable Apply; Back to auto restores
  an automatic preview, not an implicit reload. Preserve missing-file fetch
  controls and source configuration within Details.

Render again on the box (Chrome path may differ on other machines):

```sh
/opt/ungoogled-chromium/chrome --headless --no-sandbox --disable-gpu \
  --hide-scrollbars --window-size=900,1120 \
  --screenshot=/workspace/day21-balance-mockup.png \
  file:///workspace/caravan/docs/mockups/day21/balance.html
/opt/ungoogled-chromium/chrome --headless --no-sandbox --disable-gpu \
  --hide-scrollbars --window-size=900,1240 \
  --screenshot=/workspace/day21-balance-mockup-adjust.png \
  file:///workspace/caravan/docs/mockups/day21/balance-adjust.html
```

## Live model switch/unload verification — Nov 9, 23:02–23:04 CST

Two physical M4 Minis, normal web API through Omarchy18190, same KV16 and
EXO2→EXO1 layer order. No UI redesign/discovery implementation, service
restarts or configuration changes. Only model workers were changed by the
ordinary `/api/models/load` and `/api/models/stop` controls, the same API the
web UI uses. This is an API live check, **not a recorded GUI click test**.

| Step | Observed wall time | Result |
|---|---:|---|
| Huihui24/40 → Orvena Qwen3.5-4B16/16, initial control |9.382s to Ready|Both physical stages started; invalid proxy slug caused subsequent HTTP502; excluded from reply success|
| Huihui24/40 → Orvena16/16, canonical-ID repeat |9.173s to Ready (API acceptance2.333s)|Matching model, changed lead PID, KV16, counts16/16 and healthy lead|
| Orvena reply through18090 |0.369s|“Caravan switch works.”, finish stop, native TTFT0.146s, no cache|
| Unload Orvena on both Minis |1.782s API wall|Idle, model/PIDs null, main unhealthy as expected, EXO18194 and EXO25560 no longer listening|
| Restore Huihui24/40 |9.016s to Ready (API acceptance1.460s)|Saved restore preference Huihui, EXO2→EXO1, KV16, lead PID30460|
| Final full Hermes-prefix replay through18090 |11.350s wall|19 tools, medium thinking,11310 prompt tokens, native TTFT0.383s,6.24tok/s, finish stop|
| Final title request through18090 |0.306s wall|HTTP200, X-Caravan-Aux:title-sidecar, relevant valid title JSON, finish stop|

This is one operational smoke cycle, not a repeated performance benchmark or
an end-to-end Hermes CLI/tool-execution run. No tools were removed from the
frozen prefix and no emitted tool calls were executed. The full reply was
“I'm online and ready to help.” It reused a persisted/warm checkpoint, so do
not present0.383s as fresh cold-start performance. No cache deletion.

Initial control issue: the UI/API model slug `orvena-4b-mlx-4bit` is not the
same as an OpenAI-proxy model ID. Proxy routing is explicitly configured for
`Orvena/`; corrected request uses `Orvena/Orvena-4B-MLX-4bit`. The first
attempt returned502, restored Huihui in10.207s and never reached unload.
This is a controller-ID mismatch; no production bug fix is claimed. A future
proxy alias mapping could improve this error, but is outside this mockup gate.
The corrected run is separately retained rather than hiding the failure.
Unload intentionally clears auto-restore, so successful final reload and
saved-preference verification are mandatory; those both passed.

Evidence: `handoff/lab/day21/raw/` and Omarchy `~/day21-checks/`. Private
Hermes request bodies remain only under the existing private Day20 folder.
The final title was “Review Caravan after reboot and improve Hermes speed”;
that is test prompt content, **not** evidence a reboot happened today.

## Dynamic Thunderbolt discovery/routing design (not implemented)

### Existing behavior, not starting from zero

`agent/discovery/thunderbolt.py` already enumerates Thunderbolt hardware ports
and their active IPv4 addresses for the old agent. `agent/service_endpoints.py`
resolves explicit `tb://INTERFACE:PORT` or
`ssh+tb://TRUSTED_SSH_HOST/INTERFACE:PORT` endpoints at load time using verified
hardware labels, active link state, a private/link-local address, and
host-key-checked SSH. `proxy/web_pipeline.py:resolve_nodes` applies that to an
N-stage plan. This survives an address change but still requires the chosen
interface/cabling to be specified. It is **not** automatic N-Mini cable mapping.
Do not silently weaken the current fail-closed behavior.

### Discovery and identity

1. Begin only with explicitly configured/trusted Mini IDs and existing SSH
   control hosts; optional mDNS records are hints, never authorization to enroll
   a new computer or trust a new host key. Use BatchMode, StrictHostKeyChecking,
   bounded timeouts, no password/key collection and no subnet scans.
2. Each trusted node reports timestamped JSON: stable Mini ID, observed hostname,
   Thunderbolt hardware ports, active physical interface indices, bridge-member
   relationships, IPv4 addresses and masks, IPv6 link-local addresses including
   interface scope, configured data-service port, and service identity/version.
   Read `networksetup -listallhardwareports`, `ifconfig`, and route information;
   never change macOS networking, bridges, firewall or IP assignments.
3. Include active Thunderbolt Bridge addresses only when bridge membership is
   proven to consist of the trusted Thunderbolt path. A bridge name or RFC1918
   address alone does not prove a cable. For IPv4 link-local, never assume every
   169.254 address is the intended peer. For scoped IPv6, retain the egress index
   per source node and proper bracketed URI representation; leave IPv6 disabled
   until the transport/parser has dedicated tests. Multiple ambiguous addresses
   are an explicit diagnostic, not “take the first.”

### Build and select the actual data path

4. Construct a directed graph over **trusted Mini identities**, with candidate
   edges only when the source's route uses the verified Thunderbolt interface
   or verified TB-only bridge. Probe only known peer candidates/ports, bounded
   to e.g. two concurrent short probes. Confirm a matching peer identity over
   the trusted control channel and the data-service handshake; TCP-open alone
   is not identity. The current raw split protocol must stay restricted to
   trusted private links, not be treated as Internet-safe or authenticated.
5. Resolve/probe from **each actual connection source**, including middle
   packers, not just EXO1. Record route, endpoint, port, RTT, freshness and why
   accepted/rejected. Rank verified direct Thunderbolt edges first; use
   hop count and small handshake latency only as tie breakers, not a throughput
   promise. No model-weight transfers or heavy bandwidth benchmark at discovery.
6. Find a deterministic feasible model pipeline ending at the selected lead.
   Reuse the configured layer/node order where connected; offer an explicit
   reordered plan only if memory/files remain valid. A chain without forwarding
   may be supported by the model pipeline's adjacent connections, but do not
   assume IP forwarding, magically route through a Mini, or claim all-to-all
   mesh connectivity. If no path visits the requested nodes once, show the
   missing edges and block that load. Build for arbitrary N with bounded graph
   search and a deterministic heuristic for large fleets, not permutations.
7. Freeze resolved endpoints into the owned launch record for that load. Expire
   discovery snapshots quickly (e.g.30s) and recheck before stopping a working
   model. Never rewrite a running worker's peer or migrate an in-flight session.
   A lost cable becomes an explicit error; rediscovery precedes the next load.

### Fallbacks and safety

- Preserve manual per-node endpoint overrides, validated as today. On uncertain
  discovery, keep the current working model untouched and explain the failure.
- Default is **Thunderbolt-only data**, not silent Wi-Fi/Tailscale/public
  fallback. SSH management over an already-trusted overlay is separate from
  model-data routing. An optional private Ethernet/overlay data fallback must
  be explicitly enabled, identity/route-verified and shown as slower/non-TB.
  Public, wildcard, loopback-as-remote, multicast and untrusted interfaces are
  rejected. “Private IP” alone is insufficient trust.
- No automatic peer enrollment, firewall openings, credential reads, host-key
  policy changes, network reconfiguration or downloads. Unauthenticated raw
  MLX/RPC ports must never be exposed to untrusted networks. Future remote
  deployments need a separate authenticated/encrypted transport design.

### What can actually be tested with two Minis

Observed read-only: EXO1 `en2` **169.254.65.20** ↔ EXO2 `en2`
**169.254.99.64**; hardware ports report Thunderbolt1, links active; EXO1's
route to EXO2 uses `en2`, and existing packer TCP **5560** is reachable.
These are internal evidence addresses, not user-configurable constants.

After approval: candidate enumeration, source-specific route/identity checking,
stale-address refresh, explicit overrides, no-cable/fail-closed behavior and
real inference after a selected direct link. Cable unplug/replug requires a
separate supervised idle window; it was **not done** in phase1. A physical
reboot/address-change experiment is Brenden-controlled, not simulated proof.
Bridge layouts, third-Mini chains, asymmetric routes, multiple cables,
non-neighbor routing and scaling require fixtures first, then 3+ physical
Minis. Two Minis cannot prove automatic N-Mini topology discovery.

## Auxiliary title-worker physical reboot check — Brenden runs this

**Passed November10,17:17–17:20 CST.** Results are recorded in the section
immediately after this recipe. The recipe is kept as the exact method used.
LaunchAgents require desktop login after startup; FileVault may require local
unlock. Do not call a manual service restart or a no-reboot health check
reboot proof.

1. Stop active chats. On Omarchy, confirm the intended saved restore state:

```sh
curl -fsS http://127.0.0.1:18190/api/status | python3 -m json.tool
ssh exo1 'cat ~/.caravan/web-ui/last-model.json'
systemctl --user status caravan-web-tunnel hermes-caravan-tunnel --no-pager
```

Require Huihui, counts `[24,40]`, node order `["exo2","exo1"]`, KV16,
restore enabled/saved; both tunnel units should be active. If these units
are installed system-wide instead, use `systemctl status` (no `--user`).

2. Start this observer in an Omarchy terminal **before** rebooting. It logs
   wall time as CST and all outages; Ctrl-C stops it after recovery:

```sh
mkdir -p ~/day21-checks/reboot
python3 -u - <<'PYWATCH' | tee ~/day21-checks/reboot/observer.jsonl
import datetime,json,subprocess,time,urllib.request
from zoneinfo import ZoneInfo
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
while True:
    row={'time_CST':datetime.datetime.now(ZoneInfo('America/Chicago')).isoformat()}
    try:
        with http.open('http://127.0.0.1:18190/api/status',timeout=3) as r:
            s=json.load(r)
        w=s['worker']; row.update(status=w.get('status'),model=w.get('model_id'),
            counts=(w.get('balance') or {}).get('counts'),
            kv_bits=(s.get('active') or {}).get('kv_bits'),restore=s.get('restore'),
            lead_healthy=s.get('lead_healthy'))
    except Exception as e: row['web_error']=str(e)
    try:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=3','exo1',
            'curl -fsS --max-time 2 http://127.0.0.1:8196/health'],
            capture_output=True,text=True,timeout=8)
        row.update(aux_exit=p.returncode,aux_health=p.stdout.strip(),aux_error=p.stderr.strip())
    except subprocess.TimeoutExpired: row['aux_error']='SSH probe timeout'
    print(json.dumps(row),flush=True);time.sleep(2)
PYWATCH
```

3. In separate terminals, **Brenden** issues the reboots when convenient:

```sh
ssh -t exo2-via-exo1 'sudo /sbin/shutdown -r now'
ssh -t exo1 'sudo /sbin/shutdown -r now'
```

Restart EXO2 first, then EXO1 promptly (or reboot both directly at the Macs).
SSH disconnects are expected. Log in/unlock both Macs when needed. Do not run
Load, restart launchd jobs or alter Hermes while measuring automatic recovery.
Wait up to10min for gated admission; it requires primary health200 plus
at least **0.9GB aux budget +1.75GB reserve** of known available memory.
launchd retries an aux wait timeout with exit75. If no recovery, keep the logs
and report a fail rather than hiding it with a restart.

4. After the observer shows Huihui24/40 KV16 ready and aux health200, verify
   services and saved preference, then replay the **existing title payload**:

```sh
ssh exo1 'launchctl print gui/$(id -u)/com.caravan.v3.aux; cat ~/.caravan/web-ui/last-model.json'
ssh exo1 'cat ~/.caravan/logs/day20-aux.log' > ~/day21-checks/reboot/aux.log
curl -fsS --max-time 30 -D ~/day21-checks/reboot/title.headers \
  -H 'Content-Type: application/json' \
  --data-binary @"$HOME/day20-speedups/private/title-current.json" \
  http://127.0.0.1:18090/v1/chat/completions \
  > ~/day21-checks/reboot/title.json
python3 ~/day20-speedups/bin/probe.py day21-reboot-full-power \
  --payload ~/day20-speedups/private/final-full-power.json \
  --session d20-final-full-power
```

Keep private request bodies local. Title must have HTTP200,
`X-Caravan-Aux: title-sidecar` and a relevant valid title JSON (`session_title` is the response-schema name)
response; a correct main-model fallback alone is not an aux pass. Full reply
must have19 tools, medium reasoning, a visible answer and finish `stop`.
Read the returned JSON, not just the probe process exit code (it records errors
without exiting nonzero). Inspect only log entries from this boot; historical
aux lines must not be mistaken for this run. Require the aux wait/admission
sequence to agree with primary recovery and sufficient free RAM; health200
ordering alone is evidence of readiness, not a precise admission timestamp.
Record reboot request→main-ready and request→aux-ready separately, including
any manual unlock/login. Finally confirm the saved Huihui24/40 KV16 state
again. No automatic reboot has been scheduled or executed.

### Results — November10,17:17–17:20 CST

Brenden issued the two documented reboot commands from Omarchy around17:17
CST, EXO2 first and EXO1 immediately after. Both Minis auto-login; no manual
unlock or login was required. **EXO2 did not actually reboot** (kern.boottime
remains November9,20:07:05 CST, uptime21h+). The likely cause is that
`exo2-via-exo1` depends on EXO1, which was then restarted promptly, so the
EXO2 shutdown may not have completed. This check is therefore an EXO1
physical reboot plus automatic packer relaunch on a still-running EXO2, not a
dual-machine cold start. Day20 already proved two-Mini main-model restore.

EXO1 kern.boottime: **2026-11-10T17:17:30.876098-06:00**. Auto-login brought
launchd web, proxy and the aux wrapper up at17:17:45. The aux process entered
the primary-health/RAM wait (this-boot log only):

```
aux wait: primary_ready=False, available_gb=16.06852608, budget_gb=0.9, reserve_gb=1.75
aux wait: primary_ready=False, available_gb=14.165614592, budget_gb=0.9, reserve_gb=1.75
aux wait: primary_ready=False, available_gb=4.697939968, budget_gb=0.9, reserve_gb=1.75
```

Available RAM fell as the main model loaded. The EXO2 packer worker started
at17:17:59; the EXO1 lead worker started at17:18:02 and **loaded Huihui
24/40 KV16 in4.9s**, listening on :8194 at **17:18:08**. last-model.json was
rewritten at17:18:08.206645 (37.3s after boot). Aux was then admitted
(4.70GB available vs 0.9GB budget +1.75GB reserve), loaded
Qwen2.5-0.5B-Instruct-4bit in0.4s, and listened on :8196 at **17:18:18**
(~47.1s after boot). launchd `com.caravan.v3.aux` runs=1, last exit never,
health HTTP200 `{"status":"ok","worker":"caravan","split":false}`.

The continuous observer was started at17:18:42, after recovery had already
finished, because the reboot commands were issued before the observer could
be launched. Boot-to-ready timings therefore come from this-boot logs
(`lead.log`, `day20-aux.log`, process start times, file mtimes and
kern.boottime), not from a pre-reboot observer. From17:18:42 onward the
observer showed status `ready`, Huihui, counts`[24,40]`, KV16, restore
phase `restored`, lead healthy, and aux health200.

Post-recovery checks, no services restarted:

| Check | Result |
|---|---|
| Title through :18090 | **PASS** HTTP200, `X-Caravan-Aux: title-sidecar`, finish `stop`, wall **0.135s** (native total0.083s, TTFT0.041s). Body `{"title":"Review Caravan after reboot and improve Hermes speed"}` — test-prompt content, as in earlier Day21 title checks, not a claim that the title model observed the reboot. A main-model fallback did **not** occur (sidecar header present; model Qwen2.5-0.5B-Instruct-4bit). |
| Full19-tool medium Hermes replay through :18090 | **PASS** HTTP200, finish `stop`, visible answer “I'm online and ready to help.”,19 tools, reasoning `medium`, wall **11.504s**, native total11.231s, TTFT**0.421s**, write**6.2tok/s**,11310 prompt tokens (11309 cached). Functional check, not cold-prefill or actual tool execution. |
| Saved preference after probes | Huihui, counts`[24,40]`, node order EXO2→EXO1, KV16, restore enabled/saved; aux still running PID682, health200. New lead PID **1036**. |

Raw evidence stays on Omarchy at `~/day21-checks/reboot/` (timeline, this-boot
logs, title headers/body, probe JSON, observer from17:18:42, final status).
Private request bodies were not copied into the repo.


## Approved Balance implementation — Nov 9, 2026 CST

Brenden approved the mockup as shown. Built the real Topology Balance section:
Auto preview on opening Topology, one memory card per participating Mini,
Adjust reveals N−1 adjacent MLX layer sliders (or N GGUF proportion fields),
one-line preview, Apply, and Back to auto. Technical file/stage/source/fetch
controls remain behind Details; nothing is downloaded or reloaded by preview,
Adjust, or Back to auto. Bars are explicitly within usable model budgets.

The existing guarded Balance preview and explicit reload endpoints remain the
source of truth. Unknown/unsafe memory, failed requests, pending input and stale
responses keep Apply disabled. Source/model changes invalidate old plans. Apply
submits the exact previewed counts/node IDs, invalidates the plan immediately,
and cannot double-submit. File fetching/cancellation and post-reload measured
speed remain available. DOM text construction, not HTML injection, displays
peer labels, paths and errors. Themes inherit the existing UI variables.

Added production-JS contract coverage for 1/2/3/7-Mini boundaries, constant layer
totals, safe memory bars, malformed plans, Auto/Adjust/Back transitions, stale
responses, invalid GGUF shares, exact Apply payload and duplicate/unsafe Apply
blocking. Baseline794 tests; added14 Balance cases; full regression808 tests passed in43.807s. Deployment uses ff-only pulls
and only the existing web LaunchAgent (already configured
CARAVAN_WEB_KEEP_WORKERS=1 and AbandonProcessGroup=true). Live verification
will not press Apply, Load or Unload; Huihui24/40 KV16 must retain its PID and
saved preference. No physical reboot is authorized by this implementation step.


### Balance live verification (Omarchy18190)

Deployed `d56977d` by ff-only pulls in EXO1 `~/dev/caravan-v3` and EXO2
`~/cv3`. Restarted only `com.caravan.v3.web` after checking its plist contains
CARAVAN_WEB_KEEP_WORKERS=1 and AbandonProcessGroup=true. Existing main worker
PID **30460** was adopted unchanged; no Apply/Load/Unload request was made.

Real browser screenshots: `/workspace/day21-balance-live.png` (Auto) and
`/workspace/day21-balance-live-adjust.png` (Adjust open). Browser integration
checked2 memory cards, hidden-by-default slider, Adjust, moving28/36→29/35
with immediate disabled Apply and a fresh one-line memory preview, then Back
to auto. All of these were previews only. Zero JS errors and zero model/file
mutation requests; an interception guard would have blocked any such request.
The running/saved split stayed24/40, active KV16. Estimated Auto counts differ
from the currently applied split by design and are not silently applied.

Initial deployment verifier incorrectly required restore.last_model in the
status response after adoption and timed out; adoption legitimately reports
phase=adopted without that field. Corrected verification reads the unchanged
last-model.json preference and checks the active PID/counts/KV16 separately.
No second restart or reload was needed to correct the verifier.

## Trusted Thunderbolt read-only implementation

Added an explicit **Inspect links** readout and GET `/api/thunderbolt`. It
queries only configured Mini identities, with BatchMode and strict existing
SSH host keys; no mDNS enrollment, scanning or user-supplied API targets. Two
bounded-concurrency passes (maximum4 inspectors) collect local TB hardware
interfaces/addresses, then each source Mini’s route to known peer addresses.
Each snapshot is cached30s; opening Topology does not start inspection.

The directed N-node graph labels every edge **candidate only**, with
usable_for_routing=false. Source routes must use an observed TB interface or
a bridge proven to contain only TB hardware members. Public addresses, unknown
hardware, mixed bridges and ambiguous addresses across Minis are excluded.
Scoped IPv6 is deferred rather than incorrectly stripping its scope.
Malformed inventories/offline peers fail closed with diagnostics.

No data-plane sockets/probes, data handshakes, benchmark transfers, route or macOS
network changes, peer/listen rewrites, model changes or automatic routing.
Trusted SSH confirms inventory provenance, **not** authenticated raw MLX data
service identity, cable adjacency or transfer speed. Those checks and actual
automatic route selection remain future work; the UI says this explicitly.
25 new discovery tests (23 Python plus2 JS readout contracts) cover parser/bridge/security rules, strict SSH, failed
inspection, source-specific and asymmetric3-node graphs,7-node fixtures,
address collisions, cache invalidation and API confinement/read-only failures.


### Compatibility correction and final regression

Code review caught that existing GGUF previews return estimated use + headroom
without a separate capacity_gb. View helpers now derive that usable budget
without altering the API; unknown values remain blocked. Added a real-contract
regression (`1570c3e`), so Balance adds15 cases total. Also shortened live
result wording to fit the actual drawer width; for N>2 the one-line result
shows Mini count and minimum headroom while per-boundary controls show layers.

Final full box regression: **834 passed in44.216s**, baseline794 (**+40**):
15 Balance JS/helper/DOM contracts,23 discovery Python cases,2 discovery JS
readout contracts. Node syntax, Python compilation and git diff checks passed.
No physical reboot, live GGUF load or production model reload for this work.


## Phase2 live closeout — Nov 9, 23:29–23:30 CST

Both Minis ff-only synced to `010ee54` (`d56977d` approved Balance, `1570c3e`
GGUF presentation compatibility, `010ee54` passive discovery/refinements).
Only web restarted for the new API; this phase used two web-only restarts
(one per feature deployment), zero worker/proxy/aux restarts and zero reboots.
Huihui lead PID30460 remained unchanged across both; saved24/40 KV16 preference
checked directly. No Apply/Load/Unload or file-fetch request from the browser.

The live discovery API found2 trusted Mini inventories and2 directed
**candidate** edges, EXO1/en2→EXO2/en2 and the reverse. Both nodes report active
private link-local addresses. No ambiguous addresses; graph automatic_routing
isfalse and every edge usable_for_routing isfalse. The UI readout was clicked
and its two arrow directions verified. This proves passive collection and
source-route observations only, not transport identity or physical N>2 routing.

Final screenshots from the deployed UI through Omarchy18190:
- `/workspace/day21-balance-live.png` — default Auto, technical details closed.
- `/workspace/day21-balance-live-adjust.png` — Adjust open, compact one-line result.
- `/workspace/day21-balance-live-thunderbolt.png` — passive directed-link readout.

Omarchy originals are `~/day21-balance-live/default.png`, `adjust.png`,
`thunderbolt.png`. Browser verified slider28/36→29/35 preview followed by
Back to auto; zero JS errors or mutation requests. Applied split remained24/40.

Final18090 full-prefix replay retained19 tools and medium reasoning:
HTTP200, **11.167s wall**, **0.318s native TTFT**, **6.24tok/s**,
11310 prompt tokens, warm hit-memory checkpoint, finish stop; visible answer
“I'm online and ready to help.” GET/v1/models also200. These are operational
smoke checks, not a new cold/performance or end-to-end tool-execution claim.

Retained source, JSON snapshots, saved-preference proof, browser checks and
full-tool result: `handoff/lab/day21/live/`. Private request bodies were not
copied. Obsidian Day21 note mirrors this runbook/design/results. Pending:
physical auxiliary reboot proof (Brenden), data-service identity/reachability
validation, supervised cable-loss tests and opt-in automatic route planning.

Exact shipped application revision `010ee54` rechecked after final UI wording:
**834 tests passed in44.103s**, zero failures; summary in live/regression.json.


## Apply feedback correction (priority before further Thunderbolt work)

Brenden requested an unmistakable reload state and clearer Apply styling.
Enabled Apply is now solid black with readable light text; disabled Apply is
gray. A preview identical to the currently applied model/node order/counts
keeps Apply disabled, as do unknown status, unsafe/stale previews and reloads.

Clicking Apply immediately locks chat/Enter, Balance editing and model controls
and shows **“Reloading model… this takes about 10 seconds”** beside Balance
and above chat. Steps show stopping, loading each participating Mini and health
checks. Polling cannot mistake the previous worker's stale Ready for completion:
completion requires a changed PID, healthy lead, requested model/counts/node
order and preserved KV precision. Done says **“Ready, new split applied.”**;
errors and lost status are explicit. Other-tab reloads/unloads are handled too.

Reload requests preserve the actual active settings, including KV16, instead
of silently replacing them with page Auto defaults. GGUF status now exposes
actual applied shares so the same no-change/completion checks can work there.
No live GGUF load is part of this correction.

Preflight found Huihui **27/37 KV16**, PID35708, loaded at23:35 CST through
the prior UI (not the24/40 left by the previous executor checkpoint). The
requested live demonstration will explicitly restore24/40 through the new
Apply flow and leave it saved. No further Thunderbolt implementation until
this correction, screenshots and results have been reported.

Regression validation: **846 tests passed in44.805s**, up12 from the prior834
(+52 versus the original Day21 baseline794). The12 new scenarios cover
no-op Apply, immediate locks, stale Ready, progress, exact completion, mismatch,
error, connection loss, external reload/unload, active settings and GGUF shares.
Node syntax, Python compilation and whitespace checks passed.

Live integration caught a schema mismatch before any worker was disturbed:
the initial settings-preservation helper sent `fuse_kernels=off` and
`keepalive=on`, but this API exposes those implicit states as `auto`. The API
correctly rejected the request and the UI reported a clear error. Corrected
the helper to the actual allowed values (also adaptive lookup/self-tuning),
and added a JS→real Python normalizer/worker-args contract test rather than
relying only on a mocked success response. The rejected trial left27/37 intact.

### Live Apply correction proof —23:51–23:52 CST, November9

- Shipped `5b122f7` and settings-contract correction `5cd7a3e`; both Minis
  ff-only synced. Web-only restarts asserted `CARAVAN_WEB_KEEP_WORKERS=1` and
  `AbandonProcessGroup=true`, preserving PID35708 until the explicit UI Apply.
- Omarchy **:18190**: real Adjust24/40 preview, enabled Apply confirmed black
  (`rgb(0,0,0)`), then one permitted Apply. During reload Apply was gray
  (`rgb(51,51,51)`), chat/Enter and controls were disabled, and both the Balance
  and main-chat banners explained the reload. An injected Enter sent no chat.
- Status progressed stopping → starting lead → Ready (short packer stage fell
  between2-second polls). The per-Mini checklist ended EXO2 loaded / EXO1 loaded.
  Backend Ready/saved at23:51:49 CST, **8.82s** after click;
  completed banner plus chat usable at **12.93s** including poll cadence.
- Done: **“Ready, new split applied.”** Chat usable again; Apply gray/disabled
  because24/40 is now already running. No JS errors, unexpected mutations or
  second reload. Final lead PID**39479**, Huihui **24/40 KV16**, EXO2→EXO1;
  `last-model.json` explicitly saved the same counts/node order and KV16.
- Screenshots, captured and visually checked:
  `/workspace/day21-apply-ready.png`, `/workspace/day21-apply-reloading.png`,
  `/workspace/day21-apply-done.png`.
- Exact-shipped regression: **847 passing in44.852s** (+13 since834; +53 since794).
  Production Node syntax and Python compilation/whitespace checks passed.
- **:18090** actual full19-tool / medium-effort request: HTTP200, finish`stop`,
  visible response, **11.402s wall**, TTFT0.403s, write6.22tok/s. This was a
  cached-prefix functional check (11,309 /11,310 prompt tokens cached), not a
  cold-prefill benchmark or a tool-execution test. Worker remained39479 and
  active KV16 /24 packer layers. Private request body was not committed.

Nonprivate evidence and the guarded one-shot live-check script:
`handoff/lab/day21/apply-feedback/`. Thunderbolt data-plane validation remains
paused at this checkpoint, pending reporting this priority feedback correction.
No discovery probes/routing changes, reboot, release tag or worker-service
restart was made; only the explicitly requested Balance model reload occurred.


## Explicit Thunderbolt data-plane validation and suggested plan — November10 CST

### Safety and verification scope

Passive GET `/api/thunderbolt` remains probe-free. Explicit POST
`/api/thunderbolt/validate` refreshes the configured trusted inventory and probes
each candidate from its actual source Mini. Results are `verified`, `unverified`
or `failed`, with authenticated-hello latency and TCP-connect latency when known.
No request can supply hosts, interfaces, addresses or a replacement graph.

The probe uses **existing system SSH TCP22**, not MLX5560: the current MLX
packer serves a single persistent head connection, so an extra hello there
could queue behind or interfere with the running model. The SSH transport
opens one socket bound to the observed private source IP AND Darwin
`IP_BOUND_IF`; the kernel must confirm the interface index before connect.
It never falls back to an unbound socket, Wi-Fi, Tailscale or another interface.
Hardware TB and proven TB-only bridges are accepted; mixed/unknown bridges,
public/wildcard addresses and unscoped IPv6 remain rejected.

A strict SSH handshake checks the peer's **existing configured host-key alias**
(or trusted local-node hostname on reverse probes), then a tiny read-only
command echoes a fresh nonce, hostname and SSH_CONNECTION. Source/destination
IP endpoints must match; trusted hardware/interface and source route are
rechecked before AND after the hello. Unknown existing host trust or unavailable
noninteractive login is **unverified**, not an invitation to enroll a key. A
changed key, identity/nonce/endpoint mismatch, route drift or deadline is failed.
Caravan never opens credential/key files; system SSH uses existing authentication.
No trust file is changed.

The data socket is constrained by a6-second forwarding deadline and256KiB
budget, plus the SSH parent's8-second process deadline. Source inventory/route
checks have5-second command deadlines; remote orchestration is bounded42s.
At most4 edge probes run concurrently, at most64 per inspection, with existing
pipeline-required edges first. Excess edges are explicitly unverified, not
guessed. Explicit validation is single-flight/cached30s; there is no background
probe service. Expired verification becomes unverified in API/UI; planning
checks every required edge's timestamp independently.

**Verified here means authenticated host identity/reachability on TCP22 over
a kernel-pinned private TB interface.** SSH hello wall time includes handshake
and command overhead; TCP-connect time is reported separately. This is not
ping RTT, MLX protocol health/authentication, bandwidth, exact cable adjacency,
or evidence that existing model transports themselves are interface-pinned.
The existing raw MLX transport is unchanged and remains trusted-private-only.

### Opt-in suggested plan, never an apply

Check the UI opt-in and explicitly request **Preview plan**, POST
`/api/thunderbolt/plan` with `opt_in:true` and the current validation ID. No
probes happen during planning. Missing/stale IDs, changed config, expired edges,
unknown/offline Minis or missing links fail closed; the server never tries
an alternate network or silently picks/reorders a different model pipeline.

The N-Mini algorithm preserves configured packer order followed by the lead
and preserves existing peer ports. Each packer's SINGLE selected address must
be verified from both its successor and the lead, because existing startup
preflights all packers from the lead. A chain with no lead-to-packer path is
therefore rejected, not falsely advertised as currently loadable. Multiple
valid addresses prefer the explicit current address; otherwise ambiguity is
a hard failure. `peer`, private-address `listen`, and previous-stage
`upstream_peer` are shown, together with required directed evidence. Existing
`tb://en2` / `ssh+tb://trusted/en2` configuration is compared using only this
trusted inventory, without resolving over another network or rewriting it.

The result is **preview_only=true, apply_supported=false**. There is NO apply
endpoint; even an identical plan is not applied. `matches_current_config` means
resolved configured endpoints, NOT verified live application (`matches_live`
is deliberately null). Concrete preview addresses are observations, not a
replacement for reboot-safe interface URIs. Future apply must be a separate
explicit action, revalidate freshness/identity/memory/files before touching a
worker, pin all runtime connections and fail without network fallback.

Fixtures cover multi-Mini plans, the lead's additional reachability requirement,
strict binding/deadlines/byte limits, trust/nonce/route mismatch, stale evidence,
probe budgets, API target injection, no apply route, opt-in and UI expiry races.
Physical proof remains limited to the two existing Minis; no third-Mini, cable
unplug, bridge or address-change/reboot experiment is claimed.

Pre-deploy exact-code regression: **906 tests passing** (+59 versus the Apply
checkpoint847; +112 versus Day21 baseline794). Thunderbolt-targeted84 cases
include the pre-existing25. Syntax/compilation/whitespace checks passed.

Live inspection confirmed that a link can be TCP-reachable while SSH identity
remains unverified. The UI now shows those separately, including known TCP
connect latency even when existing SSH trust/login prevents a verified hello.
This does not weaken the identity gate or trigger an alternate login/network.
Final UI-complete regression: **907 passing**, up60 from847 (+113 from794);
85 targeted Thunderbolt tests.

Final hardening: management inventory/source-orchestration SSH also explicitly
disables UpdateHostKeys, not just the interface-bound hello. Existing known
hosts remain the trust anchors; discovery may not accept/rotate trust entries.


## Final live trusted-link readout — 2026-11-10 00:26:14 CST

Final code: `c2c7ec6` (validation/preview), `efdf8ba` (reachability clarity),
`609908e` (disable SSH host-key updates on management paths too). Both Minis
ff-only synced. Backend deployments restarted only EXO1 web with asserted
keep-workers/AbandonProcessGroup policy; the static UI update needed no restart.
No model, packer, proxy or auxiliary job was restarted by this Thunderbolt work.

Omarchy18190 actual UI: click Validate links, then opt in and Preview plan.
Bound validation request completed in **0.849s**. Each source
used en2, private169.254 addresses, and kernel-confirmed **ifindex11**.

| Direction (en2 → en2) | Identity/status | TCP reachability | TCP connect | Authenticated SSH hello |
|---|---|---|---:|---:|
| EXO1 .65.20 → EXO2 .99.64 | **verified** | yes |0.279ms|158.980ms|
| EXO2 .99.64 → EXO1 .65.20 | **unverified** | yes |0.712ms|not established|

Addresses above abbreviate169.254.65.20 /169.254.99.64. Counts:1 verified,
1 unverified,0 failed. Reverse existing SSH trust or noninteractive login was
unavailable; it was NOT converted into a trusted identity, retried on another
network, or fixed by adding/copying keys. TCP reachability alone is not identity.
The UI explicitly shows the distinction and its known connect latency.
No live fault/cable interruption was manufactured to produce a failed edge;
failure and timeout states are covered by fixtures.

The required current TCP connection is EXO1→EXO2, so the two-Mini preview needs
that verified direction, not the unused reverse SSH login. Middle-Mini paths
must independently verify every required successor/lead direction. The preview
returned HTTP200, explicit opt-in/current validation ID, order EXO2→EXO1,
EXO2 peer/listen **169.254.99.64:5560**, no upstream, and the lead's effective
peer unchanged. It matches configured reboot-safe en2 URI resolution AND the
live status peer, but **nothing was applied**. API `matches_live` remains null
rather than pretending an apply happened. No apply endpoint exists.

Verification expires within30s. API/UI downgrade expired proof; the server
rejects stale plan requests and the UI rejects expiry-in-flight. Reopen/refresh
the UI and click Validate links for a new readout; there is no automatic probe
or persistent verified badge. Screenshot (final capture, visually checked):
**`/workspace/day21-tb-verified.png`**.

Final inference check after the final backend/UI deploy: :18090 actual19-tool,
medium-effort request **HTTP200 / finish stop / visible response**;
**11.196s wall**, TTFT**0.315s**, write**6.23tok/s**.
Cached prefix11309/11310 tokens; this is a functional check, NOT cold-prefill
performance or actual tool execution. Private request bodies were not copied.
Afterward loaded AND saved Huihui remained **24/40 KV16**, lead **39479**,
EXO2→EXO1 and existing peer unchanged. No model reload occurred in this step.

Exact final regression: **907 passing /45.084s**, up60 from847,
up113 from the Day21 baseline794. 85 targeted Thunderbolt cases cover old and
new paths; Node syntax, Python compilation and whitespace checks passed.
Nonprivate API/UI/plan/model/full-tool evidence and guarded capture script:
`handoff/lab/day21/thunderbolt-verified/`.

Release notes in `docs/release-notes/day21.md` are finalized for tag
`day21-2026-11-10` after the auxiliary reboot check passed (see results
above). Two Minis do not prove physical N-Mini scaling, arbitrary
bridges/cables, automatic path application, or MLX transport authentication.
These limits are not hidden by a verified SSH link or by a successful aux
recovery. EXO2 was not physically rebooted in this check.

### Published release / downloaded-package verification

- Published17:26:20 CST: https://github.com/linuxbren/caravan/releases/tag/day21-2026-11-10
- Immutable annotated tag `day21-2026-11-10` points to `b6c9394`. Later
  documentation-only verification does not move the tag.
- Assets: `caravan-day21.tar.gz`18,273,897B, SHA256
  `26821c51c552518f284c3046e23ad8eba6d21a0623c10e210566841e2f0f91b4`;
  ZIP19,352,327B, SHA256
  `e704ca32827a25a8cdbfc48e6d392a853eb379bdbea944b9cfd27ce46706c66b`.
- Downloaded the published assets, matched those digests, confirmed
  INSTALL.md, and reran the full stdlib suite in a fresh extract: **907
  tests passed in44.187s**, zero failures/skips. This is not a clean-Mac
  install claim. Video is handled separately and is not part of this tag.
