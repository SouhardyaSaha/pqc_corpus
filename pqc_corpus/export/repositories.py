"""One record per repository: its corpus and the GitHub metadata the commit filter and the figures read.

The commit filter needs `is_fork`, `description` and `topics` (see `filters.commits`).
`language`, `stars`, `forks` and `created_at` describe the corpus (figures 3 and 4).
`github_pull_requests` and `github_issues` are GitHub's totals when the corpus was
assigned, and `git_commits` the size of the full Git history before selection
(table 1).
"""

from pathlib import Path
from typing import Any, Iterator

from .run_data import Run


def repository_record(repo: str, corpus: str, meta: dict[str, Any], fetched_at: str, plan: dict[str, Any],
                      git_commits: int) -> dict[str, Any]:
    totals = plan.get('metadata') or {}
    return {
        'repo': repo, 'corpus': corpus, 'url': f'https://github.com/{repo}',
        'description': meta.get('description'), 'topics': meta.get('topics') or [],
        'is_fork': bool(meta.get('fork')), 'language': meta.get('language'),
        'stars': meta.get('stargazers_count'), 'forks': meta.get('forks_count'),
        'created_at': meta.get('created_at'),
        'github_pull_requests': (totals.get('pullRequests') or {}).get('totalCount'),
        'github_issues': (totals.get('issues') or {}).get('totalCount'),
        'git_commits': git_commits,
        'fetched_at': fetched_at,
    }


def repositories(run_dir: Path) -> Iterator[dict[str, Any]]:
    """Every manifest repository, ordered by name."""
    run = Run(run_dir)
    try:
        metadata = run.repository_metadata()
        for repo in sorted(run.repositories):
            if repo not in metadata:
                raise ValueError(f'No GitHub metadata for {repo}')
            meta, fetched_at = metadata[repo]
            plan = run.plan(repo)
            yield repository_record(repo, run.corpus(repo), meta, fetched_at, plan, run.git_history_size(repo))
    finally:
        run.close()
