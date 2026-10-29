"""Pull requests of a finished run, each with its discussion, reviews, commits and closed issues.

A pull request's general comments are GitHub issue comments whose `issue_url`
carries the pull request's number; inline comments are review comments on its
diff; reviews are formal reviews (approve, request changes, comment). Commit
SHAs are GitHub's commit list for the pull request; every one is in the commit
file. Closed issues come from GitHub's "closes" relationship and can be in
another repository or not collected.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from .issues import Comments, issue_comments, login
from .run_data import Run, github_url

Items = dict[tuple[str, int], list[dict[str, Any]]]


def number_from(url: str) -> int:
    return int(url.rstrip('/').rsplit('/', 1)[1])


def ordered(found: dict[tuple[str, int], list[tuple[Any, ...]]]) -> Items:
    """Sort each pull request's items by (time, id) and drop the sort keys."""
    return {key: [item for *_, item in sorted(items, key=lambda entry: entry[:2])] for key, items in found.items()}


def reviews(run: Run) -> Items:
    found: dict[tuple[str, int], list[tuple[Any, ...]]] = defaultdict(list)
    for repo, record, _ in run.records('review'):
        review = {'author': login(record.get('author')), 'state': record['state'],
                  'submitted_at': record.get('submittedAt'), 'body': record.get('body')}
        found[(repo, int(record['pr_number']))].append(
            (record.get('submittedAt') or '', int(record.get('databaseId') or 0), review))
    return ordered(found)


def review_comments(run: Run) -> Items:
    found: dict[tuple[str, int], list[tuple[Any, ...]]] = defaultdict(list)
    for repo, record, _ in run.records('review_comment'):
        comment = {'author': login(record.get('user')), 'created_at': record['created_at'],
                   'path': record.get('path'), 'line': record.get('line') or record.get('original_line'),
                   'body': record.get('body')}
        found[(repo, number_from(record['pull_request_url']))].append(
            (record['created_at'], int(record['id']), comment))
    return ordered(found)


def commit_shas(run: Run) -> dict[tuple[str, int], list[str]]:
    found: dict[tuple[str, int], set[str]] = defaultdict(set)
    for repo, record, _ in run.records('pr_commit'):
        found[(repo, int(record['pr_number']))].add(record['commit']['oid'])
    return {key: sorted(shas) for key, shas in found.items()}


def closed_issues(run: Run) -> Items:
    """`(PR repository, PR number) -> [{repo, number, url}]` of the issues it closes."""
    names = {name.lower(): name for name in run.repositories}
    canonical = {meta['full_name'].lower(): name for name, (meta, _) in run.repository_metadata().items()}
    found: Items = defaultdict(list)
    for repo, record, _ in run.records('closing_issue_link'):
        target = record['repository']['nameWithOwner']
        issue_repo = names.get(target.lower()) or canonical.get(target.lower()) or target
        number = int(record['number'])
        found[(repo, int(record['pr_number']))].append(
            {'repo': issue_repo, 'number': number, 'url': github_url(issue_repo, 'issues', number)})
    for links in found.values():
        links.sort(key=lambda link: (link['repo'], link['number']))
    return found


def pull_request_record(repo: str, corpus: str, raw: dict[str, Any], fetched_at: str, comments: Comments,
                        inline: Items, formal: Items, shas: dict[tuple[str, int], list[str]],
                        closes: Items) -> dict[str, Any]:
    number = int(raw['number'])
    key = (repo, number)
    return {
        'repo': repo, 'corpus': corpus, 'number': number, 'url': raw['html_url'],
        'title': raw['title'], 'body': raw.get('body'), 'state': raw['state'],
        'draft': bool(raw.get('draft')), 'merged': raw.get('merged_at') is not None,
        'author': login(raw.get('user')), 'created_at': raw['created_at'],
        'closed_at': raw.get('closed_at'), 'merged_at': raw.get('merged_at'),
        'base_branch': (raw.get('base') or {}).get('ref'), 'head_branch': (raw.get('head') or {}).get('ref'),
        'commit_shas': shas.get(key, []),
        'closes_issues': closes.get(key, []),
        'comments': comments.get(key, []),
        'reviews': formal.get(key, []),
        'review_comments': inline.get(key, []),
        'fetched_at': fetched_at,
    }


def pull_requests(run_dir: Path) -> Iterator[dict[str, Any]]:
    """Every collected pull request, ordered by repository and number."""
    run = Run(run_dir)
    try:
        corpora = run.corpora()
        comments, inline, formal = issue_comments(run), review_comments(run), reviews(run)
        shas, closes = commit_shas(run), closed_issues(run)
        rows = sorted(run.records('pull'), key=lambda row: (row[0], int(row[1]['number'])))
        for repo, raw, fetched_at in rows:
            yield pull_request_record(repo, corpora[repo], raw, fetched_at, comments, inline, formal, shas, closes)
    finally:
        run.close()
