| Model / placement | Route | Cache | Prompt / cached | Generated | TTFT native / wire (s) | First visible answer (s) | Write tok/s | Full wall (s) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Huihui 27B 24/40 | direct | cold | 54 / 0 | 275 | 1.275 / 1.795 | 36.712 | 6.62 | 42.748 |
| Huihui 27B 24/40 | direct | warm | 54 / 53 | 275 | 0.298 / 0.925 | 35.754 | 6.63 | 41.785 |
| Huihui 27B 24/40 | hermes | cold | 11,322 / 0 | 226 | 177.438 / 177.684 | 195.202 | 6.30 | 213.413 |
| Huihui 27B 24/40 | hermes | warm | 11,326 / 11,287 | 183 | 1.436 / 3.090 | 19.019 | 6.30 | 32.043 |
| Qwen3 30B-A3B 24/24 | direct | cold | 52 / 0 | 174 | 0.387 / 0.548 | 3.766 | 44.94 | 4.308 |
| Qwen3 30B-A3B 24/24 | direct | warm | 56 / 47 | 181 | 0.127 / 0.246 | 3.919 | 44.87 | 4.170 |
| Qwen3 30B-A3B 24/24 | hermes | cold | 11,229 / 0 | 238 | 36.269 / 36.366 | 43.898 | 29.20 | 44.449 |
| Qwen3 30B-A3B 24/24 | hermes | warm | 11,233 / 11,196 | 415 | 0.569 / 1.097 | 14.623 | 29.20 | 15.241 |
