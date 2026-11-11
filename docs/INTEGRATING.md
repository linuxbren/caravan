# Connect a client to Caravan

Caravan exposes an OpenAI-compatible proxy on the first Mac (the lead). You
can use a compatible chat application, terminal client or your own program;
no particular personal app or development operating system is required.
The proxy is optional; the simple browser installer does not install clients.

## Connection and requests

Keep the proxy loopback-only. For a client on your development node, use a
trusted SSH tunnel as in [remote access](REMOTE-ACCESS.md), forwarding the
proxy's configured port instead of the web port. Do not expose it publicly.
Point the client at the forwarded `/v1` base URL.

- `POST /v1/chat/completions` supports streamed replies (`stream: true`).
- `GET /v1/models` lists models exposed by the configured backend routes.
- Resend the intended conversation with a stable system/tool prefix for cache
  reuse. The proxy recognizes sessions; changing template inputs can require
  a fresh prompt read. Reuse is not a promise of an instant cold first reply.
- Models that return reasoning separately should have it displayed separately
  from the final answer. Honor cancellation and show server errors clearly.

Use actual backend/model identifiers, not names copied from the build log.
Optional service setup is in [SERVICES](SERVICES.md). Internal status/control
endpoints are not an assumed stable public client contract; verify their current
implementation before building a client around them. Future console integration
is tracked in [ROADMAP](ROADMAP.md).
