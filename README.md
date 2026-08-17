# claude-session-analyzer

Sweeps your own Claude Code session transcripts and claude.ai chat exports for
the places you corrected the model, then triages, judges, dedupes, ranks and
reports on them. The output is an evidence base: which mistakes actually recur,
how often, and with what supporting quotes — as opposed to a list of rules
someone assumed would help.

It reads only your local corpus. Nothing is uploaded, and no findings are
committed.

## Setup

Python 3, standard library only. Nothing to install. `collect_prs.py` needs the
[`gh`](https://cli.github.com) CLI authenticated.

Run any tool with no config on a terminal and it will offer to build one,
deriving what it can and asking you to confirm: your commit emails from `git
config`, your login from `gh`, the date window from the earliest session in your
corpus, and the repo list by walking the directories your sessions ran in and
reading each `origin`. Nothing is written until you approve it.

If you would rather write it yourself, copy the template:

```sh
cp csa.config.example.json csa.config.json   # or ~/.claude-session-analyzer.json
```

### Where config comes from

Checked in order, first hit wins. The resolved path is printed on every run.

1. `--config PATH`
2. `CSA_CONFIG`
3. `./csa.config.json`
4. `~/.claude-session-analyzer.json`

| Key | Used by |
| --- | --- |
| `author_emails` | `compare_style` — which commits you hand-wrote |
| `pr_repos`, `pr_author` | `collect_prs` |
| `window_start` | `collect_git`, `collect_prs` |
| `extra_roots` | corpora copied from other machines |
| `excluded_sessions` | session ids to leave out |
| `excluded_project_substrings` | projects to skip entirely |
| `artifact_excluded_projects` | projects whose commits/PRs/comments are not evidence, though their transcripts still are |
| `project_label_strip` | cosmetic prefixes to drop from project names in the report |

A tool that needs a value you have not set stops with an error naming the key.
It will not fall back to a default and sweep the wrong corpus.

**In a non-interactive context** — an agent, cron, CI — nothing ever prompts. A
missing value is the same hard error, naming the key and the files that were
checked.

## How it works

The pipeline runs in stages, each writing to `findings/`. Stages that need a
model read a batch of JSON from `findings/*_in/` and expect the verdicts back in
`findings/*_out/` — the judging itself is done by whatever model you point at
those batches, not by this repo.

**Extract** — pull raw material out of the corpus.

| Tool | Writes |
| --- | --- |
| `extract_transcripts.py` | `candidates_transcripts.jsonl` |
| `extract_chat.py <export-dir>` | `candidates_chat.jsonl` |
| `extract_interrupts.py` | `interrupts.jsonl` |
| `extract_artifacts.py` | `artifacts_authored.jsonl` |
| `extract_code_comments.py` | `code_comments.jsonl` |

**Corroborate** — check what the model wrote against what survived.

| Tool | Writes |
| --- | --- |
| `collect_git.py` | `git_landed.jsonl` |
| `collect_prs.py [--refresh]` | `prs.jsonl` |
| `match_rewrites.py` | `rewrites.jsonl` |
| `compare_style.py` | `style_comparison.json` |
| `detect_comment_rewrites.py` | `comment_survival.json` |

**Judge** — batch out for classification, then merge the verdicts back.

| Tool | Writes |
| --- | --- |
| `make_triage_batches.py [size] [--new-only]` | `triage_in/batch_NNN.json` |
| `merge_triage.py [--min-confidence N]` | `triaged.jsonl`, `judge_in/` |
| `make_comment_batches.py [size]` | `comment_in/batch_NNN.json` |
| `summarize_comments.py` | `comment_summary.json` |

**Reduce** — collapse duplicates, then lift the result into rules.

| Tool | Writes |
| --- | --- |
| `dedupe_incidents.py [--gap N]` | `incidents.jsonl` |
| `make_problem_batches.py [--min N]` | `problem_in/<kind>.json` |
| `merge_problems.py` | `problems.jsonl` |
| `make_behavior_batch.py` | `behavior_in/all.json` |
| `merge_behaviors.py` | `behaviors.jsonl`, `behaviors_unassigned.jsonl` |
| `rank_findings.py` | `findings.jsonl`, `report.md` |
| `build_report.py` | `report.html` |

**Check** — `status.py` walks the stage graph and names any output older than its
inputs, with the command that rebuilds it. Exits 1 if anything is stale, so it
can gate a workflow rather than just inform. An output that no longer reflects
the data looks exactly like one that does.

### Why there are three levels above an episode

    kind  ->  problem  ->  behavior

A **kind** is a category. It has no checkable action in it, so no rule can attach
to it — "unverified premise" is a label, not an instruction.

A **problem** is rule-shaped but scoped to the situation it came from. Problems
are grouped within a single kind, which is what keeps them tight, and also what
makes their rules read like the session they came from: *"read the CI workflow
before assuming it applies"* is true and does not survive contact with a
different project.

A **behavior** is the standing instruction, found by grouping every rule
candidate at once with the kinds removed as a boundary. That matters because the
clusters that are actually rule-shaped cut *across* kinds: stating something from
memory instead of reading the source appears under one kind in one session and a
different one in the next, and grouping inside a kind can never see them
together. Behaviors are what a ruleset loads; the problem rules stay underneath
as worked examples and as a regression set to check a candidate rule against.

## Output location

`findings/` is created under the current working directory. Override per-run
with `--output PATH` (or `-o`), or for a whole shell with `CSA_FINDINGS`.

It contains verbatim excerpts of your sessions, your repos and your own rulings
on them. It is gitignored here, but treat it as sensitive wherever it lands.

## Tuning the language patterns

Six patterns match text rather than structure. Four are how one person writes in
English when they are annoyed; two are lines that tooling appends. All of them
are **finders** — their hits get reviewed, never treated as verdicts — and all of
them can be extended from the config:

| Config key | Extends | Matches |
| --- | --- | --- |
| `extra_profanity` | `PROFANITY` | swearing and exasperation |
| `extra_negation_lead` | `NEGATION_LEAD` | a message that opens with a correction |
| `extra_correction_phrase` | `CORRECTION_PHRASE` | a correction anywhere in the message |
| `extra_repeat_marker` | `REPEAT_MARKER` | "I already told you" — this one gates the rule bar |
| `extra_commit_trailers` | `TRAILER` | trailers stripped before commits are compared |
| `extra_comment_skip` | `SKIP_PATTERNS` | machine directives that are not prose |

Each list **adds** alternatives; the built-in terms always stay in. Entries are
literal phrases and are escaped for you, bounded so they will not fire inside a
longer word. Prefix an entry with `re:` for a raw regex fragment. A bad regex or
an empty entry stops the run and names the key it came from, rather than
silently matching nothing.

`extra_repeat_marker` is the one worth spending time on. Whether a failure counts
as noncompliant — an instruction already existed and was broken anyway — is what
separates a pattern that needs a standing rule from one a single correction
fixes. Miss the way you phrase "I already told you" and those failures rank as
first offences.

## Caveats worth knowing

- The patterns above are finders, not measurements. Precision was hand-checked
  once at 47% on one corpus, which is why every hit goes to review.
- Everything derived from complaints undercounts failures you absorbed silently.
  The interrupt and comment-survival signals exist because they need no
  complaint to fire.

## License

MIT — see [LICENSE](LICENSE).
