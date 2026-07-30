#!/usr/bin/env python3
"""PostToolUse hook: hold memory frontmatter in the canonical shape.

Enforcement lives here rather than behind a write tool because Claude Code's
auto-memory writes memory files with `Write`, never through the clerk - so any
invariant guarded by a tool call is simply bypassed. A hook sees every write.

Two jobs, both silent unless something needs saying:
  1. Move clerk-owned fields under `metadata:` (see docs/adr/0004). Normalizes
     in place rather than rejecting: PostToolUse runs after the write, and a
     fixed file beats a complaint about one that already landed.
  2. Warn when a filename prefix disagrees with `type` for feedback/user
     memories - the memory repo's .gitignore keys on that prefix, so a
     mismatch either leaks personal memory into history or hides work memory
     from it. Other type/prefix mismatches are cosmetic and stay silent.
"""
import json
import sys
from pathlib import Path

import memorylib as ml
import nest_frontmatter as nf

# Types whose tracking status is decided by filename prefix in the memory repo.
PREFIX_CRITICAL = ("feedback", "user")


def _target_path(data: dict) -> str:
    response = data.get("tool_response")
    if isinstance(response, dict):
        for key in ("filePath", "file_path"):
            if response.get(key):
                return str(response[key])
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and tool_input.get("file_path"):
        return str(tool_input["file_path"])
    return ""


def _in_memory_store(path: Path) -> bool:
    try:
        path.relative_to(ml.MEMORY_DIR.resolve())
    except ValueError:
        return False
    return True


def _prefix_warning(path: Path, text: str) -> str | None:
    """Only warn when the prefix decides whether the file is tracked."""
    if path.parent.name == "past_projects":
        return None  # archival names are historical (past_pr_*, dated files)
    typ = ml.parse_frontmatter(text).get("type", "")
    prefix = path.name.split("_", 1)[0] if "_" in path.name else ""
    if not typ or prefix == typ:
        return None
    if typ not in PREFIX_CRITICAL and prefix not in PREFIX_CRITICAL:
        return None
    return (f"{path.name}: type `{typ}` but filename prefix `{prefix or '(none)'}`. "
            f"The memory repo tracks by prefix, so rename to `{typ}_*` or fix `type` "
            f"- otherwise this file lands on the wrong side of version control.")


def main() -> None:
    data = json.loads(sys.stdin.read())
    raw = _target_path(data)
    if not raw or not raw.endswith(".md"):
        return
    path = Path(raw).resolve()
    if not _in_memory_store(path) or path.name in ml.SKIP_FILES or not path.is_file():
        return

    text = path.read_text(encoding="utf-8")
    new_text, moved, conflicts = nf.normalize_text(text)
    notes = []
    if conflicts:
        notes.append(f"{path.name}: `{'`, `'.join(conflicts)}` differs top-level vs nested in "
                     f"frontmatter. Left alone - resolve by hand, not by guessing.")
    elif new_text != text:
        path.write_text(new_text, encoding="utf-8")
        notes.append(f"{path.name}: moved {', '.join(moved)} under `metadata:` "
                     f"(top-level clerk fields are droppable by auto-memory).")
    warning = _prefix_warning(path, new_text)
    if warning:
        notes.append(warning)
    if notes:
        print(json.dumps({"systemMessage": " ".join(notes)}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a normalizer must never interrupt the conversation
