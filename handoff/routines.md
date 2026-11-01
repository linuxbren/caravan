# Recurring routines (recreate these on the new assistant)

Brenden asked for both reminders **every day, weekends included**. They were set up in the
old assistant's routine scheduler and do **not** carry over: recreate them on the new
account. Both are flexible by about ±15 minutes. Times are US Central (America/Chicago).

> **Update before (or right after) recreating them.** The roadmap order written into both
> prompts is stale. It was written on Oct 30 2026 (before v1, v2, v2.1, v3 and v3.1 were
> finished). Replace it with the current order from `docs/ROADMAP.md` ("Next, in order" and
> "Beating the turn-taking in the split"). As of Oct 31 2026 the suggested next steps are:
> idea 5 (uneven layer split, `--split-packer-layers`), idea 1 (several chats at once), and
> idea 3 (guess ahead), then per-model profiles, proxy overhead, memory headroom and
> cold-disk restore. Also change the paths: `/workspace/llm-lab/...` was the old assistant's
> computer. On a fresh computer, read `handoff/lab/experiments.md` and
> `handoff/lab/videos/index.md` from this repo (or copy them back to
> `/workspace/llm-lab/` first; see `handoff/README.md`, "First steps").

---

## Routine 1: "Daily Caravan progress post reminder + draft"

- Schedule: `CRON_TZ=America/Chicago 0 20 * * *` (8:00 PM Central every day), flexible ±15 min.
- Prompt (verbatim):

```
This is Brenden's daily reminder to post about Caravan progress on X. He asked to be reminded every day.

Read Brenden's experiment log at /workspace/llm-lab/experiments.md, plus anything he told me in this chat today about his Caravan / Mac Mini local LLM work that isn't logged yet (log it first).

- If today's post was already drafted in chat and he has posted it or said he's skipping, send nothing.
- If today's post was drafted but he hasn't approved or posted it yet, send a short, friendly reminder to post it, with the intent link if he approved the text.
- If nothing was tried or learned today, send a short reminder that today's progress post is still open. Offer to draft a quick "what I'm planning next" post from the roadmap, or note that there's nothing new to share.
- Otherwise, remind him it's time to post and draft today's post as described below.

The draft is today's daily Caravan build-log post in his voice. The voice is hands-on and mad-scientist homebrew, with concrete numbers. Write for a friend who's into computers and AI but doesn't know local-AI lingo (no GGUF/MLX/TTFT/tg128 shorthand; no "we're teaching" framing). Gloss a term once if needed (e.g. tokens/sec = how fast it writes), then move on. Keep it short; he prefers a tight single post (under 280 characters), with an optional short thread only if there's a lot to share.

ALWAYS start the post with the day of development plus a few words summing up what Caravan is. Oct 30, 2026 is Day 1, and each calendar day after that counts up (Oct 31 = Day 2). For example: "Day N of building Caravan in the open, my homebrew app for running AI models across my Mac minis."

Cover:
1. What we worked on today.
2. The key stats compared with the previous Caravan version and the Caravan v0 baseline (commit 45ed2c2, Oct 30, 2026 numbers in experiments.md).
3. What's next on the roadmap. The order is:
   a. rebase onto upstream llama.cpp so slot restore works on sliding-window models (done Oct 30)
   b. MLX support (step a, routing to mlx-lm, done Oct 30; next: MLX chat save/restore, then a two-Mac MLX split)
   c. higher-precision cache when it fits (done Oct 30, automatic choice)
   d. per-model profiles
   e. proxy overhead
   f. memory headroom
   g. cold-disk restore

   Mark items done when they're done.

If a lab video for today exists in /workspace/llm-lab/videos/index.md, suggest attaching it.

Never post, and never use any posting tool. Show the draft in this chat for his approval and offer to revise. After he approves, give him https://x.com/intent/post?text=<URL-encoded text> links so he presses Post himself. Mark the log entry's post status as "drafted".

The result goes to Brenden in this chat. Send nothing only when today's post is already handled.
```

## Routine 2: "Daily Caravan work reminder"

- Schedule: `CRON_TZ=America/Chicago 0 18 * * *` (6:00 PM Central every day), flexible ±15 min.
- Prompt (verbatim):

```
Remind Brenden that it's time to put some work into Caravan, his homebrew local LLM runtime that he's building in the open on his two Mac minis. He asked for this reminder every day.

Before writing, read /workspace/llm-lab/experiments.md (newest entries first) and the roadmap in my memory, so the reminder is specific: say which day of development it is (Oct 30, 2026 is Day 1, and each calendar day counts up), what was finished most recently, and the one or two next items, with a concrete suggestion for tonight's session. The roadmap order after Oct 30 is MLX chat save/restore, then a two-Mac MLX split, per-model profiles, proxy overhead, memory headroom, and cold-disk restore. Prefer whatever the latest log entry says is open. Mention any loose ends from the log, such as unmerged branches or exo still paused, only if they matter tonight.

Keep it to two or three short, friendly sentences, and offer to start the work if he says go. Don't start any work, run anything on the Minis, or change anything on your own.

The result goes to Brenden in this chat, every day.
```

### Stale bits to fix in these prompts (as of Oct 31 2026)

| In the prompt | Now |
|---|---|
| Routine 1, items a–c "done Oct 30" and "next: MLX chat save/restore, then a two-Mac MLX split" | MLX chat save/restore = v2 (Oct 31), steadier MLX = v2.1, two-Mac MLX split = v3 (tag `v3`), shard size check + cable benchmark = v3.1 (tag `v3.1`). All done. |
| Routine 2, "The roadmap order after Oct 30 is MLX chat save/restore, then a two-Mac MLX split, ..." | Next: uneven layer split (idea 5), several chats at once (idea 1), guess ahead (idea 3); then per-model profiles, proxy overhead, memory headroom, cold-disk restore. Check `docs/ROADMAP.md` first. |
| "Previous Caravan version" | Latest is v3.1 (plus the unreleased Low Power Mode rerun); the previous is v3. Benchmark videos show the latest and the one before it. |
| `/workspace/llm-lab/...` paths | The old assistant's computer. Use this repo's `handoff/lab/` copy, or restore it to the same path. |
