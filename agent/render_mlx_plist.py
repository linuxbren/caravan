#!/usr/bin/env python3
"""Renders launchd/com.caravan.mlx-server.plist from the same builder the
agent uses (mlx_backend.build_mlx_command). Writes the file only; loading
it (launchctl bootstrap gui/$UID ...) is a deliberate manual step.

    python3 agent/render_mlx_plist.py mlx-community/Qwen3-30B-A3B-4bit [--port 8092] [-o PATH]
"""
import argparse
import plistlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import mlx_backend  # noqa: E402

LABEL = "com.caravan.mlx-server"
REPO = Path(__file__).resolve().parent.parent


def render(model: str, cfg: dict, overrides=None, log_dir="~/.caravan/logs") -> dict:
    cmd = mlx_backend.build_mlx_command(model, cfg, overrides)
    log = str(Path(log_dir).expanduser() / "mlx-server.log")
    return {
        "Label": LABEL,
        "ProgramArguments": cmd,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "ProcessType": "Interactive",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--python", default=None)
    ap.add_argument("-o", "--output", default=str(REPO / "launchd" / f"{LABEL}.plist"))
    a = ap.parse_args(argv)
    try:
        pl = render(a.model, config.load_config_file(), {"port": a.port, "host": a.host, "python": a.python})
    except (FileNotFoundError, ValueError) as e:
        ap.error(str(e))
    Path(a.output).write_bytes(plistlib.dumps(pl))
    print(f"wrote {a.output}: {' '.join(pl['ProgramArguments'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
