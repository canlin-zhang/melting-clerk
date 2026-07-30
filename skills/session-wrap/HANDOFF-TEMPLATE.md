# Handoff Template

```
Branch: feature/retry-backoff
Tree: ~/src/<project>
Last action: Swept frontmatter under metadata: and verified the index renders identically.
What's next:
  - Register the PostToolUse normalizer, after showing the settings block
  - Rewrite the memory skills off the retired MCP tools
Open failures: none
Decisions made: Hooks write to disk directly rather than through MCP - hooks cannot make MCP calls.
```

Keep "Last action" to one sentence. "What's next" must be actionable, not vague.

`Tree:` is the working tree the work happened in (`git rev-parse --show-toplevel`). Omit it if you only ever use one checkout; include it when several clones or worktrees of the same repo are in play, since the next session otherwise cannot tell which one holds the in-progress branch.
