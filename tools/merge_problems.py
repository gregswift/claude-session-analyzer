"""Fold reviewed problem groupings back into the incidents.

A kind is a category and has no checkable action in it, so no rule can attach to
it. A problem is specific enough to carry one, and the rule is the deliverable.
This adds that middle level: kind -> problems -> episodes.

Episode numbers in problem_out are positions in the kind's list as the report
orders it, so this resolves them back to ids immediately and never carries a
position further. Two orderings of one list is how "episode 2" came to mean two
different episodes, which corrupted a grouping run.

Usage: python3 tools/merge_problems.py
Writes: findings/problems.jsonl, and a problem field on findings/incidents.jsonl
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, write_jsonl  # noqa: E402


def report_order(items):
    """The single ordering. Anything that numbers episodes must use this."""
    return sorted(
        items,
        key=lambda i: (
            not i.get("repeat_after_instruction"),
            -float(i.get("severity") or 0),
        ),
    )


def main():
    inc_path = os.path.join(FINDINGS, "incidents.jsonl")
    incidents = [json.loads(line) for line in open(inc_path)]

    by_kind = {}
    for inc in incidents:
        by_kind.setdefault(inc["kind"], []).append(inc)

    out_dir = os.path.join(FINDINGS, "problem_out")
    if not os.path.isdir(out_dir):
        sys.exit("no findings/problem_out - run the problem grouping first")

    problems = []
    by_id = {}
    complaints = []

    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".json"):
            continue
        data = json.load(open(os.path.join(out_dir, name)))
        # The generic judge wraps a bare object in a list; accept both shapes.
        if isinstance(data, list):
            data = data[0] if data else {}
        kind = data.get("kind") or name[:-5]
        ordered = report_order(by_kind.get(kind, []))
        if not ordered:
            complaints.append(f"{kind}: grouped but no incidents carry that kind")
            continue

        seen_positions = set()
        for p in data.get("problems", []):
            members = []
            for n in p.get("episodes", []):
                if not isinstance(n, int) or not 1 <= n <= len(ordered):
                    complaints.append(f"{kind}: episode {n} out of range 1..{len(ordered)}")
                    continue
                if n in seen_positions:
                    complaints.append(f"{kind}: episode {n} claimed by two problems")
                    continue
                seen_positions.add(n)
                members.append(ordered[n - 1])

            if not members:
                continue

            pid = f"{kind}::{p.get('name') or 'unnamed'}"
            noncompliant = sum(
                1 for m in members if m.get("repeat_after_instruction")
            )
            severities = [float(m.get("severity") or 0) for m in members]
            record = {
                "id": pid,
                "kind": kind,
                "name": p.get("name"),
                "rule": (p.get("rule") or "").strip(),
                "why_grouped": p.get("why_grouped"),
                "confidence": p.get("confidence"),
                "episodes": len(members),
                "noncompliant": noncompliant,
                "sessions": len({m.get("session") for m in members if m.get("session")}),
                "severity_max": round(max(severities), 2),
                "severity_median": round(sorted(severities)[len(severities) // 2], 2),
                "episode_ids": [m["id"] for m in members],
            }
            problems.append(record)
            for m in members:
                by_id[m["id"]] = {"problem": pid, "problem_name": p.get("name")}

        missing = set(range(1, len(ordered) + 1)) - seen_positions
        if missing:
            complaints.append(f"{kind}: {len(missing)} episodes in no problem")

    for inc in incidents:
        inc.update(by_id.get(inc["id"], {}))

    write_jsonl(inc_path, incidents)
    problems.sort(key=lambda p: (-p["episodes"], -p["severity_median"]))
    write_jsonl(os.path.join(FINDINGS, "problems.jsonl"), problems)

    for c in complaints:
        print(f"WARNING: {c}")
    ungrouped = sum(1 for i in incidents if "problem" not in i)
    print(
        json.dumps(
            {
                "problems": len(problems),
                "recurring_problems": sum(1 for p in problems if p["episodes"] > 1),
                "episodes_grouped": len(by_id),
                "episodes_without_a_problem": ungrouped,
                "problems_with_a_rule": sum(1 for p in problems if p["rule"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
