"""Unit tests for automatic KV-cache type selection (agent/kv_auto.py)
and the GGUF header reader (agent/gguf_meta.py). Synthetic GGUF headers
in temp dirs (padded sparse to the real models' sizes); nothing started.
"""
import importlib
import io
import os
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import gguf_meta  # noqa: E402
import kv_auto  # noqa: E402

MIB = 1024 * 1024


def _s(x):
    b = x.encode()
    return struct.pack("<Q", len(b)) + b


def _val(v):
    if isinstance(v, bool):
        return struct.pack("<I", 7) + struct.pack("<?", v)
    if isinstance(v, int):
        return struct.pack("<I", 4) + struct.pack("<I", v)
    if isinstance(v, float):
        return struct.pack("<I", 6) + struct.pack("<f", v)
    if isinstance(v, str):
        return struct.pack("<I", 8) + _s(v)
    if isinstance(v, tuple):  # ("i32", n): a long int32 array, e.g. a stand-in vocab
        return struct.pack("<IIQ", 9, 5, v[1]) + b"\0" * (4 * v[1])
    if isinstance(v, list):
        if all(isinstance(x, bool) for x in v):
            return struct.pack("<IIQ", 9, 7, len(v)) + b"".join(struct.pack("<?", x) for x in v)
        return struct.pack("<IIQ", 9, 4, len(v)) + b"".join(struct.pack("<I", x) for x in v)
    raise TypeError(v)


def write_gguf(path, kv, size=None):
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv)))
        for k, v in kv.items():
            f.write(_s(k) + _val(v))
        if size:
            f.truncate(size)  # sparse: weights size without the bytes


QWEN = {"general.architecture": "qwen3moe", "qwen3moe.block_count": 48,
        "qwen3moe.embedding_length": 2048, "qwen3moe.attention.head_count": 32,
        "qwen3moe.attention.head_count_kv": 4, "qwen3moe.attention.key_length": 128,
        "qwen3moe.attention.value_length": 128, "tokenizer.ggml.tokens": ("i32", 151936)}
QWEN_SIZE = 17_456_009_792

_GEMMA_SWA = [(il % 6) != 5 for il in range(30)]
GEMMA = {"general.architecture": "gemma4", "gemma4.block_count": 30,
         "gemma4.embedding_length": 2816, "gemma4.attention.head_count": 16,
         "gemma4.attention.head_count_kv": [2 if not s else 8 for s in _GEMMA_SWA],
         "gemma4.attention.key_length": 512, "gemma4.attention.value_length": 512,
         "gemma4.attention.key_length_swa": 256, "gemma4.attention.value_length_swa": 256,
         "gemma4.attention.sliding_window": 1024,
         "gemma4.attention.sliding_window_pattern": _GEMMA_SWA,
         "tokenizer.ggml.tokens": ("i32", 262144)}
GEMMA_SIZE = 14_439_363_584

GPTOSS = {"general.architecture": "gpt-oss", "gpt-oss.block_count": 24,
          "gpt-oss.embedding_length": 2880, "gpt-oss.attention.head_count": 64,
          "gpt-oss.attention.head_count_kv": 8, "gpt-oss.attention.key_length": 64,
          "gpt-oss.attention.value_length": 64, "gpt-oss.attention.sliding_window": 128,
          "tokenizer.ggml.tokens": ("i32", 201088)}
GPTOSS_SIZE = 12_109_565_632

LIMIT = 18186.25  # Metal recommendedMaxWorkingSetSize on EXO1 (19,069.67 MB)


def fixed_limit(explicit=None):
    return (float(explicit), "configured") if explicit else (LIMIT, "test")


class KvAutoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {k: "" for k in (
            "CARAVAN_GPU_WORKING_SET_MIB", "CARAVAN_COMPUTE_RESERVE_MIB",
            "CARAVAN_KV_SAFETY_MARGIN_MIB")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def model(self, name, kv, size):
        p = self.d / f"{name}.gguf"
        write_gguf(p, kv, size)
        return p

    def decide(self, path, *a, **kw):
        kw.setdefault("limit_fn", fixed_limit)
        return kv_auto.decide(path, *a, **kw)

    # --- metadata / layout -------------------------------------------------
    def test_gguf_reader_roundtrip(self):
        m = gguf_meta.read_metadata(self.model("g", GEMMA, None))
        self.assertEqual(m["gemma4.attention.head_count_kv"][5], 2)
        self.assertEqual(m["gemma4.attention.sliding_window_pattern"], _GEMMA_SWA)
        with self.assertRaises(gguf_meta.GGUFError):
            p = self.d / "bad.gguf"
            p.write_bytes(b"NOPE" + b"\0" * 64)
            gguf_meta.read_metadata(p)

