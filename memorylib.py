#!/usr/bin/env python3
"""Shared helpers for the memory toolchain (index regen, hooks, migrations).

Frontmatter is parsed with a small line parser instead of PyYAML, because hooks
run on the system python with stdlib only. The store needs just scalars, one
optional `metadata:` nesting level, and lists in either YAML spelling.
"""
import json
import os
import re
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("CLAUDE_MEMORY_DIR", str(Path.home() / ".claude" / "memory")))
STATE_DIR = Path(os.environ.get("CLERK_STATE_DIR", str(Path.home() / ".claude" / "clerk-state")))
FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
# Capture the whole paragraph, not the first line: these wrap, and a line-only
# capture delivers the reminder cut off mid-sentence at action time.
HOW_RE = re.compile(r"\*\*How to apply:\*\*\s*(.+?)(?:\n\s*\n|\n\s*\*\*|\Z)", re.S)

TIER0_TYPES = {"feedback", "user", "project", "todo"}
TYPE_ORDER = {"user": 0, "feedback": 1, "project": 2, "todo": 3, "reference": 4, "arch": 5}
# The index and the handoff live in the store but are not memories.
SKIP_FILES = {"MEMORY.md", ".handoff.md"}

# A ceiling, not a target: the index must fit whole, since a truncated index
# silently drops the entries you most wanted guaranteed. Set it high enough to
# hold every always-loaded rule plus active work-state with headroom, and well
# under wherever your host starts truncating a loaded memory file. Raise it and
# you trade context budget for coverage; lower it and the budget guard starts
# naming demotion candidates instead.
MAX_BYTES = 24 * 1024
MAX_LINES = 150


def _scalar(raw: str) -> str:
    """Unquote a YAML scalar, honouring JSON escapes so `\\\\b` stays one backslash."""
    if len(raw) > 1 and raw[0] == raw[-1] == '"':
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw.strip("\"'")


def parse_frontmatter(text: str) -> dict:
    """Parse the YAML-ish frontmatter block. Returns {} if absent.

    Handles both type variants in the store (top-level `type:` and
    `metadata:`-nested), scalar values (colons allowed), and lists in BOTH
    YAML spellings: one-line flow (`triggers: ["a", "b"]`) and block
    sequences. The block form is not optional to support - a host that
    manages memory files may re-serialise frontmatter and rewrite a flow
    list into a block sequence, and parsing only flow form drops those keys
    silently, which is how a trigger list disappears without an error.
    """
    m = FM_RE.match(text)
    if not m:
        return {}
    out: dict = {}
    in_metadata = False
    pending_list_key = None  # last key with an empty value: may own block items
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if pending_list_key and stripped.startswith("- "):
            out.setdefault(pending_list_key, []).append(_scalar(stripped[2:].strip()))
            continue
        pending_list_key = None
        indented = line[0] in (" ", "\t")
        if not indented:
            in_metadata = False
        key, sep, val = stripped.partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if key == "metadata" and not val:
            in_metadata = True
            continue
        if indented and not in_metadata:
            continue  # nested under a key we don't track (e.g. node_type blocks)
        if val.startswith("[") and val.endswith("]"):
            try:
                out[key] = json.loads(val.replace("'", '"'))
                continue
            except json.JSONDecodeError:
                pass
        if not val:
            pending_list_key = key
            continue
        out[key] = _scalar(val)
    return out


def resolve(fm: dict, relpath: str) -> tuple[int, str]:
    """Effective (tier, status) for a memory file.

    Defaults: feedback/user/project/todo -> tier 0, arch/reference -> tier 1;
    status active unless an `archived:` stamp or past_projects/ location says
    otherwise. Hard rule: non-active status always forces tier 1.
    """
    status = fm.get("status", "")
    if not status:
        is_archived = "archived" in fm or relpath.startswith("past_projects/")
        status = "archived" if is_archived else "active"
    tier_raw = str(fm.get("tier", ""))
    tier = int(tier_raw) if tier_raw.isdigit() else (0 if fm.get("type") in TIER0_TYPES else 1)
    if status != "active":
        tier = 1
    return tier, status


def walk_memories(root=None) -> list[dict]:
    """All parseable memory files under root, sorted by relpath (determinism)."""
    root = Path(root or MEMORY_DIR)
    out = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if p.name in SKIP_FILES:
            continue
        text = p.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm.get("type"):
            continue  # not a memory entry (regen reports the skip count)
        tier, status = resolve(fm, rel)
        out.append({"file": rel, "fm": fm, "tier": tier, "status": status, "body": text})
    return out


def extract_reminder(entry: dict) -> str:
    """Reminder text for triggers.json: the 'How to apply' paragraph, else description.

    Whitespace is collapsed so a wrapped paragraph arrives as one line, and the
    result is capped - a reminder rides a permission-denial message, where length
    costs attention at exactly the wrong moment.
    """
    m = HOW_RE.search(entry["body"])
    src = m.group(1) if m else entry["fm"].get("description", "")
    return " ".join(src.split())[:300]


def count_human_messages(transcript_path: str) -> int:
    """Count real human prompts in a session transcript JSONL.

    Excludes tool_result-bearing user rows, slash-command expansions
    (<command-name> markers), and meta rows. Tolerates both observed
    envelope shapes: {"type": "user", "message": {...}} and flat
    {"role": "user", ...} rows.
    """
    n = 0
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("isMeta"):
                    continue
                msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
                if rec.get("type") == "user" or msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        if any(isinstance(c, dict) and c.get("type") == "tool_result"
                               for c in content):
                            continue
                        text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                    else:
                        text = str(content)
                    if ("<command-name>" in text or "<local-command-stdout>" in text
                            or not text.strip()):
                        continue
                    n += 1
    except OSError:
        return 0
    return n


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_state(session_id: str) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = STATE_DIR / f"{session_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            pass
    return {"resurfaced": [], "last_clerk_count": 0}


def save_state(session_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(STATE_DIR / f"{session_id}.json", json.dumps(state))
