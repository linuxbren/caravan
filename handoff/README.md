# Handoff: start here (for the next assistant)

You're taking over from Brenden's previous assistant. Brenden had signed up for it under
the wrong account and is moving to his X account. This folder holds everything the old
assistant knew, so you can carry on exactly where it stopped. It was written on
**Sat Oct 31 2026, about 6:45 PM CDT**, at branch tip `0e9f1df` (plus the commit that
added this folder).

**This repo is PUBLIC.** It contains no secrets, no email addresses, and no tailnet IP
addresses. Secrets are named only (for example `MINI_SSH_PASSWORD`); Brenden has to give
them to you again. Never commit one.

Read this file first, then [`memory.md`](memory.md) (everything the old assistant
remembered, word for word) and [`routines.md`](routines.md) (the two daily reminders to
recreate). [`lab/`](lab/) is a copy of the old assistant's working folder: the
experiment log, the roadmap snapshot, the video scripts, and every video. [`tools/`](tools/)
holds the small helper scripts it used to reach the Minis.

---

## 1. Who Brenden is and what the job is

- **Brenden** (GitHub `linuxbren`) builds **Caravan** in the open: his homebrew app for
  running AI models across his two Mac minis (GGUF through llama.cpp, MLX through mlx-lm,
  and since v3 one MLX model split across both Macs). He lives in US Central time
  (America/Chicago). Report every time in Central (CDT until Sun Nov 1 2026, then CST).
- **Your job** (from memory):
  1. Do the Caravan engineering work he asks for on the Minis: code, benchmarks and docs.
  2. Log every experiment in the lab log (`lab/experiments.md`, newest first). Each entry
     has: date, goal, hardware, runtime, model and quant, config, results, what broke,
     fix or next step, and post status.
  3. Turn the work into daily X posts and lab videos for him to approve.
  4. Send him two reminders a day (see `routines.md`).
- He likes plain language, short replies, and a quick "here's what I expect" before a test.
  He decides; you suggest. Ask before anything that deletes, commits, pushes, tags,
  merges, or stops a service, unless he has already said go for that exact step.

## 2. Hardware and network

| | EXO1 = **lead** | EXO2 = **packer** (Packer 1) |
|---|---|---|
| Tailscale hostname | `prf-hays-exo01` | `prf-hays-exo02` |
| Local name | `prf-hays-exo01-2.local` | — |
| Thunderbolt address | `169.254.4.161` (en2) | `169.254.104.38` |
| Caravan checkout | `~/dev/caravan-v3` (branch `caravan-v3-mlx-split`) | `~/cv3` (same branch) |

- Both are a **Mac mini M4** (Mac16,10): 10 cores (4 performance + 6 efficiency), 24 GB,
  500 GB disk, macOS 26.6.2. They're cabled directly over Thunderbolt/USB4 (40 Gb/s,
  a Thunderbolt 4 cable). See `lab/hw-check.txt`.
- **SSH:** user `brenden`, password login (keyboard-interactive). Tailscale SSH is
  **off**, so you need normal SSH over the tailnet. The password is the secret
  **`MINI_SSH_PASSWORD`**: ask Brenden to set it again as a secret on your account. Never
  print, echo, log or commit it.
- **The remote shell is zsh.** An unmatched glob is an error, so use `setopt nullglob`.
  There's no `timeout` command.
- **Low Power Mode must be OFF on both Minis for benchmarks.** EXO2 had it on during
  every two-Mac run before Oct 31 at 6 PM. Check with `pmset -g | grep lowpowermode` and
  say so if it's on. Only Brenden changes it.
- Other folders on EXO1:

  | Folder | What it is |
  |---|---|
  | `~/dev/caravan` | `main`, c026359 |
  | `~/dev/caravan-improvements` | `improvements-1-3`, c846e65 |
  | `~/dev/caravan-v2` | `caravan-v2-mlx-cache`, 7835efd |
  | `~/dev/caravan-v2.1` | `caravan-v2.1`, 24adc11 |
  | `~/dev/llama.cpp` | Branch `caravan-patches`, locally at 2f26123 (the v0 patch). Its `origin` is `linuxbren/llama.cpp` and its `upstream` is ggml-org. |
  | `~/dev/llama.cpp-rebase` | `caravan-patches-rebase-2026-10-30`, 86e1620: the rebased fork that v1+ uses |
  | `~/dev/exo` | exo |
  | `~/cv3` | Not a git repo: an old work folder |
  | `~/.caravan/` | Config, venvs, models, bench output |

