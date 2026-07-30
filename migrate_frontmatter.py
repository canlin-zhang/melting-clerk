#!/usr/bin/env python3
"""One-time migration: stamp explicit status/tier into every memory file.

Raw text edits only — the `last_modified` frontmatter field is deliberately
NOT bumped (it is the staleness signal; rewriting it would destroy the data
the redesign exists to use). Idempotent: files already stamped are skipped.
"""
import sys
from pathlib import Path

import memorylib as ml


def migrate(root=None, dry=True) -> list[tuple[str, list[str]]]:
    root = Path(root or ml.MEMORY_DIR)
    changed = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if p.name in ml.SKIP_FILES:
            continue
        text = p.read_text(encoding="utf-8")
        m = ml.FM_RE.match(text)
        fm = ml.parse_frontmatter(text)
        if not m or not fm.get("type"):
            continue
        tier, status = ml.resolve(fm, rel)
        add = []
        if "status" not in fm:
            add.append(f"status: {status}")
        if "tier" not in fm:
            add.append(f"tier: {tier}")
        if not add:
            continue
        new_text = text[: m.end(1)] + "\n" + "\n".join(add) + text[m.end(1):]
        if not dry:
            p.write_text(new_text, encoding="utf-8")
        changed.append((rel, add))
    return changed


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    changed = migrate(dry=dry)
    for rel, add in changed:
        print(f"{rel}: {', '.join(add)}")
    print(f"{'DRY RUN — ' if dry else ''}{len(changed)} files {'would be' if dry else ''} stamped")
