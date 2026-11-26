#!/usr/bin/env python3
"""Pack a built own-part engine into the checksummed archive ensure() installs.

Run on an Apple Silicon Mac after the engine is built (gguf_runtime.ensure(),
or a tree laid out the same way). Writes a tar.gz whose top folder is
caravan-gguf-shards-<8-char pin>, containing caravan-shards-version and
build/bin (the two servers plus any dylibs next to them). Prints the sha256.

Does not upload the archive or edit runtime/gguf-shards-release.json: put the
file on a https URL (a GitHub release asset is fine), then set url and sha256
in that pin file. Nothing is invented here.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import gguf_runtime as R  # noqa: E402


def tree_from(src: Path) -> Path:
    src = src.resolve()
    if (src / "caravan-shards-version").is_file() and (src / "build" / "bin").is_dir():
        return src
    # Allow passing build/bin
    if src.name == "bin" and src.parent.name == "build":
        return src.parents[1]
    raise SystemExit(f"not an own-part engine tree: {src}")


def pack(src: Path, dest: Path) -> str:
    src = tree_from(src)
    if not R._bin_ok(src):
        raise SystemExit("engine tree is missing the marker or the two servers")
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    # Only regular files under the marker, build/bin, and optional release.sha256.
    include = ["caravan-shards-version"]
    bindir = src / "build" / "bin"
    for path in sorted(bindir.iterdir()):
        if path.is_file() and not path.is_symlink():
            include.append(str(path.relative_to(src)))
    sha_file = src / "release.sha256"
    if sha_file.is_file() and not sha_file.is_symlink():
        include.append("release.sha256")
    with tarfile.open(dest, "w:gz") as tar:
        for rel in include:
            info = tar.gettarinfo(src / rel, arcname=f"{R.ARCHIVE_DIR}/{rel}")
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with (src / rel).open("rb") as fh:
                tar.addfile(info, fh)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    print(dest)
    print(digest)
    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from",
        dest="source",
        default=None,
        help="PIN directory (contains caravan-shards-version and build/bin). Default: the engine already on this Mac.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Archive path (default: ./<archive name from the pin file or caravan-gguf-shards-<pin>.tar.gz)",
    )
    args = parser.parse_args(argv)
    if args.source:
        src = Path(args.source).expanduser()
    else:
        src = R.location()
        if not R._bin_ok(src):
            raise SystemExit("no ready own-part engine on this Mac; build it first or pass --from")
    name = (R.release_pin().get("archive") or f"{R.ARCHIVE_DIR}-macos-arm64.tar.gz")
    dest = Path(args.output).expanduser() if args.output else Path.cwd() / name
    pack(src, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
