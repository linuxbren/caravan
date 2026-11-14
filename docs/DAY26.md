# Day 26 — Download progress under the model, a clearer First-token chart, GGUF speed-ups, and Voice design notes

Day 26 is in progress (Nov 12–13 2026, America/Chicago). There is no
`day26` tag yet; that waits until Brenden has tried the work. Day 25
remains tagged (`day25-2026-11-12`). The 1st Mac and 2nd Mac are not
changed by this work: Brenden updates those Macs with `caravan update`.

This first follow-up does not change `agent/`, `runtime/`, or the
requirements files, so a `caravan update` from the Day 25 pin keeps a
loaded model running. The web page still restarts.

## What shipped

### Download progress under the model you clicked

In the Models list, the download progress card now appears right
under the model you clicked Download on, so it is clear that this
model is the one downloading. The card stays there, with its bar,
size, speed, and waiting time, and with Stop, Resume, and
Load-when-ready, even if you close that model's file list. If two
downloads for the same model are running, the cards stack under that
row. If a search hides the model, the card sits at the top of the
Models list until the model is visible again, then moves back under
it. After a page refresh, a still-running download is re-attached
the same way.

### First token bars follow the seconds

The `caravan bench` chart used to draw a longer First token bar for a
sooner reply, which was easy to read the wrong way: 0.28s looked
"bigger" than 0.46s. The bars now follow the printed number, the same
way Reading and Writing already do. The label is still **First token
(s, lower is better)**, and a shorter bar is sooner. The winner
marker (`* +39%` on 0.28s vs 0.46s) is unchanged. `--ascii` uses the
same scaling with '#' bars; `--details` (the reply-stats lines) is
unchanged. The Day 25 sample chart in [DAY25](DAY25.md) and
[BENCHMARKS](BENCHMARKS.md) was redrawn with this direction; the
measured numbers are the same.

This follow-up does not change `agent/`, `runtime/`, or the
requirements files, so a `caravan update` from the previous Day 26
pin keeps a loaded model running.

### GGUF Prompt lookup and a draft model

Under Advanced, a GGUF model now has **Prompt lookup** and
**Guess-ahead**, each Auto, Off, or On. Auto stays off until a test
finds a winner (or you turn it on). Prompt lookup reuses words from
your prompt to help with repeated text; it can help on repeated
passages and can slow mixed chats. When it is on, Caravan asks the bundled engine to reuse words from
your prompt. Auto-tune may try it last, only
when it is safe: one chat (not Two chats), and the row is not already
pinned. A garbled trial is a loss, even if it looks faster, and the
previous setting is kept. Self-tuning does not try this option.
Chat window and Two chats are still not flipped automatically.

Guess-ahead uses a smaller model already on this Mac to guess upcoming
words for the main model to check. On is only available when a smaller
model of the same family is already on disk; Caravan will not download
one for you. Auto-tune does not try Guess-ahead in this follow-up — turning it
on is a deliberate choice, because it is often slower on a Mac and
uses more memory. A missing or unknown helper is treated as off, and
Caravan never passes a flag that would download weights.

This follow-up does not change `agent/`, `runtime/`, or the
requirements files, so a `caravan update` from the previous Day 26
pin keeps a loaded model running. The web page still restarts.

## Voice design notes (not running yet)

Listening-first design notes are in [VOICE](VOICE.md): a microphone
next to Send, words in the chat box so you can edit them, a listen
worker on the 1st Mac that does not unload the chat model, and a
planned "send a recording, get text back" address on the same URL as
chat. Spoken replies wait until listening feels right. No listening
code is shipped in this follow-up. This does not change `agent/`,
`runtime/`, or the requirements files, so a `caravan update` from the
previous Day 26 pin keeps a loaded model running.

### Daily update check and Update on the page

Caravan checks once a day, and shortly after it starts, whether a newer
version is published. The check is a short look at the published
version list; it does not download the update until you ask. If this
Mac is offline, the check stays quiet and keeps any earlier result.
**Check for updates daily** is on by default in Settings, and
**Check now** runs a check right away. In Terminal,
`caravan update --check` does the same check and does not install
anything.

When a newer version is ready, an **Update available** badge appears
in the header of the chat page, in the same style as the Tuning…
badge, including on Campfire. Opening Settings shows an **Updates**
section with the version on this Mac and the newer one, in plain
dates such as November 12 and November 13 — no hashes up front.
What's new is the short list of changes, when that is available.
The section also says **Your model stays loaded** or **Caravan will reload the model**, using the same rule as `caravan update`: the
model is reloaded only if the parts that run it changed.

