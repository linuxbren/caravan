# Day 26 — Download progress under the model, a clearer First-token chart, and GGUF speed-ups

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

## What is still ahead (same Day 26)

- **GGUF Phase 3:** prompt lookup and a draft model, off by default,
  measured per model.
- **Voice:** listening first — a microphone in the chat box and a
  listen worker. Design notes only unless a clearly safe piece is
  ready.
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
