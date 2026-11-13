"""Day 26: download progress sits under the model you just clicked."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "proxy/web/index.html").read_text()
PICKER = (ROOT / "docs/MODEL_PICKER.md").read_text()
DAY = (ROOT / "docs/DAY26.md").read_text()
WEB = (ROOT / "docs/WEB.md").read_text()


def _fn(name: str, end: str | None = None) -> str:
    start = HTML.index(f"function {name}")
    if end:
        return HTML[start:HTML.index(end, start)]
    nxt = HTML.find("\n    function ", start + 10)
    nxt2 = HTML.find("\n    async function ", start + 10)
    cuts = [c for c in (nxt, nxt2) if c != -1]
    return HTML[start:min(cuts)] if cuts else HTML[start:start + 4000]


class UnderTheClickedModel(unittest.TestCase):
    def test_host_prefers_the_matching_row_slot(self):
        body = _fn("jobCardHost", "function showJobs")
        self.assertIn('querySelectorAll("#pickerList .p-row[data-repo-ids]")', body)
        self.assertIn("row.dataset.repoIds", body)
        self.assertIn("ids.includes(repo)", body)
        self.assertIn('picker-job-slot', body)
        self.assertIn('return $("pickerJob")', body)
        # A missing model falls back; a match does not.
        self.assertIn("is not in the current list", body)

    def test_show_jobs_moves_the_card_into_the_row(self):
        body = _fn("showJobs", "function renderJobCard")
        self.assertIn("jobCardHost(j)", body)
        self.assertIn("card.parentElement !== host", body)
        self.assertIn("host.appendChild(card)", body)
        self.assertIn("usedFallback", body)
        self.assertIn("fallback.hidden = !usedFallback", body)
        # Stale cards are cleaned from both the fallback and the in-row slots.
        self.assertIn("#pickerJob [data-job-id], .picker-job-slot [data-job-id]", body)

    def test_job_card_lookup_covers_in_row_slots(self):
        body = _fn("jobCardEl", "function jobCardHost")
        self.assertIn('pickerBody', body)
        self.assertIn("data-job-id", body)
        # No longer limited to the fallback box alone.
        self.assertNotIn('const el = $("pickerJob")', body)

    def test_render_list_tags_rows_and_leaves_a_visible_slot(self):
        body = _fn("renderList", "function escapeHtml")
        self.assertIn("row.dataset.repoIds = repoIds.join(", body)
        self.assertIn("quants.map((q) => q.repo_id)", body)
        self.assertIn('slot.className = "picker-job-slot"', body)
        # Slot is a sibling after the quant list, not inside it, so the
        # card stays visible when the row is closed.
        qpos = body.index("row.appendChild(quantsEl)")
        spos = body.index('slot.className = "picker-job-slot"')
        self.assertLess(qpos, spos)
        self.assertNotIn("quantsEl.appendChild(slot)", body)
        # Re-attach cards after every redraw, including an empty list.
        self.assertIn("showJobs();", body)
        empty = body[body.index("No models match"):body.index("for (const g of groups)")]
        self.assertIn("showJobs()", empty)
        self.assertIn("showJobs();", body[body.rindex("box.appendChild(row)"):])

    def test_slot_stays_visible_when_the_row_is_closed(self):
        self.assertIn(".picker-job-slot:not(:empty) { display: block; }", HTML)
        self.assertIn(".picker-job-slot { display: none;", HTML)
        # The closed-row rule hides only the quant buttons, not the slot.
        self.assertIn(".p-row.open .p-quants { display: block; }", HTML)
        self.assertNotIn(".p-row.open .picker-job-slot", HTML)
        self.assertNotIn(".p-quants .picker-job-slot", HTML)

    def test_campfire_still_styles_the_card(self):
        self.assertIn(
            'html[data-theme="campfire"] .picker-job-slot,', HTML,
        )

    def test_starting_a_download_scrolls_the_in_row_card(self):
        # Both GGUF and MLX paths place the card, then scroll it.
        gguf = HTML[HTML.index('source: "gguf", gguf_file'):HTML.index("function placeButtonLabel")]
        mlx = HTML[HTML.index("Downloading ${q.repo_id}"):HTML.index("function placeButtonLabel")]
        for body in (gguf, mlx):
            self.assertIn("upsertJob(data.job)", body)
            self.assertIn("showJobs()", body)
            self.assertIn("jobCardEl(data.job.id)", body)
            self.assertIn('scrollIntoView({ block: "nearest"', body)
        # The old "always scroll the top box" path is gone.
        self.assertNotIn('$("pickerJob").scrollIntoView', HTML)

    def test_docs_say_the_card_sits_under_the_model(self):
        import re
        for text in (PICKER, DAY, WEB):
            flat = re.sub(r"\s+", " ", text.lower())
            self.assertIn("under the model you clicked", flat)


if __name__ == "__main__":
    unittest.main()
