# Idea 1 plan — several chats at once (pipeline overlap)

Date: 2026-10-31 (America/Chicago). Branch tip while planning: `cb61970`
(lab video only; no idea-1 code yet). Read-only inspection of
`docs/ROADMAP.md`, `docs/MLX-SPLIT.md`, `agent/mlx_split.py`,
`agent/mlx_worker.py`, `proxy/slot_pin_proxy.py`. No code changes or
benchmarks run for this plan.

## Goal (plain language)

Today one chat uses the lead and Packer 1 in lockstep: for every token,
Packer 1 runs its layers, then the lead runs its layers and picks the
token. Each Mini is idle about half the time.

Idea 1 keeps **two or three chats** in flight so while the lead finishes
chat A’s token, Packer 1 is already working on chat B’s. **Per-chat
writing speed does not go up**; **total tokens/s across chats** should
rise toward ~2× when the halves are balanced. ROADMAP expects this for
agents / several users, not for a lone chat (guess-ahead is idea 3 for
that).

Use idea 5’s **balanced cuts** so the slower half sets the pace evenly:
Gemma 4 **K=16**, GPT-OSS **K=13**, Qwen3 **even**. Keepalive (idea 6)
stays on; idea 1 sits on top of it.

## What blocks it today

1. **Proxy FIFO** (`proxy/slot_pin_proxy.py` `completion_fifo`): all
   completions (llama.cpp and MLX) go one at a time. A second chat waits
   until the first finishes.
2. **Lead worker Engine** (`mlx_worker.py`): one dedicated MLX thread and
   a job queue — “one generation at a time.” HTTP handlers already hand
   jobs in; only one `gen` runs.
3. **SplitModel / FrontClient** (`mlx_split.py`): one TCP connection,
   used only from that MLX thread (explicitly “so no locking”). Each
   `fwd` is a blocking round-trip: send tokens → wait for packer hidden
   state → run lead layers → logits.
4. **Packer FrontState**: single `self.cur` session for non-scratch
   `fwd`; `serve_front` accepts one lead connection and answers ops
   serially on the calling thread.
5. **Sessions**: `SplitSessions` keeps lead and packer stores in
   lockstep for prepare/save/restore, but generation still serializes
   through one `fwd` at a time.

So even if the proxy let two requests in, the lead would still run them
back-to-back, and the packer would still see one `fwd` then the next.

## Target design (smallest useful version)

**Pipeline depth 2** first (two chats), then try 3 if memory allows.

### Interleave pattern (writing)

For chats A and B generating tokens:

```
Packer:  A1 → B1 → A2 → B2 → …
Lead:       A1 → B1 → A2 → B2 → …
```

After warm-up, both Minis stay busy. Ideal aggregate writing ≈
`1 / max(t_packer, t_lead)` tokens/s **per chat cadence**, times 2 chats
≈ `2 / max(t_packer, t_lead)`. With balanced cuts and keepalive, halves
are ~16–18 ms, so one chat ~30–45 tok/s today; two chats could approach
~60–90 aggregate tok/s if overlap is tight and overhead stays small.

### Prefill / reading

Same idea as ROADMAP idea 2 (chunked reading), but for idea 1’s first
cut: **do not** require overlapping prefill. Measure writing overlap
first with short prompts / warm sessions. Optionally later: while lead
reads chat A’s prefill chunk, packer starts chat B’s — out of scope for
v1 of this plan.

### Session identity

Each in-flight chat keeps its own session key / KV cache on **both**
halves (already true for sequential multi-session). Concurrent `fwd`
must name which cache: extend the `fwd` header with `key` (or a
stable ctx id) instead of relying on packer’s single `self.cur`.

Scratch warmup (`ctx=scratch`) stays single-flight at startup.

## Concrete code changes

Order matters: make the string able to pipeline, then open the gates.

### A. Protocol / packer (`agent/mlx_split.py`)

