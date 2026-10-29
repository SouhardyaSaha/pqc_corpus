"""Table 1 and figures 3-5 of the PQC-Corpus paper, computed from a release directory only.

Inputs and the fields read:

| Output | File | Fields |
|---|---|---|
| table 1 | repositories | corpus, github_pull_requests, github_issues, git_commits |
| | commits, commits_filtered | repo, corpus (counted per line) |
| | issues, issues_filtered | corpus, comments |
| | pull_requests | corpus, commit_shas, closes_issues, comments, reviews, review_comments |
| figure 3 | repositories | language; commits per repository |
| figure 4 | repositories | corpus, stars, forks, created_at, fetched_at; commits per repository |
| figure 5 | pull_requests | corpus, created_at |

Every figure's numbers are also written as CSV, so the PDFs (drawn only when
matplotlib is installed) can be checked or redrawn. Nothing in the release is
changed. Repository age is the time from `created_at` to `fetched_at`, in years
of 365.25 days.
"""

from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Iterator

from .common import file_sha256, now, write_json_atomic
from .export import jsonl
from .release import locate

CORPORA = ('A', 'B', 'C')
# Records written by `mine` start with their repository and corpus; other files are parsed in full.
PREFIX = re.compile(rb'^\{"repo":("(?:[^"\\]|\\.)*"),"corpus":"([ABC])"')
BINS = (('0', 0, 0), ('1–9', 1, 9), ('10–99', 10, 99), ('100–999', 100, 999), ('1k–9,999', 1000, 9999),
        ('10k+', 10000, None))
SHOWN_LANGUAGES = 6
FIRST_YEAR = 2015


def repo_and_corpus(directory: Path, name: str) -> Iterator[tuple[str, str]]:
    """`(repo, corpus)` of every line, reading only the start of each line when possible."""
    path = locate(directory, name)
    for file in (jsonl.part_files(path) if path.is_dir() else [path]):
        with file.open('rb') as stream:
            for line in stream:
                match = PREFIX.match(line[:1024])
                if match:
                    yield json.loads(match.group(1)), match.group(2).decode()
                elif line.strip():
                    record = json.loads(line)
                    yield record['repo'], record['corpus']


def per_corpus(items: Iterator[tuple[str, int]]) -> dict[str, int]:
    totals: dict[str, int] = {corpus: 0 for corpus in CORPORA}
    for corpus, value in items:
        totals[corpus] += value
    return totals


def years(start: str, end: str) -> float:
    parse = lambda text: datetime.fromisoformat(text.replace('Z', '+00:00'))  # noqa: E731
    return (parse(end) - parse(start)).total_seconds() / (365.25 * 86400)


def table_rows(directory: Path, repositories: list[dict],
               commit_counts: Counter) -> tuple[list[tuple[str, str, dict]], list[dict]]:
    """Table rows as (section, row, counts by corpus), and the pull requests read for them."""
    filtered = Counter(corpus for _, corpus in repo_and_corpus(directory, 'commits_filtered'))
    issues = list(jsonl.read(locate(directory, 'issues')))
    issues_filtered = Counter(i['corpus'] for i in jsonl.read(locate(directory, 'issues_filtered')))
    prs = list(jsonl.read(locate(directory, 'pull_requests')))
    corpus_of = {r['repo']: r['corpus'] for r in repositories}
    commits = per_corpus((corpus_of[repo], n) for repo, n in commit_counts.items())
    total = lambda field: per_corpus((r['corpus'], r[field] or 0) for r in repositories)  # noqa: E731
    count = lambda rows, field: per_corpus((r['corpus'], len(r[field])) for r in rows)  # noqa: E731
    general = count(issues, 'comments')
    for corpus, n in count(prs, 'comments').items():
        general[corpus] += n
    before, records, context = 'GitHub totals before selection', 'Records', 'Discussion inside records'
    return [
        (before, 'PRs on GitHub', total('github_pull_requests')),
        (before, 'Issues on GitHub', total('github_issues')),
        (before, 'Commits in full history', total('git_commits')),
        (records, 'Repositories', per_corpus((r['corpus'], 1) for r in repositories)),
        (records, 'Commits', commits),
        (records, 'Commits, filtered set', per_corpus(filtered.items())),
        (records, 'Pull requests', per_corpus((p['corpus'], 1) for p in prs)),
        (records, 'Issues', per_corpus((i['corpus'], 1) for i in issues)),
        (records, 'Issues, filtered set', per_corpus(issues_filtered.items())),
        (records, 'Commit–PR links', count(prs, 'commit_shas')),
        (records, 'Closing-issue links', count(prs, 'closes_issues')),
        (context, 'General comments', general),
        (context, 'Inline comments', count(prs, 'review_comments')),
        (context, 'Formal reviews', count(prs, 'reviews')),
    ], prs


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def write_table(output: Path, rows: list[tuple[str, str, dict]]) -> None:
    flat = [[section, name, *(counts[c] for c in CORPORA), sum(counts.values())] for section, name, counts in rows]
    write_csv(output / 'table1.csv', ['section', 'row', *CORPORA, 'total'], flat)
    lines = ['| Row | A | B | C | Total |', '|---|---:|---:|---:|---:|']
    tex = [r'\begin{tabular}{lrrrr}', r'\toprule', r'Artifact & A & B & C & Total \\']
    section = None
    for row in flat:
        if row[0] != section:
            section = row[0]
            lines.append(f'| **{section}** | | | | |')
            tex += [r'\midrule', rf'\multicolumn{{5}}{{l}}{{\emph{{{section}}}}} \\']
        lines.append('| ' + ' | '.join([row[1], *(f'{v:,}' for v in row[2:])]) + ' |')
        tex.append(' & '.join([row[1].replace('–', '--'), *(f'{v:,}'.replace(',', '{,}') for v in row[2:])]) + r' \\')
    tex += [r'\bottomrule', r'\end{tabular}']
    (output / 'table1.md').write_text('\n'.join(lines) + '\n')
    (output / 'table1.tex').write_text('\n'.join(tex) + '\n')


