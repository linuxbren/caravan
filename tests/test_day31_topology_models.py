"""Day 31 part C: Topology's On disk list agrees with the Settings list.

Brenden saw Topology and Settings disagree. Topology's list walked old GGUF
folders (~/.caravan/gguf, ~/.ollama/models), so none of the GGUF models
Settings lists showed there, and it listed any folder under ~/.exo/models
(for example exo's caches/) as a model. Now both read the same scans, and a
model on disk that Settings can't load says so.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

import gguf_split as G  # noqa: E402
import web_picker as P  # noqa: E402
import web_server as WS  # noqa: E402


def gguf(folder: Path, name: str, size=60_000_000):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    with open(f, "wb") as fh:
        fh.truncate(size)
    return f


class Roots:
    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name)
        self.mlx = base / "mlx-models"
        self.exo = base / "exo-models"
        self.gguf = base / "models"
        for d in (self.mlx, self.exo, self.gguf):
            d.mkdir()
        self.patches = [
            mock.patch.object(P, "MLX_MODEL_ROOTS", [self.mlx, self.exo]),
            mock.patch.object(G, "GGUF_ROOTS", [self.gguf]),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()
        self.td.cleanup()


class OnDiskList(unittest.TestCase):
    def test_gguf_models_from_caravan_folder_are_listed(self):
        with Roots() as r:
            gguf(r.gguf / "bartowski--Llama-GGUF", "Llama-Q4_K_M.gguf")
            ids = [m["id"] for m in P.list_installed()]
        self.assertEqual(ids, ["gguf/Llama-Q4_K_M"])

    def test_topology_and_settings_use_the_same_gguf_ids(self):
        with Roots() as r:
            gguf(r.gguf / "a", "Qwen-Q4.gguf")
            topo = {m["id"] for m in P.list_installed() if m["source"] == "gguf"}
            settings = {g["id"] for g in G.scan_local()}
        self.assertEqual(topo, settings)

    def test_multi_part_gguf_is_one_row_with_full_size(self):
        with Roots() as r:
            for i in (1, 2):
                gguf(r.gguf / "big", f"Big-Q4-0000{i}-of-00002.gguf")
            rows = P.list_installed()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["size_gb"]["lead"], 0.12, places=2)

    def test_gguf_still_downloading_is_not_listed(self):
        with Roots() as r:
            gguf(r.gguf / "m", "M-Q4.gguf")
            dl = r.gguf / "m" / ".cache" / "huggingface" / "download"
            dl.mkdir(parents=True)
            (dl / "M-Q4.gguf.incomplete").write_bytes(b"")
            self.assertEqual(P.list_installed(), [])

    def test_exo_caches_and_empty_folders_are_not_models(self):
        with Roots() as r:
            (r.exo / "caches").mkdir()
            (r.exo / "caches" / "x.safetensors").write_bytes(b"x")
            (r.exo / "org--empty").mkdir()
            (r.mlx / "drafts").mkdir()
            real = r.exo / "mlx-community--Qwen3-30B-A3B-4bit"
            real.mkdir()
            (real / "config.json").write_text("{}")
            ids = [m["id"] for m in P.list_installed()]
        self.assertEqual(ids, ["mlx-community/Qwen3-30B-A3B-4bit"])


class InSettingsFlag(unittest.TestCase):
    def test_complete_mlx_is_in_settings(self):
        e = WS.mark_in_settings({"id": "org/a", "source": "hf-mlx"}, {"org/a"})
        self.assertTrue(e["in_settings"])
        self.assertNotIn("settings_note", e)

    def test_partial_mlx_says_why_it_is_not_in_settings(self):
        e = WS.mark_in_settings({"id": "org/p", "source": "hf-mlx"}, {"org/a"})
        self.assertFalse(e["in_settings"])
        self.assertEqual(e["settings_note"], "Not in Settings: files incomplete")

    def test_gguf_rows_are_in_settings(self):
        e = WS.mark_in_settings({"id": "gguf/x", "source": "gguf"}, set())
        self.assertTrue(e["in_settings"])


class GgufDelete(unittest.TestCase):
    def test_delete_removes_every_part_and_the_folder(self):
        with Roots() as r:
            folder = r.gguf / "bartowski--Big-GGUF"
            for i in (1, 2):
                gguf(folder, f"Big-Q4-0000{i}-of-00002.gguf")
            (folder / "caravan-gguf-source.json").write_text("{}")
            out = P.delete_model("gguf/Big-Q4-00001-of-00002", current_model_id=None)
            self.assertTrue(out["ok"], out)
            self.assertEqual(len(out["removed"]), 2)
            self.assertFalse(folder.exists())
            self.assertTrue(r.gguf.exists())

    def test_delete_keeps_other_models_in_the_folder(self):
        with Roots() as r:
            folder = r.gguf / "two"
            gguf(folder, "A-Q4.gguf")
            gguf(folder, "A-Q8.gguf")
            out = P.delete_model("gguf/A-Q4", current_model_id=None)
            self.assertTrue(out["ok"])
            self.assertEqual(sorted(f.name for f in folder.iterdir()), ["A-Q8.gguf"])

    def test_loaded_gguf_is_refused(self):
        with Roots() as r:
            gguf(r.gguf / "m", "M-Q4.gguf")
            out = P.delete_model("gguf/M-Q4", current_model_id="gguf/M-Q4")
            self.assertFalse(out["ok"])
            self.assertTrue((r.gguf / "m" / "M-Q4.gguf").exists())

    def test_unknown_gguf_is_not_found(self):
        with Roots():
            out = P.delete_model("gguf/nope", current_model_id=None)
        self.assertEqual(out, {"ok": False, "error": "not found on disk"})

    def test_symlinked_gguf_is_refused(self):
        with Roots() as r, tempfile.TemporaryDirectory() as other:
            real = gguf(Path(other), "Live-Q4.gguf")
            (r.gguf / "l").mkdir()
            (r.gguf / "l" / "Live-Q4.gguf").symlink_to(real)
            out = P.delete_model("gguf/Live-Q4", current_model_id=None)
            self.assertFalse(out["ok"])
            self.assertTrue(real.exists())


class Wiring(unittest.TestCase):
    def test_disk_endpoint_marks_rows_from_the_settings_list(self):
        src = (ROOT / "proxy" / "web_server.py").read_text()
        self.assertIn("app.list_loadable_models(invs, with_gguf=False)", src)
        self.assertIn("mark_in_settings(e, listed)", src)

    def test_page_shows_the_settings_note(self):
        html = (ROOT / "proxy" / "web" / "index.html").read_text()
        i = html.index("function diskLocation(m)")
        self.assertIn("m.in_settings === false", html[i:i + 900])
        self.assertNotIn("including incomplete downloads", html)


if __name__ == "__main__":
    unittest.main()
