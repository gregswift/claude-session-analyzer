"""Collect PRs the user authored, with their review conversations.

Scope is set by Q16 of the design session: repos that appear in the transcripts,
PRs authored by the user, inside the transcript window, excluding forks with a
separate upstream. Responses are cached so re-runs cost no API calls.

Usage: python3 tools/collect_prs.py [--refresh]
Writes: findings/prs.jsonl, findings/.pr_cache/
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    FINDINGS,
    config_required,
    ensure_findings_dir,
    window_start,
    write_jsonl,
)

REPOS = config_required("pr_repos")
AUTHOR = config_required("pr_author")
WINDOW_START = window_start()
CACHE = os.path.join(FINDINGS, ".pr_cache")


def gh(args, cache_key=None, refresh=False):
    path = os.path.join(CACHE, cache_key + ".json") if cache_key else None
    if path and not refresh and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    out = subprocess.run(
        ["gh"] + args, capture_output=True, text=True, timeout=120
    )
    if out.returncode != 0:
        print(f"  gh failed: {' '.join(args[:4])}: {out.stderr.strip()[:120]}")
        return None
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None
    if path:
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)
    return data


def main():
    refresh = "--refresh" in sys.argv
    ensure_findings_dir()
    os.makedirs(CACHE, exist_ok=True)
    rows = []

    for repo in REPOS:
        slug = repo.replace("/", "_")
        listing = gh(
            [
                "pr", "list", "-R", repo, "--author", AUTHOR, "--state", "all",
                "--limit", "300", "--json", "number,title,createdAt",
            ],
            cache_key=f"list_{slug}",
            refresh=refresh,
        ) or []
        in_window = [p for p in listing if p["createdAt"][:10] >= WINDOW_START]
        print(f"{repo}: {len(in_window)} PRs in window")

        for pr in in_window:
            num = pr["number"]
            detail = gh(
                [
                    "pr", "view", str(num), "-R", repo, "--json",
                    "number,title,body,createdAt,state,additions,deletions,"
                    "changedFiles,comments,reviews,commits",
                ],
                cache_key=f"pr_{slug}_{num}",
                refresh=refresh,
            )
            if not detail:
                continue

            # Review-thread comments live on a different endpoint than the
            # issue-style comments returned above.
            threads = gh(
                ["api", f"repos/{repo}/pulls/{num}/comments", "--paginate"],
                cache_key=f"threads_{slug}_{num}",
                refresh=refresh,
            ) or []

            rows.append(
                {
                    "repo": repo,
                    "number": num,
                    "title": detail.get("title"),
                    "body": (detail.get("body") or "")[:12000],
                    "created": detail.get("createdAt"),
                    "state": detail.get("state"),
                    "additions": detail.get("additions"),
                    "deletions": detail.get("deletions"),
                    "changed_files": detail.get("changedFiles"),
                    "commit_subjects": [
                        c.get("messageHeadline") for c in detail.get("commits") or []
                    ],
                    "comments": [
                        {
                            "author": (c.get("author") or {}).get("login"),
                            "body": (c.get("body") or "")[:4000],
                            "created": c.get("createdAt"),
                        }
                        for c in detail.get("comments") or []
                    ],
                    "review_bodies": [
                        {
                            "author": (r.get("author") or {}).get("login"),
                            "state": r.get("state"),
                            "body": (r.get("body") or "")[:4000],
                        }
                        for r in detail.get("reviews") or []
                        if (r.get("body") or "").strip()
                    ],
                    "review_threads": [
                        {
                            "author": (t.get("user") or {}).get("login"),
                            "path": t.get("path"),
                            "body": (t.get("body") or "")[:4000],
                            "created": t.get("created_at"),
                        }
                        for t in threads
                    ],
                }
            )

    out = os.path.join(FINDINGS, "prs.jsonl")
    write_jsonl(out, rows)
    print(f"wrote {len(rows)} PRs -> {out}")


if __name__ == "__main__":
    main()
