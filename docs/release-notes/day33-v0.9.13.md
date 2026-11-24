Day 33 Guess-ahead helper for MLX on one Mac (ROADMAP #1).

- **A helper for MLX on one Mac.** An MLX model running on one Mac can use the same Guess-ahead helper as a split MLX model and as GGUF. The setting is still Auto, Off, or On. Caravan checks that a matching helper is on this Mac and that it fits in the memory left after the main model is loaded. If the helper is missing, incompatible, or does not fit, load continues without it and the log says why. A reply that used guesses still ends with "guesses kept N%". Auto-tune can try the helper once it is loaded. When a known helper is not downloaded yet, Settings shows "Download helper for faster replies?" with Download and Not now. A Balance split still does not use a helper.
- **Native MTP does not load a second helper.** If you pick Native MTP (experimental), Caravan does not also auto-pair or load a conventional Guess-ahead helper beside the MTP head.
- Tests: 2,247 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
