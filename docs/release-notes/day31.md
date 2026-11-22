Day 31 release. Caravan now checks whether a model fits with its full chat window, and the model lists match what's really on your Macs.

- **Fit counts the chat window.** When Caravan decides between one Mac and a split, it now counts the memory for the model's full default chat window, not just its files. If one Mac only fits a shorter window, it recommends the split and says so in plain words, for example "Fits on 1 Mac with a 64K window. Split across 2 Macs for the full 128K window." You can still pick one Mac. GGUF uses the same numbers as Chat window Auto, MLX uses the model's real settings file, a Mac whose memory can't be read never counts as a fit, and every part of a multi-part GGUF download is counted.
- **Settings only lists downloaded models.** The list of models to load shows only models whose files are complete on the Mac or Macs that will run them: no partial downloads, no split missing its other half. Deleting a model updates the list right away.
- **Topology matches Settings.** Topology's On disk list now uses the same checks, so the GGUF models show there too, and exo's cache folder no longer shows up as a model. A model on disk that can't load yet is marked "Not in Settings: files incomplete". You can delete GGUF models from Topology.
- **Code folder fix.** Topology showed an old developer folder as each Mac's code folder. It now shows where Caravan really runs from, and a Mac without a saved path falls back to the install folder.
- Checks on two Macs: Llama 3.1 8B and gpt-oss 20B fit on 1 Mac with their full 128K window; Qwen3 30B-A3B (GGUF) is recommended as a split for its full 32K window. Settings and Topology list the same models on both Macs. 2,028 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY31.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY31.md).
