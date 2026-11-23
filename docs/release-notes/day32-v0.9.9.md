Day 32 Spanish localization, a mid-day release (Day 32 continues; Japanese, Simplified Chinese and Russian can drop in later).

- **Spanish (beta) in Settings.** Caravan can show the page, the `caravan` command and the installers in Spanish. Open Settings, pick **Español (beta)**, and the page switches. Your choice is remembered on that Mac. You can also set `CARAVAN_LANG`. If you don't pick one, Caravan uses the Mac's language when it has a strings file, otherwise English. Spanish is marked beta until a native speaker reviews it.
- **Numbers and dates in Spanish.** Decimal comma, thousands separator (1.234,5), lists with "y", and dates like "13 de noviembre".
- Built so later languages can drop in: a CLDR plural engine, one strings file per language (`locales/es.json` for every current English key), and the same language setting for the page, the command and the installers. Model names, Caravan, Mini, GGUF, MLX and commands stay in English.
- Tests: 2,176 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#spanish-v099).
