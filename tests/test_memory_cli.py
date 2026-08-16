import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def mem(root: Path, name: str, typ: str, extra: str = "", age_days: int = 0) -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {name.rsplit('/', 1)[-1][:-3]}\ndescription: d\n"
                 f"metadata:\n  type: {typ}\n{extra}---\nbody\n", encoding="utf-8")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    return p


def run(root: Path, *args):
    env = dict(os.environ, CLERK_MEMORY_DIR=str(root), PYTHONPATH=str(SCRIPTS))
    return subprocess.run(["python3", "memory_cli.py", *args], capture_output=True,
                          text=True, env=env, cwd=str(SCRIPTS), timeout=30)


class TestMemoryCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "MEMORY.md").write_text("index\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_and_type_filter(self):
        mem(self.root, "feedback_a.md", "feedback")
        mem(self.root, "arch_b.md", "arch")
        rows = json.loads(run(self.root, "list", "--json").stdout)
        self.assertEqual({r["file"] for r in rows}, {"feedback_a.md", "arch_b.md"})
        rows = json.loads(run(self.root, "list", "--type", "arch", "--json").stdout)
        self.assertEqual([r["file"] for r in rows], ["arch_b.md"])

    def test_stale_uses_days_threshold(self):
        mem(self.root, "project_fresh.md", "project", age_days=2)
        mem(self.root, "project_old.md", "project", age_days=200)
        rows = json.loads(run(self.root, "stale", "--days", "90", "--json").stdout)
        self.assertEqual([r["file"] for r in rows], ["project_old.md"])

    def test_recent_uses_days_threshold(self):
        mem(self.root, "project_fresh.md", "project", age_days=2)
        mem(self.root, "project_old.md", "project", age_days=200)
        rows = json.loads(run(self.root, "recent", "--days", "7", "--json").stdout)
        self.assertEqual([r["file"] for r in rows], ["project_fresh.md"])

    def test_archived_lists_only_past_projects_and_filters(self):
        mem(self.root, "past_projects/project_done.md", "project")
        mem(self.root, "past_projects/project_other.md", "project")
        mem(self.root, "project_live.md", "project")
        rows = json.loads(run(self.root, "archived", "--json").stdout)
        self.assertEqual(len(rows), 2)
        rows = json.loads(run(self.root, "archived", "--query", "done", "--json").stdout)
        self.assertEqual([r["file"] for r in rows], ["past_projects/project_done.md"])

    def test_hidden_finds_typeless_files(self):
        mem(self.root, "arch_ok.md", "arch")
        (self.root / "broken.md").write_text("no frontmatter here\n")
        (self.root / "typeless.md").write_text("---\nname: x\ndescription: d\n---\nbody\n")
        hidden = json.loads(run(self.root, "hidden", "--json").stdout)
        self.assertEqual(set(hidden), {"broken.md", "typeless.md"})

    def test_health_counts_visible_and_hidden(self):
        mem(self.root, "feedback_a.md", "feedback")
        mem(self.root, "arch_b.md", "arch")
        (self.root / "broken.md").write_text("nope\n")
        info = json.loads(run(self.root, "health").stdout)
        self.assertEqual(info["visible"], 2)
        self.assertEqual(info["hidden"], 1)
        self.assertEqual(info["by_type"], {"arch": 1, "feedback": 1})

    def test_archive_moves_and_stamps_inside_metadata(self):
        mem(self.root, "project_done.md", "project", extra="  status: active\n  tier: 0\n")
        r = run(self.root, "archive", "project_done.md", "--note", "PR merged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.root / "project_done.md").exists())
        text = (self.root / "past_projects" / "project_done.md").read_text()
        self.assertIn("  status: archived", text)
        self.assertIn("  archive_note: PR merged", text)
        self.assertNotIn("  status: active", text)
        # stamps must land nested, never top-level
        fm = text.split("---")[1]
        self.assertNotIn("\nstatus:", fm)

    def test_archive_refuses_traversal_missing_and_double(self):
        self.assertNotEqual(run(self.root, "archive", "../escape.md").returncode, 0)
        self.assertNotEqual(run(self.root, "archive", "absent.md").returncode, 0)
        mem(self.root, "past_projects/project_x.md", "project")
        self.assertNotEqual(run(self.root, "archive", "past_projects/project_x.md").returncode, 0)

    def test_archive_refuses_file_without_frontmatter(self):
        (self.root / "raw.md").write_text("just text\n")
        r = run(self.root, "archive", "raw.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.root / "raw.md").exists())

    def test_archive_refuses_to_clobber_existing_archive_entry(self):
        mem(self.root, "project_dup.md", "project")
        mem(self.root, "past_projects/project_dup.md", "project")
        r = run(self.root, "archive", "project_dup.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.root / "project_dup.md").exists())


if __name__ == "__main__":
    unittest.main()
