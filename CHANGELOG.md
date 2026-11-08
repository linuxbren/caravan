### GGUF Optimize now runner (offline-tested) — 2026-11-07
- New `proxy/gguf_tune.py` (`GgufTuner`):
  - Follows `gguf_schedule()` one option at a time: reload, measure the incumbent, reload, measure the challenger.
  - Keeps the challenger only if it's more than 3% faster. Otherwise it records the challenger as a loser so it won't be retried.
  - Saves after every trial, and always leaves the winner running, including after an error.
- Store: `~/.caravan/gguf-tuned.json`, keyed by `<file>.gguf|<N>mini`.
- `measure_http()` reads llama-server's own `timings.predicted_per_second`, using 2 fixed prompts, temperature 0, 192 tokens.
- The web GGUF launcher now passes `best_tune()` to `llama_args(tune=...)`. Bad values are dropped, and with nothing learned the launch behaves as before.
- Not yet wired to the Optimize now button. That needs a web endpoint that calls `GgufTuner` with the launcher's restart. Next step.
- Tests: 5 new. Full suite 461 OK (32.8s). One failed test run: my test assumed ubatch 1024 is the first challenger, but the schedule picks 256 (a tie in distance from 512, so 256 comes first). The test was fixed; the code was unchanged.
- Live check: run the tuner against a small GGUF (Qwen2.5-3B q4_0) on 1 and 2 Minis. Expect about 6 reloads per run.

### Picker warnings for risky checkpoints — 2026-11-07
- `mlx_arch.model_warnings(config, weight_map)` flags four cases. It only warns and never blocks:
  - a top-level `*_text` model_type that isn't in the remap table
  - config ties embeddings but the files ship `lm_head` (the Dark Champion case)
  - config says untied but there's no `lm_head` (the output layer would be random)
  - `*_mtp`/`*_nextn` helper heads
- Carried through `inspect_tree` → node inventory → catalog rows (`warnings`). The model picker adds a ⚠ to the name, and the warnings show in its tooltip.
- Tests: 6 new. Full suite 456 OK (32.8s).
- Live check: after the Minis pull this, Dark Champion should show ⚠ with the tie note.

### MTP layers in split planning — 2026-11-07
- Checked HF indexes on Nov 7:
  - `mlx-community/Qwen3.6-35B-A3B-4bit`: 2090 keys, layers 0-39, `language_model.*`, no `mtp.*` keys.
  - `mlx-community/Qwen3.6-35B-A3B-MTP-4bit`: a standalone helper head. model_type `qwen3_5_mtp`, 46 keys, `fc`, `norm`, `pre_fc_norm_*`, a single `layers.0`, no embeddings. Its config still says 40 layers.
- Before: splitting the MTP repo would have planned 40 nonexistent layers. `mtp.*` keys inside a full checkpoint were fetched by both Minis, and `mtp.layers.0.*` was even counted as layer 0, which went to the packer.
- Now:
  - `mtp.*` keys go to the lead only.
  - Layers numbered at or above `num_hidden_layers` (DeepSeek/GLM nextn) go to neither stage. mlx_lm drops them at load, so neither Mini needs them.
  - `head_only_reason()` refuses to split helper heads (`*_mtp`/`*_nextn`, or no embeddings with fewer layers than config). Split downloads stop with a clear error, and inventory marks them not splittable.
- Tests: 5 new. Full suite 450 OK (32.3s). One failed run before the fix: `mtp.layers.0` was matched as layer 0, so its MTP check now runs first.
- Live check: none needed for the planner. For Qwen3.6 native MTP, confirm the lead still finds the MTP head.

### Rope scaling for classes that ignore it (mixtral etc.) — 2026-11-07
- Some mlx_lm classes ignore `rope_scaling` because they build a plain `nn.RoPE`. Examples: mixtral, qwen3_moe, phi3, gemma2, and about 40 more in mlx_lm 0.32.2.
- `proxy/mlx_arch.fix_rope_scaling()` swaps those for `mlx_lm.models.rope_utils.initialize_rope(...)` when config (or text_config) asks for scaling. Types covered: llama3, yarn, dynamic, and linear.
- Applied after load in the single-Mini worker and in split `Stage` (lead and packer). Classes that already scale (llama, qwen2/3, gpt_oss) are left alone. Site-packages is not edited.
- Tests: 5 new (fake RoPE/config). Full suite 445 OK (32.8s).
- Live check (testing window): load Dark Champion. Worker/packer logs should show `rope scaling: applied llama3 to N attention layer(s)`, and a long prompt should stay coherent.

### Releases — 2026-11-07
- First daily source release: `day17-2026-11-07`; main fast-forwarded to current work.
- Root INSTALL.md covers the web UI, dependencies, private-network setup and more Minis.
- Daily process: [RELEASES.md](docs/RELEASES.md). ZIP/tar.gz exclude lab video media.



### GGUF split hardening and picker downloads — 2026-11-06/07
- Picker downloads GGUF quants (one file, lead only) on the shared job system; finished downloads auto-load only when idle.
- Re-attach to a running GGUF split after a web restart; tensor-split from live free RAM; watchdog cleanup; plain 502 on peer loss mid-chat.
- CLI GGUF split moved to SSH tunnels; `agent/rpc_gate.py` removed (one mechanism). MLX-only Settings disabled for GGUF; Topology names Minis.
- Robustness: 5 cycles 20/20 OK, Stop mid-load and peer kill leave 0 processes. Known limit: GGUF Resume restarts from 0 %.

### Web helper consent and inventory — 2026-11-06
- Ask explicitly before downloading missing split-MLX guess-ahead helpers; allow reconsidering in Settings, and use normal resumable download jobs on the lead.
- No permanent silent decline for non-interactive loads; legacy silent declines no longer suppress the web prompt.
- Show individual draft helpers and native MTP heads in Topology disk inventory; protect helpers while any model is loaded.
- Tests: 6 new helper tests; full suite 371 passed (32.576s). Initial concurrent-work run: 365 tests / 1 GGUF fixture error, retained in WEB.md.

- Settings: validate HF tokens server-side, hide accepted-token input behind “Use a different token”, retain Cancel and saved-file removal, distinguish rejected credentials from unavailable checks.

### Optimize now scheduler (PR #9 replacement, 2026-11-07)

- Replace the hidden Deep/Quick coverage runner with paired, one-option A/B
  trials; keep everyday Auto learning separate.
- Add worker pause/hold/commit/release controls, web Pause/Resume, hardware-scoped
  losses and raw results, and cancel/error winner restoration.
- Preserve placement, config pins, PID ownership and web worker-keeping/adoption.
- See [OPTIMIZE-NOW.md](docs/OPTIMIZE-NOW.md) for the PR comparison and all test
  attempts, including failed runs and deployment status.
- Live testing also found/fixed an unnecessary single-Mini baseline reload and
  post-restart load-entry/recovery-release bugs. Final code passes 407 tests on
  box/EXO1/EXO2 (EXO1: one existing Node-only test skips), plus 24/24 theme parity.
