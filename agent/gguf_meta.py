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
        raise GGUFError("truncated GGUF header")
    return b


def _read_str(f):
    (n,) = struct.unpack("<Q", _read(f, 8))
    if n > 1 << 24:
        raise GGUFError("implausible string length")
    return _read(f, n).decode("utf-8", errors="replace")


def _skip_value(f, vtype):
    if vtype in _SCALARS:
        f.seek(_SCALARS[vtype][1], 1)
    elif vtype == _STRING:
        (n,) = struct.unpack("<Q", _read(f, 8))
        f.seek(n, 1)
    else:
        raise GGUFError(f"unknown value type {vtype}")


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
    raise GGUFError(f"unknown value type {vtype}")


def read_metadata(path) -> dict:
    """{key: value} for every GGUF header key (long arrays -> SkippedArray).
    Raises GGUFError / OSError."""
    with open(Path(path).expanduser(), "rb") as f:
        if _read(f, 4) != b"GGUF":
            raise GGUFError(f"{path}: not a GGUF file")
        (version,) = struct.unpack("<I", _read(f, 4))
        if version < 2:
            raise GGUFError(f"{path}: GGUF v{version} not supported")
        _n_tensors, n_kv = struct.unpack("<QQ", _read(f, 16))
        meta = {"GGUF.version": version}
        for _ in range(n_kv):
            key = _read_str(f)
            (vtype,) = struct.unpack("<I", _read(f, 4))
            meta[key] = _read_value(f, vtype)
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
