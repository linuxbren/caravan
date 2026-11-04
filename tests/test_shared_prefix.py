import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
import shared_prefix as SP  # noqa: E402


class PrefixKey(unittest.TestCase):
    def test_stable(self):
        t = list(range(1000))
        self.assertEqual(SP.prefix_key(t, 512), SP.prefix_key(t, 512))
        self.assertNotEqual(SP.prefix_key(t, 512), SP.prefix_key(t, 256))


class CacheLookup(unittest.TestCase):
    def test_store_and_hit(self):
        c = SP.SharedPrefixCache(min_tokens=256)
        prompt = list(range(3000))
        key = c.store(prompt, 2048, lead_snaps={"x": 1}, nbytes=100)
        self.assertIsNotNone(key)
        n, ent = c.lookup(prompt + [99, 100])  # same prefix, new tail
        self.assertEqual(n, 2048)
        self.assertEqual(ent.n_tokens, 2048)
        self.assertEqual(c.hits, 1)

    def test_miss_short(self):
        c = SP.SharedPrefixCache(min_tokens=256)
        n, ent = c.lookup(list(range(100)))
        self.assertEqual(n, 0)
        self.assertIsNone(ent)

    def test_mismatch(self):
        c = SP.SharedPrefixCache(min_tokens=256)
        prompt = list(range(3000))
        c.store(prompt, 1024, lead_snaps=None, nbytes=10)
        other = list(range(500, 3500))
        n, ent = c.lookup(other)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
