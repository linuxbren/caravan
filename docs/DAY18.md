# Day 18: load prompt, real Resume, GGUF stage 2, saved split, Optimize now additions

Nov 7, 2026, ~5:58 PM CT onward (America/Chicago). Branch `caravan-v3-mlx-split`.
Direct edits on the box, committed as linuxbren. No cloud agents.

## Status by item

| # | Item | Status | Commits |
|---|---|---|---|
| 1 | Load now / Not now prompt after a download (no silent auto-load) | Done (code + tests; live UI check queued) | 61fd3a3 |
| 2 | Resume continues a partial file with HTTP Range | Done, verified live on EXO1 and EXO2 | 07a8df8 |
| 2b | Split-download progress overcount / false "stalled?" | Done (code + tests; live check queued) | d173929 |
| hotfix | Dark Champion 21B greyed out ("missing shards on EXO1") | Done, verified live | 1955cab |
| 3 | GGUF stage 2: peers load their share from their own disk | Done, verified live (3B); 30B timing queued | 0dbe51c, (note text) |
| 4 | llama.cpp upgrade + before/after | Partial: "before" recorded; upgrade paused for Brenden's live test | — |
| 5 | MLX optimizing single stage | Blocked: needs a decision (see below) | — |
| 6 | Optimize now: native MTP, adaptive lookup, GGUF tuning | Partial: MTP + lookup sweeps wired; GGUF knobs + plan, runner not wired | f5670e8 |
| 7 | Qwen3.6-35B-A3B + helper | Investigated; live test queued | — |

## 1. Load now / Not now

When a download finishes and nothing is loaded, the page asks "No model is loaded.
Load <name> now?" with **Load now** / **Not now**. Not now leaves a Load button on
the job card. With a model already loaded it still only offers the Load button.
The `<dialog>` uses the shared theme dialog style, so it follows Amber, Green,
Meadow and Nebula. Tests: `tests/test_day18_load_prompt.py` (3).

## 2. Resume with HTTP Range

hf_xet keeps no partial file, so Resume used to restart a file from 0.
`agent/range_fetch.py` now downloads every weight file (MLX shards and GGUF)
into `.cache/huggingface/download/<name>.incomplete` and resumes with
`Range: bytes=<have>-`. If the server ignores Range it starts that file clean.
Small files (config, tokenizer) still use `snapshot_download`.
Tests: `tests/test_day18_range_fetch.py` (4).

Live records (Qwen/Qwen2.5-0.5B-Instruct-GGUF `qwen2.5-0.5b-instruct-q4_0.gguf`,
428,730,208 bytes, sha256 7671c0c3…af6ed):

| Where | Stop | Resumed from | Rest | sha256 |
|---|---|---|---|---|
| Box | killed at 6 s | 337,641,472 B | 91,088,736 B in 1.7 s | match |
| EXO1 (first try) | `timeout` missing on macOS, no stop | 0 | 428.7 MB in 92.3 s | match |
| EXO1 | killed at 20 s | 116,391,936 B | 312,338,272 B in 169.8 s | match |

Speed check on EXO1, same file, from 0: hf_xet `hf_hub_download` 138 s, plain
curl 89 s. Single-stream Range is not slower on this line.

Through the web UI (`/api/picker/download`, Qwen/Qwen2.5-3B-Instruct-GGUF
q4_0, 1,997,879,712 B, job 1b421e5f088b, 6:18–6:21 PM CT): EXO1 picked up at
~1.75 GB, EXO2 logged `RESUMED qwen2.5-3b-instruct-q4_0.gguf from 1012924416 bytes`;
both finished with the full size.

### 2b. Progress overcount (Brenden's report)

Job d653dbe7d055 (Dark Champion 21B, split:2) showed EXO2 at "17.62/11.77 GB ·
stalled?" while files were landing. Causes and fixes (d173929):
- The disk probe counted a `.incomplete` as well as the finished file beside it. Now counted once (local and remote probe).
- The Mini's total came from the planned split, not what that Mini's fetcher
  actually downloads (EXO2 needed shards 1–4, ~20.7 GB). The remote fetcher's first
  line (`my_gb`) now sets that Mini's total (`web_picker.apply_reported_total`).
- Shown bytes are capped at the total.
- "Stalled?" now needs no growth on any signal (shown bytes, disk, network), not
  "no new maximum". Tests: `tests/test_day18_progress_overcount.py` (4).

## Hotfix: saved split point (1955cab)

Dark Champion 21B (32 layers) was downloaded with the server default
packer_layers 24, but the catalog checked it with 32//2 = 16, so EXO1's shards
4–5 looked incomplete. Now:
- `caravan-placement.json` stores `packer_layers` and `n_stages` at download time.
- `inspect_tree` uses the saved value over the caller's default; older split
  placements without it are detected from the shards present (24 tried first).
