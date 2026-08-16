import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def run_hook(store: Path):
    env = dict(os.environ, CLERK_MEMORY_DIR=str(store))
    return subprocess.run(["python3", str(SCRIPTS / "session_stop.py")],
                          capture_output=True, text=True, env=env, timeout=30)


class TestSessionStop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_handoff_nudges(self):
        out = run_hook(self.store).stdout
        self.assertIn("No handoff written", out)

    def test_fresh_handoff_is_silent(self):
        (self.store / ".handoff.md").write_text("Branch: x\n")
        out = run_hook(self.store).stdout
        self.assertEqual(out.strip(), "")

    def test_stale_handoff_nudges(self):
        handoff = self.store / ".handoff.md"
        handoff.write_text("Branch: x\n")
        old = time.time() - 601  # older than the 600s threshold
        os.utime(handoff, (old, old))
        out = run_hook(self.store).stdout
        self.assertIn("not updated this session", out)


if __name__ == "__main__":
    unittest.main()
