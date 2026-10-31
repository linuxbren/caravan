# MLX in Caravan

Caravan serves MLX models (Apple's array framework and `mlx-lm`'s
safetensors models) through the same proxy and port as GGUF models. A
request whose `model` is an MLX id goes to the **Caravan MLX worker**
(`agent/mlx_worker.py`). Everything else goes to llama.cpp.

## Setup

1. A Python venv with `mlx-lm` at `~/.caravan/venvs/mlx` (tested with
   mlx-lm 0.32.2), or set `mlx.python`.
2. The model on disk, in `~/.exo/models/` or `~/.caravan/models/mlx/`, as
   `mlx-community--<name>/` (exo's layout) or `mlx-community/<name>/`, with
   a `config.json` inside. Other locations can be added with
   `mlx.model_dirs`, or a model can be named directly with `mlx.models`
   (alias → directory). **Caravan never downloads a model.** The proxy
   rewrites the request's model id to the local directory.
3. Start the worker: `caravan_agent.py --model mlx-community/<name>
   --apply`. This runs `mlx_worker.py --model <dir> --port 8092
   --cache-dir ~/.caravan/mlx/prompt-cache`. Or render a launchd plist
   with `agent/render_mlx_plist.py`.
4. Send requests to the proxy on port 8090 with `"model":
   "mlx-community/<name>"`.

One worker serves one model. The worker takes 6–9 s to start (plain
`mlx_lm.server`: about 1.6 s).

## Why Caravan has its own MLX server

Version 1 used plain `mlx_lm.server` (0.32.2). Measured on one 24 GB Mac
mini, it had three problems:

- **Gemma 4 and GPT-OSS reused nothing between messages.**
  `mlx_lm.server` stores a conversation's cache after the reply, keyed by
  prompt plus reply. On the next message, the chat template re-renders
  the earlier reply differently (the thinking or analysis part is
  dropped), so the stored cache only matches up to the end of the old
  prompt. Getting back there means trimming the cache. Sliding-window
  layers (25 of Gemma 4's 30, 12 of GPT-OSS's 24) can't be trimmed once
  their window has wrapped. Result: turn 2 of a 4k chat re-read about
  4,000 tokens (Gemma 4 10.8 s, GPT-OSS 9.2 s). Qwen3, with only plain
  layers, reused fine (0.44 s).
- **Every cache hit was a full copy** of the stored cache. That pushed
  Qwen3 30B over the GPU limit at 16k.
- **Nothing was saved to disk**, so every restart started cold.

## How the worker's cache works

**One live cache per session.** The proxy sends the session fingerprint
in an `X-Caravan-Session` header, and the worker keeps one cache per
session, with no copies. A request with no session key uses a shared
`_anon` session that is never saved.

**Checkpoint and rewind**, the same idea as llama.cpp's context
checkpoints:

1. Compare the new prompt with the session's cache, and reuse the
   matching start. If a sliding-window cache has diverged, it can't be
   rewound, so the prompt is read in full. That's rare, because of step 4.
2. Read the rest of the prompt, up to its last token, in chunks of
   `--prefill-step-size` (2048).
3. **Checkpoint**: snapshot the layers that can't be trimmed
   (sliding-window or other non-plain layers).
4. Generate the reply starting from the last prompt token. Afterwards,
   **rewind** to the checkpoint: trim the plain layers and restore the
   rest from the snapshot. The next message's prompt starts with exactly
   those tokens, so only the new part is read: the earlier reply, as the
   template re-renders it, plus the new message.

The same happens on an error or a client disconnect, so a session is
never left half-written.

**Saving and restoring.**

- On request from the proxy, the worker writes the checkpoint to
  `<cache-dir>/<fingerprint>.safetensors` using mlx-lm's prompt-cache
  format.
- The metadata records:
  - the format (`caravan-mlx-cache-1`)
  - the model path and a tokenizer hash
  - the mlx-lm version and model type
  - the cache layout, `kv_bits`, and the tokens
- If any of that doesn't match on load, the session simply starts cold;
  it never crashes.
- The proxy calls `POST /caravan/cache/restore` before every MLX request.
  The answer is `warm` (already in memory), `restored` (loaded from disk)
  or `miss`. The proxy logs it as `cache=mlx-<result>`.
- After a successful reply, the proxy calls `POST /caravan/cache/save`
  from turn `mlx_save_min_turns` (1) onward, every `slot_save_every` (1)
  turns.
- Saves are skipped when nothing changed.
- Measured file sizes:

  | model | 4k chat | 16k chat |
  |---|---|---|
  | Qwen3 30B | about 400 MB | – |
  | Gemma 4 | about 300 MB | about 570 MB |
  | GPT-OSS | about 110 MB | about 410 MB |

- A 4k save takes about 0.1 s. A restore takes 0.01–0.13 s with the file
  in the disk cache.

**Memory.**

- At most `--prompt-cache-size` (4) sessions stay in memory, and
  `--prompt-cache-bytes` (2 GiB) for all of them.
- The least recently used session is evicted first, except the session
  in use (it's the live cache, so keeping it costs nothing extra).
- A session with unsaved turns is saved before it's evicted.
- On SIGTERM, unsaved sessions are written out before exit.
- The saved files on disk are held to the per-Mac cap together with
  llama.cpp's slot files (see
  [CONFIGURATION.md](CONFIGURATION.md#saved-chat-cleanup-and-the-per-mac-cap)).
  Evicted sessions are also dropped from the worker's memory
  (`POST /caravan/cache/drop`).

**One GPU thread.** All MLX work runs on one thread with its own MLX
stream, so requests never overlap on the GPU. The proxy's FIFO gate
already sends them one at a time.

**Wired limit.** At startup the worker raises Metal's wired limit to the
recommended working set (about 19.07 GB on an M4 24 GB) and holds it for
the life of the process, as `mlx_lm.server` does. The log says `wired
limit 0 -> 19069665280 bytes (held for process lifetime)`. Options are
`--wired-limit startup|per-request|off`.

## Replies

- **GPT-OSS (harmony format).** GPT-OSS writes its reasoning in an
  `analysis` (or `commentary`) channel and the answer in `final`. The
  worker splits the stream as it arrives. Reasoning goes to
  `reasoning_content` (llama.cpp's field name) and `reasoning`
  (mlx-lm's), and the answer to `content`. Clients see a clean answer,
  with no `<|channel|>` tags. This also works when streaming.
- **Reasoning sent back.** If a client sends earlier replies back with
  `reasoning_content` or `reasoning`, those fields are removed before the
  chat template runs, so they never leak into the visible history.
- **Qwen3 / Gemma thinking.** These use mlx-lm's own reasoning parser.
  The blank lines Qwen leaves after an empty `<think>` block are removed.
- **Sampling.** Supported request fields: `temperature` (default 0),
  `top_p`, `min_p`, `top_k`, `repetition_penalty`, `max_tokens` (default
  `--max-tokens`, 512), `stop`, `stream`, `chat_template_kwargs`.
  llama.cpp-only fields (`id_slot`, `cache_prompt`, `n_probs`, `slot_id`)
  are dropped by the proxy.
- **Usage.** `usage` includes `prompt_tokens_details.cached_tokens` (the
  tokens reused) and a `caravan` object with `how` (for example
  `hit-memory`, `trimmed-disk`, `diverged-new`), `prefill_s`, `ttft_s`, `total_s` and `peak_gb`.

## Endpoints

| method | path | what |
|---|---|---|
| GET | `/health` | `{"status": "ok", "worker": "caravan"}`. |
| GET | `/v1/models` | The one model. |
| GET | `/caravan/cache` | Sessions in memory (tokens, size, unsaved, turns), the cache dir, and whether saving is on. |
| POST | `/caravan/cache/restore` | `{"key": fp}` → `warm`, `restored`, `miss` or `rejected`. |
| POST | `/caravan/cache/save` | `{"key": fp}`: write the session's checkpoint to disk. |
| POST | `/caravan/cache/drop` | `{"keys": [...]}`: forget sessions in memory. |
| POST | `/v1/chat/completions`, `/v1/completions` | OpenAI-compatible, streaming or not. |

## Results

Single Mac mini M4 24 GB, through the proxy. Full tables are in
[BENCHMARKS.md](BENCHMARKS.md).

| | v1 (`mlx_lm.server`) | v2/v2.1 (Caravan worker) |
|---|---|---|
| Turn 2 of a 4k chat, Gemma 4 / GPT-OSS / Qwen3 | 10.76 / 9.16 / 0.44 s | 0.49 / 0.50 / 0.56 s |
| First message after a restart, 4k chat | 16.0 / 12.7 / 16.0 s | 0.64 / 0.52 / 0.59 s |
| Turn 2 of a 16k chat, Gemma 4 / GPT-OSS | 55.1 / 37.3 s | 0.72 / 0.59 s |
| Writing speed (tg128), Gemma 4 / GPT-OSS / Qwen3 | 39.8 / 35.3 / 47.0 tok/s | 42.2 / 37.4 / 49.1 tok/s |

## Limits

- **One model per worker, one Mac.** MLX models aren't split across Macs
  yet (that's on the [roadmap](ROADMAP.md)), and one worker holds one
  model.
- **Qwen3 30B at 16k doesn't fit** on a 24 GB Mac with a plain f16 cache,
  not even with `--kv-bits 8`. Use 4k–8k chats, or the GGUF build of the
  model.
- **Gemma 4 reads short prompts about 8% slower** than with plain
  `mlx_lm.server` (397 vs 430 tok/s on a 512-token prompt, side by side).
  The likely cause is the checkpoint snapshot of its sliding-window
  layers. Long prompts and writing speed are unaffected.
- **Tool calls** are passed to the chat template, but the reply comes
  back as text. There's no structured `tool_calls` field yet.
- **Same first message = same session.** This is the proxy's
  fingerprint rule. Two chats that start identically share (and
  overwrite) one saved cache.
- **Saved caches are tied to the model and mlx-lm version.** After an
  upgrade, old files are ignored (cold once) and cleaned up by age.
- **`mlx.server = "mlx_lm"`** still runs plain `mlx_lm.server` for
  comparison: no saved sessions, and Gemma and GPT-OSS re-read every
  turn. The proxy logs `cache=mlx-noop` for it.
