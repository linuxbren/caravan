"""Day 31 part A: placement counts the default chat window's memory.

A placement fits when the weights, the chat memory for the model's default
window (its trained window, 8192 if unknown), working memory and the
safety margin fit that placement's budget. The default is the smallest
placement that holds the full window. GGUF uses Chat window Auto's own
math (auto_ctx / ctx_estimate / kv_auto), so placement and the launched
window agree; MLX uses memory_guard with the model's real config.
"""
import functools
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

import gguf_meta  # noqa: E402
import gguf_split as G  # noqa: E402
import kv_auto  # noqa: E402
import memory_guard as MG  # noqa: E402
import placement as PL  # noqa: E402
import web_catalog as catalog  # noqa: E402
import web_picker as P  # noqa: E402

LIMIT = 18186.25  # MiB per Mac, the limit Chat window Auto plans with
RAM = 25.77       # GB the Macs report (any matching pair works)


def llama_meta(ctx=131072):
    """Llama 3.1 8B-like header: 32 layers, 8 KV heads of 128."""
    return {"general.architecture": "llama", "llama.block_count": 32,
            "llama.attention.head_count": 32, "llama.attention.head_count_kv": 8,
            "llama.embedding_length": 4096, "llama.context_length": ctx,
            "llama.vocab_size": 128256}


def gptoss_meta():
    """gpt-oss 20B-like header: 24 layers, every other one sliding (128)."""
    return {"general.architecture": "gpt-oss", "gpt-oss.block_count": 24,
            "gpt-oss.attention.head_count": 64, "gpt-oss.attention.head_count_kv": 8,
            "gpt-oss.embedding_length": 2880, "gpt-oss.attention.key_length": 64,
            "gpt-oss.attention.value_length": 64, "gpt-oss.attention.sliding_window": 128,
            "gpt-oss.context_length": 131072, "gpt-oss.vocab_size": 201088}


def N(i, role, gb=RAM):
    n = {"id": i, "label": i.upper(), "role": role}
    if gb is not None:
        n["ram"] = {"total_gb": gb}
    return n


TWO = [N("exo1", "lead"), N("exo2", "packer")]


def place(weights_gb, nodes=TWO, meta=None, **kw):
    meta = meta or llama_meta()
    return G.placement_options(weights_gb, nodes, model_path="m.gguf",
                               meta_fn=lambda _p: meta, lead_limit=LIMIT, **kw)


def auto_window(weights_gb, n_devices, meta=None, tune=None):
    """The window resolve_launch (Chat window Auto) picks with the same limit."""
    meta = meta or llama_meta()
    decide = functools.partial(kv_auto.decide, limit_fn=lambda _e=None: (LIMIT, "test"),
                               meta_fn=lambda _p: meta,
                               weights_bytes=int(weights_gb * 1e9))
    return G.resolve_launch("m.gguf", tune=tune, n_devices=n_devices, decide=decide,
                            meta_fn=lambda _p: meta)["ctx"]


