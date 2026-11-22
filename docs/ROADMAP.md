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

- **Day 27:** "guesses kept" under replies; `caravan bench --speedups`;
  GGUF Guess-ahead measured (+93% code edits, +34% short chats with a
  small helper) and tried by Auto-tune; a better GGUF Prompt lookup
  guesser; "Download helper for faster replies?" under the model, only
  with your click; Cancel Auto-tune feedback and one
  "Cancel Auto-tune and apply" action; model-neutral Guess-ahead
  wording; and one-Mac Topology (Balance and Thunderbolt hidden when
  only one Mac is live; a stopped Mac shows as offline, with a grey
  light). See [DAY27](DAY27.md).

- **Day 28 link order:** one route picker for every path between Macs.
  Fixed order: Thunderbolt, then wired Ethernet, then Wi-Fi, then anything
  else (Tailscale) last; the first link that answers and proves it is the
  paired Mac wins, re-checked on every load. Used by GGUF split tunnels,
  MLX split peer addresses, the remote-worker tunnel, stats, stop, update
  and pairing. Topology and `caravan status` show the link; falling back
  to Wi-Fi logs a warning. Found when a 2-Mac split drifted from about 19
  to 11 tok/s over Wi-Fi (15 ms) instead of Thunderbolt (0.6 ms). Before
  this the order was never written down or coded as one rule: Day 21
  designed "Thunderbolt only, no silent fallback" for MLX, and the GGUF
  tunnel followed the other Mac's network name.

## Planned dev days

- **Day 28 (done):** shootout and tuning rounds 1–3, one Mac vs
  two Macs on Qwen3 30B-A3B, gpt-oss 20B, Qwen3 14B and Llama 3.1 8B,
  on Caravan, LocalAI, Exo and llama.cpp rpc-server, plus Caravan v0.
  Auto-tune keeps the helper on 1-Mac and 2-Mac Llama 8B and on
  Qwen3 14B (1 and 2 Macs). Final numbers are in the
  [experiment log](../handoff/lab/experiments.md). The first-shootout
  Qwen3 30B 8k split write of 17.5 tok/s was the pre-fix Wi-Fi tunnel,
  not a remaining regression; after the Thunderbolt-first fix, round 3
  measured 25.18, faster than v0's 22.4.
- **Day 30 (done, released as
  [v0.9.0](https://github.com/linuxbren/caravan/releases/tag/v0.9.0)):**
  see [DAY30](DAY30.md).
  - **llama.cpp 1.0:** benched on Nov 19 against the pinned b12283 and
    no faster (short writes within ±2% on all four setups, first word on
    long prompts 1–4% slower with the helper). Not rolled in; the pin
    stays b12283.
  - **TensorFold: shelved.** TensorFold 1.2.10
    ([ashhart/TensorFold](https://github.com/ashhart/TensorFold)) could
    not run any of the three test models on these Macs: its native Llama
    engine needs an M5 or later, and it has no engine yet for Qwen3 MoE
    or gpt-oss. Removed from the test Macs. Revisit when it supports M4
    Macs and Qwen3 MoE.
  - **Native context for GGUF:** Chat window Auto runs a GGUF model as
    close to its trained window as memory allows, with no fixed 32K cap.
  - **One branch, `main`:** install and update read `main`; the old
    branch names are fast-forwarded with each release for older
    installs. Retire those fast-forwards once no older installs are left.
  - **Power-loss resume:** a request journal saves each chat before the
    model sees it, and after a power loss or crash Caravan runs
    unfinished chats again from the start once the model is back
    (`/api/jobs`, `caravan jobs`, "Finished after a restart"). Restores
    wait up to 60 s for Thunderbolt when it worked before, and a split
    left on Wi-Fi gets a note when Thunderbolt comes up. Passed a plug
    pull on both Macs and a five-prompt crash series.

- **Day 31 (in progress):** see [DAY31](DAY31.md).
  - **Part A, placement counts the chat window:** deciding between one
    Mac and a split now counts the memory for the model's default chat
    window (its trained window), not just its files. The default is the
    smallest placement that holds the full window; one Mac when it does.
    GGUF placement and Chat window Auto use the same numbers, MLX uses
    the model's real config, and unknown memory fails closed.
  - **Part B, load list shows only downloaded models:** the Settings list
    of models to load lists only models whose files are complete on the
    Mac or Macs that will run them, and updates right after a delete.

## Next candidates

1. **A helper for MLX on one Mac.** Today an MLX model uses a helper only
   when it is split across Macs; on one Mac GGUF is the faster choice for
   Qwen2.5 Coder 7B.
2. **First token with Guess-ahead.** The helper also reads the prompt, so
   the first word on long prompts comes about 10% later; Auto-tune could
   weigh that.
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

- Link order with three or more Macs: the picker checks the link from the
  1st Mac to each other Mac. The hop between two other Macs in a 3+ Mac MLX
  chain still uses its explicit Thunderbolt address (no fallback) until a
  Mac can run the picker for its own next hop.

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
