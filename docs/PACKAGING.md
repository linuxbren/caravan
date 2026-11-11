# Mac package status

## Implemented

- One reviewed shell command, native Apple Silicon/macOS 14+ only. No sudo,
  preinstalled Python, Homebrew, Git or Xcode required by the bootstrap.
- Development channel selects a SHA-pinned source tarball and SHA-256. uv
  0.8.22's Apple Silicon archive is checksum-verified; it installs private Python
  3.12.11. System Python and shell profiles are untouched.
- Per-user web service and local-only browser, no bundled models or credentials.
- Safe start/stop/status/open/doctor/update/uninstall/add-mini command. Uninstall
  retains source/runtime/models/settings; stop does not kill model workers.
- Immutable committed-tree source archive builder and checksum. These are
  **source packages**, not compiled, signed or notarized application bundles.
- Current documentation and required daily release checklist.

## Distribution choice

A signed, notarized `.app`/`.pkg` would be the nicest consumer experience, but
we do not have an Apple Developer ID/signing setup. An unsigned package gives
Gatekeeper warnings and is not an improvement over a reviewed command. Do not
ship a warning-prone app, strip quarantine or tell users to disable protection.
No Homebrew tap is created: it adds another prerequisite and distribution
maintenance without removing the model/network setup. Keep both on the plan.

The current channel follows development and trusts the repository's HTTPS
bootstrap/manifest. The source archive itself is pinned and checksummed. This
is not independent signature verification. Easy-package dependencies use `requirements-mac.lock` with exact versions and
binary wheels only (not a hash-locked offline bundle). Developer/source installs
retain `requirements-mac.txt`. uv's managed Python is a third-party CPython
build; it is not an Apple Python distribution. See Astral's
[Python documentation](https://docs.astral.sh/uv/concepts/python-versions/).

`bash scripts/package.sh REF OUTPUT_DIRECTORY` produces an archive plus SHA-256
from the committed tree. Keep existing Day 21 release assets/tag unchanged;
this follow-up's artifacts are prepared for a later authorized release.

## Remaining acceptance gates (do not call “fireproof” yet)

- Entire bootstrap on a fresh macOS user with no developer tooling; non-admin
  account and FileVault-on unlock/login behavior. An isolated HOME is **not** a
  new macOS user or proof of all clean-machine cases.
- Hash-locked dependency artifacts/wheel availability across supported macOS versions,
  offline download-failure tests, and transactional update/rollback (source
  backups exist; environment rollback is manual).
- Independent security review and native/fresh-account acceptance of the new short-code pairing UI. Day 21 discovery itself only
  inventories/checks configured trusted peers; it cannot apply a plan.
- Signed/notarized app or package and updater. The publisher needs an Apple Developer
  membership/Developer ID and a secure signing workflow; do not share keys here.
- Bundled/pinned optional GGUF runtime; independent per-Mac GGUF loading is Day22.
- Physical inference on 3+ Macs. N-stage planning/socket tests are not that proof.

Advanced isolated tests can use `--name UNIQUE_NAME --port UNUSED_PORT --no-start`
and `caravan start/stop/uninstall --name UNIQUE_NAME`. Never register a test
under a production service label, even with a temporary HOME.

## Verification record

See the [follow-up record in DAY21.md](DAY21.md). Portable script/unit tests and isolated
Mac setup are recorded separately from live reboot/inference evidence.


## Pairing/trim follow-up verification

- Portable suite (with `requirements-test.txt`): **1,095 tests passed**, including
  35 new protocol/config/removal/local-management tests. Full output is retained
  on the development box; this is not a native macOS acceptance result.
- Real HTTP add/remove smoke between two scratch homes on the Linux box passed;
  no production SSH files/config were used. SSH verification is mocked in those
  protocol tests; `ssh -G` checks the actual generated strict OpenSSH settings.
- All four new pinned dependencies were downloaded successfully as binary
  wheels for managed Apple Silicon Python 3.12 (no compiler/CLT fallback).
- Read-only checks of the existing Macs confirmed current checkouts; the second
  Mac does not yet have the new PAKE dependency. No restart, trust/config edit,
  model action or reboot was performed by this task.
- Pending: isolated protocol and real SSH/native browser/Remote Login tests on
  macOS, fresh-account/FileVault test, security review, pushed-channel bootstrap
  verification and updating the package pin after the reviewed code is pushed.
  Do not call the new pairing feature live-proven until those are recorded.

The C++ experiment was parked with Git renames and resume instructions. Other
cleanup is an [approval-only inventory](CLUTTER.md), not a deletion plan already
executed. No release or tag was changed for this follow-up.
