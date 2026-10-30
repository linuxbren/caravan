# Architecture

This is the current reference for how Caravan is put together and where
it's heading. The design was worked out in a 2026-09-06 session (see
`docs/LOG.md` for the narrative and the measurements); update this doc in
place as the design changes. For setup and configuration see the
[README](../README.md).

## Components today

```
client --> :8090 slot_pin_proxy.py --> :8080 llama-server (head) ==RPC==> :50052 rpc-server (tail)
                 (node-a)                    (node-a, full GGUF)          (node-b, --cache)
caravan-agent on each node: /health on :8091, discovery, role, supervision
```

| component | where | status |
|---|---|---|
| `agent/` (Python) | every node | Has run in production under launchd (`com.caravan.agent`): role detection, discovery, fastest-path selection, supervision of `llama-server` or `rpc-server --cache`. |
| `proxy/slot_pin_proxy.py` | head | Has run in production (`com.caravan.slot-pin-proxy`). Separate from the agent. |
| `launchd/com.caravan.llama-server.plist`, `com.caravan.rpc-server.plist` | head / tail | The manual per-role alternative to the agent. The llama-server plist is rendered from the agent's own command builder (`agent/render_llama_plist.py`). |
| `cpp/` | every node | Experimental single binary: head and tail in-process, mDNS + Tailscale discovery. Proven end to end once; missing `--cache`, health server, identity, supervision, configurable model. |

### The proxy

llama-server assigns requests to slots on its own and was found moving
conversations between slots, discarding their cached prompt each time.
The proxy sits in front of it and:

- **Fingerprints sessions.** Chat requests use a hash of the first
  non-system message, skipping a client-inserted, timestamped "session
  bootstrap" marker. Raw-prompt requests use a hash of a fixed-length
  prompt prefix. Requests with no usable identity are one-shots.
- **Pins slots.** Each session keeps its slot; new sessions take the least
  recently used slot. Occupancy and last-use times persist in
  `~/.caravan/proxy/session_slots.json`.
- **Serializes completions** through a FIFO gate, and cancels the upstream
  request when the client disconnects.
- **Persists the KV cache.** Each session's slot is saved to disk with
  llama-server's slot save/restore API (`--slot-save-path`). It's restored
  on that session's first request after a restart, unless the slot is
  still warm. Saves are skipped when nothing changed, can be thinned to
  every N turns, or can be done by an idle saver. Every save, restore and
  cleanup happens while holding the FIFO gate, so they never overlap a
  request or each other.
- **Cleans up** slot files older than a configurable age.
- **Streams** responses as they arrive, with correct HTTP framing.

llama-server runs with `--parallel N --no-kv-unified`, so each slot owns
a fixed `ctx_per_slot` context. With a unified KV pool, restoring one big
session could exhaust space for the others (see LOG.md).

## Goal

One app (the "Caravan agent"), installed identically on every machine in
the cluster. Each instance figures out on its own whether it's acting as
**head** (serves inference, holds the full model) or a **tail**
(contributes compute to whichever machine is head) — no manually-edited
plist per role, no hand-picked IPs, no human deciding up front which
machine is "the server."

## Why this isn't just "build what exo does"

**Correction (2026-09-06, later that night):** earlier LOG.md entries and
an earlier version of this section claimed exo requires every node to
hold a full local copy of the model. That was wrong -- never verified,
carried forward from an earlier session's assumption. Checked directly:
exo uses pipeline parallelism and each node downloads only the layer
range it's assigned (its "Placement Engine" decides the split, each
node's "DownloadCoordinator" fetches just its own shard) -- see
[exo's README](https://github.com/exo-explore/exo/blob/main/README.md).
That's the same shard-only-storage property this project's own planned
Phase 2 (below) is aiming for, not something Caravan does instead of
exo. Corrected the reasoning below; see LOG.md for the fuller writeup of
what was wrong and why.

llama.cpp's RPC backend still has a real structural asymmetry, just not
the one originally claimed here:

- **Head** (`llama-server`) needs the *full model file* on local disk (to
  read metadata/tokenizer and do orchestration) and does the actual
  serving.
- **Tail** (`rpc-server`) needs *nothing stored* — a dumb, stateless
  compute backend that executes whatever tensors arrive over the wire and
  forgets them when the process exits.

The genuine difference from exo isn't storage footprint -- it's that
exo's pipeline-parallel design has no node that needs *full* model
knowledge; every node, including whichever one starts the pipeline, only
ever needs its own shard. llama.cpp's RPC backend isn't built that way:
the head specifically needs the complete model file present, even though
it only computes some of the layers itself. That's a real, inherent
constraint of this backend, not a duplication cost Caravan is avoiding by
being cleverer than exo. Practical effect is the same either way: head
role follows wherever the full model already lives.

## Role determination — self-declared, not elected

No leader-election protocol. Each agent instance checks its own local
Ollama blob store on startup/periodically:

- Has the model requested → **head** for that model. Launches
  `llama-server --rpc <discovered peers>`.
- Doesn't have it → **tail** candidate. Ensures `rpc-server` is running,
  waits to be used.

In practice there's one Ollama instance across the whole cluster (the
machine running openclaw's gateway, or whichever machine a human/agent
points requests at) — that machine pulls models and is therefore always
head. This is fine and expected, not a limitation to design around: the
value of "one app everywhere" is a uniform install and automatic
tail-side behavior, not that head literally moves around day to day.
Multi-model support falls out for free regardless (different nodes could
independently be head for different models, if that ever becomes real
usage) without any extra design work.

