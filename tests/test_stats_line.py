import pathlib, unittest

HTML = (pathlib.Path(__file__).resolve().parents[1] / "proxy/web/index.html").read_text()


class StatsLine(unittest.TestCase):
    def test_new_format(self):
        self.assertIn('_seg("Read", st.prompt_tokens, readTs, 0)', HTML)
        self.assertIn('_seg("Write", st.completion_tokens, st.write_tok_s, 1)', HTML)
        self.assertIn('" at"', HTML)
        self.assertNotIn('}→${st.completion_tokens', HTML)


if __name__ == "__main__":
    unittest.main()
