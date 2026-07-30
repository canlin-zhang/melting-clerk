#!/usr/bin/env python3
"""Query and lifecycle commands for the memory store, for skills to call via Bash.

Replaces the read-only and lifecycle tools of the retired memory MCP server.
Reading, writing and deleting a memory file need no wrapper - Read, Write and
rm do that, and the PostToolUse normalizer keeps written frontmatter canonical.
What is NOT re-derivable from those is aggregation across the store (list by
type, staleness, archived set) and the archive move, so only those live here.

  memory_cli.py list    [--type T] [--json]
  memory_cli.py recent  [--days 7]  [--type T] [--json]
  memory_cli.py stale   [--days 90] [--type T] [--json]
  memory_cli.py archived [--query Q] [--json]
  memory_cli.py hidden                        # on disk but invisible to the clerk
  memory_cli.py health
  memory_cli.py archive <file> [--note NOTE]
"""
import argparse
import json
import shutil
import sys
import time

import memorylib as ml
import nest_frontmatter as nf

ARCHIVE_DIR = "past_projects"


def _entries(type_filter: str = ""):
    out = []
    for e in ml.walk_memories(ml.MEMORY_DIR):
        if type_filter and e["fm"].get("type") != type_filter:
            continue
        path = ml.MEMORY_DIR / e["file"]
        out.append({
            "file": e["file"],
            "name": e["fm"].get("name", ""),
            "type": e["fm"].get("type", ""),
            "tier": e["tier"],
            "status": e["status"],
            "description": e["fm"].get("description", ""),
            "mtime": path.stat().st_mtime if path.exists() else 0,
        })
    return out


def _age_days(mtime: float) -> int:
    return int((time.time() - mtime) / 86400) if mtime else -1


def _emit(rows, as_json: bool, cols=("age", "tier", "status", "type", "file")):
    if as_json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("(none)")
        return
    for r in rows:
        bits = []
        for c in cols:
            if c == "age":
                bits.append(f"{_age_days(r['mtime']):>4}d")
            else:
                bits.append(str(r.get(c, "")))
        print("  ".join(bits))
    print(f"-- {len(rows)} entries")


def cmd_list(a):
    _emit(sorted(_entries(a.type), key=lambda r: r["file"]), a.json)


def cmd_recent(a):
    cutoff = time.time() - a.days * 86400
    rows = [r for r in _entries(a.type) if r["mtime"] >= cutoff]
    _emit(sorted(rows, key=lambda r: -r["mtime"]), a.json)


def cmd_stale(a):
    cutoff = time.time() - a.days * 86400
    rows = [r for r in _entries(a.type) if 0 < r["mtime"] < cutoff]
    _emit(sorted(rows, key=lambda r: r["mtime"]), a.json)


def cmd_archived(a):
    rows = [r for r in _entries() if r["file"].startswith(ARCHIVE_DIR + "/")]
    if a.query:
        q = a.query.lower()
        rows = [r for r in rows if q in r["name"].lower() or q in r["description"].lower()
                or q in r["file"].lower()]
    _emit(sorted(rows, key=lambda r: r["file"]), a.json)


def cmd_hidden(a):
    """Files on disk that the clerk cannot see - unparseable or type-less frontmatter.

    These are invisible to every other command and to the index, so they are a
    silent-loss class rather than a cosmetic one. Never auto-delete: a hidden
    file is a broken file, not a stale one.
    """
    seen = {e["file"] for e in ml.walk_memories(ml.MEMORY_DIR)}
    on_disk = {p.relative_to(ml.MEMORY_DIR).as_posix()
               for p in ml.MEMORY_DIR.rglob("*.md") if p.name not in ml.SKIP_FILES}
    hidden = sorted(on_disk - seen)
    if a.json:
        print(json.dumps(hidden, indent=1))
    else:
        for f in hidden:
            print(f"  {f}")
        print(f"-- {len(hidden)} hidden (broken or type-less frontmatter)")


def cmd_health(_a):
    rows = _entries()
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    seen = {r["file"] for r in rows}
    on_disk = {p.relative_to(ml.MEMORY_DIR).as_posix()
               for p in ml.MEMORY_DIR.rglob("*.md") if p.name not in ml.SKIP_FILES}
    info = {
        "memory_dir": str(ml.MEMORY_DIR),
        "visible": len(rows),
        "hidden": len(on_disk - seen),
        "tier0": sum(1 for r in rows if r["tier"] == 0),
        "by_type": dict(sorted(by_type.items())),
        "by_status": dict(sorted(by_status.items())),
        "writable": ml.MEMORY_DIR.exists() and ml.MEMORY_DIR.is_dir(),
    }
    print(json.dumps(info, indent=1))


def cmd_archive(a):
    src = (ml.MEMORY_DIR / a.file).resolve()
    try:
        src.relative_to(ml.MEMORY_DIR.resolve())
    except ValueError:
        sys.exit(f"refusing: {a.file} escapes the memory store")
    if not src.is_file():
        sys.exit(f"no such memory: {a.file}")
    if src.parent.name == ARCHIVE_DIR:
        sys.exit(f"already archived: {a.file}")

    text = src.read_text(encoding="utf-8")
    m = ml.FM_RE.match(text)
    if not m:
        sys.exit(f"refusing: {a.file} has no frontmatter to stamp")
    top, nested, top_clerk, _ = nf._classify(m.group(1))
    stamped = [ln for ln in nested
               if not ln.strip().startswith(("status:", "archived:", "archive_note:"))]
    stamped.append("  status: archived")
    stamped.append(f"  archived: {time.strftime('%Y-%m-%d')}")
    if a.note:
        stamped.append(f"  archive_note: {a.note}")
    new_text = text[: m.start(1)] + nf._rebuild(top, stamped, top_clerk) + text[m.end(1):]

    dest_dir = ml.MEMORY_DIR / ARCHIVE_DIR
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        sys.exit(f"refusing: {dest.relative_to(ml.MEMORY_DIR)} already exists")
    src.write_text(new_text, encoding="utf-8")
    shutil.move(str(src), str(dest))
    print(f"archived {a.file} -> {ARCHIVE_DIR}/{src.name}")
    print("run regen_index.py to refresh the index")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Query and lifecycle commands for the memory store.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, days=None):
        s = sub.add_parser(name)
        s.set_defaults(fn=fn)
        s.add_argument("--json", action="store_true")
        if name in ("list", "recent", "stale"):
            s.add_argument("--type", default="")
        if days is not None:
            s.add_argument("--days", type=int, default=days)
        return s

    add("list", cmd_list)
    add("recent", cmd_recent, days=7)
    add("stale", cmd_stale, days=90)
    s = add("archived", cmd_archived)
    s.add_argument("--query", default="")
    add("hidden", cmd_hidden)
    add("health", cmd_health)
    s = sub.add_parser("archive")
    s.set_defaults(fn=cmd_archive)
    s.add_argument("file")
    s.add_argument("--note", default="")

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
