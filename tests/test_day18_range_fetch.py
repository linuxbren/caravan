from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import range_fetch  # noqa: E402

DATA = bytes(range(256)) * 40


class _Resp(io.BytesIO):
    def __init__(self, b, status):
        super().__init__(b); self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def opener(honor=True, log=None):
    def op(req, timeout=None):
        rng = req.get_header("Range")
        if log is not None:
            log.append(rng)
        if rng and honor:
            n = int(rng.split("=")[1].rstrip("-"))
            return _Resp(DATA[n:], 206)
        return _Resp(DATA, 200)
    return op


class RangeFetch(unittest.TestCase):
    def test_resumes_from_partial(self):
        with tempfile.TemporaryDirectory() as d:
            p = range_fetch.partial_path(Path(d), "m.gguf")
            p.parent.mkdir(parents=True); p.write_bytes(DATA[:3000])
            log = []
            r = range_fetch.fetch("a/b", "m.gguf", d, len(DATA), opener=opener(log=log))
            self.assertEqual(log, ["bytes=3000-"])
            self.assertEqual(r["resumed_from"], 3000)
            self.assertEqual(r["fetched"], len(DATA) - 3000)
            self.assertEqual((Path(d) / "m.gguf").read_bytes(), DATA)
            self.assertFalse(p.exists())

    def test_server_ignores_range_restarts_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = range_fetch.partial_path(Path(d), "x.safetensors")
            p.parent.mkdir(parents=True); p.write_bytes(DATA[:100])
            range_fetch.fetch("a/b", "x.safetensors", d, len(DATA), opener=opener(honor=False))
            self.assertEqual((Path(d) / "x.safetensors").read_bytes(), DATA)

    def test_complete_file_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "y").write_bytes(DATA)
            r = range_fetch.fetch("a/b", "y", d, len(DATA), opener=opener(log=[]))
            self.assertTrue(r["skipped"])

    def test_short_read_keeps_partial(self):
        def op(req, timeout=None):
            return _Resp(DATA[:500], 200)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                range_fetch.fetch("a/b", "z", d, len(DATA), opener=op)
            self.assertEqual(range_fetch.partial_path(Path(d), "z").stat().st_size, 500)


if __name__ == "__main__":
    unittest.main()
