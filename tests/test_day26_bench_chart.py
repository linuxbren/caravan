"""Day 26: First token bars follow the seconds (shorter is sooner)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import caravan_chart as CH  # noqa: E402

DAY = (ROOT / "docs/DAY26.md").read_text()
BENCH = (ROOT / "tools/caravan_bench.py").read_text()


def _hashes(line: str) -> int:
    return line.count("#")


def _section(text: str, title: str) -> list[str]:
    lines = text.splitlines()
    i = lines.index(title)
    out = []
    for line in lines[i + 1:]:
        if not line.strip():
            break
        out.append(line)
    return out


class FirstTokenShorterIsSooner(unittest.TestCase):
    def test_label_is_unchanged(self):
        text = CH.fixture_chart(ascii=True)
        self.assertIn("First token (s, lower is better)", text)

    def test_short_prompt_bar_follows_the_seconds(self):
        text = CH.fixture_chart(ascii=True)
        rows = _section(text, "First token (s, lower is better)")
        gguf, mlx = rows[0], rows[1]
        self.assertIn("0.28s", gguf)
        self.assertIn("0.46s", mlx)
        self.assertIn("* +39%", gguf)
        self.assertNotIn("*", mlx)
        g, m = _hashes(gguf), _hashes(mlx)
        self.assertLess(g, m, "sooner (0.28s) must be the shorter bar")
        # 0.28/0.46 ≈ 0.609; 30/49 ≈ 0.612 on the 80-column fixture.
        self.assertAlmostEqual(g / m, 0.28 / 0.46, delta=0.03)

    def test_longer_wait_is_the_longer_bar_at_every_size(self):
        def seconds(line):
            for tok in line.split():
                if tok.endswith("s") and tok[:-1].replace(".", "", 1).isdigit():
                    return float(tok[:-1])
            self.fail(line)

        text = CH.fixture_chart(ascii=True)
        rows = _section(text, "First token (s, lower is better)")
        self.assertEqual(len(rows), 8)
        for i in range(0, 8, 2):
            g_line, m_line = rows[i], rows[i + 1]
            gs, ms = seconds(g_line), seconds(m_line)
            g_h, m_h = _hashes(g_line), _hashes(m_line)
            if gs < ms:
                self.assertLess(g_h, m_h, (g_line, m_line))
            elif gs > ms:
                self.assertGreater(g_h, m_h, (g_line, m_line))

    def test_reading_and_writing_bars_are_unchanged(self):
        # Same fixture speeds as Day 25; only first-token direction flipped.
        text = CH.fixture_chart(ascii=True)
        self.assertIn(
            "Short  GGUF  ###################################                   182",
            text,
        )
        self.assertIn(
            "       MLX   ###########################################          20.4  * +22%",
            text,
        )

    def test_ascii_and_unicode_agree_on_who_is_shorter(self):
        ascii_txt = CH.fixture_chart(ascii=True)
        uni = CH.fixture_chart(ascii=False, color=False)
        a = _section(ascii_txt, "First token (s, lower is better)")
        u = _section(uni, "First token (s, lower is better)")
        def bar_len(line, marks):
            return sum(line.count(m) for m in marks)
        # Short prompts: GGUF shorter in both styles.
        self.assertLess(bar_len(a[0], "#"), bar_len(a[1], "#"))
        self.assertLess(bar_len(u[0], "█▌"), bar_len(u[1], "█▌"))
        self.assertIn("0.28s  ★ +39%", u[0] if "★" in u[0] else uni)

    def test_details_is_unchanged_words(self):
        # --details is the reply-stats lines, not the bars.
        self.assertIn("--details", BENCH)
        self.assertIn("stats under each reply", BENCH)

    def test_docs_explain_the_choice(self):
        import re
        low = re.sub(r"\s+", " ", DAY.lower())
        self.assertIn("shorter bar is sooner", low)
        self.assertIn("first token (s, lower is better)", low)


if __name__ == "__main__":
    unittest.main()
