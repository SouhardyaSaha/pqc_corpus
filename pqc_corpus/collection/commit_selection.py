"""Select one repository's commit metadata according to its corpus.

Corpora A and C keep every commit. Corpus B keeps the union of
commits linked to selected PRs and commits whose message contains a policy term,
recording the reason for each selected commit.
"""

import json
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any

from ..common import connect_read_only, lowercase_slug, now, read_json, write_json_atomic
from .linked_commits import linked_metadata
from .plans import POLICY_FILE, load_plan

SCHEMA = '''CREATE TABLE IF NOT EXISTS commits(repo TEXT NOT NULL,sha TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(repo,sha));
      CREATE TABLE IF NOT EXISTS repositories(repo TEXT PRIMARY KEY,status TEXT NOT NULL,data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS commit_selection(repo TEXT,sha TEXT,reason TEXT,PRIMARY KEY(repo,sha));'''


def message_pattern(terms: list[str]) -> re.Pattern[str]:
    """Case-insensitive literal term matching with alphanumeric boundaries.

    Boundaries avoid matching e.g. PQC inside an unrelated identifier. This is
    not a reproduction of GitHub search.
    """
    alternatives = '|'.join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    return re.compile(r'(?<![A-Za-z0-9])(?:' + alternatives + r')(?![A-Za-z0-9])', re.I)


def selection_reason(corpus: str, sha: str, message: str, linked: set[str],
                     pattern: re.Pattern[str]) -> str:
    """Why a commit is selected; an empty string means it is not.

    `corpus` is the plan's value (`unrated` for C); the reasons keep the frozen run's
    names (`all_tier_A`, ...).
    """
    if corpus != 'B':
        return 'all_tier_' + corpus
    reasons = []
    if sha in linked:
        reasons.append('selected_pr')
    if pattern.search(message):
        reasons.append('commit_message_keyword')
    return '+'.join(reasons)


def save_commit(out: sqlite3.Connection, repo: str, sha: str, data: str, reason: str) -> None:
    out.execute('INSERT OR REPLACE INTO commits VALUES (?,?,?)', (repo, sha, data))
    out.execute('INSERT OR REPLACE INTO commit_selection VALUES (?,?,?)', (repo, sha, reason))


def linked_pr_commits(api: sqlite3.Connection, repo_id: str) -> set[str]:
    rows = api.execute("SELECT data FROM records WHERE repo_id=? AND kind='pr_commit'", (repo_id,))
    return {json.loads(data)['commit']['oid'] for data, in rows}


def recover_linked(out: sqlite3.Connection, run: Path, repo: str,
                   missing_shas: list[str]) -> tuple[list[str], dict[str, str]]:
    """Add metadata for linked commits outside the snapshot; keep failures explicit."""
    missing: list[str] = []
    errors: dict[str, str] = {}
    for sha in missing_shas:
        try:
            payload = linked_metadata(run, repo, sha)
            save_commit(out, repo, sha, json.dumps(payload), 'selected_pr')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            missing.append(sha)
            errors[sha] = type(exc).__name__
    return missing, errors


def select_git(run: Path, repo: str, source_path: Path) -> None:
    """Write the repository's selected commits into the run's `git.sqlite`."""
    plan = load_plan(run, repo)
    pattern = message_pattern(read_json(run / POLICY_FILE)['terms'])
    source = connect_read_only(source_path)
    available = source.execute('SELECT repo,status FROM repositories WHERE lower(repo)=?',
                               (repo.lower(),)).fetchone()
    if not available or available[1] != 'completed':
        raise ValueError(f'Git source incomplete: {repo}')
    api = connect_read_only(run / 'github.sqlite')
    linked = linked_pr_commits(api, plan['repo_id'])
    corpus = plan['tier']
    out = sqlite3.connect(run / 'git.sqlite')
    out.executescript(SCHEMA)
    scanned = 0
    for _, sha, data in source.execute('SELECT * FROM commits WHERE repo=?', (available[0],)):
        scanned += 1
        message = json.loads(data).get('message', '') if corpus == 'B' else ''
        reason = selection_reason(corpus, sha, message, linked, pattern)
        if reason:
            save_commit(out, repo, sha, data, reason)
    found = {sha for sha, in out.execute('SELECT sha FROM commits WHERE repo=?', (repo,))}
    missing, recovery_errors = recover_linked(out, run, repo, sorted(linked - found))
    detail_gaps = api.execute(
        "SELECT count(*) FROM failures WHERE lower(repo)=? AND stage LIKE 'pr:%'",
        (repo.lower(),)).fetchone()[0]
    selected = out.execute('SELECT count(*) FROM commits WHERE repo=?', (repo,)).fetchone()[0]
    result: dict[str, Any] = {
        'at': now(), 'source': str(source_path), 'tier': corpus, 'scanned': scanned,
        'selected': selected, 'linked_shas_missing_metadata': missing,
        'linked_metadata_errors': recovery_errors, 'pr_detail_gaps': detail_gaps,
    }
    status = 'completed_with_gaps' if missing or detail_gaps else 'completed'
    out.execute('INSERT OR REPLACE INTO repositories VALUES (?,?,?)',
                (repo, status, json.dumps(result)))
    out.commit()
    write_json_atomic(run / 'git_selection' / (lowercase_slug(repo) + '.json'), result)
    print(json.dumps({'repo': repo, 'git_scanned': scanned, 'git_selected': selected,
                      'missing_linked_metadata': len(missing)}), flush=True)
    source.close()
    api.close()
    out.close()
