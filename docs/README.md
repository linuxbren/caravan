# Caravan documentation

New here? Start with [How to install Caravan](../INSTALL.md). You do not need
to know the project's build history to use it.

## Names used in these guides

- **Development node** (or dev machine): the computer used to edit, test and
  manage the project. It need not run models or use a particular operating system.
- **1st node** (first Mac, or lead): the Mac hosting Caravan's browser page.
- **2nd node** (second Mac, or helper): another Mac sharing the model workload.
  More helpers can be added; this is not a two-Mac limit.
- **Model worker**: the background process that runs a model. An internal
  `packer` role means a helper; a `stage` is one part of a split model.

Older build logs called the development node `Omarchy`, the 1st node `EXO1`,
and the 2nd node `EXO2`. Those were names in the original test environment,
not required products, an operating-system requirement, or names for your Macs.
Historical records retain their measured machine details and original commands.

Commands in current guides may use `lead-mac` and `helper-mac` as **example SSH
names**, not built-in aliases. Replace them with your own trusted Mac names.
`YOUR_MAC_USER` and `YOUR_*_ADDRESS` are placeholders. Documentation addresses
in `192.0.2.0/24` are examples, not usable network settings. Default installation
uses your own home folder; no particular person's username or private network
is required. Never paste an old build-log command into your Mac unchanged.

## Everyday use

[Install and recovery](../INSTALL.md) · [Browser controls](WEB.md) ·
[Models and downloads](MODEL_PICKER.md) · [Add/remote Macs](REMOTE-ACCESS.md) ·
[Security](SECURITY.md) · [Package status](PACKAGING.md) ·
[License](../LICENSE) (MIT)

## Development and technical details

[Developer setup](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) ·
[Configuration](CONFIGURATION.md) · [Services](SERVICES.md) ·
[MLX](MLX.md) · [Split models](MLX-SPLIT.md) · [File placement](FILES.md) ·
[Client integration](INTEGRATING.md) · [Optimization](OPTIMIZE-NOW.md) ·
[Measurement method](METHODOLOGY.md) · [Roadmap](ROADMAP.md) ·
[Daily release checklist](RELEASES.md) · [Voice design (listening first)](VOICE.md)

## History and evidence

[Build log](LOG.md) · [Measured results](BENCHMARKS.md) ·
[Historical guide/test-environment snapshots](history/README.md).
History describes what was tested then; it is not a promise about every Mac.

[Adding Macs securely](PAIRING.md) · [Cleanup candidates (approval required)](CLUTTER.md) · [Paused C++ experiment](history/cpp/README.md).

## License

Caravan is open source under the [MIT License](../LICENSE). Copyright (c)
2026 Brenden Dawson. One adapted file keeps its own MIT notice:
[agent/native_mtp.LICENSE](../agent/native_mtp.LICENSE).
