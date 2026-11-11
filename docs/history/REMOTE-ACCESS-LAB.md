# Historical development record

These notes describe an earlier test environment, not installation defaults.
For current instructions use the [documentation index](../README.md).
Older machine names are explained there.

# Remote access without a Tailscale single point of failure

## Verified 2026-11-09 (CST)

Brenden found EXO2's Tailscale needed updating and was off after the previous
reboot. Earlier checks tried only `ssh exo2`; they did **not** establish that LAN
SSH was down. Omarchy had **no `~/.ssh/config`**. Its `/etc/hosts` maps `exo1`
to `100.68.62.20` and `exo2` to `100.90.134.95`: these are Tailscale addresses,
not independent LAN routes or MagicDNS fallbacks.

During today's move, both EXO2 tailnet and LAN SSH initially timed out. EXO2
returned without intervention from this task; the return watch observed tailnet
SSH at **17:50:56 CST**. After Brenden moved it upstairs and connected the cable,
all five access paths below passed. We did not reboot either Mini, disconnect
Tailscale, start/restart any Caravan service, load a model, or begin the Day 19
restoration test. Do not interpret today's transient timeouts as proof of a new
Tailscale or Remote Login defect.

## Network inventory (observed, not static assignments)

Omarchy is on the same `192.168.1.0/24` LAN at `192.168.1.29`, Ethernet `enp6s0`.

| Mini | LAN / mDNS | Active Wi-Fi MAC (`en1`) | Thunderbolt (`en2`) |
| --- | --- | --- | --- |
| EXO1 | `192.168.1.79`, `prf-hays-exo01-2.local` | `92:29:8d:cc:fc:79` | IPv4 `169.254.242.28`; IPv6 `fe80::c21:90cb:b71f:e98c`; MAC `36:a0:83:e8:0d:c0` |
| EXO2 | `192.168.1.38`, `prf-hays-exo02.local` | `d0:11:e5:d7:30:24` | IPv4 `169.254.155.4`; IPv6 `fe80::8c3:dd7:5d56:b1ed`; MAC `36:d3:43:0a:d5:00` |

Both Minis' wired Ethernet `en0` is currently inactive. Its hardware MAC is
`d0:11:e5:9a:67:fe` on EXO1 and `d0:11:e5:d9:11:be` on EXO2. Wi-Fi private
addresses can change; use the address shown by the router if making a reservation.
There is no configured service literally named "Thunderbolt Bridge" on EXO1;
its services are named `EXO Thunderbolt 1`, `EXO Thunderbolt 2`, and
`EXO Thunderbolt 4`. The verified cable/interface is `en2` on each Mini.

LAN DHCP leases and Thunderbolt IPv4 link-local addresses can change. The LAN
aliases use working `.local` mDNS names rather than those leases. No router
reservation is required for these aliases; reservations are recommended only
if also relying on numeric LAN addresses. Multicast/mDNS must be permitted on
the same LAN; it is not an off-site recovery channel.

## Omarchy aliases and fallback helper

Before creating `~/.ssh/config`, saved an absent-config marker at
`~/.ssh/config.before-caravan-remote-access-20261109-175152`. Existing `/etc/hosts`,
SSH keys and known-host entries were left unchanged. Config mode is `0600`.
New aliases verify the existing `exo1`/`exo2` host keys with `HostKeyAlias` and
`StrictHostKeyChecking yes`; no host-key checking was disabled.

| Command | Transport | Result |
| --- | --- | --- |
| `ssh exo1 hostname` | Tailscale, existing `/etc/hosts` mapping | PASS: `prf-hays-exo01-2.local` |
| `ssh exo2 hostname` | Tailscale, existing `/etc/hosts` mapping | PASS: `prf-hays-exo02.local` |
| `ssh exo1-lan hostname` | mDNS / Wi-Fi LAN, independent of Tailscale | PASS: `prf-hays-exo01-2.local` |
| `ssh exo2-lan hostname` | mDNS / Wi-Fi LAN, independent of Tailscale | PASS: `prf-hays-exo02.local` |
| `ssh exo2-via-exo1 hostname` | Omarchy -> EXO1 LAN -> EXO2 Thunderbolt | PASS: `prf-hays-exo02.local` |

