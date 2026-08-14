"""Cluster confirmed findings into ranked patterns and apply the rule bar.

Two gates, both set during the design session:

  fixability  a pattern nobody could write a checkable rule for is real friction
              but not a rule. It goes in its own section rather than padding the
              ruleset with aspirations.
  rule bar    >=2 incidents AND >=1 repeat-after-instruction. Repeat is the whole
              point: an instruction the user already gave and Claude broke anyway is
              exactly the failure this plugin exists to stop.

Usage: python3 tools/rank_findings.py
Writes: findings/findings.jsonl, findings/report.md
"""

import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, ensure_findings_dir, write_jsonl  # noqa: E402

MIN_INCIDENTS = 2
CLASS_LABEL = {
    "A": "Class A - what Claude did",
    "A-comments": "Class A - code comments",
    "B": "Class B - what Claude wrote for humans",
}


def load_judged():
    """Assemble judge_out/*.json, then report anything the judges dropped.

    The judging models silently omit items from long batches while still
    reporting a full count, so the join is the only trustworthy census."""
    out_dir = os.path.join(FINDINGS, "judge_out")
    if not os.path.isdir(out_dir):
        sys.exit("no findings/judge_out - run the judging pass first")

    rows, seen = [], set()
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(out_dir, name)))
        except ValueError:
            print(f"unparseable: {name}")
            continue
        if isinstance(data, dict):
            data = data.get("results") or data.get("items") or []
        for row in data:
            if isinstance(row, dict) and row.get("id") and row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)

    expected = set()
    judge_in = os.path.join(FINDINGS, "judge_in")
    if os.path.isdir(judge_in):
        for name in sorted(os.listdir(judge_in)):
            for item in json.load(open(os.path.join(judge_in, name))):
                expected.add(item["id"])
    missing = expected - seen
    if missing:
        print(f"WARNING: {len(missing)} of {len(expected)} items were never judged")
        with open(os.path.join(FINDINGS, "judge_missing.json"), "w") as fh:
            lookup = {}
            for name in sorted(os.listdir(judge_in)):
                for item in json.load(open(os.path.join(judge_in, name))):
                    lookup[item["id"]] = item
            json.dump([lookup[m] for m in missing], fh, indent=1)

    write_jsonl(os.path.join(FINDINGS, "judged.jsonl"), rows)
    return rows


def load_severity():
    path = os.path.join(FINDINGS, "triaged.jsonl")
    sev = {}
    if os.path.exists(path):
        for line in open(path):
            row = json.loads(line)
            sev[row["id"]] = {
                "severity": row.get("severity"),
                "source": row.get("source"),
                "ts": row.get("ts"),
                "project": row.get("project"),
                "session": row.get("session"),
            }
    return sev