- Add `key` (session id) on `fwd` (and maybe `checkpoint`/`rewind` if
  concurrent turns need them). Packer looks up `store.sessions[key]`
  instead of only `self.cur`.
- Keep `prepare` setting `cur` for back-compat, but concurrent path
  always passes `key`.
- `serve_front`: still one TCP connection from the lead is fine for v1
  (ops still ordered on the wire). Concurrency is **logical** (A then B
  ops interleaved), not two sockets.
- Optional later: packer-side queue if we move to async send/recv; not
  needed if the lead drives the schedule.

### B. Lead split client / model (`mlx_split.py` + `mlx_worker.py`)

- **Scheduler on the lead MLX thread** (stay single-threaded for MLX
  safety): cooperative multitasking of 2–3 active generations.
  Sketch:
  - Each active gen is a small state machine: `need_packer` →
    `have_hidden` → `ran_lead` → emit token / sample → next.
  - When gen A is waiting on packer, do **not** block the whole Engine;
    instead issue packer `fwd` for B (or run lead work for a gen that
    already has hidden states).
- Practical v1 approach that fits current blocking sockets:
  1. **Async packer I/O on a helper thread**: lead posts `fwd` request,
     continues other MLX work only when safe; **or**
  2. **Strict lockstep scheduler with non-blocking progress**: send A’s
     `fwd`, immediately send B’s `fwd` only after A’s reply if the
     socket is still request/reply — **that cannot overlap**. So the
     socket must become **pipelined request/reply** (multiple in-flight
     frames) **or** use two connections.

**Recommendation for v1:** **two logical streams over one connection
with sequenced frames** (each frame carries `key` + `seq`), packer
replies with same `key`/`seq`, lead may have one outstanding `fwd` per
active chat (max 2). Packer processes FIFO but lead can have sent the
next chat’s `fwd` only after receiving the previous reply unless we
allow N outstanding.

Wait — with one outstanding request, packer and lead still cannot
overlap compute: lead is idle until reply. **Overlap requires either:**

- **(Preferred)** Lead runs chat A’s lead-layers while packer’s reply
  for B is in flight: so after receiving A’s hidden state, lead
  **sends B’s `fwd` first**, then runs A’s local layers while waiting
  for B’s reply (keepalive thread already warms GPU during recv; now
  real work replaces idle).

  Sequence for depth 2:

  ```
  send fwd(A)
  recv h(A)
  send fwd(B)          # packer starts B
  run lead_layers(A)   # overlaps packer(B)
  sample A
  recv h(B)
  send fwd(A')
  run lead_layers(B)
  …
  ```

  This needs only **one** outstanding request at a time after the
  prime, and fits today’s request/reply socket. First token still
  serial; steady state overlaps.

- Engine changes: replace “one `stream_generate` to completion” with a
  dual-gen loop, or run two generators that yield control at the packer
  boundary (custom step loop instead of stock `mlx_lm.stream_generate`
  for the split path).

### C. Engine job model (`mlx_worker.py`)

- Allow **up to N concurrent `gen` jobs** on the MLX thread (N=2 or 3),
  scheduled as above; or one special `multi_gen` job that owns the
  pipeline.
- HTTP: multiple handler threads already exist; they already enqueue.
  Change `_main` so a second `gen` is accepted while one is in the
  packer-wait/lead-overlap window (not a second OS thread doing MLX).
- Cancel: if client A disconnects, drop A from the pipeline without
  killing B; packer must ignore or rewind only A’s key.

### D. Proxy (`proxy/slot_pin_proxy.py`)

- For **MLX split upstream only**, allow up to N concurrent completions
  (config flag, default 1 for safety). llama.cpp path stays FIFO=1
  unless separately designed (slots already exist there).
- Session fingerprints still pin caches; two different sessions must
  not share one fingerprint.
- Do not hold `completion_fifo` across the whole MLX stream when
  multi-flight is on; use a **separate MLX concurrency semaphore**
  (N) so llama and MLX don’t block each other incorrectly.