class GgufPlacement(unittest.TestCase):
    def test_weights_fit_one_mac_but_window_does_not_defaults_to_split(self):
        p = place(16.5)
        one, split = p["options"]
        self.assertTrue(one["enabled"])           # the weights fit on one Mac
        self.assertLess(one["ctx"], 131072)       # ...with a shorter window only
        self.assertFalse(one["full_window"])
        self.assertTrue(split["full_window"])
        self.assertEqual(p["default_id"], "split:exo1,exo2")
        self.assertIn("128K window", p["summary"])
        self.assertIn("Split across 2 Macs for the full 128K window.", p["summary"])
        # The old weights + 1.5 GB rule put this on one Mac.
        self.assertEqual(G.placement_options(16.5, TWO)["default_id"], "one:exo1")

    def test_full_window_on_one_mac_stays_on_one(self):
        p = place(4.92)  # Llama 3.1 8B Q4_K_M
        self.assertEqual(p["default_id"], "one:exo1")
        self.assertEqual(p["summary"], "Fits on 1 Mac with the full 128K window.")
        self.assertNotIn("Split", p["summary"])
        p = place(12.1, meta=gptoss_meta())  # sliding window keeps it small
        self.assertEqual(p["default_id"], "one:exo1")
        self.assertTrue(p["options"][0]["full_window"])

    def test_64k_vs_128k_drives_the_default(self):
        p = place(13.0)
        one, split = p["options"]
        self.assertEqual(one["ctx"], 65536)
        self.assertEqual(split["ctx"], 131072)
        self.assertEqual(p["default_id"], split["id"])
        self.assertEqual(p["summary"], "Fits on 1 Mac with a 64K window. "
                                       "Split across 2 Macs for the full 128K window.")
        self.assertEqual(one["window_note"], "Fits on 1 Mac with a 64K window.")
        self.assertEqual(split["window_note"], "Fits on 2 Macs with the full 128K window.")

    def test_placement_and_chat_window_auto_agree(self):
        for w in (4.92, 9.0, 13.0, 16.5):
            with self.subTest(weights=w):
                one, split = place(w)["options"]
                self.assertEqual(one["ctx"], auto_window(w, 1))
                self.assertEqual(split["ctx"], auto_window(w, 2))

    def test_pinned_16_bit_memory_uses_the_same_pin_as_launch(self):
        p = place(9.0, settings={"kv_bits": "16"})
        tune = {"cache_type": "f16", "pinned_knobs": ["cache_type"]}
        self.assertEqual(p["options"][0]["ctx"], auto_window(9.0, 1, tune=tune))
        self.assertLess(p["options"][0]["ctx"], place(9.0)["options"][0]["ctx"])
        self.assertEqual(p["default_id"], "split:exo1,exo2")

    def test_pinned_chat_window_is_the_target(self):
        p = place(13.0, settings={"chat_window": "32768"})
        self.assertEqual(p["default_id"], "one:exo1")
        self.assertEqual(p["summary"], "Fits on 1 Mac with the full 32K window.")

    def test_model_too_big_even_short_window_behaves_as_today(self):
        p = place(40.0)
        self.assertEqual(p["default_id"], None)
        self.assertTrue(all(not o["enabled"] for o in p["options"]))
        self.assertIn("shortest chat window", p["options"][0]["reason"])
        p = place(30.0)  # only a split can run it, with a shorter window
        self.assertEqual(p["default_id"], "split:exo1,exo2")
        self.assertFalse(p["options"][0]["enabled"])
        self.assertEqual(p["summary"], "Split across 2 Macs with a 64K window.")

    def test_trained_window_unknown_falls_back_to_8192(self):
        meta = llama_meta()
        del meta["llama.context_length"]
        p = place(13.0, meta=meta)
        self.assertEqual(p["options"][0]["target_ctx"], 8192)
        self.assertEqual(p["default_id"], "one:exo1")

    def test_unreadable_header_uses_old_rule(self):
        p = G.placement_options(5, TWO, model_path="m.gguf",
                                meta_fn=mock.Mock(side_effect=OSError("gone")),
                                lead_limit=LIMIT)
        self.assertEqual(p["default_id"], "one:exo1")
        self.assertNotIn("ctx", p["options"][0])

    def test_multi_part_weights_are_summed(self):
        with tempfile.TemporaryDirectory() as td:
            for i, size in ((1, 100), (2, 250), (3, 50)):
                (Path(td) / f"m-0000{i}-of-00003.gguf").write_bytes(b"x" * size)
            first = Path(td) / "m-00001-of-00003.gguf"
            self.assertEqual(kv_auto.model_weights_bytes(first), 400)
            one = Path(td) / "solo.gguf"
            one.write_bytes(b"y" * 7)
            self.assertEqual(kv_auto.model_weights_bytes(one), 7)


