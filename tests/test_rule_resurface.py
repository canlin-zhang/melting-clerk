import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def run_hook(cmd, root, state_dir, session="s1"):
    env = dict(os.environ, CLAUDE_MEMORY_DIR=str(root), CLERK_STATE_DIR=str(state_dir))
    payload = {"session_id": session, "hook_event_name": "PreToolUse",
               "tool_name": "Bash", "tool_input": {"command": cmd}}
    r = subprocess.run(["python3", "rule_resurface.py"], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=30)
    return r


class TestRuleResurface(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        (self.root / "triggers.json").write_text(json.dumps({"version": 1, "rules": [
            {"pattern": "gh pr merge", "file": "feedback_ci.md",
             "name": "never-merge-without-ci", "reminder": "poll checks to success first"},
            {"pattern": r"git push .*--force(?!-with-lease)", "file": "user_preferences.md",
             "name": "force-with-lease", "reminder": "use --force-with-lease"},
        ]}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_heredoc_body_does_not_fire(self):
        """A commit message quoting a watched command is data, not an invocation."""
        cmd = ("git commit -q -F - <<'MSG'\n"
               "docs: explain the merge gate\n\n"
               "Never run gh pr merge without polling checks first.\n"
               "MSG\n")
        r = run_hook(cmd, self.root, self.state)
        self.assertEqual(r.stdout.strip(), "")

    def test_real_command_after_a_heredoc_still_fires(self):
        cmd = ("cat > notes.txt <<'EOF'\nsome text\nEOF\n"
               "gh pr merge 42\n")
        r = run_hook(cmd, self.root, self.state)
        self.assertIn("never-merge-without-ci", r.stdout)

    def test_unterminated_heredoc_is_left_alone(self):
        """Don't swallow the whole command when the delimiter never closes."""
        cmd = "gh pr merge 42 <<'EOF'\nstill open"
        r = run_hook(cmd, self.root, self.state)
        self.assertIn("never-merge-without-ci", r.stdout)

    def test_match_denies_with_reminder(self):
        r = run_hook("gh pr merge 123 --merge", self.root, self.state)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("poll checks to success first", hso["permissionDecisionReason"])
        self.assertIn("re-run", hso["permissionDecisionReason"])

    def test_second_occurrence_passes(self):
        run_hook("gh pr merge 123", self.root, self.state)
        r = run_hook("gh pr merge 123", self.root, self.state)
        self.assertEqual(r.stdout.strip(), "")   # no output = allow

    def test_different_sessions_independent(self):
        run_hook("gh pr merge 123", self.root, self.state, session="s1")
        r = run_hook("gh pr merge 123", self.root, self.state, session="s2")
        self.assertIn("deny", r.stdout)

    def test_negative_lookahead_force_with_lease_ok(self):
        r = run_hook("git push --force-with-lease origin main", self.root, self.state)
        self.assertEqual(r.stdout.strip(), "")

    def test_bare_force_denied(self):
        r = run_hook("git push --force origin main", self.root, self.state)
        self.assertIn("force-with-lease", r.stdout)

    def test_no_match_no_output(self):
        r = run_hook("ls -la", self.root, self.state)
        self.assertEqual(r.stdout.strip(), "")

    def test_missing_triggers_json_is_silent(self):
        (self.root / "triggers.json").unlink()
        r = run_hook("gh pr merge 1", self.root, self.state)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
