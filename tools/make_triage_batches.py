"""Slice candidates into compact batches for the triage pass.

Triage only needs enough context to answer "is this the user correcting the model?"
- the assistant turn that provoked it, what the user said, and what the model did
next. Shipping the full +/-3 window would quadruple the token cost for judgment
the triage model does not make.

Usage: python3 tools/make_triage_batches.py [batch_size]
Writes: findings/triage_in/batch_NNN.json
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, ensure_findings_dir, is_user_turn  # noqa: E402

PROMPT_CLIP = 1400
BEFORE_CLIP = 900
AFTER_CLIP = 500


def last_claude_before(window):
    """The model turn that provoked the prompt: last claude turn before the
    final user turn in the window."""
    user_idx = max(
        (i for i, t in enumerate(window) if is_user_turn(t)), default=None
    )
    if user_idx is None:
        return None
    for turn in reversed(window[:user_idx]):
        if turn["role"] == "claude":
            return turn
    return None


def first_claude_after(window):
    user_idx = max(
        (i for i, t in enumerate(window) if is_user_turn(t)), default=None
    )
    if user_idx is None:
        return None
    for turn in window[user_idx + 1 :]:
        if turn["role"] == "claude":
            return turn
    return None


def compact(cand):
    before = last_claude_before(cand["window"])
    after = first_claude_after(cand["window"])
    return {
        "id": cand["id"],
        "source": cand["source"],
        "flags": cand["flags"],
        "claude_said_before": (before or {}).get("text", "")[:BEFORE_CLIP],
        "claude_tools_before": [c["tool"] for c in (before or {}).get("calls", [])][:20],
        "user_said": cand["prompt"][:PROMPT_CLIP],
        "claude_said_after": (after or {}).get("text", "")[:AFTER_CLIP],
        "preceding_output_chars": cand["preceding_output_chars"],
        "preceding_tool_calls": cand["preceding_tool_calls"],
        "thread_ended_here": cand["thread_ended_here"],
    }


def already_triaged():
    """Ids that already have a verdict, so a re-run only pays for new material."""
    done = set()
    out_dir = os.path.join(FINDINGS, "triage_out")
    if not os.path.isdir(out_dir):
        return done
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(out_dir, name)))
        except ValueError:
            continue
        for row in data if isinstance(data, list) else []:
            if isinstance(row, dict) and row.get("id"):
                done.add(row["id"])
    return done


def main():
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    incremental = "--new-only" in sys.argv
    ensure_findings_dir()
    out_dir = os.path.join(FINDINGS, "triage_in")
    os.makedirs(out_dir, exist_ok=True)
    for stale in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, stale))

    cands = []
    for name in ("candidates_transcripts.jsonl", "candidates_chat.jsonl"):
        path = os.path.join(FINDINGS, name)
        if os.path.exists(path):
            cands += [json.loads(line) for line in open(path)]

    if incremental:
        done = already_triaged()
        skipped = sum(1 for c in cands if c["id"] in done)
        cands = [c for c in cands if c["id"] not in done]
        print(f"incremental: {skipped} already triaged, {len(cands)} to do")

    rows = [compact(c) for c in cands]
    batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
    total_chars = 0
    for i, batch in enumerate(batches):
        path = os.path.join(out_dir, f"batch_{i:03d}.json")
        with open(path, "w") as fh:
            json.dump(batch, fh, ensure_ascii=False, indent=1)
        total_chars += os.path.getsize(path)

    print(
        json.dumps(
            {
                "candidates": len(rows),
                "batches": len(batches),
                "batch_size": batch_size,
                "est_tokens_total": total_chars // 4,
                "est_tokens_per_batch": total_chars // 4 // max(1, len(batches)),
            }
        )
    )
    print(f"wrote -> {out_dir}")


if __name__ == "__main__":
    main()
