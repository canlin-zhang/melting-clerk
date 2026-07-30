---
name: session-wrap
description: End-of-session hygiene: write a handoff, prompt for memory saves, surface stale memories. Use when user is about to close a session, create a PR, or says "wrap up", "session wrap", or "/session-wrap".
---

# Session Wrap

## Step 1 - Write the handoff

Get branch: `git rev-parse --abbrev-ref HEAD`
Get working tree: `git rev-parse --show-toplevel` — worth recording when you keep several clones or worktrees of the same repo, since the next session needs to know which one held the in-progress branch.

Write `$CLAUDE_MEMORY_DIR/.handoff.md` (default `~/.claude/memory/.handoff.md`) with the Write tool, using this structure (see HANDOFF-TEMPLATE.md). It has no frontmatter and is not a memory file — nothing indexes it. A SessionStart hook is expected to read that path and inject it as the next session's opening context.

```
Branch: <branch>
Tree: <path>              # omit when you only ever use one checkout
Last action: <one sentence - what was just completed>
What's next: <1-3 bullets of concrete next steps>
Open failures: <known-failing tests, or "none">
Decisions made: <any architectural or workflow choices worth preserving, or "none">
```

## Step 2 - Prompt for memory saves

Ask once: "Did we make any decisions or learn anything this session worth saving to memory?"

If yes: write the file with the Write tool into `~/.claude/memory/`, frontmatter as `name`, `description`, then a `metadata:` block holding `type` and anything else. Name it `<type>_<slug>.md` — the memory repo decides what is version controlled from that prefix, so a `feedback_`/`user_` file named otherwise lands on the wrong side of it. Then run `python3 ${CLAUDE_PLUGIN_ROOT}/regen_index.py`; it is the sole writer of `MEMORY.md`.

If no: skip - do not ask again.

## Step 3 - Surface stale memories

Run `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py stale --days 90`. If count > 0:
> "There are N memory files older than 90 days. Run /memory-audit to review them."

Do not audit now unless explicitly asked.
