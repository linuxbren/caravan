# Developer setup

For everyday use, use the [Mac installer](../INSTALL.md). This page is for
people changing Caravan's source. See [node names](README.md#names-used-in-these-guides)
if you are reading older build logs.

## Get a separate working copy

Use a folder you own. Do not point development work at an active installation.

```sh
git clone --branch caravan-v3-mlx-split https://github.com/linuxbren/caravan.git "$HOME/projects/caravan"
cd "$HOME/projects/caravan"
```

On an Apple Silicon Mac with a native Python, preview before installing:

```sh
bash scripts/install.sh --repo "$PWD" --use-existing --python /absolute/path/to/python3 --dry-run
```

Remove `--dry-run` when ready. Source installation supports native Python
3.10+; the easy package supplies its own tested Python and exact-version wheels.
Use `--no-start` if the Mac has no logged-in desktop session. A running custom
service is never silently adopted or replaced. See [SERVICES](SERVICES.md).

## Test without models

```sh
PYTHONPATH=.:proxy:tests python3 -m unittest discover -s tests
```

Portable tests can run on a development node that is not a Mac. MLX imports,
GPU inference, launchd, reboot recovery and FileVault require separate Mac
checks. For an isolated Mac smoke, use a fresh HOME, unused ports and a unique
`--name`; never reuse a production service label. No live model is needed.

## Work across Macs safely

`lead-mac` and `helper-mac` are example SSH aliases you configure yourself.
Use the actual source path on each Mac, not somebody else's build-log path.
Commit and push reviewed changes, then use `git pull --ff-only` in each intended
checkout. Check for local changes first; never reset or copy over them. Do not
clone another copy to work around an access problem.

Restart only what changed, at a safe time. A web restart must preserve model
workers (`CARAVAN_WEB_KEEP_WORKERS=1`, set by generated service plans). Do not
reboot, change SSH trust, delete model files or alter another person's services
as a documentation step. Follow [daily release checks](RELEASES.md).

## Legacy compatibility boundaries

The source still contains original-test-environment fallbacks in
`web_nodes.DEFAULT_NODES`, `web_catalog.DEFAULT_PACKER_SSH` /
`DEFAULT_PACKER_PEER`, and older picker/worker alias matching. Their inventory
IDs, display labels, default SSH address and remote checkout path have **not**
been renamed in this documentation pass, because existing installations may
rely on them. Use an explicit `[web.nodes.*]` inventory with your own trusted
names, endpoints and repository paths. The easy installer creates a local-only
entry and does not install the old remote defaults. Changing those fallbacks
safely is a separate migration, not a find-and-replace of documentation.

Several older remote gather, download, discovery, adoption and cleanup paths
also retain a legacy helper source-path fallback. In particular, the worker
manager has older direct launch/cleanup commands as well as inventory-aware
paths. Those behavioral assumptions are intentionally unchanged here and still
need a separate portability/migration audit before calling arbitrary multi-Mac
networks turnkey. Explicit inventory is the supported documented starting point;
it does not erase every legacy fallback in the source.
