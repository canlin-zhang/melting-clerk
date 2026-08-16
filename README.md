# melting-clerk

Tiered memory for coding agents. A generated index that cannot outgrow its
context budget, a status/tier lifecycle so stale notes stop competing with
current ones, rules that resurface at the moment they apply, and a frontmatter
shape that survives the host rewriting your files.

Named for Dalí's melting clocks — *The Persistence of Memory*, filed and
indexed.

## The problem

Agent memory that is just "a folder of markdown loaded at startup" fails in
three specific ways once the folder gets big:

1. **The index outgrows the context window.** It gets truncated at load, so the
   content you most wanted guaranteed is the content silently dropped.
2. **Stale notes win.** A note from four months ago reads exactly as
   authoritative as one from yesterday, and nothing marks the difference.
3. **Rules loaded at startup aren't applied at the moment of action.** A rule
   about `git push`, read 200 messages ago, is not in effect when the push
   happens.

melting-clerk addresses each directly: a **budgeted, generated index**;
**status and tier** as first-class frontmatter; and **triggers** that re-surface
a rule when a matching command is about to run.

## How it is organised

Three layers, with different portability. This matters if you use more than one
agent harness:

| Layer | Files | Portable? |
| --- | --- | --- |
| **Interface** | `memory_server.py` — MCP server over the store | Any MCP client |
| **Core** | `memorylib.py`, `regen_index.py`, `nest_frontmatter.py`, `memory_cli.py` | Plain Python, no host assumptions |
| **Host adapter** | `session_start.py`, `budget_guard.py`, `clerk_cadence.py`, `rule_resurface.py`, `normalize_memory_write.py`, `session_stop.py`, `skills/` | Claude Code specific |

The adapter is the layer another harness replaces. The core and the MCP server
are not Claude Code specific at all.

**Why ship an MCP server when a host may have its own memory feature?** Because
a host's built-in memory is that host's. An MCP server exposes the same store to
anything that speaks MCP. If your host already reads and writes markdown
memories natively, you may not need the server locally — it is what makes the
store reachable from a harness that has no such feature.

## Install (Claude Code)

```bash
/plugin marketplace add canlin-zhang/melting-clerk
/plugin install melting-clerk
```

The plugin registers the hooks in `hooks/hooks.json` and the MCP server in
`.claude-plugin/plugin.json`. The server runs via `uv run`, which reads its
dependencies from the PEP-723 block in `memory_server.py`.

Prerequisites: Python 3.11+ and `uv` on PATH. For the standalone CLI, install
the entry points with `uv tool install .` (gives `regen-index` and `memory-cli`).

Point it at a store (defaults to `~/.claude/memory`):

```bash
export CLERK_MEMORY_DIR=~/.claude/memory
```

If your host also has a native memory directory setting, point both at the same
path. The clerk curates what is in the store; the host loads it.

## The store

One directory of markdown files. Frontmatter:

```yaml
---
name: never-merge-without-ci
description: One line. This is what lands in the index, so write it to be read there.
metadata:
  type: feedback          # user | feedback | project | todo | reference | arch
  status: active          # active | merged | superseded | archived
  tier: 0                 # 0 = always in context, 1 = on demand
  triggers: ["gh pr merge"]
  last_modified: 1778622504
---

Body. For a rule, include a **How to apply:** line — that is what a trigger
re-surfaces at action time.
```

**Only `name` and `description` belong at the top level.** Everything the clerk
owns goes under `metadata:`. This is not cosmetic: hosts that manage memory
files themselves may model frontmatter as exactly `{name, description,
metadata}` and rewrite it, spreading `metadata` through and dropping top-level
keys they don't recognise. Nesting is what makes your `status` and `tier`
survive that. See `docs/adr/0004`.

## The handoff

A handoff is not a memory — it is one file, `$CLERK_MEMORY_DIR/.handoff.md`, with
no frontmatter, holding where work left off. `session_start.py` reads it and
injects it into the next session along with your active todos, the branch, and
which working copy you are in.

That last part means the hook also carries a small clone registry, which is wider
scope than "memory" strictly needs. It is here because a handoff saying "branch X,
spec at this relative path" is ambiguous when several checkouts of one repo exist.
The registry is data-driven — `expected_origin` lives in `clones.md` itself, so it
tracks whatever repo you point it at, and an empty registry seeds its own first
row. Copy `examples/clones.md` to get started, or delete the file and the hook
degrades to branch, handoff and todos with no error. Reasoning in
`docs/adr/0005`.

Two invariants hold it together, both enforced rather than remembered:

- **`normalize_memory_write.py`** (PostToolUse) moves stray top-level clerk
  fields back under `metadata:` on every write — including writes made by the
  host itself, which is precisely why this cannot live behind a tool call.
- **`regen_index.py`** is the sole writer of `MEMORY.md`. The index is derived
  from frontmatter; hand edits are overwritten by design.

Tier defaults by type — `user`/`feedback`/`project`/`todo` → 0, `arch`/
`reference` → 1 — and any non-active `status` forces tier 1, so a stale note
cannot occupy guaranteed context.

## Commands

```bash
regen-index                                 # regenerate MEMORY.md + triggers.json
memory-cli list [--type T]                  # everything the clerk can see
memory-cli stale --days 90                  # untouched for N days
memory-cli recent --days 7
memory-cli archived [--query Q]
memory-cli hidden                           # on disk, invisible to the clerk
memory-cli health
memory-cli archive <file> --note "why"
```

`hidden` is worth knowing about. A file whose frontmatter is unparseable or has
no `type` appears in no index, no listing and no search — it is present but
unreachable. That is a silent-loss class, so it gets its own command.

Adopting the clerk on an existing store: `python3 migrate_frontmatter.py`
stamps explicit `status`/`tier`, and `python3 nest_frontmatter.py` moves clerk
fields under `metadata:`. Both are idempotent and both default to a dry run;
pass `--apply` when the preview looks right.

## Reading and writing memories

Use your agent's own file tools. Read with Read, write with Write/Edit, delete
with `rm` — the normalizer keeps the frontmatter honest either way. The CLI
exists only for what file tools cannot do: aggregate across the store, and move
a file into the archive with its stamps.

## Tests

```bash
python3 -m unittest discover -s tests -t .   # or: uv run pytest
```

87 tests. The ones worth reading first are in `tests/test_nest_frontmatter.py`:
the property that matters is that the clerk parses identical values before and
after a migration, and that file bodies come through byte-for-byte.

## Limitations, honestly

- **The cadence hook schedules judgement, it does not replace it.** It blocks
  once every N human messages and asks for a filing pass. Whether anything
  useful gets filed is still the agent's call, and "nothing to file" is a valid
  outcome.
- **Rules with no command surface cannot be trigger-resurfaced.** A rule about
  tone or framing has nothing to match on, so it stays always-loaded or it
  stays unenforced.
- **Nothing pushes back on index growth except the budget warning.** Capture is
  automated; consolidation is not. Expect to prune by hand.
- **The host adapter assumes Claude Code's hook contract.** Other harnesses get
  the core and the MCP server, and need their own adapter.
