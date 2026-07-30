#!/usr/bin/env python3
"""Stop hook: nudge user if handoff not updated this session."""
import os
import time
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("CLAUDE_MEMORY_DIR", str(Path.home() / ".claude" / "memory")))
HANDOFF_FILE = MEMORY_DIR / ".handoff.md"
_THRESHOLD = 600  # 10 minutes


def main() -> None:
    if not HANDOFF_FILE.exists():
        print("[session-wrap] No handoff written - run /session-wrap to preserve context for next session")
        return
    if time.time() - HANDOFF_FILE.stat().st_mtime > _THRESHOLD:
        print("[session-wrap] Handoff not updated this session - run /session-wrap to preserve context")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
