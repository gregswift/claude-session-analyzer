# claude-session-analyzer

Evidence-driven ruleset for Claude Code, derived from a sweep of my own
session history for places I corrected the model or it repeated a mistake.

- `tools/` - the extraction and judging pipeline (re-runnable)
- `findings/` - report + machine-readable findings (gitignored; local only)
- `skills/`, `hooks/`, `commands/` - the plugin itself
