"""Resumable single-file download with HTTP Range (Day 18).

hf_xet keeps no partial file, so a stopped download restarted from 0.
This writes <dest>/.cache/huggingface/download/<name>.incomplete (the path the
progress meter already counts) and, on the next run, asks for
`Range: bytes=<have>-` so it continues where it stopped. On completion the
file is checked against the expected size and moved into place.
"""
from __future__ import annotations

import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

CHUNK = 1 << 20
HF_URL = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")


def partial_path(dest: Path, name: str) -> Path:
    return Path(dest) / ".cache" / "huggingface" / "download" / (name + ".incomplete")


def file_url(repo: str, name: str, revision: str = "main") -> str:
    return "%s/%s/resolve/%s/%s" % (HF_URL, repo, revision, urllib.parse.quote(name))


def fetch(repo: str, name: str, dest, size: int, token: str | None = None,
          opener=None, url: str | None = None) -> dict:
    """Download one file. Returns {"resumed_from": bytes, "fetched": bytes, "skipped": bool}."""
    dest = Path(dest)
    final = dest / name
    if final.is_file() and size and final.stat().st_size == size:
        return {"resumed_from": size, "fetched": 0, "skipped": True}
    part = partial_path(dest, name)
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.is_file() else 0
    if size and have > size:
        part.unlink(); have = 0
    start = have
    if not size or have < size:
        req = urllib.request.Request(url or file_url(repo, name))
        req.add_header("User-Agent", "caravan-range-fetch/1")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        if have:
            req.add_header("Range", "bytes=%d-" % have)
        op = opener or urllib.request.urlopen
        with op(req, timeout=60) as r:
            code = getattr(r, "status", None) or r.getcode()
            if have and code != 206:
                have = 0  # server ignored Range: start over
            with part.open("ab" if have else "wb") as f:
                while True:
                    b = r.read(CHUNK)
                    if not b:
                        break
                    f.write(b)
        start = have
    got = part.stat().st_size
    if size and got != size:
        raise RuntimeError("%s: have %d of %d bytes; Resume to continue" % (name, got, size))
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(part), str(final))
    return {"resumed_from": start, "fetched": got - start, "skipped": False}
