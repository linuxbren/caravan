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
