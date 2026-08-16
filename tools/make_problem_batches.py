"""Batch episodes for grouping into distinct problems within each kind.

A kind is a category, not a rule. "unverified_premise" has no checkable action in
it; "before stating repo state, fetch and diff against origin" does. Rules attach
to problems, so the problems have to be found before rules can be written.

Grouping is done by review, not by similarity score. Text similarity was tried
and failed its own test: on two pairs the user identified by reading, both scored
0.53, under a 0.55 threshold that had looked reasonable. Lowering it to catch them
flagged 18 pairs in one kind, most of them noise. Similarity ranks candidates for
a reader; it does not decide.

Each batch is one kind, so the reviewer sees every episode that could group
together and none that cannot.

Usage: python3 tools/make_problem_batches.py [--min N]
Writes: findings/problem_in/<kind>.json
"""

import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS  # noqa: E402

CLIP = 300


def norm(text):
    return re.sub(r"\W+", " ", (text or "")).strip().lower()


def nearest(items):
    """For each episode, the most similar sibling by rule candidate.

    Offered to the reviewer as a hint about where to look, explicitly not as a
    verdict - the threshold that would have caught the user's own pairs also
    floods with false positives.
    """
    hints = {}
    for i, x in enumerate(items):
        best, score = None, 0.0
        for j, y in enumerate(items):
            if i == j:
                continue
            r = difflib.SequenceMatcher(
                None, norm(x.get("rule_candidate")), norm(y.get("rule_candidate"))
            ).ratio()
            if r > score:
                best, score = j + 1, r
        if best and score >= 0.40:
            hints[i + 1] = {"n": best, "similarity": round(score, 2)}
    return hints


def main():
    minimum = 2
    if "--min" in sys.argv:
        minimum = int(sys.argv[sys.argv.index("--min") + 1])

    findings = FINDINGS
    incidents = [
        json.loads(line) for line in open(os.path.join(findings, "incidents.jsonl"))
    ]

    by_kind = {}
    for inc in incidents:
        by_kind.setdefault(inc["kind"], []).append(inc)

    out_dir = os.path.join(findings, "problem_in")
    os.makedirs(out_dir, exist_ok=True)
    for stale in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, stale))

    written = 0
    skipped = []
    for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        if len(items) < minimum:
            skipped.append(kind)
            continue
        # Same order as the report. Two orderings of one list means episode #2
        # denotes different episodes in different places, and any human reference
        # to a number silently lands on the wrong one.
        items.sort(
            key=lambda i: (
                not i.get("repeat_after_instruction"),
                -float(i.get("severity") or 0),
            )
        )
        hints = nearest(items)
        rows = [
            {
                "n": i + 1,
                "id": x["id"],
                "severity": x["severity"],
                "noncompliant": bool(x.get("repeat_after_instruction")),
                "what_claude_did": x.get("what_claude_did"),
                "what_user_wanted": x.get("what_user_wanted"),
                "rule_candidate": x.get("rule_candidate"),
                "evidence_quote": (x.get("evidence_quote") or "")[:CLIP],
                "most_similar_sibling": hints.get(i + 1),
            }
            for i, x in enumerate(items)
        ]
        with open(os.path.join(out_dir, f"{kind}.json"), "w") as fh:
            json.dump({"kind": kind, "episodes": rows}, fh, ensure_ascii=False, indent=1)
        written += 1

    print(
        json.dumps(
            {
                "kinds_batched": written,
                "episodes": sum(
                    len(v) for k, v in by_kind.items() if len(v) >= minimum
                ),
                "kinds_skipped_single_episode": len(skipped),
            },
            indent=2,
        )
    )
    print(f"wrote -> {out_dir}")


if __name__ == "__main__":
    main()
