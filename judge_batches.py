#!/usr/bin/env python3
"""Drive a judging pass through an Ollama model (local or :cloud).

Reads every batch in <input_dir>, sends it to the model with <rubric_file> as
instructions, and writes the parsed verdicts to <output_dir>. Generic across the
triage and judge passes; the rubric defines the output shape.

Usage:
  python3 judge_batches.py <model> <input_dir> <output_dir> <rubric_file> [--limit N]

Example:
  python3 judge_batches.py minimax-m3:cloud findings/triage_in findings/triage_out tools/triage_rubric.md
"""

import json
import os
import re
import sys
import time
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def generate(model, prompt, timeout=900):
    payload = {"model": model, "prompt": prompt, "stream": False}
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("response", "")


def extract_json(text):
    """Pull the first JSON array or object out of a model reply, tolerating
    markdown fences and surrounding prose."""
    text = text.strip()
    # Strip ```json ... ``` fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    # Prefer a top-level array; fall back to an object.
    for candidate in (text,):
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    # Find the first [ ... ] or { ... } span.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except ValueError:
                        break
    raise ValueError("no JSON found in model reply")


def normalize(parsed):
    """Accept a bare list, or a dict wrapping the list under results/items."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("results", "items", "verdicts", "output"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    raise ValueError(f"unexpected model output shape: {type(parsed)}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 4:
        print(__doc__)
        sys.exit(2)
    model, in_dir, out_dir, rubric_path = args[:4]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    rubric = open(rubric_path).read()
    os.makedirs(out_dir, exist_ok=True)

    batches = sorted(n for n in os.listdir(in_dir) if n.endswith(".json"))
    if only:
        batches = [only]
    if limit:
        batches = batches[:limit]

    for name in batches:
        in_path = os.path.join(in_dir, name)
        out_path = os.path.join(out_dir, name)
        if os.path.exists(out_path):
            print(f"skip {name} (already judged)")
            continue

        items = json.load(open(in_path))
        prompt = (
            f"{rubric}\n\n"
            f"Here is the input batch (a JSON array of {len(items)} items).\n"
            f"Return a JSON array with exactly one verdict object per input item, "
            f"in the same order, ids copied verbatim. Do not omit or merge any items.\n\n"
            f"{json.dumps(items, ensure_ascii=False)}"
        )

        for attempt in range(3):
            try:
                reply = generate(model, prompt)
                verdicts = normalize(extract_json(reply))
                break
            except Exception as e:  # noqa: BLE001
                verdicts = None
                print(f"  attempt {attempt + 1} failed for {name}: {e}")
                time.sleep(5)
        if verdicts is None:
            print(f"FAILED {name} after 3 attempts")
            continue

        with open(out_path, "w") as fh:
            json.dump(verdicts, fh, ensure_ascii=False, indent=1)
        n = len(verdicts) if isinstance(verdicts, list) else "?"
        print(f"{name}: {len(items)} in -> {n} verdicts")

    print(f"done -> {out_dir}")


if __name__ == "__main__":
    main()