    def test_layouts(self):
        q = kv_auto.kv_layout(gguf_meta.read_metadata(self.model("q", QWEN, None)))
        self.assertEqual(q.n_vocab, 151936)  # from the (skipped) long tokens array
        self.assertEqual(len(q.layers), 48)
        self.assertFalse(any(s for _, s in q.layers))
        self.assertEqual(q.layers[0][0], 4 * 256)
        g = kv_auto.kv_layout(gguf_meta.read_metadata(self.model("g2", GEMMA, None)))
        self.assertEqual(sum(s for _, s in g.layers), 25)
        self.assertEqual(g.layers[5], (2 * 1024, False))
        self.assertEqual(g.layers[0], (8 * 512, True))
        no_vocab = {k: v for k, v in GPTOSS.items() if k != "tokenizer.ggml.tokens"}
        self.assertEqual(kv_auto.kv_layout(no_vocab).n_vocab, kv_auto.DEFAULT_N_VOCAB)  # conservative
        o = kv_auto.kv_layout(GPTOSS)
        # pattern hard-coded: even layers SWA
        self.assertEqual([s for _, s in o.layers][:4], [True, False, True, False])

    def test_kv_bytes(self):
        q = kv_auto.kv_layout(QWEN)
        # 48 layers x 1024 elems x 2 B = 96 KiB per token
        self.assertEqual(kv_auto.kv_bytes(q, 1, 18432, 1024, "f16", "f16"), 18432 * 96 * 1024)
        self.assertAlmostEqual(kv_auto.kv_bytes(q, 2, 8192, 1024, "q8_0", "q8_0"),
                               2 * 8192 * 96 * 1024 * 34 / 64)
        g = kv_auto.kv_layout(GEMMA)
        per_slot = 5 * 2048 * 2 * 18432 + 25 * 4096 * 2 * (1024 + 2048)
        self.assertEqual(kv_auto.kv_bytes(g, 2, 18432, 2048, "f16", "f16"), 2 * per_slot)
        full = 30 * 0 + 5 * 2048 * 2 * 18432 + 25 * 4096 * 2 * 18432
        self.assertEqual(kv_auto.kv_bytes(g, 1, 18432, 2048, "f16", "f16", swa_full=True), full)
        # small context: SWA cache never exceeds ctx
        self.assertEqual(kv_auto.kv_bytes(g, 1, 512, 2048, "f16", "f16"), 30 * 0 + (5 * 2048 + 25 * 4096) * 2 * 512)

    # --- decisions for the benchmark configs (calibration points) ---------
    def test_qwen_bench_configs_pick_q8(self):
        p = self.model("qwen", QWEN, QWEN_SIZE)
        for slots, ctx, ub in ((2, 8192, 1024), (1, 18432, 1024), (4, 65536, 512)):
            d = self.decide(p, slots, ctx, ub)
            self.assertEqual((d.cache_type_k, d.cache_type_v), ("q8_0", "q8_0"), (slots, ctx, d.reason))
        # compute reserve tracks the measured Metal compute buffers (-ub 2048):
        # Qwen 1203 MiB, Gemma 2092, GPT-OSS 1616 (Oct 30 verbose runs)
        for kv, size, measured in ((QWEN, QWEN_SIZE, 1203), (GEMMA, GEMMA_SIZE, 2092),
                                   (GPTOSS, GPTOSS_SIZE, 1616)):
            lay = kv_auto.kv_layout(gguf_meta.read_metadata(self.model("m", kv, None)))
            self.assertLess(abs(kv_auto.compute_reserve_mib(lay, 2048) - measured), 50)
        # the known OOM (2 x 12288 q8_0) is flagged
        self.assertIn("WARNING", self.decide(p, 2, 12288, 1024).reason)
        # a short context does fit f16
        self.assertEqual(self.decide(p, 1, 4096, 512).cache_type_k, "f16")

    def test_gemma_and_gptoss_bench_configs_pick_f16(self):
        for name, kv, size in (("gemma", GEMMA, GEMMA_SIZE), ("gptoss", GPTOSS, GPTOSS_SIZE)):
            d = self.decide(self.model(name, kv, size), 2, 18432, 2048)
            self.assertEqual((d.cache_type_k, d.cache_type_v), ("f16", "f16"), (name, d.reason))
            self.assertIn("f16 fits", d.reason)

    def test_production_default_stays_q8(self):
        # 4 x 64K on two minis (RPC) -- today's production shape
        d = self.decide(self.model("qwen", QWEN, QWEN_SIZE), 4, 65536, 512, n_devices=2)
        self.assertEqual(d.cache_type_k, "q8_0")

    # --- overrides / fallbacks --------------------------------------------
    def test_explicit_types_win(self):
        p = self.model("gemma", GEMMA, GEMMA_SIZE)
        self.assertEqual(self.decide(p, 2, 18432, 2048, "q8_0", "q8_0").reason, "explicit")
        d = self.decide(p, 2, 18432, 2048, "q4_0", "auto")
        self.assertEqual((d.cache_type_k, d.cache_type_v), ("q4_0", "f16"))