No safeguard is needed for "two nodes both have the same model and both
try to become head" — given the single-Ollama-instance reality this
isn't a real scenario. Revisit only if actual usage changes.

## Discovery — mDNS + Tailscale, then the fastest live path

- Every agent advertises and browses a `_caravan._tcp` Bonjour/mDNS
  service on the LAN: zero-config, no other infrastructure needed.
- When Tailscale is running, the agent also reads `tailscale status
  --json` for peers.
- A discovered machine counts as a peer only if its Caravan agent answers
  `/health` on port 8091. This keeps unrelated machines on the same LAN or
  tailnet out of `--rpc`.
- Each agent has a small persistent identity (a UUID under
  `~/.caravan/agent/`). Peers seen through both mechanisms are merged by
  normalized hostname.
- **Path selection:** each agent's `/health` reports its `fast_paths`
  (IPv4 addresses on up Thunderbolt Bridge interfaces). The head tries
  those first, then the Tailscale address, then the mDNS/LAN address, and
  uses the first one whose agent answers. If the cable is unplugged it
  falls back automatically. This is a fixed priority by interface type,
  not a bandwidth measurement.
- History: Tailscale used to be preferred over LAN because LAN connections
  failed from some process contexts. The real cause turned out to be
  macOS's Local Network privacy permission. A `llama-server` launched
  directly by launchd has no grantable identity; spawned by an allowed
  parent (the Python agent) it inherits the grant. See LOG.md, "The actual
  root cause".

## Head/tail interaction

Head, once it knows which peers are live tail candidates, decides a
tensor split and launches `llama-server --rpc host1:port,host2:port,...`
pointed at them — conceptually "I've got this model, I'm head, here's
your shard." Tails just need `rpc-server` already running and reachable;
llama.cpp's own RPC protocol handles the actual tensor transfer.

"Cache it for next time" (a tail persisting its assigned tensor range
across restarts) is **not** part of this phase — see Phase 2 below.

## Scope: what "one app" actually covers

Not just process spawning. Everything that's currently a separate,
manually-managed piece is in scope to eventually be absorbed into this
one agent, not left standing alongside it forever:

- **Process supervision** (Phase 1, below) -- replaces the hand-written
  launchd plists.
- **The slot-pinning reverse proxy** (`../proxy/slot_pin_proxy.py`) --
  currently a third, separately-supervised process. Not yet folded in;
  real open question is whether it becomes a component the agent runs
  itself, or stays a standalone piece the agent merely launches/monitors.
  Not decided -- see Open Questions.
