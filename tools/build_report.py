"""Generate findings/report.html from the pipeline's output.

The report is generated rather than written by hand so it stays true to the data
after a re-run. Every confirmed incident is listed in full: a summary kind is not
enough to decide whether a pattern is worth fixing.

Usage: python3 tools/build_report.py
Writes: findings/report.html
"""

import collections
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FINDINGS  # noqa: E402

CLASS_NAME = {
    "A": "what Claude did",
    "A-comments": "code comments",
    "B": "what Claude wrote for humans",
}


def esc(text):
    return html.escape(str(text or "").strip())


def load(name, jsonl=True):
    path = os.path.join(FINDINGS, name)
    if not os.path.exists(path):
        return [] if jsonl else {}
    if jsonl:
        return [json.loads(line) for line in open(path)]
    return json.load(open(path))


def sev_band(value):
    if value >= 5:
        return "high"
    if value >= 3.5:
        return "mid"
    return "low"


def incident_html(inc, index):
    flags = []
    if inc.get("repeat_after_instruction"):
        flags.append('<span class="pill flag">Repeat after instruction</span>')
    if inc.get("fixable_by") == "hook":
        flags.append('<span class="pill">Needs a hook</span>')
    if inc.get("fixable_by") == "neither":
        flags.append('<span class="pill">Not rule-fixable</span>')

    sev = float(inc.get("severity") or 0)
    meta = [
        f'<span class="sev {sev_band(sev)}">sev {sev:.1f}</span>',
        f'<span>{esc((inc.get("ts") or "")[:10])}</span>',
        f'<span>{esc(inc.get("source") or "")}</span>',
    ]
    project = (inc.get("project") or "").replace("-Users-example-user-Development-", "")
    if project:
        meta.append(f'<span class="proj">{esc(project)}</span>')
    conf = inc.get("confidence")
    if conf is not None:
        meta.append(f'<span>conf {float(conf):.2f}</span>')

    occurrences = int(inc.get("occurrences") or 1)
    if occurrences > 1:
        flags.insert(
            0,
            f'<span class="pill quiet">{occurrences} turns, one episode</span>',
        )

    also = "".join(
        f'<blockquote class="said also">{esc(q)}</blockquote>'
        for q in (inc.get("also_said") or [])
    )

    return f"""
      <article class="inc" data-repeat="{str(bool(inc.get('repeat_after_instruction'))).lower()}" data-sev="{sev:.1f}" data-class="{esc(inc.get('class'))}">
        <div class="inc-head">
          <span class="idx">{index}</span>
          <div class="inc-meta">{''.join(meta)}</div>
          <div class="inc-flags">{''.join(flags)}</div>
        </div>
        <blockquote class="said">{esc(inc.get('evidence_quote'))}</blockquote>
        {also}
        <dl>
          <dt>Claude did</dt><dd>{esc(inc.get('what_claude_did'))}</dd>
          <dt>the user wanted</dt><dd>{esc(inc.get('what_greg_wanted'))}</dd>
          <dt>Rule candidate</dt><dd class="rule">{esc(inc.get('rule_candidate')) or '<em>none — not rule-fixable</em>'}</dd>
        </dl>
      </article>"""


def pattern_html(pattern, incidents):
    open_attr = " open" if pattern["meets_rule_bar"] else ""
    bar = (
        '<span class="pill">Clears the bar</span>'
        if pattern["meets_rule_bar"]
        else '<span class="pill quiet">Below the bar</span>'
    )
    incidents = sorted(
        incidents,
        key=lambda i: (
            not i.get("repeat_after_instruction"),
            -float(i.get("severity") or 0),
        ),
    )
    body = "".join(incident_html(inc, n + 1) for n, inc in enumerate(incidents))
    return f"""
    <details class="pat{' barred' if pattern['meets_rule_bar'] else ''}"{open_attr}>
      <summary>
        <span class="pat-kind">{esc(pattern['kind'])}</span>
        <span class="pat-class">{esc(CLASS_NAME.get(pattern['class'], pattern['class']))}</span>
        <span class="pat-nums">
          <b>{pattern['incidents']}</b> incidents ·
          <b>{pattern['sessions']}</b> sessions ·
          <b class="{'hot' if pattern['repeats'] else ''}">{pattern['repeats']}</b> repeats ·
          sev <b>{pattern['severity_median']}</b>
        </span>
        {bar}
      </summary>
      <div class="pat-body">{body}</div>
    </details>"""


def main():
    patterns = load("findings.jsonl")
    survival = load("comment_survival.json", jsonl=False)
    style = load("style_comparison.json", jsonl=False)

    # Deduped episodes are the unit of reporting. A single argument spans several
    # flagged messages; listing each one makes the report read as duplicated
    # because it is.
    judged = load("incidents.jsonl")
    raw_count = sum(1 for j in load("judged.jsonl") if j.get("confirmed"))
    if not judged:
        sys.exit("no findings/incidents.jsonl - run dedupe_incidents.py first")

    by_pattern = collections.defaultdict(list)
    for j in judged:
        by_pattern[(j.get("class", "A"), j.get("kind", "other"))].append(j)

    sections = "".join(
        pattern_html(p, by_pattern[(p["class"], p["kind"])]) for p in patterns
    )

    repeats = sum(1 for j in judged if j.get("repeat_after_instruction"))
    shrinks = survival.get("in_session_shrinks", 0)

    template = open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html")
    ).read()

    page = (
        template.replace("<!--INCIDENTS-->", sections)
        .replace("{{CONFIRMED}}", str(len(judged)))
        .replace("{{PATTERNS}}", str(len(patterns)))
        .replace("{{BAR}}", str(sum(1 for p in patterns if p["meets_rule_bar"])))
        .replace("{{REPEATS}}", str(repeats))
        .replace("{{SHRINKS}}", str(shrinks))
        .replace("{{RAW}}", str(raw_count))
        .replace("{{COLLAPSED}}", str(raw_count - len(judged)))
        .replace("{{CLAUDE_CHARS}}", str(int(style["profiles"][1]["body_chars_median"])))
        .replace("{{USER_CHARS}}", str(int(style["profiles"][0]["body_chars_median"])))
        .replace("{{RATIO}}", str(style["ratios"]["body_chars_median"]))
    )

    out = os.path.join(FINDINGS, "report.html")
    with open(out, "w") as fh:
        fh.write(page)
    print(f"wrote {len(page) // 1024} KB -> {out}")
    print(f"{len(judged)} incidents across {len(patterns)} patterns")


if __name__ == "__main__":
    main()
