from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import gguf_rpc_seed as s  # noqa: E402


def fnv(b: bytes) -> int:
    h = 0xcbf29ce484222325
    for x in b:
        h = ((h ^ x) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


class Layers(unittest.TestCase):
    def test_even_two_way(self):
        # 48 layers + output = 49 slots, 1:1 -> lead 0..24, peer 25..48 (padded by 1)
        self.assertEqual(s.device_layers(48, [1, 1], 1), range(24, 49))
        self.assertEqual(s.device_layers(48, [1, 1], 0, pad=0), range(0, 25))

    def test_three_minis_cover_all(self):
        got = set()
        for i in range(3):
            got |= set(s.device_layers(36, [1, 2, 1], i, pad=0))
        self.assertEqual(got, set(range(37)))


@unittest.skipUnless(__import__("shutil").which("cc"), "needs a C compiler")
class Helper(unittest.TestCase):
    def test_hash_matches_ggml_fnv(self):
        import os, subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            data = os.urandom(5000)
            f = Path(d) / "m.gguf"; f.write_bytes(b"x" * 100 + data)
            exe = Path(d) / "seed"
            subprocess.run(["cc", "-O2", "-o", str(exe), str(Path(s.HERE) / "fnv_seed.c")], check=True)
            out = subprocess.run([str(exe), str(f), d], input="100 5000\n",
                                 capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(out[0], "%016x" % fnv(data))
            self.assertEqual(out[1], "new")
            self.assertEqual((Path(d) / out[0]).read_bytes(), data)
            again = subprocess.run([str(exe), str(f), d], input="100 5000\n",
                                   capture_output=True, text=True).stdout.split()
            self.assertEqual(again[1], "have")


if __name__ == "__main__":
    unittest.main()


class SeedCommand(unittest.TestCase):
    def test_command_and_parse(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proxy"))
        import gguf_split as G
        c = G.seed_command("/x/My Model.gguf", 123, [1.0, 2.0], 1, repo="~/cv3")
        self.assertIn("'My Model.gguf'", c)
        self.assertIn("--shares 1.0,2.0 --index 1", c)
        self.assertIn("= 123 ]", c)
        self.assertIn("NO_LOCAL_COPY", c)
        self.assertEqual(G.parse_seed('noise\n{"tensors": 3, "new": 1}\n')["tensors"], 3)
        self.assertIsNone(G.parse_seed("NO_LOCAL_COPY"))
