#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp[cli]",
# ]
# ///
import os
import re
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

MEMORY_DIR = Path(os.environ.get("CLAUDE_MEMORY_DIR", str(Path.home() / ".claude" / "memory")))
HANDOFF_FILE = MEMORY_DIR / ".handoff.md"

mcp = FastMCP("memory")

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def _startup_checks() -> None:
    issues = []
    if not MEMORY_DIR.exists():
        issues.append(f"MEMORY_DIR does not exist: {MEMORY_DIR}")
    elif not (MEMORY_DIR / "MEMORY.md").exists():
        issues.append(f"MEMORY.md missing from {MEMORY_DIR} — wrong directory?")
    else:
        try:
            probe = MEMORY_DIR / ".write_probe"
            probe.write_text("probe")
            probe.unlink()
        except OSError as e:
            issues.append(f"MEMORY_DIR not writable: {e}")

    if issues:
        for issue in issues:
            print(f"[memory-server] WARNING: {issue}", file=sys.stderr)
    else:
        print(f"[memory-server] OK — {MEMORY_DIR}", file=sys.stderr)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


def _resolve_memory_path(filename: str) -> tuple[Path | None, str]:
    """Resolve and validate a memory file path, blocking traversal escapes."""
    if not filename.endswith(".md"):
        filename += ".md"
    path = (MEMORY_DIR / filename).resolve()
    try:
        path.relative_to(MEMORY_DIR.resolve())
    except ValueError:
        return None, f"!!! ERROR !!! {filename} escapes MEMORY_DIR"
    return path, ""


def _all_memory_files() -> list[Path]:
    if not MEMORY_DIR.exists():
        return []
    excluded = {"MEMORY.md", HANDOFF_FILE.name}
    return sorted(f for f in MEMORY_DIR.rglob("*.md") if f.name not in excluded)


