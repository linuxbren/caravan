#!/usr/bin/env python3
"""Which Caravan version is installed (Day 32 part A).

The release number comes from the VERSION file that ships inside the
installed source (each release's source commit sets it), and the exact
build from the installed pin (`.caravan-package`, the source commit the
installer verified). A source checkout uses VERSION and its git commit.
Nothing here is hardcoded and nothing touches the network.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)

ROOT = Path(__file__).resolve().parents[1]
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def release(root=None):
    """'0.9.4' from VERSION, or None when missing or malformed."""
    try:
        text = (Path(root or ROOT) / "VERSION").read_text().strip()
    except OSError:
        return None
    return text if _VERSION_RE.match(text) else None


def installed_ref(root=None):
    """Full source commit of this install: the pin for a package install,
    the checkout's HEAD for a source checkout, else None."""
    root = Path(root or ROOT)
    try:
        ref = (root / ".caravan-package").read_text().strip().split()[0].lower()
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            return ref
    except (OSError, IndexError):
        pass
    if (root / ".git").exists():
        try:
            out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, timeout=3)
            ref = out.stdout.strip().lower()
            if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", ref):
                return ref
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def info(root=None):
    """JSON-safe: {"version", "label", "ref", "short", "packaged"}."""
    root = Path(root or ROOT)
    version = release(root)
    ref = installed_ref(root)
    return {
        "version": version,
        "label": f"v{version}" if version else "",
        "ref": ref,
        "short": ref[:7] if ref else None,
        "packaged": (root / ".caravan-package").is_file() and not (root / ".git").exists(),
    }


def text(root=None):
    """One line for the CLI: 'Caravan v0.9.4 (4b48b85)'."""
    i = info(root)
    head = T("cli.version.caravan_label", label=i['label']) if i["label"] else T("cli.version.caravan_version_unknown")
    return head + (f" ({i['short']})" if i["short"] else "")


def main(argv=None):
    print(text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