def figure_data(output: Path, repositories: list[dict], commit_counts: Counter, prs: list[dict]) -> dict[str, Any]:
    languages = Counter(r['language'] or 'None' for r in repositories)
    shown = [name for name, _ in languages.most_common(SHOWN_LANGUAGES)]
    language_rows = [[name, languages[name]] for name in shown]
    language_rows.append([f'Other ({len(languages) - len(shown)} labels)',
                          sum(n for name, n in languages.items() if name not in shown)])
    write_csv(output / 'fig3a_languages.csv', ['language', 'repositories'], language_rows)
    bins = Counter()
    for r in repositories:
        n = commit_counts.get(r['repo'], 0)
        bins[next(label for label, low, high in BINS if n >= low and (high is None or n <= high))] += 1
    bin_rows = [[label, bins[label]] for label, _, _ in BINS]
    write_csv(output / 'fig3b_commits_per_repository.csv', ['commits', 'repositories'], bin_rows)
    profile = [[r['repo'], r['corpus'], r['stars'], r['forks'], round(years(r['created_at'], r['fetched_at']), 3),
                commit_counts.get(r['repo'], 0)] for r in repositories]
    write_csv(output / 'fig4_repositories.csv', ['repo', 'corpus', 'stars', 'forks', 'age_years', 'commits'], profile)
    per_year = Counter((p['corpus'], int(p['created_at'][:4])) for p in prs)
    all_years = sorted({year for _, year in per_year})
    write_csv(output / 'fig5_pull_requests_per_year.csv', ['year', 'A', 'B'],
              [[y, per_year[('A', y)], per_year[('B', y)]] for y in all_years])
    return {'languages': language_rows, 'bins': bin_rows, 'profile': profile, 'per_year': per_year,
            'years': all_years}


def draw(output: Path, data: dict[str, Any]) -> list[str]:
    """PDF figures, if matplotlib is installed; returns the files written."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    fig, (left, right) = plt.subplots(1, 2, figsize=(7, 2.6))
    names, counts = zip(*reversed(data['languages']))
    left.barh(names, counts, color='#4c72b0')
    left.set_title('(a) Primary language')
    left.set_xlabel('Repositories')
    labels, counts = zip(*data['bins'])
    right.bar(labels, counts, color='#4c72b0')
    right.set_title('(b) Selected commit volume')
    right.set_xlabel('Commits / repository')
    right.set_ylabel('Repositories')
    right.tick_params(axis='x', rotation=45)
    fig.tight_layout()
    fig.savefig(output / 'fig3.pdf')
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(7, 3.6))
    panels = (('(a) Stars', 2), ('(b) Forks', 3), ('(c) Age (years)', 4), ('(d) Commit records', 5))
    for axis, (title, column) in zip(axes.flat, panels):
        values = [[row[column] for row in data['profile'] if row[1] == corpus] for corpus in ('A', 'B')]
        try:
            axis.boxplot(values, orientation='horizontal', showfliers=False)
        except TypeError:  # matplotlib before 3.10
            axis.boxplot(values, vert=False, showfliers=False)
        axis.set_yticks([1, 2], ['A', 'B'])
        axis.invert_yaxis()
        axis.set_title(title)
    fig.tight_layout()
    fig.savefig(output / 'fig4.pdf')
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(7, 2.4))
    shown = [y for y in data['years'] if y >= FIRST_YEAR]
    width = 0.4
    for offset, corpus in ((-width / 2, 'A'), (width / 2, 'B')):
        axis.bar([y + offset for y in shown], [data['per_year'][(corpus, y)] for y in shown], width,
                 label=f'Corpus {corpus}')
    axis.set_xticks(shown)
    axis.set_ylabel('PRs created')
    axis.legend()
    fig.tight_layout()
    fig.savefig(output / 'fig5.pdf')
    plt.close(fig)
    return ['fig3.pdf', 'fig4.pdf', 'fig5.pdf']


def figures(directory: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise SystemExit(f'{output} exists; choose a new output directory')
    output.mkdir(parents=True)
    repositories = list(jsonl.read(locate(directory, 'repositories')))
    commit_counts = Counter(repo for repo, _ in repo_and_corpus(directory, 'commits'))
    rows, prs = table_rows(directory, repositories, commit_counts)
    write_table(output, rows)
    data = figure_data(output, repositories, commit_counts, prs)
    drawn = draw(output, data)
    manifest = directory / 'manifest.json'
    summary = {'created_at': now(), 'release_manifest_sha256': file_sha256(manifest) if manifest.exists() else None,
               'figures': drawn or 'matplotlib not installed; CSV only'}
    write_json_atomic(output / 'summary.json', summary)
    print((output / 'table1.md').read_text())
    print(f'figures: {drawn or "matplotlib not installed; CSV data only"}')
    return summary
