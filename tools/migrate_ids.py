"""Re-key every stored verdict and ruling onto message-uuid ids.

Incident ids were originally `session:turn-index`. That was a mistake: turn
indices shift whenever the prompt filter changes. Excluding 65 harness interrupt
markers renumbered 510 of 1163 ids in one go, orphaning their triage verdicts and
- far worse - every ruling the user had attached to them.

Ids are now `session:message-uuid`, which nothing can renumber. This maps the old
ids to the new ones by matching session plus message text, then rewrites the
stored files in place. Each is backed up alongside with a .preuuid suffix.

Usage: python3 tools/migrate_ids.py [--dry-run]
"""

import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS  # noqa: E402

# Sources of (old id -> message text). More than one is needed: triaged.jsonl is
# written after the join, so it has already dropped the very ids the filter change
# orphaned - the ones most in need of remapping.
OLD_SOURCES = [
    "/tmp/triaged_oldids.jsonl",
    "/tmp/cand_before.jsonl",
]

# Files keyed by incident id. Rulings first - those are the ones that matter.
ID_KEYED_OBJECTS = ["overrides.json", "greg_review.json"]
ID_KEYED_ARRAYS = ["repeat_judged.json", "reclassify_out.json"]
ID_KEYED_DIRS = ["triage_out", "judge_out"]


def norm(text):
    return re.sub(r"\W+", " ", (text or "")).strip().lower()[:300]


def build_map():
    """old id -> new id, matched on (session, message text)."""
    available = [p for p in OLD_SOURCES if os.path.exists(p)]
    if not available:
        sys.exit(f"need at least one pre-migration snapshot: {OLD_SOURCES}")

    new_by_key = {}
    for name in ("candidates_transcripts.jsonl", "candidates_chat.jsonl"):
        path = os.path.join(FINDINGS, name)
        if not os.path.exists(path):
            continue
        for line in open(path):
            row = json.loads(line)
            session = row["id"].rpartition(":")[0]
            new_by_key[(session, norm(row.get("prompt")))] = row["id"]

    mapping, unmatched = {}, []
    for path in available:
        for line in open(path):
            row = json.loads(line)
            old = row["id"]
            if old in mapping:
                continue
            session = old.rpartition(":")[0]
            new = new_by_key.get((session, norm(row.get("prompt"))))
            if new:
                mapping[old] = new
            elif old not in unmatched:
                unmatched.append(old)
    print(f"sources: {', '.join(os.path.basename(p) for p in available)}")
    return mapping, unmatched


def remap_file(path, mapping, dry):
    if not os.path.exists(path):
        return 0, 0
    data = json.load(open(path))
    hit = miss = 0

    def fix(i):
        nonlocal hit, miss
        if i in mapping:
            hit += 1
            return mapping[i]
        miss += 1
        return i

    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            out[k if k.startswith("_") or k.startswith("standalone:") else fix(k)] = v
        data = out
    elif isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and row.get("id"):
                row["id"] = fix(row["id"])

    if not dry and hit:
        shutil.copy(path, path + ".preuuid")
        json.dump(data, open(path, "w"), indent=1)
    return hit, miss


def main():
    dry = "--dry-run" in sys.argv
    mapping, unmatched = build_map()
    print(f"mapped {len(mapping)} old ids; {len(unmatched)} had no match")
    if unmatched:
        print(f"  unmatched sample: {unmatched[:4]}")

    total_hit = total_miss = 0
    for name in ID_KEYED_OBJECTS + ID_KEYED_ARRAYS:
        h, m = remap_file(os.path.join(FINDINGS, name), mapping, dry)
        total_hit += h
        total_miss += m
        print(f"  {name:26} remapped {h:4}  unchanged {m:4}")

    for d in ID_KEYED_DIRS:
        base = os.path.join(FINDINGS, d)
        if not os.path.isdir(base):
            continue
        h = m = 0
        for name in sorted(os.listdir(base)):
            if name.endswith(".json"):
                a, b = remap_file(os.path.join(base, name), mapping, dry)
                h += a
                m += b
        total_hit += h
        total_miss += m
        print(f"  {d:26} remapped {h:4}  unchanged {m:4}")

    print(f"\n{'DRY RUN - ' if dry else ''}remapped {total_hit}, left alone {total_miss}")


if __name__ == "__main__":
    main()
