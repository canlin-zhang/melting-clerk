"""Tests for memory_server.py's store logic, with the `mcp` dependency stubbed.

CI skips memory_server.py because it imports `mcp`; these tests inject a fake
`mcp.server.fastmcp` before importing it, so the store logic (write/archive/
list/traversal) is exercised with no third-party package installed.
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _install_fake_mcp() -> None:
    fastmcp = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, name=None):
            self.name = name

        def tool(self, *args, **kwargs):
            return lambda fn: fn

        def run(self, *args, **kwargs):
            pass

    fastmcp.FastMCP = FastMCP
    server = types.ModuleType("mcp.server")
    server.fastmcp = fastmcp
    mcp = types.ModuleType("mcp")
    mcp.server = server
    sys.modules["mcp"] = mcp
    sys.modules["mcp.server"] = server
    sys.modules["mcp.server.fastmcp"] = fastmcp


_install_fake_mcp()
import memory_server as ms  # noqa: E402  # mcp stub must precede the import


class TestMemoryServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"
        self.store.mkdir()
        ms.MEMORY_DIR = self.store
        ms.HANDOFF_FILE = self.store / ".handoff.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_nests_last_modified(self):
        ms.write_memory("note.md", "---\nname: note\ndescription: a note\n---\nbody")
        text = (self.store / "note.md").read_text()
        self.assertIn("metadata:", text)
        self.assertIn("  last_modified:", text)
        self.assertNotIn("\nlast_modified:", text)

    def test_write_refreshes_nested_last_modified(self):
        """A round-trip write must refresh the (now nested) timestamp, not freeze it."""
        times = iter([1000, 2000])
        original = ms.time.time
        ms.time.time = lambda: next(times)
        try:
            ms.write_memory("note.md", "---\nname: note\ndescription: a note\n---\nbody")
            first = (self.store / "note.md").read_text()
            ms.write_memory("note.md", first.replace("body", "edited body"))
            second = (self.store / "note.md").read_text()
        finally:
            ms.time.time = original
        self.assertIn("last_modified: 2000", second)
        self.assertNotIn("last_modified: 1000", second)
        self.assertIn("edited body", second)

    def test_archive_stamps_status_nested(self):
        content = "---\nname: note\ndescription: a note\nmetadata:\n  type: project\n---\nbody"
        ms.write_memory("note.md", content)
        ms.archive_memory("note.md", "shipped")
        archived = (self.store / "past_projects" / "note.md").read_text()
        self.assertIn("  status: archived", archived)
        self.assertIn("  archive_note: shipped", archived)
        self.assertNotIn("\nstatus: archived", archived)
        self.assertFalse((self.store / "note.md").exists())

    def test_active_listing_excludes_archive(self):
        (self.store / "past_projects").mkdir()
        (self.store / "active.md").write_text("---\nname: a\ndescription: a\n---\n")
        (self.store / "past_projects" / "done.md").write_text("---\nname: d\ndescription: d\n---\n")
        self.assertEqual({f.name for f in ms._all_memory_files()}, {"active.md"})

    def test_resolve_blocks_traversal(self):
        path, err = ms._resolve_memory_path("../evil.md")
        self.assertIsNone(path)
        self.assertIn("escapes", err)


if __name__ == "__main__":
    unittest.main()
