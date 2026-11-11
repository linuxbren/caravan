"""Official whole-GGUF runtime. The custom own-share backend stays isolated."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
import urllib.request

PIN = json.loads((Path(__file__).resolve().parents[1] / "runtime/llama-release.json").read_text())


def location(home=None):
    return Path(home or Path.home()) / ".caravan/runtime/llama" / PIN["version"]


def ready(home=None):
    root = location(home)
    try:
        return (root / "release.sha256").read_text().strip() == PIN["sha256"] and all(
            (root / n).is_file() and os.access(root / n, os.X_OK)
            for n in ("llama-server", "ggml-rpc-server")) and (root / "libggml-rpc.dylib").is_file()
    except OSError:
        return False


def bin_dir(home=None):
    root = location(home)
    if ready(home):
        return root
    return Path(os.environ.get("CARAVAN_LLAMA_BIN", "~/dev/llama.cpp/build/bin")).expanduser()


def ensure(home=None, retrieve=urllib.request.urlretrieve):
    """Verify before extraction; stage on same filesystem, keep older releases."""
    root = location(home)
    if ready(home):
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists() or root.is_symlink():
        raise ValueError("The model engine folder is incomplete. Keep it for inspection and run caravan doctor.")
    with tempfile.TemporaryDirectory(dir=root.parent, prefix="download-") as tmp:
        archive = Path(tmp) / "release.tar.gz"
        retrieve(PIN["url"], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != PIN["sha256"]:
            raise ValueError("Model engine download failed its safety check. Retry setup.")
        stage = Path(tmp) / "unpack"
        stage.mkdir()
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                dest = (stage / member.name).resolve()
                if not dest.is_relative_to(stage.resolve()) or member.isdev() or member.isfifo() or member.islnk():
                    raise ValueError("Unsafe model engine archive")
                if member.issym() and not (dest.parent / member.linkname).resolve().is_relative_to(stage.resolve()):
                    raise ValueError("Unsafe model engine archive link")
            if hasattr(tarfile, "data_filter"):
                tar.extractall(stage, filter="data")
            else:  # Python 3.10: validated members above.
                tar.extractall(stage)
        extracted = stage / ("llama-" + PIN["version"])
        for name in ("llama-server", "ggml-rpc-server", "libggml-rpc.dylib"):
            if not (extracted / name).is_file():
                raise ValueError("Model engine archive is missing a required file: " + name)
        (extracted / "release.sha256").write_text(PIN["sha256"] + "\n")
        extracted.rename(root)
    return root


if __name__ == "__main__":
    print("Model engine ready:", ensure())
