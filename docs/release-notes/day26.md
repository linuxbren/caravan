# Day 26 (Nov 13 2026)

Published Nov 13 CST; development-day tag `day26-2026-11-13`.

## Changed
- In the Models list, download progress sits under the model you
  clicked.
- In `caravan bench`, First token bars follow the seconds: a shorter
  bar is a sooner reply. Each live run is saved, and
  `--from-averages` shows "Last bench" or "Saved".
- GGUF Prompt lookup and Guess-ahead are Auto, Off, or On under
  Advanced.
- Caravan checks once a day for a newer version. An Update available
  badge appears, with Check now and `caravan update --check`.
- Update now works on this Mac and over Tailscale. It is refused on
  the local network and on a public Funnel address; the local network
  shows no Updates section.
- The 1st Mac updates every other Mac first, then itself.
- A short Updates card shows one line per Mac, with Try again when a
  Mac failed. The button shows Updating… with a campfire and a step
  line.
- The page reloads itself after an update, in every open tab once
  nobody is typing or waiting on a reply.
- A newly published version can take about 5 minutes to appear.
- Voice design notes (no listening code yet).

An update from the Day 25 tag keeps a loaded model running. The web
page still restarts.

## Operational checks
- Day 26 was approved after live review.

Details: [DAY26.md](https://github.com/linuxbren/caravan/blob/day26-2026-11-13/docs/DAY26.md). Install: [INSTALL.md](https://github.com/linuxbren/caravan/blob/day26-2026-11-13/INSTALL.md).