- Folders on EXO2: `~/dev/caravan` (main, 0d70875) and `~/cv3` (the branch). There's also
  `~/cv3.pre-rename-2026-10-31`, a backup from before the lead/packer rename; keep it.
- **MLX:** the venv is `~/.caravan/venvs/mlx/bin/python` (mlx 0.32.4, mlx-lm 0.32.2) on
  both Minis.
  - EXO1 keeps its 4-bit MLX models in `~/.exo/models` and its 8-bit ones in
    `~/.caravan/mlx-models`.
  - EXO2 has all six (3 models × 4-bit and 8-bit) in `~/.caravan/mlx-models`.
  - Each packer keeps its own share of a model on its own disk. That's a firm rule; see
    `docs/ROADMAP.md`.

### How the old assistant's computer reached the Minis

It ran Tailscale in userspace mode and used a local SOCKS5 proxy:

```bash
# install tailscale (Debian/Ubuntu): curl -fsSL https://tailscale.com/install.sh | sh
sudo nohup tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
  --state=/var/lib/tailscale/tailscaled.state > /tmp/tailscaled.log 2>&1 &
sudo tailscale up --hostname=<pick-a-name>        # prints a login URL for Brenden to approve
#   or: sudo tailscale up --authkey=<NEW auth key from Brenden> --hostname=<pick-a-name>
tailscale status                                   # should list prf-hays-exo01 / prf-hays-exo02
```

- The old computer was named `grokbot-llm-lab`. After a reboot on Oct 30 it was
  `grokbot-llm-lab-1`. Ask Brenden to remove the old node from his tailnet admin page
  once you're in.
- Never commit an auth key. It's a secret, like the password.
- `tools/rc.py` does SSH via paramiko through the SOCKS5 proxy (`pip install paramiko`).
  It reads the password from `MINI_SSH_PASSWORD`:

  ```bash
  python3 handoff/tools/rc.py 1 run 'cd ~/dev/caravan-v3 && git status -sb'   # 1 = EXO1, 2 = EXO2
  python3 handoff/tools/rc.py 2 put ./local.txt /tmp/remote.txt
  python3 handoff/tools/rc.py 1 get /remote/file ./local
  ```

- **"socks fail"** means rc.py gave up after 6 retries because userspace tailscaled
  dropped. Restart it with the same `tailscaled` command above, wait about 5 s, and
  retry. That fixed it every time.
- Remote paths: use `~` inside single quotes so it expands on the Mini. Quote carefully.
  Copy files to `/tmp/...` on the Mini first, then `mv` them into place.

## 3. GitHub

- The repo is **github.com/linuxbren/caravan** (public, default branch `main`).
- The patched llama.cpp fork is **github.com/linuxbren/llama.cpp**:
  - `caravan-patches` = `caravan-patches-rebase-2026-10-30` = 86e1620 (current);
  - `caravan-patches-v0` = 2f26123 ("rpc: use getaddrinfo instead of gethostbyname", the
    old version).
- **Who can push where:**
  - The Minis' saved GitHub login is the **RookiOS72** account. It can push to
    `linuxbren/caravan` from EXO1, which is how every Caravan commit was pushed.
  - It **can't** push to the `linuxbren/llama.cpp` fork. Fork pushes went from the
    assistant's own computer, using `gh` logged in as `linuxbren`.
  - On your new computer, run `gh auth login` and have Brenden sign in as linuxbren, if
    you need it (fork pushes, releases, API checks).
- **Commits are by "Rook":**

  ```bash
  git -c user.name=Rook -c user.email=<Rook's address> commit
  ```

  Rook's address is the one on the existing commits (`git log -1 --format=%ae`). It's
  left out here because the repo is public.
- **Remote branches:** `main` (c026359; README says main = v2.1), `caravan-v2.1`, and
  `caravan-v3-mlx-split` (current work, **not merged to main**). `improvements-1-3` and
  `caravan-v2-mlx-cache` exist only on EXO1, but their commits are already in the v3
  branch.
- **Tags:** `v2.1`, `v3` (→ df68468), and `v3.1` (→ 2260d2e). Never move them.
- Push normally. Never force push, never `--no-verify`, and don't touch `main` or tags
  unless he asks.

## 4. Standing rules (always)

