"""Day 33 (CAR-9): a GGUF split pick splits the download.

Brenden's bug: a GGUF that fits on one Mac, where Step 2 recommended 2 Macs
for the full chat window. He accepted the 2-Mac split, and only the 1st Mac
downloaded: `_api_picker_download` ran the own-part download only `and not
one_ok`, then cut the targets to the 1st Mac. A missing own-part engine or
an unsupported layout fell through to the same whole-file download, silently.

Rule now (Brenden): a split pick downloads only each Mac's own part and the
model is split-only; a one-Mac pick downloads the whole file there and is
not a split; when per-Mac parts can't happen, Step 2 says so before any
download and offers the explicit "over the cable" split or one Mac.
No network, no Macs: everything below is mocked.
"""
import contextlib
import io
import json
import os
import re
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for folder in ("agent", "proxy", "tools"):
    sys.path.insert(0, str(ROOT / folder))

import gguf_split as G  # noqa: E402
import web_picker as P  # noqa: E402
from i18n_check import english_source  # noqa: E402

LANGS = ("en", "es", "ru", "ja", "zh-Hans")
NEW_KEYS = (
    "server.gguf_split.this_mac_downloads_the_whole_file",
    "server.gguf_split.each_mac_downloads_only_its_part",
    "server.gguf_split.every_mac_downloads_the_whole_file",
    "server.gguf_split.the_first_split_download_builds_the",
    "server.gguf_split.this_model_comes_in_several_files",
    "server.gguf_split.own_parts_dont_support_arch",
    "server.gguf_split.splitting_needs_the_own_part_engine",
    "server.gguf_split.split_across_k_macs_over_the",
    "server.gguf_split.only_the_1st_mac_downloads_the",
    "server.gguf_split.you_can_split_it_over_the",
    "server.web_server.cant_split_this_download_yet_macs",
    "server.web_server.this_file_cant_be_split_into",
    "server.web_server.mac_isnt_set_up_here",
    "server.web_server.couldnt_check_mac",
    "server.web_server.mac_needs_tools",
    "server.web_server.whole_file_the_other_macs_get",
    "server.web_server.could_not_delete_it_on_mac",
    "server.web_server.deleted_here_but_not_on_macs",
    "server.web_files.only_its_part_layers_first_last",
    "server.web_gguf_shares.split_only_each_mac_keeps_only",
    "server.web_gguf_shares.an_older_own_part_tree_isnt",
)
DROPPED = (  # the first CAR-9 cut: whole file on every Mac in a split
    "server.gguf_split.each_of_these_k_macs",
    "server.web_server.whole_file_reads_its_part_from",
    "server.web_workers.who_was_picked_to_keep",
)

LIMIT = "18186.25"  # MiB per Mac Chat window Auto plans with (as test_day31_context_fit)
RAM = 25.77
READY = {"ready": True, "missing": []}


def llama_meta(ctx=131072, arch="llama"):
    """Llama 3.1 8B-like header (same as test_day31_context_fit)."""
    return {"general.architecture": arch, arch + ".block_count": 32,
            arch + ".attention.head_count": 32, arch + ".attention.head_count_kv": 8,
            arch + ".embedding_length": 4096, arch + ".context_length": ctx,
            arch + ".vocab_size": 128256}


def node(i, role, ram=RAM):
    return dict(id=["lead", "peer", "third"][i], role=role, label=["My Mac", "Studio", "Mini"][i],
                host="local" if role == "lead" else "peer%d" % i, ssh=None if role == "lead" else "peer%d" % i,
                ram=dict(total_gb=ram, available_gb=ram - 2))


