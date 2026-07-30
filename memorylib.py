#!/usr/bin/env python3
"""Shared helpers for the curated-memory toolchain (regen, hooks, migration).

Frontmatter is parsed with a small line parser instead of PyYAML: hooks run on
the system python (3.11, stdlib only), and the store uses just scalars, one
optional `metadata:` nesting level, and one-line flow lists.
"""
import json
import os
import re
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("CLAUDE_MEMORY_DIR", str(Path.home() / ".claude" / "memory")))
STATE_DIR = Path(os.environ.get("CLERK_STATE_DIR", str(Path.home() / ".claude" / "scripts" / ".clerk_state")))
FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
HOW_RE = re.compile(r"\*\*How to apply:\*\*\s*(.+)")

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


def parse_frontmatter(text: str) -> dict:
    """Parse the YAML-ish frontmatter block. Returns {} if absent.

    Handles both type variants in the store (top-level `type:` and
    `metadata:`-nested), scalar values (colons allowed), and one-line
    flow lists like `triggers: ["a", "b"]`.
    """
    m = FM_RE.match(text)
    if not m:
        return {}
    out: dict = {}
    in_metadata = False
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        indented = line[0] in (" ", "\t")
        if not indented:
            in_metadata = False
        key, sep, val = line.strip().partition(":")
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
        out[key] = val.strip("\"'")
    return out


def resolve(fm: dict, relpath: str) -> tuple[int, str]:
    """Effective (tier, status) for a memory file.

    Defaults: feedback/user/project/todo -> tier 0, arch/reference -> tier 1;
    status active unless an `archived:` stamp or past_projects/ location says
    otherwise. Hard rule: non-active status always forces tier 1.
    """
    status = fm.get("status", "")
    if not status:
        status = "archived" if ("archived" in fm or relpath.startswith("past_projects/")) else "active"
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
    """Reminder text for triggers.json: first 'How to apply' line, else description."""
    m = HOW_RE.search(entry["body"])
    src = m.group(1).strip() if m else entry["fm"].get("description", "")
    return src[:300]


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
                        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                            continue
                        text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                    else:
                        text = str(content)
                    if "<command-name>" in text or "<local-command-stdout>" in text or not text.strip():
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
