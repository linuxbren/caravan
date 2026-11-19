# Day 31 — GGUF chat window runs at the model's full trained length

Day 31 ran Nov 19 2026 (America/Chicago). Goal from the owner:
"Context is important." A GGUF model should run as close to the window
it was trained for as memory allows, and Caravan should not cut the
window to gain speed. Day 30's TensorFold test is shelved (see the
[roadmap](ROADMAP.md)).

## At a glance

- **Chat window Auto has no 32K cap any more.** It picks the longest
  window that fits in memory, up to the model's trained window: Llama 3.1
  8B and gpt-oss 20B now get their full 131072 on one Mac (they had
  32768). Qwen3 30B-A3B and Qwen3 14B were trained for 32768, so they
  were already at their full window and do not change.
- **Auto never picks less than before.** The old rule is kept as the
  floor, and the trusted 8192 default still applies when the model file
  or memory cannot be measured.
- **The window comes first.** Settings Caravan learned for speed
  (16-bit chat memory, flash attention off, a bigger prompt batch, the
  Guess-ahead helper) never make Auto pick a shorter window. If one would
  not fit, Caravan uses the lighter choice and the load log says so, for
  example: "Kept the full chat window of 131072: using 8-bit chat memory
  instead of the learned setting, which would not fit". Auto-tune and
  Self-tuning skip trials whose win would need a shorter window. Settings
  you pin yourself still count, so pinning Memory compression 16 can give
  a shorter Auto window.
- **More Chat window choices.** 131072, 262144 and **Native** (the
  model's own trained window, which can be a size not in the list, such
  as 40960). Sizes past the trained window, or that will not fit in
  memory, stay greyed out with a plain reason.
- **Restores and updates resize too.** A window saved from an Auto load
  (restart, Update now, Self-tuning reload) is sized again on the next
  load instead of staying at the old 32768.
- **The web chat keeps history up to the real window.** It used to trim
  every model's history at about 32K tokens; a GGUF chat now trims at
  its actual window.
- **Long reads are not cut off.** Caravan waited at most 30 minutes for a
  model's first bytes. Reading a prompt close to a 128K window on one
  Mac takes longer than that, so the wait is now 2 hours
  (`CARAVAN_REPLY_TIMEOUT_S` changes it).
- **Split loads no longer say "Couldn't start the model on the other
  Mac" when they worked.** The success line for the other Mac's model
  server mentions its link, and the plain-wording filter turned every
  such line into the failure message. Only lines that report a failure
  become that message now, and the load notes name the other Mac in
  plain words ("2nd Mac") instead of dropping its name.