- The catalog uses the saved/detected value, and the load uses the same entry value.
- Defaults match: catalog and server both use 24 (models of 24 layers or fewer split in half).
- Backfilled `packer_layers: 24, n_stages: 2` in this model's placement file on both
  Minis (weights untouched). Web restarted on EXO1 with KEEP_WORKERS=1 at ~6:28 PM CT.
- Verified: `/api/models` lists it `usable=True, packer_layers=24`.
Tests: `tests/test_day18_saved_split.py` (4).

## 3. GGUF stage 2

llama.cpp RPC already sends only a hash for tensors over 10 MiB when the peer's
`rpc-server -c` cache has that tensor. Stage 2 fills that cache from the peer's own
copy of the GGUF before the load:
- GGUF downloads now go to every online Mini.
- At a split load, each peer with the same file (name + size) runs
  `agent/gguf_rpc_seed.py`: reads tensor offsets with gguf-py, works out the
  layers llama.cpp gives that device (same rule as llama-model.cpp, ±1 layer),
  and a small C helper (`agent/fnv_seed.c`, built once to
  `~/.caravan/bin/caravan-fnv-seed`) writes `<cache>/rpc/<fnv1a64>` files.
- No peer copy: same as before (share over the link). Seeding can't fail a load.
- Lockdown unchanged: rpc-server still listens on 127.0.0.1 only, reached over the SSH tunnel.

Checks:
- Hash format: seeding Qwen3-30B-A3B-Q4_K_S (EXO2 share, 1:1) into a temp dir gave
  73 tensors / 8.41 GB in 19.0 s; 70 of the 73 names already existed in EXO2's real
  rpc-server cache (the 3 others are padding layers). The hashes match llama.cpp.
- Live split load, qwen2.5-3b-instruct-q4_0 (llama.cpp 6a1a922), 6:22–6:26 PM CT:

| Run | EXO2 share came from | Load | Write tok/s (3 × 256 tok, temp 0) |
|---|---|---|---|
| No local copy on EXO2 | link (cache grew 574→617 files) | 4.0 s | 41.8 / 41.7 / 41.6 |
| Local copy, cache entries removed first | own disk: 43 tensors, 0.8 GB seeded in 6.2 s | 3.0 s (+6.2 s seed) | 41.8 / 42.1 / 41.1 |

  After the seeded load the cache was still 617 files: every big tensor was a hit.
  Over Thunderbolt the first seed costs more than it saves; it pays off on
  slower links and on later loads (seed reports "have" and skips).
Tests: `tests/test_day18_gguf_seed.py` (4).

## 4. llama.cpp upgrade (partial)

"Before" numbers, llama.cpp 6a1a922 (Sep 5), prompt "Write a short story about a
caravan crossing a desert at night.", n_predict 256, temp 0, no prompt cache, 3 runs:

| Model | Where | Write tok/s |
|---|---|---|
| qwen2.5-3b-instruct-q4_0 | one Mini (EXO1) | 50.6 / 50.6 / 50.5 |
| qwen2.5-3b-instruct-q4_0 | split 20.4:12.9 | 41.6–42.1 (above) |
| Qwen3-30B-A3B-Q4_K_S | one Mini (EXO1) | 34.4 / 34.4 / 34.4 |
| Qwen3-30B-A3B-Q4_K_S | split EXO1+EXO2 (load 12.1 s) | 35.1 / 35.1 / 34.3 |

Attempts (all failed, nothing changed in the running binaries):
1. EXO1 `git pull` refused: EXO1 is on local branch `caravan-patches` (one patch,
   2f26123e "rpc: use getaddrinfo…") and `origin` is linuxbren/llama.cpp. Made
   branch `caravan-day18` at upstream 76a67730 (Nov 7); the patch no longer applies
   (upstream rewrote that code). Caravan only dials 127.0.0.1 tunnels, so it isn't needed.
2. EXO2 master pulled to 76a67730.
3. First build: `cmake: command not found` over non-interactive SSH (PATH).
4. Second build (with /opt/homebrew/bin) was stopped when Brenden started live
   testing. It had already relinked some dylibs in `build/bin`; they were put back
   from the backup `~/dev/llama.cpp-bin-6a1a922` (mv over, so running processes kept
   theirs). `llama-server --version` = 6a1a922 on both. New-version-only dylib files
   (`*.0.29.0.dylib`, `*.0.9.0.dylib`) are left in place, unused.
Next: build 76a67730 into a separate dir, switch `CARAVAN_LLAMA_BIN`, re-run the table.

## 5. MLX optimizing "single stage" (blocked, needs a decision)

Optimize now already runs in one pass (one option at a time). The "two-stage" in
the docs is the MLX split runtime (`MAX_SPLIT_STAGES = 2`): MLX splits across at
most 2 Minis. Making that N-stage is a runtime change (mlx_split chain, packer
relay) that can't be tested beyond 2 Minis here. Question for Brenden: which one did he mean?

## 6. Optimize now additions (partial)

