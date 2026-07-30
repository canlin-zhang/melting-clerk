---
name: memory-audit
description: Audit memory files for staleness, orphaned index entries, and near-duplicates. Present action list with per-item confirmation. Use when user says "memory audit", "clean up memory", "audit memory", or "/memory-audit".
---

# Memory Audit

## Step 1 - Gather

```bash
cd ~/.claude/scripts
python3 memory_cli.py stale --days 90   # not touched in 90+ days
python3 memory_cli.py list              # every file the clerk can see
python3 memory_cli.py archived          # past_projects/ entries
python3 memory_cli.py hidden            # on disk but invisible to the clerk
```

Add `--json` to any of these when you need to process the output rather than read it.

## Step 2 - Two independent checks (don't conflate)

"Orphan" is **one-way**: an index line in MEMORY.md pointing at a file that doesn't exist. The reverse direction (file on disk that the clerk can't see) is a **different** problem — broken frontmatter — and the file MUST NOT be removed.

### 2a - True orphans (index → missing file)

Verify against the **filesystem**. Run this from `~/.claude/memory/`:

```bash
grep -oE '\([a-zA-Z_/.0-9-]+\.md\)' MEMORY.md | tr -d '()' | sort -u | \
  while read f; do [ -e "$f" ] || echo "MISSING: $f"; done
```

Only paths printed by `MISSING:` are orphans — and since `regen_index.py` derives the index from the frontmatter of files that exist, an orphan can only mean the index is stale (a file was deleted or archived without a regen). The action is therefore `python3 ${CLAUDE_PLUGIN_ROOT}/regen_index.py`, never hand-editing MEMORY.md; hand edits are overwritten on the next regen by design.

### 2b - Hidden files (on disk → invisible to the clerk)

The clerk skips files whose frontmatter is unparseable or has no `type`, so they appear in no index, no listing, and no search:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py hidden
```

These are **not** orphans — the content is real. The action is to **fix the frontmatter** (set `type`, fill `description`), never to delete or archive. Treat them like Step 4's "broken frontmatter" bucket.

## Step 3 - Flag near-duplicates

Scan file names and descriptions for overlapping topics (e.g. `feedback_build.md` + `feedback_build_test.md`). Flag pairs that might be merged.

## Step 4 - Cross-file contradiction detection (project/todo types only)

**Why:** The 90-day staleness check (Step 1) misses recently-modified files whose *content* is stale. The specific failure mode: two project/todo files track the same initiative (same issue #, same PR #, same domain keywords) but one was updated while the other wasn't. The stale file still looks "recent" by mtime but its status claims are wrong. Step 1 would never flag it.

### 4a - Extract project/todo files and their reference sets

Collect the project and todo files (`memory_cli.py list --type project --json`, then `--type todo`). For each file, read the content and extract:

- **Issue references:** `#\d{4,6}` (e.g. `#16329`, `#16568`)
- **PR references:** same pattern, distinguished by context (e.g. "PR #16568", "merged #16568")
- **Status keywords** near each reference: `merged`, `in progress`, `pending`, `next`, `ready to draft`, `not started`, `scoped`, `⏳`, `✅`
- **Branch names:** any branch name pattern (e.g. `chi-flatten-response`, `worktree-chi-e5-c2c-req-pkt`)
- **Domain keywords:** repeated significant nouns across files (e.g. `CHI_state`, `cache_line_state`, `req_pkt`, `CHI_Response`, `is_last`, `packet_fields`)

### 4b - Group files by shared references

Two files belong to the same "topic group" if they share:
- ≥1 issue number, OR
- ≥1 PR number, OR
- ≥3 domain keywords

### 4c - Within each group, compare status claims

For each shared reference (issue #, PR #, or domain term), check whether the two files agree on status:

| Signal | Interpretation |
|--------|---------------|
| File A says "✅ MERGED" or "merged #XXXXX", File B says "⏳ IN PROGRESS" or "next" or doesn't mention it as merged | **Contradiction** — A claims done, B doesn't know |
| File A says "X not started", File B says "X merged" | **Contradiction** |
| File A says "2 of 7 merged", File B lists 7 as merged | **Contradiction** |
| Both agree a PR is merged | OK |
| Both agree a PR is pending | OK (consensus, may both be stale — verify against git separately) |

### 4d - Verify against git for high-confidence resolution

When a contradiction involves PR merge status, run `git log --oneline main | grep -E "#<PR1>|#<PR2>|..."` to determine ground truth. This turns ambiguous contradictions ("does A or B have the correct status?") into actionable items ("A is stale, B is correct" or "both are stale").

### 4e - Flag output

Present contradictions in the action list with the source files and the specific claim difference:

```
CROSS-FILE CONTRADICTIONS:
  [5] project_chi_packet_fields_root_cause_elimination.md says E "IN PROGRESS (2 of 7)",
      E-3 "next"; project_unify_chi_flit_types.md says B thru E-7 "merged".
      Git confirms all E merged. -> update project_chi_packet_fields_root_cause_elimination.md
  [6] file_a.md says PR #16568 "pending"; file_b.md says #16568 "merged".
      Git confirms merged. -> update file_a.md
```

Resolution action: update the stale file(s) to match ground truth. If the user confirms, make the edits.

**Important:** Files that agree on "pending" status may still be *collectively* stale (both written before a merge). The contradiction detector only catches cases where files *disagree*. A separate "verify project/todo status claims against git" sweep would catch consensus-staleness, but that's a heavier operation — don't run it automatically. Offer it as an opt-in: "No contradictions found across N project/todo files. Run full git-verification sweep of all status claims? [y/N]"

## Step 5 - Present action list

```
STALE (>90 days, oldest first):
  [1] arch_clang_format_drift.md (134 days) -> archive?
  [2] feedback_old_workflow.md (98 days) -> archive?

ORPHANED INDEX LINES:
  [3] deleted_file.md -> remove from MEMORY.md?

NEAR-DUPLICATES:
  [4] feedback_build.md + feedback_build_test.md -> merge?

CROSS-FILE CONTRADICTIONS:
  [5] project_chi_packet_fields_root_cause_elimination.md says E "IN PROGRESS (2 of 7)",
      E-3 "next"; project_unify_chi_flit_types.md says B thru E-7 "merged".
      Git confirms all E merged. -> update project_chi_packet_fields_root_cause_elimination.md
```

Ask user to respond with numbers to act on (e.g. "1 3"). Execute one action at a time with confirmation:

- archive -> `python3 ${CLAUDE_PLUGIN_ROOT}/memory_cli.py archive <file> --note "<why>"`
- stale index line -> `python3 ${CLAUDE_PLUGIN_ROOT}/regen_index.py` (never hand-edit MEMORY.md)
- merge -> read both files, Write the merged content, delete the old one
- fix hidden file -> Edit its frontmatter to add `type`/`description`

After any change to memory files, run `regen_index.py` so the index matches. Writes go through the Write/Edit tools; the PostToolUse normalizer keeps frontmatter in the canonical shape, so don't hand-place clerk fields at the top level.

Never batch multiple destructive actions without per-item confirmation.
