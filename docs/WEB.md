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
reading/writing times from the worker, not simulated performance. Reasoning
may be shown separately when supported by the model. Stop cancels the current
reply; **Unload** releases the loaded model and disables next-login restore.

Closing the browser does not unload the model. To stop the web service, use
`~/.caravan/bin/caravan stop`; its model workers remain running. Unload first
if you want their memory freed. See [safe removal](../INSTALL.md#remove-caravan-safely).

## Balance work between Macs

In Topology, **Balance** starts on Auto and shows memory use for each Mac.
**Adjust** reveals the controls and a live preview. **Apply** is black when a
changed plan is ready; it is grey when no change is needed or during reload.
A banner shows each Mac's reload steps. Chat is locked until the model is ready.
Changing the split moves memory use between Macs; it does not create memory.
Use **Back to auto** to let Caravan choose the split again.

Plans support an ordered set of Macs. Real inference has been tested on two
physical Macs; software simulations are not proof of a larger physical setup.
Some older picker/Optimize paths are still two-stage: do not run Optimize on
an N-stage Balance load. Missing files and unknown capacity must be resolved
before a reload, not bypassed with a forced load.

## Thunderbolt checks

The panel inspects configured, trusted Macs. Inventory and link checks are
read-only. Requested checks show verified/unverified/failed and expire after
30 seconds. A reachable port alone does not verify SSH identity. A plan preview
does not apply routes, pair Macs, install keys or authenticate model transport.

## Settings and optimization

Settings can choose thinking, chat-memory compression and optional performance
features. Leave Auto when unsure. Some settings require a reload and not every
model supports every feature. See [configuration](CONFIGURATION.md).
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
