"""Day 33 power-loss test: boot restore waits for the 2nd Mac in plain words."""
import sys, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "proxy")]
import web_restore as R  # noqa: E402
import web_nodes  # noqa: E402
from service_endpoints import RetryableReadinessError  # noqa: E402

PEER = "paired_20a07ea04739f1d5bb415fba55175503"
NODES = [dict(id="local", role="lead", host="local", label=""),
         dict(id=PEER, role="packer", host="prf-hays-exo02.local", ssh="caravan-20a07ea0", label="")]
BODY = {"model_id": "gguf/Qwen_Qwen3-30B-A3B-Q4_K_M", "engine": "gguf",
        "placement": {"mode": "split", "node_ids": ["local", PEER]},
        "node_ids": ["local", PEER], "counts": [19.0, 15.7], "settings": {}}


def app():
    return NS(configured_nodes=lambda: [dict(n) for n in NODES], nodes=lambda: {"nodes": []},
              _ssh_fn=lambda: None, mgr=NS(snapshot=lambda: {"status": "idle"}))


class RestoreWaitWording(unittest.TestCase):
    def _run(self, stats):
        def gather(node, ssh_fn=None):
            return stats if node["id"] == PEER else {"ram": {"available_gb": 18.0}}
        with mock.patch.object(web_nodes, "gather_node_stats", side_effect=gather), \
                mock.patch.object(web_nodes, "is_local", side_effect=lambda n: n.get("id") == "local"):
            R.validate_placement(app(), {"source": "gguf"}, dict(BODY))

    def test_offline_peer_is_named_the_2nd_mac(self):
        with self.assertRaises(RetryableReadinessError) as cm:
            self._run({"offline": True})
        msg = str(cm.exception)
        self.assertEqual(msg, "The 2nd Mac is not reachable yet")
        self.assertNotIn("paired_", msg)
        self.assertNotIn("press Load", msg)  # restore retries by itself
        wait = cm.exception.waiting_message(2, 4)
        self.assertEqual(wait, "Waiting for your other Macs to start… (attempt 2); "
                               "trying again in 4s: The 2nd Mac is not reachable yet")
        self.assertNotIn("Mini", wait)

    def test_unknown_memory_is_named_the_2nd_mac(self):
        with self.assertRaises(RetryableReadinessError) as cm:
            self._run({"ram": {}})
        self.assertEqual(str(cm.exception), "Free memory on the 2nd Mac is unknown for now; nothing was loaded")
        self.assertEqual(cm.exception.kind, "memory")

    def test_timeout_still_says_press_load(self):
        e = RetryableReadinessError("The 2nd Mac is not reachable yet", kind="mini")
        self.assertIn("Press Load to try again", e.timeout_message(300))

    def test_custom_mac_name_is_kept(self):
        self.assertEqual(R.mac_name({"label": "Studio"}, "x", []), "Studio")
        self.assertEqual(R.mac_name({}, PEER, []), "The other Mac")


class RestoredChipShowsChatMemory(unittest.TestCase):
    """After the Day 33 restore the Settings chip had kv_bits None: the saved
    tune only holds flash attention and prompt batch."""

    def test_launch_cache_type_fills_in(self):
        import web_settings as WS
        a = WS.gguf_active_settings({"flash_attn": "on", "ubatch": 512}, {},
                                    launch={"ctx": 32768, "n_slots": 1, "cache_type": "f16"})
        self.assertEqual(a["kv_bits"], 16)
        a = WS.gguf_active_settings({}, {}, launch={"cache_type": "q8_0"})
        self.assertEqual(a["kv_bits"], 8)

    def test_tune_still_wins(self):
        import web_settings as WS
        a = WS.gguf_active_settings({"cache_type": "q8_0"}, {}, launch={"cache_type": "f16"})
        self.assertEqual(a["kv_bits"], 8)

    def test_worker_records_the_real_cache_type(self):
        src = (ROOT / "proxy" / "web_workers.py").read_text()
        self.assertIn('launch = dict(launch or {}, cache_type=args[args.index("-ctk") + 1])', src)


if __name__ == "__main__":
    unittest.main()
