"""Day 32 ROADMAP #9: GGUF downloads use the same Step 2 placement as MLX."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in ("proxy", "agent", "tools"):
    sys.path.insert(0, str(ROOT / folder))

import gguf_split as G  # noqa: E402
from i18n_check import english_source  # noqa: E402

HTML = english_source(ROOT / "proxy/web/index.html")


def N(i, role, total=24, avail=None, offline=False):
    if avail is None:
        avail = max(0, total - 4)
    return {
        "id": i, "label": i.upper(), "role": role,
        "host": "local" if role == "lead" else i,
        "offline": offline, "error": None,
        "ram": {"total_gb": total, "available_gb": avail, "free_gb": avail},
        "disk": {"free_gb": 200},
        "active_gb": 0,
    }


def pick_src():
    return HTML[HTML.index("    async function pickQuant("):HTML.index("    function placeButtonLabel(")]


def choose_src():
    return HTML[HTML.index("    async function choosePlacement("):HTML.index("    function placementStep(")]


class PageChooser(unittest.TestCase):
    def test_pickquant_has_no_red_only_gate(self):
        src = pick_src()
        self.assertNotIn('fit.color === "red"', src)
        self.assertNotIn("fit.color === 'red'", src)
        self.assertIn("choosePlacement", src)
        self.assertIn("placement_id", src)
        self.assertIn("gguf_file: q.gguf_file", src)

    def test_chooseplacement_shows_every_option(self):
        src = choose_src()
        self.assertNotIn("GGUF keeps automatic placement", src)
        self.assertNotIn("o.id === place.default_id", src)
        self.assertIn("placementStep(place, q, anchor, keep)", src)

    @unittest.skipUnless(__import__("shutil").which("node"), "Node needed")
    def test_gguf_green_yellow_red_all_open_chooser_and_send_placement(self):
        import subprocess
        script = r'''
const assert = require("assert/strict");
const calls = [];
const state = { abort: null, searchSeq: 0, searchTimer: null };
const T = (k, d) => k;
T.plural = (k) => k;
T.ordinal = (n) => String(n);
T.num = (n) => String(n);
const $ = () => ({ textContent: "", hidden: false, scrollIntoView() {}, classList: { remove() {}, add() {} } });
async function api(path, opts) {
  calls.push({ path, body: opts && opts.body ? JSON.parse(opts.body) : null });
  if (path === "/api/picker/placement") {
    return { options: [{ id: "one:local", mode: "one", enabled: true, label: "1 Mini" }], default_id: "one:local" };
  }
  if (path === "/api/picker/download") {
    return { job: { id: "j1" } };
  }
  return {};
}
async function choosePlacement(place, q) {
  calls.push({ path: "choosePlacement", color: (q.fit || {}).color, options: (place.options || []).map(o => o.id) });
  return "one:local";
}
function upsertJob() {}
function showJobs() {}
function jobCardEl() { return null; }
function pollJob() {}
function plainDownloadError(s) { return String(s); }
function loadCloudModel() { throw new Error("cloud"); }
''' + pick_src() + r'''
(async () => {
  for (const color of ["green", "yellow", "red", "gray"]) {
    calls.length = 0;
    const q = { source: "gguf", repo_id: "pub/m", gguf_file: "m-Q4_K_M.gguf",
                weights_gb: 4.2, fit: { color }, filters: [], pipeline_tag: "text-generation" };
    await pickQuant(q, {});
    const chooser = calls.find(c => c.path === "choosePlacement");
    assert.ok(chooser, "chooser missing for " + color);
    assert.equal(chooser.color, color);
    assert.deepEqual(chooser.options, ["one:local"]);
    const dl = calls.find(c => c.path === "/api/picker/download");
    assert.ok(dl, "download missing for " + color);
    assert.equal(dl.body.source, "gguf");
    assert.equal(dl.body.gguf_file, "m-Q4_K_M.gguf");
    assert.equal(dl.body.placement_id, "one:local");
  }
})().catch(e => { console.error(e); process.exit(1); });
'''
        r = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)


class OptionsShape(unittest.TestCase):
    def test_two_minis_offer_one_each_split_and_copy_all(self):
        nodes = [N("a", "lead", 24), N("b", "packer", 24)]
        p = G.placement_options(5, nodes)
        modes = [o["mode"] for o in p["options"]]
        self.assertEqual(modes, ["one", "one", "split", "all"])
        self.assertEqual([o["id"] for o in p["options"] if o["mode"] == "one"], ["one:a", "one:b"])
        self.assertTrue(all(o.get("full_copy") for o in p["options"] if o["mode"] in ("one", "all")))
        self.assertFalse(next(o for o in p["options"] if o["mode"] == "split")["full_copy"])
        self.assertEqual(p["default_id"], "one:a")
        self.assertTrue(all(o["enabled"] for o in p["options"]))

    def test_default_is_smallest_that_fits_any_node_count(self):
        nodes = [N("a", "lead", 24)] + [N(f"p{i}", "packer", 24) for i in range(1, 4)]
        small = G.placement_options(5, nodes)
        self.assertEqual(small["default_id"], "one:a")
        self.assertEqual(len([o for o in small["options"] if o["mode"] == "one"]), 4)
        self.assertTrue(any(o["id"] == "all" and o["enabled"] for o in small["options"]))
        big = G.placement_options(40, nodes)
        self.assertEqual(big["default_id"], "split:a,p1,p2")
        ones = [o for o in big["options"] if o["mode"] == "one"]
        self.assertTrue(all(not o["enabled"] and o.get("reason") for o in ones))
        self.assertFalse(next(o for o in big["options"] if o["id"] == "all")["enabled"])
        self.assertTrue(next(o for o in big["options"] if o["id"] == "all")["reason"])

    def test_unfit_options_keep_a_reason(self):
        p = G.placement_options(1000, [N("a", "lead", 16), N("b", "packer", 16)])
        self.assertIsNone(p["default_id"])
        for o in p["options"]:
            self.assertFalse(o["enabled"])
            self.assertTrue(o.get("reason"), o["id"])


class DownloadHonorsPlacement(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            dict(id="n0", role="lead", label="1st node", host="local"),
            dict(id="n1", role="packer", label="2nd node", host="trusted-peer"),
        ]
        live = [dict(n, ram=dict(available_gb=20, total_gb=24), disk=dict(free_gb=200),
                     offline=False, active_gb=0) for n in self.nodes]
        self.app = SimpleNamespace(
            configured_nodes=lambda: self.nodes,
            nodes=lambda: dict(nodes=live),
            mgr=SimpleNamespace(repo="/repo", python=sys.executable, snapshot=lambda: {}),
            picker_role_totals=lambda *a, **k: {"lead": 2_000_000_000, "packer": 2_000_000_000,
                                                "each": 2_000_000_000, "full": 2_000_000_000},
            picker_measure_node=lambda *a, **k: {"have_bytes": 0},
            _ssh_fn=lambda: lambda *a, **k: SimpleNamespace(returncode=0, stdout="FETCH_STARTED", stderr=""),
            _friendly_job=lambda job: job,
        )

    def handler(self):
        import web_server
        h = object.__new__(web_server.make_handler(self.app))
        h._json = lambda code, out: (code, out)
        return h

    def _download(self, **body):
        import web_picker, gguf_runtime, web_files
        blobs = dict(gguf_files=[dict(rfilename="model.gguf", size=2_000_000_000)])
        with patch.object(web_picker, "_fetch_repo_blobs", return_value=blobs), \
             patch.object(gguf_runtime, "current", return_value=Path("/custom/bin")), \
             patch.object(web_files, "start") as share, \
             patch.object(web_picker, "start_download", return_value={"id": "job-1", "runners": []}) as start:
            status, out = self.handler()._api_picker_download(dict(
                repo_id="test/model", source="gguf", gguf_file="model.gguf", **body))
        return status, out, start, share

    def test_one_mini_on_the_second_mac_is_honored(self):
        status, out, start, share = self._download(placement_id="one:n1")
        self.assertEqual(status, 200, out)
        share.assert_not_called()
        start.assert_called_once()
        kwargs = start.call_args.kwargs
        place = kwargs.get("placement") or (start.call_args[1].get("placement") if start.call_args[1] else None)
        if place is None:
            # positional / kwargs mix
            place = start.call_args.kwargs["placement"]
        self.assertEqual(place["mode"], "one")
        self.assertEqual(place["node_ids"], ["n1"])
        runners = kwargs.get("runners") or start.call_args.kwargs["runners"]
        self.assertEqual([r["id"] for r in runners], ["n1"])

    def test_copy_to_all_downloads_to_every_mini(self):
        status, out, start, share = self._download(placement_id="all")
        self.assertEqual(status, 200, out)
        share.assert_not_called()
        place = start.call_args.kwargs["placement"]
        self.assertEqual(place["mode"], "all")
        self.assertEqual(place["node_ids"], ["n0", "n1"])
        runners = start.call_args.kwargs["runners"]
        self.assertEqual([r["id"] for r in runners], ["n0", "n1"])

    def test_disabled_placement_is_rejected(self):
        # 40 GB will not fit as a one-Mini copy on these 24 GB Minis
        import web_picker
        blobs = dict(gguf_files=[dict(rfilename="model.gguf", size=40_000_000_000)])
        with patch.object(web_picker, "_fetch_repo_blobs", return_value=blobs):
            status, out = self.handler()._api_picker_download(dict(
                repo_id="test/model", source="gguf", gguf_file="model.gguf",
                placement_id="one:n0"))
        self.assertEqual(status, 400)
        self.assertTrue(out.get("error"))


class LoadHonorsPlacement(unittest.TestCase):
    def mgr(self, nodes):
        import web_workers
        from unittest.mock import patch as _patch
        m = web_workers.WorkerManager.__new__(web_workers.WorkerManager)
        m.live_nodes = nodes
        return m, _patch("web_nodes.nodes_from_config", return_value=nodes)

    def test_one_mini_on_a_non_lead_does_not_become_a_split(self):
        nodes = [N("n0", "lead"), N("n1", "packer")]
        m, p = self.mgr(nodes)
        with p:
            got = m._gguf_nodes({"mode": "one", "node_ids": ["n1"]})
        self.assertEqual([n["id"] for n in got], ["n1"])

    def test_split_keeps_only_the_named_minis(self):
        nodes = [N("n0", "lead"), N("n1", "packer"), N("n2", "packer")]
        m, p = self.mgr(nodes)
        with p:
            got = m._gguf_nodes({"mode": "split", "node_ids": ["n0", "n1"]})
        self.assertEqual([n["id"] for n in got], ["n0", "n1"])

    def test_saved_one_mini_is_the_catalog_default(self):
        import web_server
        from placement import write_placement
        nodes = [N("n0", "lead"), N("n1", "packer")]
        app = web_server.App.__new__(web_server.App)
        app.mgr = SimpleNamespace(snapshot=lambda: {})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # A real-looking tree so scan_local will pick it up if we point roots at it.
            model = root / "pub--m"
            model.mkdir()
            gguf = model / "m-Q4_K_M.gguf"
            gguf.write_bytes(b"x" * 60_000_000)
            write_placement(model, {"mode": "one", "k": 1, "node_ids": ["n0"],
                                    "node_labels": ["N0"], "full_copy": True})
            g = {"id": "gguf/m-Q4_K_M", "name": "m-Q4_K_M", "path": str(gguf), "size_gb": 0.06}
            with patch.object(G, "scan_local", return_value=[g]), \
                 patch("web_nodes.is_local", return_value=True), \
                 patch.object(web_server.App, "_scan_remote_gguf", return_value=[]):
                rows = app.gguf_entries(nodes)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["default_placement"], "one:n0")
        self.assertEqual((rows[0].get("placement") or {}).get("mode"), "one")
        self.assertEqual((rows[0].get("placement") or {}).get("node_ids"), ["n0"])


if __name__ == "__main__":
    unittest.main()
