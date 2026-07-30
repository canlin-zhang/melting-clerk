# The session hook carries a clone registry, which is scope this project otherwise wouldn't claim

`session_start.py` delivers the handoff and active todos into a new session -
squarely memory's job, and the piece without which a handoff is written and never
read. It also resolves which working copy the session is in, against a
`clones.md` registry in the store. That second job is not memory, and shipping it
here is a deliberate widening of scope.

The reason is that the handoff needs it. A handoff says "branch X, spec at this
relative path", and when several clones or worktrees of one repo exist, that is
ambiguous - the next session cannot tell which checkout held the branch. So the
registry exists to make handoffs unambiguous, which makes it memory-adjacent
rather than unrelated. It is also small: a table, an `expected_origin` in the
registry's own frontmatter, and auto-registration by basename when a new working
tree's origin matches.

The registry is deliberately data-driven, not hardcoded to any repo:
`expected_origin` is read from `clones.md`, so it tracks working copies of
whatever you point it at. An empty registry self-seeds its first row - requiring
a hand-added row before auto-registration would work is a trap that looks like a
broken feature on first run.

The alternative was to ship no SessionStart hook and document that the host must
deliver the handoff itself. That was rejected: it leaves the product defining a
handoff format with nothing that reads it, which is a worse kind of incomplete
than a slightly wide scope. If you want the delivery without the registry, delete
`clones.md` and the clone line disappears - the hook degrades to branch, handoff
and todos, with no error.
