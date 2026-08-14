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

**Reduce and report.**

| Tool | Writes |
| --- | --- |
| `dedupe_incidents.py [--gap N]` | `incidents.jsonl` |
| `rank_findings.py` | `findings.jsonl`, `report.md` |
| `build_report.py` | `report.html` |

`migrate_ids.py [--dry-run]` re-keys stored verdicts when the id scheme changes,
so hand-made rulings survive a pipeline change.

## Output location

`findings/` is created under the current working directory. Override per-run
with `--output PATH` (or `-o`), or for a whole shell with `CSA_FINDINGS`.

It contains verbatim excerpts of your sessions, your repos and your own rulings
on them. It is gitignored here, but treat it as sensitive wherever it lands.

## Reading older findings

Earlier versions of this tool named its fields after its author: role `greg`,
`greg_said`, `what_greg_wanted`, `greg_note`, `corrected_by_greg`,
`greg_hand_written` and `greg_review.json`. Everything is written as `user_*`
now, but those names are still **read** so an existing findings directory keeps
working. Nothing is rewritten in place and there is no migration to run.

## Caveats worth knowing

Two things in here are tuned to one corpus rather than being general truths, and
they are marked as such in the source:

- `REPEAT_MARKER` in `common.py` matches English phrasings meaning "I already
  told you". It is a finder whose hits are meant to be reviewed, not a
  measurement. Your phrasings will differ.
- Everything derived from complaints undercounts failures you absorbed silently.
  The interrupt and comment-survival signals exist because they need no
  complaint to fire.

## License

MIT — see [LICENSE](LICENSE).