- `native_mtp` and `adaptive_lookup` are new reload options, tried last, one at a
  time, 3% margin, recorded losers skipped. MTP needs one Mini, an installed head
  and 16-bit KV; lookup needs one chat. Both start from off (a saved winner
  isn't used as the starting value). Because these modes load with `--no-learn`,
  the runner goes back to the normal worker to record the result, then applies the winner.
- Page settings that pin them (Guess-ahead or Prompt lookup not Auto) skip them.
  Optimize still refuses to start while MTP/adaptive lookup is the page setting.
- GGUF: `llama_args(tune={"flash_attn", "ubatch"})` and `gguf_schedule()` (same
  rules). Not wired: the runner talks to the MLX worker's `/caravan/sweep`, which
  llama-server doesn't have. Next step: a GGUF runner that stores results in the
  tuned store and reloads llama-server per option.
- Not run live yet. Tests: `tests/test_day18_optimize_more.py` (10).

## 7. Qwen3.6-35B-A3B with a helper (investigated)

- Sizes (HF API): `mlx-community/Qwen3.6-35B-A3B-4bit` 20.4 GB; MTP head
  `mlx-community/Qwen3.6-35B-A3B-MTP-4bit` 0.48 GB (not 0.8); `Qwen/Qwen3.5-0.8B` 1.75 GB.
- Fit: 20.4 GB doesn't fit one 24 GB Mini (Metal ~18 GB). Split: ~10.2 GB each + 0.48 GB head on the lead fits.
- Vocab: Qwen3.5-0.8B 248,320 = Qwen3.6 248,320. The draft is hybrid too (24 layers, linear attention).
- Rewind: Caravan's native MTP (Day 17) already snapshots the whole cache and
  replays on a rejected guess (`agent/native_mtp.py`), so rejected guesses work with
  linear-attention layers. Blockers for this model: it only accepts dense Qwen3.5
  (`num_experts` → rejected; 35B-A3B is MoE), and native MTP is one-Mini only, while
  this model needs the split. Needed: MoE MTP head support, and MTP on the lead in
  split mode with a snapshot of the packer's linear caches per verify.
- Live benchmark (no helper vs helper) queued; it needs a 20.4 GB download to both Minis.

## Queued for the Minis (needs Brenden's go-ahead)

See the report. Tests at the end of the code work: 436 OK on the box.

## Dark Champion 21B gibberish: root cause (Nov 7, read-only diagnosis)

**Symptom:** `mlx-community/Llama-3.2-8X4B-MOE-V2-Dark-Champion-...-21B-MLX` as a 2-Mini split (EXO2 packer layers 0-23, EXO1 lead 24-31) printed multilingual token salad from the first token, ran to 768 tokens, ~12 tok/s.

**Root cause: the two sides disagree on whether embeddings are tied.**
- config.json says `tie_word_embeddings: true`, but the checkpoint also ships `lm_head.*` (in shard 5).
- Caravan's `mlx_split_fetch.tied_of()` only checked for `lm_head` in the weight map, so it said "untied" and gave the lead only shards 4-5. Shard 1, which holds `embed_tokens`, wasn't included.
- mlx_lm's mixtral follows the config. It builds no `lm_head` and drops `lm_head.weight` in sanitize, then computes logits with `embed_tokens.as_linear`.
- On EXO1, `embed_tokens` was never in any local file. `load_model(strict=False)` left it at random init. The quantize predicate also skipped it because there were no scales. So every logit came from a random matrix.
- The startup shard check passed because it used the same wrong `tied_of`.
- Evidence (EXO1, offline):
  - `ModelArgs.tie_word_embeddings=True` means the model has no lm_head.
  - `plan_files(...,24)` gives tied=False and head files = shards 4-5 only.
  - The packer loaded 17.0 GB for 24 layers and the lead about 5.7 GB for 8 layers, so all layer weights were present. Only the output head was garbage.
- **Not the cause:**
  - The `model_type remap: qwen3_5_text → qwen3_5` log line. It's a startup patch that runs for every model and is harmless.
  - The split boundary. It's 24 on both sides.
  - Missing layer tensors.
  - Quantization config.
  - The ignored llama3 rope_scaling. That one is real but secondary.

**Fix (local branch `fix/tied-embed-split`, not committed):**
1. `tied_of` returns True if `tie_word_embeddings` is true (top level, `text_config`, or `llm_config`) or if there's no lm_head. Downloader, inventory, and the startup check all share it, so the lead now needs shard 1 too.
2. `Stage` records the keys mlx_lm actually loaded. If any weight this stage uses was missing, it raises `MissingWeightsError` instead of running random weights. This makes the whole "strict=False silently random" class fail loudly.
3. New tests are in tests/test_tied_embed_split.py.

**To verify (needs Brenden's OK):**
- Fetch shard 1 (~5.2 GB) to EXO1 with `mlx_split_fetch.py ... --role lead --packer-layers 24`.
- Restart the split and send one short chat.

**Follow-up:** mlx_lm mixtral uses plain `nn.RoPE` and ignores llama3 `rope_scaling` (factor 32). Quality drops on long contexts. A Caravan patch could swap in `mlx_lm.models.rope_utils.initialize_rope`.
