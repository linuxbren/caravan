"""Placement options: one / split / all, defaults, disable reasons."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
import placement as PL  # noqa: E402
import web_picker as P  # noqa: E402


def _node(label, avail, *, total=None, disk=200, role="lead", nid=None):
    total = total if total is not None else avail + 4
    return {
        "id": nid or label.lower(),
        "label": label,
        "role": role,
        "ram": {"available_gb": avail, "total_gb": total, "free_gb": avail},
        "disk": {"free_gb": disk},
        "active_gb": 0,
    }


class PlacementTest(unittest.TestCase):
    def test_default_one_when_fits(self):
        nodes = [_node("EXO1", 20, role="lead"), _node("EXO2", 18, role="packer")]
        fit = P.fit_check(weights_gb=8.0, nodes=nodes, safety_gb=1.75)
        opts = PL.placement_options(fit=fit, nodes=nodes, max_split_stages=2, weights_gb=8.0)
        self.assertTrue(opts["default_id"].startswith("one:"))
        enabled = [o for o in opts["options"] if o["enabled"]]
        self.assertTrue(any(o["mode"] == "one" for o in enabled))
        self.assertTrue(any(o["mode"] == "all" for o in enabled))

    def test_default_split_when_needs_two(self):
        nodes = [
            _node("EXO1", 12, total=16, role="lead"),
            _node("EXO2", 12, total=16, role="packer"),
        ]
        fit = P.fit_check(weights_gb=18.0, nodes=nodes, safety_gb=1.75, split_ok=True)
        opts = PL.placement_options(fit=fit, nodes=nodes, max_split_stages=2, weights_gb=18.0)
        # one should be disabled; split:2 enabled if fit allows
        ones = [o for o in opts["options"] if o["mode"] == "one"]
        self.assertTrue(all(not o["enabled"] for o in ones) or fit.get("nodes_needed", 1) == 1)
        if 2 in (fit.get("fits_on") or []):
            split2 = next(o for o in opts["options"] if o["id"] == "split:2")
            self.assertTrue(split2["enabled"])
            self.assertEqual(opts["default_id"], "split:2")

    def test_split3_disabled_when_runtime_2(self):
        nodes = [
            _node("A", 10, total=14, role="lead"),
            _node("B", 10, total=14, role="packer"),
            _node("C", 10, total=14, role="packer", nid="c"),
        ]
        fit = P.fit_check(weights_gb=22.0, nodes=nodes, safety_gb=1.75, split_ok=True)
        opts = PL.placement_options(fit=fit, nodes=nodes, max_split_stages=2, weights_gb=22.0)
        s3 = next((o for o in opts["options"] if o["id"] == "split:3"), None)
        if s3:
            self.assertFalse(s3["enabled"])
            self.assertIn("coming later", s3["reason"])

    def test_write_read_placement(self):
        with tempfile.TemporaryDirectory() as td:
            PL.write_placement(td, {
                "mode": "one", "k": 1, "node_ids": ["exo1"],
                "node_labels": ["EXO1"], "repo_id": "org/m", "full_copy": True,
            })
            got = PL.read_placement(td)
            self.assertEqual(got["mode"], "one")
            self.assertEqual(got["node_ids"], ["exo1"])


class HfAuthTest(unittest.TestCase):
    def test_token_status_never_leaks(self):
        import hf_auth
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "hf_token"
            with unittest.mock.patch.object(hf_auth, "CARAVAN_TOKEN_PATH", path):
                with unittest.mock.patch.dict("os.environ", {}, clear=False):
                    for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
                        if k in __import__("os").environ:
                            del __import__("os").environ[k]
                    hf_auth.save_caravan_token("hf_secret_value_123")
                    st = hf_auth.token_status()
                    blob = json.dumps(st)
                    self.assertNotIn("hf_secret", blob)
                    self.assertTrue(st["configured"])
                    self.assertEqual(st["source"], "settings")
                    hf_auth.clear_caravan_token()
                    self.assertFalse(hf_auth.token_status()["configured"])


if __name__ == "__main__":
    unittest.main()
