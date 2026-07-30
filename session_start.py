#!/usr/bin/env python3
"""SessionStart hook: inject focused context block into each session.

Delivers the handoff and active todos into the new session, plus the branch and
which checkout it is. The clone registry is data-driven: `clones.md` declares its
own `expected_origin`, so this tracks working copies of whatever repo you point
it at - see docs/adr/0005 for why a registry rides along with the memory store.
"""
import os
import re
import subprocess
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("CLAUDE_MEMORY_DIR", str(Path.home() / ".claude" / "memory")))
HANDOFF_FILE = MEMORY_DIR / ".handoff.md"
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def _get_branch() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _git_run(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _short_repo(remote_url: str) -> str:
    """Extract 'org/repo' from common git remote URL forms."""
    if not remote_url:
        return ""
    url = remote_url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "://" in url:                       # https://host/org/repo
        tail = url.split("://", 1)[1]
        parts = tail.split("/", 1)
        return parts[1] if len(parts) == 2 else tail
    if "@" in url and ":" in url:          # git@host:org/repo
        return url.split(":", 1)[1]
    return url


_CLONE_ROW_RE = re.compile(r"\|\s*([A-Za-z0-9_.-]+)\s*\|\s*`([^`]+)`\s*\|")


_CLONE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _read_clones_registry() -> tuple[str, list[str], dict[Path, str], int] | None:
    """Parse clones.md. Returns (text, lines, path_to_label, insert_after_idx).

    insert_after_idx is the line to append a new row below: the last data row, or
    the table separator when the table has a header but no rows yet - otherwise a
    fresh registry could never auto-populate its first entry. -1 means no table.
    """
    registry = MEMORY_DIR / "clones.md"
    if not registry.exists():
        return None
    text = registry.read_text()
    lines = text.splitlines()
    path_to_label: dict[Path, str] = {}
    last_data_idx = -1
    for i, line in enumerate(lines):
        m = _CLONE_ROW_RE.match(line)
        if not m:
            continue
        row_label, path_str = m.group(1), m.group(2)
        if row_label.lower() == "label":
            continue
        try:
            path_to_label[Path(path_str).expanduser().resolve()] = row_label
        except Exception:
            continue
        last_data_idx = i
    if last_data_idx < 0:
        for i, line in enumerate(lines):
            if _CLONE_SEP_RE.match(line):
                last_data_idx = i
                break
    return text, lines, path_to_label, last_data_idx


def _get_expected_origin() -> str:
    """Extract metadata.expected_origin from clones.md frontmatter, or '' if absent."""
    registry = MEMORY_DIR / "clones.md"
    if not registry.exists():
        return ""
    text = registry.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        s = line.strip()
        if s.startswith("expected_origin:"):
            return s.split(":", 1)[1].strip()
    return ""


def _try_auto_register(top_path: Path, remote_short: str) -> str | None:
    """Append a row for (top_path, remote_short) if eligible. Returns the new label or None.

    Eligible iff: clones.md exists, remote_short matches metadata.expected_origin,
    top_path isn't already in the registry, and the derived label (basename of top_path)
    doesn't collide with an existing row.
    """
    if not remote_short:
        return None
    expected = _get_expected_origin()
    if not expected or expected != remote_short:
        return None
    parsed = _read_clones_registry()
    if parsed is None:
        return None
    _, lines, path_to_label, last_data_idx = parsed
    if last_data_idx < 0 or top_path in path_to_label:
        return None
    label = top_path.name
    if label in path_to_label.values():
        return None  # collision; defer to manual fix
    new_row = f"| {label} | `{top_path}` |"
    lines.insert(last_data_idx + 1, new_row)
    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    try:
        (MEMORY_DIR / "clones.md").write_text(new_text)
        return label
    except Exception:
        return None


def _get_current_clone() -> tuple[str, str, str, bool] | None:
    """Return (label, toplevel, remote_short, auto_registered) for the current git repo, or None.

    Authoritative: uses `git rev-parse --show-toplevel` and `git remote get-url origin`
    rather than string-matching CWD. label comes from the clones.md row whose path equals
    the resolved toplevel; auto-registers when origin matches metadata.expected_origin and
    toplevel is new; "<unregistered>" otherwise. auto_registered is True only when the row
    was appended this run.
    """
    toplevel = _git_run("rev-parse", "--show-toplevel")
    if not toplevel:
        return None
    try:
        top_path = Path(toplevel).resolve()
    except Exception:
        return None

    remote_short = _short_repo(_git_run("remote", "get-url", "origin") or "")

    parsed = _read_clones_registry()
    if parsed is not None:
        _, _, path_to_label, _ = parsed
        if top_path in path_to_label:
            return (path_to_label[top_path], str(top_path), remote_short, False)

    new_label = _try_auto_register(top_path, remote_short)
    if new_label:
        return (new_label, str(top_path), remote_short, True)
    return ("<unregistered>", str(top_path), remote_short, False)


def _get_todos() -> list[tuple[str, str]]:
    if not MEMORY_DIR.exists():
        return []
    todos = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            text = f.read_text().lstrip("﻿")
            m = _FM_RE.match(text)
            if not m:
                continue
            fm: dict[str, str] = {}
            for line in m.group(1).splitlines():
                if ": " in line:
                    k, v = line.split(": ", 1)
                    fm[k.strip()] = v.strip()
            if fm.get("type") == "todo":
                todos.append((f.name, fm.get("description", f.stem)))
        except Exception:
            continue
    return todos


def _get_handoff() -> str | None:
    try:
        return HANDOFF_FILE.read_text().strip() if HANDOFF_FILE.exists() else None
    except Exception:
        return None


def main() -> None:
    lines = ["=== SESSION CONTEXT ==="]

    branch = _get_branch()
    if branch:
        lines.append(f"Branch: {branch}")

    clone = _get_current_clone()
    if clone:
        label, top, remote, auto_added = clone
        bits = [label, f"at {top}"]
        if remote:
            bits.append(f"[origin: {remote}]")
        if auto_added:
            bits.append("(auto-registered)")
        elif label == "<unregistered>":
            bits.append("— origin doesn't match expected_origin; "
                        f"edit {MEMORY_DIR / 'clones.md'} to add a row")
        lines.append("Clone: " + " ".join(bits))

    handoff = _get_handoff()
    if handoff:
        lines += ["", "Handoff:", handoff]

    todos = _get_todos()
    if todos:
        lines += ["", "Active todos:"]
        for fname, desc in todos:
            lines.append(f"- {fname}: {desc}")

    lines.append("======================")
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Never fail loudly - hook output is context, not gating
