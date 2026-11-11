# Roadmap

Caravan helps Macs at home run models that do not fit on one Mac. More memory,
or adding Macs, lets larger models fit. Caravan checks capacity rather than
assuming a particular Mac configuration.

See [node names](README.md#names-used-in-these-guides), [installation](../INSTALL.md)
and [package status](PACKAGING.md). Older checkpoints, measured numbers and
superseded proposals are preserved in [roadmap history](history/ROADMAP-LAB.md)
and the daily logs, not mixed into current setup instructions.

## Available now

- Browser model search/download/load/chat, per-Mac placement and file accounting.
- MLX models on one Mac or an ordered set of Macs, with Balance previews and
  explicit reload progress. Live inference has been measured on two physical
  Macs; planning/socket tests do not prove three-or-more physical Mac behavior.
- Session/prefix reuse and saved conversation caches where the model supports it.
- Login startup and last-successful-model restore. Temporary node, memory and
  link readiness failures retry within a bounded window; Unload saves “restore
  nothing.” Reboot evidence is in [DAY21](DAY21.md).
- Read-only Thunderbolt inventory and explicit link verification. This does
  not pair unknown Macs or apply routes automatically.
- Optional GGUF through a separately built patched llama.cpp runtime. The
  current normal RPC path still needs the full model on the lead Mac.
- Simple Mac bootstrap, private Python, locked binary dependency versions,
  doctor, safe per-user commands and prepared checksummed source packages.
  This is not a signed/notarized consumer application.

## Current development order

1. **Day 22 — independent GGUF storage and loading.** Each Mac should download
   and load only its own assigned tensors, including small tensors. Do not
   present incomplete GGUF files as ordinary standalone models. Experimental
   sharding/loader work is not a bundled runtime or a new performance claim.
2. **Day 23 — guess-ahead and speed improvements.** Test prompt lookup with an
   acceptance-rate readout, matching-model multi-token prediction and other
   acceleration ideas. Compare realistic prompts as well as favorable cases;
   keep an ordinary baseline and reject regressions.
3. **Day 24 — safe cleanup, repeated runs and model profiles.** Protect active
   files/services, obtain explicit per-file cleanup approval, repeat matching
   speed runs, and save settings separately for each model. Use identical
   prompts/models, report medians and include prompt-reading time.
4. **Day 25 — terminal UI and remaining packaging work.** A friendly terminal
   interface, automatic trusted-Mac onboarding, clean-account/FileVault proof,
   supported-macOS wheel checks, transactional update/rollback and a signed,
   notarized Mac package/updater. Signing requires the publisher's Apple
   Developer ID and secure signing workflow.

Documentation, install instructions, package/source pins and deployment notes
are maintained **every development day**, not deferred to Day 25. Follow
[the daily checklist](RELEASES.md). Change priorities when a newly observed
correctness or safety problem needs attention.

## Rules for model placement

- Each Mac keeps its own share of model files; download from the source, not
  by copying another Mac's files. Current GGUF RPC independence is incomplete.
- Do not delete files needed by a running model, saved plan or owned service.
- Revalidate current files and available memory before applying a plan. Unknown
  capacity or identity fails closed, rather than assuming a favorable answer.
- Build for an ordered set of Macs, not hard-coded first/second-Mac aliases.

## Further work and known limits

- Authenticate model transport and turn verified link previews into safely
  applied plans. Read-only SSH verification alone is not transport security.
- Measure on three or more physical Macs before broader capacity/speed claims.
- Improve split-model scheduling/guess-ahead overlap without trading away
  correctness, cache persistence or individual-chat responsiveness.
- Keep optional cloud/catalog/conversion features explicit; never silently
  download, convert or upload a model as a side effect of a preview.
- Keep cleanup, disk accounting and download recovery honest on every Mac.
- General-purpose client/terminal integration can follow the stable terminal
  interface. No particular personal terminal app or development OS is required.
- Tensor parallelism, fused kernels, automatic pruning and deeper platform
  integrations remain research/parked work, not installation prerequisites.

Release tags are immutable checkpoints. Later fixes and the development install
channel may be newer than a published tag. See [CHANGELOG](../CHANGELOG.md)
and [daily release procedure](RELEASES.md) for the distinction.
