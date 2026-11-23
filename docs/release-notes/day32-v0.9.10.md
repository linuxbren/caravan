Day 32 Russian localization, a mid-day release (Day 32 continues; Japanese and Simplified Chinese can drop in later).

- **Russian (beta) in Settings.** Caravan can show the page, the `caravan` command and the installers in Russian. Open Settings, pick **Русский (beta)**, and the page switches. Your choice is remembered on that Mac. You can also set `CARAVAN_LANG`. If you don't pick one, Caravan uses the Mac's language when it has a strings file, otherwise English. Russian is marked beta until a native speaker reviews it.
- **Numbers and dates in Russian.** Decimal comma, a space as the thousands separator (1 234,5), lists with "и", and dates like "13 ноября".
- Built on the same language setting as Spanish: one strings file per language (`locales/ru.json` for every current English key, with one/few/many/other forms everywhere counts appear). Model names, Caravan, Mini, GGUF, MLX and commands stay in English.
- Tests: 2,187 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#russian-v0910).
