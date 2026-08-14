"""Collect what actually landed in git, to compare against what the model wrote.

Repos are discovered from the cwd recorded in the transcripts rather than
hardcoded, so this stays correct as the working set changes. Forks with a
separate `upstream` remote are skipped - the user curated those themselves.

Usage: python3 tools/collect_git.py
Writes: findings/git_landed.jsonl
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    FINDINGS,
    ensure_findings_dir,
    window_start,
    write_jsonl,
)

WINDOW_START = window_start()

SEP = "\x1e"  # record separator - safe inside commit bodies
FMT = SEP.join(["%H", "%an", "%ae", "%cn", "%aI", "%s", "%b"]) + "\x1d"


def run(args, cwd=None):
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=60
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return out.stdout if out.returncode == 0 else None


def toplevel(path):
    out = run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    return out.strip() if out else None


def has_upstream(repo):
    out = run(["git", "remote"], cwd=repo)
    return bool(out) and "upstream" in out.split()


def common_dir(path):
    """Identity of the underlying repo. Worktrees share one object store, so
    keying on toplevel would walk the same history once per worktree."""
    out = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=path)
    return os.path.realpath(out.strip()) if out else None


def discover_repos():
    """Every distinct git object store that produced an artifact, minus forks."""
    cwds = set()
    artifacts = os.path.join(FINDINGS, "artifacts_authored.jsonl")
    if os.path.exists(artifacts):
        for line in open(artifacts):
            cwd = json.loads(line).get("cwd")
            if cwd and os.path.isdir(cwd):
                cwds.add(cwd)

    repos = {}
    seen_stores = set()
    for cwd in sorted(cwds):
        top = toplevel(cwd)
        store = common_dir(cwd)
        if not top or not store or store in seen_stores:
            continue
        if has_upstream(top):
            print(f"skip (has upstream): {top}")
            continue
        seen_stores.add(store)
        repos[top] = run(["git", "remote", "get-url", "origin"], cwd=top)
    return repos


def main():
    ensure_findings_dir()
    rows = []
    seen_shas = set()
    for repo, origin in discover_repos().items():
        out = run(
            [
                "git",
                "log",
                "--all",
                f"--since={WINDOW_START}",
                f"--pretty=format:{FMT}",
            ],
            cwd=repo,
        )
        if not out:
            continue
        count = 0
        for record in out.split("\x1d"):
            record = record.strip("\n")
            if not record.strip():
                continue
            parts = record.split(SEP)
            if len(parts) < 7:
                continue
            sha, an, ae, cn, date, subject, body = parts[:7]
            if sha in seen_shas:
                continue
            seen_shas.add(sha)
            rows.append(
                {
                    "repo": os.path.basename(repo),
                    "repo_path": repo,
                    "origin": (origin or "").strip(),
                    "sha": sha,
                    "author": an,
                    "author_email": ae,
                    "committer": cn,
                    "date": date,
                    "subject": subject,
                    "body": body.strip()[:6000],
                }
            )
            count += 1
        print(f"{os.path.basename(repo)}: {count} commits since {WINDOW_START}")

    out_path = os.path.join(FINDINGS, "git_landed.jsonl")
    write_jsonl(out_path, rows)
    print(f"wrote {len(rows)} commits -> {out_path}")


if __name__ == "__main__":
    main()
