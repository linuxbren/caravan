## 2026-11-01: Day 9 ROADMAP #13(a) auto-pick (split + pipeline)

- Helpers `choose_packer_layers` / `choose_pipeline_chats` in `mlx_split.py`;
  worker omits default for `--split-pipeline-chats` (None → auto); packer
  hello carries `mem_total_gb` / `mem_available_gb`. Startup logs
  `auto split:` / `auto pipeline:`. Explicit flags still win.
- Mini verify (8194/5560, LPM off, warm-up, medians of 2, q 3/3): Qwen3 /
  Llama 3.1 8B / Qwen2.5 14B × auto|tuned. Auto picked K24/N2, K16/N2,
  K24/N2 (same as hand-tuned). Speeds matched or beat tuned (Qwen2.5 pipe
  wall auto 20.9 > tuned 18.9). No failures. Raw
  `~/.caravan/bench-2026-11-01/day9-autotune/`.
- Unit tests: 133 pass. Docs: ROADMAP #13(a) shipped; METHODOLOGY auto
  section; BENCHMARKS table; experiments entry.

## 2026-11-01: Llama 3.1 8B Mini suite (keepalive / pipeline / guess-ahead)

- Target `mlx-community/Meta-Llama-3.1-8B-Instruct-4bit` (~4.2 GB) on both
  Minis; draft `Llama-3.2-1B-Instruct-4bit` (~680 MB / size_mb 663) on lead.
  Even cut K=16. Test ports 8194/5560. LPM off. Medians of 2. Raw:
  `~/.caravan/bench-2026-11-01/llama-suite/`.
- Keepalive: off write **21.2**, read 243.0 / 227.7; on **22.8**, 243.9 /
  229.5; quality 3/3.
- Pipeline: wall_agg N1 **22.5** / N2 **39.3** / N3 **39.0**; max TTFT ≤0.60 s.
- Guess-ahead suite nodraft medians count/repeat/edit/cont **22.7 / 22.0 /
  20.7 / 22.2**; auto-pair **51.5 / 51.6 / 64.7 / 46.8**, accept ~0.75,
  quality 3/3.
- First-load gate keep=1: baseline **19.29** / spec **35.87**, accept 0.75,
  break_even ≈0.45, quality 3/3.
- Shut-off: restart without `--split-draft-skip-first-load` after raising
  cached be to 0.80 → hex chat disabled (`0.688 < 0.80`).
- Download prompt: `A 663 MB helper…` yes → download; draft restored from
  `.bak`. `speculate_bench.py` denom>0 guard for short quality replies.
- Decision: **keep** `llama3` as `mini_verified` in `agent/guessers.json`.

## 2026-11-01: download-prompt live test + top-family guesser map

- EXO1 test ports only (8194/5560; production untouched). Moved Qwen3-0.6B HF
  cache + drafts aside (`.bak`), backed up `guess-ahead-state.json`, then:
  - Size prompt appeared: `A 335 MB helper can make … Download Qwen3-0.6B-4bit?`
  - Yes → download, draft k=3 exact, first-load keep (baseline **36.98** /
    spec **40.71** tok/s from the gate), quality keep.
  - Reload remembered yes (auto-pair, no prompt, first-load cache hit keep=1).
  - Cleared answers and answered no → baseline; reload remembered no (no prompt).
  - Removed only the test download; restored `.bak` caches + state (2318 B,
    first_load Qwen+Gemma, empty `download_answers`). Raw:
    `~/.caravan/bench-2026-11-01/guess-ahead-download-test/`.
- Expanded `agent/guessers.json` for top open LLM families (Mini-verified vs
  HF vocab-checked vs explicit skip). `find_pairing` now prefers pairings
  over skips (Distill-Qwen vs native DeepSeek-R1). Unit tests: **22**.
  Docs: ROADMAP, METHODOLOGY family table, handoff next steps.

## 2026-11-01: first-load quality scores final answer only (Gemma channel closer)

- `guess_ahead.final_answer_text` / `answer_ok` strip think/channel blocks and
  match the final answer only (whole-word, last line/sentence). Gemma-4 form
  `<|channel>thought…<channel|>ANSWER<turn|>` (open `<|channel>`, close
  `<channel|>`) was matching "4"/"Paris"/"Cold" inside the thought; now
  those fail unless the closer segment holds the answer. Gate probe
  `max_tokens` 96→256; quality `out` store 80→400 chars. Tests: 20 in
  `agent/test_guess_ahead.py` (prior 14 + AnswerOkCases).
- Mini re-verify (8194/5560, LPM off, keepalive on, medians of 2, raw under
  `~/.caravan/bench-2026-11-01/guess-ahead-strict/`):
  first-load Gemma keep=1 quality **3/3** (baseline 31.63 / spec 34.79);
  autopair write **44.3**; nodraft **38.4**. Prior auto-pair table unchanged
  (Qwen 45.9→59.7, Gemma 38.4→44.5, GPT-OSS skip 34.3; shut-off 0.438<0.80).

## 2026-11-01: idea 3 guess-ahead auto-pair (ask / gate / shut-off)

- Shipped behind existing speculate path: `agent/guessers.json` pairings
  (Qwen3-30B-A3B → 0.6B-4bit k=3; Gemma-4-26B → g3-270m k=2 + specials remap;
  GPT-OSS no pairing). Vocab match at load; ask-once download with remembered
  answers; first-load quality+speed gate cached in
  `~/.caravan/mlx/guess-ahead-state.json`; mid-chat shut-off when accepted
  frac < break-even. `--no-split-draft` / `--split-draft-model` /
  `--split-draft-auto-download`. Tests: `agent/test_guess_ahead.py`.
  Methodology: `docs/METHODOLOGY.md`. Commit local, no push.
- Mini verify (8194/5560, LPM off, keepalive on, medians of 2, no new
  downloads; drafts already on EXO1):

  | model | mode | write tok/s | quality |
  |---|---|---:|---|
  | Qwen3-30B-A3B-4bit | auto-pair k=3 | **59.7** | 3/3 |
  | Qwen3-30B-A3B-4bit | `--no-split-draft` | 45.9 | 3/3 |
  | Gemma-4-26B-4bit | auto-pair k=2 (remap 6187) | **44.5** | 3/3 |
  | Gemma-4-26B-4bit | `--no-split-draft` | 38.4 | 3/3 |
  | GPT-OSS-20B MXFP4 | auto-skip (no pairing) | 34.3 | 3/3 |

  Shut-off: with break-even raised to 0.80, low-hit hex prompt disabled
  guessing after 48 tokens (`accepted_frac 0.438 < 0.800`). Download
  decline/auto paths covered by unit tests + dry-run. Raw JSON:
  `~/.caravan/bench-2026-11-01/guess-ahead/` on EXO1.

## 2026-11-01: idea 3 follow-up (Gemma 270m, prompt-lookup, GPT-OSS)

- Full-prompt draft prefill fix; `--split-prompt-lookup`; rotating-KV trim room
  guard for GPT-OSS; draft/verify timing in usage.caravan.speculate.
- Gemma: E2B still loses (draft_s dominates); **gemma-3-270m-it-4bit k=2 → 44.4**
  vs 38.4; PL helps repeat only. GPT-OSS: no small draft; PL ≤ baseline.
  Qwen draft k=3 → **59.3** (suite also strong). Commit local, no push.

## 2026-11-01: idea 3 guess-ahead (speculative decoding) prototype

- Off-by-default `--split-draft-model` / `--split-speculate-k` on the lead;
  packer `trim` op + `SplitModel.trim_caches`. Custom loop (mlx_lm-style)
  because stock speculative assumes a single-process cache.
- Drafts on EXO1 only: Qwen3-0.6B-4bit (335 MB), gemma-4-E2B-it-4bit (3.3 GB).
- Bench vs keepalive 4-bit baseline (LPM off, test ports, medians of 2):
  Qwen **45.9 → 57.4 tok/s at k=3** (~+25%), quality 3/3; Gemma slower at
  every k with E2B draft; GPT-OSS no small same-family draft.
- Commit local only (no push). Workers stopped after.

# Log

*Naming note: entries written before 2026-10-31's rename say "head" for
the Mac you talk to and "tail" (llama.cpp) or "front" (MLX) for the
other one, and they're left as written. Today's names: the **lead** is
the Mac you talk to, the **packers** are the others (Packer 1 runs the
first layers), and the whole group is the **string**.*

## 2026-09-05

- Confirmed Ollama has no native multi-machine sharding, but llama.cpp
  (the engine underneath it) has an RPC backend (`GGML_RPC`) that does
  cross-machine layer splitting. Decided to try it as "step 1" before
  considering anything bigger.
- Set up SSH key-based access from `node-a` to `node-b` (its LAN IP) to
  make working across both machines practical.
- Checked Homebrew's `llama.cpp` formula: it does **not** set `GGML_RPC` or
  `GGML_METAL` explicitly, relying on upstream defaults. Confirmed upstream
  defaults are `GGML_METAL_DEFAULT=ON` on Apple platforms (good) but
  `GGML_RPC` defaults to `OFF` — so the Homebrew bottle would **not** have
  RPC support. Building from source instead.
- Installed `cmake` via Homebrew on both machines (neither had it).
- Cloned `llama.cpp` (shallow, `--depth 1`) into `~/dev/llama.cpp` on both
  machines.
- Configured the build with `-DGGML_RPC=ON -DGGML_METAL=ON
  -DCMAKE_BUILD_TYPE=Release` on both. Notable output on both machines:
  ```
  -- Metal framework found
  -- Including METAL backend
  -- Using RPC backend
  --   RDMA transport enabled (Apple RDMA-over-Thunderbolt, UC)
  -- Including RPC backend
  ```
  The RDMA-over-Thunderbolt line is a good sign — if these two Macs are
  ever connected via Thunderbolt, the RPC backend can use that instead of
  Wi-Fi/Ethernet for node-to-node traffic, which should help throughput a
  lot given how much a plain network hop hurt exo's MLX pipeline earlier
  this session.
- Build started on both machines (background). Next: once built, start
  `rpc-server` on node-b, point `llama-server`/`llama-cli` at it from
  node-a with `--rpc`, load a real GGUF model split across both, and
  benchmark actual tok/s against what we saw with exo/MLX.
