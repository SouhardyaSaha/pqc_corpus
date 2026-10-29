"""Resumable Git worker: clone, freeze, and mine every manifest repository.

Exit codes: 0 complete, 2 complete with failed repositories, 3 paused for low
disk space, 130 paused by a signal.
"""

import argparse
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from ...common import mirror_name, now, read_json, write_json_atomic
from ...interrupt import StopController
from .clone import clone
from .commits import WorkerPause, mine_commits, save_refs_snapshot, verify_commit_count

PASSES = 3
# Kept byte-identical: SQLite stores this text as the table definition.
SCHEMA = '''CREATE TABLE IF NOT EXISTS commits (
        repo TEXT NOT NULL, sha TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(repo,sha));
        CREATE TABLE IF NOT EXISTS repositories (
        repo TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);'''


class StatusFile:
    """Live `git_status.json`, rewritten atomically on every update."""

    def __init__(self, path: Path, **initial: Any) -> None:
        self.path = path
        self.values = dict(initial)

    def report(self, **values: Any) -> None:
        self.values.update(values, updated_at=now())
        write_json_atomic(self.path, self.values)


def open_database(run: Path) -> sqlite3.Connection:
    db = sqlite3.connect(run / 'git.sqlite')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript(SCHEMA)
    return db


def set_repository_status(db: sqlite3.Connection, repo: str, status: str,
                          data: dict[str, Any]) -> None:
    db.execute('INSERT OR REPLACE INTO repositories VALUES (?,?,?)',
               (repo, status, json.dumps(data)))


class GitWorker:
    def __init__(self, run: Path, repositories: list[dict[str, Any]], minimum_free: int,
                 stop: StopController) -> None:
        self.run = run
        self.repositories = repositories
        self.minimum_free = minimum_free
        self.stop = stop
        self.mirrors = run / 'mirrors'
        self.db = open_database(run)
        self.status = StatusFile(
            run / 'git_status.json', pid=os.getpid(), worker='git',
            pydriller_version=importlib.metadata.version('pydriller'),
        )

    def disk_low(self) -> bool:
        return shutil.disk_usage(self.run).free < self.minimum_free

    def run_passes(self) -> int:
        """Up to three passes over unfinished repositories; failures are retried."""
        self.mirrors.mkdir(exist_ok=True)
        try:
            for attempt in range(PASSES):
                for index, entry in enumerate(self.repositories):
                    self.process(entry['repo'], index, attempt)
                if self.stop.requested:
                    raise WorkerPause(130, status='paused')
                completed = self.completed_count()
                if completed == len(self.repositories):
                    total = self.db.execute('SELECT count(*) FROM commits').fetchone()[0]
                    self.status.report(status='completed', repositories_completed=completed,
                                       total_commits=total)
                    return 0
        except WorkerPause as pause:
            self.status.report(**pause.status)
            return pause.exit_code
        self.status.report(status='completed_with_gaps', repositories_completed=completed)
        return 2

    def completed_count(self) -> int:
        return self.db.execute(
            "SELECT count(*) FROM repositories WHERE status='completed'").fetchone()[0]

    def process(self, repo: str, index: int, attempt: int) -> None:
        old = self.db.execute('SELECT status FROM repositories WHERE repo=?', (repo,)).fetchone()
        if old and old[0] == 'completed':
            return
        if self.stop.requested:
            raise WorkerPause(130, status='paused')
        if self.disk_low():
            raise WorkerPause(3, status='paused_low_disk')
        total = len(self.repositories)
        self.status.report(status='running', stage='clone', repo=repo,
                           repository_index=index + 1, repositories=total,
                           attempt=attempt + 1)
        print(f'[{now()}] [git] {index + 1}/{total} {repo}', flush=True)
        try:
            self.mine_repository(repo)
        except WorkerPause:
            raise
        except Exception as exc:
            # Keep the failure explicit; the next pass or run retries it.
            self.db.commit()
            message = f'{type(exc).__name__}: {exc}'[:500]
            set_repository_status(self.db, repo, 'failed', {'at': now(), 'error': message})
            self.db.commit()
            print(f'[{now()}] [git] deferred {repo}: {message}', flush=True)

    def mine_repository(self, repo: str) -> None:
        mirror = self.mirrors / mirror_name(repo)
        snapshot_path = self.mirrors / (repo.replace('/', '__') + '.refs.json')
        if not mirror.exists():
            clone(repo, mirror, self.minimum_free, self.stop)
        if not snapshot_path.exists():
            save_refs_snapshot(repo, mirror, snapshot_path)
        mine_commits(self.db, repo, mirror, self.stop, self.disk_low, self.status.report)
        actual = verify_commit_count(self.db, repo, mirror)
        set_repository_status(self.db, repo, 'completed', {
            'completed_at': now(), 'commits': actual, 'refs_snapshot': str(snapshot_path),
        })
        self.db.commit()
        print(f'[{now()}] [git] completed {repo}: {actual} commits', flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--min-free-gib', type=int, default=20)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    repositories = read_json(run / 'manifest.json')['repositories']
    # Held until exit so that two workers never mine the same run.
    lock = (run / 'git.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stop = StopController()
    stop.install()
    worker = GitWorker(run, repositories, args.min_free_gib * 1024**3, stop)
    return worker.run_passes()
