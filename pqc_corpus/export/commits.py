"""Commits of a finished run, each with its patch, as dataset records.

The selected commits are those in the run's `git.sqlite` (every commit of
corpus A and C repositories; in corpus B, commits whose message names a policy
term or that belong to a keyword-selected pull request). Each record adds the pull
requests that contain the commit, the files it changes and its full patch,
both computed with `git_diff` from the frozen mirror, and the observations of
`collection.eligibility`. The author's e-mail address is not exported; an opaque
`author_key` (see `author_key`) is, so that copies of one commit by one author can
be recognised.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
import json
from pathlib import Path
from typing import Any, Iterator

from ..collection.eligibility import Observation
from ..collection.linked_commits import find_object_store
from ..common import connect_read_only, mirror_name
from .author_key import AuthorKeys
from .git_diff import commit_diff
from .run_data import Run, github_url

Eligibility = dict[tuple[str, str], Observation]
WORKERS = 4
CHUNK = 32


def pr_numbers(run: Run) -> dict[tuple[str, str], list[int]]:
    """`(repository, SHA) -> numbers of the collected pull requests that contain the commit`."""
    found: dict[tuple[str, str], set[int]] = defaultdict(set)
    for repo, record, _ in run.records('pr_commit'):
        found[(repo, record['commit']['oid'])].add(int(record['pr_number']))
    return {key: sorted(numbers) for key, numbers in found.items()}


def object_store(run_dir: Path, repo: str, sha: str) -> Path:
    stores = (run_dir / 'mirrors' / mirror_name(repo), run_dir / 'recovery_mirrors' / mirror_name(repo))
    store = find_object_store(stores, sha)
    if store is None:
        raise ValueError(f'{repo}@{sha} is in no mirror of the run')
    return store


def commit_record(run_dir: Path, repo: str, corpus: str, git: dict[str, Any], prs: list[int],
                  eligibility: Observation, keys: AuthorKeys) -> dict[str, Any]:
    sha = git['sha']
    diff = commit_diff(object_store(run_dir, repo, sha), sha, git['parents'])
    encoding, patch = diff.encoded_patch
    files = diff.changed_files
    on_default_branch, in_merged_pr, pqc_in_linked_text = eligibility
    return {
        'repo': repo, 'corpus': corpus, 'sha': sha, 'url': github_url(repo, 'commit', sha),
        'message': git['message'],
        'author_name': git['author']['name'],
        'author_key': keys.key(git['author']['email']),
        'authored_at': git['authored_at'],
        'committer_name': git['committer']['name'], 'committed_at': git['committed_at'],
        'parents': git['parents'],
        'pr_numbers': prs, 'pr_urls': [github_url(repo, 'pull', n) for n in prs],
        'on_default_branch': on_default_branch, 'in_merged_pr': in_merged_pr,
        'pqc_in_linked_text': pqc_in_linked_text,
        'changed_files': files,
        'lines_added': sum(f['additions'] or 0 for f in files),
        'lines_deleted': sum(f['deletions'] or 0 for f in files),
        'patch_encoding': encoding, 'patch_content': patch,
        'fetched_at': git['collected_at'],
    }


def selected(run_dir: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    git = connect_read_only(run_dir / 'git.sqlite')
    try:
        for repo, data in git.execute('SELECT repo, data FROM commits ORDER BY repo, sha'):
            yield repo, json.loads(data)
    finally:
        git.close()


def commits(run_dir: Path, eligibility: Eligibility, keys: AuthorKeys) -> Iterator[dict[str, Any]]:
    """Every selected commit, ordered by repository and SHA; patches are computed in parallel."""
    run = Run(run_dir)
    try:
        corpora, prs = run.corpora(), pr_numbers(run)
    finally:
        run.close()
    missing = [key for key in ((repo, g['sha']) for repo, g in selected(run_dir)) if key not in eligibility]
    if missing:
        raise ValueError(f'{len(missing)} commits have no eligibility observation, e.g. {missing[0]}')

    def build(row: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        repo, git = row
        key = (repo, git['sha'])
        return commit_record(run_dir, repo, corpora[repo], git, prs.get(key, []), eligibility[key], keys)

    rows = selected(run_dir)
    with ThreadPoolExecutor(WORKERS) as pool:
        while chunk := list(islice(rows, CHUNK)):
            yield from pool.map(build, chunk)
