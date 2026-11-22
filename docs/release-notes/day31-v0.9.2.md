Day 31 follow-up. Caravan now says "context" everywhere it meant the model's context, so the page, Settings and the placement lines use one word.

- **"Context", not "window".** The 1-Mac-or-split line now reads, for example, "Fits on 1 Mac with a 64K context. Split across 2 Macs for the full 128K context." The same goes for the placement choices, the too-big reason, the greyed-out sizes in Settings, the Settings chip, notes in the load log and `caravan bench` skip reasons.
- **Settings row renamed.** **Chat window** is now **Context**, with the same help in plain words. The saved setting is still `chat_window`, so anything you pinned keeps working.
- Wording only: how Caravan decides between one Mac and a split, and how much context Auto picks, are unchanged. 2,033 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY31.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY31.md#follow-up-the-app-says-context-v092).
