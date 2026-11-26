Day 33: the installer and update set up the own-part engine (CAR-10).

- **Split at download, as the norm.** Install and `caravan update` now set up the own-part engine on every configured Mac. For a single-file Llama or Qwen2 GGUF, a missing toolchain should no longer push a split pick to the slower "over the cable" option.
- **A prepared build when one is published; fail-soft until then.** The preferred path is a checksum-checked download, with no developer tools needed. This release leaves that pin empty; a ready-made copy can be published later, and no checksum is invented. Until then, a Mac that has Apple's Command Line Tools, git and cmake builds the engine from source. If those tools aren't there, setup prints a short "Hey, I'm sorry…" note and continues, so a first-time install still finishes. Caravan itself still works. `caravan doctor` says whether the engine is ready.
- Several-file models and types other than Llama or Qwen2 are unchanged: Step 2 still offers the cable split or one Mac.
- Not run on the Macs as part of this release's testing; the tests use stand-ins for the Macs and the download source.
- Tests: 2,426 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
