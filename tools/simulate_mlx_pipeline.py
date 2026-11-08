#!/usr/bin/env python3
"""No-MLX smoke test: N fake Minis, real framed sockets, separate cache folders.

Development tool, requires the repository's tests/ fake-cache helpers. This is
not an inference benchmark and does not SSH, load weights or start a web server.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "proxy", ROOT / "agent", ROOT / "tests"):
    sys.path.insert(0, str(path))
from test_day19_balance import Pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=3)
    args = parser.parse_args()
    if args.nodes < 2:
        parser.error("--nodes must be at least 2")
    with tempfile.TemporaryDirectory(prefix="caravan-pipeline-sim-") as root:
        pipeline = Pipeline(root, args.nodes)
        try:
            cold, first = pipeline.turn([101, 102, 103])
            warm, second = pipeline.turn([101, 102, 103, 104, 105])
            from test_mlx_worker import KEY
            pipeline.split.save(KEY)
            tokens = [store.sessions[KEY].tokens for store in pipeline.stores]
            for store in pipeline.stores:
                store.sessions.clear()
            restored = pipeline.split.restore(KEY)
            assert cold == 0 and warm == 2
            assert second["path"] == list(range(args.nodes-1))
            assert tokens == [[101, 102, 103, 104]] * args.nodes
            assert restored == "restored"
            print(json.dumps({"simulated_nodes": args.nodes, "transport": "real socketpairs; fake layers",
                              "forward_order": second["path"] + [args.nodes-1],
                              "cold_reused_tokens": cold, "warm_reused_tokens": warm,
                              "stage_local_caches_saved": args.nodes, "restore": restored,
                              "mlx_benchmark": False}, indent=2))
        finally:
            pipeline.close()


if __name__ == "__main__": main()
