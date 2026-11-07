# Roadmap

What's built, what's next and in what order, and what's still limited.
Numbers are from [BENCHMARKS.md](BENCHMARKS.md) (one Mac mini M4 24 GB
unless noted). "4k" and "16k" are chat lengths in tokens.

*Last updated 2026-11-01 (idea 1 + N=3 stall fix shipped as v3.3; Day 6
video v12 / techie-friend cut as v3.4; idea 3 guess-ahead auto-pair). Per-version changes: [CHANGELOG.md](CHANGELOG.md).*

**Names.** In a split, the **lead** is the Mac you talk to (it serves the
API, runs the last layers and picks each token), the **packers** are the
other Macs, numbered in layer order (Packer 1 runs the first layers), and
the whole group is the **string**. The old words "head", "front" and
"tail" survive only in older log entries, internal code names and
deprecated flag aliases.

## Firm rules

### Each packer keeps its share of the model on its own disk (GGUF and MLX)

The lead never resends a packer's portion at startup. A restart, or going
back to a model the packer already has, should send no weights over the
cable. A packer that's missing files gets them from the original source
(Hugging Face), never from the lead.

Where things stand (checked 2026-10-31 against this branch's code and the
disks on EXO1 and EXO2):

| Format | Rule met? | Why |
|---|---|---|
| MLX (v3 split) | **Yes** | Packer 1 loads its layers from its own folder (`--model` is a local path) and reads only those weights. The link between the Macs carries hidden states and session commands (`hello`, `prepare`, `fwd`, `save`, `restore` and so on); it has no way to send weights or files. If a shard it needs is missing, the packer refuses to start and names the files to fetch with `mlx_split_fetch.py`. It never downloads on its own and never copies from the lead. On EXO2 the packer loaded in 0.4–7.0 s for every v3 run. |
| GGUF (llama.cpp RPC) | **Partly** | In llama.cpp's design the lead reads the whole GGUF and sends each packer its tensors at load. With `rpc-server --cache` (on by default in the agent and in the plist) the packer saves each tensor over 10 MiB to `~/Library/Caches/llama.cpp/rpc/`, named by a hash of its contents, and later loads send only the hash for those. Still sent every time: tensors of 10 MiB or less (0.56 GB of the whole Qwen3 30B Q4_K_S file and 0.84 GB of Gemma 4 26B q4_0; the packer gets its layers' share). Sent in full: the first load of any model or of a changed file. EXO2's cache today (504 files, 14.4 GB, written Sep 8–10) holds none of the tensors of the GGUFs now on EXO1, so the next two-Mac GGUF start would be a full cold send. Stage 2 (Next, item 5) is what makes this a yes. |

Open tasks for this rule:

- [ ] **GGUF stage 2** (Next, item 5): the packer loads its tensors from
  its own copy of the file, small tensors included, so the lead sends no
  weights at all.
- [ ] **GGUF, until then: show cache misses.** Log, at each load, how much
  the lead actually sent to each packer, so a cold send is visible.
- [ ] **GGUF: own the packer's cache.** Caravan doesn't manage it today:
  there's no size cap and no cleanup of tensors from old models (slot
  cleanup only touches the slot and MLX session folders), and it sits
  under `~/Library/Caches`, which macOS cleanup tools may clear. Point it
  at a Caravan folder with `LLAMA_CACHE` and add a cap that never
  removes the current model's tensors.
- [ ] **GGUF: the C++ binary** has no `--cache`, so it always resends.
- [x] **MLX: check the files on startup** (sizes done, v3.1). Each stage
  checks that its shards exist and have the right size: the size their
  own safetensors header implies, and the size Hugging Face lists when
  `mlx_split_fetch.py` recorded it (`caravan-split-sizes.json`). A wrong
  size stops the stage with the file name and the fetch command.
  Still open: checksums (a file of the right size with bad bytes isn't
  caught).
- [ ] **MLX: fetch missing shards from the source.** Offer to run
  `mlx_split_fetch.py --role packer` (Hugging Face) instead of stopping
  with an error. Never fetch from the lead.
- [ ] **MLX: the lead checks it's the same model.** `hello` compares only
  the layer range and layer count. The packer already knows its model
  name and tokenizer hash, so compare those too.
- [ ] **MLX: keep packer files in Caravan's own folder**
  (`~/.caravan/mlx-models`). The Qwen3.6 35B packer on EXO2 ran from
  exo's model folder, which exo manages and could remove.

## Done

### Before v0: the split, the proxy, the agent (Sep 2026)

1. **Prove the split.** One 16 GB-weight GGUF model ran across two Macs
   with llama.cpp RPC (Metal on both).
2. **Make it usable day to day.**
   - The proxy: a session keeps its slot, requests run one at a time,
     requests are cancelled when the client disconnects, and slots are
     saved to disk.
   - launchd supervision.
   - The Thunderbolt cable: the packer's cold load went from 7–11 min to
     29–39 s, and writing from ~4 to 6.1 tok/s.
   - The shard cache, which turned out to be native (`rpc-server --cache`).
3. **The self-organizing agent.**
   - mDNS and Tailscale discovery, lead and packer roles.
   - Automatic Thunderbolt > Tailscale > LAN path choice.
   - Supervision.
   - The root cause of the launchd networking failures: the Local
     Network permission.
4. **Unified C++ binary (experiment).** Lead and packer in one process with
   mDNS discovery, proven end to end once.

### v0: baseline (`45ed2c2`, Oct 30)

- Configurable target model.
- Saved-slot cleanup after 30 days.
- Proxy performance work: LRU slots, fewer saves, prefix fingerprints for
  raw prompts, smoother streaming.
- Explicit llama-server flags.
- Docs for the public repo.

### v1: rebased llama.cpp, MLX through the proxy, automatic KV (`32b9756`, `737fea2`, `c846e65`)

- **Rebased llama.cpp** (upstream `5047748f`) keeps checkpoints in slot
  files. A 16k chat after a restart: GPT-OSS 46.3 → **0.65 s**, Gemma 4
  56.1 → **0.93 s**.
- **Faster reading** (pp4096): GPT-OSS 403 → 454, Gemma 4 355 → 380,
  Qwen3 338 → 356 tok/s.
- **Automatic KV type**: f16 when it fits (Gemma 4, GPT-OSS), q8_0
  otherwise (Qwen3).
- **MLX step a**: MLX ids routed to `mlx_lm.server`. It worked, but Gemma 4
  and GPT-OSS reused nothing between messages.