- **Cross-node restart coordination** -- `../scripts/restart-rpc-server.sh`
  encodes the safe restart order (stop head, restart tail, start head)
  as a manual/scripted operator action today. Once agents run on both
  nodes with a real health/status surface between them, this becomes
  something the agents negotiate directly (a tail can tell its head "I'm
  about to restart" and get a clean pause instead of a crash) rather
  than a human running a script. See GitHub issue #7.
- **Monitoring/heartbeat** -- `health_server.py`'s `/health` endpoint
  today only answers "is this node a live Caravan agent" (for discovery
  gating). Growing it into real liveness + resource reporting (CPU,
  memory, and GPU memory via `ggml-rpc`'s existing `RPC_CMD_GET_DEVICE_MEMORY`)
  is the natural, single place this lives -- not a separate monitoring
  script -- since this endpoint already exists and already runs on every
  node.

## Two build phases

**Phase 1 — orchestration/robustness layer (built, proven under launchd).** Discovery,
self role-detection, process supervision (spawn/monitor `llama-server` or
`rpc-server` locally based on role, replacing the hand-written per-role
launchd plists), and picking the fastest live path per peer. This absorbs
GitHub issue #1 (manual launchd supervision). The per-role plists remain
as a manual fallback.

**Phase 2 — shard cache.** ~~A real patch to `ggml-rpc.cpp`~~ **Done
already, turned out to need no patch at all** (2026-09-06, later still:
see LOG.md, "Issue #3: solved natively"). `ggml-rpc.cpp` already ships a
hash-keyed, self-invalidating on-disk tensor cache; `rpc-server --cache`
turns it on. Verified live: 53s warm-cache restart vs. 7-11 minutes cold.
The agent passes `--cache` when it spawns `rpc-server`
(`supervisor.build_tail_command()`). The Thunderbolt link later cut the
*cold*-cache transfer to 29-39 s (LOG.md). Corresponds to GitHub issue #3,
now closed.

## Language

**Phase 1: Python.** Matches the existing `slot_pin_proxy.py`, no build
step, cheapest to iterate while the design is still moving. The agent
needs Python 3.10+; the proxy is stdlib-only and 3.9-compatible.

**In progress: C++ single binary (`cpp/`).** Rather than a full rewrite,
llama.cpp itself is linked as a library: `llama_server()` for the head and
`ggml_backend_rpc_start_server()` for the tail, called in-process, with
mDNS and Tailscale discovery ported from Python. The llama.cpp fork's
`caravan-patches` branch carries Caravan's patches. See `cpp/README.md`.

**Later: a compiled language, undecided.** Once Phase 1 has proven itself
in real daily use, port it — this is PLAN.md's stage 3 packaging/"real
app for other people" milestone, a distinct later decision, not something
Phase 1 needs to serve. The reasoning captured here and in LOG.md/GitHub
issues is the actual bridge to that port — not portable Python code.
Options, for whenever that decision comes up:

- **Go** — full cross-platform (macOS/Linux/Windows/BSD/more) with
  trivial cross-compilation (`GOOS`/`GOARCH`, no target SDK needed). Best
  choice if a non-Mac node ever joins the cluster.
- **Rust** — same platform breadth, the most battle-tested of the three
  for this class of networked infra tooling, more cross-compile setup
  overhead than Go.
- **Swift** — best native fit for today's all-Mac fleet: built-in
  Bonjour/Network framework (no third-party mDNS library needed), clean
  launchd/codesigning story. Real official Linux support, but less
  mature/common for this than Go or Rust; Windows support is the least
  mature of the three.

**Ruled out: Ruby / Rails.** Ruby is interpreted — a peer to Python, not
a compiled-language option. Rails specifically is a web application
framework (MVC, database-backed models, views, asset pipeline); Caravan's
agent is a networked daemon with no database and no web UI, so Rails'
actual machinery doesn't apply. Plain Ruby would be a fair comparison to
Python but has no advantage here — weaker stdlib/ecosystem for this kind
of systems/networking work, and, like Python, still needs a language
runtime installed on every node, so it doesn't get any closer to the
eventual compiled/dependency-free goal either.

## Open questions (not yet decided)

- Head selection is "whoever has the model". There's no handling for two
  nodes that both have it; acceptable while one machine owns the Ollama
  store.
- The fallback `--rpc` in the hand-managed plist is a literal link-local
  (169.254.x.x) address, which macOS can reassign. The agent and
  `render_llama_plist.py --rpc auto` avoid this by discovering it.

- Exact wire format for the head→tail "here's your shard" coordination
  message (today this is implicit in how `llama-server --rpc` connects
  out; whether the agent needs its own explicit message on top of that,
  or whether "tail has `rpc-server` reachable" is sufficient, is unresolved).
- Whether the slot-pinning proxy becomes a component the agent runs
  itself, or stays a standalone piece the agent merely launches/monitors
  (see "Scope: what 'one app' actually covers," above).
- Exact protocol for cross-node restart coordination (a tail telling its
  head "restarting, please pause" before it goes down) — GitHub issue #7
  scoped this down considerably once issue #3 made recovery cheap (~50s),
  so this is lower urgency than it was, but still undecided.

## Relationship to existing GitHub issues

Issues live at <https://github.com/linuxbren/caravan/issues>; statuses
below are as of the last update to this section.

- **#1** (supervise processes with launchd) — closed
  (2026-09-06, crash-recovery verified live). Phase 1 still absorbs the
  *manual per-role plist* problem this leaves behind; #1 itself was
  narrower (does it survive a crash/reboot) and that part is done.
- **#2** (system prompt size) — unrelated, still open on its own track.
- **#3** (shard-scoped cache) — closed (2026-09-06, solved natively via
  `rpc-server --cache`, no patch needed — see Phase 2 above). The agent
  passes the flag.
- **#7** (node-to-node lifecycle signaling) — open; two of its three
  proposed signals turned out to already be covered by existing
  mechanisms (see LOG.md), the remaining monitoring/coordination piece
  is this doc's "Scope" section above, not separate work.
