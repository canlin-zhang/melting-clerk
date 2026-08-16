import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from clerk_cadence import CADENCE  # derive counts, so raising CADENCE can't stale these tests


def make_transcript(path: Path, n_human: int, n_tool_results: int = 5):
    rows = []
    for i in range(n_human):
        rows.append({"type": "user", "message": {"role": "user", "content": f"human message {i}"}})
        rows.append({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "reply"}]}})
    for _ in range(n_tool_results):
        rows.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "result"}]}})
    rows.append({"type": "user", "message": {"role": "user",
                 "content": "<command-name>/foo</command-name> expansion"}})
    path.write_text("\n".join(json.dumps(r) for r in rows))


def run_hook(transcript, state_dir, session="s1", stop_active=False):
    env = dict(os.environ, CLERK_STATE_DIR=str(state_dir))
    payload = {"session_id": session, "transcript_path": str(transcript),
               "hook_event_name": "Stop", "stop_hook_active": stop_active}
    return subprocess.run(["python3", "clerk_cadence.py"], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)


class TestClerkCadence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.transcript = self.root / "t.jsonl"
        self.state = self.root / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def test_under_cadence_silent(self):
        make_transcript(self.transcript, n_human=CADENCE - 1)
        r = run_hook(self.transcript, self.state)
        self.assertEqual(r.stdout.strip(), "")

    def test_at_cadence_blocks_once_with_instruction(self):
        make_transcript(self.transcript, n_human=CADENCE + 1)
        r = run_hook(self.transcript, self.state)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("Clerk pass", out["reason"])
        # Assert the doctrine, not the prose: filing nothing must stay permissible,
        # and the pass must tell Claude to regenerate the index after edits.
        self.assertIn("Filing nothing", out["reason"])
        self.assertIn("regen_index.py", out["reason"])
        # same count again -> silent (state advanced)
        r2 = run_hook(self.transcript, self.state)
        self.assertEqual(r2.stdout.strip(), "")

    def test_tool_results_and_command_expansions_not_counted(self):
        make_transcript(self.transcript, n_human=CADENCE - 5, n_tool_results=40)
        r = run_hook(self.transcript, self.state)
        # real humans still under cadence despite 40 tool rows
        self.assertEqual(r.stdout.strip(), "")

    def test_stop_hook_active_passes_through(self):
        make_transcript(self.transcript, n_human=60)
        r = run_hook(self.transcript, self.state, stop_active=True)
        self.assertEqual(r.stdout.strip(), "")

    def test_missing_transcript_silent(self):
        r = run_hook(self.root / "nope.jsonl", self.state)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
