# Use Caravan in your browser

Setup opens the page on the first Mac (the **1st node**, also called the lead).
Later run `~/.caravan/bin/caravan open`. For access from a development node,
use the [remote-access guide](REMOTE-ACCESS.md). No particular hostname,
operating system for the dev machine, or personal SSH alias is required.

## Choose a model

Open **Models**, search for a model, and check its fit and download location.
More memory or adding Macs lets larger models fit; Caravan checks each Mac's
capacity and files for you. Start with a small model. Download, then **Load**.
No model is bundled with the installer. Publisher terms may apply.

A one-Mac placement uses only the selected Mac. A split placement runs different
parts on participating Macs. A copy on every Mac is not the same as a split.
Only select Macs you configured and trust. See [models/downloads](MODEL_PICKER.md)
and [file placement](FILES.md).

## Chat and stop

Type in the chat box and send. The page streams the reply and reports measured
reading/writing times from the worker, not simulated performance. Each reply
has its own timing line, for example "Read 165 tok at 200 tok/s · Write 10 tok
at 20.7 tok/s · first token 0.34s · total 0.78s". Under the input box, a quiet
average appears once this model has answered at least once with the current
optimizations. It uses the same wording, units, and rounding, with a leading
Average label: "Average · Read 165 tok at 200 tok/s · Write 10 tok at 20.7
tok/s · first token 0.34s · total 0.78s". The numbers are averages for this
model and this set of optimizations. A field with no data yet is left out.
The average is kept on the
1st node in `~/.caravan/speed_averages.json`, separately for each model and
each set of optimizations, so a change of settings starts a new average. The
line is hidden until there is something to show. Thinking may be shown
separately when the model supports it. **New session** starts a fresh chat
without unloading the model. The chips under the input sit in a **Current optimizations** box, in the same order as Settings (Self-tuning first), with a
short hover hint on each chip. They are labels, not switches. Stop cancels the
current reply; **Unload** releases the loaded model and disables next-login restore.

