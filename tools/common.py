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


def corpus_roots():
    """Every directory holding session transcripts, local machine first.

    Extra machines are added by unpacking their tarball and listing the path in
    findings/corpus_roots.json or DISCIPLINE_EXTRA_ROOTS (colon-separated). Each
    root may be either a `projects` directory or its parent.
    """
    roots = [("local", PROJECTS)]
    extra = []

    config = os.path.join(FINDINGS, "corpus_roots.json")
    if os.path.exists(config):
        extra += json.load(open(config))
    env = os.environ.get("DISCIPLINE_EXTRA_ROOTS", "")
    extra += [p for p in env.split(":") if p.strip()]

    for entry in extra:
        label, path = (entry["label"], entry["path"]) if isinstance(entry, dict) else (
            os.path.basename(entry.rstrip("/")),
            entry,
        )
        path = os.path.expanduser(path)
        if os.path.isdir(os.path.join(path, "projects")):
            path = os.path.join(path, "projects")
        if os.path.isdir(path):
            roots.append((label, path))
        else:
            print(f"WARNING: corpus root not found, skipped: {path}")
    return roots


def iter_transcripts():
    """Yield (project_dir, path) for every top-level session transcript.

    Sessions are deduped by filename across machines: transcript names are UUIDs,
    so a repeat means the same session was collected twice, not two sessions.
    """
    seen = set()
    for label, base in corpus_roots():
        for root, _dirs, files in os.walk(base):
            # Subagent transcripts live in subagents/; they are not the user talking.
            if os.path.basename(root) == "subagents":
                continue
            for name in files:
                if not name.endswith(".jsonl"):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, base)
                project = rel.split(os.sep)[0]
                if any(s in project for s in EXCLUDED_PROJECT_SUBSTRINGS):
                    continue
                if any(s in name for s in EXCLUDED_SESSIONS):
                    continue
                if name in seen:
                    continue
                seen.add(name)
                yield (project if label == "local" else f"{label}/{project}"), path


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


# the user saying they already told us. The judges were told to set
# repeat_after_instruction only when the window proves it, and they read that
# conservatively - they missed 12 of 21 real repeats, including an explicit
# "We've talked about thhis." Repeats gate the rule bar, so missing them decides
# which patterns become rules.
#
# Every marker must name a prior communication act or an ongoing failure. Bare
# "stop" is excluded: "Actually, stop. Give me a synopsis" is abandonment, not
# repetition.
REPEAT_MARKER = re.compile(
    r"("
    r"we[' ]?ve (talked|discussed|been over)"
    r"|we (talked|discussed) about (this|that|it)"
    # "i asked you" is a complaint; "what i asked for" is a noun phrase. Require
    # the addressee for told/asked, and keep the intransitive verbs separate.
    r"|\bi (already |just )?(told|asked) you\b"
    r"|\bi (already |just )?(said|mentioned|explained|stated)\b"
    r"|which is why i said"
    r"|as i (said|asked|mentioned|explained)|like i said"
    # Must be a complaint, not a reference. "a synopsis of what i asked for" is
    # a request; "that isnt what i asked for" is the user repeating themselves.
    r"|(that|this) (is|isn'?t|'?s not) what i asked"
    r"|not what i (asked|wanted|said)"
    r"|you keep\b|you (still|continue to)\b|still (do not|don'?t|doesn'?t|not)\b"
    r"|stop referencing|stop (doing|trying|using)"
    r"|i'?ve (said|told|asked)"
    r"|per (my|our) (earlier|previous|last)"
    r"|(said|told|asked|mentioned) (you |this |that )?(before|earlier|already)"
    r"|how many times"
    r")",
    re.I,
)


def says_repeat(text):
    """True when the user's own words say they had already told us."""
    return bool(REPEAT_MARKER.search(text or ""))


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
