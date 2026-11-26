"""Pinned GGUF own-share backend.

Install and `caravan update` call ensure() on every Mac so a missing
toolchain never pushes a llama/qwen2 split pick to the cable option.

Prefer a pinned prebuilt (URL + sha256 in runtime/gguf-shards-release.json):
checksum-verified extract, no developer tools, same pattern as the official
llama.cpp engine. If no prebuilt is published yet, build the pinned llama.cpp
revision plus Caravan's patch from source (Apple Command Line Tools, git and
cmake). Never patches a production checkout.
"""
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
import subprocess

try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

PIN = "76a67730ffc7d650dffa4db04d96be84a59e7ef3"
MARKER = "catalog-v1/" + PIN
_RELEASE_PATH = Path(__file__).resolve().parents[1] / "runtime" / "gguf-shards-release.json"
ARCHIVE_DIR = "caravan-gguf-shards-" + PIN[:8]


def release_pin():
    """Pinned prebuilt metadata. url/sha256 may be empty until a build is published."""
    return json.loads(_RELEASE_PATH.read_text())


def prebuilt_configured(pin=None):
    """True when a checksummed prebuilt is published and may be downloaded."""
    pin = pin if pin is not None else release_pin()
    url = str(pin.get("url") or "").strip()
    sha = str(pin.get("sha256") or "").strip().lower()
    return url.startswith("https://") and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)


def location(home=None):
    return Path(home or Path.home()) / ".caravan/runtimes/gguf-shards" / PIN


def _bin_ok(root):
    marker = Path(root) / "caravan-shards-version"
    bindir = Path(root) / "build" / "bin"
    try:
        return (
            marker.is_file()
            and marker.read_text().strip() == MARKER
            and all((bindir / n).is_file() for n in ("llama-server", "ggml-rpc-server"))
        )
    except OSError:
        return False


def current(home=None):
    """Return the build/bin directory of the ready own-part engine, or raise."""
    configured = os.environ.get("CARAVAN_GGUF_SHARD_BIN")
    home_path = Path(home or Path.home())
    if configured:
        candidates = [Path(configured).expanduser()]
    else:
        candidates = [
            location(home_path) / "build" / "bin",
            home_path / ".caravan/day22-runtime/build/bin",
        ]
    for b in candidates:
        marker = b.parents[1] / "caravan-shards-version"
        try:
            if marker.is_file() and marker.read_text().strip() == MARKER and all(
                (b / n).is_file() for n in ("llama-server", "ggml-rpc-server")
            ):
                return b
        except OSError:
            continue
    raise FileNotFoundError(T("agent.gguf_runtime.own_part_gguf_backend_is_not"))


def ready(home=None):
    try:
        current(home)
        return True
    except FileNotFoundError:
        return False


def _tool_path(env):
    return os.pathsep.join(
        dict.fromkeys([*env.get("PATH", os.defpath).split(os.pathsep), "/opt/homebrew/bin", "/usr/local/bin"])
    )


