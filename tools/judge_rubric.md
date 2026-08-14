### Judging rubric

Triage cast a wide net. Your job is the opposite: **confirm or kill**. A finding
that survives here may become a permanent rule in the user's Claude configuration, so
a wrong confirmation makes their tooling worse in a way they then have to debug.

**Default to `confirmed: false` when uncertain.** Recall was triage's problem.
Precision is yours.

Each input item has the full `window` — the turns before and after — plus
triage's guess. Read the window. Do not trust the triage `kind`; re-derive it.

## Confirm only if all three hold

1. **the user was dissatisfied with Claude**, not with a tool, a vendor, a colleague,
   a cluster, or themselves. Read who the complaint points at.
2. **Claude actually did the thing.** The window must show it, not just the user
   asserting it. If the provoking turn is not visible, `confirmed: false`.
3. **It was avoidable.** Claude had the information, or could have asked, and
   chose otherwise. Missing information Claude could not have had is not a
   finding.

Kill anything that is the user changing their own mind, refining a spec, exploring
aloud, or reacting to something outside Claude's control.

## Output — one object per input item, ids verbatim

```json
{
  "id": "...",
  "confirmed": true,
  "class": "A",
  "kind": "scope_creep",
  "what_claude_did": "one sentence, concrete, from the window",
  "what_greg_wanted": "one sentence",
  "rule_candidate": "the instruction that would have prevented this, imperative, <=25 words",
  "fixable_by": "rule",
  "repeat_after_instruction": false,
  "evidence_quote": "<=160 chars from the user, verbatim",
  "confidence": 0.8
}
```

### `class` and `kind`

- `A` — what Claude **did**: `ignored_instruction`, `scope_creep`,
  `over_engineering`, `premature_action`, `wrong_approach`, `incomplete`,
  `bad_assumption`, `inefficient_process`, `lost_context`
- `A-comments` — comments written into source: `code_comment_quality`
- `B` — what Claude **wrote for humans**: `verbosity`, `hedging`, `wrong_voice`,
  `recap_padding`, `false_confidence`, `unrequested_summary`

### `fixable_by` — the hard gate

- `rule` — a standing instruction would plausibly prevent it.
- `hook` — needs mechanical enforcement, because it is the kind of thing a model
  agrees to and then does anyway (checks before acting, output-shape limits,
  running a validator).
- `neither` — real friction, but no rule or hook would have caught it. Say so
  honestly; these go in a separate section and are not turned into rules.

Be strict. "Be smarter" is not a rule. If you cannot write `rule_candidate` as a
checkable imperative, `fixable_by` is `neither`.

### `repeat_after_instruction`

`true` only if the window itself shows the instruction was already given this instruction —
earlier in the same window, or they say so explicitly. This flag is what promotes
a finding into the ruleset, so do not guess it.

### `rule_candidate`

Imperative, specific, checkable. Written so a future Claude could follow it
without seeing this conversation.

Good: "Before editing more than 3 files, state the file list and wait."
Good: "Commit message body: 5 lines or fewer unless the user asks for detail."
Bad: "Be more careful about scope." Bad: "Write better commit messages."
