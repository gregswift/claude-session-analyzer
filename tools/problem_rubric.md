### Problem-grouping rubric

You are given every confirmed episode of ONE failure kind. Group them into
distinct **problems**.

A kind is a category. It has no checkable action in it, so no rule can be written
against it. A problem is specific enough that a rule can be written, and that
rule is the deliverable.

## The test for "same problem"

**Would one rule, written once, have prevented both episodes?**

If yes, same problem. If preventing them needs two different instructions, they
are two problems even when they share a kind, a theme, or a vocabulary.

Worked example, both from `unverified_premise`:

- *"proposed CI-auth workarounds premised on CI running applies, when CI only runs preview"*
- *"built an access-model recommendation on the premise that CI applies the stack, when CI only runs preview"*

Same problem. One rule — *check what the CI workflow actually runs before building
on it* — prevents both.

- *"declared the branch red based on a subagent summary it had not verified"*
- *"reported a fix unmerged from a stale vendored checkout without fetching origin"*

Same problem, despite different surface detail. One rule — *verify repo state
against the source of truth rather than a cached or delegated view* — prevents
both.

Now a pair that is NOT the same problem, though both are `unverified_premise`:

- *"assumed CI runs applies"*
- *"assumed a resource was still active when it had been decommissioned"*

Both are unchecked premises. But no single checkable instruction prevents both
without collapsing into "check your premises", which is not a rule — it is the
kind name restated.

## Both failure directions are real

**Over-merging** produces a rule so general it cannot be followed. If the rule you
would write comes out as "be careful", "check things", or "understand the
context", you have merged episodes that are not the same problem. Split them.

**Under-merging** produces a pile of one-off rules that each fire once and never
again. If two episodes differ only in which system they happened to touch, they
are one problem.

A singleton is a legitimate outcome. Most episodes may end up alone, and that is
a finding in itself — it means the kind is broad rather than recurring. Do not
manufacture groups to look productive.

## `most_similar_sibling`

A similarity score on the rule-candidate text, offered only as a hint about where
to look. It is unreliable in both directions: on two pairs a human identified by
reading, it scored 0.53, below a threshold that had looked reasonable; lowering
the threshold to catch them flagged 18 pairs in one kind, mostly noise. Read the
episodes. Do not group on the score, and do not decline to group because the
score is low or absent.

## Output

```json
{
  "kind": "<copied from input>",
  "problems": [
    {
      "name": "short specific label, lowercase with underscores",
      "episodes": [2, 14],
      "rule": "One imperative a future assistant could follow without seeing these episodes. Concrete and checkable.",
      "why_grouped": "one sentence naming what the episodes share",
      "confidence": 0.8
    }
  ]
}
```

Every episode number in the input appears in exactly one problem. None omitted,
none duplicated, none invented. Count them before you finish.

### Writing the rule

Imperative, specific, and checkable by someone who has not read the episodes.

Good: *"Before building on what CI does, read the workflow file and confirm
whether it applies or only previews."*
Good: *"Report repo state only from a fresh fetch, never from a local checkout or
a delegated summary."*
Bad: *"Verify premises before acting."* — that is the kind, restated.
Bad: *"Be more careful with CI."* — nothing to check.

If a group genuinely has no checkable rule, keep the group and set `rule` to `""`
with `why_grouped` explaining why it resists one. An honest gap is more useful
than an unfollowable instruction.
