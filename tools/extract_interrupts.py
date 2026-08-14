"""Extract every point where the user hit stop, with what Claude was doing at the time.

The user's own taxonomy of why they interrupt:

  1. "You are doing something I dont want you to do."
  2. "I'm realizing i should have tried to make my last response clearer or more
     detailed."
  3. "I feel like you are running down a path that needs more information or
     context otherwise its gonna be a lot of wasted work. I just wanted to stop
     you as you were rolling through the last 5 minutes worth of work because of
     this. Part of the problem is i have you on automode."

Only 1 and 3 are Claude's failures; 2 is the user correcting themselves. The difference
needs judgement, but the COST does not: how long Claude had been running and how
much it had done before they pulled the handle are both measurable, and that is
exactly what type 3 is about.

An interrupt leaves no words to complain with, so this is a silence-independent
signal by construction - it exists precisely where the user said nothing.

Usage: python3 tools/extract_interrupts.py
Writes: findings/interrupts.jsonl
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    FINDINGS,
    ensure_findings_dir,
    is_interrupt,
    is_real_prompt,
    iter_transcripts,
    read_jsonl,
    text_of,
    tool_uses,
    write_jsonl,
)

CLIP = 700


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def main():
    ensure_findings_dir()
    rows = []

    for project, path in iter_transcripts():
        entries = list(read_jsonl(path))
        session = os.path.basename(path)[:-6]

        # Walk forward tracking the last thing the user actually typed and everything
        # Claude has done since.
        last_prompt = None
        last_prompt_ts = None
        since_prompt = []  # (tool_name, payload_snippet, ts)
        last_text = ""

        for entry in entries:
            if is_real_prompt(entry):
                last_prompt = text_of((entry.get("message") or {}).get("content"))
                last_prompt_ts = parse_ts(entry.get("timestamp"))
                since_prompt = []
                last_text = ""
                continue

            if is_interrupt(entry):
                stopped_at = parse_ts(entry.get("timestamp"))
                elapsed = None
                if stopped_at and last_prompt_ts:
                    elapsed = round((stopped_at - last_prompt_ts).total_seconds())
                writes = sum(
                    1 for t, _ in since_prompt if t in ("Edit", "Write", "NotebookEdit")
                )
                rows.append(
                    {
                        "id": f"{session}:{(entry.get('uuid') or '')[:12]}",
                        "project": project,
                        "session": session,
                        "ts": entry.get("timestamp"),
                        "seconds_running": elapsed,
                        "tool_calls_since_prompt": len(since_prompt),
                        "file_writes_since_prompt": writes,
                        "tools_used": [t for t, _ in since_prompt][:40],
                        "user_last_said": (last_prompt or "")[:CLIP],
                        "claude_last_said": last_text[:CLIP],
                        "claude_was_doing": [
                            {"tool": t, "input": p} for t, p in since_prompt[-4:]
                        ],
                    }
                )
                continue

            if entry.get("type") == "assistant" and not entry.get("isSidechain"):
                text = text_of((entry.get("message") or {}).get("content"))
                if text:
                    last_text = text
                for name, payload in tool_uses(entry):
                    since_prompt.append((name, json.dumps(payload)[:200]))

    out = os.path.join(FINDINGS, "interrupts.jsonl")
    write_jsonl(out, rows)

    timed = [r["seconds_running"] for r in rows if r["seconds_running"] is not None]
    timed.sort()
    calls = sorted(r["tool_calls_since_prompt"] for r in rows)

    def pct(values, p):
        return values[int(len(values) * p)] if values else 0

    print(
        json.dumps(
            {
                "interrupts": len(rows),
                "sessions_affected": len({r["session"] for r in rows}),
                "seconds_running_median": pct(timed, 0.5),
                "seconds_running_p90": pct(timed, 0.9),
                "tool_calls_median": pct(calls, 0.5),
                "tool_calls_p90": pct(calls, 0.9),
                "interrupts_after_10plus_calls": sum(1 for c in calls if c >= 10),
                "interrupts_with_file_writes": sum(
                    1 for r in rows if r["file_writes_since_prompt"] > 0
                ),
            },
            indent=2,
        )
    )
    print(f"wrote -> {out}")


if __name__ == "__main__":
    main()
