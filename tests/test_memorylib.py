import textwrap
import unittest

import memorylib as ml


def fm(s):
    return ml.parse_frontmatter(textwrap.dedent(s))


class TestParseFrontmatter(unittest.TestCase):
    def test_top_level_type(self):
        d = fm("""\
        ---
        name: Memory system discipline
        description: Read memory before acting; a colon: inside is fine
        type: feedback
        last_modified: 1778622504
        ---
        body
        """)
        self.assertEqual(d["type"], "feedback")
        self.assertIn("colon: inside", d["description"])

    def test_nested_metadata_type(self):
        d = fm("""\
        ---
        name: dual-memory-systems
        description: Two stores
        metadata:
          type: feedback
        last_modified: 1778798771
        ---
        """)
        self.assertEqual(d["type"], "feedback")

    def test_flow_list_triggers(self):
        d = fm("""\
        ---
        name: x
        description: y
        type: feedback
        triggers: ["gh pr merge", "git push"]
        ---
        """)
        self.assertEqual(d["triggers"], ["gh pr merge", "git push"])

    def test_block_sequence_triggers(self):
        """A host re-serialising frontmatter turns flow lists into block sequences."""
        d = fm("""\
        ---
        name: x
        description: y
        metadata:
          type: feedback
          triggers:
            - "gh pr merge"
            - "git push"
          last_modified: 1778622504
        ---
        """)
        self.assertEqual(d["triggers"], ["gh pr merge", "git push"])
        # keys after the block sequence must still parse
        self.assertEqual(d["last_modified"], "1778622504")
        self.assertEqual(d["type"], "feedback")

    def test_block_sequence_preserves_regex_escapes(self):
        d = fm("""\
        ---
        name: x
        description: y
        type: feedback
        triggers:
          - "git push .*--force(?!-with-lease)"
          - "\\\\brm\\\\s+-[a-zA-Z]*[rR]"
        ---
        """)
        # a doubled backslash in YAML is one backslash in the compiled pattern
        self.assertEqual(d["triggers"][1], r"\brm\s+-[a-zA-Z]*[rR]")
        self.assertIn("--force(?!-with-lease)", d["triggers"][0])

    def test_unquoted_block_sequence_items(self):
        d = fm("""\
        ---
        name: x
        description: y
        type: feedback
        triggers:
          - gh issue create
          - gh issue comment
        ---
        """)
        self.assertEqual(d["triggers"], ["gh issue create", "gh issue comment"])

    def test_empty_valued_key_is_not_a_list(self):
        d = fm("""\
        ---
        name: x
        description: y
        type: feedback
        note:
        status: active
        ---
        """)
        self.assertEqual(d["status"], "active")
        self.assertNotIn("note", d)

    def test_no_frontmatter(self):
        self.assertEqual(ml.parse_frontmatter("# Just a doc\n"), {})


class TestResolve(unittest.TestCase):
    def test_defaults_by_type(self):
        self.assertEqual(ml.resolve({"type": "feedback"}, "f.md"), (0, "active"))
        self.assertEqual(ml.resolve({"type": "arch"}, "a.md"), (1, "active"))
        self.assertEqual(ml.resolve({"type": "reference"}, "r.md"), (1, "active"))

    def test_past_projects_path_forces_archived(self):
        self.assertEqual(ml.resolve({"type": "project"}, "past_projects/p.md"), (1, "archived"))

    def test_archived_field_forces_archived(self):
        self.assertEqual(
            ml.resolve({"type": "todo", "archived": "2026-04-30"}, "t.md"), (1, "archived"))

    def test_explicit_status_nonactive_forces_tier1(self):
        self.assertEqual(
            ml.resolve({"type": "project", "status": "merged", "tier": "0"}, "p.md"),
            (1, "merged"))

    def test_explicit_tier_respected_when_active(self):
        self.assertEqual(ml.resolve({"type": "arch", "tier": "0"}, "a.md"), (0, "active"))


class TestMigrate(unittest.TestCase):
    def test_stamps_tier_status_preserves_last_modified(self):
        import tempfile
        from pathlib import Path

        import migrate_frontmatter as mig
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "feedback_x.md"
            f.write_text("---\nname: x\ndescription: d\ntype: feedback\nlast_modified: 1778622504\n---\nbody\n")
            changed = mig.migrate(root, dry=False)
            self.assertEqual(changed, [("feedback_x.md", ["status: active", "tier: 0"])])
            text = f.read_text()
            self.assertIn("last_modified: 1778622504", text)   # untouched — staleness data preserved
            self.assertIn("status: active", text)
            self.assertIn("tier: 0", text)
            self.assertEqual(mig.migrate(root, dry=False), [])  # idempotent

    def test_dry_run_writes_nothing(self):
        import tempfile
        from pathlib import Path

        import migrate_frontmatter as mig
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "arch_y.md"
            f.write_text("---\nname: y\ndescription: d\ntype: arch\n---\nbody\n")
            before = f.read_text()
            mig.migrate(root, dry=True)
            self.assertEqual(f.read_text(), before)


if __name__ == "__main__":
    unittest.main()