1. **Never post on X or use any posting tool.**
   - Draft the post in chat and revise it until he approves.
   - Then give him `https://x.com/intent/post?text=<URL-encoded text>` links, so he
     presses Post himself.
   - Also don't follow any X accounts until he chooses which.
2. Never show or commit secrets (`MINI_SSH_PASSWORD`, Tailscale keys, GitHub tokens).
3. No deletes, commits, pushes, tags, merges or stopping services unless he asked for
   that step. No force pushes, no `--no-verify`.
4. **Don't touch Talaria Hub.** The only related thing ever run was the read-only
   `~/macstax/talaria_check.sh` on EXO2 after restoring exo.
5. **exo and Hermes:** pause or leave them alone during Caravan work, but keep them
   restorable. Since Oct 30 at 8:16 PM he has said they can stay down for a few days.
   See section 10.
6. **Don't invent numbers.** Every number comes from the log, a bench output, or git.
7. Use **lead / packer / string** naming everywhere, never head/front/tail:
   - the **lead** is the Mac you talk to; it picks each token and runs the last layers;
   - the **packers** are the other Macs, numbered in layer order (Packer 1 runs the
     first layers);
   - the **string** is the whole group.

   Old log entries from before Oct 31 keep their old words.
8. Keep `docs/ROADMAP.md` current with every change, including a "Deferred / parked"
   section. Add an entry to `docs/LOG.md` and `lab/experiments.md` for every session.
9. Firm design rule: **each packer keeps its share of the model on its own disk** and
   downloads only its own parts from the source, never through the lead. This applies to
   MLX and GGUF alike.
10. Low Power Mode off on both Minis for benchmarks. Plain language. Times in Central.

## 5. Post style (X)

- **Always open with the day of development plus what Caravan is.** For example: "Day N
  of building Caravan in the open, my homebrew app for running AI models across my Mac
  minis."
- **Day 1 = Fri Oct 30 2026.** Count up each calendar day (memory says Oct 31 = Day 2).
- Posts have gone out a day or two after the work, and the **video and post titles use
  the day of the post**:
  - v6 is "Day 3" (for Nov 1);
  - v8 is "Day 4" (the thread scheduled for Mon Nov 2).

  Check with Brenden which day number the next post gets.
- **Audience:** a friend who's into computers and AI but doesn't know local-AI lingo
  (GGUF, MLX, tok/s, TTFT, tg128, and other lab shorthand). Confident show-your-work
  tone — teach by explaining the mechanism crisply, never announce that you're teaching
  ("Teach-along", "Come learn with us", "those pieces are called tokens" is too
  elementary). No condescending basics; no insider bench jargon on screen or in posts.
- **Voice:** hands-on, mad-scientist homebrew, concrete numbers. Prefer one tight post
  (under 280 characters), or a short thread only when there's a lot.
- **Cover three things:**
  1. what we did;
  2. key stats vs the previous version and the **v0 baseline** (commit 45ed2c2, the
     Oct 30 numbers in `lab/experiments.md`);
  3. what's next.
- Suggest attaching the day's lab video if there is one.
- After he approves, mark the log entry's post status "drafted". Update it again when he
  posts or schedules it.

**Plain labels:**

| Say | Not |
|---|---|
| writing speed (or "tokens/sec (how fast it writes)" once, then writing speed) | tg / tg128 / tok/s alone |
| reading speed | pp |
| wait before the first word | TTFT |
| top half / bottom half of the model (or the Mini you talk to / the other Mini) | N=, K=, agg, pipeline depth |

- Avoid lab shorthand on screen and in posts: tg128, TTFT, GGUF, MLX as unexplained
  jargon, KV, q8_0, f16, SWA, ub, N=, K=, agg.
- You may use "tokens per second" if glossed in context once; otherwise say writing
  speed. Don't stop to define what a token is.

## 6. Lab video conventions

- ID `LAB-YYYY-MM-DD-NN`, file `videos/YYYY-MM-DD_topic-slug_vN.mp4`, and a row in
  `videos/index.md` with ID, date, file, title, source experiment, duration and status.
- **Don't put the ID or filename inside the video.**
- The title slide shows "Day N", matching the post's day.
- Benchmark videos show **Caravan's latest version and the one before it**, next to the
  other runtimes (llama.cpp, Ollama, LocalAI, exo) as reference bars.
