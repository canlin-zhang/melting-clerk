---
name: clones
description: Registry of local working copies on this machine, so a handoff can say which checkout it meant.
metadata:
  type: reference
  tier: 1
  expected_origin: your-org/your-repo
---

# Clones

Copy this to `$CLAUDE_MEMORY_DIR/clones.md` and set `expected_origin` above to the
`org/repo` your working copies share. The SessionStart hook resolves the current
`git rev-parse --show-toplevel`, matches it against the Path column, and appends a
row automatically when the origin matches `expected_origin` and the path is new.
The label defaults to the directory basename.

Nothing is hardcoded to a particular repo: change `expected_origin` and it tracks
whatever you point it at. Delete this file entirely and the hook simply stops
reporting a clone - branch, handoff and todos still work.

Two cases still need a manual row: an origin that does not match
`expected_origin`, and a basename that collides with an existing label (two
checkouts both called `app`). The hook leaves those as `<unregistered>` rather
than guessing.

## Registry

| Label | Path |
|-------|------|
