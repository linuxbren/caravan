Day 33: a GGUF split pick downloads each Mac's part (CAR-9).

- **Split means split.** Pick a split across your Macs for a GGUF model and each Mac downloads only its own part, even when the model would also fit on one Mac. The model then runs only as that split. Pick one Mac and that Mac downloads the whole file; it isn't a split.
- **The bug this fixes.** When a model fit on one Mac but Step 2 recommended 2 Macs for its full chat window, accepting the split downloaded the whole file to the 1st Mac only.
- **No quiet fallbacks.** Before anything downloads, every picked Mac is checked. If one can't take its part, Caravan names the Mac and what it needs, and nothing is downloaded. When per-Mac parts can't work for a file (several files, or a model type other than Llama or Qwen2), Step 2 says so first and offers "Split across N Macs over the cable" (only the 1st Mac downloads) or one Mac.
- **Where it goes.** Each Step 2 choice says where the download goes, and the download card shows each Mac's part. Split-only models show in Topology → On disk, and Delete removes each Mac's part.
- The first split download on a Mac builds the own-part engine there, which needs Apple's Command Line Tools, git and cmake. Setting it up from the installer and update is next (CAR-10).
- Not run on the Macs as part of this release's testing; the tests use stand-ins for the Macs and the download source.
- Tests: 2,403 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
