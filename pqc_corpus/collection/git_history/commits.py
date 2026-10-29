"""Refs snapshots and commit metadata for one frozen mirror."""

import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Callable

from pydriller import Repository

from ...common import now, write_json_atomic
from ...interrupt import StopController

CHECKPOINT_COMMITS = 100
PROGRESS_LOG_COMMITS = 5000


class WorkerPause(Exception):
    """Stop cleanly after a checkpoint, with the status to report and exit code."""

    def __init__(self, exit_code: int, **status: Any) -> None:
        super().__init__(status.get('status', 'paused'))
        self.exit_code = exit_code
        self.status = status


def git_capture(*args: object) -> str:
    return subprocess.check_output(['git', *map(str, args)], text=True, timeout=120).strip()


def save_refs_snapshot(repo: str, mirror: Path, snapshot_path: Path) -> None:
    """Freeze the mirror: record every advertised ref and HEAD once."""
    refs = git_capture('-C', mirror, 'for-each-ref',
                       '--format=%(refname) %(objectname)').splitlines()
    head = subprocess.run(['git', '-C', str(mirror), 'symbolic-ref', 'HEAD'],
                          text=True, capture_output=True)
    write_json_atomic(snapshot_path, {
        'repo': repo,
        'captured_at': now(),
        'refs': refs,
        'head': head.stdout.strip(),
        'mirror': str(mirror),
        'git_version': git_capture('--version'),
    })


def commit_payload(repo: str, commit: Any) -> dict[str, Any]:
    """Commit metadata kept for every commit; diffs stay in the mirror."""
    return {
        'repo': repo,
        'sha': commit.hash,
        'message': commit.msg,
        'author': {'name': commit.author.name, 'email': commit.author.email},
        'committer': {'name': commit.committer.name, 'email': commit.committer.email},
        'authored_at': commit.author_date.isoformat(),
        'committed_at': commit.committer_date.isoformat(),
        'parents': commit.parents,
        'is_merge': commit.merge,
        'collected_at': now(),
    }


def mine_commits(
    db: sqlite3.Connection,
    repo: str,
    mirror: Path,
    stop: StopController,
    disk_low: Callable[[], bool],
    report: Callable[..., None],
) -> None:
    """Insert commits reachable from all refs, skipping those already saved.

    Commits are checkpointed every 100 new rows. A stop request or low disk
    space commits the open transaction and raises `WorkerPause`.
    """
    known = {row[0] for row in db.execute('SELECT sha FROM commits WHERE repo=?', (repo,))}
    saved = len(known)
    report(stage='commits', commits_saved=saved)
    history = Repository(str(mirror), include_refs=True, include_remotes=True)
    for commit in history.traverse_commits():
        if stop.requested:
            db.commit()
            raise WorkerPause(130, status='paused', commits_saved=saved)
        if commit.hash in known:
            continue
        db.execute('INSERT OR IGNORE INTO commits VALUES (?,?,?)',
                   (repo, commit.hash, json.dumps(commit_payload(repo, commit))))
        saved += 1
        if saved % CHECKPOINT_COMMITS == 0:
            db.commit()
            report(commits_saved=saved)
            if disk_low():
                raise WorkerPause(3, status='paused_low_disk')
        if saved % PROGRESS_LOG_COMMITS == 0:
            print(f'[{now()}] [git] {repo}: {saved} commits', flush=True)


def verify_commit_count(db: sqlite3.Connection, repo: str, mirror: Path) -> int:
    """An independent Git count checks completeness, including merge commits."""
    expected = int(git_capture('-C', mirror, 'rev-list', '--all', '--count'))
    actual = db.execute('SELECT count(*) FROM commits WHERE repo=?', (repo,)).fetchone()[0]
    if actual != expected:
        raise RuntimeError(f'Commit count mismatch: mined={actual}, git={expected}')
    return actual
