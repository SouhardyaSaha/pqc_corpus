"""Observe, for every selected commit, the facts about its history and pull requests that the filter reads.

- `on_default_branch`: the commit is reachable from the repository's default
  branch, as the frozen mirror recorded it (`git rev-list HEAD` in the mirror).
- `in_merged_pr`: GitHub associates the commit with at least one merged pull
  request of the same repository (GraphQL `associatedPullRequests`). This can be
  true for a commit whose pull request was not itself collected.
- `pqc_in_linked_text`: a PQC term (`filters.terms`) appears in the title or body
  of a pull request of the same repository that GitHub associates with the
  commit, merged or not, or of an issue such a pull request closes.

Observations are stored in the run's `eligibility.sqlite`, one repository at a
time, so an interrupted stage resumes where it stopped.
"""

import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Iterable

from ..common import connect_read_only, mirror_name, now
from ..filters.terms import mentions_pqc
from .github_client import GraphQL

# (on_default_branch, in_merged_pr, pqc_in_linked_text); the last is None when it was not observed.
Observation = tuple[bool, bool, bool | None]

BATCH = 20
SCHEMA = '''CREATE TABLE IF NOT EXISTS eligibility(repo TEXT NOT NULL, sha TEXT NOT NULL,
    on_default_branch INTEGER NOT NULL, merged_pr_numbers TEXT NOT NULL, pqc_in_linked_text INTEGER NOT NULL,
    observed_at TEXT NOT NULL, PRIMARY KEY(repo, sha));
    CREATE TABLE IF NOT EXISTS repositories(repo TEXT PRIMARY KEY, completed_at TEXT NOT NULL);'''


def query_text(count: int) -> str:
    variables = ['$owner:String!', '$name:String!'] + [f'$sha{i}:GitObjectID!' for i in range(count)]
    fields = [
        f'c{i}: object(oid:$sha{i}) {{ ... on Commit {{ associatedPullRequests(first:100) {{ '
        'nodes { number merged title body repository { nameWithOwner } '
        'closingIssuesReferences(first:50) { nodes { title body } } } pageInfo { hasNextPage } } } }'
        for i in range(count)
    ]
    return f'query({", ".join(variables)}) {{ repository(owner:$owner,name:$name) {{ {" ".join(fields)} }} }}'


def associated(node: dict[str, Any] | None, names: set[str]) -> tuple[list[int], bool]:
    """Merged pull requests of the same repository (under any of its names), and whether the
    texts of all its same-repository pull requests and the issues they close name a PQC term."""
    if not node:
        return [], False
    connection = node['associatedPullRequests']
    if connection['pageInfo']['hasNextPage']:
        raise RuntimeError('A commit has more than 100 associated pull requests; not supported')
    prs = [pr for pr in connection['nodes'] if pr['repository']['nameWithOwner'].lower() in names]
    texts = [(item.get('title') or '') + '\n' + (item.get('body') or '')
             for pr in prs for item in [pr, *((pr.get('closingIssuesReferences') or {}).get('nodes') or [])]]
    return sorted({pr['number'] for pr in prs if pr['merged']}), mentions_pqc('\n'.join(texts))


def associated_prs(client: GraphQL, repo: str, names: set[str],
                   shas: list[str]) -> dict[str, tuple[list[int], bool]]:
    owner, name = repo.split('/', 1)
    found: dict[str, tuple[list[int], bool]] = {}
    for start in range(0, len(shas), BATCH):
        batch = shas[start:start + BATCH]
        variables: dict[str, Any] = {'owner': owner, 'name': name}
        variables.update({f'sha{i}': sha for i, sha in enumerate(batch)})
        data = client.query(query_text(len(batch)), variables)['repository']
        for i, sha in enumerate(batch):
            found[sha] = associated(data.get(f'c{i}'), names)
    return found


def default_branch_shas(mirror: Path, timeout: int = 1800) -> set[str]:
    """Commits reachable from a bare mirror's HEAD, which names the default branch."""
    result = subprocess.run(['git', '-C', str(mirror), 'rev-list', 'HEAD'], capture_output=True,
                            text=True, timeout=timeout, check=True)
    return set(result.stdout.split())


def repository_names(run: Path, repo: str) -> set[str]:
    """The requested name and GitHub's current full name, lower-case."""
    api = connect_read_only(run / 'github.sqlite')
    row = api.execute('SELECT r.full_name FROM aliases a JOIN repositories r ON r.id=a.repo_id '
                      'WHERE a.requested_name=?', (repo.lower(),)).fetchone()
    api.close()
    return {repo.lower()} | ({row[0].lower()} if row and row[0] else set())


def selected_commits(run: Path) -> dict[str, list[str]]:
    git = connect_read_only(run / 'git.sqlite')
    by_repo: dict[str, list[str]] = {}
    for repo, sha in git.execute('SELECT repo, sha FROM commits ORDER BY repo, sha'):
        by_repo.setdefault(repo, []).append(sha)
    git.close()
    return by_repo


def observe(run: Path, client: GraphQL) -> int:
    """Observe every selected commit not yet observed; returns the number of repositories done now."""
    db = sqlite3.connect(run / 'eligibility.sqlite')
    db.executescript(SCHEMA)
    done = {repo for repo, in db.execute('SELECT repo FROM repositories')}
    observed = 0
    for repo, shas in selected_commits(run).items():
        if repo in done:
            continue
        reachable = default_branch_shas(run / 'mirrors' / mirror_name(repo))
        prs = associated_prs(client, repo, repository_names(run, repo), shas)
        stamp = now()
        db.executemany('INSERT OR REPLACE INTO eligibility VALUES (?,?,?,?,?,?)', [
            (repo, sha, int(sha in reachable), json.dumps(prs[sha][0]), int(prs[sha][1]), stamp) for sha in shas])
        db.execute('INSERT INTO repositories VALUES (?,?)', (repo, stamp))
        db.commit()
        observed += 1
        print(f'[{stamp}] eligibility {repo}: {len(shas)} commits', flush=True)
    db.close()
    return observed


def load(path: Path) -> dict[tuple[str, str], Observation]:
    """`(repo, sha) -> (on_default_branch, in_merged_pr, pqc_in_linked_text)` from `eligibility.sqlite`
    or a JSONL file.

    A JSONL file has one `{repo, sha, on_default_branch, in_merged_pr, pqc_in_linked_text}` object
    per line; it carries observations made outside the run (see the project README).
    """
    if path.suffix == '.sqlite':
        db = connect_read_only(path)
        rows: Iterable[tuple[str, str, bool, bool, bool | None]] = [
            (repo, sha, bool(on_main), bool(json.loads(merged)), bool(linked))
            for repo, sha, on_main, merged, linked in db.execute(
                'SELECT repo, sha, on_default_branch, merged_pr_numbers, pqc_in_linked_text FROM eligibility')]
        db.close()
    else:
        with path.open(encoding='utf-8') as stream:
            rows = [(r['repo'], r['sha'], r['on_default_branch'], r['in_merged_pr'], r['pqc_in_linked_text'])
                    for r in map(json.loads, stream)]
    return {(repo, sha): (on_main, in_pr, linked) for repo, sha, on_main, in_pr, linked in rows}