def _require_build_tools(env):
    path = _tool_path(env)
    env = dict(env)
    env["PATH"] = path
    if sys.platform == "darwin":
        try:
            clt = subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            clt = False
        if not clt:
            try:
                subprocess.run(["xcode-select", "--install"], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
            raise FileNotFoundError(T("agent.gguf_runtime.apple_command_line_tools_are_needed"))
    missing = [tool for tool in ("git", "cmake") if not shutil.which(tool, path=path)]
    if missing:
        raise FileNotFoundError(T("agent.gguf_runtime.own_part_gguf_backend_needs_tool", tool=", ".join(missing)))
    return env


def _safe_extract(archive, stage):
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            dest = (stage / member.name).resolve()
            if not dest.is_relative_to(stage.resolve()) or member.isdev() or member.isfifo() or member.islnk():
                raise ValueError(T("agent.gguf_runtime.unsafe_own_part_engine_archive"))
            if member.issym() and not (dest.parent / member.linkname).resolve().is_relative_to(stage.resolve()):
                raise ValueError(T("agent.gguf_runtime.unsafe_own_part_engine_archive_link"))
        if hasattr(tarfile, "data_filter"):
            tar.extractall(stage, filter="data")
        else:  # Python 3.10: validated members above.
            tar.extractall(stage)


def _extracted_root(stage):
    named = stage / ARCHIVE_DIR
    if named.is_dir():
        return named
    entries = [p for p in stage.iterdir() if p.name != "release.tar.gz"]
    dirs = [p for p in entries if p.is_dir()]
    if len(dirs) == 1 and not any(p.is_file() for p in entries):
        return dirs[0]
    if (stage / "caravan-shards-version").is_file():
        return stage
    raise ValueError(T("agent.gguf_runtime.own_part_engine_archive_is_missing", name="caravan-shards-version"))


def _install_prebuilt(home, retrieve, pin):
    root = location(home)
    if root.exists() or root.is_symlink():
        raise ValueError(T("agent.gguf_runtime.the_own_part_engine_folder_is_incomplete"))
    root.parent.mkdir(parents=True, exist_ok=True)
    sha = str(pin["sha256"]).strip().lower()
    url = str(pin["url"]).strip()
    print(T("agent.gguf_runtime.preparing_own_part_engine_from_a_prepared"), flush=True)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix="download-") as tmp:
        archive = Path(tmp) / "release.tar.gz"
        retrieve(url, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != sha:
            raise ValueError(T("agent.gguf_runtime.own_part_engine_download_failed_its_safety"))
        stage = Path(tmp) / "unpack"
        stage.mkdir()
        _safe_extract(archive, stage)
        extracted = _extracted_root(stage)
        if not _bin_ok(extracted):
            for name in ("llama-server", "ggml-rpc-server", "caravan-shards-version"):
                path = extracted / "build" / "bin" / name if name != "caravan-shards-version" else extracted / name
                if name == "caravan-shards-version":
                    if not path.is_file() or path.read_text().strip() != MARKER:
                        raise ValueError(T("agent.gguf_runtime.own_part_engine_archive_is_missing", name=name))
                elif not path.is_file():
                    raise ValueError(T("agent.gguf_runtime.own_part_engine_archive_is_missing", name=name))
            raise ValueError(T("agent.gguf_runtime.own_part_engine_archive_is_missing", name="caravan-shards-version"))
        (extracted / "release.sha256").write_text(sha + "\n")
        extracted.rename(root)
    return current(home)


def _build_from_source(home, env):
    base = Path(home or Path.home()) / ".caravan/runtimes/gguf-shards"
    base.mkdir(parents=True, exist_ok=True)
    env = _require_build_tools(env)
    print(T("agent.gguf_runtime.preparing_own_part_gguf_backend_from_source"), flush=True)
    src = base / "source.git"
    dst = base / PIN
    if any(p.is_symlink() for p in (base, src, dst)):
        raise ValueError(T("agent.gguf_runtime.linked_runtime_folder_refused"))
    if not dst.exists():
        if not src.exists():
            subprocess.run(["git", "init", "--bare", str(src)], check=True, env=env, timeout=300)
        subprocess.run(
            ["git", "-C", str(src), "fetch", "--depth=1", "https://github.com/ggml-org/llama.cpp.git", PIN],
            check=True,
            env=env,
            timeout=300,
        )
        script = Path(__file__).resolve().parents[1] / "runtime/gguf-shards/apply.py"
        subprocess.run([sys.executable, str(script), str(src), str(dst)], check=True, env=env, timeout=300)
    marker = dst / "caravan-shards-version"
    if not marker.is_file() or marker.read_text().strip() != MARKER:
        raise ValueError(T("agent.gguf_runtime.incomplete_isolated_runtime_retained_for_inspect"))
    subprocess.run(
        ["cmake", "-S", str(dst), "-B", str(dst / "build"), "-DGGML_RPC=ON", "-DLLAMA_CURL=OFF", "-DLLAMA_BUILD_TESTS=OFF"],
        check=True,
        env=env,
        timeout=300,
    )
    subprocess.run(
        ["cmake", "--build", str(dst / "build"), "-j", "4", "--target", "llama-server", "ggml-rpc-server"],
        check=True,
        env=env,
        timeout=1800,
    )
    return current(home)


def ensure(home=None, retrieve=urllib.request.urlretrieve, pin=None):
    """Install the own-part engine if needed. Prefer a pinned prebuilt."""
    home = Path(home) if home is not None else Path.home()
    try:
        return current(home)
    except FileNotFoundError:
        if os.environ.get("CARAVAN_GGUF_SHARD_BIN"):
            raise
    base = home / ".caravan/runtimes/gguf-shards"
    base.mkdir(parents=True, exist_ok=True)
    lock = base / "build.lock"
    if lock.is_symlink():
        raise ValueError(T("agent.gguf_runtime.linked_runtime_lock_refused"))
    with lock.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            return current(home)
        except FileNotFoundError:
            pass
        pin = pin if pin is not None else release_pin()
        if prebuilt_configured(pin):
            return _install_prebuilt(home, retrieve, pin)
        env = dict(os.environ)
        return _build_from_source(home, env)


def main(home=None, retrieve=urllib.request.urlretrieve, pin=None, out=None):
    """Install-time entry: try to set up the engine, but never fail the install.

    Missing tools, a missing prebuilt, a checksum mismatch or an unsafe
    archive are printed plainly and return 0 so install.sh and
    `caravan update` can finish. Genuine unexpected errors still propagate.
    Doctor reports the engine missing unless current() would succeed.
    """
    out = sys.stdout if out is None else out
    try:
        path = ensure(home=home, retrieve=retrieve, pin=pin)
        print(T("agent.gguf_runtime.own_part_engine_ready"), path, file=out, flush=True)
        return 0
    except (FileNotFoundError, ValueError, OSError) as e:
        print(
            T("agent.gguf_runtime.own_part_engine_not_ready_yet", reason=str(e)),
            file=out,
            flush=True,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
