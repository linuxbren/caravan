import unittest
from download_progress import parse_nettop_bytes_in


class NettopParse(unittest.TestCase):
    def test_only_requested_pid(self):
        out = ",bytes_in,\nlaunchd.1,851195580175,\nPython.4242,26150339,\n"
        self.assertEqual(parse_nettop_bytes_in(out, 4242), 26150339)

    def test_missing_pid_is_none(self):
        self.assertIsNone(parse_nettop_bytes_in(",bytes_in,\nlaunchd.1,5,\n", 99))


if __name__ == "__main__":
    unittest.main()
