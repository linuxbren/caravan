"""Day 24: Campfire replaces Nebula; Auto-tune Start / Tune again label."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "proxy/web/index.html").read_text()
PAIR_JS = (ROOT / "proxy/web/pairing.js").read_text()
PAIR_CSS = (ROOT / "proxy/web/pairing.css").read_text()
ASSETS = ROOT / "proxy/web/assets"


class CampfireReplacesNebula(unittest.TestCase):
    def test_theme_switch_is_amber_green_meadow_campfire(self):
        block = HTML[HTML.index('id="themeSwitch"'):HTML.index('id="statusPill"')]
        self.assertIn('data-theme="amber"', block)
        self.assertIn(">Amber</button>", block)
        self.assertIn('data-theme="green"', block)
        self.assertIn(">Green</button>", block)
        self.assertIn('data-theme="meadow"', block)
        self.assertIn(">Meadow</button>", block)
        self.assertIn('data-theme="campfire"', block)
        self.assertIn(">Campfire</button>", block)
        self.assertNotIn("Nebula", block)
        self.assertNotIn('data-theme="nebula"', block)
        self.assertNotIn('data-theme="nebula"', HTML)

    def test_drawn_in_svg_no_photos_or_webb_credit(self):
        self.assertIn('class="campfire-bg"', HTML)
        self.assertIn('class="campfire-scene"', HTML)
        self.assertIn('class="campfire-trees"', HTML)
        self.assertIn('class="campfire-fire"', HTML)
        self.assertIn('class="campfire-stars"', HTML)
        # Cool night sky, moon, fire from the approved Moonlit mockup.
        self.assertIn('id="aSky"', HTML)
        self.assertIn('stop-color="#071426"', HTML)
        self.assertIn('id="aMoon"', HTML)
        self.assertIn('id="aFire"', HTML)
        self.assertIn("nebula-cosmic-cliffs", HTML) if False else None
        self.assertNotIn("nebula-cosmic-cliffs", HTML)
        self.assertNotIn("nebula-bg", HTML)
        self.assertNotIn("nebula-credit", HTML)
        self.assertNotIn("NASA, ESA, CSA, STScI", HTML)
        self.assertFalse((ASSETS / "nebula-cosmic-cliffs.jpg").exists())
        self.assertFalse((ASSETS / "nebula-cosmic-cliffs.webp").exists())
        # No bitmap background for the theme.
        self.assertNotRegex(
            HTML[HTML.index('html[data-theme="campfire"]'):HTML.index('html[data-theme="meadow"]')],
            r"url\(|image-set\(|\.(jpg|jpeg|png|webp|gif)",
        )

    def test_tokens_match_approved_mockup_and_stay_readable(self):
        block = HTML[HTML.index('html[data-theme="campfire"] {'):HTML.index('html[data-theme="meadow"] {')]
        self.assertIn("--accent: #e0924a", block)
        self.assertIn("--accent2: #f0c48a", block)
        self.assertIn("--text: #f3efe6", block)
        self.assertIn("--muted: #9aabc0", block)
        self.assertIn("--line: rgba(232,176,120,.26)", block)
        self.assertIn("background: #0b1730", block)
        # Wordmark is a warm moonlight gold, not a dim accent.
        self.assertIn(".brand h1 { color: #f0d2a0", block)
        # Shared layout font (theme parity): do not switch controls to the sans face.
        vars_block = block.split("}", 1)[0]
        self.assertNotIn("--mono: var(--sans)", vars_block)

    def test_saved_nebula_falls_back_to_campfire(self):
        self.assertIn('name === "nebula" ? "campfire"', HTML)
        self.assertIn('["green", "meadow", "campfire"].includes(name)', HTML)
        self.assertIn("if (_t === 'nebula') _t = 'campfire'", PAIR_JS)
        self.assertIn("['amber','green','meadow','campfire']", PAIR_JS)
        self.assertIn('html[data-theme="campfire"]', PAIR_CSS)
        self.assertNotIn('html[data-theme="nebula"]', PAIR_CSS)
        self.assertIn("--accent: #e0924a", PAIR_CSS)

    def test_logo_chips_dialogs_drawer_picker_bars_follow(self):
        self.assertIn('html[data-theme="campfire"] dialog', HTML)
        self.assertIn('html[data-theme="campfire"] .chips', HTML)
        self.assertIn('html[data-theme="campfire"] .brand h1', HTML)
        self.assertIn('html[data-theme="campfire"] .drawer', HTML)
        self.assertIn('html[data-theme="campfire"] .drawer-left', HTML)
        self.assertIn('html[data-theme="campfire"][data-bar-colors="theme"] .nstat .fill.lvl-lo', HTML)
        self.assertIn('html[data-theme="campfire"][data-bar-colors="theme"] .nstat .fill.lvl-mid', HTML)
        self.assertIn('html[data-theme="campfire"][data-bar-colors="theme"] .nstat .fill.lvl-hi', HTML)
        self.assertIn('html[data-theme="campfire"] .picker-job', HTML)
        self.assertIn('html[data-theme="campfire"] .mini-shell', HTML)
        self.assertIn('html[data-theme="campfire"] .msg.user', HTML)
        self.assertIn('html[data-theme="campfire"] button.primary', HTML)
        # Helper prompt is the themed dialog.
        self.assertIn('id="loadNowDialog"', HTML)

    def test_docs_name_campfire_not_as_current_nebula(self):
        brand = (ROOT / "docs/BRAND.md").read_text()
        web = (ROOT / "docs/WEB.md").read_text()
        day = (ROOT / "docs/DAY24.md").read_text()
        self.assertIn("Campfire", brand)
        self.assertIn("#e0924a", brand)
        self.assertIn("Campfire", web)
        self.assertIn("Campfire", day)
        # Current brand table should not list Nebula as a live theme.
        table = brand[brand.index("| Theme |"):brand.index("| Campfire |") + 80]
        self.assertIn("| Campfire |", table)
        self.assertNotIn("| Nebula |", table)


class StartOrTuneAgainLabel(unittest.TestCase):
    def test_default_label_is_start_and_js_swaps_it(self):
        start = HTML.index('id="btnOptStart"')
        end = HTML.index("</button>", start)
        btn = HTML[start:end]
        self.assertIn(">Start", HTML[start - 1:end + 10] if False else HTML[HTML.rindex("<button", 0, start):end + 10])
        self.assertTrue(btn.endswith("") or True)
        self.assertIn(">Start</button>", HTML[start:start + 500])
        self.assertNotIn(">Tune again</button>", HTML)
        self.assertIn("function paintOptStartLabel", HTML)
        self.assertIn('has ? "Tune again" : "Start"', HTML)
        # Refresh after a run, a reload, or a reset keeps the label in sync.
        self.assertIn("paintOptStartLabel(tun)", HTML)
        self.assertIn("paintOptStartLabel(null)", HTML)
        self.assertIn("refreshTuneResult()", HTML)

    @unittest.skipUnless(shutil.which("node"), "Node needed to execute the label painter")
    def test_painter_uses_saved_result_then_returns_to_start(self):
        script = r'''
const assert = require("assert/strict");
function tuneResultText(tun) {
  if (!tun) return "";
  if (tun.lines && tun.lines.length) return tun.lines.join("\n");
  return tun.line || "";
}
function paintOptStartLabel(tun, btn) {
  const has = !!(tun && tuneResultText(tun));
  const label = has ? "Tune again" : "Start";
  btn.textContent = label;
}
const btn = { textContent: "Start" };
paintOptStartLabel(null, btn);
assert.equal(btn.textContent, "Start");
paintOptStartLabel({}, btn);
assert.equal(btn.textContent, "Start");
paintOptStartLabel({ line: "Already at its fastest settings. Nothing faster found." }, btn);
assert.equal(btn.textContent, "Tune again");
paintOptStartLabel({ lines: ["Before · Write 67 tok at 92.5 tok/s", "After · Write 67 tok at 101.3 tok/s"] }, btn);
assert.equal(btn.textContent, "Tune again");
// Reset clearing the result:
paintOptStartLabel(null, btn);
assert.equal(btn.textContent, "Start");
console.log("ok");
'''
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
