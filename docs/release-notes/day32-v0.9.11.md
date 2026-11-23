Day 32 Japanese localization, a mid-day release (Day 32 continues; Simplified Chinese can drop in later).

- **Japanese (beta) in Settings.** Caravan can show the page, the `caravan` command and the installers in Japanese. Open Settings, pick **日本語 (beta)**, and the page switches. Your choice is remembered on that Mac. You can also set `CARAVAN_LANG`. If you don't pick one, Caravan uses the Mac's language when it has a strings file, otherwise English. Japanese is marked beta until a native speaker reviews it.
- **Numbers and dates in Japanese.** Dates like 2026年11月13日 and 2026年11月, lists with "、" and "と", and numbers like 1,234.5.
- Built on the same language setting as Spanish and Russian: one strings file per language (`locales/ja.json` for every current English key, with `_other` only for plural forms). Model names, Caravan, Mini, GGUF, MLX and commands stay in English. The page uses CJK line breaking and fonts that cover Japanese.
- Tests: 2,198 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#japanese-v0911).
