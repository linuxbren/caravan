Day 32 GGUF placement, a mid-day release (Day 32 continues with choosing and adding languages).

- **Every GGUF download asks where it goes.** Downloading a GGUF model now opens the same Step 2 chooser as MLX, whether the model fits on one Mac or not: one Mac, split across your Macs, or a copy on each. Options that don't fit stay visible, greyed out, with the reason. The recommended choice is the smallest placement that fits. Your choice is saved and used again when you load the model: only the files you need go to the Macs you picked, and a one-Mac choice is not turned into a split.
- Tests: 2,161 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#gguf-placement-roadmap-9).
