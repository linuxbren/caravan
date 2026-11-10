Caravan Day 20: less waiting, same tools.

Hermes brings a big backpack of instructions and tools. We looked at where the waiting came from, tried the obvious fixes, and kept the ones that actually helped.

---

Caravan alone vs Caravan+Hermes: the same task with a short prompt started generating in 1.28s cold; the full Hermes-prefix replay took 177.44s. Warm: .30s vs 1.44s.

Those are first model tokens, not full answers or a pure measure of app overhead.

---

The big win: stop rereading the setup.

A tiny title request was erasing the main chat’s saved state. We separated them and saved the shared setup properly. Repeated setup work fell from 207.87s to 1.17–1.76s.

Thinking and writing still take time.

---

Next: let a tiny helper name the chat.

Titles went from a median 6.458s to .114s in the pilot. Real assistant work stays on the big model. Bad or slow helper replies fall back safely.

No main tools were removed.

---

We tried warming everything before the first real request.

It added extra work and barely changed the wait. Saved setup recovery was already doing the useful bit.

Dropped automatic warm-up. More activity isn’t always more speed.

---

Guessing ahead helped copying:44.26→70.69tokens/s, with 86% of proposed tokens accepted.

Normal chat got a little slower:29.34→28.48.

Kept it as an option for repetitive work, not the default. A copying win isn’t an everything win.

---

We tried a smaller chat-memory format, KV8.

On the Qwen trial, setup got slower:36.20→49.15s. Writing slowed too:29.20→22.68tokens/s.

Dropped it for this setup. We kept the original KV16 format.

---

Turning thinking off cut a short reply from 42.75s to 9.68s.

But it generated far less, not faster. Less deliberation is a tradeoff, so this stays a per-request option. Main Hermes keeps its normal thinking and tools.

---

One Mini vs two: the big Huihui model answered short prompts on one, but our full Hermes request ran out of GPU memory. Sharing it across both worked.

The smaller Qwen3.5-family models were 3–6.5% slower split. Two Minis bought room, not double speed.

---

The reboot lesson: don’t give up while the other Mac is still waking up.

We fixed restore to wait and retry, and made the connections reconnect. On the next reboot, the saved split loaded itself in about 65s. No manual Load click.

---

So the useful changes weren’t “make every number bigger.”

Keep the setup. Give tiny jobs a tiny helper. Don’t enable an optimization just because the name sounds fast.

The measurements, dropped ideas and limits are all written down.

github.com/linuxbren/caravan
