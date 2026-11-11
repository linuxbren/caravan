# Add Macs: design, safety and remaining tests

For everyday steps use [Install → Add Minis](../INSTALL.md#add-minis). This is the
technical explanation, not another manual installation procedure.

## The Mac permission

Caravan opens **System Settings → General → Sharing → Remote Login** using
`x-apple.systempreferences:com.apple.preferences.sharing?Services_RemoteLogin`.
The current account must be allowed there. If a macOS update changes the deep
link, navigate to that same pane. An administrator may have to approve it.

We deliberately do **not** run `sudo systemsetup -setremotelogin on`. Modern
macOS can require Full Disk Access for that command as well as administrator
rights. Granting Terminal that broad permission just to avoid one native switch
is a worse tradeoff. This OS permission cannot honestly be automated away by an
ordinary per-user installer. See [Apple's Remote Login instructions](https://support.apple.com/guide/mac-help/mchlp1066/mac)
and [Jamf's Settings/deep-link notes](https://github.com/Jamf-Concepts/setup-checklist/blob/main/Profile/ScriptStep.md).

## What discovery does, and does not prove

The web service advertises its pairing endpoint with the existing macOS
Bonjour adapter. Discovery resolves nearby `_caravan._tcp` services (including
Thunderbolt/local-link addresses) and existing online Tailscale peers. It does
not create a tailnet, scan arbitrary subnets, change routes, or trust names.
Private resolved addresses are checked before connecting; no redirect following
or second hostname lookup is used for a protocol request. Public addresses are
refused. The default pairing listener is TCP 8197; HTTP connections and body
sizes are bounded. IPv4 LAN/link-local and tailnet discovery are the supported
initial path; an IPv6-only deployment is not yet supported.

The private management page is loopback-only and validates Host, Origin and
an anti-CSRF token. A per-account capability in a private file must first open
its browser session. Other local accounts cannot obtain the pairing code just
by fetching localhost. A private HTML handoff avoids putting that capability
in `open` command arguments or HTTP access logs; the page erases its URL fragment
and uses an HttpOnly SameSite cookie. These files are under
`~/.caravan/pairing/` with private permissions; never share that directory.
Normal app access over a LAN address or tailnet does not grant pairing controls.

## Human check and encrypted channel

- The new Mac displays an eight-digit code, also printed explicitly by a fresh
  installer (never by the background service). It lasts five minutes, is
  single-use, and has a durable global budget of five handshake attempts.
  Restarting the service or changing source addresses does not reset the budget.
  Exhausted/expired codes require an explicit local **Show a new code** action.
- SPAKE2 (`spake2==0.9`) authenticates the short code without sending it over
  HTTP. Roles and offer ID are bound into the exchange. AES-GCM provides key
  confirmation, protects enrollment metadata, and binds direction/session.
  The first Mac sends no SSH key until it has checked key confirmation.
- A fresh, dedicated Ed25519 identity is generated **for each paired Mac**.
  Existing private keys are never read or uploaded. The helper adds only its
  public key to a marked `authorized_keys` entry. Its SSH host public key is
  returned inside the authenticated encrypted reply, then pinned in a private
  per-peer known-hosts file. Host checks are never disabled.
- An actual strict SSH check, using an isolated app-owned SSH config (no
  fallback to personal identity files), must pass before the UI says Connected. A wrong
  code cannot write trust/config. Failed or interrupted enrollment retains a
  cleanup credential when rollback cannot be confirmed; the page shows it.
- Config and managed SSH blocks are validated before writing, updated through
  atomic replacements with backups and a recoverable intent journal, and
  preserve unrelated settings. Existing legacy inventory is materialized
  before appending a new Mac. Orders append automatically; Balance Auto chooses
  model placement/split. Pairing does not reload any model. External configs outside the account's home are refused; use the developer/manual route for those installations.

**Scope matters:** OpenSSH's `restrict` disables PTY, agent/X11 forwarding and
user rc. Forwarding destinations and requested remote listeners are limited to the
worker's loopback HTTP address; sources must be private/local. The separate
`sshd_config` must retain macOS's `GatewayPorts no` default so the SSH server
does not override a loopback listen request. However the first Mac
still has **command execution as the paired account** to start Caravan workers.
This is not a sandbox or a replacement for a separate restricted Mac account.
Pair only Macs you control and accounts you trust. Do not expose either service
or Remote Login to the internet. Pairing authenticates setup; it does not add
transport encryption to the existing model-data links.

The Python SPAKE2 implementation is not constant-time. This is an experimental
feature, **not an independently audited or signed security product**. Private
network scope, the short window, bounded attempts and user confirmation limit
exposure; a protocol/security review remains required before calling it ready
for untrusted networks. See [upstream security notes](https://github.com/warner/python-spake2).

## Removal and recovery

Removal uses authenticated encryption under a separate per-pair random secret;
its reply echoes a fresh nonce so a forged HTTP success cannot silently leave
SSH trust behind. It removes only marked app-owned keys, SSH/config blocks and
per-peer private key/known-host files. Model files stay. A small private receipt
allows an acknowledged removal to be retried after a lost reply. Re-pairing uses
a new credential, so an old request cannot revoke the new connection.

Unload first. Both the first Mac's manager and the helper's model/data listeners
are checked conservatively. Offline removal stays pending with its credential
and retries; it is not reported as complete. Bring the helper back before
uninstalling. Uninstalling the web service alone does **not** revoke SSH trust.
Macs that change address are found again through their saved Bonjour name or
stable tailnet address; addresses, cabling and physical N-Mac inference still
need real deployment verification.

## Native acceptance: Day 22 follow-up

The real curl installer passed on the second Mac under a private sibling HOME,
using managed Python 3.12.11 and `--no-start` / a unique service name. The source
checksum and installed marker were verified. No login service or browser was
started for that isolated install.

`tools/pairing_smoke.py` then paired physical Macs over Bonjour through the same
private UI APIs: helper-page code obtained, code submitted, PAKE exchange,
automatic host pin and config, an actual dedicated-key SSH command, and removal
on both sides. A separate unprivileged sshd, test host key, scratch HOME and
random ports kept production SSH/config untouched. Production Remote Login on
TCP 22 was already reachable on both Macs; no toggle, sudo or Full Disk Access
request was needed. This availability check is not a privileged macOS settings
read; the dedicated-key command is the authentication proof.

All 44 pairing/harness tests also passed natively on the first Mac. The full
portable suite passed 1,107 tests. Huihui remained ready on its saved split,
answered before/after, and kept the same worker PID. Only the first Mac's web
service was restarted, with worker preservation already set. Test servers were
stopped and their pairing keys removed; private scratch installations remain
for inspection. See [DAY22](DAY22.md) for the complete evidence and boundaries.

Not tested here: a fresh macOS account, FileVault unlock/login, native Safari
rendering or clicking the System Settings switch (it was already on). The UI
API test is not a claim of manual browser click-through or a security audit.

## Acceptance evidence

See the task's test record in [PACKAGING](PACKAGING.md). Protocol/config tests
run in isolated homes with synthetic keys. They are not a security audit,
FileVault test, fresh-account install, or proof of three-or-more-Mac inference.
The existing live two-Mac model must not be re-paired or unloaded for this test.
