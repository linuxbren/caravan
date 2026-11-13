# Security and trusted connections

Caravan is experimental software for Macs you control on a trusted network.
There is no browser login or multi-user access policy. Do not expose the UI,
model workers or RPC service directly to the public internet.

- The easy install keeps the browser page only on this Mac. You can turn
  on **Open on my local network** in Settings or `caravan lan on`.
  Anyone on the same network can use Caravan, and there is no login.
  **Update now** in Settings is available when you open the page on
  this Mac itself, and when you open it through this Mac's Tailscale
  share (the share must be on, and the address must match a live
  Tailscale address for this Mac). From the local network, the page
  can show that an update is ready, and asks you to run
  `caravan update` in Terminal on this Mac.
  `caravan lan status` shows the address (`http://<lan-ip>:<port>`),
  and a clickable link appears under the Settings switch. This can be
  on at the same time as the opt-in Tailscale share; both addresses
  stay reachable. The
  opt-in Tailscale share is described in [remote access](REMOTE-ACCESS.md).
  Never expose the page to the public internet. Use an SSH tunnel for
  access from a development computer if you prefer not to open the page
  on the local network.
- Trust each helper's SSH identity yourself. Never disable host-key checking
  or add a key from an unverified source. Setup does not establish SSH trust.
- GGUF RPC should listen on loopback and travel through an SSH tunnel. Check
  the actual listener and attempt a connection from outside the intended host
  before assuming a deployment is private. A historical successful check is
  not proof of your current listener settings.
- Read-only Thunderbolt verification checks SSH identity/reachability; it does
  not authenticate the raw MLX model transport. Keep that transport on a
  private trusted link. Authenticated model transport remains open work.
- Keep FileVault, Gatekeeper and other Mac protections enabled. Do not remove
  quarantine flags or grant broad privileges to avoid a warning. Setup uses
  your normal account and does not change login/security settings.
- Local model chats stay on your Macs. Model downloads contact publishers;
  optional cloud features send data to the provider you choose.
- Do not put credentials, private chat text, real addresses or keys in issues,
  screenshots or release artifacts. Use the provided token settings rather
  than committing secrets. Inspect logs before sharing them.

Historical loopback/tunnel checks are retained in
[the security lab record](history/SECURITY-LAB.md). The
[package status](PACKAGING.md) explains signatures, checksum trust and remaining
clean-install acceptance gates.