class Handler:
    """The download handler over 2 (or 3) Macs with nothing real behind it."""

    def __init__(self, n=2, meta=None, ssh_reply=READY):
        import web_server
        self.nodes = [node(0, "lead")] + [node(i, "packer") for i in range(1, n)]
        cfg = [{k: v for k, v in x.items() if k != "ram"} for x in self.nodes]
        self.ssh_calls = []

        def ssh(n, cmd, timeout=60):
            self.ssh_calls.append(cmd)
            if ssh_reply is None:
                raise OSError("off")
            return SimpleNamespace(returncode=0, stdout=json.dumps(ssh_reply), stderr="")
        self.app = SimpleNamespace(configured_nodes=lambda: cfg, nodes=lambda: dict(nodes=self.nodes),
                                   mgr=SimpleNamespace(repo=str(ROOT), snapshot=lambda: {}),
                                   _ssh_fn=lambda: ssh)
        self.h = object.__new__(web_server.make_handler(self.app))
        self.h._json = lambda code, out: (code, out)
        self.h._friendly_job = lambda j: j
        self.meta = meta
        self.start = mock.Mock(return_value=dict(id="whole", runners=[]))
        self.plan = dict(safe=True, stages=[dict(id="lead"), dict(id="peer")][:n])
        self.own_start = mock.Mock(return_value=dict(id="own"))
        self.preview = mock.Mock(return_value=self.plan)

    @contextlib.contextmanager
    def patched(self, files, engine=READY):
        with mock.patch.object(P, "_fetch_repo_blobs", return_value=dict(gguf_files=files)), \
                mock.patch.object(P, "fetch_gguf_header", return_value=self.meta), \
                mock.patch.object(P, "start_download", self.start), mock.patch.object(P, "_job_set"), \
                mock.patch.object(G, "engine_status", return_value=engine), \
                mock.patch("web_gguf_shares.preview", self.preview), \
                mock.patch("web_files.start", self.own_start), \
                mock.patch.dict(os.environ, {"CARAVAN_GPU_WORKING_SET_MIB": LIMIT}):
            yield

    def placement(self, weights_gb, fname="a.gguf", engine=READY):
        files = [dict(rfilename=fname, size=int(weights_gb * 1e9))]
        with self.patched(files, engine):
            return self.h._gguf_source_placement(dict(repo_id="test/model", gguf_file=fname), weights_gb, self.nodes)

    def download(self, size, placement_id=None, files=None, engine=READY, **extra):
        files = files or [dict(rfilename="a.gguf", size=size)]
        body = dict(repo_id="test/model", source="gguf", gguf_file=files[0]["rfilename"], **extra)
        if placement_id:
            body["placement_id"] = placement_id
        with self.patched(files, engine):
            return self.h._api_picker_download(body)

    def runners(self):
        return self.start.call_args.kwargs["runners"]


class ContextRecommendedSplit(unittest.TestCase):
    """Brenden's exact case (t1171u)."""

    def test_fits_on_one_mac_recommended_and_accepted_split_downloads_each_part(self):
        h = Handler(meta=llama_meta())
        place = h.placement(16.5)
        one = next(o for o in place["options"] if o["id"] == "one:lead")
        split = next(o for o in place["options"] if o["id"] == "split:lead,peer")
        # The weights fit on one Mac, with a shorter window only...
        self.assertTrue(one["enabled"])
        self.assertFalse(one["full_window"])
        # ...so Step 2 recommends 2 Macs for the full window.
        self.assertTrue(split["full_window"])
        self.assertEqual(place["default_id"], "split:lead,peer")
        self.assertIn("only its own part", split["download_note"])
        self.assertTrue(split["split_only"])
        # He accepts the recommendation.
        code, out = h.download(16_500_000_000, place["default_id"])
        self.assertEqual(code, 200, out)
        h.preview.assert_called_once()
        self.assertEqual(h.preview.call_args.args[1]["node_ids"], ["lead", "peer"])
        h.own_start.assert_called_once_with(h.app, h.plan)
        h.start.assert_not_called()  # never the whole file on the 1st Mac
        self.assertEqual(out["placement"]["storage"], "own-parts")
        self.assertTrue(out["placement"]["split_only"])
        self.assertEqual(out["stages"], 2)

    def test_the_old_one_ok_gate_is_gone(self):
        src = (ROOT / "proxy" / "web_server.py").read_text()
        self.assertNotIn("and not one_ok", src)

    def test_engine_checked_on_every_picked_mac_before_any_byte(self):
        h = Handler(meta=llama_meta())
        code, out = h.download(16_500_000_000, "split:lead,peer")
        self.assertEqual(code, 200, out)
        self.assertEqual(len(h.ssh_calls), 1)
        self.assertIn("caravan-shards-version", h.ssh_calls[0])


