Day 32 Simplified Chinese localization, a mid-day release (the last planned Day 32 language; Spanish, Russian, Japanese and Simplified Chinese are now in Settings, each marked beta until a native speaker reviews it).

- **Simplified Chinese (beta) in Settings.** Caravan can show the page, the `caravan` command and the installers in Simplified Chinese. Open Settings, pick **简体中文 (beta)**, and the page switches. Your choice is remembered on that Mac. You can also set `CARAVAN_LANG`. If you don't pick one, Caravan uses the Mac's language when it has a strings file, otherwise English. Tags such as `zh-CN` map to Simplified Chinese; Traditional tags such as `zh-TW` do not. Simplified Chinese is marked beta until a native speaker reviews it.
- **Numbers and dates in Simplified Chinese.** Dates like 2026年11月13日 and 2026年11月, lists with "、" and "和", numbers like 1,234.5, and ordinals like 第1 / 第2.
- Built on the same language setting as Spanish, Russian and Japanese: one strings file per language (`locales/zh-Hans.json` for every current English key, with `_other` only for plural forms). Model names, Caravan, Mini, GGUF, MLX and commands stay in English. The page uses CJK line breaking and fonts that cover Simplified Chinese.
- Tests: 2,213 pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#simplified-chinese-v0912).
