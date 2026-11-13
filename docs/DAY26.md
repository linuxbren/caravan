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

## What is still ahead (same Day 26)

- **A clearer First-token chart** in `caravan bench`, so a longer
  bar is not mistaken for a slower first token.
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
