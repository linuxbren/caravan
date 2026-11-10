# Day 20 — less waiting, same tools

Caravan runs local models; Hermes supplies the assistant's instructions and tools.
The extra setup matters: a short direct Huihui request started generating in
1.275s cold, while the full Hermes-prefix replay took177.438s. Warm, those
were .298s and1.436s. This is inference-only replay, not a measurement of pure
Hermes app overhead: output lengths, hidden thinking and complete reply times
also differ. Nothing here removes Hermes's tools.

## What we tried, why, and what happened

1. **Stop rereading the same setup — kept.** Imagine opening the same thick
   instruction manual before every reply. Hermes's small chat-title request was
   sharing the main chat's saved-state slot and erasing it. We gave the two jobs
   separate identities, then saved an exact copy of the shared setup on every
   participating Mac. Historical repeated setup/prefill fell from207.87s
   (about3½min) to1.17–1.76s, with13,182 cached tokens. A truly new setup still
   needs reading once. This is not “a full visible answer in one second”: first
   generated tokens may be hidden reasoning, and writing still takes time.
2. **Let a tiny helper name the chat — kept as an opt-in.** A title should not
   hold up the big model. A local Qwen2.5-0.5B helper handles only narrowly
   recognized title requests: median6.458s became .114s in the measured pilot.
   It gets concise title-only instructions, not a reduced main-agent prompt.
   Wrong-shaped/unrelated/slow/unavailable replies fall back to the main model.
   Main summaries and real work are not silently redirected. Earlier helper
   attempts produced bad titles; they were rejected rather than counted as wins.
3. **Warm the setup at startup — not enabled.** We tried paying for a dummy
   request before real work arrived. It cost .668s; the real first-token time
   barely moved1.762→1.699s and its wall time1.864→1.972s. Existing saved-state
   recovery was already doing the useful work, so automatic extra warm-up stayed off.
4. **Guess the next words — optional, not default.** Repeated copying gives
   useful clues. N-gram lookup improved a paired warm copy task44.26→70.69tok/s,
   accepting86% of proposed tokens. That is about60% faster, **not double**.
   Ordinary chat regressed29.34→28.48tok/s, so it stays off for normal work.
   The readout now reports actual proposed/accepted tokens rather than a vague hit.
5. **Pack chat memory into a smaller format — rejected for this setup.** On the
   Qwen3-30B-A3B trial, KV8 made cold setup36.200→49.151s and writing
   29.20→22.68tok/s, with a higher measured peak allocation. We kept KV16.
   A shorter warm answer is not proof of faster generation.
6. **Think less for simple replies — per-request option only.** A short Huihui
   reply fell42.748→9.68s when thinking was disabled, but generated tokens also
   fell275→54 and writing speed stayed about the same. It saves deliberation,
   not compute per generated token. Main Hermes remains medium; safe automatic
   thinking suppression for real tool turns was not established.
7. **One Mini versus two — room, not double speed.** We copied the missing
   Huihui weights over Thunderbolt without deleting other models. A short chat
   worked on one24GiB Mini, but the full~11.3k-token Hermes replay GPU-OOMed
   before its first token after123.562s. Split24/40 worked. Qwen3.5-derived
   smaller models fit on one: Astrea9B OptiQ mixed4/8 and Orvena4B4-bit were
   about3% and6.5% slower split on full-prefix decode. Matching requests gave
   identical visible outputs/token counts. Splitting helps fit a bigger working
   set; extra serial handoffs do not make this single chat twice as fast.
8. **Restart without babysitting — main split recovery passed.** The first
   attempt started before peer free-memory information was ready and blocked
   permanently. Restore now waits/retries with bounded backoff; Omarchy tunnels
   reconnect under user services instead of silently dying. A second physical
   reboot restored the saved Huihui24/40 automatically in64.735s from the first
   failed EXO1 transport probe to healthy model load. A complete :18090 reply
   followed without a manual Load/restart. That run did not exercise an actual
   retry: prerequisites were ready on its first load attempt. The newer tiny
   title helper's guarded startup order has not yet had a physical reboot check.

## For the nerds

