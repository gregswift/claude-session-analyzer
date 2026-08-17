### Behavior-grouping rubric

You are given every rule candidate in the corpus at once: each confirmed
**problem**, plus each lone **episode** that no problem claimed. They are NOT
partitioned by kind. Group them into **behaviors**.

This is the last layer, and the only one that ships. The layers are:

    kind  ->  problem  ->  behavior
    (a category)   (rule-shaped, but scoped to the situation it came from)
                          (rule-shaped AND loadable as a standing instruction)

## Why this layer exists

Problems were grouped inside a single kind, so their rules encode the situation
they came from:

- *"read the CI workflow file to confirm whether it runs apply or only preview"*
- *"check the OTel processor source, not just the Helm chart"*
- *"confirm a hardware port against the device rather than model recall"*

Each is accurate. None survives contact with a different project. And they sit
under three different kinds while describing one behavior: **stating something
from memory or a proxy artifact instead of reading the actual source.**

A behavior is the instruction a future assistant could load having never seen
this corpus, in any project, and follow. The problems become its worked
examples.

## The test for "same behavior"

**Would one standing instruction, loaded before the session started, have
prevented every episode under it?**

Not "are these thematically similar." Not "do they share a kind" - kind is a
label here, never a reason to group or to split. The instruction has to actually
do the work in every case, in a project it has never seen.

## Both failure directions are real, and the pull is toward the first

**Too general** is the failure this layer invites. "Be careful." "Verify things."
"Follow instructions." These pass the test only because they are unfalsifiable.
Apply this check: could someone follow the rule and still commit the episode? If
yes, it is too general. Also: does the rule name a *decision point* - a moment
where the assistant must do something observable before proceeding? If there is
no such moment, it is a sentiment, not a rule.

**Too specific** is what this pass exists to fix. If a rule names a particular
tool, vendor, repo, or file that happened to be involved, it belongs one layer
down as an example, not up here as a behavior.

## Size

Aim for **5 to 8 behaviors**. Not a quota - if the evidence honestly supports
four, return four and say so. But a result of fifteen means the merge did not
happen, and a result of three almost certainly means one of them is "be
careful."

Every candidate lands in exactly one behavior, or in `unassigned` with a reason.
`unassigned` is a legitimate outcome for a genuine one-off; it is not a bin for
anything awkward. If more than about a fifth end up there, the behaviors are too
narrow.

## Writing the rule

Imperative. Names an observable action at a named moment. Project-agnostic.
Followable by someone who has read nothing else.

Good: *"Before stating what a system does, read the artifact that defines it -
the workflow file, the source, the live state. If you cannot read it, say the
claim is unverified rather than stating it plainly."*

Good: *"Treat facts and decisions established earlier in the conversation as
ground truth. To contradict one, cite what changed; never re-derive it from
priors."*

Bad: *"Verify your premises."* - no decision point, nothing observable.
Bad: *"Check the CI workflow before assuming it applies."* - a worked example.

Also write `detects`: how a violation would be spotted after the fact. A rule
nobody can check is a rule nobody can enforce.

## Output

```json
{
  "behaviors": [
    {
      "name": "short_specific_label",
      "title": "Human-readable name, a few words",
      "rule": "The standing instruction. Imperative, project-agnostic, checkable.",
      "why": "One or two sentences on what these candidates share.",
      "detects": "How a violation is spotted after the fact.",
      "covers": ["kind::problem_name", "session:message-uuid"],
      "confidence": 0.8
    }
  ],
  "unassigned": [
    {"id": "kind::problem_name", "why": "one sentence"}
  ]
}
```

`covers` holds candidate ids copied exactly from the input. Every input id
appears exactly once across all `covers` plus `unassigned` - none omitted, none
duplicated, none invented. Count them before you finish.
