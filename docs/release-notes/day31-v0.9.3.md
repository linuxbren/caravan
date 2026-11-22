Day 31 follow-up. Pre-quantized (4-bit) MLX models now load when split across two Macs, even when the model's files are cut in an awkward place.

- **Fixed: Qwen3 32B (MLX, 4-bit) split load.** The load stopped on the 1st Mac with `KeyError: 'model.layers.17.mlp.up_proj.weight'`. One piece of a layer the other Mac runs had its weight in a file only that Mac holds and its 4-bit scales in a file both Macs hold, and the loader wanted both. Caravan now leaves that piece alone (it is dropped after load anyway) and names it in the load log. The fix was first made on the Macs during setup and is now part of Caravan.
- Older MLX loaders load as before. Loads on one Mac and models that aren't pre-quantized are unchanged. 2,038 tests pass.

Install or update:

```
(set -o pipefail; curl -fsSL https://raw.githubusercontent.com/linuxbren/caravan/main/install | bash)
```

Already installed: `caravan update`. Details: [docs/DAY31.md](https://github.com/linuxbren/caravan/blob/main/docs/DAY31.md#follow-up-4-bit-mlx-split-load-fix-v093).
