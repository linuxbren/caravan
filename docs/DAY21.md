# Day 21 — clearer Balance, loose ends and Thunderbolt discovery

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

**Not run in phase1.** Main restore was already reboot-proved in Day20; the
new aux primary/RAM gate still needs physical reboot evidence. LaunchAgents
require desktop login after startup; FileVault may require local unlock.
Do not call a manual service restart or a no-reboot health check reboot proof.

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

No new sockets/probes, data handshakes, benchmark transfers, route or macOS
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