Closing the browser does not unload the model. To stop the web service, use
`~/.caravan/bin/caravan stop`; its model workers remain running. Unload first
if you want their memory freed. See [safe removal](../INSTALL.md#remove-caravan-safely).

## Balance work between Macs

In Topology, **Balance** and **Thunderbolt** stay collapsed until you click
them. Balance starts on Auto and shows memory use for each Mac.
**Adjust** reveals the controls and a live preview. **Apply** is black when a
changed plan is ready; it is grey when no change is needed or during reload.
A quiet line says when this split is already applied, or when it is not safe
to apply, or when a new split is ready. A banner still shows each Mac's
reload steps while a reload is running. Chat is locked until the model is ready.
Changing the split moves memory use between Macs; it does not create memory.
Use **Back to auto** to let Caravan choose the split again.

Plans support an ordered set of Macs. Real inference has been tested on two
physical Macs; software simulations are not proof of a larger physical setup.
Some older picker/Optimize paths are still two-stage: do not run Optimize on
an N-stage Balance load. Missing files and unknown capacity must be resolved
before a reload, not bypassed with a forced load.

## Thunderbolt checks

The panel stays collapsed until you click it. It inspects configured, trusted
Macs. Inventory and link checks are
read-only. Requested checks show verified/unverified/failed and expire after
30 seconds. A reachable port alone does not verify SSH identity. A plan preview
does not apply routes, pair Macs, install keys or authenticate model transport.

## Look

The theme switch at the top of the page offers **Amber**, **Green**,
**Meadow**, and **Campfire**. Campfire is a cool night sky with a soft
moon, crisp stars, a dark tree line, and a campfire glowing low, drawn
in the page itself with no photos. Panels are frosted and dark, with
amber accents, and the text stays readable. The logo, chips, dialogs,
helper prompt, drawers, model picker, download cards, and Topology bars
(in Theme mode) all follow the chosen theme, including on a phone. If
you had previously chosen Nebula, the page opens in Campfire instead.

## Settings and optimization

**Self-tuning** stays visible in Settings and is on by default: Caravan learns
from your chats and remembers faster settings for each model; pinned choices
stay yours. Below a thin divider, **Auto-tune** sits outside Advanced,
with the hint "Tries different settings on the loaded model right now and
keeps the fastest." An indented block holds **Start** (or **Tune again**)
and **Reset tuning**, a short note, and the Before and After lines.
Auto-tune works whether Self-tuning is On or Off. The primary button
says **Start** when this model has never been tuned, and **Tune again**
once a run has finished and a result is saved. After Reset tuning
clears those results, it says **Start** again. Either label runs a
fresh trial on the loaded model — you do not need to remove or
redownload it. Reset tuning clears the saved results for this
model and puts Memory compression back to Auto; the model stays
loaded, and is reloaded at Auto if it was running a tighter value. After a Self-tuning or Auto-tune run
finishes for the loaded model, two quiet lines in Auto-tune
show how fast the model was before and after, for example
"Before · Write 88.4 tok/s · first token 0.29s" and
"After · Write 94.5 tok/s · first token 0.15s". The wording, units, and
rounding match the stats under each reply and the average under the chat
input. Extra fields that were recorded (Read, token counts, total time)
are included; a field with no data is left out. Self-tuning results feed
the same Auto-tune lines. If a run finds nothing faster, or the two sides
would look the same, the page shows one line instead: "Already at its
fastest settings. Nothing faster found." The slot is reserved so the rows
below do not jump. The lines stay empty until a run has finished for
this model, and they are kept on the 1st node with the other speed
averages. Every other optimization — Guess-ahead,
Prompt lookup, Shared start, Two chats, Fused kernels, Memory compression,
and GPU keep-warm — sits under an **Advanced** section that
is closed until you open it, along with **Apply & restart**. There is no
Tune or Optimize button inside Advanced. Toggling
Self-tuning On or Off takes effect immediately on a loaded model, without
reloading. The switch does not show a conflicting "now: off" line.
Leave Auto when unsure. The other settings require a reload (use
Apply & restart) and not every model supports every feature. See
[configuration](CONFIGURATION.md).
**Auto-tune** runs real comparisons and may reload the model; do not start
it during an important chat. See [optimization](OPTIMIZE-NOW.md).

When a GGUF model is loaded, Self-tuning, Memory compression, Shared start,
**Flash attention**, and **Prompt batch** are used, with plain-word hints.
Memory compression offers Auto, 16, and 8 only (never 4). Guess-ahead and
Prompt lookup stay off for now. Fused kernels and GPU keep-warm are hidden,
because they do not apply. Self-tuning on a GGUF model reloads when you
are not mid-reply. Auto-tune also compares 16-bit and 8-bit memory
compression and scores how fast the model reads, how soon the first
token arrives, and how fast it writes, so the two Before and After
lines work for GGUF as well.

If a Self-tuning or Auto-tune trial stops, a short plain reason
appears next to Self-tuning, for example
"Self-tuning stopped while trying Memory compression. A trial setting
was rejected. The model is back on the previous settings." The full
detail goes to the log only.

At login, Caravan restores the last successful model and placement. Temporary
node/memory/link readiness failures retry within a bounded window. Missing
files are not automatically downloaded. FileVault needs its owner to unlock
and log in before login services can start.

## Problems or reports

Run `~/.caravan/bin/caravan doctor`, then `status` for the log path. Check that
each selected Mac is reachable, has its own files, and has enough available
memory. Start with a smaller model rather than bypassing safety checks.
The model-report link opens an editable report; review it before submitting.
Never include tokens, private chats, usernames or real network addresses.

If a model load fails with "Couldn't start the model on the 2nd Mac. Try loading again.", the full detail is in the log on that Mac. Caravan
reuses its own leftover SSH forward when it still works, or replaces
only that process when it does not. It never stops a process that is
not its own. Try loading again. If it still fails, check that the other
Mac is reachable.

If Self-tuning or Auto-tune stops with a short reason next to
Self-tuning, the model is usually already back on the previous
settings. The full detail is in the log (`caravan doctor`, then
`status` for the path).

The browser has no login. Fresh installs keep the page only on this Mac.
You can turn on **Open on my local network** in Settings or run
`caravan lan on`. Anyone on the same network can use Caravan, and there is no login. `caravan lan status` shows the address to open
(`http://<lan-ip>:<port>`), and a clickable link appears under the
switch the same way the Tailscale link is shown. This can be on at the
same time as **Open from my other devices**; both addresses stay
reachable. Turn it off with `caravan lan off` or the
same Settings switch; the page goes back to this Mac only, and the
Tailscale share is unchanged. Turning the
switch does not unload a model that is already loaded. Never expose
the page to the public internet. [Security](SECURITY.md) explains the
trust boundary.

If a reply comes out garbled (blank, leftover markers, or a short
chunk repeated many times), a plain note appears under it, for example
"This reply came out garbled, so Memory compression was turned back to
16." Caravan puts that model back on safe settings and will not pick
the bad setting again in Auto-tune or Self-tuning. If settings are
already safe, the note says so and nothing else is changed.

## Developer details and history

The page is served by `proxy/web_server.py`; model processes are managed through
`proxy/web_workers.py`, not by sweeping process names. Generated web services
set `CARAVAN_WEB_KEEP_WORKERS=1`. API/configuration keys and legacy fallback
identities have not been renamed by the public documentation cleanup.

Implementation notes, earlier screenshots, bug investigations and measurements
are preserved in [the web development record](history/WEB-LAB.md).


## Add Macs

**Add Macs** opens a separate, private per-account page. It discovers installed
Macs, confirms a one-use code, saves SSH/config trust and can remove a connection.
See [everyday steps](../INSTALL.md#add-minis) and [security scope](PAIRING.md).
The ordinary remote/LAN app view is not permission to pair Macs; use the page
on the Mac itself. `caravan add-mini` opens the private browser session if needed.
Pairing does not apply routes, reload the current model or bypass Remote Login.
