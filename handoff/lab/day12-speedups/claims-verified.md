# Claude claim verification (from docs/BENCHMARKS.md + experiments.md)

| Claim | Source numbers | Computed | Verdict |
|---|---|---|---|
| Qwen3 guess-ahead +30% | baseline **45.5** → draft 0.6B k=3 **59.3** (count) | (59.3-45.5)/45.5 = **+30.3%** | **True** |
| Llama 8B +127% | nodraft **22.7** → auto-pair 1B k=3 **51.5** (count) | (51.5-22.7)/22.7 = **+126.9%** ≈ +127% | **True** |
| Qwen2.5 14B +173% | nodraft **12.4** → 0.5B k=3 **33.8** (count) | (33.8-12.4)/12.4 = **+172.6%** ≈ +173% | **True** |
| GPT-OSS stuck at 34.3 | BENCHMARKS baseline **34.0**; ROADMAP/experiments **34.3**; no draft | ~**34.0–34.3**, no helper | **True** (34.3 is the rounded/auto figure; measured nodraft table shows 34.0) |
