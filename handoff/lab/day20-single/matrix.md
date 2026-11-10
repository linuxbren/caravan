# Short, medium

| Model | Placement | TTFT cold / warm s | Write cold / warm tok/s | Wall cold / warm s |
|---|---|---:|---:|---:|
| Huihui Qwen3.5-27B 4-bit | 1× EXO1 | 1.403 / 0.295 | 6.730 / 6.750 | 42.169 / 40.884 |
| Huihui Qwen3.5-27B 4-bit | 2× 24/40 | 1.275 / 0.298 | 6.620 / 6.630 | 42.748 / 41.785 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 1× EXO1 | 0.387 / 0.107 | 16.090 / 16.050 | 3.192 / 2.865 † |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 2× 16/16 | 0.401 / 0.108 | 15.510 / 15.520 | 3.308 / 2.971 † |
| Orvena Qwen3.5-4B 4-bit | 1× EXO1 | 0.220 / 0.054 | 38.680 / 39.070 | 13.323 / 12.993 |
| Orvena Qwen3.5-4B 4-bit | 2× 16/16 | 0.217 / 0.051 | 36.200 / 36.180 | 14.216 / 14.036 |

# Full Hermes, medium

| Model | Placement | TTFT cold / warm s | Write cold / warm tok/s | Wall cold / warm s |
|---|---|---:|---:|---:|
| Huihui Qwen3.5-27B 4-bit | 1× EXO1 | N/A / N/A | N/A / N/A | N/A (Metal OOM; failed after123.562s) |
| Huihui Qwen3.5-27B 4-bit | 2× 24/40 | 177.438 / 1.436 | 6.300 / 6.300 | 213.413 / 32.043 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 1× EXO1 | 50.443 / 0.447 | 15.410 / 15.400 | 60.763 / 10.193 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 | 2× 16/16 | 50.669 / 0.449 | 14.930 / 14.890 | 61.318 / 10.800 |
| Orvena Qwen3.5-4B 4-bit | 1× EXO1 | 28.638 / 0.259 | 33.850 / 33.880 | 33.104 / 5.083 |
| Orvena Qwen3.5-4B 4-bit | 2× 16/16 | 28.770 / 0.266 | 31.650 / 31.700 | 33.513 / 5.566 |

# Astrea short compatibility, explicit none

| Astrea short, explicit none | Cold TTFT / write / wall | Warm TTFT / write / wall |
|---|---:|---:|
| 1× EXO1 | 0.394 / 16.04 / 3.334 | 0.104 / 16.04 / 2.988 |
| 2×16/16 | 0.399 / 15.44 / 3.450 | 0.109 / 15.48 / 3.108 |

# Context budget

| Model / placement | Guard headroom cold →warm GB | Guard prompt budget cold →warm | Successfully tested full prompt |
|---|---:|---:|---:|
| Huihui / single | old metadata invalid; see below | not trustworthy before fix | 54-token short succeeds;11,322-token full OOM |
| Huihui Qwen3.5-27B 4-bit / 2× 24/40 | 2.676 →4.618 | 16,073 →27,927 | 11,322 / 11,326 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 / 1× EXO1 | 11.649 →9.833 | 87,849 →73,999 | 11,435 / 11,439 |
| Astrea Qwen3.5-9B OptiQ mixed4/8 / 2× 16/16 | 5.427 →3.784 | 81,792 →56,714 | 11,435 / 11,439 |
| Orvena Qwen3.5-4B 4-bit / 1× EXO1 | 14.494 →12.736 | 109,554 →96,143 | 11,435 / 11,439 |
| Orvena Qwen3.5-4B 4-bit / 2× 16/16 | 7.150 →5.282 | 108,070 →79,574 | 11,435 / 11,439 |
