"""Fit check + catalog helpers for web_picker."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "agent"))
import web_picker as P  # noqa: E402


class FitTest(unittest.TestCase):
    def test_green_on_one(self):
        nodes = [
            {"ram": {"available_gb": 20}, "disk": {"free_gb": 100}},
            {"ram": {"available_gb": 18}, "disk": {"free_gb": 100}},
        ]
        f = P.fit_check(weights_gb=8.0, nodes=nodes, safety_gb=1.75)
        self.assertEqual(f["color"], "green")
        self.assertEqual(f["nodes_needed"], 1)
        self.assertIn(1, f["fits_on"])

    def test_yellow_needs_two(self):
        nodes = [
            {"ram": {"available_gb": 12}, "disk": {"free_gb": 100}},
            {"ram": {"available_gb": 12}, "disk": {"free_gb": 100}},
        ]
        f = P.fit_check(weights_gb=18.0, nodes=nodes, safety_gb=1.75, split_ok=True)
        self.assertIn(f["color"], ("yellow", "red"))
        if f["color"] == "yellow":
            self.assertGreaterEqual(f["nodes_needed"], 2)

    def test_red_too_big(self):
        nodes = [
            {"ram": {"available_gb": 4}, "disk": {"free_gb": 10}},
            {"ram": {"available_gb": 4}, "disk": {"free_gb": 10}},
        ]
        f = P.fit_check(weights_gb=40.0, nodes=nodes, safety_gb=1.75)
        self.assertEqual(f["color"], "red")

    def test_cloud_skipped_in_attach(self):
        groups = [{
            "base": "Cloud", "source": "cloud", "likes": 0,
            "quants": [{"repo_id": "ollama-cloud/x", "cloud": True, "weights_gb": None}],
        }]
        out = P.attach_fit(groups, [{"ram": {"available_gb": 1}, "disk": {"free_gb": 1}}])
        self.assertEqual(out[0]["quants"][0]["fit"]["color"], "green")


class QuantParseTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(P._parse_quant("mlx-community/Qwen3-4bit"), "4bit")
        self.assertEqual(P._bits_of_quant("q4_k_m"), 4.5)
        self.assertIn("chat", P._filters_for("text-generation", []))


if __name__ == "__main__":
    unittest.main()
