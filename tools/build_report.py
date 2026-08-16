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

from common import CONFIG, HOME, FINDINGS  # noqa: E402

# Claude encodes a project path as its slashes-to-dashes form. Drop the part
# that is just the user's home directory, plus anything else the config names.
PROJECT_STRIP = ["-" + HOME.strip("/").replace("/", "-") + "-"] + list(
    CONFIG["project_label_strip"]
)


def shorten_project(project):
    for prefix in PROJECT_STRIP:
        project = project.replace(prefix, "")
    return project

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
    project = shorten_project(inc.get("project") or "")
    if project:
        meta.append(f'<span class="proj">{esc(project)}</span>')
    conf = inc.get("confidence")
    if conf is not None:
        meta.append(f'<span>conf {float(conf):.2f}</span>')

    occurrences = int(inc.get("occurrences") or 1)
    if occurrences > 1:
        flags.insert(
            0,
            f'<span class="pill quiet">{occurrences} write-ups, one moment</span>',
        )
    if inc.get("corrected_by_user"):
        flags.insert(0, '<span class="pill user">Corrected by user</span>')

    note = inc.get("user_note")
    user_note = (
        f'<div class="user-note"><b>User correction</b>{esc(note)}</div>'
        if note
        else ""
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
          <dt>User wanted</dt><dd>{esc(inc.get('what_user_wanted'))}</dd>
          <dt>Rule candidate</dt><dd class="rule">{esc(inc.get('rule_candidate')) or '<em>none — not rule-fixable</em>'}</dd>
        </dl>
        {user_note}
      </article>"""


def pattern_html(pattern, incidents):
    open_attr = " open" if pattern["meets_rule_bar"] else ""
    bar = (
        (
            '<span class="pill greg">Rule — your call</span>'
            if pattern.get("decided_by") == "user"
            else '<span class="pill">Needs a rule</span>'
        )
        if pattern["meets_rule_bar"]
        else '<span class="pill quiet">No rule yet</span>'
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
          <b class="{'hot' if pattern['repeats'] else ''}">{pattern['repeats']}</b> noncompliant ·
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

    interrupts = load("interrupts.jsonl")
    # One outlier spans a resumed session, so its clock covers the gap between
    # sittings rather than a run. Excluded from the timing stats, kept in the count.
    timed = sorted(
        r["seconds_running"]
        for r in interrupts
        if r.get("seconds_running") is not None and r["seconds_running"] < 7200
    )
    calls = sorted(r["tool_calls_since_prompt"] for r in interrupts)

    def pct(values, p):
        return values[int(len(values) * p)] if values else 0

    int_stats = {
        "n": len(interrupts),
        "sessions": len({r["session"] for r in interrupts}),
        "median_s": pct(timed, 0.5),
        "p90_s": pct(timed, 0.9),
        "median_calls": pct(calls, 0.5),
        "p90_calls": pct(calls, 0.9),
        "over_3min": sum(1 for s in timed if s >= 180),
        "with_writes": sum(1 for r in interrupts if r.get("file_writes_since_prompt")),
    }

    # Corpus window, taken from the incidents themselves rather than assumed.
    days = sorted(j["ts"][:10] for j in judged if j.get("ts"))
    window = f"{days[0]} \u2192 {days[-1]}" if days else ""

    # Funnel. Each stage is counted from the file that stage wrote, so a missing
    # stage shows 0 rather than a number carried over from a previous run.
    candidates = len(load("candidates_transcripts.jsonl")) + len(load("candidates_chat.jsonl"))
    triaged_out = len(load("judged.jsonl"))

    def profile(label):
        """Style profile by label. Looked up by name, never by list position -
        the order the profiles are written in is not part of the contract."""
        for prof in style.get("profiles", []):
            if prof.get("label") == label:
                return prof
        return {}

    user_p = profile("user_hand_written")
    claude_p = profile("claude_co_authored")
    other_p = profile("other_humans_same_repos")

    def chars(prof):
        return int(prof.get("body_chars_median") or 0)

    widest = max(chars(user_p), chars(claude_p), chars(other_p), 1)

    def width(prof):
        return max(1, round(100 * chars(prof) / widest))

    def as_pct(value):
        return f"{round((value or 0) * 100)}%"

    checked = survival.get("checked_against_worktree", 0)
    lost = survival.get("did_not_survive", 0)
    survived = max(0, checked - lost)
    widest_c = max(survived, lost, 1)

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
        .replace("{{INT_N}}", str(int_stats["n"]))
        .replace("{{INT_SESSIONS}}", str(int_stats["sessions"]))
        .replace("{{INT_MED_S}}", str(int_stats["median_s"]))
        .replace("{{INT_P90_MIN}}", f"{int_stats['p90_s'] / 60:.1f}")
        .replace("{{INT_MED_CALLS}}", str(int_stats["median_calls"]))
        .replace("{{INT_P90_CALLS}}", str(int_stats["p90_calls"]))
        .replace("{{INT_OVER3}}", str(int_stats["over_3min"]))
        .replace("{{INT_WRITES}}", str(int_stats["with_writes"]))
        .replace("{{INT_MED_W}}", str(max(1, round(
            100 * int_stats["median_s"] / (int_stats["p90_s"] or 1)))))
        .replace("{{WINDOW}}", window)
        .replace("{{CANDIDATES}}", f"{candidates:,}")
        .replace("{{TRIAGED}}", f"{triaged_out:,}")
        .replace("{{CLAUDE_CHARS}}", str(chars(claude_p)))
        .replace("{{USER_CHARS}}", str(chars(user_p)))
        .replace("{{OTHER_CHARS}}", str(chars(other_p)))
        .replace("{{CLAUDE_N}}", f"{claude_p.get('n', 0):,}")
        .replace("{{USER_N}}", f"{user_p.get('n', 0):,}")
        .replace("{{OTHER_N}}", f"{other_p.get('n', 0):,}")
        .replace("{{CLAUDE_W}}", str(width(claude_p)))
        .replace("{{USER_W}}", str(width(user_p)))
        .replace("{{OTHER_W}}", str(width(other_p)))
        .replace("{{CLAUDE_LINES}}", str(int(claude_p.get("body_lines_median") or 0)))
        .replace("{{USER_LINES}}", str(int(user_p.get("body_lines_median") or 0)))
        .replace("{{CLAUDE_EMPTY}}", as_pct(claude_p.get("pct_no_body")))
        .replace("{{USER_EMPTY}}", as_pct(user_p.get("pct_no_body")))
        .replace("{{COMMENT_BLOCKS}}", f"{survival.get('authored_blocks', 0):,}")
        .replace("{{COMMENT_CHECKED}}", f"{checked:,}")
        .replace("{{COMMENT_SURVIVED}}", f"{survived:,}")
        .replace("{{COMMENT_LOST}}", f"{lost:,}")
        .replace("{{COMMENT_SURV_W}}", str(max(1, round(100 * survived / widest_c))))
        .replace("{{COMMENT_LOST_W}}", str(max(1, round(100 * lost / widest_c))))
        .replace("{{RATIO}}", str(style.get("ratios", {}).get("body_chars_median", "")))
    )

    out = os.path.join(FINDINGS, "report.html")
    with open(out, "w") as fh:
        fh.write(page)
    print(f"wrote {len(page) // 1024} KB -> {out}")
    print(f"{len(judged)} incidents across {len(patterns)} patterns")


if __name__ == "__main__":
    main()
