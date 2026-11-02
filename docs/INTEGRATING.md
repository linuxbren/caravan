# Integrating with Caravan (for Terminal Delight and other clients)

Written for Parker Brown. Caravan is flexible on how the console looks; this
is the contract it offers today and what is coming.

## What Caravan exposes today
- An OpenAI-compatible HTTP proxy on the lead Mini, port `8090`
  (`slot_pin_proxy.py`). Use `POST /v1/chat/completions` with `stream: true`.
- `GET /v1/models` lists models (llama.cpp only for now; MLX listing is a gap).
- Chat reuse: resend the whole conversation every turn, same prefix. The proxy
  recognizes the session and reuses its cache, so replies start fast.
  `/v1/responses` passes through but skips this reuse; prefer chat completions.
- GPT-OSS returns its reasoning separately from the answer; show them apart.

## Suggested shape in Terminal Delight
1. Start: point an existing CLI (`aichat`, `llm`) at `http://<lead>:8090/v1`.
2. Better: a small chat program started by the Local launcher
   (`~/.config/terminal-delight/local-agent.toml`) that streams replies and
   writes Workbench JSON under `surfaces/<session>/<pane>/`
   (see `app/src/surfacefeed.rs`): one item for the reply, one for reasoning,
   one for status.
3. Nicest: a native Rust chat pane (needs an HTTP client in the terminal).

## Coming on the Caravan side (ROADMAP #14, #15)
- Bind option beyond localhost (for example `--listen-host`) plus an optional
  API key. Until then, use an SSH tunnel to the lead.
- `GET /caravan/status` (JSON): nodes, layers per Mini, memory, tok/s, chats
  in flight, guess-ahead on/off. Good for a node-view Workbench item.
- Model switching and options through an endpoint, backed by
  `~/.caravan/config.toml` (ROADMAP #13c).
- Lead discovery so clients don't need a hard-coded address.

Field names for the status and control endpoints are not final; Caravan
will shape them with Parker's input.
