"""Count a rhetorical tic in the model's own prose: "it's not X, it's Y".

A measured signal, not a complaint finder. It fires on what the model wrote
whether or not anyone objected, which is the property that makes the interrupt
and comment-shrink numbers worth trusting - and this tic in particular drew no
complaints at all, so a correction-based method cannot see it.

Two forms were measured before settling on one. The broad form - any "X, not Y"
- matched 12.1% of chat turns, but hand-checking 25 hits put precision near 20%:
most were load-bearing ("the type is `promql`, not `promql_query`"), where
naming the rejected option is what makes the sentence useful. Gating on that
would delete good writing.

The form kept here requires a copula on BOTH sides of the contrast, same
subject. That is the rhetorical figure rather than the disambiguation, and
hand-checking 20 hits put precision near 75%.

Not paraprosdokian, despite the resemblance. A paraprosdokian's tail forces you
to reinterpret its head; this just sets up a wrong answer to knock down. No
paraprosdokians were found, and finding them would need a judge rather than a
pattern - the surprise is semantic.

Usage: python3 tools/detect_reversals.py
Writes: findings/reversals.json
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    CONFIG,
    FINDINGS,
    config_required,
    ensure_findings_dir,
    extendable_pattern,
    iter_transcripts,
    read_jsonl,
    strip_trailers,
    text_of,
)

REVERSAL = extendable_pattern(
    "reversal",
    r"(",
    [
        # "it's not X, it's Y" - both halves carry the copula.
        r"\b(?:it'?s|that'?s|this is|the \w+ is|they'?re)\s+not\s+[^.;!?\n]{3,70}"
        r"[,;]\s*(?:it'?s|that'?s|this is|they'?re)\b",
        # Same figure split across a sentence boundary.
        r"\b(?:isn'?t|aren'?t|wasn'?t)\s+[^.!?\n]{3,70}[.!?]\s+(?:It'?s|That'?s|They'?re)\b",
        # "not a X - it's a Y"
        r"\bnot\s+(?:a|an|the)\s+\w[^.;!?\n]{0,40}[,;—-]{1,2}\s*(?:it'?s|that'?s)\s+(?:a|an|the)\b",
    ],
    r")",
)

CLAUDE_TRAILER = re.compile(r"Co-[Aa]uthored-[Bb]y:.*(Claude|anthropic)", re.I)
MIN_LEN = 40  # below this there is no room for the figure
CLIP = 150


def scan(rows):
    """(examined, hits, samples) for one body of text.

    Samples stay in corpus order and are not filtered - misfires included. The
    rate is a claim about writing, and the only way to argue with it is to read
    what actually matched. Near-identical hits are collapsed, since one moment
    written up twice would otherwise take two of the slots the report shows.
    """
    examined = hits = 0
    samples, seen = [], set()
    for text in rows:
        text = (text or "").strip()
        if len(text) < MIN_LEN:
            continue
        examined += 1
        match = REVERSAL.search(text)
        if not match:
            continue
        hits += 1
        sample = clip(text, match)
        # Short key on purpose: one moment written up twice diverges a clause or
        # two in, and only the samples are affected - never the counts.
        key = re.sub(r"\W+", "", sample.lower())[:40]
        if key in seen:
            continue
        seen.add(key)
        samples.append(sample)
    return examined, hits, samples


def clip(text, match):
    """Context around the match, snapped to word boundaries at both ends."""
    start = max(0, match.start() - 30)
    if start and not text[start - 1].isspace():
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < match.start() else start
    end = min(len(text), match.end() + 60)
    if end < len(text) and not text[end].isspace():
        space = text.rfind(" ", match.end(), end)
        end = space if space > match.end() else end
    return " ".join(text[start:end].split())[:CLIP]


def assistant_turns():
    """The model's chat prose. Not in any other findings file, and where this
    tic lives - it did not appear in a single commit body."""
    for _project, path in iter_transcripts():
        for entry in read_jsonl(path):
            if entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            yield text_of((entry.get("message") or {}).get("content"))


def jsonl_field(name, field):
    path = os.path.join(FINDINGS, name)
    if not os.path.exists(path):
        return []
    return [json.loads(line).get(field) for line in open(path)]


def commit_bodies():
    """Landed commits, split by who wrote them. The user's own are the control:
    the same repos, the same subject matter, a different author."""
    path = os.path.join(FINDINGS, "git_landed.jsonl")
    if not os.path.exists(path):
        return [], []
    emails = set(config_required("author_emails"))
    claude, human = [], []
    for line in open(path):
        row = json.loads(line)
        body = row.get("body") or ""
        if CLAUDE_TRAILER.search(body):
            claude.append(strip_trailers(body))
        elif row.get("author_email") in emails:
            human.append(strip_trailers(body))
    return claude, human


def main():
    ensure_findings_dir()
    claude_commits, human_commits = commit_bodies()

    corpora = [
        ("chat_prose", "Claude's chat turns", list(assistant_turns())),
        ("authored_artifacts", "Commit and PR bodies as written", jsonl_field("artifacts_authored.jsonl", "body")),
        ("landed_commits", "Co-authored commits that landed", claude_commits),
        ("user_commits", "The user's own commits (control)", human_commits),
        ("code_comments", "Code comments Claude wrote", jsonl_field("code_comments.jsonl", "comment")),
    ]

    out = {
        "note": (
            "Narrow form only: a copula on both sides of the contrast. The broad "
            "'X, not Y' matched 12.1% of chat turns at ~20% precision and was "
            "rejected - most instances name the rejected option because that is "
            "what makes the sentence useful."
        ),
        "hand_checked_precision": {"sample": 20, "genuine": 15, "rate": 0.75},
        "corpora": {},
    }
    for key, label, rows in corpora:
        examined, hits, samples = scan(rows)
        out["corpora"][key] = {
            "label": label,
            "examined": examined,
            "hits": hits,
            "rate": round(hits / examined, 4) if examined else None,
            "samples": samples[:12],
        }

    path = os.path.join(FINDINGS, "reversals.json")
    with open(path, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    for key, row in out["corpora"].items():
        rate = f"{100 * row['rate']:.1f}%" if row["rate"] is not None else "-"
        print(f"  {row['label']:38} {row['examined']:6} examined  {row['hits']:4} hits  {rate:>6}")
    print(f"wrote -> {path}")


if __name__ == "__main__":
    main()
