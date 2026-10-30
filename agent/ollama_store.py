"""Checks this node's local Ollama store to answer the one question the
whole role-detection design rests on: "do I have model X pulled locally?"
See docs/ARCHITECTURE.md, "Role determination -- self-declared, not
elected".

Reads Ollama's on-disk manifest/blob layout directly rather than calling
`ollama list`/`ollama show`, because resolving a model name to the actual
GGUF blob path llama-server needs for `-m` requires the manifest's layer
digests anyway -- `ollama list` doesn't expose those. Verified against a
real manifest on this machine (see docs/LOG.md) rather than guessed:

    ~/.ollama/models/manifests/registry.ollama.ai/library/<name>/<tag>
        -> JSON, layers[].mediaType == "application/vnd.ollama.image.model"
           is the GGUF blob, layers[].digest "sha256:<hex>" maps to
    ~/.ollama/models/blobs/sha256-<hex>   (dash, not colon, in the filename)

Model names follow Ollama's own conventions:
    "name" / "name:tag"                 -> registry.ollama.ai/library/name/tag
    "namespace/name:tag"                -> registry.ollama.ai/namespace/name/tag
    "host/namespace/name:tag"           -> host/namespace/name/tag (e.g. hf.co/...)
Tag defaults to "latest", same as Docker/Ollama. $OLLAMA_MODELS overrides
the store root, same as Ollama itself.

Also usable as a CLI, so the hand-written launchd plist's hardcoded blob
path can be regenerated for any model without editing code:

    python3 agent/ollama_store.py                 # resolve the configured model
    python3 agent/ollama_store.py qwen3:30b       # resolve a specific model
    python3 agent/ollama_store.py --list          # every model in the store
"""
from __future__ import annotations  # keeps `X | None` hints 3.9-safe

import json
import os
import sys
from pathlib import Path
from typing import Optional

OLLAMA_HOME = Path.home() / ".ollama"
MODELS_DIR = Path(os.environ.get("OLLAMA_MODELS", str(OLLAMA_HOME / "models"))).expanduser()
MANIFESTS_ROOT = MODELS_DIR / "manifests"
DEFAULT_REGISTRY = "registry.ollama.ai"
MANIFESTS_DIR = MANIFESTS_ROOT / DEFAULT_REGISTRY / "library"
BLOBS_DIR = MODELS_DIR / "blobs"

GGUF_LAYER_MEDIA_TYPE = "application/vnd.ollama.image.model"


def _split_name_tag(model: str) -> tuple:
    # Tag is whatever follows the last ":" *after* the last "/" -- so a
    # registry host with a port ("host:5000/ns/name") isn't mistaken for
    # a tag.
    head, slash, last = model.rpartition("/")
    if ":" in last:
        last, tag = last.split(":", 1)
    else:
        tag = "latest"
    return head + slash + last, tag


def _manifest_path(model: str) -> Path:
    name, tag = _split_name_tag(model.strip())
    parts = name.split("/")
    if len(parts) == 1:
        return MANIFESTS_DIR / parts[0] / tag
    if len(parts) == 2:
        return MANIFESTS_ROOT / DEFAULT_REGISTRY / parts[0] / parts[1] / tag
    return MANIFESTS_ROOT.joinpath(*parts) / tag


def has_model(model: str) -> bool:
    return _manifest_path(model).exists()


def resolve_blob_path(model: str) -> Optional[Path]:
    """Returns the local GGUF blob path for `model`, or None if the model
    isn't pulled locally or its manifest doesn't have a model layer."""
    manifest_path = _manifest_path(model)
    if not manifest_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text())
    for layer in manifest.get("layers", []):
        if layer.get("mediaType") == GGUF_LAYER_MEDIA_TYPE:
            digest = layer["digest"].replace(":", "-", 1)
            blob_path = BLOBS_DIR / digest
            return blob_path if blob_path.exists() else None
    return None


def list_local_models() -> list:
    """All model names with a manifest on this node, "name:tag" form
    (library models), "namespace/name:tag" or "host/ns/name:tag" otherwise."""
    if not MANIFESTS_ROOT.exists():
        return []
    models = []
    for tag_file in sorted(MANIFESTS_ROOT.rglob("*")):
        if not tag_file.is_file() or tag_file.name.startswith("."):
            continue
        rel = tag_file.relative_to(MANIFESTS_ROOT).parts
        if len(rel) < 3:
            continue
        *name_parts, tag = rel
        if name_parts[0] == DEFAULT_REGISTRY:
            name_parts = name_parts[1:]
            if name_parts and name_parts[0] == "library":
                name_parts = name_parts[1:]
        models.append("/".join(name_parts) + ":" + tag)
    return models


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Resolve an Ollama model name to its local GGUF blob path "
                    "(what llama-server's -m needs)."
    )
    parser.add_argument("model", nargs="?", default=None,
                        help="Model name; default is the configured target model "
                             "($CARAVAN_MODEL / ~/.caravan/config.json / muse-glimmer).")
    parser.add_argument("--list", action="store_true", help="List local models and exit.")
    args = parser.parse_args(argv)

    if args.list:
        for m in list_local_models():
            blob = resolve_blob_path(m)
            print(f"{m}\t{blob if blob else '(no GGUF blob)'}")
        return 0

    model = args.model
    if model is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import config  # noqa: E402 -- only needed for the default
        model = config.resolve_target_model()

    blob = resolve_blob_path(model)
    if blob is None:
        print(f"error: {model!r} not found in {MANIFESTS_ROOT} (or has no GGUF layer). "
              "Try --list.", file=sys.stderr)
        return 1
    print(blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
