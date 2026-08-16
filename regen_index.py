#!/usr/bin/env python3
"""Sole writer of the store's MEMORY.md and triggers.json.

MEMORY.md is a generated artifact: Tier-0 entries get one index line each,
Tier-1 is a single summary line. Deterministic (sorted by type order, then
relpath) and atomic, so concurrent SessionStart hooks can't corrupt it.
"""
import json
from pathlib import Path

import memorylib as ml

HEADER = """# Memory Index (GENERATED — do not hand-edit)

> regen-index owns this file; hand edits are overwritten on every regen.
> Store: $CLERK_MEMORY_DIR/ — Read to read, Write/Edit to write. A PostToolUse
> normalizer keeps clerk fields (type/status/tier/...) under `metadata:`; only
> name and description belong at the top level. Name files `<type>_<slug>.md`.
> Aggregate queries and the archive move: memory-cli
> (list | recent | stale | archived | hidden | health | archive).
> Tier 1 (arch, reference, archived/merged/superseded) has NO lines here —
> reach it with Grep over the store, or `memory-cli list --type <type>`.
> Lifecycle: status active|merged|superseded|archived in frontmatter; flip
> status when reality changes (clerk pass), tombstone superseded bodies.
"""

SECTION_TITLES = {
    "user": "## User",
    "feedback": "## Feedback",
    "project": "## Active Projects",
    "todo": "## Active Todos",
}


def render(entries: list[dict]) -> str:
    t0 = sorted(
        (e for e in entries if e["tier"] == 0),
        key=lambda e: (ml.TYPE_ORDER.get(e["fm"]["type"], 9), e["file"]),
    )
    t1 = [e for e in entries if e["tier"] != 0]
    lines = [HEADER]
    current = None
    for e in t0:
        typ = e["fm"]["type"]
        if typ != current:
            lines.append("")
            lines.append(SECTION_TITLES.get(typ, f"## {typ}"))
            lines.append("")
            current = typ
        name = e["fm"].get("name", e["file"])
        line = f"- [{name}]({e['file']}) — {e['fm'].get('description', '')}"
        lines.append(line[:197] + "..." if len(line) > 200 else line)
    counts: dict[str, int] = {}
    for e in t1:
        counts[e["fm"]["type"]] = counts.get(e["fm"]["type"], 0) + 1
    summary = ", ".join(f"{n} {t}" for t, n in sorted(counts.items()))
    lines += ["", "## Tier 1 (on demand)", "",
              f"{len(t1)} files not indexed here ({summary}) — "
              "Grep or memory_cli.py reaches them.", ""]
    return "\n".join(lines)


def build_triggers(entries: list[dict]) -> dict:
    rules = []
    for e in entries:
        if e["tier"] != 0:
            continue
        for pat in e["fm"].get("triggers", []) or []:
            rules.append({
                "pattern": pat,
                "file": e["file"],
                "name": e["fm"].get("name", e["file"]),
                "reminder": ml.extract_reminder(e),
            })
    rules.sort(key=lambda r: (r["file"], r["pattern"]))
    return {"version": 1, "rules": rules}


def regen(root=None) -> list[dict]:
    root = Path(root or ml.MEMORY_DIR)
    root.mkdir(parents=True, exist_ok=True)
    entries = ml.walk_memories(root)
    ml.write_atomic(root / "MEMORY.md", render(entries))
    ml.write_atomic(root / "triggers.json", json.dumps(build_triggers(entries), indent=1))
    return entries


def budget_status(root=None):
    """(over_budget, bytes, lines, demotion_candidates) for the rendered index."""
    root = Path(root or ml.MEMORY_DIR)
    entries = ml.walk_memories(root)
    text = render(entries)
    size, nlines = len(text.encode()), text.count("\n")
    over = size > ml.MAX_BYTES or nlines > ml.MAX_LINES
    t0 = [e for e in entries if e["tier"] == 0]
    # missing last_modified = unknown age -> sort LAST (never the first demotion suggestion)
    t0.sort(key=lambda e: int(str(e["fm"].get("last_modified", "")) or 2**63))
    return over, size, nlines, [e["file"] for e in t0[:5]]


def main() -> None:
    n = regen()
    over, size, nlines, cands = budget_status()
    suffix = (f" OVER BUDGET — demote candidates: {', '.join(cands)}"
              if over else " (within budget)")
    print(f"regen: {len(n)} entries, MEMORY.md {size}B/{nlines}L{suffix}")


if __name__ == "__main__":
    main()
