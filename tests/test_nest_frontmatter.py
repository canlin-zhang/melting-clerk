import tempfile
import unittest
from pathlib import Path

import memorylib as ml
import nest_frontmatter as nf


def write(root: Path, name: str, text: str) -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestNestFrontmatter(unittest.TestCase):
    def test_flat_fields_move_under_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "feedback_x.md",
                      "---\nname: x\ndescription: d\ntype: feedback\n"
                      "status: active\ntier: 0\nlast_modified: 1778622504\n---\nbody\n")
            changed, conflicts = nf.migrate(root, dry=False)
            self.assertEqual(conflicts, [])
            self.assertEqual(changed[0][0], "feedback_x.md")
            text = f.read_text()
            self.assertIn("metadata:\n  type: feedback", text)
            self.assertIn("  status: active", text)
            self.assertIn("  tier: 0", text)
            # name/description stay top-level: they are auto-memory's fields.
            self.assertIn("\nname: x\n", text)
            self.assertIn("\ndescription: d\n", text)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root, "arch_y.md", "---\nname: y\ndescription: d\ntype: arch\ntier: 1\n---\nbody\n")
            nf.migrate(root, dry=False)
            first = (root / "arch_y.md").read_text()
            changed, _ = nf.migrate(root, dry=False)
            self.assertEqual(changed, [])
            self.assertEqual((root / "arch_y.md").read_text(), first)

    def test_merges_into_existing_metadata_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "project_z.md",
                      "---\nname: z\ndescription: d\nmetadata:\n  node_type: memory\n"
                      "  type: project\nstatus: active\ntier: 0\n---\nbody\n")
            nf.migrate(root, dry=False)
            text = f.read_text()
            self.assertIn("  node_type: memory", text)
            self.assertIn("  type: project", text)
            self.assertIn("  status: active", text)
            self.assertEqual(text.count("metadata:"), 1)

    def test_duplicate_same_value_drops_top_level_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "todo_a.md",
                      "---\nname: a\ndescription: d\nmetadata:\n  status: active\n"
                      "status: active\ntype: todo\n---\nbody\n")
            _, conflicts = nf.migrate(root, dry=False)
            self.assertEqual(conflicts, [])
            self.assertEqual(f.read_text().count("status: active"), 1)

    def test_conflicting_duplicate_is_reported_and_file_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "todo_b.md",
                      "---\nname: b\ndescription: d\nmetadata:\n  status: archived\n"
                      "status: active\ntype: todo\n---\nbody\n")
            before = f.read_text()
            changed, conflicts = nf.migrate(root, dry=False)
            self.assertEqual(changed, [])
            self.assertEqual(conflicts, [("todo_b.md", "status")])
            self.assertEqual(f.read_text(), before)

    def test_body_preserved_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = "# Head\n\nText with --- dashes and\ttabs\n\n```\ntype: not-frontmatter\n```\n"
            f = write(root, "arch_c.md", "---\nname: c\ndescription: d\ntype: arch\n---\n" + body)
            nf.migrate(root, dry=False)
            self.assertTrue(f.read_text().endswith("\n---\n" + body))

    def test_flow_list_and_quoted_values_moved_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "feedback_d.md",
                      '---\nname: d\ndescription: "has a colon: here"\ntype: feedback\n'
                      'triggers: ["gh pr merge", "git push"]\n---\nbody\n')
            nf.migrate(root, dry=False)
            text = f.read_text()
            self.assertIn('  triggers: ["gh pr merge", "git push"]', text)
            self.assertIn('description: "has a colon: here"', text)

    def test_past_projects_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "past_projects/project_old.md",
                      "---\nname: old\ndescription: d\ntype: project\ntier: 1\n---\nbody\n")
            before = f.read_text()
            changed, _ = nf.migrate(root, dry=False)
            self.assertEqual(changed, [])
            self.assertEqual(f.read_text(), before)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root, "arch_e.md", "---\nname: e\ndescription: d\ntype: arch\ntier: 1\n---\nbody\n")
            before = f.read_text()
            changed, _ = nf.migrate(root, dry=True)
            self.assertEqual(len(changed), 1)
            self.assertEqual(f.read_text(), before)

    def test_parse_and_resolve_unchanged_by_migration(self):
        """The property that matters: the clerk must read identical values after."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = ('---\nname: n\ndescription: "d: with colon"\ntype: feedback\n'
                   'status: merged\ntier: 0\ntriggers: ["git push"]\n'
                   'last_modified: 1778622504\n---\nbody\n')
            f = write(root, "feedback_f.md", src)
            before_fm = ml.parse_frontmatter(src)
            before_res = ml.resolve(before_fm, "feedback_f.md")
            nf.migrate(root, dry=False)
            after_text = f.read_text()
            self.assertEqual(ml.parse_frontmatter(after_text), before_fm)
            self.assertEqual(ml.resolve(ml.parse_frontmatter(after_text), "feedback_f.md"), before_res)
            self.assertEqual(before_fm["last_modified"], "1778622504")


if __name__ == "__main__":
    unittest.main()
