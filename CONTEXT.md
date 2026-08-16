# melting-clerk

Tiered memory for coding agents, and the vocabulary for splitting the product
into a host-agnostic core and per-host frontends.

## Language

**Store**:
The directory of memory files, `$CLERK_MEMORY_DIR` (default `~/.claude/memory`). Flat markdown, one fact per file, plus a `past_projects/` archive.
_Avoid_: memory folder, database, the memory

**Memory index**:
`MEMORY.md` — the generated pointer file listing the tier-0 memory files. Not a memory file itself, and never hand-edited: the clerk derives it from frontmatter.
_Avoid_: memory file, MEMORY, the index

**Clerk**:
The curation core — the host-agnostic logic that owns the index and the lifecycle. It is the "core logic" later milestones split from the per-host frontends.
_Avoid_: memory system, indexer, the hooks

**Frontend**:
A per-host distribution of the clerk: a host adapter plus its install packaging. The current frontend is Claude Code; a DeepSeek Harness frontend is planned.
_Avoid_: interface, publishing frontend

**Adapter**:
The host-specific bridge code inside a frontend. For Claude Code: the hook scripts and the skills. For DeepSeek Harness: a Cordis plugin.
_Avoid_: glue, host layer

**MCP server**:
`memory_server.py` — exposes the store over MCP. Host-agnostic (any MCP client) but protocol-specific, and currently shipped inside the Claude frontend; whether it becomes its own frontend in the multi-host split is an open question.
_Avoid_: the interface, the server

**Tier**:
Whether a memory is always in context (0) or reachable on demand (1). Defaults by type; any non-active `status` forces tier 1. Orthogonal to `status`.
_Avoid_: priority, level, importance

**Trigger**:
A command pattern declared on a feedback memory that re-surfaces that rule at the moment a matching command is about to run.
_Avoid_: hook, rule match, reminder

**Hidden memory**:
A file present in the store but invisible to the clerk, because its frontmatter is unparseable or has no `type`.
_Avoid_: broken memory, missing memory, orphan

**Stale memory**:
A memory file not modified in more than 90 days. A candidate for archiving, not a verdict.
_Avoid_: old memory, outdated entry, inactive memory

**Tombstone**:
Replacing a superseded memory's body with a pointer to the memory that replaced it, at the moment of supersession.
_Avoid_: delete, deprecate, mark old

## Relationships

- The **memory index** is derived from memory frontmatter by the **clerk**; it is regenerated, never hand-edited
- A **frontend** wraps the **clerk** in an **adapter** plus packaging; the clerk is host-agnostic, the adapter is not
- The **store** is the shared state between the **clerk** and every **adapter** and **MCP server**
- A **stale memory** becomes archived when `memory_cli.py archive` moves it into `past_projects/`
- A non-active `status` forces **tier** 1
- A **hidden memory** is reachable by no command and no index