- Use the plain labels and audience guidance from section 5 (techie friend, not
  grandmother; no "we're teaching" framing).
- Superseded videos are kept and marked "superseded" in the index.
- **How they're made:** `lab/videos/make_runtime_video_v12.py` is the newest Day 6 cut (v8/v9 still the older style refs). It's a
  Python script: PIL frames, numbers from `v8_data.json`, and the Inter fonts in
  `lab/videos/fonts/` (SIL OFL), encoded with ffmpeg. Copy the latest script for the next
  video and change the data and slides.
- Every video is committed in `lab/videos/`:

  | ID | File | Size |
  |---|---|---|
  | LAB-2026-10-30-01 | `2026-10-30_runtime-compare_llamacpp-ollama-exo_v1.mp4` | 2.0 MB |
  | LAB-2026-10-30-02 | `2026-10-30_runtime-compare_caravan-llamacpp-ollama-exo_v2.mp4` | 2.6 MB |
  | LAB-2026-10-30-03 | `2026-10-30_runtime-compare_caravan-localai-llamacpp-exo_v3.mp4` | 2.8 MB |
  | LAB-2026-10-30-04 | `2026-10-30_caravan-v0-vs-v1_runtime-compare_v4.mp4` | 3.3 MB |
  | LAB-2026-10-31-01 | `2026-10-31_caravan-v1-vs-v2_mlx-chat-memory_v5.mp4` | 4.0 MB (superseded by v6) |
  | LAB-2026-10-31-02 | `2026-10-31_caravan-v1-vs-v2_mlx-chat-memory_v6.mp4` | 4.0 MB ("Day 3") |
  | LAB-2026-10-31-03 | `2026-10-31_caravan-v2.1-vs-v3_mlx-split_v7.mp4` | 3.7 MB (superseded by v8) |
  | LAB-2026-10-31-04 | `2026-10-31_caravan-v2.1-vs-v3_mlx-split_v8.mp4` | 4.1 MB ("Day 4", scheduled with the Mon Nov 2 thread) |

  `lab/videos/stills_v8/` has key frames of the latest video.

## 7. Roadmap preferences

- He wants "best of both worlds": as robust as llama.cpp, for GGUF **and** MLX, with one
  model split across Macs when it doesn't fit on one. MLX became item 2 on Oct 30.
- `docs/ROADMAP.md` in the repo is the source of truth. It has:
  - done by version;
  - next, in order;
  - ideas for beating the turn-taking in the split;
  - "Deferred / parked";
  - known limits.

  `lab/caravan-ROADMAP.md` is the old assistant's planning copy.
- **Suggested next, as of Nov 1 (after Day 7 guess-ahead):**
  1. Brenden's go to **push** local idea-3 commits and cut a milestone tag (likely v3.5).
  2. GPT-OSS still has no small same-vocab draft — park or hunt a compatible helper.
  3. Then per-model profiles, proxy overhead, memory headroom, and cold-disk restore.
  4. Housekeeping: make the bench scripts warn or refuse when `pmset -g` shows
     `lowpowermode 1` on either Mac.
  - Done since Oct 31 evening: idea 5, idea 1 (+ stall fix), Day 6 video v12, idea 3
    guess-ahead auto-pair (Qwen 45.9→59.7, Gemma 38.4→44.5, GPT-OSS skip 34.3;
    shut-off 0.438<0.80), Gemma final-answer-only quality gate + Day 7 video v13.
    Tags `v3.3` / `v3.4` pushed; idea-3 commits local only until push go.
- **Parked:** idea 4, splitting each layer across both Minis. It's a no-go: about 330–410
  µs per exchange, 48–96 exchanges per token. Even with Low Power Mode off, the estimate
  is 21.1 / 24.7 / 26.7 tok/s, vs v3's 30.4 / 27.7 / 26.6 and one Mini's 51.0 / 41.3 /
  36.5.

## 8. Benchmark method

- `docs/BENCHMARKS.md` has the details; the bench scripts are in `bench/`. The short
  version:
  - Same models every time: Qwen3 30B-A3B, Gemma 4 26B-A4B and GPT-OSS 20B (4-bit, plus
    8-bit builds for the split).
  - Report medians of 2+ runs, plus a 3-question quality check (3/3).
  - Measure writing speed (128 tokens), reading speed (512 and 4k prompts), wait before
    the first word, resume after restart, and peak memory per Mac.
