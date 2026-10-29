"""A small finished run on disk: one repository with a Git mirror and stored GitHub records."""

import json
from pathlib import Path
import sqlite3
import subprocess

from pqc_corpus.common import write_json_atomic
from pqc_corpus.export.author_key import AuthorKeys, create_secret

REPO = 'fixture/project'
GITHUB_SCHEMA = '''
CREATE TABLE repositories (id TEXT PRIMARY KEY, requested_name TEXT, full_name TEXT, data TEXT, fetched_at TEXT);
CREATE TABLE records (repo_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
    fetched_at TEXT NOT NULL, PRIMARY KEY(repo_id,kind,key));
CREATE TABLE aliases (requested_name TEXT PRIMARY KEY, repo_id TEXT NOT NULL);
'''


def author_keys(root: Path) -> AuthorKeys:
    create_secret(root / 'author_key.secret')
    return AuthorKeys(root / 'author_key.secret')


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ['git', '-C', str(path), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', *args],
        stderr=subprocess.DEVNULL, text=True).strip()


def make_source(root: Path) -> tuple[Path, dict[str, str]]:
    """A repository: root commit, a PQC change with a binary file, a side branch merged, an unmerged branch."""
    source = root / 'source'
    source.mkdir()
    git(source, 'init', '-b', 'main')
    (source / 'README.md').write_text('fixture\n')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Initial commit')
    shas = {'root': git(source, 'rev-parse', 'HEAD')}
    (source / 'kem.c').write_text('int ml_kem_768(void) { return 0; }\n')
    (source / 'logo.bin').write_bytes(bytes(range(256)))
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Add ML-KEM-768 (#2)')
    shas['kem'] = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', '-b', 'feature')
    (source / 'notes.txt').write_text('notes\n')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Add notes')
    shas['feature'] = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', 'main')
    git(source, 'merge', '--no-ff', 'feature', '-m', 'Merge feature')
    shas['merge'] = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', '-b', 'unmerged')
    (source / 'draft.txt').write_text('draft\n')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Draft')
    shas['unmerged'] = git(source, 'rev-parse', 'HEAD')
    git(source, 'checkout', 'main')
    return source, shas


def git_payload(mirror: Path, sha: str) -> dict:
    fields = git(mirror, 'show', '-s', '--format=%B%x00%an%x00%ae%x00%cn%x00%ce%x00%aI%x00%cI%x00%P', sha)
    message, an, ae, cn, ce, at, ct, parents = fields.split('\0')
    return {'repo': REPO, 'sha': sha, 'message': message.rstrip('\n'), 'author': {'name': an, 'email': ae},
            'committer': {'name': cn, 'email': ce}, 'authored_at': at, 'committed_at': ct,
            'parents': parents.split(), 'is_merge': len(parents.split()) > 1,
            'collected_at': '2026-09-21T00:00:00+00:00'}


def make_run(root: Path, tier: str = 'A') -> tuple[Path, dict[str, str]]:
    """A finished run: manifest, tier plan, mirror, git.sqlite and github.sqlite."""
    source, shas = make_source(root)
    run = root / 'run'
    mirror = run / 'mirrors' / 'fixture__project.git'
    mirror.parent.mkdir(parents=True)
    subprocess.run(['git', 'clone', '--mirror', str(source), str(mirror)], check=True, capture_output=True)
    write_json_atomic(run / 'manifest.json', {'repositories': [{'repo': REPO}], 'tiering': {'policy_sha256': 'p'}})
    write_json_atomic(run / 'tier_plans' / 'fixture__project.json',
                      {'repo': REPO, 'tier': tier, 'policy_sha256': 'p',
                       'metadata': {'pullRequests': {'totalCount': 4}, 'issues': {'totalCount': 3}}})
    write_json_atomic(run / 'git_selection' / 'fixture__project.json', {'scanned': 5, 'selected': 5})
    db = sqlite3.connect(run / 'git.sqlite')
    db.execute('CREATE TABLE commits(repo TEXT NOT NULL,sha TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(repo,sha))')
    for sha in shas.values():
        db.execute('INSERT INTO commits VALUES (?,?,?)', (REPO, sha, json.dumps(git_payload(mirror, sha))))
    db.commit()
    db.close()
    api = sqlite3.connect(run / 'github.sqlite')
    api.executescript(GITHUB_SCHEMA)
    meta = {'full_name': 'Fixture/Project', 'description': 'A post-quantum KEM', 'topics': ['pqc'], 'fork': False,
            'language': 'C', 'stargazers_count': 5, 'forks_count': 1, 'created_at': '2024-01-01T00:00:00Z'}
    api.execute('INSERT INTO repositories VALUES (?,?,?,?,?)',
                ('1', REPO, 'Fixture/Project', json.dumps(meta), '2026-09-21T00:00:00Z'))
    api.execute('INSERT INTO aliases VALUES (?,?)', (REPO, '1'))
    records = [
        ('issue', '10', {'number': 1, 'html_url': f'https://github.com/{REPO}/issues/1', 'title': 'Support ML-KEM',
                         'body': 'Please add it.', 'state': 'closed', 'state_reason': 'completed',
                         'user': {'login': 'alice'}, 'created_at': '2024-02-01T00:00:00Z',
                         'closed_at': '2024-02-03T00:00:00Z'}),
        ('issue', '11', {'number': 3, 'html_url': f'https://github.com/{REPO}/issues/3', 'title': 'Nightly failed',
                         'body': None, 'state': 'open', 'state_reason': None, 'user': {'login': 'ci[bot]'},
                         'created_at': '2024-03-01T00:00:00Z', 'closed_at': None}),
        ('issue_comment', '21', {'id': 21, 'issue_url': f'https://api.github.com/repos/{REPO}/issues/1',
                                 'user': {'login': 'bob'}, 'created_at': '2024-02-02T00:00:00Z', 'body': 'Second'}),
        ('issue_comment', '20', {'id': 20, 'issue_url': f'https://api.github.com/repos/{REPO}/issues/1',
                                 'user': None, 'created_at': '2024-02-01T12:00:00Z', 'body': 'First'}),
        ('issue_comment', '22', {'id': 22, 'issue_url': f'https://api.github.com/repos/{REPO}/issues/2',
                                 'user': {'login': 'carol'}, 'created_at': '2024-02-02T00:00:00Z', 'body': 'On PR'}),
        ('closing_issue_link', '2:I1', {'pr_number': 2, 'number': 1,
                                        'repository': {'nameWithOwner': 'Fixture/Project'}}),
        ('pr_commit', f'2:{shas["kem"]}', {'pr_number': 2, 'commit': {'oid': shas['kem']}}),
        ('pull', '30', {'number': 2, 'html_url': f'https://github.com/{REPO}/pull/2', 'title': 'Add ML-KEM-768',
                        'body': 'Closes #1', 'state': 'closed', 'draft': False, 'user': {'login': 'alice'},
                        'created_at': '2024-02-02T00:00:00Z', 'closed_at': '2024-02-03T00:00:00Z',
                        'merged_at': '2024-02-03T00:00:00Z', 'base': {'ref': 'main'}, 'head': {'ref': 'kem'}}),
        ('review', '2:R1', {'pr_number': 2, 'databaseId': 40, 'author': {'login': 'bob'}, 'state': 'APPROVED',
                            'submittedAt': '2024-02-02T18:00:00Z', 'body': ''}),
        ('review_comment', '50', {'id': 50, 'pull_request_url': f'https://api.github.com/repos/{REPO}/pulls/2',
                                  'user': {'login': 'bob'}, 'created_at': '2024-02-02T17:00:00Z', 'path': 'kem.c',
                                  'line': 1, 'body': 'Constant time?'}),
    ]
    for kind, key, data in records:
        api.execute('INSERT INTO records VALUES (?,?,?,?,?)', ('1', kind, key, json.dumps(data),
                                                              '2026-09-21T00:00:00Z'))
    api.commit()
    api.close()
    return run, shas
