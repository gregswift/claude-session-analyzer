"""Aggregate the code-comment verdicts into a rate and a worked example set.

The question this answers is narrow: do Claude's code comments fail often enough,
and repeatably enough, to justify the PostToolUse hook the user asked about? A rate,
not a vibe.

Usage: python3 tools/summarize_comments.py
Writes: findings/comment_summary.json
"""

import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, ensure_findings_dir  # noqa: E402

BAD = ("what_not_why", "unstated_premise", "verbose", "stale_narration")


def main():
    ensure_findings_dir()
    out_dir = os.path.join(FINDINGS, "comment_out")
    verdicts, seen = [], set()
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".json"):
            continue
        for row in json.load(open(os.path.join(out_dir, name))):
            if isinstance(row, dict) and row.get("id") and row["id"] not in seen:
                seen.add(row["id"])
                verdicts.append(row)

    source = {
        r["id"]: r
        for r in (
            json.loads(line)
            for line in open(os.path.join(FINDINGS, "code_comments.jsonl"))
        )
    }
    expected = set(source)
    missing = expected - seen
    if missing:
        print(f"WARNING: {len(missing)} of {len(expected)} comments were never judged")

    counts = collections.Counter(v.get("verdict") for v in verdicts)
    bad = [v for v in verdicts if v.get("verdict") in BAD]

    by_file = collections.Counter(
        source[v["id"]]["file"].split("/")[-1] for v in bad if v["id"] in source
    )
    words_good = [
        source[v["id"]]["words"]
        for v in verdicts
        if v.get("verdict") == "good" and v["id"] in source
    ]
    words_bad = [source[v["id"]]["words"] for v in bad if v["id"] in source]

    result = {
        "judged": len(verdicts),
        "total_comments": len(expected),
        "unjudged": len(missing),
        "verdicts": dict(counts),
        "bad_rate": round(len(bad) / max(1, len(verdicts)), 3),
        "median_words_good": statistics.median(words_good) if words_good else None,
        "median_words_bad": statistics.median(words_bad) if words_bad else None,
        "worst_files": by_file.most_common(8),
        "examples": [
            {
                "verdict": v["verdict"],
                "why": v.get("why"),
                "file": source[v["id"]]["file"].split("/")[-1],
                "comment": source[v["id"]]["comment"][:280],
                "suggested": v.get("suggested", ""),
            }
            for v in bad[:12]
            if v["id"] in source
        ],
    }

    path = os.path.join(FINDINGS, "comment_summary.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "examples"}, indent=2))


if __name__ == "__main__":
    main()
