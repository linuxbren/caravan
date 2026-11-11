# Models, downloads and placement

The **Models** drawer searches models, checks what fits and downloads the
required files. It is part of the browser page on your first Mac (1st node /
lead). You do not need names from the build log to use it.

## Sources and fit

Choose the intended model source/engine. Hugging Face hosts MLX and GGUF files;
GGUF execution needs the separate patched llama.cpp runtime. A GGUF download
does not install that runtime. Optional cloud choices use a provider rather
than your local Macs; choose them explicitly if you intend to send data there.

Fit is based on usable capacity, the selected placement, reclaimable memory
from the current model, and disk space on every participating Mac. More memory
or more Macs lets larger models fit. Caravan calculates the plan; a colored
fit hint is not permission to ignore a load-time safety check.

## Choose where files go

- **One Mac:** keep and run the complete model on that selected Mac.
- **Split:** keep the files required by each participating Mac's assigned part.
- **All Macs / copies:** keep a complete copy on every selected Mac. This is not
  the same as splitting the work.

Configured nodes, not personal SSH names, define the available Macs. The easy
installer creates a local-only inventory. Legacy source-only launches without
explicit inventory still have old test-environment fallbacks: outside that
setup, define your own `[web.nodes.*]` as described in
[configuration](CONFIGURATION.md#web-ui-nodes-caravanconfigtoml).

Downloads run directly on each Mac from the publisher; setup does not copy the
lead's model folder to a helper. Watch per-Mac progress, disk requirements and
missing files. Large downloads can pause while the publisher's transfer tool
works; the UI distinguishes observed bytes from an unknown total. Resume/retry
behavior depends on the file/source path. Check visible errors rather than
assuming a stalled-looking download has finished.

## Load, change a split, or remove files

Load respects the saved placement and checks required local files. A one-Mac
load should not start an unrelated helper. For changing the work split, use
[Balance](WEB.md#balance-work-between-macs); preview first, then Apply.
Older picker/Optimize paths remain two-stage; use the N-stage Balance path for
more Macs and do not Optimize that load.

The current normal GGUF RPC path keeps the full GGUF on the lead and can cache
peer tensors. It does not yet meet the independent per-Mac GGUF loading goal.
Experimental shard/native-loader work is separate, not a bundled runtime.

Deletion is a separate explicit action. Inspect which files are on which Mac;
protect active models, saved plans and owned services. Uninstall does not delete
models. [FILES](FILES.md) explains storage and the current limitations.

## Credentials and troubleshooting

Some models need the publisher's terms accepted and an access token. Use the
Settings token control; never put a token in an issue or command pasted for
others. Token status is shown without echoing its value. Check connectivity,
free disk, file placement and publisher access before retrying a failed load.

Implementation history, earlier fit/display bugs and API sketches are preserved
in [the model-picker development record](history/MODEL_PICKER-LAB.md).
