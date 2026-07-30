#!/usr/bin/env python3
"""PreToolUse(Bash) hook: deny-once-per-session rule re-surfacing.

PreToolUse has no non-blocking context channel to Claude (v2.1.165), so the
reminder rides the only channel Claude sees: a deny + reason. The state file
makes it fire once per rule per session — the re-run goes straight through.
The denied command never executes, so there are no side effects.
"""
import json
import re
import sys

import memorylib as ml


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if payload.get("tool_name") != "Bash":
        return
    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return
    triggers_file = ml.MEMORY_DIR / "triggers.json"
    if not triggers_file.exists():
        return
    try:
        rules = json.loads(triggers_file.read_text()).get("rules", [])
    except json.JSONDecodeError:
        return
    session = payload.get("session_id", "unknown")
    state = ml.load_state(session)
    fired = []
    for rule in rules:
        if rule["file"] in state["resurfaced"]:
            continue
        try:
            if re.search(rule["pattern"], command):
                fired.append(rule)
        except re.error:
            continue  # bad pattern in a memory file must not break Bash
    if not fired:
        return
    state["resurfaced"].extend(r["file"] for r in fired)
    ml.save_state(session, state)
    reminders = "; ".join(f"[{r['name']}] {r['reminder']}" for r in fired)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason":
            f"Rule reminder (fires once per session, not an error): {reminders} "
            f"— apply the rule, then re-run the command (it will not be blocked again).",
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a broken hook must never block Bash wholesale
