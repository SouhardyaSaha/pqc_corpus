"""Issues of a finished run, each with its comments and the pull requests that close it.

GitHub's issue list also returns pull requests; those copies are stored under a
different kind and are not issues here. Comments are attached by the issue
number in their `issue_url`; a comment on a pull request therefore never
attaches to an issue. Closing links come from GitHub's "closes" relationship,
recorded on the pull request's side; a link can point to an issue in another
repository.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from .run_data import Run, github_url

ClosingLinks = dict[tuple[str, int], list[dict[str, Any]]]
Comments = dict[tuple[str, int], list[dict[str, Any]]]


def login(user: dict[str, Any] | None) -> str | None:
    """GitHub username; None for a deleted account."""
    return user.get('login') if user else None


def closing_links(run: Run) -> ClosingLinks:
    """`(issue repository, issue number) -> [{repo, number, url}]` of the closing pull requests."""
    names = {name.lower(): name for name in run.repositories}
    canonical = {meta['full_name'].lower(): name for name, (meta, _) in run.repository_metadata().items()}
    links: ClosingLinks = defaultdict(list)
    for repo, record, _ in run.records('closing_issue_link'):
        target = record['repository']['nameWithOwner']
        issue_repo = names.get(target.lower()) or canonical.get(target.lower()) or target
        pr = int(record['pr_number'])
        links[(issue_repo, int(record['number']))].append(
            {'repo': repo, 'number': pr, 'url': github_url(repo, 'pull', pr)})
    for found in links.values():
        found.sort(key=lambda link: (link['repo'], link['number']))
    return links


def issue_comments(run: Run) -> Comments:
    """`(repository, parent number) -> comments` in posting order."""
    found: dict[tuple[str, int], list[tuple[str, int, dict[str, Any]]]] = defaultdict(list)
    for repo, record, _ in run.records('issue_comment'):
        parent = int(record['issue_url'].rstrip('/').rsplit('/', 1)[1])
        comment = {'author': login(record.get('user')), 'created_at': record['created_at'],
                   'body': record.get('body')}
        found[(repo, parent)].append((record['created_at'], int(record['id']), comment))
    return {key: [c for _, _, c in sorted(items, key=lambda item: item[:2])] for key, items in found.items()}


def issue_record(repo: str, corpus: str, raw: dict[str, Any], fetched_at: str,
                 links: ClosingLinks, comments: Comments) -> dict[str, Any]:
    number = int(raw['number'])
    return {
        'repo': repo, 'corpus': corpus, 'number': number, 'url': raw['html_url'],
        'title': raw['title'], 'body': raw.get('body'), 'state': raw['state'],
        'state_reason': raw.get('state_reason'), 'author': login(raw.get('user')),
        'created_at': raw['created_at'], 'closed_at': raw.get('closed_at'),
        'closed_by_prs': links.get((repo, number), []),
        'comments': comments.get((repo, number), []),
        'fetched_at': fetched_at,
    }


def issues(run_dir: Path) -> Iterator[dict[str, Any]]:
    """Every collected issue, ordered by repository and number."""
    run = Run(run_dir)
    try:
        corpora = run.corpora()
        links, comments = closing_links(run), issue_comments(run)
        rows = sorted(run.records('issue'), key=lambda row: (row[0], int(row[1]['number'])))
        for repo, raw, fetched_at in rows:
            yield issue_record(repo, corpora[repo], raw, fetched_at, links, comments)
    finally:
        run.close()