The Thunderbolt stanza uses actual `ProxyJump exo1-lan`, not `exo1`, so neither
hop depends on Tailscale. Its target is EXO2's observed link-local IPv6, scoped
to **EXO1's** cable interface; IPv6 avoids depending on the changing link-local
IPv4 lease. In `~/.ssh/config` the literal percent sign must be escaped:

```sshconfig
Host exo1-lan
    HostName prf-hays-exo01-2.local
    User brenden
    HostKeyAlias exo1
    StrictHostKeyChecking yes
    ConnectTimeout 8

Host exo2-lan
    HostName prf-hays-exo02.local
    User brenden
    HostKeyAlias exo2
    StrictHostKeyChecking yes
    ConnectTimeout 8

Host exo2-via-exo1
    HostName fe80::8c3:dd7:5d56:b1ed%%en2
    User brenden
    HostKeyAlias exo2
    ProxyJump exo1-lan
    StrictHostKeyChecking yes
    ConnectTimeout 8
```

EXO1's `route -n get -inet6 fe80::8c3:dd7:5d56:b1ed%en2` explicitly reported
**interface en2**, confirming the jump's second leg is Thunderbolt, not Wi-Fi.
The IPv6 address/interface is still an observed endpoint, **not guaranteed
immutable**. If recabling/changing ports or macOS changes it, read `ifconfig`
on both Minis through LAN and update this stanza; verify the route again.
No static network addresses or routes were installed.

Installed executable `~/.local/bin/caravan-ssh` on Omarchy (mode `0700`):

```sh
~/.local/bin/caravan-ssh --check exo1
~/.local/bin/caravan-ssh --check exo2
~/.local/bin/caravan-ssh exo2 hostname
~/.local/bin/caravan-ssh exo1
```

It probes authenticated, known-key SSH with `BatchMode=yes`, a six-second
connection timeout and a 22-second whole-probe timeout. Order is Tailscale,
then LAN, then EXO2's Thunderbolt jump. `--check` reports every route and succeeds
if at least one works. Normal mode opens the first working route, forwarding
command arguments without local shell interpolation. It does not retry a remote
command already started, avoiding duplicate destructive operations. It is an
on-demand helper, not a background network scanner or unattended password tool.

## Both Minis: Tailscale persistence and recovery

Both run the **standalone macOS app**, bundle ID `io.tailscale.ipn.macsys`, at
`/Applications/Tailscale.app`, not App Store or Homebrew `tailscaled`.

| Setting | EXO1 | EXO2 |
| --- | --- | --- |
| Version | `1.102.3` | `1.104.5` (observed after return) |
| Backend | Running | Running |
| Update checks / automatic installation | Already enabled; CLI reaffirmed | Already enabled; CLI reaffirmed |
| `TailscaleStartOnLogin` | Already true; login helper loaded | Already true; login helper loaded |
| Wants connection / logged out / shields up | true / false / false | true / false / false |
| macOS Remote Login (`com.openssh.sshd`) | enabled; LAN SSH passed | enabled; LAN and TB SSH passed |
| macOS automatic login | `brenden` | `brenden`; FileVault Off |

Reaffirmed only the supported update settings, without sudo:

```sh
/Applications/Tailscale.app/Contents/MacOS/Tailscale set --auto-update=true --update-check=true
```

No client update was forced, no login/security/network preferences were reset,
and no app or Caravan process was restarted. EXO1's older version is not evidence
that auto-update is disabled. Sparkle can still require a confirmation click.
Remote Login's socket-activated launchd service may say "not running" between
connections; enabled sockets and successful SSH are the relevant checks.

Added a separate **user-session**, non-root guard on each Mini:

- Script: `~/Library/Application Support/Caravan/remote-access/tailscale-watchdog.py`
  (mode `0700`, interpreter `/usr/bin/python3`, verified Python 3.9.6).
- LaunchAgent: `~/Library/LaunchAgents/com.caravan.remote-access.tailscale-watchdog.plist`
  (mode `0600`), `RunAtLoad=true`, `StartInterval=120`, background process.
- Log: `~/Library/Logs/Caravan/tailscale-watchdog.log` (no status JSON, credentials
  or login URLs are written). This small log is not automatically rotated.
- If the app process is absent, opens the existing app hidden with
  `/usr/bin/open -gj -a /Applications/Tailscale.app`.
