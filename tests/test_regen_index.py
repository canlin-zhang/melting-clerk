import json
import tempfile
import unittest
from pathlib import Path

import memorylib
import regen_index as ri


def make_store(root: Path):
    (root / "past_projects").mkdir(parents=True)
    (root / "user_profile.md").write_text(
        "---\nname: profile\ndescription: role and team\ntype: user\n---\nbody\n")
    (root / "feedback_ci.md").write_text(
        "---\nname: never-merge-without-ci\ndescription: poll checks first\ntype: feedback\n"
        'triggers: ["gh pr merge"]\n---\n**How to apply:** poll PR HEAD check-runs to success before any merge.\n')
    (root / "project_active.md").write_text(
        "---\nname: active-proj\ndescription: in flight\ntype: project\n---\nbody\n")
    (root / "todo_merged.md").write_text(
        "---\nname: done-todo\ndescription: merged already\ntype: todo\nstatus: merged\n---\nbody\n")
    (root / "arch_notes.md").write_text(
        "---\nname: arch-notes\ndescription: lookup material\ntype: arch\n---\nbody\n")
    (root / "past_projects" / "past_pr_1.md").write_text(
        "---\nname: pr-1\ndescription: archived pr\ntype: project\n---\nbody\n")
    (root / "MEMORY.md").write_text("old index\n")


class TestRegen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_store(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tier0_only_in_index_and_sections_ordered(self):
        text = ri.render(memorylib.walk_memories(self.root))
        self.assertIn("user_profile.md", text)
        self.assertIn("feedback_ci.md", text)
        self.assertIn("project_active.md", text)
        # non-active and tier-1 entries must NOT have index lines
        self.assertNotIn("todo_merged.md", text)
        self.assertNotIn("arch_notes.md", text)
        self.assertNotIn("past_pr_1.md", text)
        # tier-1 summary counts them
        self.assertIn("3 files not indexed", text)
        # section order: User before Feedback before Active Projects
        self.assertLess(text.index("## User"), text.index("## Feedback"))
        self.assertLess(text.index("## Feedback"), text.index("## Active Projects"))

    def test_deterministic_and_atomic(self):
        ri.regen(self.root)
        first = (self.root / "MEMORY.md").read_bytes()
        ri.regen(self.root)
        second = (self.root / "MEMORY.md").read_bytes()
        self.assertEqual(first, second)
        self.assertFalse((self.root / "MEMORY.md.tmp").exists())

    def test_triggers_json(self):
        ri.regen(self.root)
        data = json.loads((self.root / "triggers.json").read_text())
        self.assertEqual(len(data["rules"]), 1)
        r = data["rules"][0]
        self.assertEqual(r["pattern"], "gh pr merge")
        self.assertEqual(r["file"], "feedback_ci.md")
        self.assertIn("poll PR HEAD check-runs", r["reminder"])

    def test_long_line_truncated(self):
        (self.root / "feedback_long.md").write_text(
            "---\nname: long\ndescription: " + "x" * 400 + "\ntype: feedback\n---\nbody\n")
        text = ri.render(memorylib.walk_memories(self.root))
        bad = [ln for ln in text.splitlines() if ln.startswith("- [") and len(ln) > 200]
        self.assertEqual(bad, [])

    def test_over_budget_reports_candidates(self):
        for i in range(160):
            (self.root / f"feedback_bulk_{i:03}.md").write_text(
                f"---\nname: bulk-{i:03}\ndescription: {'d' * 180}\ntype: feedback\n"
                f"last_modified: {1700000000 + i}\n---\nbody\n")
        ri.regen(self.root)
        over, size, lines, cands = ri.budget_status(self.root)
        self.assertTrue(over)
        self.assertGreater(size, memorylib.MAX_BYTES)
        self.assertEqual(cands[0], "feedback_bulk_000.md")  # oldest last_modified first


class TestBudgetGuard(unittest.TestCase):
    def _run(self, stdin_obj, env_root):
        import os
        import subprocess
        env = dict(os.environ, CLAUDE_MEMORY_DIR=str(env_root))
        r = subprocess.run(
            ["python3", "budget_guard.py"], input=json.dumps(stdin_obj),
            capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_regen_runs_and_silent_within_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_store(root)
            out = self._run({"hook_event_name": "SessionStart", "source": "startup"}, root)
            self.assertEqual(out.strip(), "")            # quiet when healthy
            self.assertIn("GENERATED", (root / "MEMORY.md").read_text())

    def test_compact_source_emits_clerk_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_store(root)
            out = self._run({"hook_event_name": "SessionStart", "source": "compact"}, root)
            self.assertIn("[clerk]", out)
            self.assertIn("Compaction", out)

    def test_over_budget_warns_with_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_store(root)
            for i in range(160):
                (root / f"feedback_bulk_{i:03}.md").write_text(
                    f"---\nname: bulk-{i:03}\ndescription: {'d' * 180}\ntype: feedback\n"
                    f"last_modified: {1700000000 + i}\n---\nbody\n")
            out = self._run({"hook_event_name": "SessionStart", "source": "startup"}, root)
            self.assertIn("[memory-budget]", out)
            self.assertIn("feedback_bulk_000.md", out)


if __name__ == "__main__":
    unittest.main()
