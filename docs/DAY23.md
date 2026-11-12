# Day 23 — clean-install fixes

## Findings

The 1st node and 2nd node were installed again with the previous Caravan files
parked. This caught dependencies hidden by the development setup: the standard
GGUF engine was missing from the new installation, the picker treated the last
part of a multi-file model as a complete quantization, and download/load errors
were too technical or easy to miss. Old startup files could block setup.

## Changes

1. Every install and update prepares the official llama.cpp **b12283** macOS
   arm64 release in `~/.caravan/runtime/llama/b12283`. It checks the repository's
   SHA256 pin before extraction and keeps older versions. Standard launches
   prefer this runtime, including the peer RPC server; developer fallbacks remain.
   Doctor checks the engine. New paired Macs run the same installer.
2. Multi-part GGUF names resolve to the entire numbered set, with source byte
   sizes checked. Files stage out of the catalog until complete. Loading uses
   part 00001, and catalog/fit estimates sum all parts rather than just the last.
3. Small models use one-Mac whole-file downloads automatically. Larger supported
   models can use the isolated own-share engine if installed. Unsupported
   architecture/layout, multi-part sets, or a missing custom engine use the
   standard complete-file engine/RPC automatically. No advanced checkbox.
   Quant buttons explicitly say Download. Network/integrity failures still fail
   closed, not silently change trust or download corrupt data.
4. Complete GGUF sets appear in the normal catalog with the same ID used by the
   post-download Load prompt. MLX inventory/load-by-repository is covered too.
   Load errors are visible; unavailable defaults are labelled not downloaded.
   Remote downloads now record and check the exit code, not just process exit.
5. `caravan status` is one line: running, or the problem and next step.
   Detailed platform, runtime and service output lives in `caravan doctor`.
6. Old startup-file errors explain the problem and offer
   `--replace-old-services`. This explicit option backs up verified old files
   before unloading/replacing only the matching Caravan job. It refuses
   unrelated commands/labels and linked files; models/settings stay untouched.
7. Optional Tailscale discovery quietly falls back when missing, stopped,
   or returning non-JSON. It no longer floods the log.
8. Public install instructions say the new Mac / your first Mac consistently.
   Technical details live in the developer guide, not the beginner walkthrough.
9. Installation adds one marked PATH block to `.zprofile` and also to
   `.bash_profile` for bash login shells. Updates are idempotent; setup says
   to open a new Terminal window. Uninstall removes just the marked blocks.
10. Topology contains a dashed + Add a Mac card and pairing controls. One-Mac
    groups get a dismissible invitation remembered in local storage. Paired
    Mac cards retain one Remove button. The same pairing APIs/capability and
    loopback protections remain in force. The setup panel and helper page use
    two columns (new Mac / first Mac), stacked only on narrow screens, and
    the app's offline theme variables, colors, fonts, cards and buttons.
11. `caravan uninstall` removes all verified local Caravan startup jobs,
    tracked/exact-path owned workers, the entire `~/.caravan` tree, and only
    marked PATH/SSH entries. One confirmation explains the data loss and total
    size and reminds users to remove paired Macs first; `--yes` skips it.
    Unverified files and the unrelated Tailscale watchdog remain untouched.
    Uninstall never contacts another Mac or sweeps processes by name.

## Runtime pin and compatibility

URL: https://github.com/ggml-org/llama.cpp/releases/download/b12283/llama-b12283-bin-macos-arm64.tar.gz

SHA256: `bbc2abe2001293687540fb274bf4114b27b56af1fc166ee76730f64996d68b00`

The real archive was downloaded with curl on the box, hashed, listed and
extracted through Caravan's verifier. It contains `llama-server`,
`ggml-rpc-server` and the RPC dylibs. Inspection found the server's `--rpc`
option and RPC library entry points; the RPC executable has the device,
loopback-host, port and cache flags used by Caravan. Native execution is not
possible on these Linux hosts.

The official engine is for normal GGUF files and RPC, **not** Caravan's custom
CVGG/own-share format. That custom engine stays isolated at its original
`76a67730ffc7d650dffa4db04d96be84a59e7ef3` source revision; its existing
validation remains unchanged. A clean install uses standard GGUF/RPC rather
than attempting a developer toolchain build. Do not mix these two RPC engines
within one load. Official-to-official live split compatibility still needs
Mac verification; do not mistake archive/symbol checks for native proof.

## Verification and delivery

