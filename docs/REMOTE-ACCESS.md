# Connect to another Mac

Use one Mac locally first. For node names and placeholders, see the
[documentation index](README.md#names-used-in-these-guides).

## Add a trusted helper

1. Run the [helper setup command](../INSTALL.md#add-minis) on the second Mac.
2. On that Mac, enable System Settings → General → Sharing → Remote Login for
   the intended account. A managed Mac may require an administrator.
3. From the first Mac, connect using your own username and that Mac's address.
   Verify its SSH fingerprint before trusting it. Set up key-based access so
   Caravan does not have to answer password prompts. Never share a private key.
4. Add the helper's inventory entry and actual repository path to the first
   Mac's configuration. Restart only the browser service after changing it.

`lead-mac` and `helper-mac` below are example aliases, not aliases Caravan
creates. Configure your own names and trusted host keys first.

```sh
ssh helper-mac hostname
```

Confirm this returns the intended helper before loading a split model. Use a
stable trusted SSH control name; do not identify a Mac solely by yesterday's
Thunderbolt address. macOS can change link-local addresses after reboot.

## Open the first Mac's browser page from another device

The Tailscale share does not change where the page itself listens; it
stays on this Mac and Tailscale forwards to it. To open it from your other
devices, use the opt-in Tailscale share: `caravan remote on`, the Settings
switch **Open from my other devices**, or the install question if Tailscale
is already signed in. Only devices on your Tailscale network can reach it.
`caravan remote status` prints the addresses. `caravan remote off` and
uninstall remove only Caravan's share. Details are in
[the developer guide](DEVELOPMENT.md#open-from-other-devices-tailscale).

Through the Tailscale share, Settings also shows **Updates**, and
**Update now** works the same as on this Mac: it updates the other
Macs first, then this Mac, and the page reloads itself when Caravan is
back. Caravan checks that the share is on and that the address is a
live Tailscale address for this Mac; a public Funnel address is
refused.

## Open on your local network

In addition to Tailscale, you can open the page from other devices on the
same network. This is off by default. Turn it on with the Settings switch
**Open on my local network**, `caravan lan on`, or the install question
(default No). Anyone on the same network can use Caravan, and there is no
login. The Settings switch shows that warning beside it, and when the
switch is on, a clickable link (`http://<lan-ip>:<port>`) appears under
it, the same way the Tailscale link is shown.

This can be on at the same time as **Open from my other devices**. Both
addresses stay reachable: the Tailscale address and the local-network
address.

`caravan lan status` prints the address to open (`http://<lan-ip>:<port>`).
`caravan lan off` and uninstall turn it off, and the page goes back to
this Mac only; the Tailscale share is unchanged. Turning it on or off
does not unload a model that is already loaded, and the open page stays
up. Over the local network the page has no Updates section and refuses
update requests, because there is no login; run `caravan update` in
Terminal on this Mac. This never opens
the page to the public internet. Your Mac may ask whether to allow
incoming connections; that is expected.

You can also forward the local page over SSH and leave Tailscale unused:

```sh
ssh -N -L 18190:127.0.0.1:8190 lead-mac
```

Open http://127.0.0.1:18190/ on your other computer. Choose a different local
port if that one is busy. Keep the terminal open while using the tunnel.
Caravan does not create this alias, enable Remote Login, or install a tunnel
service for you.

## If a connection fails

- Confirm the Mac is on, unlocked and logged in; FileVault needs a person to
  unlock it after reboot. Do not disable FileVault or enable auto-login as a fix.
- Test normal LAN SSH before blaming the model. Check the actual address and
  allowed Remote Login account. Do not assume an alias exists on another device.
- Check VPN status separately if using one; LAN and VPN are different routes.
- For Thunderbolt, check the correct cable interface on both Macs. The UI's
  link check is read-only; a reachable port does not prove peer identity.
- Never disable SSH host-key checking, copy somebody else's known-hosts file,
  change routes blindly, or expose model-control ports to the public internet.

For advanced reboot-safe interface endpoints see [SERVICES](SERVICES.md).
Earlier machine-specific observations are preserved in the
[historical remote-access record](history/REMOTE-ACCESS-LAB.md), not presented
as network settings to copy.
