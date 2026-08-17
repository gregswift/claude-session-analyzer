"""Batch every rule candidate into ONE grouping run, not partitioned by kind.

Problem grouping runs inside a single kind: each batch is one kind's episodes,
and "would one rule prevent both?" gets answered inside that box. That produces
tight, correct groups - and rules that read like the conversation they came
from. "Read the CI workflow before assuming it applies" is true, and useless as
a standing instruction.

The reason is structural. The clusters that are actually rule-shaped cut ACROSS
kinds: asserting from memory instead of reading the source shows up as
unverified_premise in one session, false_confidence in another, and
internal_over_user_fact in a third. Partitioned by kind, nothing ever sees them
together.

So this batch drops the partition. Every problem and every lone episode goes in
at once, carrying its kind as a label rather than as a wall.

Lone episodes are included as candidates in their own right. A kind with one
episode never reached problem grouping at all (that stage needs two), so those
would otherwise be invisible to every layer above them - and a singleton that
joins a behavior is exactly the evidence that makes the behavior recurring.

Usage: python3 tools/make_behavior_batch.py
Writes: findings/behavior_in/all.json
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS  # noqa: E402

CLIP = 400


def main():
    problems = [
        json.loads(line)
        for line in open(os.path.join(FINDINGS, "problems.jsonl"))
    ]
    incidents = [
        json.loads(line)
        for line in open(os.path.join(FINDINGS, "incidents.jsonl"))
    ]

    candidates = []
    for p in problems:
        candidates.append(
            {
                "id": p["id"],
                "unit": "problem",
                "kind": p["kind"],
                "name": p.get("name"),
                "rule": p.get("rule") or "",
                "why_grouped": p.get("why_grouped"),
                "episodes": p["episodes"],
                "noncompliant": p["noncompliant"],
                "severity_median": p["severity_median"],
            }
        )

    # Episodes no problem claimed: singleton kinds, below the grouping minimum.
    for inc in incidents:
        if inc.get("problem"):
            continue
        candidates.append(
            {
                "id": inc["id"],
                "unit": "episode",
                "kind": inc["kind"],
                "name": None,
                "rule": inc.get("rule_candidate") or "",
                "what_claude_did": (inc.get("what_claude_did") or "")[:CLIP],
                "episodes": 1,
                "noncompliant": 1 if inc.get("repeat_after_instruction") else 0,
                "severity_median": inc.get("severity"),
            }
        )

    # Loudest first, so a reader who stops early has still seen what matters.
    candidates.sort(
        key=lambda c: (-c["noncompliant"], -c["episodes"],
                       -float(c["severity_median"] or 0))
    )

    out_dir = os.path.join(FINDINGS, "behavior_in")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "all.json")
    with open(path, "w") as fh:
        json.dump(
            {
                "candidates": candidates,
                "kinds_present": sorted({c["kind"] for c in candidates}),
            },
            fh,
            ensure_ascii=False,
            indent=1,
        )

    print(
        json.dumps(
            {
                "candidates": len(candidates),
                "from_problems": sum(1 for c in candidates if c["unit"] == "problem"),
                "from_lone_episodes": sum(1 for c in candidates if c["unit"] == "episode"),
                "episodes_covered": sum(c["episodes"] for c in candidates),
                "kinds": len({c["kind"] for c in candidates}),
            },
            indent=2,
        )
    )
    print(f"wrote -> {path}")


if __name__ == "__main__":
    main()