- **One Mac:** pause exo on that Mini, as the old assistant did.
- **Two Macs (v3):**
  - Start the packer on EXO2:

    ```bash
    ~/.caravan/venvs/mlx/bin/python agent/mlx_worker.py --split-role packer --split-listen 169.254.104.38:5560 --model <dir> --cache-dir <dir>
    ```

  - Start the lead on EXO1:

    ```bash
    ... --split-role lead --split-peer 169.254.104.38:5560 --model <dir> --port 8194
    ```

  - Run `bench/v3/split_client.py bench http://127.0.0.1:8194 <name> <out.json>`, then
    stop both workers. `tools/rerun.sh` is exactly what was run on Oct 31.
- Use test ports (8194, 5560, 5572), never the production ports.
- Write output to `~/.caravan/bench-YYYY-MM-DD/...` on the Minis.
- **Each log entry needs:** goal, hardware, software and commit, config, results table,
  takeaway, deficiencies, "would be faster / more robust if", and post status.
- Before a test, tell Brenden what you expect. Afterwards, compare against that.

## 9. Version history

| Version | Commits | Branch / tag | Date |
|---|---|---|---|
| pre-v0 ("llama-shard") | 7182c6b … 3287f51, bd73b0a | — | Sep 2026 |
| **v0** (baseline) | 45ed2c2 | — | Oct 30 |
| v1: rebased llama.cpp with sliding-window slot restore, MLX routing, auto cache precision | 32b9756, 737fea2, c846e65 | `improvements-1-3` (EXO1 only) | Oct 30 |
| v2: MLX chat save/restore | f57af3b, 6d4bdb0, fac73b8, f73eafb, 7835efd | `caravan-v2-mlx-cache` (EXO1 only) | Oct 31 |
| v2.1: steadier MLX | b9ebeb7, docs 24adc11 | `caravan-v2.1`, tag `v2.1` | Oct 31 |
| main | c026359 | `main` (= v2.1) | |
| **v3**: one MLX model split across two Macs (lead/packer) | b03d1e9, a167835, d68e094, 83f86a9, 14dfcb4, 8a64430, docs df68468 | tag `v3` → df68468 | Oct 31 |
| **v3.1**: shard size check, cable benchmark | 7bf332f, d23a276, e49567e, 2260d2e | tag `v3.1` → 2260d2e | Oct 31 |
| after v3.1 | 49d222d (changelog), f68d15e (GPU-wait test), 0e9f1df (Low Power Mode rerun) | `caravan-v3-mlx-split` tip | Oct 31 |

## 10. Current state (Sat Oct 31 2026, about 6:45 PM CDT)

- **Code:** the branch `caravan-v3-mlx-split` tip is 0e9f1df (plus this handoff commit).
  - It's pushed, clean on EXO1 `~/dev/caravan-v3`, and EXO2 `~/cv3` is at the same
    commit.
  - **Not merged to main.** The merge is waiting on Brenden's review.
- **Latest results** (v3 rerun with Low Power Mode off, 6:10–6:25 PM CDT):

  | Model (4-bit) | Writing speed (tok/s) | Reading speed, 512 / 4k (tok/s) |
  |---|---|---|
  | Qwen3 | 30.4 | 451 / 408 |
  | Gemma 4 | 27.7 | 411 / 375 |
  | GPT-OSS | 26.6 | 440 / 424 |

  - Reading speed rose 16–30% and is now within about 6% of one Mac. Writing speed rose
    only 0.5–3% and is still 27–40% slower than one Mac (51.0 / 41.3 / 36.5).
  - Splitting each layer is still a no-go.
  - Logged in `lab/experiments.md` (top entry) and `docs/LOG.md`.
- **Posts:**
  - The **Day 4** thread (v3 two-Mac split, video v8 LAB-2026-10-31-04) is **scheduled
    on X by Brenden for Mon Nov 2**.
  - The Low Power Mode rerun is **not drafted**. It could be a follow-up post.
  - The Day 3 post (v2, video v6) shows "not posted" in the video index, and the old
    assistant didn't track whether Brenden posted it. Ask him.
