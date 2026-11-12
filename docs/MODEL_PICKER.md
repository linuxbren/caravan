# Models, downloads and placement

The **Models** drawer searches models, checks what fits and downloads the
required files. It is part of the browser page on your first Mac (1st node /
lead). You do not need names from the build log to use it.

## Filters

The chips above the list narrow what you see.

Shown by default:

- **Chat** — ordinary conversation models.
- **Coding** — models trained to write and edit code.
- **Thinking** — models that can show their reasoning separately (the same
  idea as the chat **Thinking** button). This used to be labelled Reasoning.
- **Tools** — models that can call tools, so an agent app can ask them to
  take an action and use the result.
- **Vision** — models that can look at a picture you give them and answer
  about it (image-text-to-text).

An **Advanced** control, closed until you open it, shows more specialized
types. They stay available, not removed, so Caravan can sit between an
agent app and a model that is not meant for ordinary chat:

- **Embedding** — turns text into numbers so a search tool can find similar
  text. These models do not chat.
- **Any-to-any** — models that accept and produce mixed kinds of input and
  output (for example text and images together).
- **Text-to-image**, **Text-to-video**, and **Text-to-speech** — models that
  make a picture, a video, or spoken audio from text.
- **Speech-to-text** — models that turn spoken audio into text
  (automatic speech recognition, including Whisper-style repos).
- **Decision** — models that classify text, answer yes or no with a
  probability, or score text against a rubric (the kind Ollama labels
  "decision").

Caravan is a chat app, so the default chips are the ones most people need.
The Advanced types are there for agent apps that talk to a model through
Caravan. A source tab (All, HF / MLX, GGUF, Cloud) is separate from these
type filters.

Caravan's own chat can run Chat, Coding, Thinking, Tools, and Vision
models. It cannot yet run the Advanced types (embedding, any-to-any,
text-to-image, text-to-video, text-to-speech, speech-to-text, and
Decision). Those rows still let you download the files — Caravan can
sit as a middle layer — and a quiet line on the row and in the hover
says so, for example "Download only, Caravan can't run image models
yet", "Download only, Caravan can't run video models yet", or
"Download only, Caravan can't run speech models yet" (the same speech
line covers text-to-speech and speech-to-text). After a download
finishes, the card does not offer Load. If Load is requested anyway, the
page shows a short line such as "Caravan can't run image models yet."

The **fits-on** chips limit the list to models that can run on that many of
your Macs. The summary above the list follows the chip you selected — for
example "14 models · fit on 1 Mac · Chat" — and counts only the models that
match. It says Macs, not a technical word for machines.

A **Family** menu sits on its own row, separate from the type chips. It
offers the well-known families that appear in the current results: Qwen,
Llama, Gemma, Mistral, DeepSeek, gpt-oss, and Phi. Only families that have
a match in this search are listed. QwQ counts as Qwen, Mixtral as Mistral,
and CodeLlama as Llama.

Hover a model row for a short extra line or two: the maker, the month and
year it was published, how long a chat it can hold in plain words, and
whether it can use tools or read images. Fields that are not known are
simply left out. The hover does not repeat the row and does not include a
speed figure.

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
lead's model folder to a helper. Each download in progress has its own card,
stacked when more than one is running, with its own bar, size, speed and
waiting time, and its own Stop, Resume, and Load-when-ready controls. A card
stays with its download and does not switch to another one. Both MLX and
GGUF cards use the same friendly Mac name from your Topology (for example
"My Mac", "1st Mac", or "2nd Mac"), never a machine hostname or an internal
id. If a download stops, the card shows a short plain line such as
"Download stopped. Press Resume to try again." The full technical detail
goes to the log on that Mac, not onto the card. Resume continues files
already on disk; you do not need to delete a partial folder first. Large
downloads can pause while the publisher's transfer tool works; the UI
distinguishes observed bytes from an unknown total. Watch disk
requirements and missing files on each Mac.

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
