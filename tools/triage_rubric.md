# Triage rubric

You are classifying turns from the user's Claude sessions to find where **Claude got
it wrong**. Each input item is one turn the user wrote, plus what Claude said
immediately before and after.

Your job is recall-safe filtering, not final judgment. When genuinely torn, keep
the item and lower `confidence`. A later pass re-reads survivors in full context.

## The question

**Did the user's message express dissatisfaction with, correct, redirect, or push
back on what Claude just did or wrote?**

If yes → `is_correction: true`. If the user was answering a question, giving new
information, adding scope themselves, or continuing normally → `is_correction: false`.

### Not corrections (be strict about these)

- Answering a question Claude asked.
- Supplying facts, IDs, paths, or preferences on request.
- Changing their own mind about what they want.
- Reporting that an external thing broke (CI, a vendor, a cluster) with no
  implication Claude caused it.
- Cursing at a third party, a tool, a vendor, or the situation. Profanity alone
  is not a correction — check who it is aimed at.
- Thinking out loud, or narrating what they are seeing.

### Corrections (keep these)

- "No, ..." / "that's not what I asked" / "I told you..." / "why did you..."
- Pointing out Claude did something it was told not to do.
- Rejecting an approach Claude chose.
- Saying output was too long, too hedged, wrong tone, or padded.
- Saying Claude did work that was not asked for, or skipped work that was.
- Silently redoing it themselves, or telling Claude to revert/undo.

## Fields

Return one object per input item:

```json
{
  "id": "<copy verbatim from input>",
  "is_correction": true,
  "class": "A",
  "kind": "scope_creep",
  "repeat_signal": false,
  "confidence": 0.8,
  "quote": "<=140 chars from user_said, verbatim",
  "one_line": "what Claude did wrong, in the user's terms"
}
```

Every input item gets exactly one output object. Never drop or merge items.

### `class`

- `A` — what Claude **did**. Actions, process, approach, scope.
- `A-comments` — specifically about comments Claude wrote in source code.
- `B` — what Claude **wrote for humans**: commit messages, PR bodies, PR replies,
  chat prose. Style, length, tone, voice.

### `kind`

Class A: `ignored_instruction`, `scope_creep`, `over_engineering`,
`premature_action`, `wrong_approach`, `incomplete`, `bad_assumption`,
`inefficient_process`, `lost_context`

Class A-comments: `code_comment_quality`

Class B: `verbosity`, `hedging`, `wrong_voice`, `recap_padding`,
`false_confidence`, `unrequested_summary`

If `is_correction` is false: `kind: "not_a_correction"`, `class: "A"`,
`confidence` reflects how sure you are it is NOT a correction.

### `repeat_signal`

`true` only if the user's own words indicate they had said it before — "I told you",
"again", "I already said", "you keep", "stop doing", "as I said". Do not infer
it from the surrounding turns; a later pass checks history properly.

### `confidence`

0.9+ explicit and unambiguous. 0.6-0.8 clear from context. 0.3-0.5 plausible but
arguable. Below 0.3 means you are guessing - use it rather than dropping.