class SplitPickRules(unittest.TestCase):
    def test_split_too_big_for_one_mac_downloads_each_part(self):
        h = Handler()
        code, out = h.download(30_000_000_000, "split:lead,peer")
        self.assertEqual(code, 200, out)
        h.own_start.assert_called_once()
        h.start.assert_not_called()

    def test_three_mac_split_downloads_three_parts_not_the_mlx_planner(self):
        h = Handler(n=3)
        with mock.patch("web_files.prepare_new_mlx", side_effect=AssertionError("GGUF is not MLX")):
            code, out = h.download(1_000_000_000, "split:lead,peer,third")
        self.assertEqual(code, 200, out)
        self.assertEqual(h.preview.call_args.args[1]["node_ids"], ["lead", "peer", "third"])

    def test_one_mac_pick_downloads_the_whole_file_there_and_is_not_a_split(self):
        h = Handler()
        code, out = h.download(1_000_000_000, "one:lead")
        self.assertEqual(code, 200, out)
        h.preview.assert_not_called()
        self.assertEqual([r["id"] for r in h.runners()], ["lead"])
        self.assertEqual(h.start.call_args.kwargs["placement"]["mode"], "one")

    def test_one_mac_pick_on_the_other_mac(self):
        h = Handler()
        code, out = h.download(1_000_000_000, "one:peer")
        self.assertEqual(code, 200, out)
        self.assertEqual([r["id"] for r in h.runners()], ["peer"])

    def test_copy_to_all_unchanged(self):
        h = Handler()
        code, out = h.download(1_000_000_000, "all")
        self.assertEqual(code, 200, out)
        self.assertEqual([r["id"] for r in h.runners()], ["lead", "peer"])

    def test_missing_engine_on_the_other_mac_refuses_before_any_download(self):
        h = Handler(ssh_reply={"ready": False, "missing": ["cmake"]})
        code, out = h.download(16_500_000_000, "split:lead,peer")
        self.assertEqual(code, 409)
        self.assertIn("Studio needs cmake", out["error"])
        self.assertIn("Nothing was downloaded", out["error"])
        h.preview.assert_not_called()
        h.own_start.assert_not_called()
        h.start.assert_not_called()

    def test_other_mac_off_refuses_and_names_it(self):
        h = Handler(ssh_reply=None)
        code, out = h.download(16_500_000_000, "split:lead,peer")
        self.assertEqual(code, 409)
        self.assertIn("couldn't check Studio", out["error"])
        h.start.assert_not_called()

    def test_engine_missing_but_tools_present_builds_on_first_download(self):
        h = Handler(ssh_reply={"ready": False, "missing": []})
        code, out = h.download(16_500_000_000, "split:lead,peer", engine={"ready": False, "missing": []})
        self.assertEqual(code, 200, out)
        h.own_start.assert_called_once()

    def test_unsupported_layout_at_download_refuses_plainly(self):
        import gguf_share_download as D
        h = Handler()
        h.preview.side_effect = D.UnsupportedLayout("This model will download as a whole file.")
        code, out = h.download(16_500_000_000, "split:lead,peer")
        self.assertEqual(code, 409)
        self.assertIn("can't be downloaded as per-Mac parts", out["error"])
        h.start.assert_not_called()

    def test_not_enough_memory_refuses(self):
        h = Handler()
        h.plan["safe"] = False
        code, out = h.download(16_500_000_000, "split:lead,peer")
        self.assertEqual(code, 409)
        h.own_start.assert_not_called()