class UnknownCapacity(unittest.TestCase):
    def test_unknown_ram_fails_closed_with_window_math(self):
        p = place(5.0, nodes=[N("exo1", "lead", None), N("exo2", "packer")])
        self.assertEqual(p["default_id"], None)
        self.assertTrue(all(not o["enabled"] for o in p["options"]))
        self.assertIn("memory", p["options"][0]["reason"])

    def test_unknown_ram_fails_closed_old_rule(self):
        p = G.placement_options(5, [N("exo1", "lead", None)])
        self.assertFalse(p["options"][0]["enabled"])
        self.assertIsNone(p["default_id"])

    def test_unknown_peer_blocks_only_the_split(self):
        p = place(4.92, nodes=[N("exo1", "lead"), N("exo2", "packer", None)])
        self.assertEqual(p["default_id"], "one:exo1")
        self.assertFalse(p["options"][1]["enabled"])

    def test_mlx_unknown_capacity_is_red(self):
        f = P.fit_check(weights_gb=4.5, nodes=[], cfg=LLAMA8)
        self.assertEqual(f["color"], "red")


LLAMA8 = {"num_hidden_layers": 32, "num_attention_heads": 32, "num_key_value_heads": 8,
          "hidden_size": 4096, "max_position_embeddings": 131072}
LLAMA3 = {"num_hidden_layers": 28, "num_attention_heads": 24, "num_key_value_heads": 8,
          "hidden_size": 3072, "head_dim": 128, "max_position_embeddings": 131072}
QWEN35 = {"model_type": "qwen3_5", "text_config": {
    "num_hidden_layers": 32, "num_attention_heads": 16, "num_key_value_heads": 4,
    "head_dim": 256, "hidden_size": 4096, "max_position_embeddings": 262144}}


def mnode(i, role, avail=20, total=RAM):
    return {"id": i, "label": i.upper(), "role": role, "active_gb": 0,
            "ram": {"total_gb": total, "available_gb": avail}, "disk": {"free_gb": 300}}


MTWO = [mnode("exo1", "lead"), mnode("exo2", "packer")]


