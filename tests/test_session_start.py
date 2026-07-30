import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent

REGISTRY = """---
name: clones
description: Registry of local working copies.
metadata:
  type: reference
  expected_origin: {origin}
---

# Clones

| Label | Path |
|-------|------|
"""


def git(cwd: Path, *args):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


def make_repo(path: Path, origin: str | None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "T")
    (path / "f.txt").write_text("x")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "c")
    if origin:
        # .invalid is RFC-reserved and can never resolve, so no fixture here can
        # be mistaken for, or accidentally contact, a real account.
        git(path, "remote", "add", "origin", f"https://git.example.invalid/{origin}.git")
    return path


def run_hook(store: Path, cwd: Path):
    env = dict(os.environ, CLAUDE_MEMORY_DIR=str(store))
    return subprocess.run(["python3", str(SCRIPTS / "session_start.py")], cwd=cwd,
                          capture_output=True, text=True, env=env, timeout=30)


class TestSessionStart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"
        self.store.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_honours_memory_dir_override(self):
        """The store location must be configurable, not assumed under the home dir."""
        (self.store / ".handoff.md").write_text("Branch: x\nLast action: did a thing\n")
        out = run_hook(self.store, self.root).stdout
        self.assertIn("did a thing", out)

    def test_no_handoff_section_when_absent(self):
        out = run_hook(self.store, self.root).stdout
        self.assertIn("=== SESSION CONTEXT ===", out)
        self.assertNotIn("Handoff:", out)

    def test_active_todos_listed_from_memories(self):
        (self.store / "todo_thing.md").write_text(
            "---\nname: t\ndescription: finish the thing\nmetadata:\n  type: todo\n---\nbody\n")
        (self.store / "arch_other.md").write_text(
            "---\nname: a\ndescription: not a todo\nmetadata:\n  type: arch\n---\nbody\n")
        out = run_hook(self.store, self.root).stdout
        self.assertIn("finish the thing", out)
        self.assertNotIn("not a todo", out)

    def test_registry_label_used_when_origin_matches(self):
        repo = make_repo(self.root / "myproj", "demo-org/demo-repo")
        (self.store / "clones.md").write_text(REGISTRY.format(origin="demo-org/demo-repo"))
        out = run_hook(self.store, repo).stdout
        self.assertIn("myproj", out)          # auto-registered by basename
        self.assertNotIn("<unregistered>", out)

    def test_unregistered_when_origin_does_not_match(self):
        repo = make_repo(self.root / "other", "other-org/other-repo")
        (self.store / "clones.md").write_text(REGISTRY.format(origin="demo-org/demo-repo"))
        out = run_hook(self.store, repo).stdout
        self.assertIn("<unregistered>", out)

    def test_registry_is_repo_agnostic(self):
        """expected_origin comes from the file, so any repo can be tracked."""
        repo = make_repo(self.root / "totally-different", "unrelated-org/unrelated-repo")
        (self.store / "clones.md").write_text(REGISTRY.format(origin="unrelated-org/unrelated-repo"))
        out = run_hook(self.store, repo).stdout
        self.assertNotIn("<unregistered>", out)
        self.assertIn("totally-different", (self.store / "clones.md").read_text())

    def test_empty_registry_auto_populates_its_first_row(self):
        """A fresh registry must self-seed; requiring a hand-added first row is a trap."""
        repo = make_repo(self.root / "first", "demo-org/demo-repo")
        reg = self.store / "clones.md"
        reg.write_text(REGISTRY.format(origin="demo-org/demo-repo"))   # header + separator only
        run_hook(self.store, repo)
        self.assertIn("| first | `", reg.read_text())

    def test_label_collision_defers_to_manual_fix(self):
        a = make_repo(self.root / "a" / "proj", "demo-org/demo-repo")
        b = make_repo(self.root / "b" / "proj", "demo-org/demo-repo")
        reg = self.store / "clones.md"
        reg.write_text(REGISTRY.format(origin="demo-org/demo-repo"))
        run_hook(self.store, a)
        run_hook(self.store, b)
        self.assertEqual(reg.read_text().count("| proj |"), 1)  # second not auto-added

    def test_outside_a_git_repo_is_not_fatal(self):
        out = run_hook(self.store, self.root)
        self.assertEqual(out.returncode, 0)
        self.assertIn("=== SESSION CONTEXT ===", out.stdout)


if __name__ == "__main__":
    unittest.main()