class StepTwoSaysSoFirst(unittest.TestCase):
    def test_every_choice_says_where_the_download_goes(self):
        h = Handler(meta=llama_meta())
        by = {o["id"]: o for o in h.placement(16.5)["options"]}
        self.assertEqual(by["one:lead"]["download_note"],
                         "This Mac downloads the whole file and runs it on its own, not split.")
        self.assertIn("runs only as this split", by["split:lead,peer"]["download_note"])
        self.assertEqual(by["all"]["download_note"], "Every Mac downloads the whole file.")
        self.assertNotIn("split_warning", h.placement(16.5))

    def test_first_build_is_said(self):
        h = Handler(meta=llama_meta())
        place = h.placement(16.5, engine={"ready": False, "missing": []})
        split = next(o for o in place["options"] if o["id"] == "split:lead,peer")
        self.assertIn("will set it up", split["download_note"])
        self.assertTrue(split["enabled"])

    def check_cannot(self, place, why):
        split = next(o for o in place["options"] if o["id"] == "split:lead,peer")
        cable = next(o for o in place["options"] if o["id"] == "split-cable:lead,peer")
        self.assertFalse(split["enabled"])
        self.assertIn(why, split["reason"])
        self.assertTrue(cable["enabled"])
        self.assertEqual(cable["storage"], "cable")
        self.assertIn("over the cable", cable["label"])
        self.assertIn("Not a split download", cable["download_note"])
        self.assertIn(why, place["split_warning"])
        self.assertIn("put it on one Mac", place["split_warning"])
        # The recommended split for the full window moves to the labeled cable split.
        self.assertEqual(place["default_id"], "split-cable:lead,peer")

    def test_unsupported_architecture_is_said_before_download(self):
        h = Handler(meta=llama_meta(arch="gpt-oss"))
        self.check_cannot(h.placement(16.5), "this one is gpt-oss")

    def test_several_files_is_said_before_download(self):
        h = Handler(meta=llama_meta())
        self.check_cannot(h.placement(16.5, fname="a-00001-of-00002.gguf"), "several files")

    def test_no_engine_and_no_tools_is_said_before_download(self):
        h = Handler(meta=llama_meta())
        place = h.placement(16.5, engine={"ready": False, "missing": ["Apple Command Line Tools", "cmake"]})
        self.check_cannot(place, "Apple Command Line Tools")

    def test_cable_split_downloads_on_the_1st_mac_and_says_so(self):
        h = Handler(meta=llama_meta(arch="gpt-oss"))
        code, out = h.download(16_500_000_000, "split-cable:lead,peer")
        self.assertEqual(code, 200, out)
        h.preview.assert_not_called()
        self.assertEqual([r["id"] for r in h.runners()], ["lead"])
        place = h.start.call_args.kwargs["placement"]
        self.assertEqual(place["mode"], "split")
        self.assertEqual(place["node_ids"], ["lead", "peer"])
        self.assertEqual(place["storage"], "cable")
        self.assertFalse(place["split_only"])
        self.assertIn("over the cable", h.runners()[0]["share"])

    def test_greyed_own_part_split_cant_be_forced(self):
        h = Handler(meta=llama_meta(arch="gpt-oss"))
        code, out = h.download(16_500_000_000, "split:lead,peer")
        self.assertEqual(code, 400)
        h.start.assert_not_called()
        h.own_start.assert_not_called()

    def test_multipart_too_big_for_one_mac_defaults_to_cable(self):
        h = Handler()
        files = [dict(rfilename="a-%05d-of-00002.gguf" % i, size=15_000_000_000) for i in (1, 2)]
        code, out = h.download(0, None, files=files)
        self.assertEqual(code, 200, out)
        self.assertEqual(h.start.call_args.kwargs["placement"]["storage"], "cable")

    def test_engine_check_code_runs_and_answers(self):
        st = G.engine_status()
        self.assertIn("ready", st)
        self.assertIsInstance(st["missing"], list)
        self.assertIn(repr(G._engine_pin()), G.engine_check_code())

    def test_page_shows_notes_warning_and_share(self):
        html = english_source(ROOT / "proxy" / "web" / "index.html")
        self.assertIn("o.download_note", html)
        self.assertIn("place.split_warning", html)
        self.assertIn("r.share", html)
        self.assertIn("del.warning", html)