def main():
    ensure_findings_dir()
    # Prefer deduped episodes. One argument produces several flagged messages,
    # and counting them separately inflates the patterns the user pushed hardest on.
    episodes = os.path.join(FINDINGS, "incidents.jsonl")
    if os.path.exists(episodes):
        judged = [json.loads(line) for line in open(episodes)]
        print(f"ranking {len(judged)} deduped episodes")
    else:
        judged = [j for j in load_judged() if j.get("confirmed")]
        sev = load_severity()
        print(f"ranking {len(judged)} raw incidents (run dedupe_incidents.py first)")
        for j in judged:
            meta = sev.get(j["id"], {})
            j["severity"] = meta.get("severity", 5.0)
            j["source"] = meta.get("source")
            j["ts"] = meta.get("ts")
            j["project"] = meta.get("project")
            j["session"] = meta.get("session")

    clusters = collections.defaultdict(list)
    for j in judged:
        clusters[(j.get("class", "A"), j.get("kind", "other"))].append(j)

    patterns = []
    for (klass, kind), items in clusters.items():
        severities = [i["severity"] for i in items]
        repeats = [i for i in items if i.get("repeat_after_instruction")]
        sessions = {i.get("session") for i in items if i.get("session")}
        fixes = collections.Counter(i.get("fixable_by", "neither") for i in items)
        fixable_by = fixes.most_common(1)[0][0]

        # the user asking for a rule outranks the threshold. The bar exists to stop
        # rules being built on one-off noise from a model's judgement; it has no
        # business overruling the person the rules are for. The 1Password signing
        # timeout has one transcript episode and is, by his account, the most
        # frequent failure they hit - the evidence simply is not in the corpus.
        by_fiat = any(i.get("corrected_by_greg") and i.get("source") == "greg" for i in items)
        meets_bar = by_fiat or (
            len(items) >= MIN_INCIDENTS
            and len(repeats) >= 1
            and fixable_by in ("rule", "hook")
        )
        patterns.append(
            {
                "class": klass,
                "kind": kind,
                "incidents": len(items),
                "sessions": len(sessions),
                "repeats": len(repeats),
                "severity_median": round(statistics.median(severities), 2),
                "severity_max": round(max(severities), 2),
                "score": round(len(items) * statistics.median(severities), 1),
                "fixable_by": fixable_by,
                "meets_rule_bar": meets_bar,
                "sources": dict(collections.Counter(i.get("source") for i in items)),
                "rule_candidates": [
                    r
                    for r, _ in collections.Counter(
                        i.get("rule_candidate", "").strip()
                        for i in items
                        if i.get("rule_candidate")
                    ).most_common(5)
                ],
                "examples": sorted(items, key=lambda i: -i["severity"])[:4],
            }
        )

    patterns.sort(key=lambda p: (-p["meets_rule_bar"], -p["score"]))
    write_jsonl(os.path.join(FINDINGS, "findings.jsonl"), patterns)

    lines = ["# Discipline sweep - findings", ""]
    lines.append(f"Confirmed incidents: **{len(judged)}** across **{len(patterns)}** patterns.")
    lines.append("")
    for gate, title in ((True, "Meets the rule bar"), (False, "Below the bar")):
        group = [p for p in patterns if p["meets_rule_bar"] is gate]
        if not group:
            continue
        lines += [f"## {title}", ""]
        lines.append("| Class | Kind | Incidents | Sessions | Repeats | Sev (med) | Score | Fix |")
        lines.append("|---|---|--:|--:|--:|--:|--:|---|")
        for p in group:
            lines.append(
                f"| {p['class']} | `{p['kind']}` | {p['incidents']} | {p['sessions']} "
                f"| {p['repeats']} | {p['severity_median']} | {p['score']} | {p['fixable_by']} |"
            )
        lines.append("")

    for p in patterns:
        lines += [
            f"### {CLASS_LABEL.get(p['class'], p['class'])} - `{p['kind']}`",
            "",
            f"{p['incidents']} incidents across {p['sessions']} sessions, "
            f"{p['repeats']} after the user had already said it. "
            f"Median severity {p['severity_median']}. Fixable by **{p['fixable_by']}**. "
            + ("**Meets the rule bar.**" if p["meets_rule_bar"] else "Below the bar."),
            "",
        ]
        if p["rule_candidates"]:
            lines.append("Rule candidates:")
            lines += [f"- {r}" for r in p["rule_candidates"]]
            lines.append("")
        lines.append("Examples:")
        for ex in p["examples"]:
            lines.append(
                f"- *\"{(ex.get('evidence_quote') or '').strip()}\"* - "
                f"{ex.get('what_claude_did', '')} (sev {ex['severity']})"
            )
        lines.append("")

    report = os.path.join(FINDINGS, "report.md")
    with open(report, "w") as fh:
        fh.write("\n".join(lines))

    print(json.dumps({
        "confirmed_incidents": len(judged),
        "patterns": len(patterns),
        "meets_bar": sum(1 for p in patterns if p["meets_rule_bar"]),
    }, indent=2))
    print(f"wrote -> {report}")


if __name__ == "__main__":
    main()
