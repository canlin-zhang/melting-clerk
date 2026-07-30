# Stop hook nudges only - never forces a handoff write

The Stop hook prints a one-line reminder if the handoff is stale, but does not write a handoff automatically. Forced writes would produce low-quality handoffs (Claude has no summarization prompt in a hook script), pollute the handoff with every trivial session, and remove user control over what gets preserved. The tradeoff: handoffs only exist when the user runs `/session-wrap`, but those handoffs are intentional and high-quality.