- **exo:** paused on **both** Minis since Oct 30 at about 8:32 PM CDT; EXO.app isn't
  running. Brenden said it can stay down for now.
  - To restore it when asked:
    1. Run `open -g -a /Applications/EXO.app` on both Minis.
    2. On EXO1, POST to `http://127.0.0.1:52415/place_instance` with
       `{"model_id":"mlx-community/Qwen3.6-35B-A3B-5bit","sharding":"Pipeline","instance_meta":"MlxRing","min_nodes":2}`.
    3. Check Hermes `http://<EXO2's tailnet address>:8642/health`.
    4. Run `~/macstax/talaria_check.sh` on EXO2 (read-only).
  - `lab/bench-2026-10-30/runtime-compare/pre/exo_restore.py` and
    `exo-instance-pre.json` have the original setup.
- **Hermes** (Nous Research Hermes Agent v0.20.5): its desktop app and gateway (launch
  agent `ai.hermes.gateway`) are running on EXO2, but its model backend (exo) is down.
  - Don't touch it.
  - Also leave EXO2's launch agent `com.postrockfoundry.exo-restore` alone.
- **Ollama 0.40.13** (`~/ollama-bench`, models in `~/.ollama`) and **LocalAI** were used
  only as reference runtimes. Neither is running.

## 11. Pending offers and open questions for Brenden

- Draft a follow-up post about the Low Power Mode rerun ("the packer was in Low Power
  Mode; turning it off gave +16–30% reading speed"), with or without a short video.
- Try **idea 5** (uneven split with `--split-packer-layers`) as the next dev session.
- Add the Low Power Mode check to the bench scripts (small housekeeping).
- Merging `caravan-v3-mlx-split` into `main` is waiting on his review. Don't do it unless
  asked.
- Restore exo and Hermes whenever he wants them back.
- Recreate the two daily reminders, with the roadmap text updated (see `routines.md`).

## 12. First steps for the new assistant (checklist)

1. **Secrets:** ask Brenden to add **`MINI_SSH_PASSWORD`** (the Minis' `brenden` password)
   as a secret on your account. Check that it's set with
   `[ -n "$MINI_SSH_PASSWORD" ] && echo set`, which never prints the value.
2. **Tailnet:** install Tailscale and start userspace `tailscaled` with SOCKS5 on :1055
   (section 2). Run `tailscale up` with a login URL he approves, or a **new** auth key he
   gives you. Check that `tailscale status` lists `prf-hays-exo01` and `prf-hays-exo02`.
   Ask him to remove the old `grokbot-llm-lab-1` node.
3. **GitHub:**
   - Run `gh auth login`; Brenden signs in as `linuxbren`.
   - Clone: `gh repo clone linuxbren/caravan && cd caravan && git checkout caravan-v3-mlx-split`.
4. **Restore the lab folder** if you want the old paths:

   ```bash
   mkdir -p /workspace/llm-lab && cp -r handoff/lab/* /workspace/llm-lab/
   ```

   Keep `experiments.md` and `videos/index.md` there up to date, and commit copies back
   here when he asks.
5. **SSH check:**

   ```bash
   pip install paramiko
   python3 handoff/tools/rc.py 1 run 'hostname; cd ~/dev/caravan-v3 && git log --oneline -1'
   python3 handoff/tools/rc.py 2 run 'hostname; cd ~/cv3 && git log --oneline -1'
   ```

   You should see the handoff commit on both (EXO2 after a `git pull --ff-only`).
6. **Routines:** recreate the two daily reminders from `routines.md` (6:00 PM and 8:00 PM
   Central), with the roadmap text updated.
7. **Memory:** save the facts in `memory.md` to your own memory, apart from anything
   secret (there's nothing secret in it).
8. **Say hi to Brenden:** confirm you're connected, then mention the Day 4 thread (Mon
   Nov 2) and the pending offers in section 11.

## 13. Not included (on purpose)

- Secrets: the Mini password, Tailscale auth keys or state, GitHub tokens, cookies.
- Email addresses, the tailnet login, and tailnet IPs. They're replaced with
  `<EXO1-tailnet-IP>` / `<EXO2-tailnet-IP>` in copied logs.
- The large raw exo state dumps from the Oct 30 runtime comparison
  (`exo-state-pre.json`, `exo-state-pre.raw`, `exo-openapi.json`,
  `runtime-compare/exo-state-post*.json`). They held tailnet addresses and weren't needed.
- Model files (tens of GB, on the Minis) and the bench output folders on the Minis
  (`~/.caravan/bench-*`).
- The old assistant's unrelated projects, which belong to other work.
- Four memory facts were cut off by the memory tool; see `memory.md`.
