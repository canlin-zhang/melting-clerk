#!/usr/bin/env python3
"""SessionStart hook: regen the derived index, warn on budget, clerk-pass on compaction.

Plain stdout from a SessionStart hook is added to Claude's context (verified
v2.1.165). Quiet when healthy. PreCompact cannot reach Claude, so the
post-compaction clerk pass lives here, gated on source == "compact".
"""
import json
import sys

import memorylib as ml
import regen_index as ri


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    ri.regen()
    over, size, nlines, cands = ri.budget_status()
    if over:
        print(f"[memory-budget] Generated MEMORY.md is over budget: {size}B/{nlines}L "
              f"(max {ml.MAX_BYTES}B/{ml.MAX_LINES}L). Demote (status flip or tier: 1) the "
              f"oldest Tier-0 entries: {', '.join(cands)}. "
              f"Do this as a clerk pass early in the session.")
    if payload.get("source") == "compact":
        print(f"[clerk] Compaction just occurred. Run a clerk pass now: file decisions/root-causes "
              f"from the compacted span into {ml.MEMORY_DIR}/ with Write/Edit; flip status on "
              f"memories the work invalidated; refresh {ml.MEMORY_DIR}/.handoff.md if project "
              f"state changed; then run python3 ${{CLAUDE_PLUGIN_ROOT}}/regen_index.py. "
              "Filing nothing is a valid outcome.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a broken guard must never break session start
