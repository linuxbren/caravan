Day 33: prefer a shipped guesser, else the helper.

- **Prefer a shipped guesser, else the helper.** When an MLX model has its own native MTP head installed and it can run here (one Mac, 16-bit chat memory, Prompt lookup off), Guess-ahead Auto and On use it first. It is kept only when a first-load quality and speed check, or a saved Auto-tune verdict, says it wins; otherwise Caravan's paired helper is used, with the same ask-before-download and fit checks. The head and a helper are never loaded together, splits never use the head, and a Balance split still uses no helper.
- **GGUF:** Caravan's paired helper is picked over another, slightly smaller same-family file on this Mac.
- **Which guesser and why:** the worker log, the Guess-ahead chip ("built-in guesser", reason in its hint), the GGUF load notes and the Helper button say which guesser is in use and why. No helper download is offered while a model uses its own head.
- Not measured on a Mac in this release; the only shipped head Caravan runs today is the Day 17 Orvena 4B MTP head.
- Tests: 2,313 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY33.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY33.md).
