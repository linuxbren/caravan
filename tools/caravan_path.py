"""Manage only Caravan's marked login-shell PATH block."""
import os
from pathlib import Path
import re
import sys

START = "# >>> caravan >>>"
END = "# <<< caravan <<<"
BLOCK = START + '\nexport PATH="$HOME/.caravan/bin:$PATH"\n' + END + '\n'


def configure(action="install", home=None, shell=None):
    home = Path(home or Path.home())
    shell = shell or os.environ.get("SHELL", "/bin/zsh")
    names = [".zprofile"]
    if Path(shell).name == "bash" or action == "remove":
        names.append(".bash_profile")
    for name in names:
        p = home / name
        if p.is_symlink():
            raise ValueError("Shell profile is a link; add Caravan to PATH manually: " + str(p))
        text = p.read_text() if p.exists() else ""
        if text.count(START) != text.count(END):
            raise ValueError("Incomplete Caravan PATH block; inspect " + str(p))
        clean = re.sub(r"(?m)^" + re.escape(START) + r"\n.*?^" + re.escape(END) + r"\n?", "", text, flags=re.S)
        new = clean
        if action == "install":
            new = clean + ("" if not clean or clean.endswith("\n") else "\n") + BLOCK
        if new != text:
            p.write_text(new)


if __name__ == "__main__":
    configure(sys.argv[1] if len(sys.argv) > 1 else "install")
