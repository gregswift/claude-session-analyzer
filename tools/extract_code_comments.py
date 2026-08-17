"""Extract comments the model added to source files, with their surrounding code.

The user's test, verbatim from the design session:

  "Does this diff add a comment that describes what the code does rather than
   why? Does it claim to fix a bug whose premise depends on an unstated
   condition?"

Answering that needs the comment AND the code it sits on, so both are captured
here. The judgment itself happens in the judging pass.

Usage: python3 tools/extract_code_comments.py
Writes: findings/code_comments.jsonl
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    FINDINGS,
    extendable_pattern,
    artifacts_allowed,
    ensure_findings_dir,
    iter_transcripts,
    read_jsonl,
    tool_uses,
    write_jsonl,
)

# Comment syntax by extension. Only line comments - block comments spanning a
# diff hunk are rare enough in this corpus not to justify a parser.
LINE_COMMENT = {
    ".py": "#", ".sh": "#", ".bash": "#", ".zsh": "#", ".rb": "#",
    ".yaml": "#", ".yml": "#", ".tf": "#", ".hcl": "#", ".toml": "#",
    ".mk": "#", "Makefile": "#", ".dockerfile": "#", "Dockerfile": "#",
    ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//", ".go": "//",
    ".java": "//", ".c": "//", ".h": "//", ".cpp": "//", ".rs": "//",
    ".proto": "//", ".jsonnet": "//",
}

# Machine directives rather than prose - nothing here was written to be read.
# Which directives exist depends on the stack, so this is extendable from the
# config with `extra_comment_skip`.
SKIP_PATTERNS = extendable_pattern(
    "comment_skip",
    r"^\s*(",
    [
        "#!", r"#\s*-\*-",
        r"//\s*(eslint|@ts-|prettier|nolint|go:generate|Code generated)",
        r"#\s*(noqa|type:|pylint|fmt:|yamllint|nosec)",
        r"#\s*(TODO\(|FIXME\()",
        r"#{3,}", r"/{3,}",
    ],
    r")",
)

CONTEXT = 4  # code lines after the comment, enough to judge what-vs-why


def comment_token(path):
    if not path:
        return None
    base = os.path.basename(path)
    if base in LINE_COMMENT:
        return LINE_COMMENT[base]
    _, ext = os.path.splitext(path)
    return LINE_COMMENT.get(ext.lower())


def added_lines(payload, name):
    """Lines this tool call introduced into the file."""
    if name == "Write":
        return (payload.get("content") or "").split("\n")
    if name == "Edit":
        old = set((payload.get("old_string") or "").split("\n"))
        new = (payload.get("new_string") or "").split("\n")
        return [l for l in new if l not in old]
    if name == "NotebookEdit":
        return (payload.get("new_source") or "").split("\n")
    return []


def harvest(lines, token, all_lines):
    """Yield (comment_block, following_code) for each added comment.

    A comment is a *block*: consecutive comment lines in the file are one unit.
    Judging them line by line asks whether a sentence fragment explains why,
    which is not a question with an answer."""
    added = set(lines)
    out = []
    i = 0
    while i < len(all_lines):
        line = all_lines[i]
        stripped = line.strip()
        if not stripped.startswith(token) or line not in added:
            i += 1
            continue

        block = []
        start = i
        while i < len(all_lines):
            cur = all_lines[i].strip()
            if not cur.startswith(token):
                break
            block.append(cur[len(token) :].strip())
            i += 1

        # A block counts as Claude's only if Claude added part of it.
        if not any(all_lines[j] in added for j in range(start, i)):
            continue
        if any(SKIP_PATTERNS.match(all_lines[j].strip()) for j in range(start, i)):
            continue

        body = "\n".join(b for b in block if b).strip()
        if len(body) < 12:
            continue
        following = [
            nxt for nxt in all_lines[i : i + CONTEXT] if not nxt.strip().startswith(token)
        ]
        out.append((body, "\n".join(following).strip()))
    return out


def main():
    ensure_findings_dir()
    rows = []
    seen = set()

    for project, path in iter_transcripts():
        if not artifacts_allowed(project):
            continue
        session = os.path.basename(path)[:-6]
        for entry in read_jsonl(path):
            if entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            for name, payload in tool_uses(entry):
                if name not in ("Write", "Edit", "NotebookEdit"):
                    continue
                file_path = payload.get("file_path") or payload.get("notebook_path")
                token = comment_token(file_path)
                if not token:
                    continue
                added = added_lines(payload, name)
                if not added:
                    continue
                whole = (
                    payload.get("content")
                    or payload.get("new_string")
                    or payload.get("new_source")
                    or ""
                ).split("\n")
                for body, following in harvest(added, token, whole):
                    key = (file_path, body)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "id": f"{session}:{len(rows)}",
                            "source": "code_comment",
                            "project": project,
                            "session": session,
                            "ts": entry.get("timestamp"),
                            "file": file_path,
                            "tool": name,
                            "comment": body[:600],
                            "code_after": following[:800],
                            "words": len(body.split()),
                        }
                    )

    out = os.path.join(FINDINGS, "code_comments.jsonl")
    write_jsonl(out, rows)
    print(json.dumps({"comments": len(rows), "files": len({r["file"] for r in rows})}))
    print(f"wrote -> {out}")


if __name__ == "__main__":
    main()
