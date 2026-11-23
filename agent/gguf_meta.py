"""Minimal, stdlib-only GGUF metadata reader (header key/values only --
tensor data is never read). Used by kv_auto.py to estimate KV-cache size
from a model's own architecture numbers instead of hard-coding per model.

GGUF layout (v2/v3, little-endian): magic "GGUF", u32 version,
u64 n_tensors, u64 n_kv, then n_kv x (string key, u32 type, value).
Arrays are read only when short (<= MAX_ARRAY items); longer arrays
(tokenizer vocab, merges...) are skipped by seeking past them, so this
stays fast on multi-GB files.
"""
import struct
from pathlib import Path
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

MAX_ARRAY = 4096

# GGUF value types
_SCALARS = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4),
    5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1), 10: ("<Q", 8), 11: ("<q", 8),
    12: ("<d", 8),
}
_STRING, _ARRAY = 8, 9


class GGUFError(ValueError):
    pass


class SkippedArray(tuple):
    """Stands in for an array longer than MAX_ARRAY: only its length is
    kept (len() works; e.g. the vocab size from tokenizer.ggml.tokens)."""

    def __new__(cls, n):
        obj = super().__new__(cls)
        obj.n = n
        return obj

    def __len__(self):
        return self.n

    def __repr__(self):
        return f"SkippedArray({self.n})"


def _read(f, n):
    b = f.read(n)
    if len(b) != n:
        raise GGUFError(T("agent.gguf_meta.truncated_gguf_header"))
    return b


def _read_str(f):
    (n,) = struct.unpack("<Q", _read(f, 8))
    if n > 1 << 24:
        raise GGUFError(T("agent.gguf_meta.implausible_string_length"))
    return _read(f, n).decode("utf-8", errors="replace")


def _skip_value(f, vtype):
    if vtype in _SCALARS:
        f.seek(_SCALARS[vtype][1], 1)
    elif vtype == _STRING:
        (n,) = struct.unpack("<Q", _read(f, 8))
        f.seek(n, 1)
    else:
        raise GGUFError(T("agent.gguf_meta.unknown_value_type_vtype", vtype=vtype))


def _read_value(f, vtype):
    if vtype in _SCALARS:
        fmt, size = _SCALARS[vtype]
        return struct.unpack(fmt, _read(f, size))[0]
    if vtype == _STRING:
        return _read_str(f)
    if vtype == _ARRAY:
        (etype,) = struct.unpack("<I", _read(f, 4))
        (n,) = struct.unpack("<Q", _read(f, 8))
        if n > MAX_ARRAY:
            if etype in _SCALARS:
                f.seek(_SCALARS[etype][1] * n, 1)
            else:
                for _ in range(n):
                    _skip_value(f, etype)
            return SkippedArray(n)  # too long to be an architecture parameter
        return [_read_value(f, etype) for _ in range(n)]
    raise GGUFError(T("agent.gguf_meta.unknown_value_type_vtype", vtype=vtype))


def read_metadata(path) -> dict:
    """{key: value} for every GGUF header key (long arrays -> SkippedArray).
    Raises GGUFError / OSError."""
    with open(Path(path).expanduser(), "rb") as f:
        return read_metadata_from(f, name=str(path))


def read_metadata_from(f, name: str = "GGUF") -> dict:
    """Same as read_metadata, from an open binary file (or BytesIO holding
    the start of a file). Day 31: placement reads a not-yet-downloaded
    model's header from the first bytes of the download source. A buffer
    that ends inside the header raises GGUFError("truncated GGUF header")."""
    if _read(f, 4) != b"GGUF":
        raise GGUFError(T("agent.gguf_meta.name_not_a_gguf_file", name=name))
    (version,) = struct.unpack("<I", _read(f, 4))
    if version < 2:
        raise GGUFError(T("agent.gguf_meta.name_gguf_v_version_not_supported", name=name, version=version))
    _n_tensors, n_kv = struct.unpack("<QQ", _read(f, 16))
    meta = {"GGUF.version": version}
    for _ in range(n_kv):
        key = _read_str(f)
        (vtype,) = struct.unpack("<I", _read(f, 4))
        meta[key] = _read_value(f, vtype)
        if hasattr(f, "getbuffer") and f.tell() > len(f.getbuffer()):
            raise GGUFError(T("agent.gguf_meta.truncated_gguf_header"))
    return meta


if __name__ == "__main__":
    import json
    import sys
    m = read_metadata(sys.argv[1])
    arch = m.get("general.architecture", "")
    for k, v in m.items():
        if k.startswith(arch + ".") or k.startswith("general.") or k == "GGUF.version":
            print(k, "=", repr(v) if isinstance(v, SkippedArray) else json.dumps(v)[:200])
    print("tokenizer.ggml.tokens =", repr(m.get("tokenizer.ggml.tokens")))
