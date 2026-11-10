import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("aux_worker", Path(__file__).resolve().parents[1]/"tools/aux_worker.py")
aux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aux)

class AuxWorkerTests(unittest.TestCase):
    def test_memory_guard_fails_closed(self):
        for value in [None, "unknown", -1, 0, float("nan"), float("inf"), 3.749]:
            self.assertFalse(aux.admit(value))
        self.assertTrue(aux.admit(3.75))
        self.assertFalse(aux.admit(8, -1, 1.75))
        self.assertFalse(aux.admit(8, 2, float("nan")))

    def test_worker_is_scoped_and_does_not_wire_or_persist(self):
        cmd = aux.worker_command("/models/tiny", 8196, 2)
        for arg in ["--no-learn", "--no-split-draft", "--no-persist"]:
            self.assertIn(arg, cmd)
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
        self.assertEqual(cmd[cmd.index("--wired-limit") + 1], "off")
        self.assertEqual(cmd[cmd.index("--memory-limit-gb") + 1], "2")
        self.assertEqual(cmd[cmd.index("--memory-recall-tokens") + 1], "0")
