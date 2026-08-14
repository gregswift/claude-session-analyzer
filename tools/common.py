"""Shared helpers for the claude-session-analyzer pipeline."""

import json
import os
import re
import sys

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")


def _output_arg():
    """`--output PATH` / `-o PATH`, honoured by every tool in the pipeline."""
    for flag in ("--output", "-o"):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            if i + 1 < len(sys.argv):
                return sys.argv[i + 1]
    return None


# Findings are generated output: they land under the working directory unless
# told otherwise, never next to the code. Precedence: --output, then
# CSA_FINDINGS, then ./findings.
FINDINGS = os.path.abspath(
    _output_arg() or os.environ.get("CSA_FINDINGS") or "findings"
)

CONFIG_PATH = os.environ.get("CSA_CONFIG") or "csa.config.json"

# Everything here is per-user. No corpus, employer, project or person belongs in
# this file - see csa.config.example.json.
CONFIG_DEFAULTS = {
    # Required by the tool that uses them; absent means "fail loudly".
    "author_emails": None,   # compare_style: which commits are hand-written
    "pr_repos": None,        # collect_prs: repos to sweep, "owner/name"
    "pr_author": None,       # collect_prs: GitHub login to filter on
    "window_start": None,    # collect_git, collect_prs: ISO date lower bound
    # Optional; empty means no filtering.
    "extra_roots": [],
    "excluded_sessions": [],
    "excluded_project_substrings": [],
    "artifact_excluded_projects": [],
    "project_label_strip": [],
}


def load_config():
    cfg = dict(CONFIG_DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as fh:
            cfg.update(json.load(fh))
    return cfg


CONFIG = load_config()


def config_required(key):
    """A missing value is a hard stop, not a silent default. Guessing here would
    sweep the wrong corpus and the run would still report success."""
    value = CONFIG.get(key)
    if value in (None, "", [], {}):
        raise SystemExit(
            f"ERROR: '{key}' is not set.\n"
            f"  Add it to {os.path.abspath(CONFIG_PATH)} "
            f"(copy csa.config.example.json to start), or set CSA_CONFIG to "
            f"another path."
        )
    return value


EXCLUDED_SESSIONS = set(CONFIG["excluded_sessions"])
EXCLUDED_PROJECT_SUBSTRINGS = tuple(CONFIG["excluded_project_substrings"])
ARTIFACT_EXCLUDED_PROJECTS = tuple(CONFIG["artifact_excluded_projects"])


def artifacts_allowed(project):
    """False for projects whose written artifacts are ruled out as evidence -
    ones the user did not review to the standard they apply elsewhere. Their
    TRANSCRIPTS still count; only the authored artifacts are excluded."""
    if not ARTIFACT_EXCLUDED_PROJECTS:
        return True
    return not any(s in (project or "") for s in ARTIFACT_EXCLUDED_PROJECTS)


def window_start():
    return config_required("window_start")

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
    `extra_roots` in the config file, or in CSA_EXTRA_ROOTS (colon-separated).
    Each root may be either a `projects` directory or its parent.
    """
    roots = [("local", PROJECTS)]
    extra = list(CONFIG["extra_roots"])

    # Compatibility: the corpus root list used to live in the findings dir.
    legacy = os.path.join(FINDINGS, "corpus_roots.json")
    if os.path.exists(legacy):
        with open(legacy) as fh:
            extra += json.load(fh)
    env = os.environ.get("CSA_EXTRA_ROOTS", "")
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
    # The harness writes these when the user hits stop. They are not messages - they
    # carry no words to judge - but 65 of them were being counted as prompts and
    # generating candidates with an empty quote.
    if INTERRUPT_MARKER.match(body):
        return False
    return True


INTERRUPT_MARKER = re.compile(r"^\[Request interrupted by user")


def is_interrupt(entry):
    """The user hit stop. Not a message, but a signal: they cut Claude off mid-action,
    which they would rarely bother to complain about afterwards."""
    if entry.get("type") != "user" or entry.get("isSidechain"):
        return False
    if entry.get("toolUseResult") is not None:
        return False
    body = text_of((entry.get("message") or {}).get("content")).strip()
    return bool(INTERRUPT_MARKER.match(body))


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


# --- compatibility with findings written before the user_* rename -------------
# Earlier versions of this tool named the person it studies after its author:
# role "greg", greg_said, what_greg_wanted, greg_note, corrected_by_greg, and
# greg_review.json. Those names are wrong for a tool anyone can run, so
# everything is WRITTEN as user_*. An existing findings directory is still READ
# under the old names, and is never rewritten in place.

USER_ROLE = "user"
LEGACY_USER_ROLES = ("user", "greg")


def is_user_turn(turn):
    """True for a turn the person typed, under either the current or old role."""
    return turn.get("role") in LEGACY_USER_ROLES


def field(obj, name, *legacy, default=None):
    """Read a field by its current name, accepting names earlier versions wrote."""
    for key in (name,) + legacy:
        if key in obj:
            return obj[key]
    return default


def findings_path(name, *legacy):
    """Path to a findings file, preferring the current name but falling back to
    one an earlier version wrote, so old rulings keep loading without migration."""
    current = os.path.join(FINDINGS, name)
    if os.path.exists(current):
        return current
    for old in legacy:
        candidate = os.path.join(FINDINGS, old)
        if os.path.exists(candidate):
            print(f"  reading legacy {old} (writing {name} from now on)")
            return candidate
    return current


def ensure_findings_dir():
    os.makedirs(FINDINGS, exist_ok=True)
    return FINDINGS


def write_jsonl(path, rows):
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)