class MlxFit(unittest.TestCase):
    def test_real_config_uses_trained_window_not_8k_or_8_percent(self):
        f = P.fit_check(weights_gb=4.5, nodes=MTWO, cfg=LLAMA8)
        self.assertEqual(f["target_ctx"], 131072)
        self.assertEqual(f["kv_source"], "config")
        self.assertAlmostEqual(f["kv_gb_full"], MG.estimate_kv_gb(LLAMA8, 131072, 32), places=2)
        self.assertNotAlmostEqual(f["kv_gb_full"], 4.5 * 0.08, places=1)
        self.assertEqual(f["window_ctx"], {"1": 65536, "2": 131072})
        self.assertEqual(f["recommended_nodes"], 2)
        self.assertEqual(f["nodes_needed"], 1)  # it can still run on one Mac
        self.assertEqual(f["reason"], "Fits on 1 Mac with a 64K window. "
                                      "Split across 2 Macs for the full 128K window.")

    def test_small_model_full_window_on_one_mac(self):
        f = P.fit_check(weights_gb=1.8, nodes=MTWO, cfg=LLAMA3)
        self.assertEqual(f["recommended_nodes"], 1)
        self.assertEqual(f["color"], "green")
        self.assertEqual(f["reason"], "Fits on 1 Mac with the full 128K window.")

    def test_one_mac_only_never_talks_split(self):
        f = P.fit_check(weights_gb=4.5, nodes=MTWO[:1], cfg=LLAMA8)
        self.assertEqual(f["recommended_nodes"], 1)
        self.assertEqual(f["reason"], "Fits on 1 Mac with a 64K window.")

    def test_no_config_keeps_old_estimate(self):
        f = P.fit_check(weights_gb=4.5, nodes=MTWO)
        self.assertEqual(f["target_ctx"], 8192)
        self.assertEqual(f["kv_source"], "estimate")
        self.assertTrue(f["reason"].startswith("Fits on 1 Mini"))

    def test_nested_text_config_window_and_layers(self):
        self.assertEqual(P.trained_ctx(QWEN35), 262144)
        f = P.fit_check(weights_gb=5.0, nodes=MTWO, cfg=QWEN35)
        self.assertEqual(f["target_ctx"], 262144)
        self.assertAlmostEqual(f["kv_gb_full"], MG.estimate_kv_gb(QWEN35, 262144, 32), places=2)

    def test_day20_nested_qwen35_guard_still_holds(self):
        inner = QWEN35["text_config"]
        self.assertEqual(MG.model_layer_count(QWEN35), 32)
        self.assertEqual(MG.bytes_per_token_for_layers(QWEN35, 22),
                         MG.bytes_per_token_for_layers(inner, 22))

    def test_placement_default_follows_recommendation(self):
        f = P.fit_check(weights_gb=4.5, nodes=MTWO, cfg=LLAMA8)
        o = PL.placement_options(fit=f, nodes=MTWO, max_split_stages=2, weights_gb=4.5)
        self.assertEqual(o["default_id"], "split:2")
        self.assertEqual(o["summary"], f["reason"])
        split = next(x for x in o["options"] if x["id"] == "split:2")
        self.assertEqual(split["window_note"], "Fits on 2 Macs with the full 128K window.")
        ones = [x for x in o["options"] if x["mode"] == "one"]
        self.assertTrue(all(x["enabled"] for x in ones))  # still offered
        f = P.fit_check(weights_gb=1.8, nodes=MTWO, cfg=LLAMA3)
        o = PL.placement_options(fit=f, nodes=MTWO, max_split_stages=2, weights_gb=1.8)
        self.assertTrue(o["default_id"].startswith("one:"))

    def test_split_beyond_runtime_is_not_recommended(self):
        f = P.fit_check(weights_gb=4.5, nodes=MTWO, cfg=LLAMA8, max_split_stages=1)
        self.assertEqual(f["recommended_nodes"], 1)


class Paths(unittest.TestCase):
    def test_fetch_config_reads_and_caches(self):
        calls = []

        def opener(req, timeout=None):
            calls.append(req.full_url)
            return io.BytesIO(json.dumps(LLAMA8).encode())
        P._cache.clear()
        self.assertEqual(P.fetch_config("org/m", opener=opener)["num_hidden_layers"], 32)
        self.assertEqual(P.fetch_config("org/m", opener=opener)["num_hidden_layers"], 32)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/org/m/resolve/main/config.json"))
        P._cache.clear()

    def test_fetch_gguf_header_reads_only_the_start_and_retries_bigger(self):
        blob = _gguf_bytes(llama_meta(), pad_tokens=3000)
        seen = []

        def opener(req, timeout=None):
            rng = req.get_header("Range")
            seen.append(rng)
            end = int(rng.split("-")[1])
            return io.BytesIO(blob[:end + 1])
        P._cache.clear()
        with mock.patch.object(P, "GGUF_HEADER_READS", (64, 1 << 20)):
            meta = P.fetch_gguf_header("org/m", "m-Q4_K_M.gguf", opener=opener)
        self.assertEqual(meta["llama.context_length"], 131072)
        self.assertEqual(seen, ["bytes=0-63", f"bytes=0-{(1 << 20) - 1}"])
        self.assertIsNone(P.fetch_gguf_header("org/m", "../x.gguf", opener=opener))
        P._cache.clear()

    def test_catalog_passes_the_real_config(self):
        rid = "mlx-community/Llama-3.1-8B-Instruct-4bit"
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.json").write_text(json.dumps(LLAMA8))
            st = {"path": td, "weights_gb": 4.5, "full_ok": True, "lead_ok": True,
                  "packer_ok": False, "kind": "full", "n_layers": 32}
            seen = {}
            real = P.fit_check

            def spy(**kw):
                seen.update(kw)
                return real(**kw)
            with mock.patch.object(P, "fit_check", side_effect=spy):
                rows = catalog.build_entries_from_inventories(
                    node_inventories=[
                        {"id": "exo1", "label": "EXO1", "role": "lead", "models": {rid: st}},
                        {"id": "exo2", "label": "EXO2", "role": "packer", "models": {}},
                    ],
                    nodes=MTWO)
        self.assertEqual(seen["cfg"]["max_position_embeddings"], 131072)
        # A one-Mac copy stays loadable even though a split is recommended.
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["usable"], rows[0].get("disabled_reason"))

    def test_server_paths_use_real_config_and_header(self):
        src = (ROOT / "proxy" / "web_server.py").read_text()
        self.assertIn("cfg=self._picker_cfg(body)", src)
        self.assertIn("self._picker_cfg(dict(body, repo_id=repo))", src)
        self.assertIn("web_picker.fetch_gguf_header(repo, fname)", src)
        self.assertIn("model_path=g[\"path\"]", src)
        self.assertNotIn("ctx_tokens=int(body.get(\"ctx_tokens\") or web_picker.DEFAULT_CTX)", src)
        # A split picked only for a longer window keeps the whole file on the lead.
        self.assertIn("and not one_ok", src)

    def test_page_shows_window_and_sends_gguf_file(self):
        html = (ROOT / "proxy" / "web" / "index.html").read_text()
        self.assertIn("o.window_note", html)
        self.assertIn("place.summary", html)
        self.assertIn("gguf_file: q.gguf_file})", html)
        self.assertIn('id="btnPlaceAddMac"', html)  # Add a Mac stays where it was


