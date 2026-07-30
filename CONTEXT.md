# melting-clerk

Vocabulary for this repo. Use these terms exactly; the alternatives listed under
_Avoid_ blur distinctions that matter.

## Language

**Store**:
The directory of memory files, `$CLAUDE_MEMORY_DIR` (default `~/.claude/memory`). Flat markdown, one fact per file, plus a `past_projects/` archive.
_Avoid_: memory folder, database, the memory

**Memory index**:
`MEMORY.md` — the generated pointer file listing the tier-0 memory files. Not a memory file itself, and never hand-edited: the clerk derives it from frontmatter, so hand edits are discarded on the next regeneration.
_Avoid_: memory file, MEMORY, the index

**Clerk**:
The curation layer that owns the index and the lifecycle — it decides what is always in context, not how memory files are stored or delivered. Distinct from delivery: the host loads the index into each session.
_Avoid_: memory system, indexer, the hooks

**Tier**:
Whether a memory is always in context (0) or reachable on demand (1). Defaults by type; any non-active `status` forces tier 1. Orthogonal to `status` — a tier is about context cost, a status is about truth.
_Avoid_: priority, level, importance

**Trigger**:
A command pattern declared on a feedback memory that re-surfaces that rule at the moment a matching command is about to run, instead of relying on it being loaded at session start.
_Avoid_: hook, rule match, reminder

**Hidden memory**:
A file present in the store but invisible to the clerk, because its frontmatter is unparseable or has no `type`. Distinct from a stale memory (which is visible and old) and from an orphan (an index line with no file).
_Avoid_: broken memory, missing memory, orphan

**Stale memory**:
A memory file not modified in more than 90 days. Surfaced by `memory_cli.py stale`. A candidate for archiving, not a verdict.
_Avoid_: old memory, outdated entry, inactive memory

**Tombstone**:
Replacing a superseded memory's body with a pointer to the memory that replaced it, at the moment of supersession. Enforces newer-wins structurally: search cannot return a stale body that no longer exists.
_Avoid_: delete, deprecate, mark old

## Relationships

- The **memory index** is derived from memory frontmatter by the **clerk**; it is regenerated, never synchronised by hand
- A **stale memory** becomes archived when `memory_cli.py archive` moves it into `past_projects/`
- A non-active `status` forces **tier** 1, so stale content cannot occupy guaranteed context
- A **hidden memory** is reachable by no command and no index — it must be repaired, never archived or deleted
