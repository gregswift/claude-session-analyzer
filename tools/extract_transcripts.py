"""Extract candidate correction windows from local Claude Code transcripts.

Finders are tuned for recall, not precision - the triage pass downstream is what
throws things away. Severity is deliberately NOT computed here: profanity rate
quadrupled mid-corpus, so anything derived from it would be uncalibrated across
time. See findings/report.md.

Usage: python3 tools/extract_transcripts.py
Writes: findings/candidates_transcripts.jsonl
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    CORRECTION_PHRASE,
    NEGATION_LEAD,
    PROFANITY,
    USER_ROLE,
    ensure_findings_dir,
    is_user_turn,
    is_real_prompt,
    iter_transcripts,
    read_jsonl,
    text_of,
    tool_uses,
    write_jsonl,
)

SHORT_PROMPT = 400  # chars
LONG_OUTPUT = 2000  # chars of assistant text + tool payload since last prompt

BACK = 3  # turns of context before the flagged prompt
FORWARD = 3  # turns after, so a repeat offense is visible in the window

ASSISTANT_CLIP = 1800
TOOL_CLIP = 300


def summarize_turns(entries):
    """Collapse a transcript into an ordered list of coarse turns."""
    turns = []
    for entry in entries:
        kind = entry.get("type")
        if kind == "user" and is_real_prompt(entry):
            turns.append(
                {
                    "role": USER_ROLE,
                    "text": text_of((entry.get("message") or {}).get("content")),
                    "ts": entry.get("timestamp"),
                    "uuid": entry.get("uuid"),
                }
            )
        elif kind == "assistant" and not entry.get("isSidechain"):
            text = text_of((entry.get("message") or {}).get("content"))
            calls = []
            for name, payload in tool_uses(entry):
                calls.append({"tool": name, "input": json.dumps(payload)[:TOOL_CLIP]})
            if not text and not calls:
                continue
            turns.append(
                {
                    "role": "claude",
                    "text": text[:ASSISTANT_CLIP],
                    "full_len": len(text),
                    "calls": calls,
                    "ts": entry.get("timestamp"),
                }
            )
    return turns


def preceding_output_size(turns, index):
    """Chars of assistant output between the previous the user turn and this one."""
    total = 0
    calls = 0
    for turn in reversed(turns[:index]):
        if is_user_turn(turn):
            break
        total += turn.get("full_len", len(turn.get("text", "")))
        for call in turn.get("calls", []):
            total += len(call["input"])
            calls += 1
    return total, calls


def turns_to_next_prompt(turns, index):
    """How many Claude turns the user sat through before speaking again."""
    count = 0
    for turn in turns[index + 1 :]:
        if is_user_turn(turn):
            return count
        count += 1
    return None  # thread ended here - possible abandonment


def flags_for(text, out_size, out_calls):
    flags = []
    if PROFANITY.search(text):
        flags.append("profanity")
    if NEGATION_LEAD.search(text):
        flags.append("negation_lead")
    if CORRECTION_PHRASE.search(text):
        flags.append("correction_phrase")
    if len(text) < SHORT_PROMPT and out_size > LONG_OUTPUT:
        flags.append("short_after_long")
    if out_calls >= 12 and len(text) < SHORT_PROMPT:
        flags.append("short_after_many_calls")
    return flags


def main():
    ensure_findings_dir()
    candidates = []
    stats = {"files": 0, "prompts": 0, "flagged": 0}

    for project, path in iter_transcripts():
        entries = list(read_jsonl(path))
        turns = summarize_turns(entries)
        if not turns:
            continue
        stats["files"] += 1

        cwd = next((e.get("cwd") for e in entries if e.get("cwd")), None)
        branch = next((e.get("gitBranch") for e in entries if e.get("gitBranch")), None)
        session = os.path.basename(path)[:-6]

        for i, turn in enumerate(turns):
            if not is_user_turn(turn):
                continue
            stats["prompts"] += 1
            out_size, out_calls = preceding_output_size(turns, i)
            flags = flags_for(turn["text"], out_size, out_calls)
            if not flags:
                continue
            stats["flagged"] += 1
            candidates.append(
                {
                    # Keyed on the message uuid, never on position. Turn
                    # indices shift whenever the prompt filter changes, which
                    # orphans every verdict and ruling attached to them.
                    "id": f"{session}:{turn.get('uuid', '')[:12]}",
                    "source": "transcript",
                    "project": project,
                    "session": session,
                    "cwd": cwd,
                    "branch": branch,
                    "ts": turn["ts"],
                    "turn": i,
                    "flags": flags,
                    "prompt": turn["text"][:4000],
                    "preceding_output_chars": out_size,
                    "preceding_tool_calls": out_calls,
                    "turns_before_next_prompt": turns_to_next_prompt(turns, i),
                    "thread_ended_here": turns_to_next_prompt(turns, i) is None,
                    "window": turns[max(0, i - BACK) : i + FORWARD + 1],
                }
            )

    out = os.path.join(ensure_findings_dir(), "candidates_transcripts.jsonl")
    write_jsonl(out, candidates)
    print(json.dumps(stats))
    print(f"wrote {len(candidates)} candidates -> {out}")


if __name__ == "__main__":
    main()
