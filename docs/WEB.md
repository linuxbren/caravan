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

## Settings and optimization

**Self-tuning** stays visible in Settings and is on by default: Caravan learns
faster settings from your chats. After a self-tuning or Optimize now run
finishes for the loaded model, a quiet line in that same Self-tuning section
shows how fast the model was before and after, for example "Before: 31
words/s, first word in 2.1 s. After: 42 words/s, first word in 1.2 s." The
line stays hidden until a run has finished for this model, and it is kept
on the 1st node with the other speed averages. Every other optimization — Guess-ahead,
Prompt lookup, Shared start, Two chats, Fused kernels, Memory compression,
GPU keep-warm, and **Optimize now** — sits under an **Advanced** section that
is closed until you open it, along with **Apply & restart**. Toggling
Self-tuning On or Off takes effect immediately on a loaded MLX model, without
reloading. Leave Auto when unsure. The other settings require a reload (use
Apply & restart) and not every model supports every feature. See
[configuration](CONFIGURATION.md).
**Optimize now** runs real comparisons and may reload the model; do not start
it during an important chat. See [optimization](OPTIMIZE-NOW.md).

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

The browser has no login. Fresh installs bind localhost; never expose it to
the public internet. [Security](SECURITY.md) explains the trust boundary.

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
