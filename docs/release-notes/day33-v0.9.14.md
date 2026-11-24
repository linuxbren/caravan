Day 33 first-token timing in Auto-tune (ROADMAP #2).

- **First-token timing in Auto-tune.** Auto-tune now weighs the time to the first word on the long test prompt together with write speed when it tries Guess-ahead or Prompt lookup (GGUF and MLX). A helper that delays the first word is kept only when generation speed pays back the wait on a whole long-prompt reply. If first-token time is missing, the older chat-only verdict is unchanged. Auto-tune still uses the existing ~2k-token long prompt; it does not run an extra long one.
- Tests: 2,273 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
