"""Extract Class B artifacts the model wrote for humans, from transcript tool calls.

Commit messages, PR titles/bodies and PR comments all pass through Bash tool_use
payloads, so the transcripts hold what the model actually submitted. What landed
is collected separately by collect_git.py - the diff between the two is the
highest-signal correction data available, because the user never had to type a
complaint for it to count.

Usage: python3 tools/extract_artifacts.py
Writes: findings/artifacts_authored.jsonl
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    ensure_findings_dir,
    iter_transcripts,
    read_jsonl,
    strip_trailers,
    tool_uses,
    write_jsonl,
)

# -m 'msg' / -m "msg", non-greedy, spanning newlines.
DASH_M = re.compile(r"-m\s+(['\"])(?P<body>.*?)(?<!\\)\1", re.S)
# --body / --title flags for gh.
GH_FLAG = re.compile(r"--(?P<flag>body|title)\s+(['\"])(?P<body>.*?)(?<!\\)\2", re.S)
# Heredoc payloads: $(cat <<'EOF' ... EOF)
HEREDOC = re.compile(r"<<\s*['\"]?(?P<tag>[A-Za-z_][A-Za-z0-9_]*)['\"]?\n(?P<body>.*?)\n\s*(?P=tag)", re.S)

def extract_bodies(command):
    """Yield (field, text) for every authored payload in one bash command.

    `field` matters: a PR title and a PR body are different artifacts with
    different length norms, and comparing one against the other makes every PR
    look rewritten."""
    out = []
    for match in HEREDOC.finditer(command):
        out.append(("body", match.group("body")))
    for match in DASH_M.finditer(command):
        body = match.group("body")
        if "<<" not in body:
            out.append(("message", body))
    for match in GH_FLAG.finditer(command):
        body = match.group("body")
        if "<<" not in body:
            out.append((match.group("flag"), body))
    return out


def classify(command):
    if re.search(r"\bgh\s+pr\s+create\b", command):
        return "pr_body"
    if re.search(r"\bgh\s+pr\s+(comment|review)\b", command):
        return "pr_comment"
    if re.search(r"\bgh\s+(issue|api)\b.*--body", command, re.S):
        return "gh_other"
    if re.search(r"\bgit\s+commit\b", command):
        return "commit_message"
    return None


def main():
    rows = []
    # Retries and resumed sessions replay the same tool call, and a heredoc can
    # also match the -m pattern. Same body + same kind is one artifact.
    seen = set()
    stats = {"commit_message": 0, "pr_body": 0, "pr_comment": 0, "gh_other": 0}

    for project, path in iter_transcripts():
        session = os.path.basename(path)[:-6]
        cwd = None
        branch = None
        for entry in read_jsonl(path):
            cwd = entry.get("cwd") or cwd
            branch = entry.get("gitBranch") or branch
            if entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            for name, payload in tool_uses(entry):
                if name != "Bash":
                    continue
                command = payload.get("command") or ""
                kind = classify(command)
                if not kind:
                    continue
                for field, body in extract_bodies(command):
                    body = strip_trailers(body)
                    if len(body) < 12:
                        continue
                    # A --title on a gh pr create is a title, not a body.
                    row_kind = "pr_title" if (kind == "pr_body" and field == "title") else kind
                    key = (row_kind, body)
                    if key in seen:
                        continue
                    seen.add(key)
                    stats[row_kind] = stats.get(row_kind, 0) + 1
                    rows.append(
                        {
                            "id": f"{session}:{len(rows)}",
                            "source": "artifact",
                            "kind": row_kind,
                            "field": field,
                            "project": project,
                            "session": session,
                            "cwd": cwd,
                            "branch": branch,
                            "ts": entry.get("timestamp"),
                            "body": body[:6000],
                            "lines": body.count("\n") + 1,
                            "chars": len(body),
                        }
                    )

    out = os.path.join(ensure_findings_dir(), "artifacts_authored.jsonl")
    write_jsonl(out, rows)
    print(json.dumps(stats))
    print(f"wrote {len(rows)} artifacts -> {out}")


if __name__ == "__main__":
    main()