- Created the public GitHub repo:
  `llama-shard` (since renamed to Caravan, now at
  [github.com/linuxbren/caravan](https://github.com/linuxbren/caravan)).
  `gh` was already installed and authenticated, so no extra setup needed.
- First build attempt on node-b failed instantly (`nohup: cmake: No such
  file or directory`) — the background SSH command didn't have Homebrew's
  `/opt/homebrew/bin` on `PATH` before invoking `cmake`. Non-interactive
  SSH sessions on macOS don't source the same shell profile as an
  interactive one, so anything installed via Homebrew needs its `PATH`
  exported explicitly in one-off SSH commands. Fixed by exporting
  `PATH="/opt/homebrew/bin:$PATH"` before the build command; restarted.
- Both builds finished successfully. `ggml-rpc-server`, `llama-cli`, and
  `llama-server` all present in `build/bin/` on both machines.
- Started `ggml-rpc-server` on node-b. First attempt used the default bind
  host (`127.0.0.1`) and was unreachable from node-a (`connection refused`)
  — the RPC server only listens on localhost unless told otherwise.
  Restarted with `-H 0.0.0.0 -p 50052`, which printed this warning on
  startup (important, keep this in mind for anyone else using this repo):
  ```
  WARNING: Host ('0.0.0.0') is != '127.0.0.1'
           Never expose the RPC server to an open network!
           This is an experimental feature and is not secure!
  ```
  This is fine on a private LAN but should **not** be exposed beyond that
  — the RPC protocol has no auth/encryption. Confirmed reachable from
  node-a after the restart. Metal initialized correctly on node-b's GPU
  (`Apple M4`, ~19GB usable GPU working set).
- Next: pick a GGUF model to actually test with, point `llama-server` on
  `node-a` at `node-b`'s RPC endpoint (`--rpc <node-b-ip>:50052`), confirm
  it splits layers across both machines, and benchmark real tok/s.
- Pulled `muse-glimmer` via `ollama pull muse-glimmer` (18GB total: a
  16GB main weights blob + 1.4GB vision/adapter blob). Deliberately chose
  this model since it's the one that started this whole detour — exo
  couldn't load it (unsupported architecture), so getting it running here
  would be a satisfying full-circle test. Located the raw GGUF blob
  directly in Ollama's own content-addressed blob store
  (`~/.ollama/models/blobs/sha256-...`) — no need to re-download from
  elsewhere, and no need to translate the format; Ollama blobs are
  themselves valid GGUF files (confirmed via magic bytes).
- **First load attempt did not actually shard.** Started `llama-server`
  with just `--rpc <node-b-ip>:50052` and no explicit device/split flags.
  It loaded fine and generated correctly (6.2 tok/s), but `node-b` showed
  ~0% CPU throughout — the whole model loaded onto `node-a` alone. Since
  this 16GB model comfortably fits in `node-a`'s own ~19GB Metal budget,
  llama.cpp's automatic placement logic didn't bother using the remote
  RPC device at all.
- Ran `--list-devices` to see how devices enumerate with `--rpc` set:
  ```
  MTL0: Apple M4 (18186 MiB, 18185 MiB free)
  BLAS: Accelerate (0 MiB, 0 MiB free)
  RPC0: <node-b-lan-ip>:50052 (18186 MiB, 18185 MiB free)
  RPC1: <node-b-lan-ip>:50052 (0 MiB, 0 MiB free)
  ```
  Note the phantom `RPC1` entry reporting 0 MiB for the same endpoint —
  this is likely what caused the original run's
  `device RPC1 did not report memory; --fit will not use it` warning and
  probably confused automatic placement.
- **Fix: force it explicitly.** Restarted with
  `--device MTL0,RPC0 --tensor-split 1,1` to name the two real devices
  directly and split evenly, sidestepping the phantom device entirely.
  This time `node-b`'s `rpc-server` process memory climbed steadily
  during load (0 → ~2GB → ~4.5GB → ~6.7GB → ~8.27GB over about 7 minutes
  total) — real tensor data streaming to it over the LAN, no local copy
  of the model file needed on `node-b` at all (unlike exo's MLX approach,
  which required each node to hold its own full copy on disk).
- **First genuinely distributed generation.** With both machines
  confirmed active (CPU ticked up on both during generation, not just
  `node-a`), a test prompt returned successfully:
  - **4.23 tok/s** generation, **15.5 tok/s** prompt processing
  - For comparison: exo's own 2-node MLX split earlier this session
    measured ~4-4.5 tok/s on a similarly-sized model. Roughly the same
    ballpark — this isn't a magic speed win over exo, but it **is** proof
    the mechanism works end-to-end on real hardware with a real model,
    which was the actual goal of step 1.

**Step 1 verdict: proven.** The core trick works, is stable enough to
finish a real request, and performs comparably to exo's own approach.
Worth deciding next whether/how to move to step 2 (the stage plan,
now summarized in [ROADMAP.md](ROADMAP.md), "Done").

## Wiring it into a real assistant (openclaw)

Went straight to a real-world test: pointed `openclaw` (an existing
agent framework already running on `node-a`) at this `llama-server`
instance via its OpenAI-compatible endpoint, replacing a broken exo
config (a different model it was pointed at turned out to use an
architecture exo doesn't support — unrelated to this project, but it's
what created the opening to try this).

- Config: added a new model provider with `"api": "openai-completions"`
  (not `"openai"` — that name isn't accepted) pointed at
  `http://127.0.0.1:8080/v1`, no real API key needed since it's local.
- **Confirmed tool-calling works** through llama-server's OpenAI-compatible
  endpoint for this model — sent a request with a `tools` array, got back
  a correctly-formatted `tool_calls` response. This mattered because the
  model's Ollama-specific `RENDERER glimmer`/`PARSER glimmer` template
  hints aren't something llama.cpp understands, so this wasn't guaranteed
  to work — it does, likely because llama.cpp handles tool-calling via
  the model's own embedded GGUF chat template rather than Ollama's
  separate renderer/parser convention.
- **Real system prompts are much bigger than expected.** openclaw's full
  agent system prompt (with its default tool/skill set loaded) came in
  around 24-30K tokens — nowhere near the small prompts used for the
  earlier benchmarks in this log. First attempt at `-c 8192` failed
  outright (`request (30525 tokens) exceeds the available context size`).
  Bumped to `-c 65536` — this model's KV cache is lean (only 2 KV heads),
  so the memory cost of a much bigger context is modest.
- **Found and cleared a genuinely stale, unrelated problem**: an old
  long-running session on the openclaw side had accumulated ~66K tokens
  of stale history over many hours (heartbeats, earlier unrelated tests)
  and was stuck in an `aborted` state. Every new message inherited that
  entire backlog before even starting, which is why token counts kept
  climbing between attempts (30K → 80K) independent of anything in this
  project. Cleared with `openclaw sessions compact <key> --max-lines 10`
  (hard truncation, no LLM summarization needed — deleting the session
  outright wasn't allowed since it's a protected "main" session).
- **First real message timed out, then succeeded on retry.** With a
  clean ~24.5K-token prompt, prompt processing alone took ~280s at
  ~80 tok/s, longer than openclaw's default 300s provider timeout —
  got killed at 79% through, before generating anything. openclaw
  auto-retried, and because llama-server keeps a prefix cache, the
  retry reused 85.8% of the already-processed prompt (only ~4K new
  tokens to process) and completed in ~133s. Total end-to-end for this
  first message: roughly 7-8 minutes.

**Practical takeaway**: it works, but the "cold start" cost of a large
tool-equipped system prompt is real on this hardware — the first message
of a new/idle session will likely time out once and need the automatic
retry to actually get an answer, adding several minutes. Ongoing
messages in an already-warm session should be much faster since they
only reprocess the incremental new tokens, not the whole system prompt
— but that assumes the prefix cache slot doesn't get evicted by other
concurrent sessions/cron jobs competing for the same small pool of
cache slots. Worth deciding whether that tradeoff is acceptable, or
whether the fix is a smaller/faster model, a trimmed-down tool set, or
both.

**Tested the "trim the tool set" option — it didn't help much.** Cut
openclaw's loaded skills from 5 down to 1 (kept only email monitoring,
dropped apple-notes/apple-reminders/1password/browser-automation since
they weren't used day-to-day). Measured the resulting system prompt on a
clean scratch session afterward: still **~28,240 tokens**, essentially
unchanged from the ~24,576-30,722 baseline before the trim. Conclusion:
the loaded skills list was not the dominant contributor to prompt size —
the base `"coding"` tools profile itself (tool definitions, workspace
`AGENTS.md`, etc.) is the bigger factor, and wasn't touched by this
change. Next person picking this up should measure that directly (e.g.
via `openclaw proxy` to inspect the actual assembled request) before
assuming further skill trimming will help — it likely won't get you far
on its own.

## Diagnosing repeat slowness: it's slot assignment, not missing caching

Continued the investigation into why *ongoing* messages (not just the
first one) were still occasionally slow. llama-server's `/slots`
endpoint plus its own stdout log (`llama-server3.log`) gave a direct,
measured answer.

- llama-server's automatic prompt caching (`--cache-prompt`, on by
  default) genuinely works well *when a request lands back on the same
  slot it used last time*: observed 70-100% prefix reuse across several
  consecutive same-slot requests in the live log (e.g. one request reused
  ~25K of its ~30.7K tokens from the prior request on that slot; another
  reused nearly its entire prompt and finished in ~15s).
- The problem: there are only 4 slots (`-np` was left at its `-1`/auto
  default), and openclaw only has **one** real conversation identity
  today (the "main" agent — heartbeats run inside that same session, per
  `agents.defaults.heartbeat` in openclaw.json, not a separate one).
  Despite that, requests were landing on three different slots over time
  (slot 2, then slot 1, then slot 0) as the prompt's size and shape
  shifted from openclaw's own context trimming between turns. Each time
  the automatic prompt-similarity slot picker (`--slot-prompt-similarity`,
  default threshold 0.10) missed the slot actually holding the relevant
  cached prefix, that request paid a mostly- or fully-cold reprocess —
  directly reproduced live: task 1395 was killed mid-prefill at 20,475
  tokens by openclaw's own timeout, and the retry (task 1408) landed back
  on the same slot and reused that leftover state (72% reuse, 153.6s for
  the remaining ~7.7K tokens) — the exact "times out once, retry succeeds
  via cache" pattern described in the wiring section above, still
  happening live months (well, hours) later.
- **Fix: `proxy/slot_pin_proxy.py`**, a small dependency-free Python
  reverse proxy that sits between openclaw and llama-server. It forwards
  every request unchanged except for injecting a fixed `"id_slot"` into
  the JSON body (confirmed via llama-server's own source,
  `server-context.cpp`, that the OAI-compatible chat-completions path
  reads `id_slot` from the raw request body exactly like the native
  `/completion` endpoint does — same code path, just not documented on
  the OpenAI-compat side). Streams responses back chunk-by-chunk so SSE
  (`stream: true`) still works. Since there's only one real identity
  today, v1 pins everything to one fixed slot rather than trying to route
  by identity — see the module docstring for how to extend it if a second
  identity shows up later.
- Verified end-to-end: started the proxy on `127.0.0.1:8090`, confirmed a
  direct completion request landed on the pinned slot via `/slots`
  (task/prompt counters updated on exactly that slot, others untouched),
  then pointed openclaw's `models.providers.llama-shard.baseUrl` at
  `http://127.0.0.1:8090/v1` (was `:8080` directly) and restarted the
  `ai.openclaw.gateway` LaunchAgent to pick it up. Ran a real end-to-end
  test via `openclaw agent -m "..." --json` (no `--deliver`, so it
  doesn't hit a real channel) to confirm a full real agent turn works
  through the new path.
- **Bonus finding from `openclaw doctor` while checking the restart**:
  the workspace `AGENTS.md` file alone is 26,749 raw chars / 19,182
  injected chars (28% truncated at the default per-file limit), and total
  bootstrap injection is 24,194 of a 60,000-char budget (40%). This is
  concrete, measured evidence for the still-open question from the
  section above about what's actually filling the ~28K-token system
  prompt — worth picking up directly next time that's being investigated,
  rather than re-deriving it.
- Not yet done: the proxy isn't supervised (same "plain background
  process" caveat as `llama-server`/`rpc-server` — see README/PLAN); it
  and the pinned slot number are the natural next candidate for the
  launchd-service work already on the roadmap.

## launchd (issue #1): 2 of 3 services done, llama-server blocked

Added `launchd/` with plists for all three processes
(`com.llama-shard.llama-server`, `com.llama-shard.slot-pin-proxy` on
node-a, `com.llama-shard.rpc-server` on node-b) plus a small robustness
fix to the proxy (return 502 instead of a raw traceback when llama-server
isn't reachable yet, since under launchd it may start before llama-server
is ready).

- **`slot-pin-proxy` and `rpc-server`: working cleanly under launchd.**
  Installed as user LaunchAgents (`gui/<uid>` domain), `RunAtLoad` +
  `KeepAlive`, logs under `~/Library/Logs/llama-shard/`.
- **`llama-server`: blocked, reverted to a plain manual process for now.**
  Every launchd-launched attempt aborts near-instantly with
  `ggml-rpc.cpp:547: Failed to connect to <node-b-lan-ip>:50052`, even
  though node-b's `rpc-server` is confirmed up and reachable (`nc -z`
  succeeds from node-a both before and during the failure). Isolated the
  cause with two tests before giving up on it:
  - Killed and replaced node-b's `rpc-server` with a completely fresh
    instance (in case the long-running original was wedged from the
    earlier abrupt `kill` of its old client) -- same failure, ruling that
    out.
  - Ran the *exact* same binary, same args, even with a stripped `env -i`
    environment (to rule out a missing env var launchd doesn't set) --
    directly in an interactive shell, and it worked fine, loading the
    model normally. So it's specifically "spawned by launchd" that
    fails, not the command itself or the environment.
  - Checked `~/Library/Application Support/com.apple.TCC/TCC.db` for a
    Local Network denial (the usual suspect for "works interactively,
    silently fails headless" on modern macOS) -- no record at all, for
    either outcome. Doesn't rule out a TCC-adjacent cause, but there's no
    direct evidence for the classic explanation either.
  - No third-party firewall found (no Little Snitch/LuLu processes or
    apps). Didn't get further into `pfctl`/Screen Time content-filtering
    since that needs `sudo`/GUI access this session doesn't have.
  - Best remaining guess: some per-process network policy that treats
    launchd-spawned processes differently from a shell's children (e.g.
    Screen Time Content & Privacy network restrictions, or an MDM
    profile) -- keyed by "responsible process" the way several macOS
    privacy/filtering features are. Untested alternative worth trying
    next: a **LaunchDaemon** (`/Library/LaunchDaemons`, `system` domain,
    root, needs `sudo`) instead of a LaunchAgent -- daemon-domain
    processes sit outside the per-user session policies that would
    explain this.
  - Net effect: llama-server is back to being a manual `nohup` process,
    same as before this issue was opened -- no regression, but the
    "survives a reboot" goal isn't met for this one process yet. See
    issue #1 for follow-up.

## 2026-09-06

### Why model load takes 5-7 minutes when exo takes seconds

Prompted by comparing today's repeated launchd-testing restarts (each
paying a fresh multi-minute load) against exo's near-instant startup on
the same hardware. Two compounding, independently-verified causes:

- **Wrong network path.** `route get <node-b-ip>` resolves over `en1`,
  confirmed via `networksetup -listallhardwareports` to be **Wi-Fi**, not
  wired Ethernet (`en0` is `status: inactive` -- no cable connected) or
  the Thunderbolt-RDMA path the build actually compiled in support for
  (`en2`/`en3`/`en4` show no link at all -- no Thunderbolt cable between
  the two Macs). WiFi link is 802.11ax at a 1020 Mbps PHY rate, so maybe
  400-500 Mbps of real TCP throughput -- nowhere near what a wired or
  Thunderbolt link would give.
- **Every restart re-transfers the full shard from scratch.** This is
  the more fundamental one. `rpc-server` on node-b is stateless: it holds
  tensors only in that process's RAM for as long as it's alive, nothing
  persisted to its own disk. So node-a's `llama-server` streams node-b's
  ~8GB half of the 16GB model (`--tensor-split 1,1`) across Wi-Fi *every
  single time it starts* -- not a one-time cost. Doing the math (8GB over
  even a generous ~450 Mbps effective WiFi throughput should be ~2.5
  min) against the observed 5-7 min points to real protocol overhead on
  top of the network bottleneck too -- consistent with PLAN.md's own
  risk note that the RPC backend is "less mature/optimized."
- exo doesn't have this problem not because its network path is faster,
  but because it doesn't do this transfer on every launch at all: each
  exo node already holds its assigned shard on local disk, so "starting"
  a run is just a local file load.

### Design: shard-scoped local cache on node-b, not a full copy like exo

The instinct is "just do what exo does" -- give node-b a persistent local
copy so restarts don't re-pay the network cost. But exo's specific
approach has a real, already-observed inefficiency worth avoiding rather
than copying: per this project's own earlier note (see "Wiring it into a
real assistant" section above), exo "required each node to hold its own
**full** copy on disk," even though each node only ever computes on its
own assigned slice at runtime. On this 2-node, 16GB-model setup that's
32GB stored to run something that only needs 16GB total -- and it scales
linearly worse with more nodes (an N-node cluster needs N full copies of
every model, each node using only ~1/N of its own copy).

Proposed design instead: node-a stays the single source of truth (as
now, zero footprint needed on node-b for correctness); node-b caches
**only the tensor range it's actually assigned** under the current
`--tensor-split`, keyed by a hash of (source file content, split
boundary, device assignment). This gets exo's fast-restart property
without exo's N-way disk duplication, and the single-source-of-truth
design gives two things exo's static per-node-copy model doesn't obviously have:

- **No version-skew risk** -- a hash-keyed cache self-invalidates if
  node-a's model file changes, so node-b can never silently serve a
  stale/mismatched shard the way per-node full copies could drift if one
  node's copy isn't resynced after a model update.
- **Cheap re-splitting** -- changing `--tensor-split` (e.g. node-b gets
  faster hardware and should take more layers) just changes the cache
  key and triggers a fetch of the new range, vs. exo's model likely
  needing the affected files redistributed to match a new boundary.

Not evaluated: how exo actually handles elastic node add/remove or
failure recovery internally -- no basis to claim an edge there without
reading its source or testing it, so left as an open question rather
than an assumed advantage.

**Scope/priority note, to keep from over-building this:** the payoff is
specifically boot-time/crash-recovery latency (relevant to issue #1's
"survives a reboot" goal), not per-request latency -- that's already
solved by the slot-pinning proxy (see 2026-09-05 entries above). Once
llama-server is genuinely stable under supervision, it may restart rarely
in practice, which lowers this feature's real-world value versus how it
felt during today's flurry of test restarts. Worth sizing the
implementation effort against actual restart frequency once issue #1
is fully resolved, not building it reflexively.

Implementation is a real lift, not a config tweak: `rpc-server` is a thin
wrapper around upstream `ggml-rpc`'s protocol, which has no concept of
persisting or short-circuiting a tensor transfer today -- this likely
means patching `ggml-rpc.cpp` itself (add a local on-disk tensor cache
keyed as above, checked before accepting a buffer from the client) rather
than something buildable purely around the existing binaries the way the
slot-pin-proxy was. Filed as
[issue #3](https://github.com/linuxbren/caravan/issues/3) for
whenever this is worth picking up.

### Renamed: llama-shard → Caravan

Wanted distance from "Ollama" in the name (the project only ever reads
Ollama's local blob cache as a convenience -- MIT-licensed, no code
reuse, so no licensing issue, but naming the project after it invites
confusion/trademark association it doesn't need). Considered several
directions (pack-animal metaphor, weaving/structure metaphor, direct
`ggml`-style technical names, a "distributed llama" pun) and picked
**Caravan**: llamas' original job was hauling loads across distance in a
group, which maps cleanly onto distributing an inference workload across
machines, without being a strained pun. Checked availability first:
`caravan` is free on GitHub (per-account namespace, so this was never in
doubt) but already used on PyPI/npm by small, inactive, unrelated
packages (an AWS SWF framework) -- low real-world confusion risk, but
worth knowing before ever publishing a package under this name.

Renamed the GitHub repo (`gh repo rename`, keeps issues/stars/history,
old URLs redirect) and updated the local git remote + doc text/links in
this commit.

### Full rebrand + accidental fix for issue #1

Followed up by renaming everything else that still said `llama-shard`:
the local directory (`~/dev/llama-shard` → `~/dev/caravan`), all three
launchd labels/plist filenames (`com.llama-shard.*` → `com.caravan.*`),
the proxy's env vars (`LLAMA_SHARD_*` → `CARAVAN_*`), the log directory
(`~/Library/Logs/caravan/`, old `llama-shard` logs left in place rather
than moved), and openclaw's config (`models.providers.llama-shard` →
`caravan`, `agents.defaults.model.primary`, and the matching
`auth.profiles` entry).

While doing this, found `llama-server` had actually been down for ~7
hours (crashed earlier at 19:48 on an unrelated RPC error, and being an
unsupervised manual process, never came back). Restarting it surfaced a
new, deterministic failure that turned out to be much more interesting
than the crash itself: `llama-server` could not connect to node-b's RPC
port (`<node-b-lan-ip>:50052`) *at all* when launched from this Claude Code
CLI session's process tree -- `ggml-rpc.cpp`'s raw `connect()` call
returned `EHOSTUNREACH` 15/15 times in a row, even though `ping` and `nc
-z` to the exact same host/port succeeded every time from the same
shell. Tracked it down to **Tailscale**: this Mac and node-b are both on
the same tailnet, and for whatever reason (not fully root-caused --
Tailscale's `RouteAll`/exit-node/netfilter prefs all looked inert, no
subnet routes are advertised) some process contexts get their LAN-IP
connections intercepted/dropped while others don't. The fix: address
node-b by its **Tailscale IP** (`<node-b-tailscale-ip>`) instead of its LAN IP
(`<node-b-lan-ip>`) for the `--rpc` flag. Verified with a raw Python socket
loop -- 0/15 success on the LAN IP, 3/3 success on the Tailscale IP, from
the identical process.

This is very likely the real root cause of **issue #1**'s launchd
connect-failure too -- a launchd-spawned process is exactly the kind of
different process context this seems to affect, matching the "works
interactively, fails under launchd" pattern documented there. Updated
`launchd/com.caravan.llama-server.plist` to use the Tailscale IP; still
needs a real bootstrap-and-verify pass to close out issue #1 (not done
yet as of this entry -- see that issue for status).

One process note from tonight: don't restart node-b's `rpc-server` while
node-a's `llama-server` is mid-load/mid-transfer to it -- did exactly
that once during this session (bootstrapping the renamed rpc-server
plist while an old load was streaming tensors to it) and it killed the
transfer (`ggml-rpc.cpp:569: Remote RPC server crashed or returned
malformed response`, `send failed`). Not a bug, just a sequencing
mistake -- node-b's rpc-server should be quiescent before starting a
load on node-a.

### The retry cascade, root-caused

The Tailscale-IP restart above got llama-server back up, but the very
first real turns after it came back kept failing with `LLM request
timed out` -- not once, but in a self-sustaining loop that ran for
close to half an hour. Traced it fully:

1. The `agent:main:main` session had grown to ~37k/66k tokens by the
   time this happened -- normal accumulation plus tonight's own churn
   (a manual smoke-test turn, several heartbeat attempts). At this
   hardware's current prompt-processing speed (~65-100 tok/s), a
   35k-token cold-cache prompt takes 400-600s just to process, before
   any generation starts.
2. `agents.defaults.timeoutSeconds` / the `caravan` provider's
   `timeoutSeconds` were both well under that (480s / 300s). So the
   *first* attempt at any cold-cache turn was close to guaranteed to
   get killed by openclaw's own client-side timeout right as it neared
   completion -- confirmed directly in the logs: one attempt got
   cancelled at n_tokens=35700/35719 (99.97% through prompt processing,
   not one token generated yet).
3. `slot_pin_proxy.py`'s `pick_slot()` forced `id_slot=0` on *every*
   request unconditionally, with no check for whether slot 0 was
   already busy. Each retry (or an overlapping heartbeat call) landed
   on the same busy slot and forced llama-server to cancel whatever was
   already in flight there -- including attempts that were seconds from
   finishing.
4. Each cancelled attempt's partial exchange still got appended to
   session history, growing the prompt for the *next* attempt, making
   the next cold reprocess slower still. Self-sustaining: cancel, grow,
   retry, cancel again.

It did eventually break out on its own (a couple of small, fully-cached
turns finally completed once the timing happened to line up), but
leaving it to chance isn't a fix. Three changes, all pushed:

- **`proxy/slot_pin_proxy.py`**: `pick_slot()` now checks `/slots`
  first. Prefers `PINNED_SLOT` when it's idle (the original cache-reuse
  behavior); if it's busy, routes to any other idle slot instead of
  stealing it. Falls back to the old unconditional pin only if the
  `/slots` check itself fails or every slot is busy -- no worse than
  before in that one case, strictly better otherwise.
- **`~/.openclaw/openclaw.json`**: `agents.defaults.timeoutSeconds`,
  `agents.defaults.heartbeat.timeoutSeconds`, and the `caravan`
  provider's `timeoutSeconds` all raised from 480/480/300 to 900 --
  real headroom over the ~600s worst-case cold-processing time measured
  tonight, so a cold turn gets one real chance to finish instead of a
  guaranteed kill-and-retry.
- **Session hygiene**: looked for a config-level fix first --
  openclaw has a native `agents.defaults.compaction` auto-compaction
  guard, but it only fires to avoid *overflowing* the context window
  (65536 tokens here); it has no opinion on a session that's merely
  large-relative-to-this-hardware's-speed without being close to that
  ceiling, so it wouldn't have prevented any of this. Added a separate,
  simple fix for that gap: `ai.openclaw.session-compact.plist`, a new
  LaunchAgent that runs `openclaw sessions compact "agent:main:main"
  --agent main --max-lines 10` once daily at 3am (outside the
  06:00-22:00 heartbeat active hours), so normal accumulation over days
  can't quietly repeat tonight's runaway growth.

Verified with a manual smoke test after all three landed: clean
21-second single-attempt success, no retry, `fallbackUsed: false`.

### Design session: the self-organizing Caravan agent

With the operational fire out, moved on to a real design conversation
about evolving Caravan toward what it was named for -- one thing hauling
a load across machines, not two hand-wired scripts. Landed on a full
design; the prescriptive reference now lives in
[docs/ARCHITECTURE.md](ARCHITECTURE.md) and gets updated in place as the
design evolves. This entry is the narrative of how we got there.

Started from "I want one app installed on every node that figures out
who's head and who's tail, like exo." First correction needed: llama.cpp's
RPC backend isn't symmetric the way MLX/exo is -- `llama-server` (head)
needs the full model file locally, `rpc-server` (tail) needs nothing
stored at all. exo buys its symmetry by giving every node a full local
copy (the N-way duplication Caravan was built to avoid, per the
shard-cache issue). Initially over-framed this as a binary choice
(lightweight tail-only subset vs. full exo-style duplication) -- wrong;
those are actually separate axes. The real resolution, worked out over a
few rounds: head follows wherever the full model already lives, and tails
only ever cache their own shard, never the whole model.

Next wrong turn: proposed "whichever node receives the request becomes
head" as if it needed to be dynamic/negotiated. Corrected once the actual
usage pattern was stated plainly -- there's realistically one Ollama
instance across the cluster (wherever openclaw's gateway points), so
head is *always* that machine in practice, and that's fine. This
simplified the whole role mechanism from something resembling leader
election down to pure self-declaration: a node checks its own local
Ollama store; has the model, it's head; doesn't, it's a tail candidate.
No voting, no negotiation, no split-brain to design around.

Also debated sequencing the shard-cache patch (issue #3) after Thursday's
incoming USB4/Thunderbolt cable, reasoning the cache matters less once
transfers are fast over a direct link. Pushed back on directly: exo is
useful without a fast interconnect, and Caravan should be too -- the
cable is a bonus, not a substitute for the software actually being good.
Corrected the reasoning: it's not "cache less important because of the
cable," it's "orchestration first because a `ggml-rpc.cpp` patch should
land on a stable base, not a manually-launched moving target." Both
phases stay fully committed regardless of Thursday.

Landed on hybrid discovery (LAN mDNS + Tailscale-when-available,
preferring Tailscale IPs given tonight's `EHOSTUNREACH` findings), Python
for phase 1 (fast iteration while the design was still visibly moving --
it changed more than once in this same conversation), and a compiled
language deferred to a later, distinct milestone rather than decided now.
Explicit call from the user on that last point: don't design the Python
code to be "portable" -- just keep archiving discoveries and reasoning in
GitHub (issues + this log) generously, and let *that* be the bridge to a
future port, not the code itself. Also considered and ruled out Ruby/Rails
-- Ruby is interpreted (a peer to Python, not a compiled option) and
Rails is a web-app framework with no fit for a networked daemon that has
no database or view layer.

Full detail, the two-phase build split, and the open questions this left
unresolved are in ARCHITECTURE.md, not repeated here.

### First real cross-node test of the scaffold

Cloned the repo onto node-b (it had none before) and ran the scaffolded
`agent/` for real on both machines, not just locally on node-a.

Found node-b's Python is old: `/usr/bin/python3` is 3.9.6, and the
scaffold's `X | None` return-type syntax needs 3.10+. Not a code
change -- node-b already has Homebrew's `/opt/homebrew/bin/python3`
(3.14.7), just need to invoke that explicitly there rather than
whatever `python3` resolves to first on PATH.

Found a real bug the moment discovery ran against live Tailscale peers:
without a liveness check, `tailscale status --json` returns *every*
tailnet peer, not just Caravan nodes -- node-a's dry run discovered an
unrelated machine (`mgmt-host`) and would have wired it into
`llama-server --rpc` as an RPC device had it not been caught. This is
exactly the gap ARCHITECTURE.md's open questions flagged ("what
health-check surface"); turned out not optional the first time this ran
against a real multi-peer tailnet. Added `health_server.py` (a tiny
`/health` endpoint every agent exposes) and an `is_agent_alive()` gate in
`caravan_agent.py` that only trusts a discovered peer if it actually
answers as a Caravan agent.

Then found a second real bug testing *that* fix cross-node: the health
server hung for ~35 seconds on startup, but only on node-b. Isolated it
in a few steps -- confirmed the hang was in constructing
`ThreadingHTTPServer` itself (nothing app-specific), then confirmed
`socket.getfqdn('0.0.0.0')` alone was the ~35s cost, called internally by
`http.server.HTTPServer.server_bind()` to set `self.server_name`. Fixed
by overriding `server_bind()` to skip that reverse-DNS-style lookup
entirely -- nothing in this codebase uses `server_name`/`server_port` for
anything, so there's no cost to not resolving them. Root cause of *why*
that lookup is specifically slow on node-b's network config wasn't
chased further; the fix doesn't depend on knowing why.

Also needed a way to actually test mutual discovery at all: the one-shot
dry run's health server dies the instant the process exits, which is
close to immediately -- no window for a second machine's discovery pass
to ever see it. Added `--serve-for SECONDS` to caravan_agent.py: keeps
the health endpoint up for a fixed window without spawning/supervising
anything, purely so two independently-launched dry runs can overlap long
enough to see each other. Test-support flag, not part of the real design
-- a persistent daemon mode is real future work (ARCHITECTURE.md doesn't
resolve this yet either).

With both fixes in place, ran the real test: started node-b's agent with
`--serve-for 60`, then ran node-a's agent (plain dry run) while it was
up. Result, exactly as designed: node-a self-declared head (has
muse-glimmer locally), discovered precisely one live peer (node-b, via
Tailscale, correctly excluding the unrelated tailnet machine this time),
and built the identical `llama-server` command already proven in
production tonight -- same blob path, same Tailscale IP, same
`--device`/`--tensor-split`/`-c` values. First genuine end-to-end proof
this design works against the real two-node setup, not just in isolation
on node-a.

Confirmed the live production processes (llama-server, the slot-pin
proxy) were unaffected throughout -- everything above ran in dry-run
mode, and test processes were cleaned up on both machines afterward.

### Real usage surfaces a gap the earlier proxy fix didn't cover

Kept using the live setup after the cross-node test and hit the actual
production version of what the scaffold's cross-node test caught in
miniature: two *different* sessions (a heartbeat on `agent:main:main`
and an interactive `openclaw chat` on a fresh `scratch-test` session)
made concurrent model calls. The earlier "don't steal a busy slot" proxy
fix (see above) meant they didn't collide/cancel each other -- but they
did run genuinely concurrently on two different slots, and llama-server's
RPC-sharded backend doesn't give each one its own throughput. Watched one
job's speed drop from ~94 tok/s to ~62 tok/s live as a second and third
started. One turn ended up taking ~12 minutes of prompt processing alone
before generation even started, then hit the (new, 900s) hard timeout
almost immediately after -- a real user-visible failure, not just slow.

Fix: a strict FIFO gate in the proxy (`FifoGate`, a ticket-based
condition-variable queue -- a plain `threading.Lock` doesn't guarantee
waiters are woken in arrival order, this does) serializing every
completion request through the proxy. Only one request is ever in flight
to llama-server at a time; everything else waits in exact arrival order.
Considered dropping llama-server to a single slot (`-np 1`) instead,
which would get the same effect via llama-server's own built-in deferred-
task queue (confirmed in `tools/server/server-queue.h` -- deferred tasks
are a `std::deque`, popped FIFO) -- rejected because it would collapse
all sessions onto one shared slot, reintroducing the cache-thrashing
problem the slot-pinning proxy was originally built to fix. The proxy-
level gate keeps all 4 slots and their per-session cache stickiness
intact; it only stops multiple slots from being *actively worked*
simultaneously.

To clear the stuck in-flight requests from the incident above rather
than wait them out, restarted the proxy directly -- severing its open
connections caused llama-server to detect disconnected clients and
cancel all four in-flight tasks at once (the same "stop: cancel task"
path seen all night), which conveniently also deployed the new FIFO code
in the same step. The original `scratch-test` turn had already hit its
900s hard timeout right as this happened and ended in a terminal error
(expected fallout of killing it, not a new bug) -- needed a manual resend
to get a fresh attempt.

Verified the fix directly rather than waiting for a natural collision:
fired two small raw completions at the proxy 0.3s apart while a real
heartbeat request was already in flight. Proxy log confirmed strict
ordering (`waited 25.2s behind 1 queued request(s)`, then
`waited 49.4s behind 2 queued request(s)`), and timing matched --
finished 3.5s apart despite starting 0.3s apart, i.e. sequential, not
concurrent. Unexpected bonus: the second test request landed on the same
slot the first had just warmed and got a 59/64-token cache hit, purely
because serialization left that slot idle-and-warm by the time its turn
came -- something concurrent execution on separate slots would never
have produced.

### Correction: exo does not require a full model copy per node

Every earlier entry in this log that describes exo's approach as
requiring "a full copy on disk" per node (the "Wiring it into a real
assistant" entry, the original shard-cache design entry, and the
self-organizing-agent design session above) is **wrong**. That claim was
never actually verified -- it was carried forward from an earlier
session's assumption and repeated without checking. Left the entries
above as-written since they're a record of what was believed and reasoned
from at the time; this entry is the correction, not an edit to them.

User asked directly tonight: exo appeared to be downloading only half the
model per node on a two-node setup, and wanted to know if that was real
or just appearances. Checked via web search rather than continuing to
assume either way: it's real. exo uses pipeline parallelism -- a model's
layers get split into per-node ranges by its Placement Engine, and each
node's DownloadCoordinator fetches only its own assigned range, never the
full model. Source: [exo's README](https://github.com/exo-explore/exo/blob/main/README.md),
[DeepWiki's exo overview](https://deepwiki.com/exo-explore/exo).

What this actually changes: issue #3 / Phase 2 (shard-scoped cache on
node-b) was framed as Caravan doing something smarter than exo --
avoiding "N-way duplication" exo supposedly forces. That framing is
gone; exo already has shard-only storage. The design itself doesn't
change (node-b caching only its assigned tensor range under a
content-addressed key is still the right target), but the motivation
does: this isn't Caravan improving on exo, it's Caravan catching up to
a pattern exo already proved out. Corrected the equivalent claim in
`docs/ARCHITECTURE.md` directly (that doc is meant to stay accurate in
place, unlike this log). The one difference from exo that does still
hold, on inspection: llama.cpp's RPC backend requires its head node
specifically to hold the *full* model file (metadata/tokenizer/
orchestration), which exo's pipeline-parallel design has no equivalent
requirement for -- no exo node ever needs full-model knowledge. That's
a real, inherent difference in this backend, not a design win.

### Two real fixes to the proxy, root-caused live against a real session

Went back to real usage after the last round of fixes: user sent "howdy"
to `main`, then "Hey you!", then a follow-up -- three real messages, each
taking ~11 minutes, each a full cold reprocess. Per-session pinning
(landed a few commits back) wasn't actually working. Two separate real
bugs, found by testing rather than continuing to reason from source:

**Bug 1: abandoned requests kept running for nobody.** User asked
directly: is there a way to cancel an ollama/llama-server request once
openclaw itself has given up on it? Checked -- no, there wasn't. A
request that hit openclaw's 900s timeout kept processing server-side for
minutes afterward, still holding both an llama-server slot and the FIFO
gate, delaying every real request queued behind it. llama-server already
has clean cancel-on-disconnect handling (confirmed all night, e.g.
whenever the proxy itself restarted mid-request) -- the gap was that our
proxy never told it the client had left. Added `ProxyHandler._client_gone()`:
polls the client connection with a non-blocking `MSG_PEEK` while waiting
on a slow upstream and while streaming; the instant the client's gone,
shuts down the proxy's own upstream connection, which trips llama-server's
existing cancel path. Tested in isolation first (a dummy slow-upstream
server + a synthetic client that disconnects mid-wait) before ever
touching the live proxy -- confirmed the disconnect propagates, and
confirmed the normal successful path is untouched.

Tried to verify this live too, by killing the CLI process behind an
`openclaw agent` call mid-flight -- inconclusive, and worth remembering
why: `openclaw agent` is a thin client that hands the request to the
already-running, persistent gateway service and waits for the result:
killing the CLI kills the thing waiting to *print* the answer, not the
gateway's own connection to the proxy, which is the real client from the
proxy's point of view. The isolated unit test remains the real evidence
this works; a true live test would need the gateway itself to give up,
not the CLI wrapper around it.

**Bug 2: per-session pinning was fingerprinting the wrong thing.** Added
temporary debug logging (message count, first-non-system-message
role/content preview, resulting fingerprint) rather than keep guessing
from openclaw's minified source, and the very next real request revealed
it immediately: the "first non-system message" `session_fingerprint()`
was hashing wasn't a real historical message at all -- openclaw injects a
synthetic marker at that position on *every single call*,
`"[Sun 2026-09-06 10:34 CDT] (session bootstrap)"`, timestamped to the
current minute. Different fingerprint every call, different slot every
call, full cache miss every call -- exactly the symptom seen live (three
requests to the same session, three different slots). Fixed by skipping
any message matching that bootstrap-marker pattern and using the first
message that's actually part of the real conversation. Verified against
the real captured pattern (varying timestamp, growing trailing history)
before deploying, not just assumed fixed.

Both changes deployed by restarting the proxy between real requests, not
mid-flight -- checked `/slots` empty first each time, and once cleanly
during an already-abandoned diagnostic request (intentionally killed for
testing, so restarting through it cost nothing real). Debug logging left
in place for now rather than stripped immediately -- cheap insurance
until the fingerprint fix has survived a few more real sessions.

### Two more real findings from live use: telegram token + TUI cancel doesn't disconnect

Root-caused the recurring `getUpdates conflict` errors flagged since the
very start of tonight's session (and, per the original handoff, before
that too). Ruled out the two usual local suspects first rather than
guess: no webhook set on the bot (confirmed directly via Telegram's own
`getWebhookInfo` API), and no duplicate openclaw gateway process on
either machine. Something external was genuinely, persistently
contending for the same bot token on a steady ~30s cycle -- user
confirmed a phone has the bot's Telegram chat open (though merely having
a chat open doesn't poll; the real cause was never conclusively
identified). Fixed decisively rather than keep hunting: revoked and
rotated the bot token via @BotFather, updated `openclaw.json`, restarted
the gateway. Conflict errors stopped immediately and stayed stopped --
clean ~30s poll cycles since.

Separately: user cancelled an in-flight TUI message and asked what was
worth doing -- checked, and the underlying request was still running
server-side, same pattern as the `openclaw agent` CLI finding above but
now confirmed for the TUI's own cancel action too. "Cancel" at the UI
layer doesn't appear to close the gateway's own connection to the
proxy -- it just stops the UI from waiting on/displaying the result,
while the request keeps consuming a real llama-server slot in the
background. The disconnect-cancel fix from earlier tonight only fires on
an actual TCP disconnect, which this isn't, from the proxy's point of
view -- so it correctly didn't fire here; the gap is one layer up, in
whatever "cancel" actually does (or doesn't do) inside openclaw itself.
Freed the slot the same way as always -- restarted the proxy, which
forces the disconnect and lets llama-server's own cancel-on-disconnect
handling do its job. Filed as a GitHub issue rather than just noted here,
since it's a real, likely-recurring cost (a user cancelling a slow
request should actually free the compute, not just hide it) and isn't
something we can fix from Caravan's side alone -- it's openclaw's own
cancel semantics.

### Seed caching for brand-new sessions -- mechanism proven, benefit not yet verified

Extended issue #4's save/restore to also help a session with no cache of
its own: instead of starting fully cold, fall back to restoring the most
recently saved *other* session's file as a seed, on the theory that the
bulk of any prompt here is the shared static prefix (tool schemas +
AGENTS.md), and llama-server's own prefix matching only reuses whatever
actually matches, safely ignoring the rest if it doesn't -- no synthetic
request or chat-template guesswork needed, just reusing a real file.

Found and fixed a real bug testing this: the in-memory "last saved
fingerprint" tracker doesn't survive a proxy restart, so it was empty
immediately after deploying this code even though a real, already-proven
save file existed on disk from before the restart. Fixed by falling back
to scanning `SLOT_SAVE_DIR` for the most recently modified `.bin` file
when the in-memory tracker is empty, rather than only trusting in-process
state.

With that fixed, the restore call itself does fire and succeed (confirmed
in the log: `restored slot 2 ... (seed from bfb2f0a32a1923d7.bin)`), but
two live tests using `openclaw agent --session-key` one-shot CLI calls
showed no measurable cache-hit benefit -- both ground through a full cold
reprocess at the normal pace (~15 min total) despite the seed restore
succeeding. Best-supported theory, not confirmed: CLI-invoked one-shot
calls may assemble the system prompt with different content than a real
persistent chat session does, beyond just the bootstrap-marker timestamp
already handled -- meaning the two test sessions likely didn't actually
share identical static-prefix content with each other, so there was
nothing for the seed to usefully match against. That's a plausible
testing-methodology gap, not confirmed evidence the mechanism doesn't
work for real sessions.

Committing the mechanism as-is (it's strictly additive and falls back to
today's behavior on any restore failure, so it can't make things worse)
but explicitly NOT claiming the cache-hit benefit is proven. Needs a
cleaner test -- two real persistent sessions, not synthetic CLI calls --
before trusting this actually helps in practice.

### Correction: seed-restore was disabled -- "can't make things worse" was wrong

Followed up properly rather than leaving the question open. Disproved
the "maybe CLI calls send different content" theory directly: added a
diagnostic hash of just the system-message content, fired two
`openclaw agent --session-key` calls with different keys, and got the
*same* hash both times (`a8f9ea07bbf4f931`) -- the static content really
is identical, so that wasn't the explanation.

The real cause, found by reading the actual error instead of continuing
to guess: this llama-server runs with `kv_unified=true` (visible in
`/slots` output all along, just not connected to this risk before
building the feature). The KV cache is one shared pool across all 4
slots, not independent per-slot buffers. Restoring a large (~38K token)
seed file into an idle slot while another slot concurrently holds a
large real context can exceed the pool's actual remaining space --
hit directly: `Unable to restore slot: No available space in KV cache`.
That failure then cascaded into a real retry-cancel storm (multiple
tasks launched and cancelled within seconds of each other) -- the exact
shape of tonight's earlier incidents, self-inflicted by this feature.

So the earlier claim that this "can't make things worse" was wrong: a
restore *failure* inside the proxy is handled gracefully (falls back to
cold, logs it, doesn't crash) -- but the resulting *error response*
reaching openclaw can still trigger openclaw's own retry behavior,
which repeats the same failing restore attempt, which fails again, on
a tight loop. Graceful failure inside one component doesn't guarantee
graceful failure of the whole system once something upstream reacts to
it. Disabled the seed branch entirely (own-file restore, issue #4's
proven mechanism, is unaffected) rather than trying to patch around the
KV-pool constraint under time pressure. Confirmed live: zero new restore
errors and the cascade stopped immediately after deploying the disable.

Re-enabling this later needs an actual fix, not just flipping it back
on -- e.g. checking available pool space before attempting a restore,
or only seeding when the other slots are idle/small. Left the code in
place, provably unreachable, with this reasoning attached, rather than
deleting it.

### Testing `--no-kv-unified` as the real fix for the shared-pool constraint

Rather than patching seed-restore to work around `kv_unified=true`'s
shared pool, tested removing the constraint at the source: added
`--no-kv-unified` to `com.caravan.llama-server.plist` so each of the 4
slots gets its own independent 65536-token KV buffer instead of sharing
one pool. Estimated cost ~4x KV memory (roughly 1GB -> 4GB), judged
affordable on 24GB machines. Bootstrapped clean (`bootout` + `bootstrap`
from the repo path, all slots confirmed idle first).

**First attempt silently didn't work.** After the ~10 minute reload
finished, the server's own startup log read
`kv_unified = 'true'` -- the flag had no effect. Read
`tools/server/server.cpp` to find out why: when `--parallel` isn't
passed explicitly, `params.n_parallel` defaults to `-1` ("auto"), and
there's an unconditional block that fires on that auto path:

```cpp
if (params.n_parallel < 0) {
    SRV_TRC("%s", "n_parallel is set to auto, using n_parallel = 4 and kv_unified = true\n");
    params.n_parallel = 4;
    params.kv_unified = true;
}
```

This runs *after* CLI arg parsing and overwrites `params.kv_unified`
unconditionally -- so `--no-kv-unified` was being silently clobbered
back to `true` on every start, because this plist has never passed
`--parallel` (it relies on the same auto-sizing to get 4 slots). Fixed
by adding `--parallel 4` explicitly alongside `--no-kv-unified`, which
keeps the slot count the same but skips the auto branch entirely,
letting the CLI flag actually stick. Confirmed live:
`n_slots = 4, n_ctx_slot = 16384, kv_unified = 'false'` -- the fix
worked, `--parallel 4` really was the missing piece.

### The 16K-per-slot cap was a real regression -- caught before shipping it

`n_ctx_slot = 16384` is `-c 65536` (the pre-existing flag) split evenly
across 4 now-independent slots. Checked that against actual usage
before calling this done: grepping the server log for past `n_tokens`
values on completed requests showed real sessions have already reached
**38,273 - 40,423 tokens** tonight alone -- more than double the new
16,384 cap. Shipping this as-is would have silently broken (truncated
or failed) any session that grows past 16K, which based on tonight's
own numbers is not a rare case.

Checked memory headroom before proposing a fix: both machines were down
to ~100MB of free VM pages with the model loaded -- there wasn't
obviously room to just quadruple the per-slot budget back to 65536
(4 slots x 65536 vs. the original single shared 65536 pool is a real 4x
KV memory increase). Flagged the tradeoff explicitly rather than
picking a side unilaterally: revert to `kv_unified=true` (dormant risk,
since seed-restore -- the only feature that ever exercised the shared-pool
failure mode -- is already disabled) vs. accept the 16K cap vs. try to
push `-c` higher despite the tight headroom. User chose to try pushing
`-c` higher and monitor memory directly.

### Raising `-c` to 262144 to get 65536/slot with kv_unified=false

Bumped `-c` from 65536 to 262144 (65536 x 4) so each of the 4
independent slots gets the originally-intended 65536-token budget.
Reloaded clean (slots confirmed idle first). Loaded successfully and
confirmed live: `n_slots = 4, n_ctx_slot = 65536, kv_unified = 'false'`,
`/health` ok, all 4 slots idle at `n_ctx: 65536`. Memory landed about
as tight as the original `kv_unified=true` config (~70-110MB free VM
pages on each machine) -- it fits, but with very little margin. This is
the expected ~4x KV cost materializing; whether it holds up under real
concurrent multi-session load (as opposed to idle-but-loaded) is still
unverified.

### Self-inflicted crash: restarting node-b's rpc-server after llama-server was already loaded

Went to fix the node-b `rpc-server` plist's stale `~/Library/LaunchAgents/`
path (deferred earlier tonight, see the launchd path-consistency section)
now that the `-c 262144` load was confirmed stable. Bootout+bootstrap on
node-b's rpc-server crashed llama-server within seconds:
`ggml-rpc.cpp:566: Remote RPC server crashed or returned malformed
response` -> `ggml_abort`.

The earlier rule from tonight ("never restart rpc-server mid-transfer")
was too narrow. `rpc-server` is stateless and holds node-b's half of the
model only in that process's own RAM for as long as the process lives --
restarting it wipes that state at *any* point while llama-server is
connected, not just during the initial load. llama-server holds a live
RPC session against it for its entire runtime, so the correct rule is:
never restart node-b's rpc-server while llama-server is running at all.
The only safe order is to restart llama-server itself afterward (which
re-establishes the connection from scratch and re-transfers), or to stop
llama-server first, restart rpc-server, then start llama-server.

launchd's `KeepAlive` caught the crash and auto-restarted llama-server
immediately (visible as a fresh boot sequence in the log within the same
second) -- no manual intervention needed to bring it back up, just
another full cold reload to sit through. rpc-server's plist path fix
itself succeeded (now loading from the repo path like the other two
services, confirmed via `launchctl print`).

### End-to-end confirmation of kv_unified=false in real use

Ran a real test through the actual `openclaw agent` CLI (not just
`/slots`/`/health` checks) after the crash-recovery reload settled, plus
the user ran their own manual tests through openclaw directly. Two
findings, one good and one worth flagging separately (see next entry):

- **Cold start is unregressed.** First real message took ~7 minutes --
  matches the historical pre-kv_unified=false baseline. So the larger
  `-c 262144` config didn't cost anything on the thing that already
  worked.
- **Cache-hit follow-ups are fast.** Plain greetings and factual/math
  questions on an already-warm session came back in 11-15 seconds.
- **Tool-calling questions are much slower, but not because of the model
  or kv_unified.** Asking "who am I" took ~3 minutes. Root cause,
  confirmed directly: this kind of question makes openclaw's agent loop
  call tools (`memory_search`, `read` on USER.md/MEMORY.md, etc.)
  instead of answering directly -- each tool round-trip is its own full
  completion call through llama-server. Individually fast (cache-hit),
  but 3-5+ stacked rounds adds up to minutes even with no single slow
  step. This is an openclaw-agent-loop cost, not a Caravan-side problem.

### My own test accidentally ran in the live `agent:main:main` session and timed out

Testing end-to-end via `openclaw agent -m "..."` reused the real
`agent:main:main` session (not an isolated test session) and triggered
an 8-assistant-turn tool-calling run (`memory_search`, `sessions_search`,
`sessions_history`, `read`, `exec`, `sessions_list`) that ran the full
15-minute `agents.defaults.timeoutSeconds` without producing a reply.
Checked whether this left `main` in the same stuck/dangling state as the
original handoff's known issue (`openclaw sessions tail`): it didn't --
openclaw closed it out cleanly (`session.ended interrupted`) rather than
leaving a hung mid-turn. Still added a chunk of failed-tool-call noise to
that session's history, the same kind of bloat that caused the original
stuck-session problem -- flagged to the user as a candidate for the same
`openclaw sessions compact "agent:main:main" --agent main --max-lines 10`
fix used before, rather than compacting unprompted.

## Issue #2: investigated the system prompt, found a safety bug along the way

Per the issue's own planned order: checked `tools.profile: "coding"` for
unnecessary weight before touching `AGENTS.md`. Per openclaw's own docs
(`docs.openclaw.ai/gateway/config-tools`), "coding" baseline is
`group:fs, group:runtime, group:web, group:sessions, group:memory, cron,
goal tools, progress_card, ask_user, skill_workshop` -- notably,
`group:sessions` already includes `sessions_spawn`/`sessions_yield`, so
those two entries in `tools.alsoAllow` were pure no-ops (removing them
changed nothing, confirmed by measurement). `browser` was the one real
addition beyond the coding baseline: removing it dropped
`tools.schemaChars` from 45,650 to 40,709 (-4,941 chars), confirmed via
`openclaw agent --json`'s `systemPromptReport`. Kept `message` in
`alsoAllow` untouched -- it's very likely what delivers replies to chat
channels, not something to remove blind.

**Bigger finding, unrelated to prompt size:** `AGENTS.md` (26,749 raw
chars) was being silently truncated to 19,182 chars by the 20,000-char
`agents.defaults.bootstrapMaxChars` limit -- and the cut landed right
after "## 1. Purpose" of the "Income Generation Module," dropping
Sections 2-8 entirely. That includes Section 4, the financial firewall
("Rook may never move money, in any amount, for any reason, without
explicit per-instance approval"), the autonomy tiers, and the escalation
default. None of that was reaching the model, on any session, silently.
Checked whether splitting the module into its own file would avoid the
size cost: no -- openclaw's bootstrap injection only recognizes a fixed
file set (`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`,
`HEARTBEAT.md`), confirmed via the config schema, so a split file
wouldn't auto-load and would depend on the model remembering to go read
it -- not acceptable for a safety-relevant rule. Fixed by raising
`agents.defaults.bootstrapMaxChars` to 30000 (all 5 bootstrap files
combined are only ~31,762 raw chars, nowhere near the separate 60,000
`bootstrapTotalMaxChars` ceiling, so this was free room, not a tradeoff
against that limit).

**Net effect measured live:** `systemPrompt.chars` went from ~38,883 to
45,741 -- *up*, not down. The tools trim saved 4,941 chars; restoring the
truncated 7,567 chars of real safety content cost more than that saved.
Correct tradeoff (a live safety gap outweighs a size optimization), but
it means this round didn't accomplish the issue's original goal of
shrinking cold-start cost. The remaining lever is trimming `AGENTS.md`'s
actual content -- real policy the user wrote, not something to cut
without them reviewing it, so left as an open, user-owned option rather
than done tonight.

## Issue #3: solved natively -- `rpc-server --cache`, no C++ patch needed

Originally scoped this as a multi-hour feature requiring a patch to
`ggml-rpc.cpp` (a hash-keyed on-disk tensor cache, checked before
accepting a network transfer). Wrong -- should have checked upstream
source before concluding that. It already exists, built into mainline
llama.cpp:

- Every `SET_TENSOR` over 10MB (`HASH_THRESHOLD`) triggers the client
  (llama-server, always, unconditionally -- no client-side flag) to try
  `RPC_CMD_SET_TENSOR_HASH` first: send just an FNV hash of the tensor's
  actual content.
- `rpc-server`'s `-c`/`--cache` flag makes the *tail* persist tensor
  content to `~/Library/Caches/llama.cpp/rpc/<hash>` (any content > 10MB)
  and check that cache on every future hash-first request. A hit
  (`response.result = 1`) skips the actual data transfer entirely and
  loads from local disk instead; a miss falls straight back to a normal
  full transfer, so it degrades cleanly with zero coordination needed
  between head and tail versions/config.
- Self-invalidating by construction -- keyed on real tensor content, not
  a filename or version string, so a changed model file just produces a
  cache miss and a normal (slow) fallback, never stale data silently
  served.

Implementation was a one-line plist change on node-b
(`com.caravan.rpc-server.plist`, add `--cache`) plus the same corrected
restart sequence from earlier tonight (stop llama-server first, since it
holds a live RPC session against rpc-server; only then bootout/bootstrap
rpc-server; then start llama-server again). Verified live, twice:

- First reload after enabling `--cache` (cache empty, has to populate):
  7m23s -- normal, matches the historical baseline, as expected for a
  cold cache.
- Confirmed the cache actually populated: `~/Library/Caches/llama.cpp/rpc/`
  on node-b, 151 files, 7.6GB, matching node-b's assigned half of the
  model.
- Second reload immediately after (same model, same tensor-split, cache
  warm): **53 seconds**, confirmed via node-a's own log timestamps
  (`model loaded` / `listening` at 0:50.5 elapsed) matching the observed
  wall-clock time. Roughly an 8-9x speedup over the 7-11 minute baseline
  that held all night.

This is the second time tonight a "sounds like real engineering work"
problem turned out to already be solved upstream (issue #4's slot
save/restore was the first). Should have checked `rpc-server --help`
before scoping this as a C++ patch in the first place -- prefer native,
built-in levers over custom builds, and check for them before estimating
effort, not after.

## Issue #7: checked for native levers first, scoped down, shipped the small piece

Applied the same "check before building" discipline to issue #7's three
proposed signals before writing anything:

- **Ready/loaded** -- already covered. The RPC `HELLO` handshake plus
  llama-server's own `/health` endpoint already give this at the
  application layer. Nothing to build.
- **Heartbeat/resource stats** -- partially already there.
  `ggml-rpc.cpp` has a real `RPC_CMD_GET_DEVICE_MEMORY` command (checked
  the source: `rpc_server::get_device_memory`, used today only once at
  startup by `common/fit.cpp` for capacity planning, never polled
  periodically). A small script polling it on a timer would give live
  GPU-memory monitoring with zero llama.cpp changes. Doesn't cover CPU
  load or temperature, though -- `ggml-rpc` has no concept of those at
  all (a tensor-compute backend, not a system monitor); that part would
  need a separate small script wrapping macOS's own tools (`vm_stat`,
  `powermetrics`), not new protocol work.
- **Shutdown notice** -- confirmed genuinely missing (no `SIGTERM`
  handler anywhere in `rpc-server.cpp`/`ggml-rpc.cpp`), but issue #3's
  `--cache` fix changed the cost math: recovery from the resulting crash
  used to mean a 7-11 minute reload, now it's ~50s warm. The crash itself
  is cheap to recover from now, so a protocol-level graceful-shutdown
  handshake isn't worth building yet -- the practical fix is just
  sequencing the existing restart correctly.

Shipped that last piece: `scripts/restart-rpc-server.sh` -- checks
`/slots` is idle (refuses without `--force`), stops llama-server, waits
for it to actually exit, restarts rpc-server via SSH from the repo path,
starts llama-server again, polls `/health` until ready. Deliberately
outside `agent/` -- that's the separate, bigger self-organizing-agent
initiative (still a scaffold, not wired into launchd); this is a small,
immediate tool for the launchd setup actually running today. Ran it for
real: 34 seconds end-to-end, even faster than the manual 53s test
earlier tonight. Verified `/health` ok, all 4 slots at `n_ctx: 65536`,
rpc-server loaded from the repo path on node-b afterward.

The remaining pieces of #7 (periodic GPU-memory polling, general
system-resource monitoring) are small, well-scoped scripting work, not
urgent -- left as a future addition rather than built tonight.

## Everything converges into one app -- and the scaffold had drifted from tonight's production config

Asked directly: won't the proxy, the restart-coordination logic, and
monitoring all eventually be part of the single unified `agent/` app
rather than staying separate scripts? Yes -- that's `ARCHITECTURE.md`'s
own stated goal ("One app... installed identically on every machine"),
just not written down explicitly enough. Added a "Scope: what 'one app'
actually covers" section to `ARCHITECTURE.md` naming all four pieces
(process supervision, the proxy, cross-node restart coordination,
monitoring) as things that converge into the agent, not stay standalone.

While there, found and fixed a real gap: `agent/supervisor.py`'s
`build_head_command()`/`build_tail_command()` didn't reflect *any* of
tonight's hard-won production config. Had the agent been run with
`--apply` as-is, it would have silently reproduced the exact
`kv_unified=true` shared-pool problem and 16K-per-slot truncation risk
fixed earlier tonight -- no `--parallel`, no `--no-kv-unified`, no
`--slot-save-path`, a flat `-c 65536` instead of `n_slots * ctx_per_slot`,
and no `--cache` on the tail side at all (the exact flag that just gave
an 8-9x restart speedup). Fixed both functions and added the missing
config (`LLAMA_SERVER_N_SLOTS`, `LLAMA_SERVER_CTX_PER_SLOT`,
`SLOT_SAVE_DIR`, `RPC_SERVER_USE_CACHE`) to `agent/config.py`. Verified
via a real dry run: `caravan_agent.py`'s printed head command now
matches the live production `llama-server` invocation exactly (`-c
262144 --slot-save-path ... --parallel 4 --no-kv-unified`), and
`build_tail_command()` now includes `--cache`.

Also corrected `ARCHITECTURE.md`'s Phase 2 description, which still said
shard caching needed "a real patch to `ggml-rpc.cpp`" -- stale as of
issue #3's native fix earlier tonight. Phase 2 is now mostly done; what's
left is exactly the `--cache` wiring just fixed above, not new
engineering. Updated the GitHub-issues cross-reference section to match
current reality (#1 and #3 both closed, #7 open but scoped down).

Monitoring itself (the actual GET_DEVICE_MEMORY polling / vm_stat
extension to `health_server.py`) is still the next concrete step --
scope agreed, not yet built.

(Monitoring shipped shortly after this entry -- see "agent: add
resource-stats monitoring to /health" below.)

## Issue #2, closed out: the last two safe AGENTS.md trims

Went through the full, now-untruncated `AGENTS.md` looking for anything
genuinely cuttable -- not a values call, just redundancy. Found two:

1. A leftover TOOLS.md-migration block that was a *template example*
   (placeholder camera names, a placeholder SSH host, a placeholder TTS
   voice) rather than real configured content -- trimmed to a one-line
   pointer, kept the "why kept separate from skills" rationale.
2. Two sections covering the exact same rule and the same real incident
   ("Large Deliverables" and "Large or Multi-Item Deliverables"),
   apparently from two authoring passes that never got merged. Combined
   into one section, keeping the full recipe, the explicit
   never-placeholder rule, and the real incident narrative -- nothing
   lost, just said once instead of twice.

Set honest expectations before doing this: these are real but small --
estimated ~3-5 seconds off a 7-minute cold start, not a fix for that
number. The actual cost driver is legitimate content (tool schemas,
~10K tokens; AGENTS.md's real remaining content, ~6.4K tokens) plus, per
earlier tonight's own test, conversation/tool-call history growing
*within* a session (one test grew from 12K to 36K+ tokens through normal
multi-round tool use -- dwarfing anything AGENTS.md contributes).
Shrinking cold-start further from here would mean trading away tool
capability or behavior guidance, not finding more bloat.

Verified live: `AGENTS.md` 26,750 -> 25,848 chars (-902), confirmed via
`openclaw agent --json`'s `systemPromptReport` on a fresh session --
`systemPrompt.chars` 45,741 -> 44,842 (-899, matching almost exactly),
`truncatedFiles: 0` still holds. Closing issue #2 here: found and fixed
the one real bug (the truncation), found and cut the one real waste
(`browser` tool), found and merged the two safe redundancies. What's
left is legitimate content, not something to keep hunting for savings
in.

## Issue #5 prep: confirmed the RDMA-over-Thunderbolt software stack is already fully ready

Asked directly whether there's anything actionable before Thursday's
USB4/Thunderbolt cable arrives, given issue #5 itself is otherwise
blocked on the hardware. Worth checking rather than assuming there's
nothing to do -- there was real prep work available.

Traced `ggml-rpc.cpp`'s startup banner (`"transport: TCP (RDMA auto-
negotiate enabled)"`, printed on every rpc-server/llama-server start
tonight, easy to have skimmed past as decorative) back to
`ggml/src/ggml-rpc/CMakeLists.txt`: on Apple, `GGML_RPC_RDMA` auto-
enables at cmake-configure time if `librdma.dylib` is found, weakly
linked (comment in the CMake file: "librdma.dylib only exists on macOS
26.2 and later"). Both nodes run macOS 26.6.2. First check
(`strings ~/dev/llama.cpp/build/bin/ggml-rpc-server`) found nothing --
false negative, because `ggml-rpc` builds as its own dylib
(`libggml-rpc.0.23.0.dylib`) that the thin `ggml-rpc-server`/
`llama-server` executables just link against; the actual RDMA code
lives there, not in the executables themselves. Checking the real
library found the full RDMA(Apple/UC) string table (probe/activate/
RTR/RTS/poll_cq error strings) on both nodes. Confirmed further with
`vmmap` on the actual *running* processes (not just static analysis):
`librdma.dylib` and, specifically, `libthunderboltrdma.dylib` are
loaded live in both llama-server (node-a) and rpc-server (node-b) right
now -- this isn't just compiled in, it's active in memory already.

Also checked whether any macOS-level Thunderbolt networking setup is
needed: both machines already have "EXO Thunderbolt 1/2/4" network
services configured (pre-existing, from exo's own earlier Thunderbolt
setup) -- nothing new to create there.

**One real unknown, genuinely can't resolve without the hardware in
hand:** read `transport-apple.cpp` to understand how RDMA activation is
actually negotiated. `apple_rdma::probe()` takes the *existing bootstrap
TCP socket* as its starting point -- RDMA negotiates over whatever
connection `--rpc <ip>:<port>` already established, not a separate
control channel. But RDMA device matching uses RoCEv2 IPv4-mapped GIDs
keyed off "the local TCP address" (source comment) -- meaning it's
unclear whether the current Tailscale-IP-based `--rpc` config will
auto-upgrade once the cable's connected, or whether it needs to be
re-pointed at whatever IP the Thunderbolt Bridge interface gets
assigned. Not resolvable by reading source alone; a real 2-minute check
once the cable's in (try as-is, check the log for "RDMA activated" vs.
plain TCP fallback, re-point the `--rpc` address if needed).

Net: nothing left to build in software for issue #5. When the cable
arrives, this should be "plug in, check one log line, maybe change one
IP" rather than research from scratch.

## Wiring the agent into launchd for real: node-b cutover, proven live

Started the "one app" milestone -- replacing the hand-written per-role
plists with `com.caravan.agent`, identical on every node, self-detecting
head/tail. Found and fixed a real gap before touching anything live:
`supervisor.py`'s `supervise()` had no signal handling. launchd stopping
the agent (a plain `bootout` -- the routine operation this whole effort
exists to make safe) would kill the Python process but leave its spawned
`llama-server`/`rpc-server` child orphaned and still running, invisible
to launchd, likely blocking the port on the next start. Fixed by
catching `SIGTERM`/`SIGINT` and forwarding `terminate()` to the child
before exiting, with a `SIGKILL` fallback. Verified synthetically first
(a long-running child actually dies with the parent on `SIGTERM`,
confirmed via `ps`; the normal crash-restart loop still restarts on
schedule) before ever trusting it with launchd.

Wrote `launchd/com.caravan.agent.plist` (Homebrew python3, matching the
version note in `agent/README.md`). Real gotcha hit immediately: wrote
and validated the plist locally but forgot to commit+push it before
trying to use it on node-b -- `bootstrap` failed with a confusing
"Input/output error" that looked like the known bootout/bootstrap race
from earlier tonight, but was actually just a missing file. Worth
remembering: that specific error message means more than one thing.

Cutover plan (chose node-b/tail first -- lower blast radius than head):
stop llama-server, swap node-b's `com.caravan.rpc-server` for
`com.caravan.agent`, verify, restart llama-server, then a real crash
test. All verified live:

- Agent correctly self-detected tail role and spawned the exact
  production command (`ggml-rpc-server -H 0.0.0.0 -p 50052 --cache`) --
  confirmed via `ps -o pid,ppid` that the child's parent PID is the
  agent's own PID, not launchd directly.
- llama-server reconnected to it normally, full health.
- **Crash test**: `kill -9`'d the agent-supervised `rpc-server` directly.
  Agent noticed and respawned it ~13s later (matches the default
  `restart_delay`), same agent PID throughout -- launchd's own
  `KeepAlive` was never involved, proving the two-layer model works
  (agent supervises its child; launchd supervises the agent itself).

**Found something worth knowing while checking this, not from the
cutover itself:** `/health` returning `ok` right after the kill did
*not* mean llama-server's RPC connection was actually usable -- it was
latently broken (a fresh `rpc-server` process is a different connection
than the one llama-server still held a reference to), and `/health`
only checks HTTP liveness, not RPC connectivity. Sent a real
`/completion` request to check properly: got `ggml_abort` immediately,
launchd's `KeepAlive` auto-recovered llama-server (same pattern as the
original "self-inflicted crash" entry, confirming that failure mode is
about *any* rpc-server restart, not specific to how it's triggered).
After that recovery, a real `/completion` request returned a genuine
`200 OK` with actual generated tokens -- confirmed fully working, not
just superficially healthy. Lesson for future verification: after any
rpc-server restart, check with a real inference request, not just
`/health`.

Node-b is now running under agent supervision, proven stable through a
real crash-and-recover cycle. Node-a (head) cutover is the next step,
deliberately sequenced after node-b per the original plan -- higher
blast radius, since that's the node openclaw actually depends on being
up.

## Node-a agent cutover: Tailscale discovery fails under launchd, reverted to the manual plist

Cut node-a over the same way as node-b (stop llama-server, bootout the
manual plist, bootstrap `com.caravan.agent`). It came up and correctly
self-detected HEAD role -- but the spawned command had no `--rpc`/
`--device` at all (`--tensor-split 1`, single value): zero peers
discovered, meaning it silently ran single-node instead of sharded
across node-b. A real functional regression, not cosmetic -- caught
before treating the cutover as done, by actually reading the spawned
command rather than just checking `/health`.

Diagnosed methodically rather than guessing: `agent.log` was empty even
with real content to show (found and fixed a related but separate bug:
Python's stdout is fully buffered when not a TTY, same class of issue as
tonight's earlier rpc-server buffering mystery -- added `-u` to the
plist's `ProgramArguments` for unbuffered agent output). With logging
actually working, both `tailscale.get_peers()` and
`caravan_agent.is_agent_alive()` were tested in isolation first and both
succeeded from an interactive shell -- yet the real agent, run for real
under launchd, reproducibly found 0 peers (twice). Added temporary debug
logging to `tailscale.py`'s exception handler rather than keep guessing,
redeployed, and got the real answer immediately: `tailscale status
--json` returns exit code 0 but stdout `"The Tailscale GUI failed to
start: The operation couldn't be completed. (Tailscale.CLIError error
3.)"` -- not JSON at all, hence the `JSONDecodeError` that was silently
swallowed into "0 peers."

Root cause: `/Applications/Tailscale.app`'s bundled CLI binary isn't a
standalone client -- its `status --json` shim talks to the already-
running Tailscale.app GUI process over local IPC. That works fine from
an interactive shell (the GUI app is reachable in that session context)
but fails specifically from a launchd LaunchAgent -- another instance of
tonight's recurring theme (see ARCHITECTURE.md's EHOSTUNREACH note) that
this Mac's process context measurably affects network/IPC behavior in
ways not fully understood. Checked for a fix: a standalone
`tailscaled`-based CLI exists as a separate Homebrew formula
(`brew install tailscale`), but it's not installed -- only the GUI cask
is. Installing it would mean running a second Tailscale client/daemon
alongside the existing GUI app, a real infrastructure change (possible
conflict with the connection that's been working reliably all night,
needs root via `brew services`) -- not something to do unilaterally
mid-cutover. Left unfixed for now, flagged as a real follow-up.

**Reverted node-a to the manual `com.caravan.llama-server` plist**
rather than leave it running degraded. Verified restored: real `--rpc
<node-b-tailscale-ip>:50052 --device MTL0,RPC0 --tensor-split 1,1` command,
warm-cache reload, and confirmed with an actual `/completion` request
(not just `/health`, per the lesson from node-b's crash test above) --
`200 OK`, all 4 slots at `n_ctx: 65536`.

Cleaned up the temporary debug prints into permanent, properly-labeled
diagnostic logging (not removed entirely -- this exact failure mode
would be equally hard to diagnose next time without them) rather than
leaving throwaway `DEBUG` output in place.

**Current state**: node-b runs under agent supervision (tail role
doesn't depend on peer discovery at all, unaffected by this bug,
verified stable). node-a is back on the manual plist, running the
proven production config. The `agent/` head-role cutover is blocked on
either fixing Tailscale CLI discovery under launchd, or adding an mDNS-
only fallback path that doesn't need Tailscale for this specific
2-node/same-LAN case -- not on anything else.

## mDNS fallback for peer discovery -- implemented, dry-run verified, live verification still pending

Researched installing a standalone `tailscaled` (the Homebrew formula)
before touching anything: confirmed via Tailscale's own docs that Mac
App Store + Standalone variants together is a hard, documented conflict
(not just a caution) -- but what's installed here is the *Standalone*
variant (`brew install --cask tailscale-app`), not App Store, so that
specific conflict doesn't apply. Whether Standalone + the separate
open-source `tailscaled` formula can coexist is genuinely unconfirmed by
official docs either way. Given that real ambiguity, no urgent need
(node-a was already safely reverted and working), and a real risk to
the production `--rpc` path if wrong, chose the safer option: extend
the agent's own mDNS discovery to work as a real fallback instead,
zero new system-level installs.

Two real bugs found and fixed along the way, in order:

1. `caravan_agent.py`'s `_rpc_addrs_from_peers` (new) now builds --rpc
   addresses from *any* discovered peer, Tailscale preferred, falling
   back to mDNS -- previously hardcoded to Tailscale-only, silently
   ignoring mDNS peers even though `discover_peers()` already found
   them. Dedupes by a best-effort normalized hostname (strips `.local`,
   lowercases) since there's no shared node_id across sources yet.
2. Deeper bug, caught by actually dry-running the change rather than
   trusting the diff: `mdns.advertise_start()` existed but was never
   called anywhere -- the agent only ever *browsed* for mDNS peers, so
   there was nothing to find regardless of fix #1. Added the missing
   `advertise_start()` call to `main()`, with `advertiser.terminate()`
   in a `finally` so a stopped agent doesn't leave a stale mDNS
   registration behind. That surfaced a *third* bug immediately: once
   node-a started advertising itself, its own `dns-sd -B` browse found
   its own advertisement, and the head command tried to add itself as
   its own `--rpc` target. Fixed with a `self_hostname` filter in
   `discover_peers()`.

**Verified**: dry run on node-a (no live launchd changes) now correctly
excludes self, and produces the same correct production command as
before when Tailscale succeeds (interactive shell -- Tailscale's CLI
works fine there, only fails under launchd). **Not yet verified**: the
actual case this was built for -- Tailscale failing under launchd
*and* mDNS correctly stepping in as the real fallback -- since that
needs a live agent cutover cycle on node-a, deliberately not attempted
tonight (see below). Committed and pushed as "implemented, dry-run
correct, live-path unverified" rather than overclaiming it's done.

## Session pausing here -- stopping-point check

User is pausing Caravan to switch to a different project (openclaw/exo
+ Rook's retro income-idea work) in a new session. Verified before
handoff: git clean and pushed on both nodes, both live services healthy
(node-a manual llama-server plist, node-b `com.caravan.agent`), GitHub
issues reflect true state. Deliberately did *not* attempt node-a's live
agent cutover under this time pressure -- that's real production risk,
not something to rush before a context switch. Next session picking
this back up should start with the live cutover test (mDNS-fallback
path specifically), now that the code is believed correct but unproven
live.

## The cable arrived, tested live -- issue #5 resolved, RDMA confirmed unavailable on this hardware

The USB4/Thunderbolt cable arrived two days early; user plugged it in
mid-session while in the middle of a different project (openclaw now
running with exo/MLX as primary, not Caravan -- see below). Tested it
live rather than waiting for a dedicated session.

**Environment had drifted since the last Caravan session**, discovered
by checking rather than assuming: `openclaw.json`'s primary model is
now `exo/mlx-community/gemma-4-31b-it-6bit`; every `com.caravan.*`
launchd job was gone from node-a entirely (not stopped -- absent); and
node-b's SSH at `<node-b-lan-ip>` timed out because its LAN IP had changed
to `<node-b-new-lan-ip>` (an ordinary DHCP change, unrelated to anything else
-- caught via Tailscale's `status` output showing the new address in
its "direct" connection line, since node-b's Tailscale IP itself,
`<node-b-tailscale-ip>`, hadn't changed). Node-b's `rpc-server` was also found
running from the old stale `~/Library/LaunchAgents/` copy again, without
`--cache` -- the file had reappeared despite being deleted earlier this
week (cause not investigated; possibly a Time Machine/local-snapshot
restore tied to whatever the other session did). Fixed the same way as
before: bootout, remove the stale copy, bootstrap from the repo path.

**Confirmed the physical link first, before any benchmark**: `en2`
(Thunderbolt 1 port, per `networksetup -listallhardwareports`) came up
active on both nodes with standard macOS link-local addresses on the
same /16 (node-a `169.254.121.90`, node-b `169.254.72.237`) -- a plain
`ping` between them showed clean sub-millisecond RTT, 0% loss.

**First benchmark attempt was misleading**, caught before drawing a
wrong conclusion: ran llama-server manually (not via the launchd plist
-- this was a benchmark, not a permanent config change) with `--rpc`
pointed at the Thunderbolt link-local IP instead of Tailscale's. Loaded
in 39.8s -- but node-b's disk cache (issue #3's `--cache`) was still
warm from before, so the entire "load" may have been served from local
disk via content-hash matching, zero bytes actually moved over any
transport. Re-ran it properly: cleared node-b's cache dir (874 files,
accumulated since issue #3 was implemented) to force a genuine cold
transfer, and timed that instead.

**Real result, genuine cold transfer**: **29-39 seconds**, cache
re-populated to the expected 151 files / 7.6GB confirming real data
moved. Compare to the documented WiFi cold baseline of 7-11 minutes
(420-660s) -- **roughly 14-22x faster**. Generation speed also improved:
6.1 tok/s vs. the ~3.8-4.5 tok/s baseline all night over WiFi (lower
per-token RPC round-trip latency over a wired link vs. WiFi). Prompt
processing on a 149-token prompt: 48.5 tok/s, in line with historical
numbers -- unsurprising, prompt processing was never network-bound the
way cold-load and per-token generation were.

**RDMA itself never activated** -- no `RDMA(Apple/UC) probed`/`activated`
line on either side, just the generic `TCP (RDMA auto-negotiate
enabled)` startup banner. User asked directly whether RDMA is even
available on M4 -- checked rather than assumed: **RDMA over Thunderbolt
requires Thunderbolt 5, available only on M4 Pro, M4 Max, or M3 Ultra**
(source: Apple's TN3205 and AppleInsider's coverage of the macOS 26.2
beta feature). Confirmed via `system_profiler`: this hardware is plain
Apple M4, and the negotiated link speed is "40 Gb/s" -- Thunderbolt
4/USB4, not Thunderbolt 5's 80-120 Gb/s. So RDMA is a genuine, permanent
hardware ceiling on this specific hardware, not a config problem to keep
chasing. The 14-22x speedup already measured is entirely from swapping
WiFi for wired Thunderbolt 4 in plain-TCP mode -- and that's the whole
result; there's no RDMA-specific follow-up to pursue on these two Macs.

Issue #5 closed as resolved. This was a manual benchmark process, not
wired into the launchd plist or openclaw -- node-a's `llama-server` plist
still points at the Tailscale IP as its checked-in config. Whether to
make the Thunderbolt link the permanent `--rpc` target (and how that
interacts with the still-unresolved agent-based head cutover from
earlier tonight) is a real follow-up, not decided here -- this session
was specifically about answering "does the cable help," not migrating
production. Left the benchmark llama-server process running rather than
tearing it down mid-write-up; cleanup/restoration to be decided based on
whether Caravan or exo should be openclaw's active primary right now,
which is the other project's call, not this one's.

## Auto-select fastest available network path

User's proposal after seeing the Thunderbolt numbers: the agent should
look for available network paths to a peer and automatically default to
the fastest one, rather than a hardcoded IP. Built it as one feature
covering both "use Thunderbolt when present" and "gracefully fall back
if it isn't" (issue raised earlier tonight as a separate open question)
-- they're the same mechanism, not two.

**Design**: fixed priority by interface type (Thunderbolt > Tailscale >
mDNS/LAN), not a live bandwidth measurement -- matches how the user
described it, and reuses already-proven code instead of building new
speed-testing infrastructure:

- New `discovery/thunderbolt.py`: `local_fast_paths()` finds this node's
  own IPv4 address on any *up* Thunderbolt Bridge interface, identified
  via `networksetup -listallhardwareports`'s "Thunderbolt N" hardware
  port labels (distinct from the "EXO Thunderbolt N" *service* names
  exo's own earlier setup created -- different namespace, confirmed by
  checking both outputs side by side rather than assuming they matched).
- `health_server.py`'s `/health` now includes `fast_paths` alongside the
  existing stats -- a peer already has to call `/health` to confirm
  liveness, so it gets this for free in the same round trip.
- `caravan_agent.py`: `is_agent_alive()` split into a lower-level
  `_agent_health()` returning the full parsed body (peers need to read
  `fast_paths`, not just get a bool). New `_select_best_address(peer)`
  tries each of a peer's self-reported `fast_paths` in priority order,
  reusing `is_agent_alive` (the same already-proven liveness check) as
  the reachability test -- first one that answers wins, otherwise falls
  back to whatever address `discover_peers` found the peer through
  (Tailscale preferred over mDNS, as before). Wired into
  `_rpc_addrs_from_peers` in place of the raw `peer['ip']` lookup.

Automatic fallback falls out for free: if a peer's Thunderbolt candidate
stops answering (cable unplugged, or never connected), `is_agent_alive`
just returns False for it and the next candidate in priority order gets
used -- no separate "detect disconnection" logic needed.

**Verified both directions**, not just the happy path: started a
disposable standalone `health_server` instance on node-b (its real
`com.caravan.agent` isn't running right now -- only the manually-managed
`rpc-server`, see above -- so this tested the new code without touching
the live benchmark) and confirmed real dry-run output on node-a: with
`fast_paths: ["169.254.72.237"]` reported, `discover_peers` found
node-b via Tailscale as before but `_select_best_address` correctly
substituted the Thunderbolt address for the actual `--rpc` target,
producing the exact command tonight's manual benchmark used, now fully
automatic. Then tested the fallback path directly with a synthetic peer
carrying a deliberately unreachable fast_path (`169.254.99.99`,
nothing listening there) and confirmed it correctly fell through to the
Tailscale IP instead of failing. Cleaned up the disposable test process
afterward.

Not yet live-tested through a real `--apply` agent cutover (same
caveat as the mDNS fallback work above) -- the logic is proven correct
in isolation and via dry run, not yet proven under actual launchd
supervision end to end.

## Live cutover attempt: real launchd run surfaced mDNS resolution ambiguity under launchd too

Went ahead with the live cutover (user: "let's do the next"). node-b:
swapped `com.caravan.rpc-server` for `com.caravan.agent` cleanly --
correctly self-detected tail role, spawned the identical `rpc-server
--cache` command as its own child (confirmed via `ps -o pid,ppid`), and
its `/health` correctly reported `fast_paths: ["169.254.72.237"]`
through the real (not disposable-test) agent.

node-a: bootstrapped `com.caravan.agent` for real -- and it fell back to
single-node again, but for a *new* reason this time, not the already-
known Tailscale-CLI-under-launchd issue (which is still present and
still logged, confirmed unrelated). The mDNS path failed too:
`_agent_health('node-b.local') failed: OSError(65, 'No route to
host')`.

Diagnosed rather than assumed: `node-b.local` is multi-homed --
`dscacheutil -q host` shows it resolves to *both* the Thunderbolt
link-local address (`169.254.72.237`) *and* node-b's LAN address
(`<node-b-new-lan-ip>`), plus several IPv6 addresses. Interactively, resolving
and connecting to that hostname happens to land on the working
Thunderbolt address and succeeds instantly (confirmed: `ping` and a
plain `socket.gethostbyname()` both picked `169.254.72.237` first, 0%
loss). Under launchd, the exact same hostname connection attempt landed
on something unreachable instead. This is the same "process context
measurably affects network behavior on this hardware" pattern
documented in `ARCHITECTURE.md`'s EHOSTUNREACH note and tonight's
Tailscale-CLI finding -- a third independent instance of it, not fully
explained mechanistically (same as the others), but now with a
consistent mitigation pattern across all three: don't trust one
ambiguous connection attempt from launchd's context, try explicit
candidates instead.

**Fix**: `_resolve_candidates(hostname)` resolves a hostname to *every*
IPv4 address it has (`socket.gethostbyname_ex`) instead of connecting to
the ambiguous hostname directly; `_agent_health_any(candidates)` tries
each in order, same pattern as `_select_best_address`'s fast-path
selection, just applied one level earlier at the initial peer-liveness
check itself. Wired into `discover_peers`'s mDNS branch; the peer's
recorded `"ip"` is now always a real resolved address that actually
answered, not the ambiguous hostname string it used to be.

Verified directly against the real failure before redeploying:
`_resolve_candidates('node-b.local')` returns
`['169.254.72.237', '<node-b-new-lan-ip>']`, and `_agent_health_any` correctly
picks the first one. Not yet re-verified live under launchd as of this
entry -- redeploying next.

## curl vs. Python socket under launchd -- the real fix

Redeployed the candidate-resolution fix above and re-tested live: still
failed, and worse than expected -- *both* resolved candidates
(`169.254.72.237` and `<node-b-new-lan-ip>`) failed with `OSError(65, 'No
route to host')`, including the Thunderbolt address that had just
worked fine moments earlier in an interactive test with the identical
code. Not a DNS ambiguity problem after all; something more fundamental
about *this specific launchd process* reaching that address at all via
Python.

Tested directly rather than theorizing further: built a throwaway
one-off launchd job (`/tmp/com.caravan.difftest.plist`, bootstrapped,
read its log, torn down) running a tiny script that tried both `curl`
(subprocess) and `socket.create_connection()` (Python's own stack)
against the same address, back to back, in the same process. Result:
**`curl` connected instantly; the Python socket call failed with the
exact same "No route to host"** -- in the same launchd context, same
moment, same target. This rules out a general network/routing block
(curl proves the path is fine) and points specifically at Python's
socket stack behaving differently under launchd on this hardware --
consistent with, but a new and more precise instance of, the "process
context measurably affects networking" pattern from `ARCHITECTURE.md`'s
EHOSTUNREACH note, the Tailscale-CLI-under-launchd finding, and the
mDNS-ambiguity investigation above -- now with an actual verified
mechanism (Python vs. curl) instead of an unexplained workaround.

**Fix**: `_agent_health()` now shells out to `curl` instead of using
`http.client`/`socket` -- same interface, same return type, just a
different transport underneath. Removed the now-unused `http.client`
import. Verified interactively first (still correctly returns the
health body for a reachable address and `None` for an unreachable one)
before redeploying live.

## The real limit: llama-server itself can't reach Thunderbolt under launchd, at all

With the curl fix, node-a's discovery finally worked correctly end to
end: `discovered 1 peer(s): mdns node-b.local 169.254.72.237`,
and the agent correctly built the full sharded command with the
Thunderbolt address selected (`--rpc 169.254.72.237:50052 --device
MTL0,RPC0 --tensor-split 1,1`) -- the auto-select-fastest-path feature's
own logic worked exactly as designed. But `llama-server` itself then
crash-looped: `ggml-rpc.cpp:547: Failed to connect to
169.254.72.237:50052` -> `ggml_abort`, repeatedly, every ~10s
(`supervise()`'s restart_delay).

Isolated methodically rather than guessing, stopping the crash loop
first (`bootout`, confirmed no orphan -- the SIGTERM-forwarding fix from
earlier tonight worked correctly here too):

1. Ruled out a real network/link problem: `ping`, `nc -zv`, and `curl`
   (against the health port) all succeeded against the exact same
   address, moments apart. Node-b's rpc-server was confirmed healthy
   and listening throughout.
2. Reproduced in complete isolation with a throwaway one-off launchd job
   running nothing but `subprocess.Popen([llama-server, --rpc,
   169.254.72.237:50052, ...])` -- same failure, ruling out anything
   specific to `caravan_agent.py`/`supervisor.py`'s own code.
3. Ran the *identical* script interactively (not via launchd) --
   succeeded. Confirmed via node-b's own rpc-server log, which showed
   real `[set_tensor] saved to ...` lines and live Metal kernel
   compilation while that process was up, not just a healthy-looking
   PID.
4. Ran the identical launchd-Python-subprocess pattern again, this time
   targeting the Tailscale IP (`<node-b-tailscale-ip>`) instead of Thunderbolt --
   succeeded. Isolates the failure to the Thunderbolt link-local address
   specifically, not "launchd grandchild processes can't make RPC
   connections" in general.
5. **The decisive test**: had launchd spawn `llama-server` *directly*,
   no Python involved at all -- a throwaway copy of the real, always-
   proven `com.caravan.llama-server.plist` with only the `--rpc` IP
   swapped to Thunderbolt. **Still failed**, identical error. This rules
   out Python/subprocess.Popen as the cause entirely: it's launchd
   itself (of any kind, direct or via a Python grandchild) that can't
   reach this specific address, full stop.

Best-supported explanation, not yet proven with source-level certainty:
`ggml-rpc.cpp`'s `socket_t::connect()` (`transport.cpp`) resolves the
target via the legacy `gethostbyname()` API before calling raw
`::connect()`. Every *working* case in this investigation (curl reaching
the same IP under the same launchd context; `is_agent_alive`'s own curl
call) goes through a modern `getaddrinfo()`-based resolver internally.
macOS's network sandboxing for non-interactive/background processes is
documented to sometimes treat legacy resolver APIs differently than
modern ones -- consistent with, and a more precise instance of, this
hardware's now four-times-observed "process context affects networking"
pattern (`ARCHITECTURE.md`'s EHOSTUNREACH note, the Tailscale-CLI
finding, the mDNS-ambiguity finding, and this one) -- but this is the
first one where the actual API-level distinction (legacy resolver vs.
modern resolver) is a concrete, plausible mechanism rather than an
unexplained workaround.

**Practical consequence**: `llama-server`, launchd-supervised, currently
cannot use the Thunderbolt link-local address at all -- only an
interactively-spawned process can (confirmed: tonight's original manual
benchmark, run via a plain background shell process, worked perfectly).
The auto-select-fastest-path feature's own logic is fully correct and
verified; what's blocked is llama-server actually being able to use what
it correctly selects, once under real process supervision. Not
fixable from Caravan's own code -- would need a patch to
`ggml-rpc.cpp`'s `socket_t::connect()` (swap `gethostbyname()` for
`getaddrinfo()`), which is real llama.cpp-side C++ work, not something
to take on mid-investigation tonight.

**Reverted node-a to the proven manual `com.caravan.llama-server` plist**
(Tailscale IP, known to work fine under launchd) rather than leave it
crash-looping or stuck on single-node. node-b's agent cutover is
unaffected and stays live -- the tail role never tries to reach
Thunderbolt itself, only the head does. Cleaned up all throwaway test
plists/scripts (`/tmp/com.caravan.difftest.plist`,
`com.caravan.spawntest.plist`, `com.caravan.directtest.plist` and their
logs) -- nothing left behind.

## The actual root cause: macOS Local Network permission, not a code bug at all

User's follow-up question reframed the plan: "unified app" meant the
already-decided submodule + patch-branch vendoring (see the earlier
"single unified app" entry), not a full Go/Rust/Swift rewrite -- so
patching llama.cpp and building the unified app aren't competing options,
the patch just needs to happen *in* the vendored fork rather than as a
one-off edit. User then raised a real, deeper version: not just vendored
source, but llama.cpp linked as a library in one Caravan binary with no
subprocess spawning at all. Corrected an overclaim from earlier in that
discussion: eliminating the subprocess boundary would *not* have avoided
this bug -- the decisive test in the previous entry already proved a
*direct* launchd-to-llama-server spawn (no Python, no subprocess chain)
fails identically, so a unified binary would hit the same wall.

Set up the vendoring infra first: forked `ggml-org/llama.cpp` to
`RookiOS72/llama.cpp` (`gh repo fork`), renamed the original `origin` to
`upstream`, added the fork as the new `origin`, created a `caravan-patches`
branch off the pinned known-good commit (`6a1a922`, same commit both
nodes have been running all night).

**Wrote and tested the getaddrinfo() patch -- it did not fix the issue.**
Replaced `gethostbyname()` with `getaddrinfo()` in
`transport.cpp`'s `socket_t::connect()`, matching the file's own existing
helper-function style (`is_valid_fd`, a new `close_fd` alongside it).
Rebuilt, confirmed via `nm -u` that the library now actually links
`getaddrinfo` not `gethostbyname`. Retested the exact same decisive
launchd-direct-spawn scenario from the previous entry: **failed
identically, twice**. This disproved the leading hypothesis -- and
exposed a real reasoning gap worth naming: Python's own
`socket.create_connection()` already uses `getaddrinfo()` internally (has
for years), so the earlier "Python socket vs. curl" test was *already*
comparing two getaddrinfo-based paths. The resolver-API theory should
have been caught as wrong before ever writing the patch, not after
testing it.

**Real root cause, found by asking the user to check something only
visible in the GUI**: macOS's Local Network privacy permission
(Settings -> Privacy & Security -> Local Network). A permission dialog
had been firing on every test tonight -- invisible over a remote shell,
never seen or answered. `llama-server` itself isn't listed there at all
(an unsigned, ad-hoc raw CLI binary apparently doesn't get its own
trackable entry), but "Terminal" and "Python" are, and both were already
toggled on. Confirmed that alone wasn't sufficient: a direct
launchd-spawned `llama-server` (no Python parent) still failed even with
both toggled on -- consistent with it having no grantable identity of
its own to inherit from. The decisive confirmation: spawning
`llama-server` *as a child of Python* (subprocess.Popen, exactly how the
real agent does it) succeeded immediately -- real generated content,
confirmed via an actual `/completion` call, not just a healthy PID. macOS's
Local Network grant propagates from a permitted parent process to its
children; a bare launchd-direct child has no such parent to inherit
from. This is presumably the actual mechanism behind all four "process
context affects networking" findings tonight, not four separate causes.

**Caveat, not yet isolated**: the successful test ran with the
getaddrinfo-patched binary already built and deployed -- whether
`gethostbyname()` alone would now also succeed with the permission
granted was never re-tested in isolation, since doing so would mean
another rebuild/restart cycle purely to satisfy that question rather
than fixing anything. The patch stays in place: it's deployed, working,
and a legitimate modernization on its own merits (a live syscall vs. a
deprecated 1980s-era API) even if it turns out not to have been
strictly necessary.

**Live-verified the real production path end to end**: cut node-a back
over to `com.caravan.agent` for real. It correctly discovered node-b via
the mDNS-with-curl-fix path, auto-selected the Thunderbolt address for
`--rpc` (the auto-select-fastest-path feature from earlier tonight,
finally exercised for real under launchd), and `llama-server` loaded and
served a real completion -- `predicted_per_second: 6.09`, matching the
original manual Thunderbolt benchmark's 6.1 tok/s almost exactly. This
is the first time tonight the entire chain -- agent discovery, fast-path
selection, and llama-server's actual connection -- has worked together
under real process supervision, not a manual workaround.

## Unified binary v0: proved llama.cpp's own library calls work in-process

Step 2's first milestone: prove the core "no subprocess" idea before
porting any of `agent/`'s discovery/health/supervision logic. Checked
the actual entry points before writing anything (`tools/server/main.cpp`
is literally `return llama_server(argc, argv);`; `ggml-rpc.h` exports
`ggml_backend_rpc_start_server(...)` as a real public API) -- both roles
have clean, already-proven, directly linkable entry points, not
something to reimplement.

New `cpp/` directory: `CMakeLists.txt` linking against the existing
`~/dev/llama.cpp` build (proper submodule vendoring deferred until this
was proven worth it), `main.cpp` porting `ollama_store.py`'s model-
detection logic to C++ (using the JSON library already vendored inside
llama.cpp itself, `vendor/nlohmann` -- no new dependency), then
dispatching to whichever role's library call applies.

One real bug caught immediately by testing rather than trusting the
diff: declared `llama_server` as `extern "C"`, matching how a C library
function normally gets declared -- linker failure. It's a plain C++
function (confirmed by the mangled symbol name `_Z12llama_serveriPPc`
seen in tonight's earlier crash backtraces); `tools/server/main.cpp`
itself declares it with no `extern "C"`. Fixed by matching that.

**Both roles verified live, not just "it compiles":**

- Head: ran single-node (no peer) on a scratch port. `/health` came up
  correctly inside `caravan`'s own process. A real completion request
  hit a genuine Metal OOM (`kIOGPUCommandBufferCallbackErrorOutOfMemory`)
  -- expected, not a bug: this is the full 30B model on one 24GB
  machine, competing with the real production process's own GPU memory
  at the same time. This model is normally sharded specifically because
  one node can't comfortably hold it alone.
- Tail: built and ran on node-b (which genuinely lacks the model
  locally, so correctly self-detects tail), on a scratch port. A real
  TCP connection succeeded against it (`nc -zv` over the Thunderbolt
  link).
- Confirmed via `ps -ef` during both tests: only `caravan` itself ever
  existed as a process. No `llama-server`/`rpc-server` child, on either
  node, at any point.

Both roles' test ports reverted to the real production values (8080,
50052) before committing -- the scratch ports were only to avoid
colliding with the live production processes during testing.

**Not built yet, and said plainly rather than implied**: mDNS/Tailscale
discovery, the health server + `fast_paths` reporting, auto-select-
fastest-path, persistent identity -- everything `agent/` already does.
This milestone answers the one question that mattered before committing
to porting all of that: do the library calls actually work standing
alone, in-process. They do, for both roles, verified live.

## Unified binary v0.1: mDNS self-discovery, replacing the hardcoded --peer

Next obvious step after v0: port `agent/discovery/mdns.py` so `caravan`
can find its own peer instead of needing `--peer` passed by hand.

Two new small modules: `subprocess.{h,cpp}` (a POSIX fork/exec/pipe/poll
utility -- `dns-sd -B`/`-L` stream forever with no "give me one result
and exit" flag, same reason the Python version needed its own
`_run_timeboxed`) and `discovery_mdns.{h,cpp}` (a direct C++ port of the
Python module: same `dns-sd` CLI, same two regexes translated to
`std::regex`, same browse-then-resolve-then-advertise shape).

Hit the exact same stdout-buffering issue as the rest of tonight's
Python work, just in C++ this time: `printf` sits in libc's buffer
indefinitely once stdout isn't a tty. Fixed with `setvbuf(stdout,
nullptr, _IONBF, 0)` at the top of `main()` -- the C equivalent of
tonight's repeated Python `-u` fix.

**Verified live, not just compiled**: ran `caravan` standalone (scratch
local port to avoid the real 8080). It correctly advertised itself,
discovered *both* itself and the real node-b peer via mDNS, and
correctly excluded itself from selection (`normalize_hostname` -- the
same self-discovery bug the Python port hit first, caught here before
it ever ran for real by porting the fix at the same time as the
feature). Built the exact same head command production long ago proved
correct, fully automatically: `--rpc node-b.local:50052
--device MTL0,RPC0 --tensor-split 1,1`. `--peer` is no longer required
at all, just kept as a manual override.

**Real mistake, caught and verified harmless rather than assumed**:
only the local `llama_server_port` had been overridden for the test --
the discovered peer's RPC port was still the real production value
(50052), so this test connected to node-b's actual live `rpc-server`
instead of a scratch one. Realized this immediately from the printed
args, killed the test right away, then verified rather than hoped:
production's `/health`, `/slots`, and a real `/completion` request all
still worked correctly afterward, node-b's `rpc-server` PID was
unchanged (no crash/restart), and its log showed only a clean "Client
connection closed" from the killed test -- a harmless connect/disconnect,
not a request that actually touched the shared session. Lesson for next
time: override *both* the local bind port and route test traffic to a
scratch port on the peer's side too, not just the local one.

Also verified the signal-handler cleanup path works: killing `caravan`
correctly terminated its `dns-sd -R` advertiser child (checked via `ps`
for the specific child pid) rather than leaking it -- the same
orphaned-child risk `agent/supervisor.py`'s SIGTERM-forwarding fix
addressed earlier tonight, ported to this binary's shutdown path too.

Synced to node-b and confirmed it builds there too (the discovery code
is role-agnostic -- proven once, on the head-role path here; both roles
share the exact same `discovery_mdns` code, not two implementations).

## Full real end-to-end test: caravan.cpp as head and tail together, in production

User turned exo off on both machines and explicitly greenlit testing
against real production ports. Did the test that mattered most: `caravan`
as head on node-a *and* tail on node-b, at the same time, on the real
production ports (8080/50052), zero Python agent running on either
side.

Stopped both `com.caravan.agent` instances first (node-a, then node-b,
same safe order as every other cutover tonight), confirmed no orphaned
`llama-server`/`rpc-server` children on either side. Real gotcha caught
immediately rather than after the fact: both nodes' `cpp/build/`
directories had been `rm -rf`'d as part of earlier repo-sync cleanup and
never rebuilt -- `nohup ./build/caravan` failed with "No such file or
directory" on the first attempt. Rebuilt on both, then proceeded.

Started tail (node-b) first so it was listening before head connected --
confirmed live via `nc -zv` against the Thunderbolt address before even
starting node-a. Started head (node-a) second: it discovered *both*
itself and node-b via mDNS, correctly excluded itself, and built the
full sharded `llama_server()` argv automatically -- `--rpc
node-b.local:50052 --device MTL0,RPC0 --tensor-split 1,1`, the
exact production shape, entirely self-organized.

**It worked completely.** Loaded in under 30 seconds -- genuinely
worth pausing on, since this is a *different* binary than the one that
needed the Local Network permission grant earlier tonight (that fix was
specific to the Python-spawned `llama-server` process; `caravan` is
its own separate executable, so this wasn't guaranteed to inherit
anything). No connection error at all. `kv_unified='false'`,
`n_ctx_slot=65536` on all 4 slots, `/health` ok, and a real
`/completion` request returned genuine generated text at
`predicted_per_second: 6.03` -- matching the original manual Thunderbolt
benchmark (6.1 tok/s) and tonight's earlier Python-agent Thunderbolt
test (6.09 tok/s) almost exactly. Three independent measurements now
agree.

This is the full vision from tonight's "unified app" conversation
actually working, live, together, for the first time: one binary, no
subprocess anywhere, self-discovery with no manual `--peer`, correctly
routed over the fastest available link, real inference at the expected
speed. Not yet production-grade (no Tailscale fallback, no `--cache`,
no crash supervision, no persistent identity) -- deliberately reverted
back to the full-featured Python agent for actual production use
afterward, confirmed restored and healthy with a real completion. This
was validation, not a production swap.

Both `caravan` processes and their `dns-sd` advertiser children
confirmed cleanly killed afterward -- no orphans, no leftover mDNS
registrations.

User: no need to revert to the Python agent after every test going
forward -- only if/when actually needed at the end of a session. Noted;
stopped doing the revert-and-restore cycle after each individual test
from here on.

## Unified binary: Tailscale discovery (address-upgrade only, not an independent trust source)

Ported `agent/discovery/tailscale.py` to C++ next: new
`discovery_tailscale.{h,cpp}`, same App-bundle-then-PATH binary lookup,
same `status --json` call via the existing `subprocess::run_timeboxed`.

Real design decision, not just a straight port: there's no health
server yet in the C++ binary (see `agent/health_server.py` for the piece
this doesn't have yet), so there's no way to independently verify a
Tailscale peer is actually running Caravan rather than some other
machine on the same tailnet -- the exact gap `is_agent_alive()` exists
to close in the Python agent. Rather than reopen that trust hole, wired
Tailscale in as an *address upgrade* for peers mDNS already validated
(matches `ARCHITECTURE.md`'s stated Tailscale-over-LAN preference)
rather than as an independent discovery source. Verified this is the
right call live: real tailnet output included an unrelated machine
(`mgmt-host`, the same one that showed up as a false positive in the
original Python agent testing) -- correctly *not* trusted, since it was
never found via mDNS.

**Real bug, caught by testing rather than trusting the diff**: first
version segfaulted (exit code 139) every time, deep inside the peer-
iteration loop, before printing anything. Debugged properly rather than
guessing -- `lldb` kept timing out non-interactively (batch mode not
behaving as expected, abandoned after two attempts rather than fighting
it further), so added temporary `fprintf(stderr, ...)` diagnostics at
each step instead and rebuilt incrementally. Narrowed it to the very
first loop iteration, before it could even print which key it was on.

Root cause: `for (const auto & [key, peer] : data.value("Peer",
json::object()).items())` -- a well-documented `nlohmann::json` pitfall.
`.items()` returns a proxy holding a *reference* to the json object it
was called on; `data.value(...)` returns a *temporary*. That temporary
is destroyed once the full expression finishes evaluating, before the
loop body ever runs -- the proxy is left holding a dangling reference,
and iterating it is undefined behavior. Fixed by binding the
intermediate value to a named variable (`json peer_map = data.value(...)`)
first, which keeps it alive for the loop's actual duration, then calling
`.items()` on that. Verified the fix directly: real Tailscale JSON
(7027 bytes, 3 real peers including the online/offline and unrelated-
machine cases) parsed and iterated correctly, no crash, and the address-
upgrade logic worked exactly as designed.

Also cleaned up leftover `dns-sd -R` processes from the crashed test
runs -- each crash skipped the normal SIGTERM-handler cleanup path
(`_exit`-on-segfault doesn't run application signal handlers), so those
had to be killed by hand rather than relying on the usual shutdown path.
Confirmed the real production advertiser (a different pid, still
running the whole time) was left untouched.

Builds clean on both nodes.

## 2026-10-30: configurable target model + stale slot-file cleanup

Two gaps found while auditing node-a's disk:

- **~154 GB of disk KV slot files** in `~/.caravan/llama-server/slots/`
  (269 x ~1 GB `.bin`, all from Sep 6-18). The proxy saves one per
  session fingerprint after every reply (issue #4) and nothing ever
  removed them. New `proxy/slot_cleanup.py`: removes (or archives) slot
  files whose mtime is older than N days (default 30), and forgets those
  fingerprints in `session_slots.json`. The proxy runs it at startup and
  every 6h on a daemon thread; removals happen while holding the FIFO
  gate (every save/restore runs inside a request that holds it), and
  each file's mtime is re-checked under the gate so a session that just
  came back isn't touched. Mapping entries are dropped on the live
  `SessionSlotAssigner` (new `forget()`), not by editing the JSON, or
  the next save would write them back. Standalone CLI with `--dry-run`.
- **Hardcoded `TARGET_MODEL = "muse-glimmer"`.** Now resolved
  `--model` > `CARAVAN_MODEL` > `~/.caravan/config.json` `"model"` >
  `muse-glimmer`. `ollama_store.py` also handles namespaced / `hf.co`
  model names and doubles as a CLI that resolves a name to its blob
  path, for regenerating the llama-server plist's `-m` argument. The C++
  binary (`cpp/main.cpp`) still hardcodes the model -- not changed here.

Tests: `tests/` (stdlib unittest, temp dirs), passing on 3.13 and 3.9.

## 2026-10-30 (later): performance pass on the proxy and llama-server flags

Thirteen items from a performance review, all configurable with the
usual precedence (flag > env > `~/.caravan/config.json` > default).
Nothing was restarted; the running services pick these up only on their
next (re)start / re-bootstrap.

Proxy (`proxy/slot_pin_proxy.py`):

1. **Fewer slot saves.** A ~1 GB save after every reply, inside the FIFO
   gate, delayed the next queued request. Now skipped when `GET /slots`
   shows the slot's token count unchanged since that session's last
   save/restore; `--slot-save-every N` thins saves to every N turns
   (default 1 = old behavior); optional idle saver
   (`--slot-idle-save-seconds`, off by default, ~60 suggested) moves
   saves off the response path and takes the FIFO gate so it can't race
   a request/restore. Unsaved sessions are flushed before eviction.
2. **Streaming.** `read(4096)` waited for 4 KB per write, making SSE
   bursty; now `read1()`. Framing fix: http.client de-chunks upstream
   and the proxy stripped `Transfer-Encoding`, so streamed responses went
   out on a keep-alive connection with no length and no chunking. Now
   re-chunked for HTTP/1.1 clients (keeps keep-alive), `Connection:
   close` for HTTP/1.0, Content-Length passed through when upstream sent
   one.
3. **Prompt-style fingerprints.** `/completion` and `/v1/completions`
   previously fell back to a whole-body hash: a new fingerprint, slot
   and disk save on every call. Now: hash of the first 2048 chars of the
   prompt (configurable); shorter prompts are unpinned one-shots, never
   saved. Chose prefix fingerprinting over always skipping because a
   growing raw-prompt conversation keeps its prefix and benefits from
   the slot cache like chat does.
7. **LRU slot assignment** instead of round-robin; state file now holds
   occupant + last-used per slot (v2; the old format still loads).
8. **No restore over a warm slot** (e.g. after a proxy-only restart).
11. **Slot count** from `--n-slots` / `CARAVAN_N_SLOTS` /
    `llama_server.n_slots` (shared with the agent).
12. Removed the per-request `GET /slots` idle check (FIFO already
    serializes; llama-server defers a task for a busy slot) and the TEMP
    debug block that logged a system-prompt hash and message previews.

llama-server flags (`agent/config.py`, `agent/supervisor.py`,
`launchd/com.caravan.llama-server.plist`, new
`agent/render_llama_plist.py`):

4. `-fa on` (was llama.cpp's `auto`).
5. `-ctk q8_0 -ctv q8_0` (half the KV memory of f16). Old slot files
   won't restore after the switch.
6. `--cache-ram 0` (llama.cpp default 8192 MiB; duplicate of what
   Caravan's slot pinning + disk persistence already does, and copied
   every idle slot on each new task). Chose 0 over 1024 since even 1 GiB
   holds less than one full slot of q8_0 KV and gets copied into on every
   task.
9. Fallback `--rpc` changed from Tailscale `<node-b-tailscale-ip>:50052` to
   node-b's Thunderbolt-bridge link-local `169.254.104.38:50052`
   (node-a's en2: 169.254.4.161). Link-local, so it can change;
   `render_llama_plist.py --rpc auto` derives it via discovery instead.
10. `-ngl 999` explicit.
13. `-b 2048 -ub 512` explicit and configurable (unchanged defaults).

Not validated yet (needs a restart and a benchmark): flash attention
across the RPC backend, q8_0 KV speed/quality on this model, and any
`-ub` above 512. Flags were checked against the caravan-patches fork's
`common/arg.cpp`. `cpp/main.cpp` unchanged.

Tests: `tests/test_proxy_perf.py` (fake llama-server on localhost:
streaming/framing, save skipping, save-every-N, idle saver, eviction
flush, warm-restore skip, LRU, fingerprints) and
`tests/test_llama_settings.py` (settings precedence/validation, command
flags, committed plist == `build_head_command()` output, render tool).

## 2026-10-30: docs overhaul for the public repo

The repo moved to [github.com/linuxbren/caravan](https://github.com/linuxbren/caravan).
It's public but unannounced, so the docs were rewritten for readers who
weren't there:

- `README.md` is now a public introduction: what Caravan is and why, the
  hardware, measured numbers (only ones recorded in this log), how it
  works, requirements, quick start, the full configuration reference
  (flag > env > `~/.caravan/config.json` > default), operations, known
  limitations, and the status (early, unreleased, experimental).
- `docs/ARCHITECTURE.md` now describes what's actually built. Discovery
  picks the fastest live path (Thunderbolt, then Tailscale, then LAN)
  instead of always preferring Tailscale. The agent passes
  `rpc-server --cache`. New sections cover the proxy and the C++ binary.
- `agent/README.md`, `launchd/README.md` and `docs/PLAN.md` updated to
  match the code. The launchd README now covers the agent plist and the
  Local Network permission, and notes that `CARAVAN_PINNED_SLOT` in the
  proxy plist is ignored.
- Personal details removed from docs and code comments: LAN and
  Tailscale IP addresses and machine hostnames in this log are now
  placeholders (`<node-b-lan-ip>`, `<node-b-tailscale-ip>`, `node-b`,
  `mgmt-host`); old repo URLs point at the new location. Thunderbolt
  link-local (169.254.x.x) addresses are kept, since they're
  self-assigned and only meaningful on the cable. Still machine-specific:
  absolute `/Users/...` paths in the launchd plists and the
  `scripts/restart-rpc-server.sh` defaults (override with
  `CARAVAN_NODE_B_HOST` / `CARAVAN_NODE_B_USER`).

## 2026-10-30 (evening, v1): improvements 1–3 measured (rebased llama.cpp, MLX step a, auto KV)

All runs were on one Mac mini (M4, 24 GB), using test ports (llama 8180, proxy 8190, mlx 8192) and the same three models as the runtime compare. Scripts are in `bench/improvements/`.

- **llama.cpp rebased** onto upstream `5047748f`, with one Caravan patch re-applied: getaddrinfo in the RPC connect. There was one conflict, in ggml-rpc transport.cpp, where the getaddrinfo version was kept. The rebase brings in upstream #26004, which stores context checkpoints in the slot file. Resume after a restart (16k chat, wait for the first token):

  | model | old build | rebased | old + `--swa-full` |
  |---|---|---|---|
  | GPT-OSS | 46.3 s | **0.65 s** | 0.59 s |
  | Gemma 4 | 56.1 s | **0.93 s** | 0.48 s |
  | Qwen3 (no SWA) | 1.18 s | 1.10 s | — |

  Raw prefix with a divergent tail after a restart: GPT-OSS 49.2 → 2.23 s, Gemma 59.3 → 2.59 s. `--swa-full` on the old build failed this case for GPT-OSS (51.2 s). Gemma slot files grow from 291 MB to 849 MB with checkpoints.
- **Auto KV.** The Metal recommendedMaxWorkingSetSize on an M4 24 GB is 18186.25 MiB. Decisions:
  - Gemma 4, 2×18k: f16 (estimate 18058 MiB, the tightest case, ran fine).
  - GPT-OSS: f16 (14406 MiB).
  - Qwen3: q8_0 (f16 would need 19097 MiB).

  Same-session speeds in tok/s (v0 = 45ed2c2 + old build, q8_0 → rebased + q8_0 → v1 = rebased + auto):

  | model | tg128 | pp512 | pp4096 | pp @16k | tg @16k | peak RSS |
  |---|---|---|---|---|---|---|
  | GPT-OSS | 35.9 → 37.1 → 37.1 | 374.7 → 434.0 → 436.8 | 403.0 → 452.3 → 453.6 | 237.3 → 258.6 → 256.6 | 27.7 → 28.9 → 31.1 | 12.8 → 13.0 → 13.4 GB |
  | Gemma 4 | 34.4 → 34.8 → 36.7 | 333.9 → 383.5 → 399.9 | 354.9 → 377.8 → 379.7 | 211.0 → 226.4 → 231.5 | 25.9 → 25.8 → 27.5 | 16.4 → 16.7 → 18.4 GB |
  | Qwen3 (q8_0 either way) | 41.4 → 42.5 | 361.1 → 401.9 | 338.0 → 356.4 | 124.8 → 128.2 | 20.7 → 20.9 | 18.7 → 18.7 GB |

  Most of the reading-speed gain comes from the rebase. f16 mostly adds writing speed for Gemma and writing speed on long chats for GPT-OSS, and costs about 1.7 GB on Gemma. Quality was 3/3 on everything.
- **MLX step a** (mlx-lm 0.32.2, through the proxy; the proxy logs `backend=mlx … cache=mlx-noop`):

  | model | pp512 | pp4096 | tg128 | turn 2 (warm) | after restart |
  |---|---|---|---|---|---|
  | Gemma 4 4-bit | 427.2 | 383.8 | 39.8 | 10.8 s (no reuse) | 16.0 s |
  | GPT-OSS MXFP4-Q8 | 434.4 | 441.4 | 35.3 | 9.2 s (no reuse) | 12.7 s |
  | Qwen3 4-bit | 439.4 | 395.7 | 47.0 | **0.44 s** | 16.0 s |

  Notes:
  - The chat for this test is 4k tokens. "After restart" includes paging the weights in, because mlx loads lazily.
  - Qwen needed capped prompt-cache settings (`--prompt-cache-size` / `--prompt-cache-bytes`, settable through `mlx.extra_args`). Without them it ran out of Metal memory twice.
  - GPT-OSS returns raw harmony markup, so the bench sends back only the final channel.
  - Peak footprint: Qwen 19.0 GB, Gemma 18.6 GB, GPT-OSS 13.9 GB.
- Step b (MLX prompt-cache save/restore) had not started yet at this point; it became the v2 MLX worker (next entry).

## 2026-10-31 (v2): MLX per-session caches saved to disk, GPT-OSS reasoning cleanup, saved-chat cap

- **MLX step b: the Caravan MLX worker** (`agent/mlx_worker.py`, branch
  `caravan-v2-mlx-cache` off `improvements-1-3`, worktree `~/dev/caravan-v2`).
  Why mlx-lm 0.32.2 (still the latest release) reused nothing for Gemma 4 /
  GPT-OSS: `LRUPromptCache` stores the cache *after* generation (prompt +
  reply tokens); the next prompt re-renders the reply differently, and a
  wrapped `RotatingKVCache` can't be trimmed back, so every turn was cold.
  Every hit was also a deepcopy (Qwen's OOM). The worker prefills up to the
  last prompt token, snapshots the non-trimmable layers there, generates,
  then rewinds; that checkpoint is what's saved
  (`save_prompt_cache`, `<cache-dir>/<fingerprint>.safetensors`, the PR #1405
  idea) and loaded after a restart. All mlx work runs on one thread with its
  own stream (MLX streams are per-thread). The proxy sends
  `X-Caravan-Session`, asks the worker to restore before every MLX
  request (`warm` when the session is already in memory) and saves every
  `slot_save_every` turns; `slot_cleanup` ages out the `.safetensors`
  files (`mlx_dir`, archive to `archive_dir/mlx`).
- **GPT-OSS harmony parsing in the worker**: a marker state machine
  splits analysis/commentary (→ `reasoning_content` + `reasoning`) from the
  final channel (→ `content`), robust to markers split across pieces.
  Reasoning fields a client sends back are dropped before templating, so
  the history renders to the cached tokens (unit-tested).
- `--kv-bits 4|8` (QuantizedKVCache for full-attention layers) added and
  tried for Qwen3 at 16k: still Metal OOM (footprint 19.3 GB), and 4k
  reading got 15% slower (380 → 325 tok/s). Off by default.
- Bench: `bench/v2/` (results in `~/.caravan/bench-2026-10-31/v2/` on the
  bench Mac), test ports
  8190/8192, exo paused. v1 = `improvements-1-3` + mlx_lm.server.

  | MLX, v1 → v2 | Qwen3 4-bit | Gemma 4 4-bit | GPT-OSS MXFP4-Q8 |
  |---|---|---|---|
  | turn 2, 4k chat (wait for first word) | 0.44 → 0.56 s | 10.76 → 0.49 s | 9.16 → 0.50 s |
  | tokens re-read on turn 2 (4k) | (reused) → 46 | 4,034 → 36 | 4,041 → 32 |
  | turn 2, 16k chat | OOM → OOM | 55.1 → 0.72 s | 37.3 → 0.59 s |
  | after restart, 4k | 16.0 → 0.59 s | 16.0 → 0.64 s | 12.7 → 0.52 s |
  | after restart, 16k | OOM → OOM | 60.3 → 0.84 s | 40.7 → 0.59 s |
  | writing tg128 (tok/s) | 47.0 → 49.1 | 39.8 → 42.2 | 35.3 → 37.4 |
  | reading pp512 / pp4096 | 439 / 396 → 438 / 380 | 427 / 384 → 397 / 393 | 434 / 441 → 433 / 442 |
  | peak footprint (speed tests) | 18.97 → 18.71 GB | 18.6 → 18.41 GB | 13.93 → 13.72 GB |
  | peak footprint (16k chat) | 19.41 (OOM) → 19.38 (OOM) | 18.28 → 17.67 GB | 14.25 → 14.09 GB |
  | save file 4k / 16k | none → 433 MB / – | none → 299 / 573 MB | none → 109 / 412 MB |
  | quality | 3/3 → 3/3 | 3/3 → 3/3 | 3/3 → 3/3, content clean |

  GPT-OSS content in v1 carried `<|channel|>analysis…` markup; in v2
  `markup_in_content` is false on every turn, and a 4th turn whose history
  echoes `reasoning_content` back still hits (24 tokens re-read). Restore
  itself takes 0.01–0.13 s (warm page cache); the worker takes 6–9 s to
  start (eager load + warm-up) vs 1.6 s for mlx_lm.server.
- **llama.cpp path regression check** (v2 proxy, rebased build, same commands
  as v1's s-* / r-*-new): no regression.

  | llama.cpp path, v1 → v2 | Qwen3 | Gemma 4 | GPT-OSS |
  |---|---|---|---|
  | reading pp512 (tok/s) | 401.9 → 438.1 | 399.9 → 408.3 | 436.8 → 437.4 |
  | reading pp4096 (tok/s) | 356.4 → 366.5 | 379.7 → 404.9 | 453.6 → 453.9 |
  | writing tg128 (tok/s) | 42.5 → 43.0 | 36.7 → 37.1 | 37.1 → 37.3 |
  | 16k chat after restart (s) | 1.103 → 1.102 | 0.93 → 0.913 | 0.652 → 0.65 |

  The `~/.caravan/models/gpt-oss-20b.gguf` symlink points at a removed
  Ollama blob; `suite_v2_llama.sh` now defaults to the HF blob v1 used
  (`GPT_OSS_GGUF` overrides). Symlink left as is.
- **Per-Mini cap on saved chats** (`proxy/slot_cleanup.py`, from an X
  reply). After the age rule, the llama.cpp `.bin` slot files and the MLX
  `.safetensors` caches left over are counted together and held to
  `max_count` (default 200) and `max_gb` (default 50). Least recently
  used (oldest mtime) go first, in the same delete / archive / off mode,
  and each eviction gets its own log line. Never evicted: a session in a
  llama.cpp slot, with unsaved turns, or with a turn (llama.cpp or MLX)
  in the last `protect_minutes` (30). In the proxy that comes from
  `_active_sessions()`; the CLI uses the occupants in
  `session_slots.json`. Each file is re-checked under the FIFO gate (it
  must be unchanged and still inactive). If everything left is active,
  the cap is exceeded and that is logged. Settings: `--slot-max-count` /
  `--slot-max-gb` / `--slot-protect-minutes` (CLI `--max-count` /
  `--max-gb` / `--protect-minutes`), `CARAVAN_SLOT_MAX_COUNT` /
  `CARAVAN_SLOT_MAX_GB` / `CARAVAN_SLOT_PROTECT_MINUTES`, and
  `slot_cleanup.max_count|max_gb|protect_minutes` in config.json. There
  are 9 new unit tests.
  Exercised only on scratch copies of bench files in `/tmp/capdemo`
  (CLI archive run: 15 MLX caches, 1.15 GB, archived LRU-first under a
  0.8 GB cap. Proxy on test port 8190: 2 slot files evicted under a
  1-file cap, and the in-slot session kept although it was the oldest).
  Dry run on the bench Mac's real `~/.caravan/llama-server/slots`: it is
  empty today (0 files), so the defaults would evict nothing there. The
  269-file / ~154-165 GB backlog in the 2026-10-30 entry isn't on that Mac,
  and the other Mac was not checked or touched. By the
  numbers logged then, the 30-day age rule alone already covers all of
  it (Sep 6-18). The cap alone (age rule off) would keep the newest
  ~50 GB (~80-90 files) and evict ~180-190 files / ~105-115 GB.
- **Limits still open (MLX):** Qwen3 30B at 16k doesn't fit in either
  version (16.4 GB weights + ~3.2 GB KV; kv8 doesn't save it); the worker
  starts 6–9 s vs 1.6 s; Gemma short-prompt reading is ~7% slower (~8% in the v2.1
  side-by-side run);
  every one-turn request also writes a small save file (cleanup ages them
  out); restore was measured on a warm disk, not a cold one.
- Next: two-Mac MLX split, then per-model profiles, proxy overhead,
  memory headroom, cold-disk restore.

## 2026-10-31 (v2.1): wired limit held from startup, optional deferred first save

- **Wired limit at startup.** The MLX worker now raises the Metal wired
  limit to the recommended working set once, right after load, and holds
  it (`wired limit 0 -> 19069665280 bytes` in the log on the 24 GB Mini),
  like mlx_lm.server. v2 wrapped each request's prompt reading in
  `mlx_lm.generate.wired_limit()`, so the limit went up and back down
  around every request. New flag `--wired-limit startup|per-request|off`
  (default startup; per-request reproduces v2). 5 new unit tests with a
  fake mx check the limit is set once and never touched per request.
- **Optional deferred first save.** `CARAVAN_MLX_SAVE_MIN_TURNS` /
  `--mlx-save-min-turns` / `proxy.mlx_save_min_turns` (default 1, no
  change). With 2, one-message requests are not saved; a session's 2nd
  turn saves everything. 2 new tests.
- **A/B in one session** (bench/v2.1/ab_bench.py, 07:15-07:33 CDT): every
  variant restarted fresh per round, rotated order, test ports only.
  Qwen3 30B (3 rounds x 2 = 6 runs per size), tok/s, median:

  | | v1 mlx_lm.server | v2 | v2.1 | v2.1 + save-min-turns 2 |
  |---|---|---|---|---|
  | 4k read (min-max) | 395.9 (385-397) | 393.4 (380-398) | 395.6 (390-399) | 396.4 (386-399) |
  | 512 read, 1st after a 4.7k chat | 436 | 380 | 387 | 386 |
  | 512 read, next | 441 | 438 | 439 | 434 |
  | peak footprint / min free | 18.8 GB / 16% | 18.7 GB / 17% | 18.7 GB / 17% | 18.8 GB / 17% |

  Swap: 1.04 GB used before the run, 1.45 GB max during it, 1.08 GB after.
  Measured side by side, the 4k gap from yesterday's runs (396 vs 374-390)
  is gone even for unchanged v2, so it was mostly drift between days. The
  wired limit made v2.1 a little steadier (lowest run 390 vs 380), but the
  medians are within noise. Skipping the first save changed nothing,
  because a 4k save takes 0.10 s (399 MB) when the disk cache is warm.
  The slower first 512 read after a big chat (~0.15 s) happens with or
  without saves; it is likely evicting the previous session from memory
  (prompt-cache-size 1).
- Gemma 4 / GPT-OSS (1 round x 3): v2.1 = v2 (Gemma 4k 375.5 vs 376.4,
  512 397 vs 396; GPT-OSS 4k 415.4 vs 415.4). Both trail v1 on Gemma in
  this session (4k 383, 512 430), so the Gemma short-prompt gap (~8%) is
  real and not fixed by the wired limit. GPT-OSS: v1 418/429 vs v2.1
  415/424.
- Restart resume (Qwen, 4k, v2.1): t1 cold 11.6 s, t2 0.72 s, restart
  9.7 s, t3 0.52 s (re-read 31 of 4377 tokens), t4 0.53 s.
- Commit b9ebeb7 on `caravan-v2.1`. Version summary and roadmap:
  [ROADMAP.md](ROADMAP.md).

## 2026-10-31: docs rewritten from the v2.1 code

The README and every doc were written again from scratch against the code
on `caravan-v2.1`, since the earlier ones still described the GGUF-only
setup and said nothing about MLX:

- `README.md`: what Caravan is and why, features, the two backends, quick
  start, measured headline numbers, status.
- New `docs/CONFIGURATION.md` (every flag, env var and config key, with
  defaults and a warning about cleanup's delete mode), `docs/MLX.md` and
  `docs/BENCHMARKS.md` (method and the per-version tables).
- `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` rewritten. `docs/PLAN.md`
  removed: its stage history is now in ARCHITECTURE ("How it got here")
  and ROADMAP ("Done").
- This log: the bench Mac is no longer named, and three statements were
  corrected to match the code (MLX restore runs before every request, the
  save setting is `slot_save_every`, and the README no longer lists the
  Qwen cache caps, so the entry names the flags).
- Known gap recorded in the roadmap: the rebased llama.cpp branch that the
  v1+ numbers depend on isn't published on the fork yet.

## 2026-10-31: llama.cpp fork moved to linuxbren/llama.cpp

The llama.cpp fork now lives at
[github.com/linuxbren/llama.cpp](https://github.com/linuxbren/llama.cpp),
next to Caravan. Its branches:

- `caravan-patches` = `86e16204`: upstream `5047748f` plus the getaddrinfo
  RPC patch. This is the rebased build that the v1, v2 and v2.1 numbers
  were measured on. Until now it existed only on the Mac.
- `caravan-patches-rebase-2026-10-30`: the same commit, under its
  original name.
- `caravan-patches-v0` = `2f26123e`: the old base plus the same patch,
  used for the v0 benchmarks.

The README, ARCHITECTURE, ROADMAP, BENCHMARKS, `cpp/README.md` and
`bench/improvements/README.md` now point at `linuxbren/llama.cpp`,
branch `caravan-patches`. The "published branch is the older base" notes
are gone, and roadmap item 1 (publish the rebased branch) is done. The
earlier entries in this log that name the old `RookiOS72/llama.cpp` fork
are left as they were written. On the bench Mac, `~/dev/llama.cpp` has a
`linuxbren` remote for fetching; its `origin` is unchanged.

## 2026-10-31: v3, one MLX model split across two Macs

Branch `caravan-v3-mlx-split` (off `c026359`, not pushed, not merged).
Design note: [MLX-SPLIT.md](MLX-SPLIT.md). Numbers:
[BENCHMARKS.md](BENCHMARKS.md#v21-vs-v3-one-mac-vs-two-macs-oct-31-mlx).

- **Why our own pipeline.** `mx.distributed`'s ring backend failed over
  Thunderbolt on messages of 2 MB and up; jaccl (RDMA) needs Thunderbolt 5;
  mlx-lm's pipeline sharding only covers Qwen3. So v3 splits by layers
  itself: the packer Mac runs the embeddings and layers 0..K-1 and sends
  the hidden state over one TCP connection; the lead Mac runs the rest,
  samples, and serves the HTTP API. Protocol `caravan-split-1`.
- **Chat memory on both halves.** Each stage keeps its own per-session
  cache, in lockstep, and saves it to its own disk. A restore needs both
  halves or neither. The lead notices a restarted packer (new epoch) and
  re-reads instead of trusting stale state.
- **Results (one session).** Memory per Mac roughly halves; Qwen3 30B now
  holds a 16k chat on MLX. Writing is 28–42% slower and reading 16–25%
  slower. Each half costs 16–24 ms per token, almost what the whole model
  cost on one Mac, while the cable adds under 1 ms and 5–10 KB per token.
  So the remaining cost is per-pass overhead (parked: overlap the halves,
  compile the stage graphs).
- **Bigger brothers.** The 8-bit versions all run split with a 16k chat:
  Qwen3 30B 8-bit at 18.1 GB per Mac (20.6 tok/s), Gemma 4 26B 8-bit at
  15.6 GB (18.1 tok/s), GPT-OSS 20B 8-bit at 12.1 GB (19.8 tok/s); 3/3
  each, none fits on one Mac. GPT-OSS 120B doesn't fit two Macs with chat
  room even at 2-bit (36.6 GB, ~18.3 GB per Mac), so it's parked. Qwen3.6 35B-A3B 5-bit runs but re-reads the whole
  chat every turn (hybrid attention; parked).
- **Split download (prototype).** `agent/mlx_split_fetch.py` reads
  `model.safetensors.index.json` and fetches only this stage's shard
  files plus config and tokenizer. Qwen3 30B 8-bit: lead 16.65 GB, packer
  21.09 GB, instead of 32.44 GB each. The worker refuses to start a stage
  whose shards are missing.
- **How the packer gets its weights today.** MLX v3: each Mac loads from its
  own local copy, and each stage only reads its own layers' weights (lazy
  load). The copies get there either by a full download per Mac, by a
  one-time copy over the cable from the other Mac, or (new) by the split
  download. Nothing is streamed from lead to packer at load time.
  llama.cpp (GGUF): the lead needs the whole GGUF on disk and sends the
  packer's tensors over RPC at load; with `rpc-server --cache` (our build
  has it, and the packer plist uses it) the packer keeps them on disk by hash,
  so only the first load crosses the wire.
- **Fixes along the way.** Qwen3.6 (`qwen3_5_moe`) built its cache by
  walking all layers after the other stage's layers were dropped; the
  stage now builds a prototype cache first and copies it.

## 2026-10-31: naming: lead, packers, string

- Renamed the roles in a split: the **lead** is the Mac you talk to (API,
  last layers, picks each token); the **packers** are the other Macs,
  numbered in layer order (Packer 1 runs the first layers); the whole
  group is the **string**. Replaces "head" and "front" (MLX v3) and
  "tail" (llama.cpp RPC) in docs, logs and the command line. Older log
  entries above keep the old words.
- New names: `--split-role lead|packer`, `--split-packer-layers`,
  `mlx.split.packer` / `packer_layers`, `CARAVAN_MLX_SPLIT_PACKER` /
  `_PACKER_LAYERS`, `build_lead_command()` / `build_packer_command()`,
  `mlx_split_fetch.py --role lead|packer --packer-layers`. The old names
  stay as deprecated aliases; the new name wins when both are set.
- `GET /caravan/split` adds `lead` and `packers` and keeps `head` and
  `front`. The saved-cache stage id (`head 24-47 of 48`) is unchanged, so
  existing caches still load.
- Added a "possible future direction" to the roadmap: Terminal Delight as
  a terminal-first console for Caravan (not scheduled).

## 2026-10-31: docs brought up to date with v3

A docs-only pass on `caravan-v3-mlx-split` (no code changes):

- New `docs/CHANGELOG.md`: v0 → v3 with commits, headline numbers and the
  deprecated names. New `bench/v3/README.md` for `split_client.py`.
- `docs/CONFIGURATION.md`: the split flags (`--split-role`,
  `--split-peer`, `--split-listen`, `--split-packer-layers`), `mlx.split`
  and its env vars, `mlx_split_fetch.py`, the packer's tensor cache
  (GGUF split download stage 1), and a "Deprecated names" table.
- Corrected: `mlx.split` is read only by the `mlx_backend` command
  helpers; `caravan_agent.py --apply` and `render_mlx_plist.py` still
  start a one-Mac worker, so both halves of a split are started by hand.
  MLX-SPLIT.md had implied the config was enough.
- README, ARCHITECTURE, MLX, MLX-SPLIT, BENCHMARKS, ROADMAP and the
  agent, cpp, launchd and bench READMEs: v3 status and results, why
  Caravan uses its own link (MLX's standard link fails on ~2 MB+ messages
  over our Thunderbolt 4 cable; the direct-memory link needs Thunderbolt
  5), lead / packer / string wording instead of head / front / tail, and
  fixed links to sections that had moved into CONFIGURATION.md. Test
  count: 120.
- Older entries in this log keep the words they were written with.

## 2026-10-31: firm rule, each packer keeps its share on its own disk

Added under "Firm rules" in ROADMAP.md: the lead never resends a packer's
portion at startup, for GGUF and MLX. Checked today. MLX v3 already meets
it: the packer loads from its own folder, the link has no way to send
weights, and a missing shard stops it with an error. GGUF only partly
meets it: `rpc-server --cache` skips tensors over 10 MiB that the packer
already has, but smaller ones are sent every time, and the first load
of a model is sent in full. EXO2's cache (14.4 GB from Sep 8–10) holds
none of the current GGUFs' tensors, so the next GGUF start is a full cold
send. The gaps are listed as open tasks there.

## 2026-10-31: shard size check at startup (v3.1)

Firm-rule task 5, sizes part. `mlx_split.check_local_shards()` now also
checks each shard a stage needs: its size must equal what its own
safetensors header implies (8 bytes + header + end of the last tensor;
exact for all 36 shard files on EXO1 and EXO2), and, when
`mlx_split_fetch.py` downloaded it, the size Hugging Face lists, which the
fetch tool now saves to `caravan-split-sizes.json`. A mismatch raises
`ShardSizeError` naming the file and the fetch command (from Hugging
Face, never from the other Mac). Checksums are still open. 126 tests pass.

## 2026-10-31: housekeeping

- EXO2 runs the current branch: the pre-rename copy `~/cv3` was renamed to
  `~/cv3.pre-rename-2026-10-31` (kept, with its old session caches and
  logs), and `~/cv3` is now a git clone of `caravan-v3-mlx-split` from
  GitHub plus the two unpushed commits brought over as a git bundle from
  EXO1 (`d23a276`). `--split-packer-layers` is there, `--help` and the
  imports work, and all 126 tests pass in EXO2's MLX venv. The new
  shard size check passes for all six packer folders on EXO2.
- EXO1: `~/.caravan/models/gpt-oss-20b.gguf` pointed at a removed Ollama
  blob. It now points at the Hugging Face copy of
  `ggml-org/gpt-oss-20b-GGUF` `gpt-oss-20b-MXFP4.gguf` (12,109,566,624
  bytes, blob `27cd6c43…5901`), the file the GPT-OSS GGUF runs already
  used directly.
- EXO2: removed 13 stale `.incomplete` files (9.22 GB) under
  `.cache/huggingface/download/` in the Qwen3 30B 8-bit (10 files) and
  Gemma 4 26B 8-bit (3) folders, left by the stalled downloads earlier
  today. Every finished shard in those folders matched the size Hugging
  Face lists first; two of the partials were for lead-only shards the
  packer doesn't need. Only `.incomplete` files were removed.

## 2026-10-31: cable timing for splitting each layer (ROADMAP idea 4)

- New `bench/cable/cable_timing.py`: an echo server on EXO2 (Caravan's
  `serve_front` with a stand-in state, plus a plain-TCP echo on the next
  port) and a client on EXO1 (`FrontClient`, plus a plain socket). Test
  ports 5570/5571, MLX venv, no models, no services running; the
  servers were stopped afterwards. Route checked: EXO1 reaches EXO2 over
  `en2` (Thunderbolt 1).
- One chat's hidden state (4–6 KB) takes about 100 µs per round trip
  through Caravan's link, median (p95 about 125, p99 about 135–140);
  plain TCP about 90 µs. Batch 4 is 122–137 µs, batch 16 190–213 µs. The
  roadmap had guessed 50 µs.
- With a GPU sync on each side before each send (`--gpu-sync`) a round
  trip is about 1.1 ms. That test runs the two syncs one after the
  other, so it's pessimistic; a lone MLX sync is about 175 µs.
- Plugged into the roadmap's formula: Qwen3 26.3 ms per token (was
  guessed 22), Gemma 4 25.0, GPT-OSS 25.5. All beat the v3 split, only
  GPT-OSS beats one Mini. Batched, only GPT-OSS at batch 4 passes the
  go rule, by 3%, and only if the GPU wait were free. Verdict: not a go
  yet; parked for Thunderbolt 4. Tables in BENCHMARKS.md, verdict in
  ROADMAP idea 4.

## 2026-10-31: GPU-wait test for splitting each layer (no-go)

- `bench/cable/gpu_wait.py`: both Minis run every layer's two exchanges at
  the same time (compute half, wait for the GPU, swap 4–6 KB over
  Caravan's link framing, add), with synthetic 4-bit work sized like
  each model. Port 5572, MLX venv, 17:31–17:36 CDT, about 4 minutes. No
  model loaded, no services stopped; both scripts exited and `/tmp`
  copies were removed.
- One exchange costs 331–359 µs at batch 1 on top of the compute. Waiting
  for the GPU alone is 246–277 µs; the cable alone 60–87 µs. Batch 4:
  298–351 µs. The overlap trick (two half-batches) was worse, 441–647 µs.
- Estimates: Qwen3 19.6 tok/s (v3 29.5, one Mini 51.0), Gemma 4 25.4
  (26.9, 41.3), GPT-OSS 27.5 (26.1, 36.5). Budgets per exchange to beat
  v3: 180 / 306 / 371 µs; to beat one Mini: 31 / 90 / 144 µs.
- Verdict: no-go; parked. A faster cable alone doesn't fix it, because the
  GPU wait is the larger cost.
- Found on the way: EXO2 is in Low Power Mode (`pmset -g` lowpowermode
  1). Its compute was 50–80% slower than EXO1's at batch 4. Not changed.

## 2026-10-31: v3 split and GPU-wait rerun with Low Power Mode off

- Brenden turned Low Power Mode off on EXO2. `pmset -g` showed
  `lowpowermode 0` on EXO1 and EXO2 before the runs. Both Macs on v3.1,
  branch tip `f68d15e`.
- v3 split bench, same as the first run (`split_client.py bench`, EXO1
  lead on port 8194, EXO2 packer on 169.254.104.38:5560, worker
  defaults), output in `~/.caravan/bench-2026-10-31/v3.1-rerun/` on EXO1.
  4-bit 18:10–18:15 CDT, 8-bit 18:15–18:21 CDT. The first attempt failed
  in 40 s because the model paths were given as `~/…` and got expanded
  on the wrong machine; rerun with full `/Users/brenden/…` paths after
  deleting the failed output.
- 4-bit writing: Qwen3 30.4 (was 29.5), Gemma 4 27.7 (26.9), GPT-OSS
  26.6 (26.1) tok/s. Reading 512 / 4k: 451 / 408 (388 / 332), 411 / 375
  (328 / 301), 440 / 424 (350 / 338). Bench peak per Mac 10.02 / 9.09 /
  6.94 GB (10.44 / 9.28 / 7.03). Quality 3/3.
- 8-bit writing: 20.7 / 18.4 / 20.1 (20.6 / 18.1 / 19.8). Reading 512 / 4k:
  442 / 395, 401 / 362, 430 / 405. Bench peak 17.65 / 15.38 / 12.01 GB.
  Quality 3/3.
- Per token, the packer half got 0.5–1 ms faster, the lead and the cable
  didn't change. So Low Power Mode mostly slowed reading (GPU-heavy) and
  hardly writing (memory and overhead).
- `gpu_wait.py` rerun, 18:21–18:25 CDT, port 5572. Per exchange at batch
  1: 325 / 366 / 359 µs; batch 4: 403 / 414 / 403 µs. Estimates with the
  new v3 halves: 21.1 / 24.7 / 26.7 tok/s (v3 30.4 / 27.7 / 26.6, one Mini
  51.0 / 41.3 / 36.5). Still no-go.
- No services stopped; all test workers exited after their runs.

## 2026-10-31: handoff folder for a new assistant

- Brenden is moving his assistant to a different account. Added
  [`handoff/`](../handoff/README.md): the full brief (lab, network, rules,
  post and video style, current state, first steps), the old assistant's
  memory, the two daily reminder routines, and a copy of the lab folder
  (experiment log, video scripts, all eight lab videos). No secrets; they're
  named only (`MINI_SSH_PASSWORD`). Code unchanged.

## 2026-10-31: uneven layer split (ROADMAP idea 5)

- Tried `--split-packer-layers K` on the v3 split: Packer 1 got the
  default half, then +1, then +2 layers, for 4-bit Gemma 4 (K=15/16/17),
  GPT-OSS (K=12/13/14) and Qwen3 (K=24/25/26). Same method as the LPM-off
  rerun: EXO1 lead on test port 8194, EXO2 packer on 169.254.104.38:5560,
  `split_client.py bench`, medians of 2, `lowpowermode 0` on both. Branch
  tip `845216b` on both Macs. Run 20:16–20:32 CDT. Output
  `~/.caravan/bench-2026-10-31/idea5-uneven/`.
- Even-split writing matched the LPM-off baseline within noise: Qwen3
  30.0 (baseline 30.4), Gemma 4 27.6 (27.7), GPT-OSS 26.8 (26.6) tok/s.
  Reading 512 / 4k likewise. Quality 3/3 on every cut.
- Moving the cut did **not** raise single-chat writing on Gemma 4 or
  GPT-OSS (27.6 → 27.4 / 27.4; 26.8 → 26.6 / 26.7). The pipeline is
  serial: packer then lead then sample, so a layer just shifts ms from
  one half to the other and the sum stays ~35.5 ms (Gemma) / ~36.6 ms
  (GPT-OSS). Qwen3 edged 30.0 → 30.2 → 30.5; near noise, and it was
  already balanced.
- Half timings (ms/token, median of the two tg128 runs): Gemma even
  16.7 / 0.82 / 17.9 → K=16 17.8 / 0.82 / 17.0 → K=17 18.6 / 0.85 / 16.1;
  GPT-OSS 16.0 / 0.85 / 19.7 → 17.4 / 0.85 / 18.5 → 18.5 / 0.83 / 17.2;
  Qwen3 16.1 / 0.76 / 15.6 → 16.7 / 0.77 / 14.7 → 17.1 / 0.77 / 14.1.
- Best balanced cuts (for idea 1 later): Gemma **K=16**, GPT-OSS **K=13**,
  Qwen3 **K=24 (even)**. Reading flat across cuts; packer peak memory
  rose and lead peak fell as K grew. Flag works; no code changes.
  Tables in BENCHMARKS.md; verdict in ROADMAP idea 5.



## 2026-11-01: Day 6 lab video + docs (v3.4)

- Lab video LAB-2026-11-01-03 (`make_runtime_video_v12.py`): techie-friend
  cut of several chats on the two-Mini split. v10 (jargon) and v11
  (beginner / "teach-along") kept, superseded, not posted. Audience
  guidance in `handoff/README.md` §5/§6, `handoff/routines.md`, videos
  index intro.
- Day 6 X draft saved in `handoff/lab/experiments.md` (status: drafted,
  not posted). Measured numbers only (wall writing 44→73 / 37→61 / 34→54;
  third-chat wait ~4 s→~0.6 s).
- Tags: `v3.3` at first Day 6 cut (`f31d15a`); `v3.4` at this tip. Branch
  pushed after Brenden approved noreply author + docs.

## 2026-11-01: Idea 1 N=3 stall fix

- **Root cause:** `_pipe_round` always gave the next packer slot to
  `need[0]` in list order. After lead(A), A rejoined need ahead of a
  never-started chat C, so C waited until A or B finished (~4 s TTFT on
  tg128). Wall aggregate for N=3 fell below N=2.
- **Fix:** fair pick by `(n_gen, t0)` among ready/need slots; admit at
  most one prefill per outer loop so decode can start sooner. Flag-off
  and N=2 paths unchanged.
- **Recheck (America/Chicago ~01:25–01:36):** flag-off writing 38.1 /
  34.2 / 45.7. Pipeline N=2 wall 61.0 / 54.0 / 72.7. N=3 wall 59.8 /
  53.0 / 70.8; max TTFT 0.62 / 0.61 / 0.59 s (was ~4 s). Quality 3/3.
  Ports cleaned after. Pushed with v3.3 / v3.4 after Brenden approved.

## 2026-10-31 night: Idea 1 several chats at once (pipeline)

- **Goal:** Keep lead and Packer 1 both busy by overlapping chat B's
  packer half with chat A's lead half (`--split-pipeline-chats N`,
  default 1 = off).
- **Code:** `3d3e98a` + fix `be19fe1` on `caravan-v3-mlx-split`. Packer
  `fwd` takes `key`; lead `begin_packer`/`finish_packer` + multiplexed
  decode on the MLX thread. Bench: `bench/v3/pipeline_bench.py`.
- **Flag-off baseline (even cut, keepalive on):** writing 38.5 / 34.3 /
  45.8 tok/s (Gemma / GPT-OSS / Qwen) — matches prior keepalive 38.3 /
  34.1 / 45.6. Quality 3/3.
- **Pipeline (idea-5 cuts, keepalive on, medians of 2):** two chats wall
  aggregate ≈1.6× (Gemma 61.0, GPT-OSS 54.0, Qwen 73.0). Three chats
  raise the sum of per-chat rates but wall aggregate falls (one chat
  ~4 s TTFT). Quality 3/3. Ports cleaned after.
- **Tag:** `v3.2` at `cb61970` (keepalive + Day 5 video) pushed earlier
  the same evening; idea 1 + stall fix + Day 6 videos pushed as v3.3 / v3.4.

## 2026-10-31: GPU keepalive while waiting on the peer

- Found the ~5–6 ms/half/token "split tax": after each Mini sits idle
  ~15–20 ms waiting on the peer, the next Metal graph build + eval is
  ~5 ms slower (cool-down). Cable and ser/deser are under 1 ms.
- Fix: `GpuKeepalive` in `agent/mlx_split.py` — a short-lived thread
  runs a tiny `mx.eval` during the blocking recv, then joins before
  this process runs its layers. `--split-keepalive` on by default;
  `--no-split-keepalive` or `CARAVAN_MLX_SPLIT_KEEPALIVE=0` disables.
  A long-lived pause thread was tried on Gemma 4 and rejected (writing
  fell to ~17.6 tok/s).
- A/B on EXO1 lead :8194 / EXO2 packer 169.254.104.38:5560, LPM off,
  medians of 2, 21:53–22:05 CDT, output
  `~/.caravan/bench-2026-10-31/split-tax/ab/`. Code commit `0f14e72`.
- Writing on vs off: Gemma 4 38.3 vs 27.7, GPT-OSS 34.1 vs 26.6, Qwen3
  45.6 vs 30.4 tok/s. Reading 512 / 4k slightly up (no regression).
  Peak mem unchanged. Quality 3/3 every run.
- Power: `sudo powermetrics` needs a password on the Minis. Lead CPU%
  median rose during waits (e.g. Gemma 4.5 → 13.9); packer median
  barely moved with the spawn design. Tables in BENCHMARKS.md.
