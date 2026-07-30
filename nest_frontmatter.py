#!/usr/bin/env python3
"""One-time migration: move clerk-owned frontmatter fields under `metadata:`.

Only `name` and `description` stay top-level - they belong to Claude Code's
auto-memory, whose serializer models a memory's frontmatter as exactly
{name, description, metadata} and can drop top-level extras when it rewrites
a file. See docs/adr/0004-clerk-fields-nested-under-metadata.md.

Raw text edits: values are moved verbatim (quotes, flow lists) and the body is
byte-preserved. `last_modified` is relocated but never recomputed - it is the
staleness signal. Idempotent: a file with no top-level clerk field is skipped.
A field present both top-level and nested with DIFFERENT values is a conflict;
the file is skipped and reported rather than resolved by guesswork.
"""
import re
import sys
from pathlib import Path

import memorylib as ml

# Emitted in this order when relocated, so output is deterministic.
CLERK_FIELDS = (
    "type",
    "node_type",
    "status",
    "tier",
    "triggers",
    "last_modified",
    "modified",
    "originSessionId",
    "archived",
    "archive_note",
    "note",
    "expected_origin",
)
NATIVE_FIELDS = ("name", "description")
EXCLUDED_DIRS = ("past_projects/",)
KEY_RE = re.compile(r"^(\s*)([A-Za-z_][\w-]*):(.*)$")


def _classify(fmtxt: str):
    """Split a frontmatter block into (top_lines, nested_lines, top_clerk, nested_keys).

    top_lines/nested_lines keep their original text so blanks and comments
    survive; top_clerk maps a relocatable key to its raw value.
    """
    top_lines: list[str] = []
    nested_lines: list[str] = []
    top_clerk: dict[str, str] = {}
    nested: dict[str, str] = {}
    in_metadata = False
    for line in fmtxt.splitlines():
        indented = bool(line) and line[0] in " \t"
        if not indented:
            in_metadata = False
        m = KEY_RE.match(line)
        if m and not indented and m.group(2) == "metadata" and not m.group(3).strip():
            in_metadata = True
            continue
        if in_metadata and indented:
            nested_lines.append(line)
            if m:
                nested[m.group(2)] = m.group(3).strip()
            continue
        if m and not indented and m.group(2) in CLERK_FIELDS:
            top_clerk[m.group(2)] = m.group(3).strip()
            continue
        top_lines.append(line)
    return top_lines, nested_lines, top_clerk, nested


def _rebuild(top_lines, nested_lines, top_clerk) -> str:
    out = [ln for ln in top_lines if ln.strip()]
    out.append("metadata:")
    out.extend(nested_lines)
    for key in CLERK_FIELDS:
        if key in top_clerk:
            out.append(f"  {key}: {top_clerk[key]}")
    return "\n".join(out)


def normalize_text(text: str):
    """Returns (new_text, moved_keys, conflict_keys) for one memory file's text.

    Shared by the one-time sweep and the PostToolUse hook so there is a single
    implementation of the canonical shape. new_text is `text` unchanged when
    there is nothing to move or when a conflict blocks the move.
    """
    m = ml.FM_RE.match(text)
    if not m:
        return text, [], []
    top_lines, nested_lines, top_clerk, nested = _classify(m.group(1))
    if not top_clerk:
        return text, [], []
    clash = sorted(k for k, v in top_clerk.items() if k in nested and nested[k] != v)
    if clash:
        return text, [], clash
    # Same key, same value on both sides: the nested copy already wins.
    moved = [k for k in top_clerk if k not in nested]
    relocate = {k: v for k, v in top_clerk.items() if k in moved}
    new_text = text[: m.start(1)] + _rebuild(top_lines, nested_lines, relocate) + text[m.end(1):]
    return new_text, sorted(moved), []


def migrate(root=None, dry=True):
    """Returns (changed, conflicts): [(relpath, moved_keys)], [(relpath, key)]."""
    root = Path(root or ml.MEMORY_DIR)
    changed: list[tuple[str, list[str]]] = []
    conflicts: list[tuple[str, str]] = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if p.name in ml.SKIP_FILES or rel.startswith(EXCLUDED_DIRS):
            continue
        text = p.read_text(encoding="utf-8")
        new_text, moved, clash = normalize_text(text)
        if clash:
            conflicts.extend((rel, k) for k in clash)
            continue
        if new_text == text:
            continue
        if not dry:
            p.write_text(new_text, encoding="utf-8")
        changed.append((rel, moved))
    return changed, conflicts


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    changed, conflicts = migrate(dry=dry)
    if "--verbose" in sys.argv:
        for rel, moved in changed:
            print(f"{rel}: {', '.join(moved)}")
    for rel, key in conflicts:
        print(f"CONFLICT (skipped) {rel}: `{key}` differs top-level vs nested")
    print(f"{'DRY RUN — ' if dry else ''}{len(changed)} files "
          f"{'would be ' if dry else ''}nested, {len(conflicts)} conflicts")
    sys.exit(1 if conflicts else 0)