class SplitOnlyAfterDownload(unittest.TestCase):
    def test_job_rows_say_which_part_each_mac_gets(self):
        import web_files
        nodes = [dict(id="lead", role="lead", label="My Mac", host="local"),
                 dict(id="peer", role="packer", label="Studio", host="peer1")]
        app = SimpleNamespace(configured_nodes=lambda: nodes)
        req = dict(format="gguf-shards", repo_id="test/model", filename="a.gguf", revision="r", dest="~/x")
        plan = dict(repo_id="test/model", model_id="gguf-shards/test/model/a.gguf", counts=[1, 1], node_ids=["lead", "peer"],
                    stages=[dict(id="lead", label="My Mac", range=[0, 17], required_bytes=2_100_000_000, downloads=["t"]),
                            dict(id="peer", label="Studio", range=[17, 33], required_bytes=1_900_000_000, downloads=["t"])],
                    file_requests=[dict(req, dest="~/a"), dict(req, dest="~/b")])
        start = mock.Mock(return_value=dict(id="j"))
        with mock.patch.object(web_files, "active", return_value=[]), \
                mock.patch.object(web_files.web_picker, "list_jobs", return_value=[]), \
                mock.patch.object(web_files.web_picker, "start_download", start), \
                mock.patch.object(web_files.web_picker, "_job_set"), \
                mock.patch.object(web_files.web_picker, "get_job", return_value={}):
            web_files.start(app, plan)
        shares = [r["share"] for r in start.call_args.kwargs["runners"]]
        self.assertEqual(shares, ["Only its part: layers 0–16, 2.1 GB", "Only its part: layers 17–32, 1.9 GB"])

    def test_saved_own_part_model_is_split_only_in_settings(self):
        import web_gguf_shares as WGS
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d) / "reg"
            root = Path(d) / "stage-0"
            root.mkdir()
            (root / "manifest.json").write_text("{}")
            rec = dict(model_id="gguf-shards/test/model/a.gguf", roots=[str(root), "~/.caravan/gguf-shares/k/p/stage-1"],
                       node_ids=["lead", "peer"], shares=[1, 1], plan_id="p",
                       source=dict(repo_id="test/model", filename="a.gguf", revision="r", source_sha256="0" * 64,
                                   source_bytes=4_000_000_000))
            reg.mkdir()
            (reg / "x.json").write_text(json.dumps(rec))
            with mock.patch.object(WGS, "REGISTRY", reg):
                rows = WGS.entries([dict(id="lead"), dict(id="peer")])
        e = rows[0]
        self.assertTrue(e["split_only"])
        self.assertEqual([o["mode"] for o in e["placement_options"]], ["split"])
        self.assertEqual(e["note"], "Split-only: each of the 2 Macs keeps only its part")

    def test_older_lead_only_split_still_defaults_and_loads_as_split(self):
        from web_server import gguf_saved_placement_id
        place = G.placement_options(1.0, [node(0, "lead"), node(1, "packer")])
        self.assertEqual(gguf_saved_placement_id(place, dict(mode="split", node_ids=["lead", "peer"]), ["lead"]),
                         "split:lead,peer")
        src = (ROOT / "proxy" / "web_workers.py").read_text()
        self.assertIn('place = read_placement(Path(entry["lead_path"]).expanduser().parent) or {}', src)


