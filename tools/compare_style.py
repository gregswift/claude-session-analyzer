"""Compare what the model writes against what the user writes, in the same repos.

This is the strongest Class B measurement available: no judgment, no recall bias,
no era drift. Every commit in the window is either hand-written by the user or
co-authored by Claude, and the trailer says which. The gap between the two
distributions is the finding.

Usage: python3 tools/compare_style.py
Writes: findings/style_comparison.json
"""

import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    FINDINGS,
    config_required,
    ensure_findings_dir,
    strip_trailers,
)

AUTHOR_EMAILS = set(config_required("author_emails"))
CLAUDE_TRAILER = re.compile(r"Co-[Aa]uthored-[Bb]y:.*(Claude|anthropic)", re.I)
BULLET = re.compile(r"^\s*[-*]\s", re.M)
HEADING = re.compile(r"^\s*#{1,4}\s|\*\*[^*]+\*\*:", re.M)


def profile(commits, label):
    if not commits:
        return None
    bodies = [strip_trailers(c["body"]) for c in commits]
    subjects = [c["subject"] for c in commits]
    body_lens = [len(b) for b in bodies]
    return {
        "label": label,
        "n": len(commits),
        "subject_chars_median": statistics.median(len(s) for s in subjects),
        "body_chars_median": statistics.median(body_lens),
        "body_chars_mean": round(statistics.mean(body_lens)),
        "body_chars_p90": sorted(body_lens)[int(len(body_lens) * 0.9) - 1],
        "body_lines_median": statistics.median(
            b.count("\n") + 1 if b else 0 for b in bodies
        ),
        "pct_no_body": round(sum(1 for b in bodies if not b) / len(bodies), 3),
        "pct_bulleted": round(
            sum(1 for b in bodies if BULLET.search(b)) / len(bodies), 3
        ),
        "pct_headed": round(
            sum(1 for b in bodies if HEADING.search(b)) / len(bodies), 3
        ),
    }


def main():
    ensure_findings_dir()
    path = os.path.join(FINDINGS, "git_landed.jsonl")
    commits = [json.loads(line) for line in open(path)]

    author_commits = [c for c in commits if c["author_email"] in AUTHOR_EMAILS]
    claude = [c for c in author_commits if CLAUDE_TRAILER.search(c["body"] or "")]
    hand = [c for c in author_commits if c not in claude]
    others = [
        c
        for c in commits
        if c["author_email"] not in AUTHOR_EMAILS and "bot" not in c["author_email"]
    ]

    result = {
        "window_commits": len(commits),
        "profiles": [
            p
            for p in (
                profile(hand, "user_hand_written"),
                profile(claude, "claude_co_authored"),
                profile(others, "other_humans_same_repos"),
            )
            if p
        ],
    }

    hand_p = next(
        (p for p in result["profiles"] if p["label"] == "user_hand_written"), None
    )
    claude_p = next(
        (p for p in result["profiles"] if p["label"] == "claude_co_authored"), None
    )
    if hand_p and claude_p:
        result["ratios"] = {
            "body_chars_median": round(
                claude_p["body_chars_median"] / max(1, hand_p["body_chars_median"]), 2
            ),
            "body_lines_median": round(
                claude_p["body_lines_median"] / max(1, hand_p["body_lines_median"]), 2
            ),
        }
    else:
        result["ratios"] = None
        print(
            "WARNING: no claude_co_authored commits for the configured author "
            "emails; ratios skipped"
        )

    out = os.path.join(FINDINGS, "style_comparison.json")
    with open(out, "w") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