- **`caravan bench` works on the model that is already loaded.** Asking
  for the loaded model restarts it, but the first status replies still
  said "ready" from before the restart, so the bench measured a stopped
  server (HTTP 502) and then could not put the model back ("a model
  switch is already in progress", HTTP 400). It now waits for a ready
  note from its own load, and waits out a switch that is already
  running. Found by the Day 31 bench check.

## How Auto sizes the window

The estimate per candidate window is: model weights, plus chat memory
for that window (8-bit unless you pin 16), plus llama.cpp's working
memory for a full prompt batch, plus a window-sized attention mask on
each Mac (window × prompt batch × 4 bytes), plus the existing safety
margin. With flash attention off, llama.cpp also keeps the full score
matrix (heads × window × prompt batch × 4 bytes, about 8 GiB for Llama
3.1 8B at 128K), so a learned "flash attention off" is never kept at a
long window. The budget is the GPU working-set limit of each Mac the
model uses, added up for a split. Auto tries the model's trained window
first and steps down through 262144, 131072, 65536, 32768 … until one
fits, never below the old rule's pick.

## Measured (Nov 19, 1st and 2nd Mac, Auto settings)

Old = the published build before Day 31 (Auto capped at 32768). New =
the Day 31 build. Each row: model loaded with every setting on Auto,
the saved Auto-tune winners applied (Llama 3.1 8B keeps its helper and
Prompt lookup), 6 short prompts (median write speed), one long prompt
at about 29K tokens, and on the new build one at about 90% of the new
window. Memory is the rise in wired (GPU) memory after loading. Swap use
did not change in any run.

| Model | Setup | Build | Auto window | Chat memory | Memory rise | Short write tok/s | ~29K prompt: first word / write | Near-window prompt |
|---|---|---|---|---|---|---|---|---|
| Llama 3.1 8B | 1 Mac | old | 32768 | 16-bit | 11.2 GB | 25.17 | 268 s / 12.45 tok/s | can't (window 32768) |
| Llama 3.1 8B | 1 Mac | new | 131072 | 8-bit | 18.5 GB | 25.56 | 268 s / 11.57 tok/s | 115,593 tokens: first word 2669 s (44 min), write 3.65 tok/s |
| gpt-oss 20B | 1 Mac | old | 32768 | 16-bit | 12.3 GB | 39.53 | 104 s / 29.39 tok/s | can't (window 32768) |
| gpt-oss 20B | 1 Mac | new | 131072 | 16-bit | 14.9 GB | 39.44 | 103 s / 29.39 tok/s | 115,626 tokens: first word 916 s, write 16.40 tok/s |
| Qwen3 30B-A3B | 2 Macs | old | 32768 | 16-bit | 11.7 + 10.3 GB | 34.64 | 117 s / 15.76 tok/s | already the full window |
| Qwen3 30B-A3B | 2 Macs | new | 32768 | 16-bit | 11.7 + 10.3 GB | 34.59 | 117 s / 15.74 tok/s | already the full window |

What it costs:

- **Short chats: no cost.** Within ±1.5% on all three models.
- **gpt-oss 20B:** no speed cost; its 128K chat memory still fits in
  16-bit (sliding-window layers keep it small). About 2.6 GB more memory.
- **Llama 3.1 8B:** the full window only fits with 8-bit chat memory, so
  writing on a long (~29K) prompt is about 7% slower (11.57 vs 12.45
  tok/s); reading is the same. About 7.4 GB more memory, and the helper
  still fits. Pin Chat window 32768 (or Memory compression 16) to get the
  old behaviour back. Near the full window it works but is slow on one
  Mac: a 115,593-token prompt took 44 minutes to read (43 tok/s on
  average, falling from about 145 to 45 tok/s as the prompt grew) and
  wrote at 3.65 tok/s. Wired memory stayed at about 20.7 GB with no swap
  use. The first try at this prompt was cut off by the 30-minute reply
  wait; that is the fix above.
- **Qwen3 30B-A3B split:** unchanged (already at its trained window).

## Checks

- Full test suite: 1,900 tests, OK (`PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests`, 63 s).
- Fresh Auto-tune on Llama 3.1 8B, 1st Mac, window 131072: finished in
  15.1 minutes (Day 28 on the old build: 19.6). Flash attention and chat
  memory were skipped with "needs a shorter chat window"; prompt batch
  512, Prompt lookup and the helper were kept, as on Day 28. Short write
  20.2 → 24.3 tok/s; the long-prompt check passed (long read 217 → 182
  tok/s with the helper, inside the Day 28 guard). It reloaded at 131072
  with 8-bit chat memory and the "Kept the full chat window" note.
- `caravan bench "llama 3.1 8b" --only gguf --yes` on the 1st Mac with
  that GGUF already loaded: the first try failed (HTTP 502, then 400
  putting the model back; the fix is above). With the fix it finished
  in 9.5 minutes and put the GGUF back. GGUF at 131072 with 8-bit chat
  memory: short write 26.0 tok/s, ~8k prompt read 153 tok/s, write
  16.5 tok/s, first token 62.4 s. MLX on the same run: 22.0, 196, 17.1,
  48.8 s.

## Compatibility

Python files in `proxy/`, `tools/caravan_bench.py` and `tests/` only,
plus docs. Nothing in
`agent/`, `runtime/` or the requirements files changed, so `caravan
update` keeps a loaded model. The next load of a GGUF model on Auto
uses the new window.