class OwnPartDelete(unittest.TestCase):
    def app(self, shell_out):
        nodes = [dict(id="lead", role="lead", label="My Mac", host="local"),
                 dict(id="peer", role="packer", label="Studio", host="peer1")]
        return SimpleNamespace(configured_nodes=lambda: nodes), shell_out

    def rec(self, reg, roots=None):
        import hashlib
        mid = "gguf-shards/test/model/a.gguf"
        rec = dict(model_id=mid, node_ids=["lead", "peer"], shares=[1, 1], plan_id="p",
                   roots=roots or ["~/.caravan/gguf-shares/k/p/stage-0", "~/.caravan/gguf-shares/k/p/stage-1"],
                   source=dict(repo_id="test/model", filename="a.gguf", revision="r", source_sha256="0" * 64,
                               source_bytes=1))
        reg.mkdir(exist_ok=True)
        path = reg / (hashlib.sha256(mid.encode()).hexdigest() + ".json")
        path.write_text(json.dumps(rec))
        return mid, path

    def run_delete(self, replies, roots=None, current=None):
        import web_gguf_shares as WGS
        calls = []

        def shell(app, n, cmd, timeout=60):
            calls.append((n["id"], cmd))
            r = replies[n["id"]]
            if r is None:
                raise OSError("off")
            return SimpleNamespace(returncode=0, stdout=json.dumps(r))
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d) / "reg"
            mid, path = self.rec(reg, roots)
            with mock.patch.object(WGS, "REGISTRY", reg), mock.patch.object(WGS.web_files, "shell", shell):
                app, _ = self.app(None)
                out = WGS.delete_deployment(app, mid, current)
                rows = WGS.disk_rows(app)
            return out, calls, path.exists(), rows

    def test_delete_removes_each_macs_part_and_the_record(self):
        out, calls, kept, _ = self.run_delete({"lead": {"ok": True}, "peer": {"ok": True}})
        self.assertTrue(out["ok"])
        self.assertEqual([c[0] for c in calls], ["lead", "peer"])
        self.assertIn("gguf-shares/k/p/stage-1", calls[1][1])
        self.assertFalse(kept)

    def test_a_mac_that_is_off_keeps_the_record_and_is_named(self):
        out, calls, kept, rows = self.run_delete({"lead": {"ok": True}, "peer": None})
        self.assertTrue(out["ok"])
        self.assertIn("still on Studio", out["warning"])
        self.assertTrue(kept)
        self.assertEqual(rows[0]["placement"]["node_labels"], ["My Mac", "Studio"])

    def test_loaded_model_and_old_trees_are_refused(self):
        out, calls, kept, _ = self.run_delete({}, current="gguf-shards/test/model/a.gguf")
        self.assertFalse(out["ok"])
        self.assertEqual(calls, [])
        out, calls, kept, _ = self.run_delete({}, roots=["~/.caravan/day22-shards/x", "~/.caravan/day22-shards/x"])
        self.assertFalse(out["ok"])
        self.assertIn("older own-part tree", out["error"])
        self.assertTrue(kept)

    def test_part_delete_code_only_removes_under_gguf_shares(self):
        import web_gguf_shares as WGS
        with tempfile.TemporaryDirectory() as home:
            base = Path(home) / ".caravan/gguf-shares"
            part = base / "k" / "p" / "stage-1"
            part.mkdir(parents=True)
            (part / "piece").write_bytes(b"x")
            outside = Path(home) / "keep"
            outside.mkdir()

            def run(arg):
                buf = io.StringIO()
                with mock.patch.dict(os.environ, {"HOME": home}), mock.patch.object(sys, "argv", ["x", arg]), \
                        contextlib.redirect_stdout(buf):
                    exec(WGS._DELETE_PART_CODE, {"__name__": "x"})  # noqa: S102
                return json.loads(buf.getvalue())
            self.assertEqual(run(str(outside)), {"ok": False, "error": "outside"})
            self.assertTrue(outside.exists())
            self.assertEqual(run(str(part)), {"ok": True})
            self.assertFalse((base / "k").exists())
            self.assertTrue(base.exists())
            self.assertEqual(run(str(part)), {"ok": True, "missing": True})

    def test_server_routes_own_part_delete(self):
        import web_server
        app = SimpleNamespace(configured_nodes=lambda: [], mgr=SimpleNamespace(snapshot=lambda: {"model_id": None}))
        h = object.__new__(web_server.make_handler(app))
        h._json = lambda code, out: (code, out)
        with mock.patch("web_gguf_shares.delete_deployment", return_value={"ok": True}) as d:
            code, out = h._api_picker_delete(dict(id="gguf-shards/test/model/a.gguf", confirm=True))
        self.assertEqual(code, 200)
        d.assert_called_once()


