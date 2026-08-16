---
name: memory-defrag
description: Use when user says "defrag your memory" or similar, or when the memory index (MEMORY.md) has grown unwieldy with redundant, stale, or overlapping entries
---

# Memory Defrag

Audit, merge, trim, and reorganize the memory system, then clean up stale session artifacts across `~/.claude`.

## Trigger

User says "defrag your memory", "clean up memory", or similar.

## Routine

### 1. Read everything

- `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py list --json` for every file with name/type/tier/status/description
- Read each file's full content with the Read tool
- Skip `past_projects/` subdirectory entries
- Note total active file count

Also run `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py hidden` — files with broken or missing `type` appear in no listing, so a defrag driven only by the listing will silently skip them.

### 1.5. GitHub PR/Issue audit (project + todo files only)

For every **project** and **todo** file (skip arch, feedback, reference, user, and **past_projects/** — archived files are archived for a reason; their refs are already decided):

1. **Extract** all GitHub references from the file content. Three forms are recognized:

| Form | Example | Repo resolution |
|------|---------|-----------------|
| Bare `#NNNNN` | `#16357` | Your default repo — the one most memories refer to. Resolve it once with `gh repo set-default` or take it from the working tree's `origin`. |
| Qualified `org/repo#NNNNN` | `<org>/<repo>#5` | Explicit repo from the qualifier |
| Full URL | `github.com/<org>/<repo>/pull/16292` | Parsed from URL path |

Regex to capture all three: `(?:([\w.-]+/[\w.-]+)#|github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/)(\d+)|(?<![\/\w.-])#(\d{4,})`

2. **Deduplicate** into a unique set of `(repo, number)` pairs across all scanned files. Bare refs get the default repo; qualified/URL refs carry their own repo.

3. **Batch-check status** via `gh`. For each `(repo, number)` pair:

```bash
# PR check (try first — most refs in memory are PRs):
gh pr view --repo <repo> <number> --json state,closed --jq '"PR \(.state)"' 2>/dev/null

# Fallback — issue check (if not a PR):
gh issue view --repo <repo> <number> --json state --jq '"ISSUE \(.state)"' 2>/dev/null
```

Fire these in parallel for all unique `(repo, number)` pairs. Collect into a map: `repo#NNNNN → status`.

4. **Build a closure table** — for each file, list its refs and their statuses (bare refs imply the default repo):

```
file → [#16357: PR MERGED, #16380: PR MERGED, #16406: PR MERGED]     — ALL CLOSED
file → [<org>/<repo>#5: PR MERGED, #16329: ISSUE OPEN]              — OPEN REMAIN
```

5. **Flag archive candidates.** If ALL refs in a file are closed/merged, surface it prominently in the classification step as a candidate for ARCHIVE.

**This is a signal, not a verdict.** A file with all-closed refs may still track active follow-up work with no issue number yet, or be a living spec that's still relevant despite its referenced PRs being done. The classification step (step 2) still applies human judgment — this audit just surfaces candidates the human might miss and saves clicking through GitHub pages to check each one manually.

### 2. Classify each file

Use the closure table from step 1.5 to inform classification. Files where all refs are closed/merged are ARCHIVE candidates, but still verify: does the file describe remaining TODOs, open design questions, or ongoing context not captured by an issue number?

| Action | Criteria | What to do |
|--------|----------|------------|
| **DELETE** | Fully redundant with another file | `rm` the file |
| **MERGE** | Two+ files covering the same topic with overlapping content | Write combined content to one file, delete originals |
| **FOLD** | Small file whose content fits naturally into an existing larger file | Edit content into the larger file, delete the small one |
| **ARCHIVE** | Completed project (all PRs merged, no remaining TODOs) | `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py archive <file> --note "<why>"` — moves to past_projects/ and stamps frontmatter in one call |
| **KEEP** | Still relevant, no overlap, right level of detail | No changes |

There is no TRIM action for project files. Existing active project files keep their full merged PR details.

New project files are pointers by convention — issue number, one state line, and the local context an issue cannot hold. They are *supposed* to be thin. Never flag one as under-detailed or "enrich" it by copying issue content back in; that is the shape working as intended.

### 2.5. TRIM: soft size target for feedback and reference files

**Guideline, not a rule.** Feedback and reference files should target under ~100 lines. The value is the rule + one canonical incident per distinct failure mode. Multiple incidents illustrating the same root cause are dead weight — keep the best one, drop the rest. Don't pad to hit 100 and don't amputate below it if the content earns its length.

When a feedback/reference file exceeds ~100 lines, check:
1. Are there duplicate incidents making the same point? Keep the strongest, cut the rest.
2. Does every remaining incident illustrate a distinct failure mode? If two blur together, merge them.
3. Is there prose that restates the rule the title already captures? Cut it.

Apply judgment — a 120-line file with 5 tight, distinct anti-patterns is fine. A 90-line file with 3 examples of the same thing should still be trimmed.

### 3. Present plan, then execute

Show a summary table: `file -> action -> reason`. **Get user approval before making changes.**

After approval, execute the approved changes with Write/Edit/`rm`, and ARCHIVE via `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py archive`. Then run `python3 ${CLAUDE_PLUGIN_ROOT}/regen_index.py` — it is the sole writer of `MEMORY.md`, which is derived from frontmatter; never write that file by hand, since the next regen discards hand edits.

Don't hand-place clerk fields (`type`, `status`, `tier`, `last_modified`) at the top level of frontmatter. They belong under `metadata:`, and the PostToolUse normalizer moves them there anyway — which means a file you just wrote may differ from what you wrote, so re-read before a follow-up edit.

### 4. Verify memory defrag

Run `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py health` and report before/after counts. Check that `hidden` did not grow — a rise there means a write left frontmatter unparseable.

### 5. Clean up stale session artifacts

Remove conversation artifacts older than 10 days from `~/.claude`. This step runs automatically after memory defrag.

**What gets cleaned (older than 10 days):**

| Directory | Contents | Find pattern |
|-----------|----------|-------------|
| `~/.claude/file-history/<uuid>/` | Per-session file edit history | `-maxdepth 1 -type d -mtime +10` |
| `~/.claude/session-env/<uuid>/` | Per-session environment snapshots | `-maxdepth 1 -type d -mtime +10` |
| `~/.claude/plans/*.md` | Session plan files | `-maxdepth 1 -name '*.md' -mtime +10` |
| `~/.claude/shell-snapshots/` | Shell state snapshots | `-maxdepth 1 -type f -mtime +10` |
| `~/.claude/telemetry/` | Failed telemetry events | `-maxdepth 1 -type f -mtime +10` |
| `~/.claude/projects/*/[uuid]/` | Per-session tool-results | UUID dirs with `tool-results/` subdir, `-mtime +10` |

**Commands:**

```bash
find ~/.claude/file-history/ -maxdepth 1 -mindepth 1 -type d -mtime +10 -exec rm -rf {} +
find ~/.claude/session-env/ -maxdepth 1 -mindepth 1 -type d -mtime +10 -exec rm -rf {} +
find ~/.claude/plans/ -maxdepth 1 -name '*.md' -mtime +10 -delete
find ~/.claude/shell-snapshots/ -maxdepth 1 -type f -mtime +10 -delete
find ~/.claude/telemetry/ -maxdepth 1 -type f -mtime +10 -delete
find ~/.claude/projects/ -mindepth 2 -maxdepth 2 -type d -mtime +10 \
  -exec test -d {}/tool-results \; -exec rm -rf {} +
```

**What is NEVER cleaned:**
- `$CLERK_MEMORY_DIR/` (canonical memory store)
- `~/.claude/sessions/` (session metadata)
- `~/.claude/settings.json`, `.credentials.json`, `policy-limits.json` (config)
- `~/.claude/skills/`, `~/.claude/plugins/` (user assets); spec PDFs live at `~/specs/` (outside `~/.claude/`)
- `~/.claude/mcp/` (MCP servers, databases)
- `~/.claude/ide/` (IDE state)
- The current session's UUID directories

**Report format:** Show before/after disk usage for `~/.claude` and per-directory counts of removed items.

## Rules

### CAN modify (via MCP tools)

- **Feedback files**: merge duplicates, fold small ones, delete if fully redundant
- **Project files**: archive to `past_projects/` if all work is done
- **Reference files**: merge closely related references
- **MEMORY.md**: regenerate with `python3 ${CLAUDE_PLUGIN_ROOT}/regen_index.py` (the sole writer — never hand-edit)

### CANNOT modify

- **`past_projects/` folder**: never touch, read, modify, or reorganize during defrag. Permanent archive.
- **User files** (`user_*.md`): only add to, never remove content without asking
- **File content accuracy**: never rewrite a memory to say something different from what the user originally conveyed
- **Merged PR details in active project files**: never trim; only move to `past_projects/` when archiving the entire file

### ASK first

- Whether a project with partial TODOs is "done enough" to archive
- Whether two similar feedback files express different rules
- Whether a large codebase note should be split or kept monolithic
