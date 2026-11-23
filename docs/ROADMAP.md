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

- **Day 31 (done, released as
  [v0.9.1](https://github.com/linuxbren/caravan/releases/tag/v0.9.1)):**
  see [DAY31](DAY31.md).
  - **Part A, placement counts the chat window:** deciding between one
    Mac and a split now counts the memory for the model's default chat
    window (its trained window), not just its files. The default is the
    smallest placement that holds the full window; one Mac when it does.
    GGUF placement and Chat window Auto use the same numbers, MLX uses
    the model's real config, and unknown memory fails closed.
  - **Part B, load list shows only downloaded models:** the Settings list
    of models to load lists only models whose files are complete on the
    Mac or Macs that will run them, and updates right after a delete.
  - **Part C, Topology agrees with Settings:** Topology's On disk list uses
    the same scans as Settings (GGUF models included, no `caches` folder),
    marks models Settings can't load, and can delete GGUF models.
  - **Code folder fallback:** a Mac without a saved code path falls back
    to the install folder, not an old developer folder.
  - **Follow-up, "context" wording
    ([v0.9.2](https://github.com/linuxbren/caravan/releases/tag/v0.9.2)):**
    the app says "context" instead of "window" everywhere it means the
    model's context; the Settings row is now **Context**.
  - **Follow-up, 4-bit MLX split load fix
    ([v0.9.3](https://github.com/linuxbren/caravan/releases/tag/v0.9.3)):**
    a pre-quantized MLX model loads split across Macs even when one piece
    of the other Mac's layers straddles two shard files (Qwen3 32B 4-bit).

- **Day 32 (in progress): localization.** See [DAY32](DAY32.md).
  - **Part A, version label
    ([v0.9.4](https://github.com/linuxbren/caravan/releases/tag/v0.9.4)):**
    Settings shows the installed release next to its title, with the daily
    update check's status ("up to date" or "update available", which leads
    to Update now). `caravan --version`, `caravan status` and
    `caravan doctor` show the same version. The number comes from a
    `VERSION` file in each release's source and the build from the
    installed pin, never from the page.
  - **Part A fix, daily update check
    ([v0.9.5](https://github.com/linuxbren/caravan/releases/tag/v0.9.5)),
    done:** with **Check for updates daily** off, the label, badge and Mac
    lines show no update status (live, no reload); an audit of the daily
    check also fixed a loop that stopped after one error, offline answers
    that kept saying "up to date", broken replies and a wrong-clock case.
  - **Part B, header layout ([v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6)), done:**
    the model/status pill moves above and outside the chat card's top-left
    corner, just outside its border (where the CHAT label was); **Update
    available** moves right of the theme picker; nothing wraps at narrow
    widths (long model names end in "…" with the full name on hover). See
    [DAY32](DAY32.md#part-b-header-layout-v096).
  - **Part B, chat message queue ([v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6)), done:** while the model answers, the prompt box stays typeable and
    Send reads **Queue**. Queued messages send in order when the answer
    finishes (also after an error or Stop), shown as a floating strip just
    above the prompt box, one chip per message with a × to cancel. A
    queued message is journaled only when it sends. See
    [DAY32](DAY32.md#part-b-chat-message-queue-v096).
  - **Part B, Ollama Cloud API key ([v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6)), done:** Settings gets a **Cloud API keys**
    section for the Ollama Cloud key (the only cloud source Models can
    search; masked, editable, removable). Picking a cloud model with no key asks for it inline, then
    carries on. Cloud models say **Load**, not Download. Keys are kept in
    `~/.caravan/cloud-keys.json` (0600), never logged, and the page sees
    only the last 4 characters. The key is saved now; chatting with Ollama
    Cloud models comes later (see Next candidates). See
    [DAY32](DAY32.md#part-b-ollama-cloud-api-key-v096).
  - **Part B, Stop a reply ([v0.9.6](https://github.com/linuxbren/caravan/releases/tag/v0.9.6)), done:** a **Stop** button under Send/Queue while a reply is
    written. It ends the reply on the server and the model (the MLX lead
    and split helper stop, even mid-prompt; llama-server cancels), keeps
    the words so far marked "(stopped)", closes the journal job as
    "stopped" so it never runs again, and still sends queued messages.
    See [DAY32](DAY32.md#part-b-stop-a-reply-v096).
  - **Localization (main theme; Day 32 stays open for it).**
    - **Step 1, English strings file ([v0.9.7](https://github.com/linuxbren/caravan/releases/tag/v0.9.7), done):** the web
      page, the `caravan` command, the installers and the server and
      worker messages read their text from one English file,
      `locales/en.json` (2,299 strings keyed by name), with English as the
      fallback. Code checks message codes instead of English words;
      plurals, numbers, units and lists go through locale helpers. The
      English text is unchanged. No other language yet. See [DAY32](DAY32.md#localization-step-1-english-strings-file).
    - **Spanish ([v0.9.9](https://github.com/linuxbren/caravan/releases/tag/v0.9.9), done):** first language after
      English. A CLDR plural engine (built so Japanese, Simplified Chinese
      and Russian can drop in later), `locales/es.json` for every current
      key, a Settings language picker that switches the page live and
      persists (`CARAVAN_LANG` > Settings > the Mac's language > English),
      Spanish number/date formatting, and layout checks at 1280 and 375 px.
      Spanish is marked beta in the picker until a native speaker reviews
      it. See [DAY32](DAY32.md#spanish-v099).
    - **Russian ([v0.9.10](https://github.com/linuxbren/caravan/releases/tag/v0.9.10), done):** next language after
      Spanish. `locales/ru.json` for every current key (natural Russian,
      informal *ты*), one/few/many/other plural keys everywhere counts
      appear, **Русский (beta)** in the Settings picker and the installer
      shell block, Russian number/date formatting (space as the thousands
      separator, decimal comma, "и" lists, genitive months), and Cyrillic
      layout checks at 1280 and 375 px. Russian is marked beta until a
      native speaker reviews it. See [DAY32](DAY32.md#russian-v0910).
    - **Japanese (in progress, pending review):** next language after
      Russian. `locales/ja.json` for every current key (natural,
      polite-casual Japanese, です/ます where it suits the UI), `_other`
      only for plural keys, **日本語 (beta)** in the Settings picker and
      the installer shell block, Japanese number/date formatting
      (2026年11月13日, 、 lists), CJK line breaking, and layout checks at
      1280 and 375 px. Japanese is marked beta until a native speaker
      reviews it. See [DAY32](DAY32.md#japanese-in-progress-pending-review).
  - **GGUF placement ([v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8), done):**
    every GGUF download uses the same Step 2 placement chooser as MLX,
    for every fit color: 1 Mini / split across K Minis / copy to all.
    Unfit options stay visible and disabled with the reason; the default
    is the smallest placement that fits; the choice is saved and honored
    at download and at load. See [DAY32](DAY32.md#gguf-placement-roadmap-9).

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
8. **Chat with Ollama Cloud models.** Day 32 saves the Ollama Cloud key
   (Settings → Cloud API keys) and cloud models say **Load**, but chats
   still only go to the Macs. Next: route `/api/chat` to Ollama Cloud when
   a CLOUD model is picked, with a first-chat notice that the message
   leaves your Macs, and keep the key out of logs, the journal and saved
   chats. Other providers come only if Models can search them.
9. **Confirm before every download.** Done in
   [v0.9.8](https://github.com/linuxbren/caravan/releases/tag/v0.9.8).
   GGUF downloads use the same Step 2 placement chooser as MLX, for every
   fit color. See [DAY32](DAY32.md#gguf-placement-roadmap-9).

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
