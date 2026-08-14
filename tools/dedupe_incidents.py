"""Collapse confirmed incidents into distinct episodes.

The finders flag every message the user wrote that looks like pushback. A single
argument produces several of them - they object, Claude answers badly, they object
again - and the judge confirms each one separately. Counting those as separate
incidents inflates exactly the patterns where the user pushed hardest.

Two incidents are the same episode when they share a session and a kind and sit
within TURN_GAP turns of each other, or when they quote the same words.

Merging keeps the WORST member, not the last: highest severity, and
repeat_after_instruction true if it was true for any member. Losing a repeat flag
to a merge would silently drop a pattern below the rule bar.

Usage: python3 tools/dedupe_incidents.py [--gap N] [--sensitivity]
Writes: findings/incidents.jsonl
"""

import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, ensure_findings_dir, write_jsonl  # noqa: E402

TURN_GAP = 12  # ~6 exchanges: close enough to be one argument


def norm(text):
    return re.sub(r"\W+", " ", (text or "")).strip().lower()


def load_confirmed():
    judged = [
        j
        for j in (
            json.loads(line)
            for line in open(os.path.join(FINDINGS, "judged.jsonl"))
        )
        if j.get("confirmed")
    ]
    triaged = {
        t["id"]: t
        for t in (
            json.loads(line)
            for line in open(os.path.join(FINDINGS, "triaged.jsonl"))
        )
    }
    for j in judged:
        meta = triaged.get(j["id"], {})
        j["severity"] = meta.get("severity", 5.0)
        j["source"] = meta.get("source")
        j["ts"] = meta.get("ts")
        j["project"] = meta.get("project")
        j["session"] = j["id"].rpartition(":")[0]
        try:
            j["turn"] = int(j["id"].rpartition(":")[2])
        except ValueError:
            j["turn"] = 0
    return judged


def episodes(incidents, gap):
    """Group into episodes. Returns a list of lists."""
    buckets = collections.defaultdict(list)
    for inc in incidents:
        buckets[(inc["session"], inc["kind"])].append(inc)

    groups = []
    for items in buckets.values():
        items.sort(key=lambda x: x["turn"])
        run = [items[0]]
        for nxt in items[1:]:
            same_quote = norm(nxt["evidence_quote"])[:200] == norm(
                run[-1]["evidence_quote"]
            )[:200]
            if nxt["turn"] - run[-1]["turn"] <= gap or same_quote:
                run.append(nxt)
            else:
                groups.append(run)
                run = [nxt]
        groups.append(run)
    return groups


def merge(group):
    """Representative = worst member. Never lose a repeat flag to a merge."""
    lead = max(group, key=lambda x: (float(x.get("severity") or 0), len(x.get("what_claude_did") or "")))
    merged = dict(lead)
    merged["severity"] = max(float(x.get("severity") or 0) for x in group)
    merged["repeat_after_instruction"] = any(
        x.get("repeat_after_instruction") for x in group
    )
    merged["occurrences"] = len(group)
    merged["merged_ids"] = [x["id"] for x in group]
    if len(group) > 1:
        merged["also_said"] = [
            x["evidence_quote"]
            for x in group
            if x["id"] != lead["id"] and x.get("evidence_quote")
        ]
        # Prefer a rule candidate from a repeat member - it is the one the user had
        # already asked for.
        repeats = [x for x in group if x.get("repeat_after_instruction")]
        if repeats and not lead.get("repeat_after_instruction"):
            merged["rule_candidate"] = repeats[0].get("rule_candidate") or merged.get(
                "rule_candidate"
            )
    return merged


def main():
    ensure_findings_dir()
    gap = TURN_GAP
    if "--gap" in sys.argv:
        gap = int(sys.argv[sys.argv.index("--gap") + 1])

    confirmed = load_confirmed()

    if "--sensitivity" in sys.argv:
        print("gap  distinct  bad_assumption  repeats_lost")
        for g in (0, 4, 8, 12, 20, 40):
            groups = episodes(confirmed, g)
            merged = [merge(x) for x in groups]
            ba = sum(1 for m in merged if m["kind"] == "bad_assumption")
            lost = sum(1 for m in merged if m.get("repeat_after_instruction")) - sum(
                1 for c in confirmed if c.get("repeat_after_instruction")
            )
            print(f"{g:>3}  {len(merged):>8}  {ba:>14}  {lost:>12}")
        return

    groups = episodes(confirmed, gap)
    merged = sorted(
        (merge(g) for g in groups), key=lambda m: -float(m.get("severity") or 0)
    )
    write_jsonl(os.path.join(FINDINGS, "incidents.jsonl"), merged)

    collapsed = len(confirmed) - len(merged)
    multi = [m for m in merged if m["occurrences"] > 1]
    print(
        json.dumps(
            {
                "confirmed": len(confirmed),
                "distinct_episodes": len(merged),
                "collapsed": collapsed,
                "multi_turn_episodes": len(multi),
                "largest_episode": max((m["occurrences"] for m in merged), default=0),
                "repeats_before": sum(
                    1 for c in confirmed if c.get("repeat_after_instruction")
                ),
                "repeats_after": sum(
                    1 for m in merged if m.get("repeat_after_instruction")
                ),
                "turn_gap": gap,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
