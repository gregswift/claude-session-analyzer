"""Batch extracted code comments for judging against the user's what-vs-why test.

Usage: python3 tools/make_comment_batches.py [batch_size]
Writes: findings/comment_in/batch_NNN.json
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, ensure_findings_dir, positional_args  # noqa: E402


def main():
    args = positional_args()
    size = int(args[0]) if args else 110
    ensure_findings_dir()
    rows = [
        {
            "id": r["id"],
            "file": os.path.basename(r["file"] or ""),
            "comment": r["comment"],
            "code_after": r["code_after"][:400],
        }
        for r in (
            json.loads(line)
            for line in open(os.path.join(FINDINGS, "code_comments.jsonl"))
        )
    ]

    out_dir = os.path.join(FINDINGS, "comment_in")
    os.makedirs(out_dir, exist_ok=True)
    for stale in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, stale))

    batches = [rows[i : i + size] for i in range(0, len(rows), size)]
    total = 0
    for i, batch in enumerate(batches):
        path = os.path.join(out_dir, f"batch_{i:03d}.json")
        with open(path, "w") as fh:
            json.dump(batch, fh, ensure_ascii=False, indent=1)
        total += os.path.getsize(path)

    print(json.dumps({
        "comments": len(rows),
        "batches": len(batches),
        "est_tokens_total": total // 4,
        "est_tokens_per_batch": total // 4 // max(1, len(batches)),
    }))


if __name__ == "__main__":
    main()
