"""Replay a candidate enforcement rule over the corpus: would it have fired, and
would it have been right?

A rule that sounds obviously correct can carry no information at all. "Block
commit bodies over 400 characters" was proposed from a real measurement - the
model's bodies run 3.84x longer than the user's - and backtesting it showed it
firing on 54 of 65 commits at 19% precision against an 18% base rate. Lift 1.00.
It would have interrupted twelve times a week to say nothing. Length is real;
length is just not what makes the user rewrite a commit.

So no rule ships on a plausible story. It ships on lift.

Rules are declared in JSON, not written as code, so adding one is editing a file
rather than extending this tool. This does NOT run as part of the report - it
answers a question that is asked while designing a rule, not every time the
findings are rebuilt.

    python3 tools/backtest_rules.py                 # all rules in the file
    python3 tools/backtest_rules.py --rules PATH
    python3 tools/backtest_rules.py --sweep chars   # try every threshold

Reads: findings/, and hook_rules.json (or --rules PATH)
"""

import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS, positional_args, _flag_arg  # noqa: E402

# --- what a rule can look at -------------------------------------------------
# Each target yields records carrying an id, a session, a timestamp, some text
# and some numbers. A hook only ever sees a tool call's input, so these are
# deliberately limited to what one could actually inspect at the time.


def _load(name):
    path = os.path.join(FINDINGS, name)
    if not os.path.exists(path):
        return []
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in open(path)]
    return json.load(open(path))


def target_written_artifacts():
    """Commit messages and PR bodies as the model wrote them, with what landed.

    Labelled: `rewritten` is true when the user changed the body before or after
    it landed.
    """
    for row in _load("rewrites.jsonl"):
        body = row.get("authored") or ""
        yield {
            "id": row.get("id"),
            "session": row.get("session"),
            "ts": row.get("ts"),
            "kind": row.get("kind"),
            "text": body,
            "chars": int(float(row.get("authored_chars") or len(body))),
            "lines": body.count("\n") + 1 if body else 0,
            "words": len(body.split()),
            "_label_rewritten": str(row.get("rewritten")).lower() == "true",
            "landed": row.get("outcome") == "landed",
        }


def target_code_comments():
    """Comment blocks the model wrote, with what became of them."""
    for row in _load("comment_outcomes.jsonl"):
        yield {
            "id": row.get("id"),
            "session": row.get("session"),
            "ts": row.get("ts"),
            "kind": "code_comment",
            "text": "",  # outcomes carry no text; length rules still work
            "chars": row.get("chars") or 0,
            "words": row.get("words") or 0,
            "lines": 0,
            "_label_shrunk": bool(row.get("shrunk")),
            "_label_not_survived": row.get("checked") and row.get("survived") is False,
        }


def target_comment_text():
    """Comment blocks with their text, for rules that match on wording."""
    outcomes = {r["id"]: r for r in _load("comment_outcomes.jsonl")}
    for row in _load("code_comments.jsonl"):
        out = outcomes.get(row["id"], {})
        text = row.get("comment") or ""
        yield {
            "id": row.get("id"),
            "session": row.get("session"),
            "ts": row.get("ts"),
            "kind": "code_comment",
            "text": text,
            "chars": len(text),
            "words": row.get("words") or 0,
            "lines": text.count("\n") + 1 if text else 0,
            "_label_shrunk": bool(out.get("shrunk")),
            "_label_not_survived": out.get("checked") and out.get("survived") is False,
        }


TARGETS = {
    "written_artifacts": target_written_artifacts,
    "code_comments": target_code_comments,
    "comment_text": target_comment_text,
}

# --- what counts as the rule having been right -------------------------------
# Every label is a proxy. The user does not rewrite everything that is wrong, so
# these UNDERSTATE precision. That bias hits the base rate too, which is why lift
# is the number to read and precision alone is not.

LABELS = {
    "rewritten": ("the user changed this body", lambda r: r.get("_label_rewritten")),
    "shrunk": ("a shorter version replaced it", lambda r: r.get("_label_shrunk")),
    "not_survived": ("it is not in the file now", lambda r: r.get("_label_not_survived")),
    "near_episode": ("a confirmed episode in the same session", None),
    "near_interrupt": ("the user hit stop soon after", None),
}


def episode_sessions():
    return {
        i.get("session") for i in _load("incidents.jsonl") if i.get("session")
    }


def interrupt_sessions():
    return {r.get("session") for r in _load("interrupts.jsonl") if r.get("session")}


def attach_session_labels(records):
    """Session-level labels, which are coarse and are reported as such.

    A fire in a session that also contains a confirmed episode is weak evidence
    at best - sessions are long. It is here because for rules about tool calls
    there is no finer-grained ground truth available, and a coarse label named
    honestly beats a precise one invented.
    """
    eps, ints = episode_sessions(), interrupt_sessions()
    for r in records:
        r["_label_near_episode"] = r.get("session") in eps
        r["_label_near_interrupt"] = r.get("session") in ints
    return records


# --- conditions --------------------------------------------------------------

OPS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
}


