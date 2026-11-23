"""A split GGUF is one model, not several independent quantizations."""
import re
from pathlib import PurePosixPath
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

PART = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$")


def members(filename, sizes):
    path = PurePosixPath(filename)
    if path.is_absolute() or ".." in path.parts or not filename.endswith(".gguf"):
        raise ValueError(T("agent.gguf_sets.choose_a_model_file_to_download"))
    match = PART.match(filename)
    names = [filename] if not match else [
        f"{match[1]}-{i:05d}-of-{int(match[3]):05d}.gguf" for i in range(1, int(match[3]) + 1)]
    if not names or any(n not in sizes or int(sizes[n] or 0) <= 0 for n in names):
        raise ValueError(T("agent.gguf_sets.some_parts_of_this_model_are"))
    return names


def groups(files):
    sizes = {f["rfilename"]: int(f.get("size") or 0) for f in files}
    seen = set()
    out = []
    for name in sizes:
        if "mmproj" in name.lower():
            continue
        try:
            parts = members(name, sizes)
        except ValueError:
            continue
        if parts[0] in seen:
            continue
        seen.add(parts[0])
        out.append(dict(rfilename=parts[0], size=sum(sizes[p] for p in parts), parts=parts))
    return out
