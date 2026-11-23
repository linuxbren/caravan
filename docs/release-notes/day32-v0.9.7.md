Day 32 localization step 1, a mid-day release (Day 32 continues with choosing and adding languages).

- **All text in one English strings file.** Everything Caravan shows you — the web page, the `caravan` command, the installers, and the messages from the web server and the Macs' workers — now comes from one file, `locales/en.json` (2,299 strings). Nothing reads differently: the English text is the same as before.
- **Ready for other languages.** The page and server now use codes instead of matching English words, and plurals ("1 Mac" / "2 Macs"), numbers with units and lists are built for any language. No other language is added yet and there is no language picker.
- **Left as they are on purpose:** logs, the request journal, lab and developer tools, benchmark and model prompts, config names and command lines.
- A flaky browser test is fixed. 2,144 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY32.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY32.md#localization-step-1-english-strings-file).