    def test_unreadable_model_falls_back_to_q8(self):
        d = self.decide(self.d / "missing.gguf", 2, 8192, 512)
        self.assertEqual((d.cache_type_k, d.cache_type_v), ("q8_0", "q8_0"))
        self.assertIn("fallback", d.reason)
        bad = self.d / "bad.gguf"
        bad.write_bytes(b"GGUF" + b"\xff" * 10)
        self.assertEqual(self.decide(bad, 2, 8192, 512).cache_type_k, "q8_0")

    def test_config_and_env_knobs(self):
        p = self.model("gemma", GEMMA, GEMMA_SIZE)
        self.assertEqual(self.decide(p, 2, 18432, 2048, cfg={"gpu_working_set_mib": 15000}).cache_type_k,
                         "q8_0")
        with mock.patch.dict(os.environ, {"CARAVAN_GPU_WORKING_SET_MIB": "15000"}):
            d = self.decide(p, 2, 18432, 2048, cfg={"gpu_working_set_mib": 30000})
            self.assertEqual(d.estimate["gpu_limit_mib"], 15000)  # env beats config
        d = self.decide(p, 2, 18432, 2048, cfg={"compute_reserve_mib": 100, "safety_margin_mib": 0})
        self.assertEqual((d.estimate["compute_reserve_mib"], d.estimate["safety_margin_mib"]), (100, 0))

    def test_limit_precedence(self):
        cache = self.d / "gpu.json"
        calls = []
        q = lambda: calls.append("q") or 18000.0  # noqa: E731
        self.assertEqual(kv_auto.gpu_working_set_mib(12345, cache, q, lambda: None), (12345.0, "configured"))
        self.assertEqual(kv_auto.gpu_working_set_mib(None, cache, q, lambda: None)[0], 18000.0)
        self.assertEqual(kv_auto.gpu_working_set_mib(None, cache, q, lambda: None)[0], 18000.0)
        self.assertEqual(calls, ["q"])  # second call served from the cache file
        cache.unlink()
        self.assertEqual(kv_auto.gpu_working_set_mib(None, cache, lambda: None, lambda: 16000.0),
                         (16000.0, "sysctl iogpu.wired_limit_mb"))
        self.assertEqual(kv_auto.gpu_working_set_mib(None, cache, lambda: None, lambda: None),
                         (kv_auto.DEFAULT_GPU_WORKING_SET_MIB, "default"))

    def test_supervisor_resolves_auto_and_logs(self):
        env = {"CARAVAN_CONFIG": str(self.d / "none.json"), "CARAVAN_GPU_WORKING_SET_MIB": str(LIMIT)}
        for k in ("CARAVAN_N_SLOTS", "CARAVAN_CTX_PER_SLOT", "CARAVAN_CACHE_TYPE_K", "CARAVAN_CACHE_TYPE_V",
                  "CARAVAN_UBATCH_SIZE", "CARAVAN_FLASH_ATTN", "CARAVAN_SWA_FULL"):
            env[k] = ""
        with mock.patch.dict(os.environ, env):
            import config
            import supervisor
            config = importlib.reload(config)
            supervisor = importlib.reload(supervisor)
            p = str(self.model("gemma", GEMMA, GEMMA_SIZE))
            s = config.resolve_llama_settings({"n_slots": 2, "ctx_per_slot": 18432, "ubatch_size": 2048})
            err = io.StringIO()
            with redirect_stderr(err):
                cmd = supervisor.build_head_command(p, [], s)
            self.assertEqual(cmd[cmd.index("-ctk") + 1], "f16")
            self.assertEqual(cmd[cmd.index("-ctv") + 1], "f16")
            self.assertIn("f16 fits", err.getvalue())
            self.assertIn("Estimate: weights", err.getvalue())
            with mock.patch.dict(os.environ, {"CARAVAN_CACHE_TYPE_K": "q8_0", "CARAVAN_CACHE_TYPE_V": "q8_0"}):
                s2 = config.resolve_llama_settings({"n_slots": 2, "ctx_per_slot": 18432, "ubatch_size": 2048})
                cmd = supervisor.build_head_command(p, [], s2)
                self.assertEqual(cmd[cmd.index("-ctk") + 1], "q8_0")
            # flash attention off: never a quantized V
            s3 = config.resolve_llama_settings({"flash_attn": "off", "n_slots": 4, "ctx_per_slot": 65536})
            with redirect_stderr(io.StringIO()):
                cmd = supervisor.build_head_command(p, [], s3)
            self.assertEqual(cmd[cmd.index("-ctv") + 1], "f16")
            s4 = config.resolve_llama_settings({"swa_full": True})
            with redirect_stderr(io.StringIO()):
                self.assertIn("--swa-full", supervisor.build_head_command(p, [], s4))


if __name__ == "__main__":
    unittest.main()
