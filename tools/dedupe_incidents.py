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
    """Group into episodes. Returns a list of lists.

    Merging is on SHARED QUOTE ONLY. An earlier version also merged incidents
    that sat close together in one session under the same kind label, on the
    theory that they were one argument. Measuring the semantic similarity inside
    those merges killed the theory: 12 of 16 scored between 0.01 and 0.11, i.e.
    they were unrelated failures that happened to be adjacent and share a label.
    The user found one by reading it - a diagram misreading merged with an
    inaccessible-file-path complaint four turns later.

    Proximity means two things went wrong near each other, not that one thing
    went wrong. Only an identical quote proves the judges wrote up the same
    moment twice, which is what resumed transcripts and adjacent-turn framings
    actually produce.
    """
    groups = [[inc] for inc in incidents]

    # Union on quote. Resuming a session writes a new transcript that replays
    # earlier messages, so the same words reach the judges under two session ids;
    # and a single message is sometimes written up twice from adjacent turns.
    owner = {}  # (kind, quote) -> index of the group that claimed it
    parent = list(range(len(groups)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, group in enumerate(groups):
        for member in group:
            key = (member["kind"], norm(member["evidence_quote"])[:200])
            if not key[1]:
                continue
            if key in owner:
                union(owner[key], i)
            else:
                owner[key] = i

    combined = collections.defaultdict(list)
    for i, group in enumerate(groups):
        combined[find(i)].extend(group)
    return list(combined.values())


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
        # Members of an episode often quote the same sentence. Showing it twice
        # is what made the report look duplicated in the first place.
        also, seen_text = [], {norm(lead.get("evidence_quote"))}
        for x in group:
            quote = x.get("evidence_quote")
            key = norm(quote)
            if not quote or key in seen_text:
                continue
            seen_text.add(key)
            also.append(quote)
        merged["also_said"] = also
        # Prefer a rule candidate from a repeat member - it is the one the user had
        # already asked for.
        repeats = [x for x in group if x.get("repeat_after_instruction")]
        if repeats and not lead.get("repeat_after_instruction"):
            merged["rule_candidate"] = repeats[0].get("rule_candidate") or merged.get(
                "rule_candidate"
            )
    return merged


def apply_overrides(incidents):
    """Let the user's rulings beat the judges'.

    The judges are a rubric applied by a model; the user is the person the rule is
    for. Where they have corrected a finding, their wording wins and survives a
    re-run. Keyed by incident id in findings/overrides.json.
    """
    path = os.path.join(FINDINGS, "overrides.json")
    if not os.path.exists(path):
        return 0
    overrides = json.load(open(path))
    applied = 0
    for inc in incidents:
        patch = overrides.get(inc["id"])
        if not patch:
            continue
        inc.update(patch)
        inc["corrected_by_greg"] = True
        applied += 1
    unknown = set(overrides) - {i["id"] for i in incidents}
    if unknown:
        print(f"WARNING: {len(unknown)} override ids match no incident: {sorted(unknown)}")
    return applied


def main():
    ensure_findings_dir()
    gap = TURN_GAP
    if "--gap" in sys.argv:
        gap = int(sys.argv[sys.argv.index("--gap") + 1])

    confirmed = load_confirmed()
    applied = apply_overrides(confirmed)
    if applied:
        print(f"applied {applied} of the user's corrections")

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
