"""Day 24 live-review: image-repo fetch, download-only honesty, plain errors."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT))

import mlx_split_fetch as F  # noqa: E402

def _stub_hub(snapshot=None, hf_hub=None):
    """huggingface_hub is not a portable-suite dependency."""
    import types
    hub = sys.modules.get("huggingface_hub")
    if hub is None:
        hub = types.ModuleType("huggingface_hub")
        sys.modules["huggingface_hub"] = hub
    parts = {}
    if snapshot is not None:
        parts["snapshot_download"] = getattr(hub, "snapshot_download", None)
        hub.snapshot_download = snapshot
    if hf_hub is not None:
        parts["hf_hub_download"] = getattr(hub, "hf_hub_download", None)
        hub.hf_hub_download = hf_hub
    return hub, parts


def _restore_hub(hub, parts):
    for k, v in parts.items():
        if v is None and hasattr(hub, k):
            delattr(hub, k)
        elif v is not None:
            setattr(hub, k, v)

import placement as PL  # noqa: E402
import web_nodes as N  # noqa: E402
import web_picker as P  # noqa: E402

HTML = (ROOT / "proxy/web/index.html").read_text()
SERVER = (ROOT / "proxy/web_server.py").read_text()
PICKER_DOCS = (ROOT / "docs/MODEL_PICKER.md").read_text()
DAY = (ROOT / "docs/DAY24.md").read_text()


class WholeRepoFetch(unittest.TestCase):
    def test_missing_config_downloads_nested_tree(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "flux"
            calls = []

            def fake_snap(repo, local_dir=None, allow_patterns=None, token=None, **kw):
                calls.append(allow_patterns)
                d = Path(local_dir)
                d.mkdir(parents=True, exist_ok=True)
                if allow_patterns:
                    return  # no top-level config — the flux layout
                (d / "model_index.json").write_text("{}")
                (d / "transformer").mkdir(exist_ok=True)
                (d / "transformer" / "config.json").write_text("{}")
                (d / "transformer" / "model.safetensors").write_bytes(b"weights")

            def fake_sizes(repo, token=None):
                return {
                    "model_index.json": 12,
                    "transformer/config.json": 40,
                    "transformer/model.safetensors": 1000,
                }

            buf = io.StringIO()
            _stub_hub(snapshot=fake_snap)
            try:
                with patch.object(F, "file_sizes", fake_sizes), \
                     patch.object(F, "write_sizes", lambda *a, **k: None), \
                     patch("sys.stdout", buf):
                    report = F.main([
                        "mlx-community/flux2-klein-4b-4bit", str(dest),
                        "--role", "all", "--no-progress",
                    ])
            finally:
                pass
            self.assertTrue(report["whole_repo"])
            self.assertTrue((dest / "model_index.json").is_file())
            self.assertTrue((dest / "transformer" / "model.safetensors").is_file())
            self.assertFalse((dest / "config.json").is_file())
            # First call looks for the LLM index; second is the whole tree.
            self.assertIn(["config.json", "model.safetensors.index.json"], calls)
            self.assertIn(None, calls)
            self.assertIn("FETCHED", buf.getvalue())


    def _fetch_layout(self, files, repo="org/demo"):
        """Run main() against a fake snapshot that writes ``files`` (relpath -> bytes)."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        dest = Path(td.name) / "model"
        if True:
            calls = []

            def fake_snap(repo_id, local_dir=None, allow_patterns=None, token=None, **kw):
                calls.append(allow_patterns)
                d = Path(local_dir)
                d.mkdir(parents=True, exist_ok=True)
                if allow_patterns:
                    return  # no LLM index at the top
                for rel, data in files.items():
                    path = d / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data if isinstance(data, (bytes, bytearray)) else str(data).encode())

            def fake_sizes(repo_id, token=None):
                return {rel: len(val if isinstance(val, (bytes, bytearray)) else str(val).encode())
                        for rel, val in files.items()}

            _stub_hub(snapshot=fake_snap)
            with patch.object(F, "file_sizes", fake_sizes), \
                 patch.object(F, "write_sizes", lambda *a, **k: None), \
                 patch("sys.stdout", io.StringIO()):
                report = F.main([repo, str(dest), "--role", "all", "--no-progress"])
            return dest, report, calls, files

    def test_tts_style_repo_downloads_whole_tree(self):
        # Kokoro / mlx-audio style: voices and a weight file, no top-level config.json.
        files = {
            "model.safetensors": b"tts-weights",
            "voices/af_alloy.safetensors": b"voice",
            "tokenizer.json": b"{}",
        }
        dest, report, calls, _ = self._fetch_layout(files, repo="mlx-community/kokoro-tts")
        self.assertTrue(report["whole_repo"])
        self.assertTrue((dest / "voices" / "af_alloy.safetensors").is_file())
        self.assertTrue((dest / "model.safetensors").is_file())
        self.assertFalse((dest / "config.json").is_file())
        self.assertIn(None, calls)

    def test_asr_style_repo_downloads_whole_tree(self):
        # Whisper-style: weights and a nested config, no top-level LLM index.
        files = {
            "weights.safetensors": b"asr-weights",
            "whisper/config.json": b"{}",
            "mel_filters.npz": b"mel",
        }
        dest, report, calls, _ = self._fetch_layout(files, repo="mlx-community/whisper-tiny")
        self.assertTrue(report["whole_repo"])
        self.assertTrue((dest / "weights.safetensors").is_file())
        self.assertTrue((dest / "whisper" / "config.json").is_file())
        self.assertFalse((dest / "config.json").is_file())
        self.assertFalse((dest / "model.safetensors.index.json").is_file())
        self.assertIn(None, calls)

    def test_video_style_repo_downloads_whole_tree(self):
        # CogVideo / Wan style: model_index and subfolders, no top-level config.json.
        files = {
            "model_index.json": b'{"_class_name": "CogVideoXPipeline"}',
            "transformer/config.json": b"{}",
            "transformer/diffusion_pytorch_model.safetensors": b"vid",
            "vae/config.json": b"{}",
            "text_encoder/config.json": b"{}",
        }
        dest, report, calls, _ = self._fetch_layout(files, repo="org/cogvideox-2b")
        self.assertTrue(report["whole_repo"])
        self.assertTrue((dest / "model_index.json").is_file())
        self.assertTrue((dest / "transformer" / "diffusion_pytorch_model.safetensors").is_file())
        self.assertTrue((dest / "vae" / "config.json").is_file())
        self.assertFalse((dest / "config.json").is_file())
        self.assertIn(None, calls)

    def test_llm_layout_still_uses_shard_plan(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "llm"
            planned = []

            def fake_snap(repo, local_dir=None, allow_patterns=None, token=None, **kw):
                d = Path(local_dir)
                d.mkdir(parents=True, exist_ok=True)
                if allow_patterns and "config.json" in (allow_patterns or []):
                    (d / "config.json").write_text(json.dumps({"num_hidden_layers": 4}))
                    (d / "model.safetensors.index.json").write_text(json.dumps({
                        "weight_map": {
                            "model.layers.0.w": "model-00001.safetensors",
                            "model.layers.1.w": "model-00001.safetensors",
                            "model.layers.2.w": "model-00002.safetensors",
                            "model.layers.3.w": "model-00002.safetensors",
                            "lm_head.weight": "model-00002.safetensors",
                            "model.embed_tokens.weight": "model-00001.safetensors",
                        }
                    }))

            def fake_sizes(repo, token=None):
                return {"model-00001.safetensors": 10, "model-00002.safetensors": 10}

            def fake_plan(*a, **k):
                planned.append(True)
                return {
                    "split": ((0, 2), (2, 4)), "tied": False,
                    "front": {"model-00001.safetensors"},
                    "head": {"model-00002.safetensors"},
                    "shared": set(), "stages": [
                        {"model-00001.safetensors"}, {"model-00002.safetensors"},
                    ],
                }

            _stub_hub(snapshot=fake_snap)
            with patch.object(F, "file_sizes", fake_sizes), \
                 patch.object(F, "plan_files", fake_plan), \
                 patch.object(F, "_range_fetch_all", lambda *a, **k: None), \
                 patch.object(F, "write_sizes", lambda *a, **k: None), \
                 patch("sys.stdout", io.StringIO()):
                report = F.main([
                    "org/llama", str(dest), "--role", "all", "--no-progress",
                ])
            self.assertTrue(planned)
            self.assertFalse(report.get("whole_repo"))
            self.assertTrue((dest / "config.json").is_file())

    def test_local_download_mlx_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "img"
            msgs = []

            def fake_hub(repo, fname, local_dir=None, token=None, **k):
                raise FileNotFoundError(fname)

            def fake_snap(repo, local_dir=None, token=None, **k):
                d = Path(local_dir)
                d.mkdir(parents=True, exist_ok=True)
                (d / "model_index.json").write_text("{}")

            _stub_hub(snapshot=fake_snap, hf_hub=fake_hub)
            P.local_download_mlx("org/flux", str(dest), None, lambda p, m: msgs.append(m))
            self.assertTrue((dest / "model_index.json").is_file())
            self.assertIn("full snapshot", msgs)


class DownloadOnlyHonesty(unittest.TestCase):
    def test_notices_for_advanced_types(self):
        self.assertIn("image models", P.serve_notice(repo_id="mlx-community/flux2-klein-4b-4bit"))
        self.assertIn("image models", P.serve_notice(["text-to-image"]))
        self.assertIn("video models", P.serve_notice(["text-to-video"]))
        self.assertIn("speech models", P.serve_notice(["text-to-speech"]))
        self.assertIn("speech models", P.serve_notice(["speech-to-text"]))
        self.assertIn("speech models", P.serve_notice(pipeline_tag="automatic-speech-recognition"))
        self.assertIn("speech models", P.serve_notice(pipeline_tag="text-to-speech"))
        self.assertIn("speech models", P.serve_notice(repo_id="mlx-community/whisper-tiny"))
        self.assertIn("speech models", P.serve_notice(repo_id="mlx-community/kokoro-tts"))
        self.assertIn("video models", P.serve_notice(pipeline_tag="text-to-video"))
        self.assertIn("video models", P.serve_notice(pipeline_tag="image-to-video"))
        self.assertIn("video models", P.serve_notice(repo_id="org/cogvideox-2b"))
        self.assertIn("image models", P.serve_notice(["image-to-image"]))
        self.assertIn("embedding", P.serve_notice(pipeline_tag="feature-extraction"))
        self.assertIn("Decision", P.serve_notice(["decision"]))
        self.assertIn("this kind", P.serve_notice(["any-to-any"]))
        self.assertEqual(P.serve_notice(["chat"]), "")
        self.assertEqual(P.serve_notice(["vision"]), "")
        # A chat model that also happens to mention an image word stays loadable.
        self.assertEqual(P.serve_notice(["chat", "text-to-image"]), "")
        self.assertEqual(
            P.load_refusal("Download only, Caravan can't run image models yet"),
            "Caravan can't run image models yet",
        )

    def test_folder_with_model_index_is_download_only(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "model_index.json").write_text('{"_class_name": "FluxPipeline"}')
            self.assertIn("image models", P.serve_notice_for_folder(d))
            llm = d / "llm"
            llm.mkdir()
            (llm / "config.json").write_text(json.dumps({
                "model_type": "llama", "num_hidden_layers": 8, "architectures": ["LlamaForCausalLM"],
            }))
            self.assertEqual(P.serve_notice_for_folder(llm), "")
            video = d / "video"
            video.mkdir()
            (video / "model_index.json").write_text('{"_class_name": "CogVideoXPipeline"}')
            self.assertIn("video models", P.serve_notice_for_folder(video))
            tts = d / "tts"
            tts.mkdir()
            (tts / "voices").mkdir()
            (tts / "voices" / "af.safetensors").write_bytes(b"v")
            (tts / "model.safetensors").write_bytes(b"w")
            self.assertIn("can't run this kind of model yet", P.serve_notice_for_folder(tts))
            asr = d / "asr"
            asr.mkdir()
            (asr / "whisper").mkdir()
            (asr / "whisper" / "config.json").write_text("{}")
            (asr / "weights.safetensors").write_bytes(b"w")
            self.assertIn("can't run this kind of model yet", P.serve_notice_for_folder(asr))

    def test_tooltip_and_page_show_the_notice(self):
        group = {
            "base": "flux2-klein",
            "filters": ["text-to-image"],
            "quants": [{"repo_id": "mlx-community/flux2-klein-4b-4bit",
                        "pipeline_tag": "text-to-image", "filters": ["text-to-image"]}],
            "download_only_note": P.serve_notice(["text-to-image"]),
        }
        tip = P.row_tooltip(group)
        self.assertIn("Download only, Caravan can't run image models yet", tip)
        self.assertIn("download_only_note", HTML)
        self.assertIn("can't run this kind of model yet", HTML)
        self.assertIn("j.download_only", HTML)
        self.assertIn("web_picker.serve_notice", SERVER)
        self.assertIn("load_refusal", SERVER)


class PlainDownloadErrors(unittest.TestCase):
    def test_traceback_and_hostname_are_stripped(self):
        raw = (
            "paired_dcbb9f1b9cd8cab4dcfa61388dffe4ec: Download did not finish. "
            "Press Resume to retry. ^^^^^^^ FileNotFoundError: [Errno 2] No such "
            "file or directory: '/Users/brenden/.caravan/mlx-models/"
            "mlx-community--flux2-klein-4b-4bit/config.json'"
        )
        self.assertEqual(
            N.plain_download_error(raw, log=False),
            "Download stopped. Press Resume to try again.",
        )
        self.assertEqual(
            N.plain_download_error(RuntimeError("cancelled"), log=False),
            "stopped by user",
        )
        self.assertIn(
            "disk space",
            N.plain_download_error(OSError(28, "No space left on device"), log=False),
        )

    def test_job_card_uses_friendly_names_and_plain_error(self):
        job = N.friendly_job({
            "note": "1 Mini · prf-hays-exo02",
            "error": (
                "paired_dcbb9f1b9cd8cab4dcfa61388dffe4ec: Download did not finish. "
                "Press Resume to retry. ^^^^^^^ FileNotFoundError: [Errno 2] "
                "No such file or directory: '/Users/brenden/.caravan/x/config.json'"
            ),
            "runners": [{
                "id": "paired_dcbb9f1b9cd8cab4dcfa61388dffe4ec",
                "label": "prf-hays-exo02",
                "role": "packer",
            }],
            "progress": {},
        }, inventory=[{
            "id": "paired_dcbb9f1b9cd8cab4dcfa61388dffe4ec",
            "label": "prf-hays-exo02",
            "role": "packer",
        }], node_count=2)
        self.assertEqual(job["note"], "1 Mini · 2nd Mac")
        self.assertNotIn("prf-hays", job["note"])
        self.assertNotIn("paired_", job["error"])
        self.assertNotIn("FileNotFound", job["error"])
        self.assertEqual(job["error"], "Download stopped. Press Resume to try again.")
        self.assertIn("function plainDownloadError", HTML)
        self.assertIn("plain_download_error", SERVER)

    def test_placement_labels_are_friendly(self):
        nodes = [
            {"id": "lead", "label": "prf-hays-omarchy", "role": "lead",
             "ram": {"available_gb": 20, "total_gb": 24}, "disk": {"free_gb": 200}},
            {"id": "paired_dcbb9f1b9cd8cab4dcfa61388dffe4ec",
             "label": "prf-hays-exo02", "role": "packer",
             "ram": {"available_gb": 20, "total_gb": 24}, "disk": {"free_gb": 200}},
        ]
        fit = P.fit_check(weights_gb=4.0, nodes=nodes, safety_gb=1.75)
        opts = PL.placement_options(fit=fit, nodes=nodes, max_split_stages=2, weights_gb=4.0)
        blob = json.dumps(opts)
        self.assertNotIn("prf-hays-exo02", blob)
        self.assertNotIn("prf-hays-omarchy", blob)
        ones = [o for o in opts["options"] if o["mode"] == "one"]
        self.assertTrue(ones)
        for o in ones:
            for lab in o.get("node_labels") or []:
                self.assertFalse(N.looks_like_hostname(lab), lab)
            self.assertNotRegex(o.get("label") or "", r"prf-hays|paired_")


class DocsMention(unittest.TestCase):
    def test_picker_docs_cover_download_only_and_plain_errors(self):
        text = " ".join(PICKER_DOCS.split())
        self.assertIn("Download only, Caravan can't run image models yet", text)
        self.assertIn("Download stopped. Press Resume to try again.", text)
        self.assertIn("friendly Mac", text)
        day = " ".join(DAY.split())
        self.assertIn("Download only, Caravan can't run image models yet", day)
        self.assertNotIn("prf-hays", DAY)
        self.assertNotIn("Usually 42 words/s", DAY)


if __name__ == "__main__":
    unittest.main()
