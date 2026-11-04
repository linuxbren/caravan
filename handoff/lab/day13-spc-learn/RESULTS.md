# Day 13 — self-tune shared-prefix per model

**Date.** 2026-11-04 (America/Chicago).  
**Goal.** Fold shared-prefix into Day 10 learn-from-real-chats. From empty
tuned settings (no `--split-shared-prefix-cache`), measure TTFT on new chats
that share a system prompt, account for one-time store/materialize, keep on
per model if it helps.

**Setup.** EXO1 lead + EXO2 packer, Thunderbolt `169.254.103.191:5560`, ports
8194/5560, LPM off. Learn on; pipeline pinned `--split-pipeline-chats 1`;
`--no-split-draft`; dedicated `tuned-settings.json` per model under
`~/.caravan/bench-2026-11-04/day13-spc-learn/<tag>/`. Scripts in `scripts/`.

## Decision (real numbers)

| Model | Chose | Chats | Off cold mean TTFT (s) | Store TTFT (s) | Hit mean TTFT (s) |
|---|---|---:|---:|---:|---:|
| Gemma 4 26B-A4B 4-bit | **on** | 7 | 12.871 | 23.158 | 2.664 |
| Qwen3-30B-A3B 4-bit | **on** | 7 | 10.369 | 10.399 | 0.897 |
| Llama 3.1 8B Instruct 4-bit | **on** | 7 | 19.289 | 19.321 | 1.472 |

Sources: `gemma-learn.json`, `qwen3-learn.json`, `llama-learn.json`.

## Notes

- Store for Gemma is the materialize cost (~23 s once); later hits ~2.66 s.
- Qwen3/Llama store ≈ cold (trim path); hits ~0.90 / 1.47 s.
- Explicit `--split-shared-prefix-cache` still pins on and skips learning that knob.
- Unit tests: `SharedPrefixLearnTest` (+8). Full suite **182 OK**.