class BalanceAndShares(unittest.TestCase):
    def test_split_budget_matches_tensor_split_shares(self):
        nodes = [N("exo1", "lead", 25.77), N("exo2", "packer", 51.54)]
        shares = G.tensor_split(nodes)
        budgets = [G.node_budget_mib(n, nodes[0], LIMIT) for n in nodes]
        self.assertAlmostEqual(budgets[1] / budgets[0], shares[1] / shares[0], places=1)
        self.assertAlmostEqual(budgets[0], LIMIT)

    def test_matching_macs_plan_like_auto_across_devices(self):
        self.assertAlmostEqual(sum(G.node_budget_mib(n, TWO[0], LIMIT) for n in TWO), 2 * LIMIT)

    def test_without_auto_limit_budget_is_75_percent_of_ram(self):
        b = G.node_budget_mib(N("a", "lead", 24.0))
        self.assertAlmostEqual(b * G.MIB / 1e9, 18.0)

    def test_split_option_order_is_lead_first(self):
        p = place(16.5, nodes=[N("exo2", "packer"), N("exo1", "lead")])
        self.assertEqual(p["options"][1]["node_ids"], ["exo1", "exo2"])


def _gguf_bytes(meta, pad_tokens=0):
    """A minimal GGUF v3 header with `meta` (+ a long string array)."""
    out = io.BytesIO()
    items = list(meta.items())
    if pad_tokens:
        items.append(("tokenizer.ggml.tokens", ["tok%05d" % i for i in range(pad_tokens)]))
    out.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, len(items)))

    def s(x):
        b = x.encode()
        out.write(struct.pack("<Q", len(b)) + b)
    for k, v in items:
        s(k)
        if isinstance(v, str):
            out.write(struct.pack("<I", 8)); s(v)
        elif isinstance(v, list):
            out.write(struct.pack("<I", 9) + struct.pack("<I", 8) + struct.pack("<Q", len(v)))
            for x in v:
                s(x)
        else:
            out.write(struct.pack("<I", 4) + struct.pack("<I", int(v)))
    return out.getvalue()


if __name__ == "__main__":
    unittest.main()
