#!/usr/bin/env python3
"""Stop hook: clerk pass every CADENCE human messages.

If you run another Stop hook on a message-count cadence, offset this one so the
two never fire on the same turn. stop_hook_active passthrough prevents block
loops (Claude Code >= 2.1.165 contract).
"""
import json
import os
import sys

import memorylib as ml

# Enforcement is behavioural - file deltas as state lands - not frequency; 25 fired too often.
CADENCE = 50

CLERK_INSTRUCTION = (
    f"Clerk pass (fires only every 50 human messages — rare, so do NOT skip it). You MUST review "
    f"the recent stretch and update memory NOW: (1) file every material decision, root cause, and "
    f"rule-worthy feedback into {ml.MEMORY_DIR}/ with the Write/Edit tools (small targeted edits, "
    f"not slow full rewrites); name files `<type>_<slug>.md` and keep clerk fields under "
    f"`metadata:`; a NEW project memory is a pointer — issue number, one state line, and only what "
    f"`gh issue view` cannot tell you (worktree, branch, scratch paths, "
    f"decisions never written up); "
    f"file a todo as an issue, not as a memory; (2) flip `status:` on any memory this session "
    f"invalidated (PR merged -> status: "
    f"merged; superseded -> tombstone the body); (3) refresh the handoff at "
    f"{ml.MEMORY_DIR}/.handoff.md if project state changed; (4) if you changed memory files, run: "
    f"python3 ${{CLAUDE_PLUGIN_ROOT}}/regen_index.py. Filing nothing is acceptable ONLY if nothing "
    f"material changed since the last pass — and you must say so explicitly, never punt a real "
    f"update. Then finish your reply normally."
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if payload.get("stop_hook_active"):
        return
    transcript = payload.get("transcript_path", "")
    if not transcript or not os.path.exists(transcript):
        return
    n = ml.count_human_messages(transcript)
    session = payload.get("session_id", "unknown")
    state = ml.load_state(session)
    if n - state.get("last_clerk_count", 0) >= CADENCE:
        state["last_clerk_count"] = n
        ml.save_state(session, state)
        print(json.dumps({"decision": "block", "reason": CLERK_INSTRUCTION}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a broken cadence hook must never wedge session stop
