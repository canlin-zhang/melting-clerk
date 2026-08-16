import os
import subprocess
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent

ENV_KEYS = ("CLERK_MEMORY_DIR", "DSH_MEMORY_DIR", "CLAUDE_MEMORY_DIR")


def resolve(overrides):
    """Resolve MEMORY_DIR in a fresh subprocess with the ambient vars scrubbed."""
    env = dict(os.environ)
    for key in ENV_KEYS:
        env.pop(key, None)
    env.update(overrides)
    proc = subprocess.run(
        ["python3", "-c", "import memorylib; print(memorylib.MEMORY_DIR)"],
        capture_output=True, text=True, env=env, cwd=SCRIPTS, timeout=30,
    )
    assert proc.returncode == 0, f"resolver failed with exit {proc.returncode}: {proc.stderr}"
    return proc.stdout.strip()


class TestMemoryDirPrecedence(unittest.TestCase):
    def test_clerk_beats_dsh_beats_claude(self):
        self.assertEqual(
            resolve({
                "CLERK_MEMORY_DIR": "/clerk",
                "DSH_MEMORY_DIR": "/dsh",
                "CLAUDE_MEMORY_DIR": "/claude",
            }),
            "/clerk",
        )

    def test_dsh_beats_claude(self):
        self.assertEqual(
            resolve({"DSH_MEMORY_DIR": "/dsh", "CLAUDE_MEMORY_DIR": "/claude"}),
            "/dsh",
        )

    def test_claude_fallback(self):
        self.assertEqual(resolve({"CLAUDE_MEMORY_DIR": "/claude"}), "/claude")

    def test_default_is_claude_home(self):
        self.assertEqual(resolve({}), str(Path.home() / ".claude" / "memory"))


if __name__ == "__main__":
    unittest.main()
