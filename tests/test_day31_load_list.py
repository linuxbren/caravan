"""Day 31 part B: the Settings load list shows only downloaded models.

Brenden: the Settings list of models to load showed models that were not
downloaded. Rule: a model whose files are not complete on the Mac or Macs
that will run it must not appear. A downloaded model that can't run (too
big, unsupported) may still show with its reason.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

import gguf_split as G  # noqa: E402
import web_catalog as catalog  # noqa: E402
import web_server as WS  # noqa: E402

NODES = [
    {"id": "exo1", "label": "EXO1", "role": "lead",
     "ram": {"available_gb": 20, "total_gb": 24}, "disk": {"free_gb": 200}},
    {"id": "exo2", "label": "EXO2", "role": "packer",
     "ram": {"available_gb": 20, "total_gb": 24}, "disk": {"free_gb": 200}},
]
FULL = {"weights_gb": 4.5, "full_ok": True, "lead_ok": True, "packer_ok": True,
        "kind": "full", "n_layers": 32, "downloaded": True, "has_tokenizer": True}


def rows(lead_models, packer_models=None, **kw):
    return catalog.build_entries_from_inventories(
        node_inventories=[
            {"id": "exo1", "label": "EXO1", "role": "lead", "models": lead_models},
            {"id": "exo2", "label": "EXO2", "role": "packer", "models": packer_models or {}},
        ], nodes=NODES, **kw)


def listed(r):
    return [x["hf"] for x in WS.loadable_only(r)]


class LoadList(unittest.TestCase):
    def test_complete_model_is_listed(self):
        r = rows({"org/full": dict(FULL, path="/m")})
        self.assertTrue(r[0]["files_ready"])
        self.assertEqual(listed(r), ["org/full"])

    def test_partial_download_is_not_listed(self):
        part = {"path": "/p", "weights_gb": 2.0, "full_ok": False, "lead_ok": False,
                "packer_ok": False, "kind": "partial", "downloaded": True,
                "reason": "missing 2 shard(s)"}
        r = rows({"org/partial": part})
        self.assertEqual(len(r), 1)            # the catalog still knows about it
        self.assertFalse(r[0]["files_ready"])
        self.assertEqual(listed(r), [])        # ...but Settings never lists it

    def test_split_with_other_half_deleted_is_not_listed(self):
        lead_half = dict(FULL, path="/l", full_ok=False, packer_ok=False, kind="split-lead",
                         placement={"mode": "split", "node_ids": ["exo1", "exo2"]})
        r = rows({"org/split": lead_half}, {})
        self.assertEqual(listed(r), [])

    def test_split_with_both_halves_is_listed(self):
        place = {"mode": "split", "node_ids": ["exo1", "exo2"]}
        lead_half = dict(FULL, path="/l", full_ok=False, packer_ok=False, kind="split-lead",
                         placement=place)
        pack_half = dict(FULL, path="/p", full_ok=False, lead_ok=False, kind="split-packer",
                         placement=place)
        r = rows({"org/split": lead_half}, {"org/split": pack_half})
        self.assertEqual(listed(r), ["org/split"])

    def test_one_mac_placement_without_its_copy_is_not_listed(self):
        st = dict(FULL, path="/x", full_ok=False, lead_ok=False, kind="partial",
                  placement={"mode": "one", "node_ids": ["exo2"], "node_labels": ["EXO2"]})
        r = rows({}, {"org/one": st})
        self.assertEqual(listed(r), [])

    def test_metadata_only_folder_is_not_listed(self):
        st = {"path": "/s", "downloaded": False, "kind": "partial", "reason": "missing tokenizer"}
        self.assertEqual(listed(rows({"org/starter": st})), [])

    def test_loaded_model_without_files_is_not_listed(self):
        r = rows({}, current_id="gone", current_hf="org/gone")
        self.assertEqual(listed(r), [])

    def test_loaded_model_missed_by_slow_inventory_stays(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(catalog.inv, "scan_local",
                                   return_value={"org/live": {"path": td, "weights_gb": 4.5}}):
                r = rows({}, current_hf="org/live")
        self.assertEqual(listed(r), ["org/live"])

    def test_downloaded_but_too_big_still_shows_with_reason(self):
        big = dict(FULL, path="/b", weights_gb=90.0)
        r = rows({"org/big": big})
        self.assertFalse(r[0]["usable"])
        self.assertTrue(r[0]["files_ready"])
        self.assertEqual(listed(r), ["org/big"])

    def test_static_catalog_never_listed(self):
        self.assertEqual(listed(rows({})), [])


class GgufRows(unittest.TestCase):
    def test_share_record_with_missing_part_is_not_listed(self):
        good = {"id": "gguf-shards/a", "hf": "a", "source": "gguf", "sharded": True, "usable": True}
        bad = {"id": "gguf-shards/b", "hf": "b", "source": "gguf", "sharded": True, "usable": False}
        self.assertEqual(listed([good, bad]), ["a"])

    def test_gguf_part_still_downloading_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "org--m"
            d.mkdir()
            (d / "m-Q4.gguf").write_bytes(b"x" * 60_000_000)
            self.assertEqual(len(G.scan_local([Path(td)])), 1)
            dl = d / ".cache" / "huggingface" / "download"
            dl.mkdir(parents=True)
            (dl / "m-Q4.gguf.incomplete").write_bytes(b"")
            self.assertEqual(G.scan_local([Path(td)]), [])


class Refresh(unittest.TestCase):
    def test_delete_refreshes_the_settings_list(self):
        html = (ROOT / "proxy" / "web" / "index.html").read_text()
        i = html.index('JSON.stringify({ id: m.id, confirm: true })')
        self.assertIn("window.refreshCaravanModels()", html[i:i + 400])

    def test_server_filters_the_load_list(self):
        src = (ROOT / "proxy" / "web_server.py").read_text()
        self.assertIn("return loadable_only(rows + self.gguf_entries(", src)


if __name__ == "__main__":
    unittest.main()