**Update now** runs the same update as `caravan update`, in the
background. A campfire flicker and a short "Updating…" line show
progress. The page comes back on its own and says Done, with the
new version, or shows the error and that the previous version is
still running. The button is off during a chat reply or Auto-tune;
you can confirm before it starts.

**Update now** is available when you open Caravan on this Mac itself,
and when you open it through this Mac's Tailscale share. Caravan
checks that the share is on and that the address matches a live
Tailscale address for this Mac, not just a name that looks like
Tailscale. On the local network there is no login, so the button
stays hidden and the page asks you to run `caravan update` in
Terminal on this Mac. The daily check itself still runs on this Mac.

**Update now** and `caravan update` on this Mac also update the other
Macs Caravan already knows about — the 2nd Mac, 3rd Mac, and so on —
over the connection already set up when each Mac was added. The other
Macs are updated first, then this Mac, and the model comes back
afterwards if it was loaded. If a Mac is off or the update doesn't
finish, this Mac still updates. Settings lists each Mac's status, and
when something goes wrong, step-by-step help appears right under that
Mac: check that it's on and awake, check that it's on the same
network or on Tailscale, click **Try again**, or on that Mac open
Terminal and run `caravan update`, then load the model again. The
daily check also shows when another Mac is on an older version, and
the **Update available** badge appears in that case too.

The Updates section now has **Check now** next to its title, and
one status line per Mac in the same format — for example
"1st Mac: up to date", "2nd Mac: update available", "3rd Mac:
updating…", or "2nd Mac: off or can't be reached". The date of a
newer version is shown only when one is ready, as "A November 13
update is ready."

This follow-up does not change `agent/`, `runtime/`, or the
requirements files, so a `caravan update` from the previous Day 26
pin keeps a loaded model running. The web page still restarts. No
`day26` tag yet.

## What is still ahead (same Day 26)

- **Voice:** build listening first, following [VOICE](VOICE.md), when
  Brenden is ready to try it.
- Later: vision and voice models, a security review, FileVault and
  separate-account testing, and more than two Macs.

## Tests

New tests cover the in-row progress card: it is hosted under the
matching model, falls back to the top of the list when that model is
not shown, is re-attached after the list is redrawn, stays visible
when the row is closed, scrolls into view when a download starts,
and is described that way in the Models and browser guides.

New tests also cover the First token chart: the 0.28s bar is shorter
than the 0.46s bar (about 61% as long), a longer wait is the longer
bar at every size, Reading and Writing bars are unchanged, and
`--ascii` and the block-character chart agree on which bar is shorter.

New tests cover GGUF Prompt lookup and Guess-ahead: the launch flags
(including that a missing helper and any download flag are refused),
finding a smaller same-family model already on disk, Settings rows
(Auto/Off/On, On disabled without a helper), Auto-tune trying Prompt
lookup last and skipping it for Two chats or a pin, Self-tuning not
trying it, and a faster but garbled Prompt lookup trial treated as a
loss.

The Voice design notes are in the docs: listening first, words appear
in the chat box, the chat model stays loaded, and no listening code is
shipped yet.

New tests cover the daily update check: a newer published version is
detected, a fresh result is cached and an old one is checked again, an
offline Mac keeps the last result and stays quiet, the daily switch
skips automatic checks but still allows Check now, the model-stays-
loaded preview follows the same path prefixes as `caravan update`,
`caravan update --check` prints the plain result, Update now is refused
from a local-network address and during a chat reply or Auto-tune, and
the chat page has the Update available badge and the Updates section
in Settings.

New tests also cover updating every other Mac: the 1st Mac asks each
known Mac (2nd, 3rd, 4th, and so on) over the existing connection,
other Macs are updated first, a Mac that is off or that fails does
not stop the rest or this Mac, `--local-only` and a one-Mac
environment flag do not ask the other Macs, and the daily check
shows when a Mac is on an older version. When a Mac couldn't be
reached, the update failed, it is still on the previous version, or
the model didn't come back, Settings shows plain step-by-step help
under that Mac, with Try again. Update now over Tailscale is allowed
only when the share is on and the address matches a live Tailscale
address; a made-up Tailscale name and a local-network request are
still refused.