### v2: the Caravan MLX worker (`f57af3b`, `6d4bdb0`, `fac73b8`, `f73eafb`, `7835efd`)

- **Per-session MLX caches** with checkpoint and rewind, saved to disk.
  Turn 2 of a 4k chat: Gemma 4 10.76 → **0.49 s**, GPT-OSS 9.16 →
  **0.50 s**. After a restart: 12.7–16.0 → **0.52–0.64 s**.
- **Clean GPT-OSS replies**: the answer goes in `content`, the reasoning
  in `reasoning_content`.
- **Per-Mac cap** on saved chats: 200 files / 50 GB, llama.cpp and MLX
  together, least recently used first, never active sessions.
- **No regression** on the llama.cpp path.

### v2.1: steadier MLX (`b9ebeb7`)

- Wired limit set once at startup and held (`--wired-limit`, default
  `startup`).
- Optional deferred first save (`mlx_save_min_turns`).
- **Benchmarking method changed**: versions are compared side by side in
  one session. With that method, v1, v2 and v2.1 read 4k at 396, 393 and
  396 tok/s.

## Next, in order

> **Priority rule (Brenden, Days 15–17, Nov 3–6 2026):** performance first, flash second. Days15–16 shipped web UI, picker/placement, N-node Topology, self-tuning controls and four themes. Day17 measured matching-target MTP (#16), adaptive prompt lookup, two-chat scheduling, then approved split block verification. Orvena EXO2 native MTP36.95→54.13 Write tok/s,98.21% proposals accepted; incompatible with Qwen30B. Qwen copy PL50.11→72.37 but mixed50.24→47.31, so default stays off. Approved split: baseline aggregate N1/N2 **41.54/70.49tok/s**; helper N1/N2 **52.11/49.77tok/s** (N2 helper slower, experimental). Fixed socket-owner race exposed by live N2 tests; all failures retained. Final Qwen singleEXO1 ready, all Auto, pre-existing KV4 trial applied (benchmarks KV16). [Raw results/reasoning](DAY17-BENCHMARKS.md). Next: improve N2 draft overlap before promoting it, remaining settings/node polish and Terminal Delight; fused kernels/tensor parallel parked.

1. ~~**Publish the rebased llama.cpp branch.**~~ **Done (2026-10-31).**
   The fork moved to `linuxbren/llama.cpp`. There, `caravan-patches` is
   the rebased branch (upstream `5047748f` + the RPC patch) that the v1+
   numbers depend on, and `caravan-patches-v0` keeps the old base used
   for v0.
2. **Two-Mac MLX split.** *In progress (v3, 2026-10-31).* Run one MLX
   model across both Macs, as llama.cpp RPC does for GGUF, so models and
   long chats that don't fit on one 24 GB Mac (Qwen3 at 16k) can run on
   MLX. Design: [MLX-SPLIT.md](MLX-SPLIT.md).
   - [x] Feasibility: `mx.distributed` ring fails on ≥2 MB messages over
     Thunderbolt; jaccl needs Thunderbolt 5; mlx-lm pipeline sharding
     covers only Qwen models. Chosen: Caravan's own layer pipeline over one TCP
     connection.
   - [x] Lead/packer worker pair (`--split-role lead|packer`), Qwen3, Gemma 4
     and GPT-OSS.
   - [x] Per-stage session caches with save/restore on each Mac (both
     halves or neither).
   - [x] `mlx.split` config and packer-command builder; unit tests.
   - [x] Side-by-side numbers vs v2.1 on one Mac (2026-10-31, one
     session; [BENCHMARKS.md](BENCHMARKS.md#v21-vs-v3-one-mac-vs-two-macs-oct-31-mlx)).
     Memory per Mac roughly halves (Qwen3 19.0 → 10.5 GB, Gemma 4 17.1 →
     9.3 GB, GPT-OSS 13.4 → 7.1 GB) and Qwen3 now holds a 16k chat. The
     price: writing 28–42% slower, reading 16–25% slower, turn 2 and
     restart resume +0.1–0.4 s. Quality 3/3 on both. **Rerun Oct 31 with
     Low Power Mode off on EXO2** (it had been on for these numbers):
     writing 30.4 / 27.7 / 26.6 tok/s (27–40% slower than one Mac),
     reading within about 6% of one Mac; see
     [BENCHMARKS.md](BENCHMARKS.md#v3-rerun-with-low-power-mode-off-oct-31-mlx-v31).
   - [x] Bigger brothers split across both Macs: Qwen3 30B 8-bit (16k chat
     fits at 18.1 GB per Mac), Gemma 4 26B 8-bit (15.6 GB per Mac) and
     GPT-OSS 20B 8-bit (12.1 GB per Mac), all 3/3, 16k chats fit; none fits
     on one Mac. Writing 24–33% slower than the 4-bit versions. Qwen3.6
     35B-A3B 5-bit ran as an extra. GPT-OSS only comes in 20B and 120B; no
     120B build fits two Macs with chat room (parked), so its bigger brother
     is the 20B at 8-bit.
   - [x] Proxy routes MLX requests to the lead unchanged (smoke test).
   - [x] Lead / packer / string naming (`83f86a9`); old flag, env and
     config names kept as deprecated aliases.
   - [x] Docs: CHANGELOG, configuration (split flags, env, config,
     deprecated names), bench/v3 README.
   - [x] Copy the renamed code to the packer Mac (EXO2): `~/cv3` is now a
     git clone of this branch at `d23a276` (Oct 31); the old copy is kept
     as `~/cv3.pre-rename-2026-10-31`.
   - [x] Housekeeping (Oct 31): repointed the broken
     `~/.caravan/models/gpt-oss-20b.gguf` symlink on EXO1 at the Hugging
     Face copy of `gpt-oss-20b-MXFP4.gguf`; removed 13 stale
     `.incomplete` partial downloads (9.22 GB) from the two 8-bit MLX
     models on EXO2 after checking every finished shard against Hugging
     Face's sizes.
   - [ ] Start the split from the agent and launchd (today both halves
     are started by hand; `mlx.split` is only read by the
     `mlx_backend` command helpers).
   - [ ] Merge to `main` (waiting for review; not pushed).
3. **Split download (MLX).** Each Mac downloads only its own layers
   straight from Hugging Face; nothing relayed through the lead. Read
   `model.safetensors.index.json`, map each node's layer range to its
   shard files, fetch them with `snapshot_download(allow_patterns=...)`
   plus config and tokenizer files. Edge cases: shards that straddle the
   cut (both Macs fetch them), embeddings and `lm_head`, tied embeddings
   (the lead needs the embedding shard too), vision towers (skipped for
   text-only), and re-planning when more packers join (a new cut means new
   shards, and files no longer needed should be reported, not deleted).
   *Prototype in v3: `agent/mlx_split_fetch.py`. Qwen3 30B 8-bit: the lead
   downloaded 16.65 GB and the packer 21.09 GB instead of 32.44 GB each,
   and the split loaded from those partial copies. Not yet wired into
   the agent (it's a CLI), and it doesn't re-plan when the cut changes.*
4. **Split download (GGUF), stage 1: rpc-server's local tensor cache.**
   With `ggml-rpc-server -c/--cache` the packer keeps the tensors it
   receives on disk, keyed by hash, so it only receives its weights over
   the wire the first time. *Checked 2026-10-31: our build has `-c,
   --cache` and the packer plist already uses it.* What's left: the lead
   still needs the full GGUF on its own disk and reads all of it, and
   tensors of 10 MiB or less are sent every time (see Firm rules).
5. **Split download (GGUF), stage 2: packer loads its own tensors.** A fork
   patch so the packer loads its assigned tensors from its own disk instead
   of the lead pushing them. Each packer fetches only its tensors' byte
   ranges (HTTP Range requests using the tensor offsets in the GGUF
   header), or uses `gguf-split` shards. Then the lead no longer needs the
   packer's part on disk either.
6. **Per-model profiles.** Today Qwen3 needs hand-tuned worker settings
   (sessions in memory, cache budget, chunk size, cache quantization, when
   to save). The plan:
   - Compute a starting profile from the model's size and config against
     the GPU limit.
   - Check it with a short probe on first load.
   - Refine it from the peak memory and speeds the worker already reports.
   - Ship starter profiles for Qwen3, Gemma 4 and GPT-OSS.
7. **Gemma 4 short-prompt cost.** Short prompts read about 8% slower with
   the worker than with plain `mlx_lm.server` (397 vs 430 tok/s at 512
   tokens). The likely cause is the per-reply snapshot of the
   sliding-window layers; make it cheaper or skip it when it isn't needed.
8. **Proxy overhead.** 27–96 ms per MLX request, depending on the model.
   It's mostly cheap already, against v1 behind the same proxy. What's
   left is the one-off ~0.15 s on the first short request after a big
   chat.
9. **Memory headroom.** Qwen3 leaves 16–17% free, and swap reaches about
   1.45 GB.
   - Size the MLX cache from the real GPU limit.
   - Adapt it to free memory.
   - Warn before a request would run out of memory instead of failing.
10. **Cold-disk restore.** Measure restore with the file out of the disk
    cache. Then consider preloading recently used sessions at startup.
11. **Re-measure the two-Mac split** with the v1+ settings (flash
    attention over RPC, automatic KV, larger `ubatch`).
12. **Packaging.** Templated launchd plists (no machine-specific paths), an
    install script, and the agent running the proxy itself.

13. **Fewer flags: self-tuning defaults + settings file.** Cut down the
    number of knobs people have to learn for day-to-day use, while keeping
    every existing flag for benches and overrides.
    - **(a) Detect and pick.** *Shipped Nov 1 (Day 9).* When
      `--split-packer-layers` / `--split-pipeline-chats` are omitted,
      `mlx_worker` auto-picks: (1) packer layer cut from each Mini's
      reported memory (`mem_total_gb` in the packer hello, or the lead's
      own reading when equal) and the model's layer count / type (idea-5
      balanced cuts on equal-RAM 24 GB Minis: Gemma K=16, GPT-OSS K=13,
      Qwen3/Qwen2.5 K=24, Llama K=16); (2) pipeline chat count from free
      memory vs this side's weights, **capped at 2** (Mini benches: every
      family tops out at N=2; never auto-pick 3; never risk swap). Explicit
      flags still win. One plain startup log line each (`auto split: …`,
      `auto pipeline: …`). Mini-verified auto ≡ hand-tuned on Qwen3,
      Llama 3.1 8B, Qwen2.5 14B (quality 3/3, no failures). See
      BENCHMARKS / METHODOLOGY.
    - **(b) Learn per model.** *Shipped Nov 2 (Day 10).* Learn from real
      chats instead of an up-front sweep: start from the Day 9 memory
      guess (or a saved winner), serve each reply with the best settings
      so far, and now and then try a nearby option for live knobs
      (`pipeline_chats`, guess-ahead on/off). Reload-only knobs (packer
      layer cut K) are queued and tried on the next load. Replies are
      timed and length-normalized; several samples are required before
      a switch. Winners are saved per model + hardware (`single` vs
      `spanned`) to `~/.caravan/mlx/tuned-settings.json` and reused on
      the next load, with slow re-checks so the tune adapts when things
      change. Flags still win (`--no-learn` / `CARAVAN_NO_LEARN=1`
      disables). One plain `learn:` log line on each keep/switch/try.
      Module: `agent/tuned_settings.py`.
      **Results (Mini-verified on all six models):** race with no flags and
      no saved file kept the Day 9 guess (2 chats) on every model, so the
      Day 9 guess was already right; learned single-chat writing speed
      Llama 22.1 / Qwen3 44.5 / Gemma 37.3 / GPT-OSS 33.7 / Qwen2.5 12.3 /
      Distill 12.4 tok/s (hand-tuned 22.6 / 45.0 / 38.4 / 34.3 / 12.4 /
      12.3). Trap (seeded at 1 chat) relearned 2 chats by reply 6–10 on
      every model (Qwen3: ~67.8 vs ~37.2 tok/s, switch at reply 6).
      Quality 12/12 on all six (final answer only). Explore cost ~30%
      slower on 3 of 11 Llama test replies. Second load and a mid-run
      kill both resume from the saved file; long prompts kept 2 chats.
      Hand-tuned vs learned time-to-tune was not measured. Note: the Day 10
      Llama single-Mini vs spanned numbers (~16.4 vs ~22.1) came from a
      different setup than the Oct 31 single-vs-split table and are not
      directly comparable to it.
    - **(b2) Self-tuning covers every option.** *Built Nov 5 (Day 15),
      not yet Mini-verified.* Design decision (Brenden): "Self-tuning"
      means all Optimizations options, not "self-tuning except". Besides
      the live trio, it now learns memory compression (kv_bits 16/8/4),
      fused kernels (off/on) and GPU keep-warm (on/off). Those need a
      reload, so a trial is queued, applied on the next load (Load / Apply
      & restart / Deep optimize), scored over 3 replies, then kept or
      rolled back. On/Off pins still win. The web page shows "wants to try
      X — Apply & restart" and a **Deep / Quick optimize** runner (verified live Day 16; single-key `:single` fix) that
      feeds itself fixed prompts and reloads between trials when no chat
      is in flight (cancelable). Only the web launcher turns reload
      learning on (`--learn-reload-auto`); plain CLI runs behave as before.
    - [x] **(c) Optional settings file.** *Built Nov 5.* `~/.caravan/config.toml`
      for human overrides such as `guess_ahead = off` or a preferred
      pipeline N, with `[defaults]` and `[models."<id>"]` tables
      (docs/CONFIGURATION.md, docs/config.example.toml). **Flags stay and
      win over the file**, mainly so benchmarking can pin exact behavior
      without editing config; page choices win too, the file fills Auto.
      Also: self-tune never tries kv_bits 8/4 on models with attention
      sinks (gpt-oss), and a reload trial that breaks the load is rejected
      and rolled back to the winner.

14. **Node view (dashboard).** *First cut built Nov 5:* `GET /api/nodes`
    on the web server (proxy/node_stats.py on each Mini, EXO2 over the
    packer ssh link, cached ~4 s) and live panels in the Topology drawer:
    model + layers held, models on disk, CPU/GPU, RAM, disk free,
    temperature via macmon when installed (else thermal pressure only).
    A live view like exo's, in Caravan's own
    style: each Mini, the layers it holds, memory, speed, chats in flight,
    whether guess-ahead is helping, plus **disk space, temperature, and
    CPU**. Most of the data is already logged; it needs a small status
    endpoint on the proxy (for example `GET /caravan/status`, JSON) and a
    screen that reads it. Shape left open: web page, Terminal Delight
    Workbench items, or both. *Flash second — after performance work.*
15. **Console via Terminal Delight (Parker's app).** Switch models, chat and
    change options from Parker Brown's terminal. Integration guide for
    Parker: `docs/INTEGRATING.md`. Shape left open; see "Terminal Delight as
    Caravan's console" below for the options.
16. **Built-in guesser/MTP experiment — Day17 implemented and measured.**
    Orvena/Orvena-4B-MLX-4bit is a Qwen3.5-4B fine-tune; its omitted BF16 head
    (15 tensors,230.025MiB) is attached by the native single-Mini greedy adapter.
    Matching target fits EXO2 (measured peak2.848GB). **Not compatible** with
    Qwen3-30B-A3B; do not attach across bases. EXO2 OFF/ON ABBA median Write
    36.95→54.13tok/s,550/560 proposals accepted; all12 uncapped, small semantic
    checks pass but code assertions differ (not bit-exact). UI option only when
    a matching head is installed; caches remain16-bit, no N2/native combination.
    Head extraction, provenance, vendor/source links and every failed run:
    [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md). Target/head kept, worker stopped.
17. **Experiment: fused kernels.** *Parked (Day 12, 2026-11-03).* Goal was
    to fuse small GPU steps so the GPU stops and starts less. Research:
    MLX 0.32 / mlx-lm 0.32 already use `mx.fast` for rms_norm, rope, SDPA
    and already `mx.compile` SwiGLU; the long tail is MoE routing and
    custom qmm (oMLX-style). Tried off-by-default `--fuse-kernels`
    (`force_fused` SDPA + Metal SwiGLU) plus `mx.compile` on layers. One
    Mini (LPM off): Llama 8B write 23.75 → 23.7 tok/s, Qwen3 30B-A3B 50.6 →
    50.8; quality 3/3 both; memory flat. Spanned follow-up (EXO1+EXO2,
    single + two chats, guess-ahead off): Llama / Qwen3 off→all and Gemma
    off→metal-swiglu all within about ±0.5% write; Gemma `all`/`force-fused`
    crashes (head dim 512). Still below the 5% go bar. Flag plumbing kept
    (default off). Revisit only with custom quantized-matmul / verify
    kernels. Details:
    [handoff/lab/experiments.md](../handoff/lab/experiments.md) Day 12 and
    `handoff/lab/day12-fused/` (+ `spanned/`).

## Possible future directions (not scheduled)

Ideas worth writing down. None is planned or started.

### Terminal Delight as Caravan's console

[Terminal Delight](https://github.com/parker-brown-family/terminal-delight)
is a Rust terminal for Linux (Omarchy) by Parker Brown. Two of its features
could make it a terminal-first console for Caravan instead of a web UI:
the **Local launcher** (`~/.config/terminal-delight/local-agent.toml`,
which starts a local agent program in a pane) and **Workbench surfaces**
(the program writes JSON items under `surfaces/<session>/<pane>/`, which
the terminal renders next to the pane; see `app/src/surfacefeed.rs`).

Ways to do it, least work first:

1. **An existing CLI in a pane.** `aichat`, `llm` or a short Python loop,
   pointed at the proxy on port 8090. Works today, no Workbench items.
2. **A small Caravan chat program, started from the Local launcher
   (recommended).** It keeps the whole chat and resends it every turn (so
   the proxy recognizes the session and reuses its cache), streams the
   reply, and writes Workbench files. For GPT-OSS it would show the
   reasoning and the answer as separate items.
3. **Codex through the Local launcher.** Little code, but Codex talks
   `/v1/responses`, which the proxy passes through without queueing or
   session pinning, so it would miss Caravan's chat reuse.
4. **A native Rust chat pane in Terminal Delight.** The nicest result, but
   it needs Parker to add an HTTP client to the terminal.

Gaps on the Caravan side this would expose:

- The proxy listens on `127.0.0.1` only (`slot_pin_proxy.py`, the
  `ThreadingHTTPServer` call near the end). Another machine needs a bind
  option (for example `--listen-host`) or an SSH tunnel.
- No authentication. Add an optional API key before listening beyond
  localhost.
- `/v1/models` should list the MLX models too, not only the llama.cpp ones.
- Nice to have: a way for a client to find the lead (the Mac you talk
  to) without a hard-coded address.

Fixing these also helps other remote clients, such as a 3D-printed AI
object on the home network.

### Beating the turn-taking in the split

Today the halves take turns: for each token, Packer 1 runs its layers,
then the lead runs its layers and picks the token, and only then can
Packer 1 start the next one. Each Mini sits idle about half the time.
That's part of why a split chat writes 27–40% slower than one Mini
(the rest is the per-pass overhead in the parked table below). Ideas,
simplest first:

1. **Run several chats at once.** *Prototype Oct 31 night (`be19fe1`).*
   Day17 Qwen split baseline aggregate41.54→70.49tok/s (N1→N2); concurrent
   memory-guard RPC race fixed with owner-thread read jobs. See
   [raw comparison](DAY17-BENCHMARKS.md#completed-approved-split-matrix--nov-6-10011004-pm-ct).
   While the lead finishes chat A's token, Packer 1 already works on chat
   B's, and they swap. Both Minis stay busy, so total throughput across
   chats rises; a single chat is no faster. Flag
   `--split-pipeline-chats N` (default 1 = off). Lead worker multiplexes
   up to N sessions on the MLX thread; packer `fwd` takes a session key.
   Bench talks straight to the lead (`bench/v3/pipeline_bench.py`); proxy
   FIFO still serializes MLX when the proxy is in the path (not required
   for this measurement). With idea-5 cuts + keepalive: two chats ≈1.6×
   aggregate writing (wall); N=3 stall fixed Nov 1 (fair `(n_gen, t0)` + one prefill per
   loop; max TTFT ≤0.62 s; wall ≈ N=2). Details:
   [BENCHMARKS.md](BENCHMARKS.md#idea-1-several-chats-at-once-oct-31nov-1-mlx).
2. **Chunked reading.** Cut a long prompt into chunks and read them like
   an assembly line: Packer 1 reads chunk 2 while the lead reads chunk 1.
   Faster long-prompt reads (time to first token); writing is unchanged.
3. **Guess ahead (speculative decoding).** Day17 k3 block verification/cache
   fixes tested live on Qwen split: N1 aggregate41.54→52.11, but N2
   70.49→49.77tok/s. N2 helper stays experimental; serial block verification
   loses normal per-token overlap. All quality negatives and failures retained.
   *Shipped Nov 1 (auto-pair on
   lead; `--no-split-draft` restores baseline).* A small draft on the lead
   guesses the next few tokens; one Thunderbolt round trip verifies them.
   Pairing table `agent/guessers.json` + vocab match/remap, ask-once
   download, first-load quality/speed gate (cached; scores **final answer
   only** after stripping think/channel blocks — Gemma uses
   `<|channel>thought…<channel|>ANSWER`), mid-chat shut-off below
   break-even. Flags: `--split-draft-model`, `--no-split-draft`,
   `--split-draft-auto-download`, `--split-speculate-k`,
   `--split-prompt-lookup`, `--split-draft-skip-first-load`. Auto-pair
   medians of 2 (8194/5560, LPM off): Qwen **45.9 → 59.7** (k=3);
   Gemma **38.4 → 44.5** (g3-270m k=2; strict-gate re-verify **44.3**);
   Llama 3.1 8B **22.7 → 51.5** (Llama-3.2-1B k=3; accept ~0.75);
   Qwen2.5 14B **12.4 → 33.8** (0.5B k=3; accept ~0.73);
   Distill-Qwen 14B **12.3 → 16.9** (same 0.5B; accept ~0.45);
   GPT-OSS **34.3** auto-skipped (no o200k draft). Shut-off confirmed
   (Qwen `accepted_frac 0.438 < 0.80`; Llama hex with be=0.80
   `0.688 < 0.80`). Full Llama suite (keepalive / pipeline N=1–3 /
   first-load / download prompt): [BENCHMARKS.md](BENCHMARKS.md). Nov 1
   evening: live download-prompt tests on EXO1 (Qwen 335 MB + Llama
   663 MB; yes downloads → remembered). Top open-LLM families mapped in
   `agent/guessers.json` (Mini-verified vs HF vocab-checked vs skip).
   Details: [LOG.md](LOG.md), [METHODOLOGY.md](METHODOLOGY.md).
4. **Split each layer across both Minis (tensor parallel).** *Brenden's
   preferred direction to investigate.* Both Minis work on every layer at
   the same time instead of taking turns, each holding half of every
   layer's weights.
   - **Scaling.** Each layer needs two exchanges between the Minis (after
     attention and after the feed-forward part), and each exchange pays a
     fixed cable delay. For one chat the exchanges are tiny (one hidden
     state, a few KB), so that delay dominates and may cancel the gain over
     Thunderbolt 4. With several users, everyone's data is batched into the
     same exchanges: the fixed delay is paid once per layer for all of
     them, so it gets better the more users there are. It scales poorly to
     3 or more Minis, because every exchange involves every Mini. The
     usual answer is a hybrid: split each layer within close pairs of
     Minis, then chain the pairs lead to packer as today.
   - **First test, before building anything: a cable-timing
     microbenchmark.** Over our Thunderbolt link between the two Minis,
     using Caravan's own TCP link (the same socket setup as the split):
     - Measure the round-trip time for small messages at each model's
       per-layer exchange size, `hidden_size × batch × 2 bytes` (bf16),
       for batch sizes 1, 4 and 16, for all three models (read
       `hidden_size` and the layer count from each model's
       `config.json`; for example Qwen3 30B-A3B is 2,048 × 48 layers, so
       4 KB per exchange at batch 1). Report the median and the 99th
       percentile; optionally also time a round trip that includes a GPU
       sync on each side, since the real exchange waits for the GPU too.
     - Estimate the cable cost per token: `layers × 2 × round-trip time`.
     - Predict the time per token as roughly one Mini's half of the
       compute plus that cable cost. For the half, use v3's per-half
       numbers from "where the time goes" (16–20 ms per token, which
       already include the per-pass overhead). At batch B one step makes
       B tokens (one per user), so the total is about B ÷ (half + cable
       cost at that batch) tokens per second. Compare with v2.1 on one Mini (20 /
       24 / 27 ms per token for Qwen3 30B / Gemma 4 26B / GPT-OSS 20B)
       and v3's layer split (34 / 37 / 38 ms). The first guess was 50 µs
       per round trip (Qwen3: 96 × 50 µs ≈ 4.8 ms of cable, 17 + 4.8 ≈ 22
       ms). **Measured on Oct 31: about 100 µs** (below), so Qwen3 is
       96 × 101 µs ≈ 9.7 ms of cable, 16.6 + 9.7 ≈ 26 ms per token: still
       better than the v3 split (34 ms), worse than one Mini (20 ms).
     - **Go / no-go rule.** Go, and build a prototype, if for at least one
       model the prediction beats v3's layer split for a single chat
       **and** beats both v2.1 and v3 with idea 1 (several chats at once)
       in total tokens per second at batch 4 or 16. If it only wins at
       batch 16, go only for the multi-user and agent case. If the cable
       cost alone is more than half of v2.1's time per token at batch 1
       and the batched case doesn't win either, it's no-go over
       Thunderbolt 4: park it until faster links (Thunderbolt 5 or
       direct-memory links) are available.
   - **Result, Oct 31 2026 (`bench/cable/`, details in
     [BENCHMARKS.md](BENCHMARKS.md#cable-timing-oct-31-thunderbolt-4)).**
     A round trip through Caravan's link takes about 100 µs for one
     chat's hidden state (median; 95th percentile about 125 µs), 122–137
     µs at batch 4 and 190–213 µs at batch 16. At these sizes plain TCP is only 10–35 µs
     faster, so Caravan's framing isn't the problem; the cable and the
     network stack are. Predicted time per token (slower v3 half +
     cable), single chat: Qwen3 26.3 ms, Gemma 4 25.0 ms, GPT-OSS 25.5
     ms, so all three beat the v3 split (34 / 37 / 38 ms), and only
     GPT-OSS also beats one Mini (27.4 ms). Batched (assuming, as above,
     that a step costs the same at batch 4 or 16, which is a best case
     for every option), only GPT-OSS at batch 4 beats both one Mini (150
     vs 146 tok/s) and v3 with idea 1 (about 98); Qwen3 and Gemma 4 lose
     to one Mini at every batch. The cable alone at batch 1 (Qwen3 9.7
     ms) is just under half of one Mini's 19.6 ms, so the "park" clause
     isn't hit on the cable alone.
     **Verdict: not a go yet.** By the letter of the rule GPT-OSS passes,
     but by 3%, and only if waiting for the GPU before each exchange is
     free. It isn't: the `--gpu-sync` run added about 1 ms per round trip
     (a pessimistic test, the two waits ran one after the other), and a
     lone MLX sync on one Mini takes about 175 µs. GPT-OSS keeps its
     batch-4 lead only if the GPU wait adds less than about 15 µs per
     exchange (single chat: less than about 40 µs). **Park it** for
     Thunderbolt 4, and do ideas 1 and 3 first. The one cheap test that
     could reopen it: measure the GPU wait the way a real layer would
     have it (both Minis at once, arrays already on the GPU).
   - **GPU-wait test, Oct 31 2026 (`bench/cable/gpu_wait.py`).** Both
     Minis ran the exchange at the same time with GPU work sized like half
     of each layer. One exchange costs about 330–360 µs on top of the
     compute: about 250–280 µs is waiting for the GPU to finish each part
     (that alone is more than the cable), about 60–90 µs the cable. Batch
     4 is about the same per exchange (300–350 µs), and sending the first
     half-batch while the GPU finishes the second made it worse (440–650
     µs). Per exchange, splitting each layer would need less than 180 /
     306 / 371 µs (Qwen3 / Gemma 4 / GPT-OSS) to beat the v3 split, and
     less than 31 / 90 / 144 µs to beat one Mini. Estimated single-chat
     speed: Qwen3 16.6 + 96 × 0.359 ≈ 51.0 ms (19.6 tok/s, v3 29.5, one
     Mini 51.0), Gemma 4 18.8 + 60 × 0.343 ≈ 39.4 ms (25.4 tok/s, v3 26.9,
     one Mini 41.3), GPT-OSS 20.5 + 48 × 0.331 ≈ 36.4 ms (27.5 tok/s, v3
     26.1, one Mini 36.5).
     **Verdict: no-go.** Against v3 it loses on Qwen3 and Gemma 4 and is
     only about 5% ahead on GPT-OSS, which is within this test's error.
     Against one Mini it loses on all three by 25–60%. A faster cable
     alone wouldn't save it: with a free cable it would still lose to one
     Mini on all three, because the GPU wait is the bigger cost. Parked
     until there's a way to swap results without stopping the GPU each
     time (for example GPU-to-GPU links). Do ideas 1 and 3 instead.
   - **Rerun with Low Power Mode off, Oct 31 2026.** EXO2 had been in Low
     Power Mode for the test above. With it off on both Minis: one
     exchange costs 325–366 µs at batch 1 (about the same) and 403–414 µs
     at batch 4 (higher: the slow packer had been hiding part of the
     wait). With the new v3 halves: Qwen3 16.1 + 96 × 0.325 ≈ 47.3 ms
     (21.1 tok/s, v3 30.4, one Mini 51.0), Gemma 4 18.5 + 60 × 0.366 ≈
     40.5 ms (24.7, v3 27.7, one Mini 41.3), GPT-OSS 20.3 + 48 × 0.359 ≈
     37.5 ms (26.7, v3 26.6, one Mini 36.5). Budgets per exchange: under
     175 / 294 / 362 µs to beat v3, under 36 / 95 / 148 µs to beat one
     Mini. **Still no-go:** it only ties v3 on GPT-OSS and loses to one
     Mini on all three. See
     [BENCHMARKS.md](BENCHMARKS.md#rerun-with-low-power-mode-off-oct-31).
5. **Uneven layer split.** Move the cut so both halves take the same time
   (the lead also does the output layer and sampling, so it is usually
   the slower half). Already possible with `--split-packer-layers K`.
   **Tried Oct 31 evening** (`845216b`, LPM off, medians of 2; details in
   [BENCHMARKS.md](BENCHMARKS.md#uneven-layer-split-oct-31-mlx-idea-5)).
   Packer +1 / +2 layers vs even: Gemma 4 K=15/16/17 writing 27.6 / 27.4
   / 27.4 tok/s; GPT-OSS K=12/13/14 26.8 / 26.6 / 26.7; Qwen3 K=24/25/26
   30.0 / 30.2 / 30.5. **No single-chat writing gain** on Gemma 4 or
   GPT-OSS — the pipeline is serial (packer then lead), so a layer only
   shifts ms between halves and the sum stays flat (~35.5 / ~36.6 ms).
   Qwen3's bump is near noise. **Best balanced cuts** (for idea 1, where
   the slower half sets the pace): Gemma 4 **K=16** (17.8 vs 17.0 ms),
   GPT-OSS **K=13** (17.4 vs 18.5), Qwen3 **even K=24** (16.1 vs 15.6).
   Reading flat; quality 3/3. Keep those cuts when building idea 1.

6. **GPU keepalive while waiting on the peer.** *Shipped Oct 31 evening*
   (`0f14e72`). Each Mini's idle wait cools Metal; the next half costs
   ~5 ms extra. A short-lived side thread runs a tiny `mx.eval` during
   the blocking recv (`GpuKeepalive`), then stops before this process
   runs layers. Default on (`--split-keepalive`; disable with
   `--no-split-keepalive` or `CARAVAN_MLX_SPLIT_KEEPALIVE=0`). A/B vs
   off (LPM off, medians of 2): writing Gemma 4 38.3 vs 27.7, GPT-OSS
   34.1 vs 26.6, Qwen3 45.6 vs 30.4 tok/s; reading 512 / 4k slightly
   up; quality 3/3; peak mem unchanged. A long-lived pause thread
   regressed writing (~17.6 tok/s on Gemma) and was rejected. Details:
   [BENCHMARKS.md](BENCHMARKS.md#gpu-keepalive-while-waiting-on-the-peer-oct-31-mlx).
   Does not remove the serial half-then-half pipeline; ideas 1 and 3
   still apply on top.

**Recommendation:** for a single chat, try 3 (guess ahead) first. For
agents or several users sending requests at once, do 1 (several chats at
once), with the balanced cuts from idea 5 (Gemma K=16, GPT-OSS K=13,
Qwen3 even). Idea 5 alone does not speed up a single chat. Idea 6 (keepalive)
is already the default and raises single-chat writing ~28–50%.

### Auto-prune single-node models (keep disk lean for the split)

Not started. Caravan now runs shard-sized models only, so small one-Mini
models (e.g. Llama 3.1 8B, Qwen2.5 14B, removed by hand Nov 5) just eat disk.
Idea: classify each local model as one-Mini vs shard-worthy (size vs one
Mini's memory), then offer to remove (or, opt-in, auto-remove) the
redundant MLX/GGUF copies on both Minis. Never delete the currently loaded
model or the guess-ahead draft helpers; always keep the shard workhorses
(Qwen3 30B, Gemma 26B, GPT-OSS 20B, Qwen3.6 35B) and drafts. Also drop
catalog rows whose files are gone. Performance-first disk hygiene, not a
flashy UI.

### Model picker: Ollama / Hugging Face with fit check

**Phases 1–2 shipping** — full write-up in [MODEL_PICKER.md](MODEL_PICKER.md).
Left dock drawer (Models) like Topology: HF MLX catalog, GGUF via HF
publishers bartowski/unsloth/lmstudio-community (Brenden's "Ollama"),
Ollama Cloud framework (CLOUD label). Fit uses **unload capacity** (available
+ worker footprint), not current free RAM; disk checked separately; New chip +
max download size; parallel split-aware download; Stop/Delete kill fetches;
HF cache + drafts cleanup rows. **N-node picker (Nov 5 2026):** config-driven
`[web.nodes.*]`, dynamic fits-on-1..N, per-node download/disk; runtime still
capped at `MAX_SPLIT_STAGES=2`. Still open: phase 3 conversion
(`mlx_lm.convert`), phase 4 GGUF via llama-server on one Mini, phase 5 live
Ollama Cloud; **N-stage split runtime** (item below).

## Deferred / parked

Things we chose not to do now, so they don't get lost. Each has why it's
parked and when to pick it up again. Items that are already on the "Next"
list above point to it.

| Item | Why parked | Revisit when |
|---|---|---|
| Gemma 4 ~8% short-prompt checkpoint cost (Next #7) | Small, only on short prompts; v3 split work took priority. | After v3 lands; before Gemma 4 becomes the default MLX model. |
| Qwen3 ~0.15 s drop-previous-chat cost (Next #8) | One-off per big chat, hard to see in use. | With the proxy overhead pass. |
| MLX worker 6–9 s startup (Known limits) | Only paid on (re)start; the split adds the packer's ~2–4 s in parallel. | When the agent restarts workers on model switch (packaging). |
| 8-bit MLX chat memory (`--kv-bits 8`, off) | Slower and still didn't fit Qwen3 at 16k on one Mac; untested with the split. | If a split model runs short of memory at long chats. |
| Per-model profiles (Next #6) | Needs the v3 memory numbers first (they change what fits). | Right after v3. |
| Proxy overhead trims (Next #8) | 27–96 ms per request, already small next to model time. | With the next proxy release. |
| Memory headroom (Next #9) | The split halves per-Mac weights, which changes the problem. | Re-check with v3 numbers; then size caches from the real GPU limit. |
| Cold-disk restore measurement and preload (Next #10) | Needs a reliable way to drop files from the disk cache without touching user data. | After v3; before advertising restart resume times. |
| Suite 2: two-Mini runs of Qwen3 30B 8-bit and the Qwen3.6 35B GGUF | Qwen3 30B 8-bit moved into v3 (MLX split); the Qwen3.6 35B GGUF two-Mini run is still parked. | After v3, with Next #11 (re-measure the llama.cpp split). |
| Saved-chat cap deletes by default (Known limits) + a dry run on the second Mini's backlog (~165 GB) | Deleting a user's saved chats needs their sign-off; v3 runs with `CARAVAN_SLOT_CLEANUP=off`. | Before the next proxy restart on that Mini: run `--dry-run`, review, then decide `archive` vs `delete`. |
| Restore exo and Hermes on both Minis | Paused for the Caravan sprint so they don't compete for memory. | When the Caravan sprint is done. |
| Scrub personal paths (launchd plists, docs) | Cosmetic for the public repo; plists are hand-managed. | With packaging (Next #12). |
| C++ binary hardcodes the model (Known limits) | Experiment only; the Python agent is the supported path. | If the single-binary route is picked up again. |
| `mx.distributed` ring over Thunderbolt (fails on ≥2 MB messages) | Our own TCP pipeline works today. | With a newer mlx release; would allow mlx-lm/exo-style sharding. |
| jaccl / RDMA over Thunderbolt | Needs Thunderbolt 5 (M4 Pro/Max); our Minis are Thunderbolt 4. | If a Thunderbolt 5 Mac joins. |
| GPT-OSS 120B split across two Minis | Needs a third Mini or more memory. The two Minis have about 2 × 19 GB of GPU memory. The stock build is 63.4 GB. Checked 2026-10-31 for heavier-compressed builds: every GGUF quant is 62.6–66 GB, even Q2_K and IQ1_S, because the experts stay in MXFP4. The smallest MLX build is `jesusoctavioas/gpt-oss-120b-mlx-2Bit` at 36.6 GB, which would be about 18.3 GB of weights per Mini, under 1 GB short of what a stage needs with chat memory (our stages peak 1.5–2.2 GB above their weights). `manjunathshiva/gpt-oss-120b-tq3a-tq2e-g32` (37.7 GB) uses a TurboQuant mode that stock mlx can't load. Pruned "REAP" 58B variants are different models. So GPT-OSS's bigger brother in v3 is the 20B at 8-bit. | When a third Mini (or a bigger-memory Mac) joins, or a ≤ 32 GB 120B build appears. |
| Split link is unauthenticated | Thunderbolt-only cable between two trusted Macs. | Before the split runs over LAN/Tailscale. |
| No overlap of the two halves, and per-pass overhead (serial pipeline) | Simplicity first. Each half costs 16–24 ms per token without keepalive, about as much as the whole model on one Mac; the cable is <1 ms. Part of that was Metal cool-down after the idle wait (~5 ms/half); idea 6 (GPU keepalive, default on) removes it and raises writing ~28–50%. The rest is still serial turn-taking and graph-build overhead. Idea 5 confirmed moving layers does not raise single-chat writing. | After v3 merges. Do ideas 1 and 3 on top of keepalive; use idea 5's balanced cuts with idea 1. Also try compiling each stage's graph. |
| `--kv-bits` with the split | Untested. | With the 8-bit chat memory item. |
| More than two stages (one lead, several packers) | Two Macs today. | When a third Mac joins; needs re-planning of the cut and of split downloads. |
| Split download used for one model only | Qwen3 30B 8-bit ran from split downloads. For Gemma 4 8-bit and GPT-OSS 20B 8-bit, the lead downloaded its files plus the packer-only ones and copied them to the packer over Thunderbolt (one internet download instead of two). | When split download is wired into the agent (Next #3). |
| Qwen3.6 35B (hybrid attention) doesn't reuse the chat | Its linear-attention layers can't be rewound, and the template drops the reasoning from earlier replies, so every turn diverges and re-reads the whole chat (11 s at 4k, 53 s at 16k), also after a restart. Same on one Mac. | With per-model profiles: keep the reasoning in the history for hybrid models, or snapshot at the end of the user turn. |
| Split download: resume and clean-up of interrupted downloads | Prototype; stale `.incomplete` files from killed downloads stay on disk (nothing deleted). | When split download is wired into the agent. |
| v3 bench hits the worker directly | The proxy path was only smoke-tested (turn 1 cold, turn 2 reused, backend=mlx). | With the next proxy benchmark pass. |

## Known limits

- **Cleanup defaults to `delete`.** At proxy startup, saves older than 30
  days, and the least recently used saves over 200 files / 50 GB, are
  deleted. Run `python3 -m proxy.slot_cleanup --dry-run` first, or set
  `CARAVAN_SLOT_CLEANUP=archive`.
- **Qwen3 30B at 16k doesn't fit on MLX** on one 24 GB Mac (16.4 GB weights
  + ~3.2 GB cache), even with `--kv-bits 8`. Use the GGUF for long Qwen
  chats, or the v3 MLX split across both Macs.
- **The MLX worker takes 6–9 s to start** (vs 1.6 s for `mlx_lm.server`).
- **The v3 split is slower than one Mac.** Writing is 27–40% slower;
  reading is within about 6% (Oct 31 rerun, Low Power Mode off). Use it
  for what doesn't fit on one Mac.
- **Benchmarks need Low Power Mode off on both Macs** (`pmset -g`
  `lowpowermode 0`). Turning it off on the packer made the split read
  16–30% faster.
- **GGUF packers still get weights from the lead** on a first load or a
  cache miss, and get the small tensors every time (see Firm rules).
- **The v3 split is started by hand.** The agent and the launchd plists
  still start a one-Mac MLX worker.
- **MLX tool calls** are returned as text, not as a `tool_calls` field.
- **Same first message = same session**, on both backends.
- **The Thunderbolt address can change.** macOS self-assigns 169.254.x.x
  addresses. The hand-managed plist's `--rpc` fallback is a literal one;
  the agent and `render_llama_plist.py --rpc auto` discover it instead.
- **The launchd plists contain absolute paths** for one user's home
  directory. Edit them for your machine. The proxy plist's
  `CARAVAN_PINNED_SLOT` is a leftover the proxy no longer reads.
- **Lead selection is "whoever has the model"**: no election, and two Macs
  that both have it aren't handled. The agent doesn't run the proxy yet.
- **The C++ binary** hardcodes the model and lacks `--cache`, the health
  server, identity and crash supervision.
- **Only tested on two Apple Silicon Macs.** RDMA over Thunderbolt needs
  Thunderbolt 5, so the split runs over plain TCP.
- **RPC is unauthenticated.** Keep it on a private link.
- **Not released.** There are no packages, and there's no support beyond
  this repo.


### Day17 approved split follow-up (after9:42PM CT)
Brenden approved the live split reload. Existing full Qwen copies on both Minis
and an installed Qwen3-0.6B helper avoided any download. Initial N1 helper is
faster; initial N2 both with/without helper stalled. Worker-owned stack evidence
identified concurrent HTTP memory-guard and scheduler RPC reads on the same
socket. Read-only stats now queue between drained rounds on the socket owner;
mutating admin calls still wait for idle. Fixed-source matrix completed36/36
uncapped replies: baselineN1/N2 aggregate41.54/70.49, helper52.11/49.77tok/s.
N2 helper is slower and stays experimental. All count/sorting semantic checks
pass; strict exact-format fails every mode (trailing spaces). Final singleEXO1
Qwen ready, Auto queuedKV4 trial applied. All failures retained in [DAY17-BENCHMARKS.md](DAY17-BENCHMARKS.md).

Final10:08:53PM CT worker-preserving UI refresh verified; QwenPID89648 remains
ready singleEXO1, allAuto/queuedKV4 trial.
[Final API proof](../bench/results/day17/split-final-ui-proof.json).
