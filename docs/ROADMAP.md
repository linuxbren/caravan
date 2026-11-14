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
- **Day 26:** download progress under the model you clicked; `caravan bench`
  First token bars where shorter is sooner, saved bench results and
  `--from-averages` ("Last bench" or "Saved"); GGUF Prompt lookup and
  Guess-ahead (Auto, Off, On).
- **Day 26 updates:** a daily update check, an Update available badge,
  Check now and `caravan update --check`; Update now on this Mac and over
  Tailscale (refused on the local network and on Funnel, and hidden on the
  local network); the 1st Mac updates every other Mac first, then itself;
  a short Updates card with one line per Mac and Try again; a campfire
  Updating… button with a step line; and pages that reload themselves after
  an update. A new version can take about 5 minutes to appear. See
  [DAY26](DAY26.md).

## Day 27 candidates

1. **Measured Guess-ahead speed-ups.** Try Guess-ahead and Prompt lookup on
   realistic chats with a hit-rate readout (how many guessed words were
   kept), keep an ordinary baseline, and turn on only measured winners.
2. **GGUF closer to MLX.** Narrow the reading, writing and first-token gap
   between a GGUF model and its MLX counterpart, measured with
   `caravan bench`.
3. **A beginner switch for Advanced.** Hide the tuning rows behind one
   simple switch so a new user sees only what they need.
4. **Vision and voice.** Image input for models that support it, and
   listening first, following [VOICE](VOICE.md).
5. **Terminal UI.** A friendly terminal interface for chat, status and
   updates.
6. **Fresh install and FileVault.** Prove a clean account, a fresh install,
   and a FileVault reboot end to end.
7. **Security review.** An independent look at pairing, the browser page,
   the Tailscale share and the update path.

Earlier development-order items (Days 22–25) are kept in
[roadmap history](history/ROADMAP-LAB.md) and the daily logs.

Documentation, install instructions, package/source pins and deployment notes
are maintained **every development day**. Follow
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


## Mac pairing and repository trim follow-up

Implemented: discovery-driven **Add Macs**, short-lived one-use code, encrypted
key exchange, pinned SSH identity, atomic backed-up node config, N-node order
suggestion, and authenticated removal with offline retry. The native Remote
Login switch remains a user/admin permission. It is not automatic OS setup.
See [PAIRING](PAIRING.md) for security limitations and acceptance evidence.

Still required: independent security review, real fresh-account/FileVault and
native browser/Settings acceptance, address-change/cable/N-Mac deployment tests.
C++ is paused under `docs/history/cpp/`; [other clutter](CLUTTER.md) is listed for
approval only, not deleted or moved.
