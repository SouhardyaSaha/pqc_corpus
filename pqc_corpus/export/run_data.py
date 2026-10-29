"""Read-only access to a finished run: repositories, their corpus and stored GitHub records."""

import json
from pathlib import Path
from typing import Any, Iterator

from ..collection.plans import load_plan
from ..common import connect_read_only, lowercase_slug, read_json

# The collector's tier plans name the corpus of each repository; `unrated` (no pull requests or
# issues) is corpus C in the dataset.
CORPUS_NAMES = {'A': 'A', 'B': 'B', 'unrated': 'C'}


def github_url(repo: str, kind: str, ref: str | int) -> str:
    return f'https://github.com/{repo}/{kind}/{ref}'


class Run:
    """One run directory, opened read-only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.repositories: list[str] = [e['repo'] for e in read_json(path / 'manifest.json')['repositories']]
        self.api = connect_read_only(path / 'github.sqlite')
        self.repo_ids: dict[str, str] = dict(self.api.execute('SELECT requested_name, repo_id FROM aliases'))
        self.names_by_id: dict[str, str] = {self.repo_ids[r.lower()]: r for r in self.repositories
                                            if r.lower() in self.repo_ids}

    def close(self) -> None:
        self.api.close()

    def plan(self, repo: str) -> dict[str, Any]:
        return load_plan(self.path, repo)

    def corpus(self, repo: str) -> str:
        return CORPUS_NAMES[self.plan(repo)['tier']]

    def corpora(self) -> dict[str, str]:
        return {repo: self.corpus(repo) for repo in self.repositories}

    def git_history_size(self, repo: str) -> int:
        """Commits in the repository's full Git history (every fetched ref), before selection."""
        return read_json(self.path / 'git_selection' / (lowercase_slug(repo) + '.json'))['scanned']

    def records(self, kind: str) -> Iterator[tuple[str, dict[str, Any], str]]:
        """`(requested repository name, record, fetched_at)` for every stored record of a kind."""
        for repo_id, data, fetched_at in self.api.execute(
                'SELECT repo_id, data, fetched_at FROM records WHERE kind=? ORDER BY repo_id, key', (kind,)):
            yield self.names_by_id[repo_id], json.loads(data), fetched_at

    def repository_metadata(self) -> dict[str, tuple[dict[str, Any], str]]:
        """GitHub's repository object and its fetch time, by requested name."""
        rows = self.api.execute('SELECT id, data, fetched_at FROM repositories')
        return {self.names_by_id[i]: (json.loads(d), f) for i, d, f in rows if i in self.names_by_id}
