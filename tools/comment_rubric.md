### Code comment rubric

Each item is a comment Claude added to one of the user's source files, plus the code
immediately below it. Apply the user's test, verbatim from the design session:

> "Does this diff add a comment that describes **what** the code does rather than
> **why**? Does it claim to fix a bug whose premise depends on an **unstated
> condition**?"

Plus their standing expectation: **code comments should be minimal and concise.**

## Verdicts

- `what_not_why` — restates what the code plainly does. If deleting the comment
  loses no information a competent reader could not get from the code in two
  seconds, it is `what_not_why`.
- `unstated_premise` — asserts a fix, a bug, a constraint, or a behaviour whose
  truth depends on something not visible here and not stated. "Guard against the
  race" when no race is described. "Fixes the timeout issue" with no issue named.
- `verbose` — the point is legitimate but takes far more words than needed.
- `stale_narration` — narrates the editing session rather than the code
  ("changed this to...", "now uses...", "as requested", "previously we...").
- `good` — explains why, names a non-obvious constraint, or records a decision
  the code cannot express. Concise.

A comment can have only one verdict. Pick the most serious that applies, in the
order listed above.

## Be honest about `good`

Do not mark comments bad to be helpful. A comment explaining a non-obvious
domain constraint, an ordering requirement, a vendor quirk, or a deliberate
deviation is doing real work even if it is several lines long. The finding here
is the **rate**, and inflating it makes the rate useless.

## Output — one object per input item, ids verbatim

```json
{
  "id": "...",
  "verdict": "what_not_why",
  "why": "one short sentence",
  "suggested": "the comment as it should have been, or \"\" to delete it entirely"
}
```

Every input item gets exactly one output object. Count the input items before you
start and make sure your array length matches. Never drop or merge items.
