import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

FLAT = ("---\nname: x\ndescription: d\ntype: feedback\nstatus: active\ntier: 0\n"
        "last_modified: 1778622504\n---\nbody\n")


def run_hook(store: Path, file_path, tool="Write", via_response=False):
    payload: dict = {"session_id": "s1", "tool_name": tool}
    if via_response:
        payload["tool_response"] = {"filePath": str(file_path)}
        payload["tool_input"] = {}
    else:
        payload["tool_input"] = {"file_path": str(file_path)}
    env = dict(os.environ, CLERK_MEMORY_DIR=str(store),
               PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    return subprocess.run(["python3", "normalize_memory_write.py"],
                          input=json.dumps(payload), capture_output=True, text=True,
                          env=env, cwd=str(Path(__file__).resolve().parent.parent), timeout=30)


class TestNormalizeMemoryWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nests_flat_fields_and_reports(self):
        f = self.store / "feedback_x.md"
        f.write_text(FLAT)
        r = run_hook(self.store, f)
        self.assertIn("metadata:\n  type: feedback", f.read_text())
        self.assertIn("moved", json.loads(r.stdout)["systemMessage"])

    def test_silent_and_unchanged_when_already_canonical(self):
        f = self.store / "feedback_x.md"
        f.write_text("---\nname: x\ndescription: d\nmetadata:\n"
                     "  type: feedback\n  tier: 0\n---\nbody\n")
        before = f.read_text()
        r = run_hook(self.store, f)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(f.read_text(), before)

    def test_reads_path_from_tool_response(self):
        f = self.store / "feedback_x.md"
        f.write_text(FLAT)
        run_hook(self.store, f, via_response=True)
        self.assertIn("  type: feedback", f.read_text())

    def test_conflict_left_alone_and_reported(self):
        f = self.store / "todo_b.md"
        src = ("---\nname: b\ndescription: d\nmetadata:\n  status: archived\n"
               "status: active\ntype: todo\n---\nbody\n")
        f.write_text(src)
        r = run_hook(self.store, f)
        self.assertEqual(f.read_text(), src)
        self.assertIn("differs top-level vs nested", json.loads(r.stdout)["systemMessage"])

    def test_prefix_mismatch_warns_for_feedback_type(self):
        f = self.store / "arch_dual_memory.md"
        f.write_text("---\nname: d\ndescription: d\nmetadata:\n  type: feedback\n---\nbody\n")
        r = run_hook(self.store, f)
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertIn("type `feedback`", msg)
        self.assertIn("wrong side of version control", msg)

    def test_prefix_mismatch_silent_for_cosmetic_types(self):
        f = self.store / "reference_thing.md"
        f.write_text("---\nname: t\ndescription: d\nmetadata:\n  type: arch\n---\nbody\n")
        r = run_hook(self.store, f)
        self.assertEqual(r.stdout.strip(), "")

    def test_past_projects_names_not_warned(self):
        f = self.store / "past_projects" / "past_pr_16502_thing.md"
        f.parent.mkdir(parents=True)
        f.write_text("---\nname: p\ndescription: d\nmetadata:\n  type: feedback\n---\nbody\n")
        r = run_hook(self.store, f)
        self.assertEqual(r.stdout.strip(), "")

    def test_ignores_paths_outside_the_store(self):
        with tempfile.TemporaryDirectory() as other:
            f = Path(other) / "feedback_x.md"
            f.write_text(FLAT)
            r = run_hook(self.store, f)
            self.assertEqual(r.stdout.strip(), "")
            self.assertEqual(f.read_text(), FLAT)  # untouched

    def test_ignores_generated_index(self):
        f = self.store / "MEMORY.md"
        f.write_text(FLAT)
        r = run_hook(self.store, f)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(f.read_text(), FLAT)

    def test_ignores_non_markdown_and_missing_files(self):
        r = run_hook(self.store, self.store / "notes.txt")
        self.assertEqual(r.stdout.strip(), "")
        r = run_hook(self.store, self.store / "feedback_absent.md")
        self.assertEqual(r.stdout.strip(), "")

    def test_malformed_payload_is_silent(self):
        env = dict(os.environ, CLERK_MEMORY_DIR=str(self.store),
                   PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        r = subprocess.run(["python3", "normalize_memory_write.py"], input="not json",
                           capture_output=True, text=True, env=env,
                           cwd=str(Path(__file__).resolve().parent.parent), timeout=30)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.returncode, 0)

    def test_body_preserved(self):
        f = self.store / "feedback_x.md"
        body = "# H\n\ntext --- with dashes\n\n```\ntype: not-frontmatter\n```\n"
        f.write_text("---\nname: x\ndescription: d\ntype: feedback\n---\n" + body)
        run_hook(self.store, f)
        self.assertTrue(f.read_text().endswith("\n---\n" + body))


if __name__ == "__main__":
    unittest.main()
