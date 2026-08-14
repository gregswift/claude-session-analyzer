"""Shared helpers for the discipline sweep pipeline."""

import json
import os
import re

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDINGS = os.path.join(REPO, "findings")

# This grilling session designed the sweep; its contents would poison it.
EXCLUDED_SESSIONS = {"6977985e-4cc2-4c1c-bce2-898b11f8e368"}

# Forks with a separate upstream remote. The user curated those comments himself,
# so they are not evidence about the model's output.
EXCLUDED_PROJECT_SUBSTRINGS = ("-Development-up-",)

WINDOW_START = "2026-07-08"

PROFANITY = re.compile(
    r"\b(fuck\w*|shit\w*|wtf|ffs|wth|goddamn\w*|dammit|damn it|bullshit"
    r"|ugh|argh|christ|jesus|seriously|for the love of)\b",
    re.I,
)

NEGATION_LEAD = re.compile(
    r"^\W*(no\b|nope|nah|wrong|stop\b|don'?t\b|do not\b|that'?s not|thats not"
    r"|why (did|are|is|would|the)|i (told|asked|said|already)|you (did|keep|still|again)"
    r"|again\b|not what|never mind|nevermind|revert|undo)",
    re.I,
)

CORRECTION_PHRASE = re.compile(
    r"(i (told|asked) you|i already (said|told)|you (keep|still|again)"
    r"|stop doing|don'?t do that|that'?s not what|thats not what"
    r"|why did you|you were told|as i said|like i said|i said\b"
    r"|you ignored|you didn'?t|you did not|not what i (asked|wanted|said)"
    r"|read (the|my) (instruction|prompt|request)|scope creep|over ?engineer"
    r"|too (verbose|long|much)|i didn'?t ask)",
    re.I,
)


def iter_transcripts():
    """Yield (project_dir, path) for every top-level session transcript."""
    for root, _dirs, files in os.walk(PROJECTS):
        # Subagent transcripts live in subagents/; they are not the user talking.
        if os.path.basename(root) == "subagents":
            continue
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, PROJECTS)
            project = rel.split(os.sep)[0]
            if any(s in project for s in EXCLUDED_PROJECT_SUBSTRINGS):
                continue
            if any(s in name for s in EXCLUDED_SESSIONS):
                continue
            yield project, path


def read_jsonl(path):
    with open(path, errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def text_of(content):
    """Flatten a message content field to plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            out.append(block.get("text") or "")
    return "\n".join(out)


def is_real_prompt(entry):
    """True for a message the user actually typed, not a tool result or system inject."""
    if entry.get("type") != "user":
        return False
    if entry.get("isSidechain"):
        return False
    if entry.get("toolUseResult") is not None:
        return False
    message = entry.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        # A tool_result-only turn carries no typed text.
        if not any(
            isinstance(b, dict) and b.get("type") == "text" for b in content
        ):
            return False
    body = text_of(content).strip()
    if not body:
        return False
    # Harness injections and command scaffolding, not typed input.
    if body.startswith("<") or body.startswith("Caveat:"):
        return False
    return True


def tool_uses(entry):
    """Yield (name, input_dict) for tool_use blocks in an assistant entry."""
    message = entry.get("message") or {}
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block.get("name") or "", block.get("input") or {}


TRAILER = re.compile(
    r"^\s*(Co-Authored-By|Co-authored-by|Claude-Session|Generated with|Signed-off-by"
    r"|https://claude\.ai/code|🤖)",
    re.I,
)


def strip_trailers(text):
    """Drop harness-mandated trailers. They are not authored prose, and leaving
    them on one side of a comparison makes every commit look rewritten."""
    kept = [l for l in (text or "").splitlines() if not TRAILER.match(l)]
    return "\n".join(kept).strip()


def ensure_findings_dir():
    os.makedirs(FINDINGS, exist_ok=True)
    return FINDINGS


def write_jsonl(path, rows):
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)