def _score(text: str, query: str) -> float:
    """Term-frequency score, weighting frontmatter name/description higher."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return 0.0
    m = _FRONTMATTER_RE.match(text)
    header = m.group(1) if m else ""
    body = text[m.end():] if m else text
    header_lower = header.lower()
    body_lower = body.lower()
    return sum(header_lower.count(w) for w in words) * 3.0 + sum(body_lower.count(w) for w in words) * 1.0


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` atomically via a sibling tmp file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _patch_memory_index(filename: str, index_line: str) -> None:
    """Replace or append an entry for `filename` in MEMORY.md.

    Searches for a Markdown link bullet matching (filename) and replaces it.
    If absent, appends under '### Unsorted' (creates the section if needed).
    """
    index_path = MEMORY_DIR / "MEMORY.md"
    if not index_path.exists():
        return
    text = index_path.read_text()
    lines = text.splitlines(keepends=True)

    # Replace existing line referencing this filename (match Markdown link syntax)
    pattern = re.compile(r"\(" + re.escape(filename) + r"\)")
    for i, line in enumerate(lines):
        if pattern.search(line) and line.strip().startswith("-"):
            lines[i] = index_line + "\n"
            _atomic_write(index_path, "".join(lines))
            return

    # Append under existing ### Unsorted section
    unsorted = "### Unsorted\n"
    idx = next(
        (i + 1 for i, line in enumerate(lines) if line == unsorted),
        None,
    )
    if idx is not None:
        lines.insert(idx, index_line + "\n")
        _atomic_write(index_path, "".join(lines))
        return

    # No Unsorted section: create it at the end
    suffix = "" if text.endswith("\n") else "\n"
    _atomic_write(index_path, text + suffix + f"\n### Unsorted\n{index_line}\n")


@mcp.tool()
def health_check() -> dict:
    """Check that the memory server and its storage are healthy.

    Returns a status dict. Call this to verify the server is alive and writable.
    """
    status: dict = {"server": "memory", "ok": True, "issues": []}

    if not MEMORY_DIR.exists():
        status["issues"].append(f"MEMORY_DIR missing: {MEMORY_DIR}")
        status["ok"] = False
    else:
        status["memory_dir"] = str(MEMORY_DIR)
        files = _all_memory_files()
        status["file_count"] = len(files)
        by_type: dict[str, int] = {}
        for f in files:
            fm, _ = _parse_frontmatter(f.read_text())
            t = fm.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        status["by_type"] = by_type
        archived = list((MEMORY_DIR / "past_projects").glob("*.md")) if (MEMORY_DIR / "past_projects").exists() else []
        status["archived_count"] = len(archived)
        if not (MEMORY_DIR / "MEMORY.md").exists():
            status["issues"].append("MEMORY.md not found — wrong directory?")
            status["ok"] = False
        try:
            probe = MEMORY_DIR / ".write_probe"
            probe.write_text("probe")
            probe.unlink()
            status["writable"] = True
        except OSError as e:
            status["issues"].append(f"not writable: {e}")
            status["writable"] = False
            status["ok"] = False

    status["handoff_exists"] = HANDOFF_FILE.exists()
    return status


@mcp.tool()
def list_memories(type: str = "") -> list[dict]:
    """List project memory files, optionally filtered by type.

    Types: todo, arch, project, reference, feedback, user
    Returns name, description, type, and filename for each entry.
    """
    results = []
    for f in _all_memory_files():
        fm, _ = _parse_frontmatter(f.read_text())
        entry_type = fm.get("type", "")
        if type and entry_type != type:
            continue
        results.append(
            {
                "filename": f.name,
                "name": fm.get("name", f.stem),
                "description": fm.get("description", ""),
                "type": entry_type,
            }
        )
    return results


@mcp.tool()
def list_recent_memories(days: int = 7, type: str = "") -> list[dict]:
    """Return memory files modified within the last N days, newest first.

    Useful for catching up on recent decisions without knowing what to search for.
    Optionally filtered by type.
    """
    cutoff = time.time() - days * 86400
    results = []
    for f in _all_memory_files():
        if f.stat().st_mtime < cutoff:
            continue
        fm, _ = _parse_frontmatter(f.read_text())
        entry_type = fm.get("type", "")
        if type and entry_type != type:
            continue
        results.append(
            {
                "filename": f.name,
                "name": fm.get("name", f.stem),
                "description": fm.get("description", ""),
                "type": entry_type,
                "modified_ago_hours": round((time.time() - f.stat().st_mtime) / 3600, 1),
            }
        )
    results.sort(key=lambda x: x["modified_ago_hours"])
    return results


@mcp.tool()
def list_stale_memories(days: int = 90, type: str = "") -> list[dict]:
    """Return memory files not modified in the last N days, oldest first.

    Excludes MEMORY.md and past_projects/. Used by /memory-audit to surface
    candidates for archiving or merging. Does not take any action.
    """
    cutoff = time.time() - days * 86400
    past_projects_dir = MEMORY_DIR / "past_projects"
    results = []
    for f in _all_memory_files():
        if f.is_relative_to(past_projects_dir):
            continue
        if f.stat().st_mtime > cutoff:
            continue
        fm, _ = _parse_frontmatter(f.read_text())
        entry_type = fm.get("type", "")
        if type and entry_type != type:
            continue
        results.append({
            "filename": f.name,
            "name": fm.get("name", f.stem),
            "description": fm.get("description", ""),
            "type": entry_type,
            "last_modified_days_ago": round((time.time() - f.stat().st_mtime) / 86400, 1),
        })
    results.sort(key=lambda x: x["last_modified_days_ago"], reverse=True)
    return results


_READ_MEMORY_CAP = 20000        # chars
_SEARCH_MAX_FILES = 20          # default cap on files returned with snippets
_SEARCH_LINES_PER_FILE = 20     # max matched lines stored per file


@mcp.tool()
def read_memory(filename: str, offset: int = 0) -> str:
    """Read content of a memory file, with optional offset for pagination.

    Returns up to 20000 chars starting at `offset`. If the file extends beyond
    `offset + 20000`, a loud TRUNCATED header is prepended naming the next
    `offset` value to use to continue reading via MCP.
    """
    path, err = _resolve_memory_path(filename)
    if not path:
        return err
    if not path.exists():
        return (
            f"!!! ERROR !!! {filename} not found in {MEMORY_DIR}. "
            f"Recover: call list_memories() to see available files."
        )
    text = path.read_text()
    total = len(text)
    if offset < 0 or offset >= total:
        return (
            f"!!! ERROR !!! offset={offset} is out of range for {filename} "
            f"(total length: {total} chars). Recover: call read_memory('{filename}') "
            f"with offset in [0, {total - 1}]."
        )
    chunk = text[offset:offset + _READ_MEMORY_CAP]
    end = offset + len(chunk)
    if end >= total:
        return chunk
    return (
        f"!!! TRUNCATED !!! file is {total} chars; returned chars [{offset}, {end}). "
        f"To read the next chunk via MCP: call "
        f"read_memory('{filename}', offset={end}).\n\n"
        + chunk
    )


@mcp.tool()
def search_memories(
    query: str,
    type: str = "",
    case_sensitive: bool = False,
    max_files: int = _SEARCH_MAX_FILES,
) -> dict:
    """Search memory file contents by keyword, optionally filtered by type.

    Results are ranked by term frequency (name/description weighted 3x over body).

    Returns a dict with:
      - "files_searched_count": total memory files scanned (after type filter)
      - "results": top max_files matching files, each with up to 20 matched lines.
        "snippet_truncated" warning string is set when the file had more than 20
        matched lines.
      - "WARNING" / "omitted_files" / "omitted_count" (only when capped):
        loud notice that some matching files were dropped from the result set.
    """
    words = [w for w in query.split() if w]
    if not words:
        return {"files_searched_count": 0, "results": []}
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile("|".join(re.escape(w) for w in words), flags)
    results = []
    files_scanned = 0
    for f in _all_memory_files():
        text = f.read_text()
        fm, _ = _parse_frontmatter(text)
        entry_type = fm.get("type", "")
        if type and entry_type != type:
            continue
        files_scanned += 1
        matched = [line for line in text.splitlines() if pattern.search(line)]
        if matched:
            entry = {
                "filename": f.name,
                "name": fm.get("name", f.stem),
                "type": entry_type,
                "score": _score(text, query.lower()),
                "match_count": len(matched),
                "matches": "\n".join(matched[:_SEARCH_LINES_PER_FILE]),
            }
            if len(matched) > _SEARCH_LINES_PER_FILE:
                entry["snippet_truncated"] = (
                    f"!! SNIPPET TRUNCATED at {_SEARCH_LINES_PER_FILE} lines "
                    f"({len(matched)} total matched lines in this file). "
                    f"Call read_memory('{f.name}') to read the full file."
                )
            results.append(entry)
    results.sort(key=lambda x: x["score"], reverse=True)
    omitted = results[max_files:]
    results = results[:max_files]
    response: dict = {
        "files_searched_count": files_scanned,
        "results": results,
    }
    if omitted:
        response["WARNING"] = (
            f"!!!!!!!!!! RESULTS CAPPED !!!!!!!!!!  {len(omitted)} additional "
            f"file(s) matched but were OMITTED from the result set because "
            f"max_files={max_files}. You are NOT seeing the full picture. "
            f"Recover via MCP: (a) re-call search_memories(query, max_files={max_files * 2}) "
            f"to raise the cap, (b) call search_memories(query, type='feedback') (or 'project', "
            f"'arch', 'reference', 'todo', 'user') to scope by category, or (c) pick a name from "
            f"omitted_files below and call read_memory(name) directly."
        )
        response["omitted_count"] = len(omitted)
        response["omitted_files"] = [r["filename"] for r in omitted]
    return response


@mcp.tool()
def write_memory(filename: str, content: str, index_line: str = "") -> str:
    """Write or update a memory file. Supports subdirectory paths (e.g. past_projects/foo.md).

    Content must include YAML frontmatter with name, description, and type fields.
    Does NOT touch MEMORY.md -- project memories are managed here, not in the index.

    If index_line is provided (format: '- [Title](filename.md) — one-line hook'),
    MEMORY.md is patched: the existing entry for this filename is replaced,
    or the line is appended under '### Unsorted' (created if absent).

    A last_modified timestamp (Unix epoch) is automatically injected into the
    frontmatter on every write, so the memory-audit skill can resolve conflicts.
    """
    path, err = _resolve_memory_path(filename)
    if not path:
        return err
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()

    # Inject last_modified timestamp into frontmatter
    now_ts = str(int(time.time()))
    if content.startswith("---\n"):
        end = content.index("\n---", 4)
        fm_block = content[4:end]
        body = content[end + 4:]
        # Replace existing last_modified line, or append before closing ---
        if "last_modified:" in fm_block:
            import re as _re
            fm_block = _re.sub(r'(^|\n)last_modified:.*', f'\\1last_modified: {now_ts}', fm_block)
        else:
            fm_block += f"\nlast_modified: {now_ts}"
        content = f"---\n{fm_block}\n---{body}"
    else:
        # Bare content without frontmatter — wrap it
        content = f"---\nlast_modified: {now_ts}\n---\n{content}"

    path.write_text(content)
    if index_line:
        _patch_memory_index(filename, index_line)
    return f"{'Updated' if existed else 'Created'}: {path}"


@mcp.tool()
def delete_memory(filename: str) -> str:
    """Delete a memory file. Supports subdirectory paths."""
    path, err = _resolve_memory_path(filename)
    if not path:
        return err
    if not path.exists():
        return (
            f"!!! ERROR !!! {filename} not found. "
            f"Recover: call list_memories() to see available files."
        )
    path.unlink()
    return f"Deleted: {filename}"


@mcp.tool()
def archive_memory(filename: str, note: str = "") -> str:
    """Move a memory file to past_projects/, adding an archived timestamp to its frontmatter.

    Use during defrag to archive completed work in one call instead of read + write + delete.
    Optionally attach a note explaining why it was archived.
    """
    path, err = _resolve_memory_path(filename)
    if not path:
        return err
    if not path.exists():
        return (
            f"!!! ERROR !!! {filename} not found. "
            f"Recover: call list_memories() to see available files."
        )

    content = path.read_text()
    from datetime import date
    stamp = f"archived: {date.today().isoformat()}"
    if note:
        stamp += f"\narchive_note: {note}"

    # Insert archived fields into frontmatter, or wrap bare content
    if content.startswith("---\n"):
        end = content.index("\n---", 4)
        content = content[: end] + f"\n{stamp}" + content[end:]
    else:
        content = f"---\n{stamp}\n---\n{content}"

    dst = MEMORY_DIR / "past_projects" / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content)
    path.unlink()
    return f"Archived: {filename} → past_projects/{filename}"


@mcp.tool()
def list_archived(query: str = "") -> list[dict]:
    """List files in past_projects/, optionally filtered by keyword against name/description.

    Useful for checking whether something has already been investigated or shipped
    before re-doing the work.
    """
    archive_dir = MEMORY_DIR / "past_projects"
    if not archive_dir.exists():
        return []
    q = query.lower()
    results = []
    for f in sorted(archive_dir.glob("*.md")):
        fm, _ = _parse_frontmatter(f.read_text())
        name = fm.get("name", f.stem)
        description = fm.get("description", "")
        if q and q not in name.lower() and q not in description.lower():
            continue
        results.append(
            {
                "filename": f"past_projects/{f.name}",
                "name": name,
                "description": description,
                "archived": fm.get("archived", ""),
                "archive_note": fm.get("archive_note", ""),
            }
        )
    return results


@mcp.tool()
def write_handoff(content: str) -> str:
    """Save a session handoff note for the next session.

    Write a brief summary of where we left off and what's next.
    Overwrites any previous handoff note.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    HANDOFF_FILE.write_text(content)
    return f"Handoff note saved to {HANDOFF_FILE}"


@mcp.tool()
def read_handoff() -> str:
    """Read the handoff note from the previous session.

    Returns the note content, or a message if none exists.
    """
    if not HANDOFF_FILE.exists():
        return "No handoff note found."
    return HANDOFF_FILE.read_text()


if __name__ == "__main__":
    _startup_checks()
    mcp.run()