Initial portable regression suite: **1,155 tests passed on the box and the
development node**. The development node uses a separate checkout; its dirty
main checkout is not edited. Final follow-up counts and publication checks
are recorded in the delivery report and Obsidian Day 23 note. Coverage includes
checksum rejection, archive safety, runtime reuse, multipart completeness,
placement/fallback, catalog/load IDs, MLX discovery, service backups, status,
PATH idempotence, discovery fallback, UI structure/JavaScript parsing and
full-uninstall ownership/confirmation/SSH preservation.

Work is isolated on `clean-install-fixes`, based on `8511c31`. The dirty main
checkout on the development node is not edited. No 1st-node/2nd-node access,
SSH, synchronization, installation, restart or removal was performed.

The package is built with `scripts/package.sh` from the committed tree under
`/workspace/caravan-packages`; its adjacent `.sha256` file records the digest.
Publication is approved: the install channel and main advance together to the
release metadata commit. `packaging-version` selects the immutable source
commit immediately before that metadata-only commit and its codeload SHA256;
a commit cannot contain its own hash. The local source-package artifact is
built again from the final release tip. Linux fetch/check-only verification
is not native Mac acceptance.

### Live Mac acceptance

A later live pass on both Minis covered the Day 23 test list; see
[Live testing on both Minis](#live-testing-on-both-minis-2026-11-11-cst).
Remaining gates are listed there. The Linux portable suite is not a
substitute for those remaining checks.

## Live clean-install follow-up

- Settings, installed-model lists and Topology refresh after download completion
  and model load/stop/switch events. A five-second visible-page poll catches
  changes from another page; it pauses while hidden, prevents overlapping
  refreshes and preserves the user's selected model. No catalog search is
  repeated by this poll. The old download callback could not reach Settings
  because the functions lived in different JavaScript scopes; the shared
  refresh hook now crosses that boundary explicitly.
- Metadata/placement-only starter directories are not installed models and are
  omitted from Settings. Actual partial weight downloads retain their reasons.
  Existing developer paths and older peer inventories remain compatible. With
  no config at all, the UI starts with one local Mac, not a lab SSH inventory.
- The placement step always offers **+ Add a Mac**, prominently when nothing
  fits. It opens Topology's themed pairing panel, keeps the selected model and
  quant, then fetches fresh placement options and returns to that choice. A
  download still requires confirmation; pairing never starts one silently.
  Oversized GGUF downloads offer the same Add a Mac escape; after pairing
  they retain the automatic placement recommendation rather than exposing
  choices the GGUF downloader would ignore.
- Left and right drawers use about one third of desktop width and full width
  on narrow screens. Topology widens only while its two-column pairing panel
  is open; the pairing columns stack on narrow screens.
- Self-tuning already defaulted to `auto`, which **enables learning**, even
  without saved winners: the worker sets `_learn_enabled` unless explicitly
  disabled. The fresh config now records this default and the toggle clearly
  says **On**, including after status rendering. Other options remain Auto;
  saved Off choices, per-model pins and the environment opt-out are preserved.
  This is MLX self-tuning, not a promise of GGUF/llama.cpp auto-tuning or that
  every optimization is forced on before measurement. The worker's related
  automatic settings continue to use their existing safe defaults.

Portable tests exercise selection during in-flight refreshes, hidden-tab
pause/resume, overlap prevention, pairing return with new placement options,
metadata-only starter exclusion, legacy compatibility, responsive CSS, and
fresh-config worker learning before saved winners. Live Mac checks still need
real download/load transitions, pairing/discovery and the resized drawers.
The update replaces application source and refreshes the existing per-user
installation, preserving models, settings, explicit user choices and pairing.
No 1st-node or 2nd-node access is part of publication. To activate an update, run `caravan update` and refresh the page. Model
workers remain running when the model-running code did not change.

## Opt-in Tailscale access from other devices

The page stays on `127.0.0.1`. An opt-in Tailscale forward, off by default,
lets other devices on the same Tailscale network open it.

- `caravan remote on|off|status` uses `tailscale serve --bg --tcp <port>
  tcp://127.0.0.1:<port>` and `tailscale serve --tcp=<port> off`. Status is
  one plain line, with the Tailscale IP and MagicDNS addresses when on.
  Missing or signed-out Tailscale is explained in plain words. A hand-made
  serve on the same loopback port is recognized as on and recorded in
  `[remote] enabled = true`.
- Fresh install asks exactly one optional question, and only when Tailscale
  is installed and signed in and a terminal can be read (`/dev/tty` under
  `curl | bash`): "Open Caravan from your other devices over Tailscale?
  (y/N)". Default no. Updates and non-interactive installs skip it.
- Settings has an **Open from my other devices** switch (`GET`/`POST
  /api/remote`) that shows the addresses when on, and a plain note when
  Tailscale is not available.
- Uninstall removes Caravan's serve entry first. Doctor reports the state.
  Other Tailscale serve entries are never touched. Funnel is never enabled.

Portable tests cover the CLI, installer prompt (tty vs not, Tailscale
present vs absent), API, uninstall, doctor, adoption of an existing serve,
and the loopback bind. The box suite is **1,213 tests** (40 new). Live Mac checks still need a signed-in Tailscale
client and a second device on the same network. No 1st-node or 2nd-node
access is part of this change. To activate an update, run `caravan update` and refresh the page. If a
hand-made share is already on, `caravan remote status` and Settings should
show it as on after the update.

## Single-step update

`caravan update` is one command. It prints "Updating Caravan, the page will
be back in a few seconds.", fetches and verifies the same SHA-pinned source
as before, and finishes with the same one-line status as `caravan status`.
`caravan stop` and `caravan start` still work on their own.

- If the installed package already matches the pin, it prints "Caravan is
  already up to date." and changes nothing.
- After a verified extract, file hashes in `.caravan-package-files` decide
  what to restart. Model-running code is `agent/`, `runtime/`,
  `requirements-mac.lock` and `requirements-mac.txt`. If none of those
  changed, only the browser service is restarted (`CARAVAN_WEB_KEEP_WORKERS=1`
  still leaves a loaded model running). The optional proxy and aux services
  restart only if their own files, or the venv lock, changed.
- If model-running code changed, web-owned workers are stopped without
  clearing the saved last model, and the page's saved restore reloads it.
  Caravan prints "The model is reloading." A launchd worker job is stopped
  and started the same way. A paired Mac's worker is asked to stop with the
  same SSH command the app already uses; a missing peer does not fail the
  update. The other Mac still runs its previously installed code until you
  update it too — update every Mac, and if the model is split, update the
  other Macs first or let the reload finish after every Mac is current.
- If fetch, verify, install or start fails after the running services were
  touched, the previous source backup is restored, the old installer is
  rerun to put the previous packages back, and the old services are started.
  The only user line is: "The update failed. Caravan is back on the previous
  version. Check your internet connection and try again." Caravan is not
  left stopped.
- The first update from a Mini still running the previous command can also
  be just `caravan update`. That older command already fetches the current
  bootstrap, which now stops and starts as needed. It may print an extra
  leftover "run caravan start when ready" line, which can be ignored; the
  page is already coming back. After this one update, that extra line is gone.

Portable tests cover an already-current install, a web-only change that
keeps workers, a worker-code change that reloads and keeps the saved model,
install and start failures that roll back and restart the old version, and
the services-loaded path no longer refusing. The box suite is **1,238 tests**
(24 new). `caravan stop` is unchanged. `caravan start` later gained
clearer messages; see below. No 1st-node or 2nd-node access is part of
this change. To activate: `caravan update`, then refresh the page.

## Clearer start messages

`caravan start` says "Caravan started" when the service is just brought
up, and "Caravan is running" when it is already loaded. Both lines tell
you to run `caravan open`. The old "Service started (or already running)"
line is gone. Two portable tests cover the two cases. This goes out with
the Day 23 tag.

## Live testing on both Minis (2026-11-11 CST)

Brenden completed live testing on both Minis against the then-current
pin (`15f4b32`, source `254b401`). Every item on the Day 23 test list
passed:

1. Update both Macs with `caravan update` (the other Mac first when a
   split model is loaded), then refresh the browser. The model stayed
   loaded.
2. Turn on "Open from my other devices" in Settings and open the page
   from another device on the same Tailscale network.
3. Download a model to one Mac, then load it and chat.
4. Download a model that needs both Macs, pick the split placement,
   then load it and chat. One-Mac and split downloads were each tried
   as GGUF and as MLX.
5. Start a download, choose Add a Mac on the placement screen, and
   return to the same choice. A new Mac did not need to be finished
   pairing for this check.
6. Restart a Mini and confirm Caravan comes back on its own.
7. `caravan uninstall` on one Mini: one confirmation, then nothing
   left behind and remote access off. Reinstall used the install line.

Portable suite at this source: **1,240 tests passed** in 52.988 s on
the development node (2 new, for the start messages).

### Remaining gates

These were not part of this live pass:

- Fresh account setup, Gatekeeper behavior, and FileVault unlock/login.
- Old-startup-file backup and replacement under real launchd.
- A finished pairing of a new Mac (Add a Mac from placement was checked
  through the return-to-choice path only).
- Standard RPC loads for unsupported own-share architectures, and a
  complete multi-part GGUF set specifically.

The Linux portable suite is not a substitute for those remaining checks.
