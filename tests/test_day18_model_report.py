import json, tempfile, unittest
from pathlib import Path
import web_alert

ROWS = [{"hf": "org/A", "warnings": ["w1", "w2"]}, {"hf": "org/B", "warnings": []}]
ENV = {"CARAVAN_ALERT_WEBHOOK_URL": "https://example.invalid/hook", "CARAVAN_ALERT_WEBHOOK_KEY": "k"}


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp()) / "alert-sent.json"
        self.calls = []

    def post(self, url, key, pl):
        self.calls.append((url, key, pl)); return True

    def test_off_when_unset(self):
        self.assertEqual(web_alert.check_and_send(ROWS, env={}, path=self.p, post=self.post), [])
        self.assertEqual(self.calls, []); self.assertFalse(self.p.exists())

    def test_payload_and_dedupe(self):
        sent = web_alert.check_and_send(ROWS, env=ENV, path=self.p, post=self.post, mini="exo1", version="abc123")
        self.assertEqual(sent, [{"model": "org/A", "warnings": ["w1", "w2"], "mini": "exo1", "caravan_version": "abc123"}])
        self.assertEqual(self.calls[0][:2], ("https://example.invalid/hook", "k"))
        web_alert.check_and_send(ROWS, env=ENV, path=self.p, post=self.post, mini="exo1", version="x")
        self.assertEqual(len(self.calls), 1)
        # new warning set -> new ping
        web_alert.check_and_send([{"hf": "org/A", "warnings": ["w3"]}], env=ENV, path=self.p, post=self.post, mini="exo1", version="x")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(json.loads(self.p.read_text())), 2)

    def test_failed_post_retries_later(self):
        web_alert.check_and_send(ROWS, env=ENV, path=self.p, post=lambda *a: False, mini="m", version="v")
        web_alert.check_and_send(ROWS, env=ENV, path=self.p, post=self.post, mini="m", version="v")
        self.assertEqual(len(self.calls), 1)

    def test_async_noop_unset(self):
        import os
        old = os.environ.pop("CARAVAN_ALERT_WEBHOOK_URL", None)
        try:
            web_alert.maybe_alert_async(ROWS)  # must not raise or start anything
        finally:
            if old is not None:
                os.environ["CARAVAN_ALERT_WEBHOOK_URL"] = old


class ReportLinkTests(unittest.TestCase):
    def test_html_has_report_link(self):
        html = (Path(__file__).resolve().parent.parent / "proxy/web/index.html").read_text()
        self.assertIn("https://github.com/linuxbren/caravan/issues/new?", html)
        self.assertIn("labels: \"model-report\"", html)
        self.assertIn("Report this model", html)
        self.assertIn("edit it before sending", html)

    def test_template(self):
        t = (Path(__file__).resolve().parent.parent / ".github/ISSUE_TEMPLATE/model-report.md").read_text()
        self.assertIn("labels: model-report", t)


if __name__ == "__main__":
    unittest.main()