- Main: Huihui Qwen3.5-27B Claude4.6 Opus abliterated4bit, EXO2→EXO1,
 24/40 layers, KV16, serial pipeline1. Main medium reasoning, all configured
 tools retained. Historical cache run21 tools/13,182 cached tokens; newer frozen
 replay19 tools/11,287 Huihui cached tokens. These are distinct datasets.
- Cache fixes367cbc9/6efecbf/ad07c13: stable system+tools/session namespace,
 exact pre-user tokenizer boundary, cloned recurrent snapshots and durable
 per-stage prefix state with layout/digest checks. No arbitrary recurrent rewind.
- f0a389e/82fa186: live MLX `/v1/models` no longer fails because GGUF is down;
 Thunderbolt SSH alias resolves current IPv4 without consuming SSH stdin.
- 6112ae6/03cd47b/49379aa/59e78f6: title-only routing and token telemetry,
 primary-health/RAM startup gate, fail-closed validation and compact-title pilot.
 Aux is disabled by default globally; this installation explicitly enables it.
 Soft worker budgets are not hard OS memory reservations or an eviction manager.
- 1976b7b fixes single-worker nested Qwen3.5 decoder depth: previous KV estimate
 counted1 instead of64 layers. No memory guard was bypassed. The model admitted
 the original full-single attempt and actually OOMed; do not recast it as a safe
 admission rejection. Subsequent small-model runs used corrected guard code.
- New small-model pairs have byte-identical request hashes and exact matching
 outputs. Astrea medium short prompts gave EOS-only reasoning/no visible answer;
 separate explicit-none short results are labeled, not silently substituted.
- Architectural context262,144 is not measured usable context. Successful full
 tests reached~11.4k; actual dynamic guard budgets/headroom are in DAY20.md.
 No maximum-context sweep, >2-Mini physical benchmark or multi-chat comparison
 was performed in this phase. Failed/mislabeled controls remain excluded but retained.
- Validation:794 unit tests passed in43.223s at the pre-release gate (earlier guard gate44.103s). Fake1/2/3/5-stage coverage is not
 proof of physical N-Mini performance. No test counts appear in the video/X drafts.
- Final real19-tool :18090 reply: “I'm online and ready to help.” .405s model
 TTFT,6.21tok/s,11.372s total, finish stop. First token may be hidden reasoning.
 Main Huihui24/40 KV16 saved for auto-restore; title sidecar healthy.

## Evidence and scope

Full raw paired matrix, failed controls and source scripts:
[DAY20.md](https://github.com/linuxbren/caravan/blob/day20-2026-11-09/docs/DAY20.md), [BENCHMARKS.md](https://github.com/linuxbren/caravan/blob/day20-2026-11-09/docs/BENCHMARKS.md),
[HERMES.md](https://github.com/linuxbren/caravan/blob/day20-2026-11-09/docs/HERMES.md), `handoff/lab/day20-speedups/`,
`handoff/lab/day20-single/`. Reboot chronology/logs remain in DAY20.md and
Omarchy `~/day19-video/reboot-watch2/`. Private Hermes instructions/tools stay
uncommitted. Historical Day19 film work remains an audit trail; the new reboot
recovery fix and unreleased work are credited to Day20, not rewritten into the
already-posted Day19 story. See `handoff/lab/videos/day20/` for video sources,
caption timings, measurement provenance and local draft text.

## Install / upgrade

Download `caravan-day20.zip` or `caravan-day20.tar.gz`, extract, then follow
[INSTALL.md](https://github.com/linuxbren/caravan/blob/day20-2026-11-09/INSTALL.md). For generated per-user Mac services,
see [SERVICES.md](https://github.com/linuxbren/caravan/blob/day20-2026-11-09/docs/SERVICES.md). Existing copies: preserve
unrelated files and `git pull --ff-only` on each Mini. Restart only a changed
service when necessary; a web-only restart must use `CARAVAN_WEB_KEEP_WORKERS=1`.
The wrap itself needs no restart. Source archives do not bundle weights, Python,
dependencies or compiled runtimes; video media is export-ignored. This is an
experimental source checkpoint, not a signed installer or a clean-Mac install claim.