- Otherwise reads `tailscale status --json`; only **Stopped** triggers plain
  `tailscale up` (no flags, preserving existing preferences), bounded by a
  20-second subprocess timeout. Running is a no-op. NeedsLogin, errors and
  timeouts are logged without trying credentials, sudo, reinstalling the app,
  disabling security, or changing DNS/routes/ACLs.
- Both agents bootstrapped successfully and exited **0** on their first tick.
  "not running" between two-minute ticks is normal. No `KeepAlive` busy loop.
- This intentionally reconnects a manually disconnected client on the next tick.
  To intentionally keep Tailscale off, first disable the guard:

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.caravan.remote-access.tailscale-watchdog.plist
```

To keep it disabled across future logins, also move that plist out of
`~/Library/LaunchAgents/`; retain the script for later re-enabling if desired.
This does not stop Caravan or change the built-in Tailscale login helper.

The app and guard start at **user login**, not before FileVault unlock or an
interactive macOS login. Existing automatic login and no-sleep settings remain
unchanged. No new boot-time root daemon, MDM policy, or Always-On lockout was
installed. Existing EXO2 non-Caravan LaunchAgents were left alone. Its old
fixed-Qwen Caravan jobs remain absent, as intended by last-model restoration.

## Validation and remaining manual steps

- **5/5 real SSH paths passed**, including authenticated Thunderbolt ProxyJump;
  the fallback helper independently reported all five as OK.
- **8/8 mocked guard tests on each Mini (16 total):** Running, Stopped,
  NeedsLogin, app absent, unavailable status, malformed JSON, timeout, OS error.
  Mocks intercepted all subprocesses: no live network toggle occurred.
- **3/3 mocked fallback-order tests:** EXO1 tailnet/LAN, EXO2 two failures then
  Thunderbolt success, and all EXO2 routes unavailable. An actual normal helper
  invocation also returned EXO2's hostname.
- Box regression suite: **738 tests passed in 43.514 s** using
  `PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`. Log:
  `/workspace/caravan-remote-access-tests-20261109.log`.
- Live kill/disconnect/reboot recovery tests were deliberately **not** run.
  No guarantee is made against power failure, failed macOS login, expired keys,
  disabled Remote Login, hardware faults, or losing all physical paths.

No required admin-password or GUI step remained for the verified configuration.
If macOS blocks a future update or helper, Brenden must approve it locally:
Tailscale Settings -> start at login and automatic update options; System
Settings -> General -> Login Items & Extensions -> allow Tailscale background
items. Approve Sparkle update dialogs when requested. If Remote Login is ever
turned off, re-enable it in System Settings -> General -> Sharing and allow
`brenden`; do not try an elevation workaround. Expired Tailscale authentication
also needs Brenden's sign-in. Optional router reservations should match the
current active interface MAC and actual DHCP lease, not these observations
blindly. Nothing here changes FileVault or requires disabling it.

## Caravan state: access fixed, model recovery still pending

Final observed state: EXO1 web **PID 6835** listening on **8190**, existing lead
**PID 7134** listening on **127.0.0.1:8194**; neither was touched. EXO2 is up,
logged in as `brenden`, Tailscale Running, and reachable over all three paths,
but **no Caravan web, lead, or packer listener** is present on EXO2's
8190/8194/5560, and no Caravan worker process was found. The split is therefore
**not restored or verified**. Do not confuse the separate legacy `exo` process
with a Caravan packer. Normal Balance reload/restoration testing remains a
separate approved task.

Repo observations: EXO1 `~/dev/caravan-v3` is at `d4757b1`; EXO2 `~/cv3` is at
`e0928ad`. Both contain the pre-existing untracked
`proxy/web/index.html.bak-pre-amber`, so neither is a clean tree. No pull was
attempted, no backup was removed, and EXO2 `~/dev/caravan` was never accessed.
This documentation-only commit needs no Mini pull or service restart. Future
runtime sync must first resolve that untracked backup with Brenden, then use
only a clean `git pull --ff-only`; never scp or force/reset a checkout.

References checked this turn:
- https://tailscale.com/docs/features/tailscale-system-policies
- https://tailscale.com/docs/features/client/update?tab=macos
- https://tailscale.com/docs/concepts/macos-variants
- Installed CLI `set --help`, `up --help`, `status`, and filtered preferences.
