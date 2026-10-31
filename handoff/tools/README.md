# Helper scripts (from the old assistant's computer)

All of them read the Mini password from the environment variable `MINI_SSH_PASSWORD`;
none contains it. They need `pip install paramiko`, plus userspace `tailscaled` with
SOCKS5 on `127.0.0.1:1055` (see `../README.md`).

| file | what |
|---|---|
| `rc.py` | `python3 rc.py <1|2> run '<cmd>'`, `put <local> <remote>`, `get <remote> <local>`. 1 = prf-hays-exo01 (lead), 2 = prf-hays-exo02 (packer). Retries 6 times, then prints "socks fail" (restart tailscaled). |
| `mini.py` | Older one-shot version: `python3 mini.py '<cmd>'` on EXO1. |
| `rerun.sh` | The exact Oct 31 v3 rerun: start the packer on EXO2 and the lead on EXO1 (test ports), run `bench/v3/split_client.py bench`, stop both. Usage: `rerun.sh <tag> <lead model dir> <packer model dir> [no_think]` (run from the folder holding `rc.py`; it `cd`s to `/tmp/cv`, so adjust). |
| `parse_split_bench.py` | Summarizes split_client `.jsonl` results (`<tag>.jsonl`, `<tag>-old.jsonl`: medians of writing / reading speed, quality) into the numbers used in the log. |
