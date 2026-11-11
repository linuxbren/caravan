# Security and trusted connections

Caravan is experimental software for Macs you control on a trusted network.
There is no browser login or multi-user access policy. Do not expose the UI,
model workers or RPC service directly to the public internet.

- The easy install binds the browser service to localhost. Use an SSH tunnel
  for access from your development node; see [remote access](REMOTE-ACCESS.md).
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