@contextlib.contextmanager
def gguf_root():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "models"
        root.mkdir()
        with mock.patch.object(G, "GGUF_ROOTS", [root]):
            yield root


def gguf(folder, name, size=60_000_000):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / name).open("wb") as f:
        f.truncate(size)
    return folder / name


class DeleteEveryCopy(unittest.TestCase):
    def test_delete_local_removes_every_part_and_the_folder(self):
        with gguf_root() as root:
            for i in (1, 2):
                gguf(root / "m", "B-0000%d-of-00002.gguf" % i)
            (root / "m" / "caravan-placement.json").write_text("{}")
            out = G.delete_local("gguf/B-00001-of-00002")
            self.assertTrue(out["ok"])
            self.assertEqual(len(out["removed"]), 2)
            self.assertFalse((root / "m").exists())

    def test_delete_local_missing_and_symlink(self):
        with gguf_root() as root, tempfile.TemporaryDirectory() as other:
            self.assertTrue(G.delete_local("gguf/nope")["missing"])
            real = gguf(Path(other), "L.gguf")
            (root / "l").mkdir()
            (root / "l" / "L.gguf").symlink_to(real)
            self.assertFalse(G.delete_local("gguf/L")["ok"])
            self.assertTrue(real.exists())

    def test_delete_local_skips_a_part_still_downloading(self):
        with gguf_root() as root:
            gguf(root / "m", "C.gguf")
            dl = root / "m" / ".cache" / "huggingface" / "download"
            dl.mkdir(parents=True)
            (dl / "C.gguf.incomplete").write_bytes(b"")
            self.assertTrue(G.delete_local("gguf/C")["missing"])
            self.assertTrue((root / "m" / "C.gguf").exists())

    def test_cli_delete_prints_counts_not_paths(self):
        with gguf_root() as root:
            gguf(root / "m", "D.gguf")
            buf = io.StringIO()
            argv = ["gguf_split.py", "--delete", "gguf/D"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf), \
                    mock.patch.dict("os.environ", {"CARAVAN_GGUF_ROOTS": str(root)}):
                with self.assertRaises(SystemExit) as ex:
                    runpy.run_path(str(ROOT / "proxy" / "gguf_split.py"), run_name="__main__")
            self.assertEqual(ex.exception.code, 0)
            out = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertEqual(out, {"ok": True, "missing": False, "removed": 1, "error": ""})
            self.assertNotIn(str(root), buf.getvalue())

    def test_cli_refuses_a_non_gguf_id(self):
        with mock.patch.object(sys, "argv", ["gguf_split.py", "--delete", "../x"]):
            with self.assertRaises(SystemExit) as ex:
                runpy.run_path(str(ROOT / "proxy" / "gguf_split.py"), run_name="__main__")
        self.assertEqual(ex.exception.code, 2)

    def test_delete_reaches_the_other_macs(self):
        with gguf_root() as root:
            gguf(root / "m", "E.gguf")
            remote = mock.Mock(return_value={"removed": True, "nodes": [dict(node="peer", removed=True)]})
            out = P.delete_model("gguf/E", current_model_id=None, gguf_remote_delete=remote)
        self.assertTrue(out["ok"])
        remote.assert_called_once_with("gguf/E")
        self.assertTrue(out["remote"]["removed"])

    def test_delete_works_when_only_another_mac_has_it(self):
        with gguf_root():
            remote = mock.Mock(return_value={"removed": True, "nodes": []})
            out = P.delete_model("gguf/F", current_model_id=None, gguf_remote_delete=remote)
        self.assertTrue(out["ok"])

    def test_loaded_model_is_refused_before_any_mac_is_touched(self):
        remote = mock.Mock()
        out = P.delete_model("gguf/G", current_model_id="gguf/G", gguf_remote_delete=remote)
        self.assertFalse(out["ok"])
        remote.assert_not_called()

    def server(self, ssh):
        import web_server
        nodes = [dict(id="lead", role="lead", label="My Mac", host="local"),
                 dict(id="peer", role="packer", label="Studio", host="peer1", ssh="peer1")]
        app = SimpleNamespace(configured_nodes=lambda: nodes, _ssh_fn=lambda: ssh,
                              mgr=SimpleNamespace(snapshot=lambda: {}), picker_kill_all=lambda *a, **k: None)
        h = object.__new__(web_server.make_handler(app))
        h._json = lambda code, out: (code, out)
        return h

    def test_server_runs_the_checked_delete_on_each_other_mac(self):
        seen = []

        def ssh(n, cmd, timeout=60):
            seen.append(cmd)
            return SimpleNamespace(returncode=0, stdout='{"ok": true, "missing": false, "removed": 1, "error": ""}')
        with gguf_root() as root:
            gguf(root / "m", "H.gguf")
            code, out = self.server(ssh)._api_picker_delete(dict(id="gguf/H", confirm=True))
        self.assertEqual(code, 200, out)
        self.assertEqual(len(seen), 1)
        self.assertIn("proxy/gguf_split.py --delete gguf/H", seen[0])
        self.assertNotIn("warning", out)

    def test_server_warns_when_a_mac_kept_its_copy(self):
        def ssh(n, cmd, timeout=60):
            return SimpleNamespace(returncode=2, stdout="", stderr="usage")  # older Caravan
        with gguf_root() as root:
            gguf(root / "m", "I.gguf")
            code, out = self.server(ssh)._api_picker_delete(dict(id="gguf/I", confirm=True))
        self.assertEqual(code, 200, out)
        self.assertIn("still on Studio", out["warning"])

    def test_server_says_nothing_when_the_other_mac_never_had_it(self):
        def ssh(n, cmd, timeout=60):
            return SimpleNamespace(returncode=0, stdout='{"ok": false, "missing": true, "removed": 0, "error": "x"}')
        with gguf_root() as root:
            gguf(root / "m", "J.gguf")
            code, out = self.server(ssh)._api_picker_delete(dict(id="gguf/J", confirm=True))
        self.assertEqual(code, 200, out)
        self.assertNotIn("warning", out)


class Strings(unittest.TestCase):
    def test_new_strings_in_all_five_languages_with_the_same_placeholders(self):
        data = {lang: json.loads((ROOT / "locales" / f"{lang}.json").read_text()) for lang in LANGS}
        for key in NEW_KEYS:
            want = set(re.findall(r"\{(\w+)", data["en"][key]))
            for lang in LANGS:
                self.assertIn(key, data[lang], (lang, key))
                self.assertTrue(data[lang][key].strip(), (lang, key))
                self.assertEqual(set(re.findall(r"\{(\w+)", data[lang][key])), want, (lang, key))
        for key in DROPPED:
            for lang in LANGS:
                self.assertNotIn(key, data[lang], (lang, key))

    def test_no_hostnames_in_the_new_strings(self):
        en = json.loads((ROOT / "locales" / "en.json").read_text())
        for key in NEW_KEYS:
            self.assertNotRegex(en[key], r"\bexo\d|\.local\b|\blead\b|packer", key)


if __name__ == "__main__":
    unittest.main()
