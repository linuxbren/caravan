"""A one-line live progress animation for `caravan bench --yes`.

On a terminal it flickers a tiny campfire and the current step, in place,
with elapsed time. When stdout is not a TTY, or NO_COLOR is set, it
prints plain step lines instead. --quiet prints nothing.
"""
from __future__ import annotations

import os
import sys
import threading
import time

# A tiny campfire flicker. One cell each, widely available.
FRAMES = ("·", "✦", "✶", "✸", "✶", "✦")


def no_color_set() -> bool:
    v = os.environ.get("NO_COLOR")
    return v is not None and v != ""


def decide_mode(stream=None, *, quiet=False) -> str:
    """'animate', 'plain', or 'off'."""
    if quiet:
        return "off"
    stream = sys.stdout if stream is None else stream
    try:
        tty = bool(stream.isatty())
    except Exception:
        tty = False
    if not tty or no_color_set():
        return "plain"
    return "animate"


def loading_step(name: str) -> str:
    return f"Loading {name}…"


def short_step(kind: str, i: int, n: int = 5) -> str:
    return f"{kind} · short prompt {int(i)} of {int(n)}"


def long_step(kind: str, size, i: int, n: int = 2) -> str:
    label = size if isinstance(size, str) else _size_label(size)
    return f"{kind} · long prompt ~{label}, {int(i)} of {int(n)}"


def restore_step() -> str:
    return "Putting the original model back…"


def _size_label(n) -> str:
    try:
        import caravan_prompts as P
        return P.size_label(int(n))
    except Exception:
        n = int(n)
        if n >= 1000 and n % 1024 == 0:
            return f"{n // 1024}k"
        if n >= 1000 and n % 1000 == 0:
            return f"{n // 1000}k"
        return str(n)


def format_elapsed(seconds: float) -> str:
    s = max(0, int(seconds))
    m, s = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class Progress:
    """Background one-line spinner, or plain step lines, or nothing."""

    def __init__(self, out=None, *, mode=None, quiet=False):
        self.out = sys.stdout if out is None else out
        self.quiet = bool(quiet)
        self.mode = mode if mode is not None else decide_mode(self.out, quiet=self.quiet)
        self._lock = threading.Lock()
        self._step = ""
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._thread = None
        self._width = 0
        self._frame = 0
        self._shown = False

    @property
    def alive(self) -> bool:
        t = self._thread
        return bool(t is not None and t.is_alive())

    def start(self):
        self._t0 = time.monotonic()
        if self.mode != "animate":
            return self
        if self.alive:
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="caravan-bench-progress", daemon=True,
        )
        self._thread.start()
        return self

    def set(self, step: str):
        step = str(step or "")
        with self._lock:
            self._step = step
        if self.mode == "plain" and step and not self.quiet:
            try:
                self.out.write(step + "\n")
                self.out.flush()
            except Exception:
                pass

    def clear(self):
        """Erase the in-place line so a result can be printed cleanly."""
        if self.mode != "animate":
            return
        with self._lock:
            if not self._shown and self._width <= 0:
                return
            try:
                self.out.write("\r" + " " * max(self._width, 1) + "\r")
                self.out.flush()
            except Exception:
                pass
            self._width = 0
            self._shown = False

    def println(self, text=""):
        """Clear the spinner line, then print a result line."""
        self.clear()
        try:
            self.out.write(str(text) + "\n")
            self.out.flush()
        except Exception:
            pass

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
            self._thread = None
        self.clear()

    def _run(self):
        while not self._stop.wait(0.12):
            try:
                with self._lock:
                    if self._step:
                        self._render()
            except Exception:
                break

    def _render(self):
        elapsed = format_elapsed(time.monotonic() - self._t0)
        frame = FRAMES[self._frame % len(FRAMES)]
        self._frame += 1
        line = f"{frame}  {self._step}  {elapsed}"
        width = _term_width(self.out)
        if width and len(line) >= width:
            line = line[: max(1, width - 1)]
        pad = max(0, self._width - len(line))
        try:
            self.out.write("\r" + line + " " * pad)
            self.out.flush()
        except Exception:
            self._shown = False
            return
        self._width = len(line)
        self._shown = True


def _term_width(stream) -> int:
    try:
        return int(os.get_terminal_size(stream.fileno()).columns)
    except Exception:
        try:
            import shutil
            return int(shutil.get_terminal_size((80, 24)).columns)
        except Exception:
            return 80
