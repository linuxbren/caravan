"""Manage only Caravan's marked login-shell PATH block."""
import os
from pathlib import Path
import re
import sys
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)

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
            raise ValueError(T("cli.path.shell_profile_is_a_link_add", p=str(p)))
        text = p.read_text() if p.exists() else ""
        if text.count(START) != text.count(END):
            raise ValueError(T("cli.path.incomplete_caravan_path_block_inspect_p", p=str(p)))
        clean = re.sub(r"(?m)^" + re.escape(START) + r"\n.*?^" + re.escape(END) + r"\n?", "", text, flags=re.S)
        new = clean
        if action == "install":
            new = clean + ("" if not clean or clean.endswith("\n") else "\n") + BLOCK
        if new != text:
            p.write_text(new)


if __name__ == "__main__":
    configure(sys.argv[1] if len(sys.argv) > 1 else "install")
