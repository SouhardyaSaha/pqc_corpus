"""Persistent, resumable collection of a prepared run.

For each repository: corpus search (A, B or C; stored as corpus plans) → selected
GitHub API collection → full Git source → recovery of pull-request commit lists
GitHub cut short → commit selection. Exit codes: 0
complete, 2 complete with unresolved repositories, 130 paused. Rerunning skips
repositories already completed.
"""

import fcntl
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from ..common import connect_read_only, lowercase_slug, mirror_name, now, read_json, write_json_atomic
from ..interrupt import StopController
from ..paths import PROJECT_ROOT
from .commit_selection import select_git
from .plans import load_plan

PASSES = 3
REQUIRED_PHASES = {'phase:inventory', 'phase:discussions', 'phase:pr_details'}
# Largest repositories first, so their long-running work starts early.
PRIORITY = ['kubernetes/kubernetes', 'golang/go', 'openssl/openssl', 'wolfssl/wolfssl',
            'ziglang/zig', 'open-quantum-safe/liboqs', 'authelia/authelia']
DENO = ['deno', 'run', '--config', 'collector/deno.json', '-A']


def ordered_entries(repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(entry: dict[str, Any]) -> tuple[int, str]:
        name = entry['repo'].lower()
        return (PRIORITY.index(name) if name in PRIORITY else len(PRIORITY), name)
    return sorted(repositories, key=key)


def api_coverage(run: Path, repo: str) -> bool:
    """All three API phases finished for the repository, with no recorded failure."""
    c = connect_read_only(run / 'github.sqlite')
    row = c.execute('SELECT repo_id FROM aliases WHERE requested_name=?', (repo.lower(),)).fetchone()
    if not row:
        c.close()
        return False
    done = {stream for stream, in c.execute(
        "SELECT stream FROM progress WHERE repo_id=? AND done=1 AND stream LIKE 'phase:%'",
        (row[0],))}
    failures = c.execute('SELECT count(*) FROM failures WHERE lower(repo)=?',
                         (repo.lower(),)).fetchone()[0]
    c.close()
    return done >= REQUIRED_PHASES and failures == 0


def git_source_complete(source_git: Path, repo: str) -> bool:
    if not source_git.exists():
        return False
    c = connect_read_only(source_git)
    exists = c.execute("SELECT 1 FROM repositories WHERE lower(repo)=? AND status='completed'",
                       (repo.lower(),)).fetchone()
    c.close()
    return exists is not None


def is_complete(run: Path) -> bool:
    """Every manifest repository finished without unresolved gaps."""
    states_path = run / 'pipeline_repositories.json'
    if not states_path.exists():
        return False
    states = read_json(states_path)
    return all(states.get(entry['repo'], {}).get('status') == 'completed'
               for entry in read_json(run / 'manifest.json')['repositories'])


class CorpusPipeline:
    def __init__(self, run: Path, stop: StopController) -> None:
        self.run = run
        self.stop = stop
        self.entries = ordered_entries(read_json(run / 'manifest.json')['repositories'])
        self.state_path = run / 'pipeline_repositories.json'
        self.states: dict[str, dict[str, Any]] = (
            read_json(self.state_path) if self.state_path.exists() else {})
        self.status: dict[str, Any] = {
            'pid': os.getpid(), 'started_at': now(), 'repositories': len(self.entries),
        }

    def report(self, **values: Any) -> None:
        completed = sum(state.get('status') == 'completed' for state in self.states.values())
        self.status.update(values, updated_at=now(), repositories_completed=completed)
        write_json_atomic(self.run / 'pipeline_status.json', self.status)

    def save_state(self, repo: str, **state: Any) -> None:
        self.states[repo] = {**state, 'updated_at': now()}
        write_json_atomic(self.state_path, self.states)

    def command(self, args: list[str], log: Path) -> int:
        """Run a child worker, forwarding stop signals; raise if a stop was requested."""
        if self.stop.requested:
            raise InterruptedError('paused')
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a') as out:
            self.stop.child = subprocess.Popen(args, cwd=PROJECT_ROOT, stdout=out,
                                               stderr=subprocess.STDOUT)
            code = self.stop.child.wait()
            self.stop.child = None
        if self.stop.requested:
            raise InterruptedError('paused')
        return code

    def run_all(self) -> int:
        try:
            for attempt in range(1, PASSES + 1):
                for index, entry in enumerate(self.entries):
                    repo = entry['repo']
                    if self.states.get(repo, {}).get('status') == 'completed':
                        continue
                    if self.stop.requested:
                        raise InterruptedError('paused')
                    self.process(repo, index, attempt)
                if all(self.states.get(e['repo'], {}).get('status') == 'completed'
                       for e in self.entries):
                    break
            incomplete = {k: v for k, v in self.states.items() if v.get('status') != 'completed'}
            self.report(status='completed_with_gaps' if incomplete else 'completed',
                        stage='finished', unresolved_repositories=len(incomplete))
            return 2 if incomplete else 0
        except InterruptedError:
            self.report(status='paused')
            return 130

    def process(self, repo: str, index: int, attempt: int) -> None:
        """Run every stage for one repository; record failures and move on."""
        try:
            # Stage names and state keys keep the frozen run's names (tier_search, tier).
            self.report(status='running', stage='tier_search', repo=repo,
                        repository_index=index + 1, attempt=attempt)
            self.search_corpus(repo)
            corpus = load_plan(self.run, repo)['tier']
            self.report(stage='collect_selected_api', tier=corpus)
            self.collect_api(repo)
            source = self.git_source(repo)
            self.recover_commit_lists(repo)
            self.report(stage='select_git')
            select_git(self.run, repo, source)
            git_result = read_json(self.run / 'git_selection' / (lowercase_slug(repo) + '.json'))
            complete = (api_coverage(self.run, repo)
                        and not git_result['linked_shas_missing_metadata']
                        and not git_result['pr_detail_gaps'])
            self.save_state(repo, status='completed' if complete else 'completed_with_gaps',
                            tier=corpus)
            print(f'[{now()}] {repo}: {self.states[repo]["status"]}, corpus {corpus}',
                  flush=True)
        except InterruptedError:
            raise
        except Exception as exc:
            self.save_state(repo, status='failed', error=str(exc)[:600])
            print(f'[{now()}] {repo}: {exc}', flush=True)

    def log_path(self, repo: str, kind: str) -> Path:
        return self.run / 'logs' / f'{lowercase_slug(repo)}.{kind}.log'

    def search_corpus(self, repo: str) -> None:
        code = self.command(
            [*DENO, 'collector/corpus_search.ts', f'--run-dir={self.run}', f'--repo={repo}'],
            self.log_path(repo, 'search'))
        if code:
            raise RuntimeError(
                f'Corpus search exited {code}; inspect logs/{lowercase_slug(repo)}.search.log')

    def collect_api(self, repo: str) -> None:
        code = self.command(
            ['flock', '-n', str(self.run / 'api.lock'), *DENO,
             'collector/collect_api.ts', f'--run-dir={self.run}',
             f'--only-repo={repo}', '--pr-batch-size=10'],
            self.log_path(repo, 'api'))
        # Exit code 2 means collection finished with recorded, inspectable gaps.
        if code not in (0, 2):
            raise RuntimeError(
                f'API collector exited {code}; inspect logs/{lowercase_slug(repo)}.api.log')

    def recover_commit_lists(self, repo: str) -> None:
        """Rebuild pull-request commit lists that GitHub cut short (at 250 commits) from the mirror.

        The collector records each short list as a failure; recovery accepts a Git
        base..head range only if it has the expected count and every SHA the API
        returned, and clears the failure. Unrecovered lists stay recorded, so the
        repository is reported with gaps.
        """
        api = connect_read_only(self.run / 'github.sqlite')
        short = api.execute(
            "SELECT count(*) FROM failures WHERE lower(repo)=? AND error LIKE 'Incomplete %:commits:%'",
            (repo.lower(),)).fetchone()[0]
        api.close()
        if not short:
            return
        self.report(stage='recover_commit_lists')
        self.command([*DENO, 'collector/recover_commits.ts', f'--run-dir={self.run}'],
                     self.log_path(repo, 'recover'))

    def git_source(self, repo: str) -> Path:
        """A full Git source for the repository: every advertised ref, mined once and frozen."""
        source_dir = self.run / 'git_sources' / lowercase_slug(repo)
        source_git = source_dir / 'git.sqlite'
        if git_source_complete(source_git, repo):
            return source_git
        source_dir.mkdir(parents=True, exist_ok=True)
        if not (source_dir / 'manifest.json').exists():
            write_json_atomic(source_dir / 'manifest.json', {
                'repositories': [{'repo': repo}],
                'purpose': 'Git source for commit selection; all fetched refs, not all PQC',
            })
        self.report(stage='fetch_git')
        code = self.command(
            [sys.executable, '-u', '-m', 'pqc_corpus.collection.git_history',
             f'--run-dir={source_dir}'],
            self.log_path(repo, 'git'))
        if code:
            raise RuntimeError(f'Git source collection exited {code}')
        mirror = source_dir / 'mirrors' / mirror_name(repo)
        target = self.run / 'mirrors' / mirror.name
        if not target.exists():
            target.symlink_to(mirror.resolve(), target_is_directory=True)
        return source_git


def collect(run: Path) -> int:
    """Collect every repository of a prepared run; returns the pipeline exit code."""
    # Held until return so that two pipelines never process the same run.
    with (run / 'pipeline.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = StopController()
        stop.install()
        return CorpusPipeline(run, stop).run_all()