### E. Cuts / flags

- Default `--split-packer-layers` to idea-5 balanced values per model
  when idea 1 is enabled (or document required K in bench scripts).
- Feature flag e.g. `--split-pipeline-chats 2` (0/1 = off).

### F. Docs / tests

- Unit tests: frame codec with `key`; packer `fwd` by key; scheduler
  ordering (send B before lead A).
- Update ROADMAP checkbox, MLX-SPLIT “no overlap yet”, BENCHMARKS,
  CHANGELOG when measured.

## How to benchmark (after code exists)

Reuse `bench/v3/split_client.py` patterns; add a small concurrent
harness (new script under `bench/v3/`, e.g. `pipeline_bench.py`):

| Case | Clients | What to report |
|---|---|---|
| Baseline | 1 | Writing tok/s (tg128), TTFT, pp512/pp4096, quality 3/3, peak GB lead+packer, split `calls`/`mb` |
| Pipeline | 2 | **Per-chat** writing tok/s, **aggregate** tok/s (sum), wall time to both finish fixed token budgets, quality 3/3 each |
| Pipeline | 3 | Same |

Method:

- LPM off on both Minis; keepalive on; ports = test ports only.
- Same model trio: Gemma 4, GPT-OSS, Qwen3; balanced K.
- Warm once; medians of ≥2 runs; never invent numbers.
- Start N clients with **distinct** `X-Caravan-Session` fingerprints
  and staggered by ~0–1 token so the pipeline primes.
- Success bar (from ROADMAP tone): aggregate writing with 2 chats
  clearly above 1-chat baseline (target near 1.6–2.0× if halves
  balanced); per-chat not slower than ~half of single-chat by more
  than overhead; quality 3/3; memory fits two (or three) KV caches on
  each Mini.
- Also log lead/packer CPU during run (stand-in for “both busy”).
- Compare to one-Mini v2.1 single-chat only as context, not as the
  idea-1 success bar.

## Risks

| Risk | Why | Mitigation |
|---|---|---|
| MLX not thread-safe | Engine comment: all MLX on one thread | Keep one MLX thread; only overlap packer RTT with lead compute |
| Session mix-ups | Packer `cur` is global today | Require `key` on every concurrent `fwd`; tests |
| KV / peak memory | 2–3 caches × both Minis | Cap N=2 first; measure peak_gb; refuse 3 if OOM |
| Proxy vs worker mismatch | Proxy still FIFO=1 → never stresses pipeline | Flip proxy MLX concurrency in same change set |
| Cancel / disconnect | One client gone mid-pipeline | Per-key cancel; don’t reset peer epoch |
| Quality / sampling | Custom step loop vs `stream_generate` | Same sampler APIs; quality 3/3 gate |
| Save/restore races | Disk save under concurrency | Serialize save/restore ops; only pipeline pure `fwd` |
| Keepalive interaction | Side thread during recv | Fine if lead does real work during recv instead; keep flag |
| Stale assumption “nearly doubles” | Cable + graph build + imbalance | Balanced K; measure; report real ratio |

## Out of scope for first implementation

- Idea 2 chunked reading assembly line.
- Idea 3 speculative decoding.
- Idea 4 tensor parallel (parked).
- Changing llama.cpp FIFO.
- Merging to `main` / pushing without Brenden’s go.

## Suggested implementation order

1. Protocol: `fwd` + `key`; packer multi-session fwd; tests.
2. Lead scheduler: prime A, then send B before lead(A); dual-gen loop.
3. Engine: accept 2 gens into that scheduler.
4. Proxy: MLX concurrency N=2 behind a flag.
5. Bench script + numbers → docs.

## Done when

- Flag off: behavior and single-chat numbers match today’s keepalive
  baseline (no regression).
- Flag on, 2 chats: aggregate writing clearly higher; quality 3/3;
  docs updated with measured numbers only.
