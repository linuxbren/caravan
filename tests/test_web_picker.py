"""Fit check + catalog helpers for web_picker; node list parsing."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "agent"))
import web_picker as P  # noqa: E402
import web_nodes as N  # noqa: E402


def _node(label, avail, *, total=None, disk=200, offline=False, role="lead",
          active=0, nid=None, error=None):
    total = total if total is not None else avail + 4
    n = {
        "id": nid or label.lower(),
        "label": label,
        "role": role,
        "ram": {"available_gb": avail, "total_gb": total, "free_gb": avail},
        "disk": {"free_gb": disk},
        "active_gb": active,
        "weights_gb": active,
    }
    if offline:
        n["offline"] = True
    if error:
        n["error"] = error
    return n


class FitTest(unittest.TestCase):
    def test_green_on_one(self):
        nodes = [
            _node("EXO1", 20, role="lead"),
            _node("EXO2", 18, role="packer"),
        ]
        f = P.fit_check(weights_gb=8.0, nodes=nodes, safety_gb=1.75)
        self.assertEqual(f["color"], "green")
        self.assertEqual(f["nodes_needed"], 1)
        self.assertIn(1, f["fits_on"])

    def test_yellow_needs_two(self):
        nodes = [
            _node("EXO1", 12, total=16, role="lead"),
            _node("EXO2", 12, total=16, role="packer"),
        ]
        f = P.fit_check(weights_gb=18.0, nodes=nodes, safety_gb=1.75, split_ok=True)
        self.assertIn(f["color"], ("yellow", "red"))
        if f["color"] == "yellow":
            self.assertGreaterEqual(f["nodes_needed"], 2)

    def test_red_too_big(self):
        nodes = [
            _node("EXO1", 4, total=8, disk=10, role="lead"),
            _node("EXO2", 4, total=8, disk=10, role="packer"),
        ]
        f = P.fit_check(weights_gb=40.0, nodes=nodes, safety_gb=1.75)
        self.assertEqual(f["color"], "red")

    def test_cloud_skipped_in_attach(self):
        groups = [{
            "base": "Cloud", "source": "cloud", "likes": 0,
            "quants": [{"repo_id": "ollama-cloud/x", "cloud": True, "weights_gb": None}],
        }]
        out = P.attach_fit(groups, [_node("A", 1, disk=1)])
        self.assertEqual(out[0]["quants"][0]["fit"]["color"], "green")

    def test_one_node_never_suggests_split(self):
        nodes = [_node("ONLY", 10, total=16, role="lead")]
        # Too big for 1 → red, no "fits on 2" language
        f = P.fit_check(weights_gb=30.0, nodes=nodes, safety_gb=1.75, split_ok=True)
        self.assertEqual(f["color"], "red")
        self.assertEqual(f["fits_on"], [])
        self.assertNotIn("Fits on 2", f["reason"])
        self.assertNotIn("×2", f["reason"])
        self.assertEqual(f["online_nodes"], 1)

    def test_one_node_green(self):
        nodes = [_node("ONLY", 30, total=36, role="lead")]
        f = P.fit_check(weights_gb=8.0, nodes=nodes, safety_gb=1.75)
        self.assertEqual(f["color"], "green")
        self.assertEqual(f["fits_on"], [1])
        self.assertIsNone(f["need_gb_split"])

    def test_three_nodes_mixed_ram_fits_on_3(self):
        # Model too big for 1 or 2 of these small Minis, but 3 together OK.
        nodes = [
            _node("A", 10, total=14, role="lead"),
            _node("B", 10, total=14, role="packer"),
            _node("C", 10, total=14, role="packer", nid="c"),
        ]
        f = P.fit_check(weights_gb=22.0, nodes=nodes, safety_gb=1.75, split_ok=True)
        self.assertIn(3, f["fits_on"])
        self.assertNotIn(1, f["fits_on"])
        # Day19: the runtime and download path now support all configured stages.
        self.assertNotIn("coming later", f["reason"])
        self.assertEqual(f["runtime_stages"], 3)

    def test_offline_node_excluded_from_fit(self):
        nodes = [
            _node("EXO1", 20, total=24, role="lead"),
            _node("EXO2", 20, total=24, role="packer", offline=True),
            _node("EXO3", 4, total=8, role="packer", nid="exo3", error="ssh failed"),
        ]
        f = P.fit_check(weights_gb=8.0, nodes=nodes, safety_gb=1.75)
        self.assertEqual(f["online_nodes"], 1)
        self.assertEqual(f["color"], "green")
        # With only EXO1 online, never suggest split
        self.assertEqual(f["fits_on"], [1])

    def test_unequal_capacities_prefer_strongest_for_one(self):
        nodes = [
            _node("SMALL", 8, total=12, role="lead"),
            _node("BIG", 40, total=48, role="packer"),
        ]
        f = P.fit_check(weights_gb=20.0, nodes=nodes, safety_gb=1.75)
        # BIG alone can take it
        self.assertIn(1, f["fits_on"])
        self.assertEqual(f["capacity_labels"][0], "BIG")


class NodesConfigTest(unittest.TestCase):
    def test_default_two_minis(self):
        with mock.patch.object(N, "_raw_web_nodes", return_value={}):
            nodes = N.nodes_from_config({})
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["label"], "EXO1")
        self.assertEqual(nodes[1]["label"], "EXO2")
        self.assertEqual(nodes[0]["role"], "lead")
        self.assertEqual(nodes[1]["role"], "packer")

    def test_one_node_config(self):
        raw = {"only": {"label": "SOLO", "host": "local", "role": "lead"}}
        with mock.patch.object(N, "_raw_web_nodes", return_value=raw):
            nodes = N.nodes_from_config({})
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["label"], "SOLO")

    def test_three_nodes_config(self):
        raw = {
            "a": {"label": "M1", "host": "local", "role": "lead", "order": 0},
            "b": {"label": "M2", "host": "exo2", "ssh": "exo2", "role": "packer", "order": 1},
            "c": {"label": "M3", "host": "exo3", "ssh": "exo3", "role": "packer", "order": 2},
        }
        with mock.patch.object(N, "_raw_web_nodes", return_value=raw):
            nodes = N.nodes_from_config({})
        self.assertEqual([n["label"] for n in nodes], ["M1", "M2", "M3"])

    def test_empty_host_skipped(self):
        raw = {
            "a": {"label": "M1", "host": "local", "role": "lead"},
            "ghost": {"label": "GHOST", "host": "", "role": "packer"},
            "b": {"label": "M2", "host": "exo2", "role": "packer"},
        }
        with mock.patch.object(N, "_raw_web_nodes", return_value=raw):
            nodes = N.nodes_from_config({})
        self.assertEqual([n["label"] for n in nodes], ["M1", "M2"])

    def test_split_stage_nodes_caps_at_max(self):
        nodes = [
            _node("A", 10, role="lead"),
            _node("B", 10, role="packer"),
            _node("C", 10, role="packer", nid="c"),
        ]
        stages = N.split_stage_nodes(nodes, max_stages=2)
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[0]["label"], "A")

    def test_online_nodes_filters(self):
        nodes = [
            _node("A", 10, role="lead"),
            _node("B", 10, role="packer", offline=True),
            _node("C", 10, role="packer", nid="c", error="down"),
        ]
        self.assertEqual([n["label"] for n in N.online_nodes(nodes)], ["A"])

    def test_toml_roundtrip(self):
        # Write a tiny config.toml and parse via nodes_from_config
        toml = """
[web.nodes.exo1]
label = "EXO1"
host = "local"
role = "lead"

[web.nodes.exo2]
label = "EXO2"
host = "exo2"
ssh = "exo2"
role = "packer"
repo = "~/cv3"

[web.nodes.exo3]
label = "EXO3"
host = "exo3"
ssh = "exo3"
role = "packer"
"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.toml"
            p.write_text(toml)
            with mock.patch.object(N.web_settings, "CONFIG_PATH", p):
                nodes = N.nodes_from_config()
        self.assertEqual([n["label"] for n in nodes], ["EXO1", "EXO2", "EXO3"])


class QuantParseTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(P._parse_quant("mlx-community/Qwen3-4bit"), "4bit")
        self.assertEqual(P._bits_of_quant("q4_k_m"), 4.5)
        self.assertIn("chat", P._filters_for("text-generation", []))


if __name__ == "__main__":
    unittest.main()