def matches(record, when):
    """`when` is {field: {op: value}} or {field: {"re": pattern}}, all ANDed."""
    for field, test in when.items():
        value = record.get(field)
        for op, wanted in test.items():
            if op == "re":
                if not re.search(wanted, str(value or ""), re.I | re.M):
                    return False
            elif op == "not_re":
                if re.search(wanted, str(value or ""), re.I | re.M):
                    return False
            elif op in OPS:
                if value is None or not OPS[op](value, wanted):
                    return False
            else:
                sys.exit(f"unknown operator '{op}' in condition on '{field}'")
    return True


def weeks_spanned(records):
    days = sorted(r["ts"][:10] for r in records if r.get("ts"))
    if len(days) < 2:
        return 1.0
    span = datetime.date.fromisoformat(days[-1]) - datetime.date.fromisoformat(days[0])
    return max(span.days / 7, 1.0)


def evaluate(rule, records):
    """Base rate over the population the rule could ever apply to - NOT over the
    whole target.

    A rule scoped to landed commit messages, measured against a base rate taken
    over every artifact including PR bodies, scored 1.42x lift. Rescoped to the
    population it actually fires within, the same rule scores 1.00x. Mixing the
    two makes a worthless rule look promising, which is the one mistake this tool
    exists to catch.
    """
    label = rule.get("label", "rewritten")
    key = f"_label_{label}"
    scope = [
        r
        for r in records
        if r.get(key) is not None and matches(r, rule.get("applies_to") or {})
    ]
    if not scope:
        return None
    positives = sum(1 for r in scope if r[key])
    base = positives / len(scope)

    fired = [r for r in scope if matches(r, rule["when"])]
    tp = sum(1 for r in fired if r[key])
    weeks = weeks_spanned(scope)
    return {
        "rule": rule["name"],
        "target": rule["target"],
        "label": label,
        "population": len(scope),
        "base_rate": round(base, 3),
        "fires": len(fired),
        "true": tp,
        "precision": round(tp / len(fired), 3) if fired else None,
        "lift": round((tp / len(fired)) / base, 2) if fired and base else None,
        "recall": round(tp / positives, 3) if positives else None,
        "fires_per_week": round(len(fired) / weeks, 1),
    }


def load_records(target):
    if target not in TARGETS:
        sys.exit(f"unknown target '{target}'. Known: {', '.join(sorted(TARGETS))}")
    return attach_session_labels(list(TARGETS[target]()))


def report(results):
    print(
        f"{'rule':34} {'pop':>5} {'base':>6} {'fires':>6} {'prec':>6} "
        f"{'lift':>6} {'recall':>7} {'per wk':>7}"
    )
    for r in results:
        if r is None:
            continue
        lift = f"{r['lift']:.2f}x" if r["lift"] is not None else "-"
        prec = f"{100*r['precision']:.0f}%" if r["precision"] is not None else "-"
        rec = f"{100*r['recall']:.0f}%" if r["recall"] is not None else "-"
        flag = "" if (r["lift"] or 0) >= 1.5 else "   <- no better than chance"
        print(
            f"{r['rule'][:34]:34} {r['population']:5} {100*r['base_rate']:5.0f}% "
            f"{r['fires']:6} {prec:>6} {lift:>6} {rec:>7} {r['fires_per_week']:7.1f}{flag}"
        )
    print(
        "\nlift is precision divided by the base rate. 1.00x means the rule fires "
        "without\npredicting anything. Below about 1.5x a blocking hook costs more "
        "than it saves."
    )


def sweep(rule, field, records):
    """Try a range of thresholds instead of guessing one."""
    values = sorted({r[field] for r in records if isinstance(r.get(field), (int, float))})
    if not values:
        sys.exit(f"no numeric '{field}' on target '{rule['target']}'")
    step = max(1, len(values) // 12)
    out = []
    for cut in values[::step]:
        probe = dict(rule)
        probe["when"] = dict(rule.get("when") or {})
        probe["when"][field] = {"gt": cut}
        probe["name"] = f"{rule['name']} {field}>{cut}"
        out.append(evaluate(probe, records))
    return out


def main():
    rules_path = _flag_arg("--rules") or "hook_rules.json"
    if not os.path.exists(rules_path):
        sys.exit(
            f"no rules file at {rules_path}\n"
            "  Copy hook_rules.example.json and edit it, or pass --rules PATH."
        )
    rules = json.load(open(rules_path))
    if isinstance(rules, dict):
        rules = rules.get("rules", [])

    wanted = positional_args()
    if wanted:
        rules = [r for r in rules if r["name"] in wanted]
        if not rules:
            sys.exit(f"no rule named {wanted} in {rules_path}")

    sweep_field = _flag_arg("--sweep")
    cache, results = {}, []
    for rule in rules:
        target = rule["target"]
        if target not in cache:
            cache[target] = load_records(target)
        if sweep_field:
            results += sweep(rule, sweep_field, cache[target])
        else:
            results.append(evaluate(rule, cache[target]))

    if not any(results):
        sys.exit(
            "no records carried the requested label.\n"
            f"  findings: {FINDINGS}\n"
            "  If that directory is empty or wrong, run from where findings/ lives,\n"
            "  or pass --output PATH / set CSA_FINDINGS."
        )
    report(results)


if __name__ == "__main__":
    main()
