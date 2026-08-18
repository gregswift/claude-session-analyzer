"""Fold the cross-kind behavior grouping back onto problems and incidents.

This is the layer that ships. Problem rules stay - they become the worked
examples and the regression set for the behavior above them - but the ruleset a
plugin loads is the handful of behaviors, not 114 rules that each name the
project they came from.

Every candidate id is validated against what the batch actually contained. An id
that matches nothing is a hard error rather than a silently dropped row: a
grouping run that quietly covered 90 of 126 candidates would still report
success, and the missing 36 would look like evidence that did not exist.

Nothing is written back onto problems.jsonl or incidents.jsonl. The mapping lives
in behaviors.jsonl and is resolved by id where it is needed, so the stage graph
stays acyclic - a stage that edits its own inputs makes every downstream output
look permanently stale, which is exactly the alarm the staleness check exists to
raise.

Usage: python3 tools/merge_behaviors.py
Writes: findings/behaviors.jsonl, findings/behaviors_unassigned.jsonl
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, write_jsonl  # noqa: E402


def main():
    batch_path = os.path.join(FINDINGS, "behavior_in", "all.json")
    if not os.path.exists(batch_path):
        sys.exit("no findings/behavior_in/all.json - run make_behavior_batch.py first")
    batch = json.load(open(batch_path))
    candidates = {c["id"]: c for c in batch["candidates"]}

    out_path = os.path.join(FINDINGS, "behavior_out", "all.json")
    if not os.path.exists(out_path):
        sys.exit("no findings/behavior_out/all.json - run the behavior grouping first")
    data = json.load(open(out_path))

    prob_path = os.path.join(FINDINGS, "problems.jsonl")
    inc_path = os.path.join(FINDINGS, "incidents.jsonl")
    problems = [json.loads(line) for line in open(prob_path)]
    incidents = [json.loads(line) for line in open(inc_path)]
    problems_by_id = {p["id"]: p for p in problems}

    seen = {}
    behaviors = []
    errors = []

    for b in data.get("behaviors", []):
        name = b.get("name") or "unnamed"
        members = []
        for cid in b.get("covers", []):
            if cid not in candidates:
                errors.append(f"{name}: '{cid}' is not a candidate in the batch")
                continue
            if cid in seen:
                errors.append(f"{name}: '{cid}' already covered by {seen[cid]}")
                continue
            seen[cid] = name
            members.append(candidates[cid])

        if not members:
            errors.append(f"{name}: covers nothing")
            continue

        behaviors.append(
            {
                "id": name,
                "title": b.get("title") or name,
                "rule": (b.get("rule") or "").strip(),
                "why": b.get("why"),
                "detects": b.get("detects"),
                "confidence": b.get("confidence"),
                "candidates": len(members),
                "problems": sum(1 for m in members if m["unit"] == "problem"),
                "lone_episodes": sum(1 for m in members if m["unit"] == "episode"),
                "episodes": sum(m["episodes"] for m in members),
                "noncompliant": sum(m["noncompliant"] for m in members),
                "kinds": sorted({m["kind"] for m in members}),
                "candidate_ids": [m["id"] for m in members],
            }
        )

    unassigned = []
    for u in data.get("unassigned", []):
        cid = u.get("id")
        if cid not in candidates:
            errors.append(f"unassigned: '{cid}' is not a candidate in the batch")
            continue
        if cid in seen:
            errors.append(f"unassigned: '{cid}' also covered by {seen[cid]}")
            continue
        seen[cid] = None
        unassigned.append({"id": cid, "why": u.get("why"),
                           "episodes": candidates[cid]["episodes"]})

    orphans = [cid for cid in candidates if cid not in seen]
    for cid in orphans:
        errors.append(f"candidate '{cid}' landed in no behavior and no unassigned")

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(f"{len(errors)} problem(s) - nothing written")

    behaviors.sort(key=lambda b: (-b["noncompliant"], -b["episodes"]))
    write_jsonl(os.path.join(FINDINGS, "behaviors.jsonl"), behaviors)
    # Separate file rather than a null-id row: what no behavior claimed is a
    # result in its own right, and the report has to be able to say so.
    write_jsonl(os.path.join(FINDINGS, "behaviors_unassigned.jsonl"), unassigned)

    print(
        json.dumps(
            {
                "behaviors": len(behaviors),
                "candidates_covered": sum(b["candidates"] for b in behaviors),
                "candidates_unassigned": len(unassigned),
                "episodes_covered": sum(b["episodes"] for b in behaviors),
                "episodes_unassigned": sum(u["episodes"] for u in unassigned),
                "problems_in_corpus": len(problems),
                "episodes_in_corpus": len(incidents),
            },
            indent=2,
        )
    )
    for b in behaviors:
        print(
            f"  {b['episodes']:3} ep  {b['noncompliant']:2} nc  "
            f"{len(b['kinds']):2} kinds  {b['id']}"
        )


if __name__ == "__main__":
    main()
