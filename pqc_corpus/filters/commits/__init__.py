"""Filter the mined commits to the filtered set (see `steps` for the eight steps).

Reads the mined commits file twice: once to reduce every commit to its facts,
then to copy the kept lines, unchanged and in input order, to the output. The
repository file supplies each repository's fork flag and PQC naming.
"""

from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from ...common import now, write_json_atomic
from ...export import jsonl
from .facts import Commit, RepositoryFacts, from_record, repository_facts
from .steps import STEPS, run

# Set in each worker process by `_start_worker`, so records are sent without this table.
_REPOSITORIES: dict[str, RepositoryFacts] = {}


def _start_worker(repositories: dict[str, RepositoryFacts]) -> None:
    global _REPOSITORIES
    _REPOSITORIES = repositories


def _line_facts(line: str) -> Commit:
    record = json.loads(line)
    return from_record(record, _REPOSITORIES[record['repo']])


def commit_facts(commits: Path, repositories: dict[str, RepositoryFacts], workers: int) -> list[Commit]:
    """Facts of every commit, in input order. At most `2 * workers` lines are in flight, so
    memory stays bounded however large the file and its patches are."""
    _start_worker(repositories)
    if workers <= 1:
        return [_line_facts(line) for line in jsonl.lines(commits)]
    facts: list[Commit] = []
    pending: deque[Future] = deque()
    with ProcessPoolExecutor(workers, initializer=_start_worker, initargs=(repositories,)) as pool:
        for line in jsonl.lines(commits):
            pending.append(pool.submit(_line_facts, line))
            if len(pending) >= 2 * workers:
                facts.append(pending.popleft().result())
        facts.extend(future.result() for future in pending)
    return facts


def write_removals(path: Path, number: int, name: str, removals: list) -> None:
    with path.open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['step', 'name', 'repo', 'sha', 'reason', 'duplicates_sha'])
        for r in removals:
            writer.writerow([number, name, r.repo, r.sha, r.reason, r.kept_sha or ''])


def kept_lines(source: Path, keep: set[tuple[str, str]]):
    for line in jsonl.lines(source):
        record = json.loads(line)
        if (record['repo'], record['sha']) in keep:
            yield line


def filter_commits(commits: Path, repositories: Path, output: Path, report: Path,
                   workers: int = os.cpu_count() or 1) -> dict[str, Any]:
    """Write the filtered commits to `output` (a file or a directory of parts) and the step-by-step
    removals to the new `report` directory."""
    if report.exists():
        raise ValueError(f'{report} exists; choose a new report directory')
    repos: dict[str, RepositoryFacts] = {r['repo']: repository_facts(r) for r in jsonl.read(repositories)}
    facts = commit_facts(commits, repos, workers)
    results, kept = run(facts)
    report.parent.mkdir(parents=True, exist_ok=True)
    # Stage the report directory and rename it into place: all files or none.
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=report.parent))
    try:
        steps, remaining = [], len(facts)
        for number, (name, removals) in enumerate(results, 1):
            file = f'{number:02d}_{name}.csv'
            write_removals(staging / file, number, name, removals)
            remaining -= len(removals)
            steps.append({'step': number, 'name': name, 'removed': len(removals), 'remaining': remaining,
                          'file': file})
        inputs = {'commits': jsonl.identity(commits), 'repositories': jsonl.identity(repositories)}
        written = jsonl.write_lines(output, kept_lines(commits, {c.key for c in kept}),
                                    filtered_from=inputs['commits']['name'])
        if written != remaining or written != len(kept):
            raise RuntimeError('Step counts do not add up')
        summary = {'created_at': now(), 'inputs': inputs, 'mined': len(facts), 'steps': steps,
                   'filtered': written, 'output': jsonl.identity(output)}
        write_json_atomic(staging / 'summary.json', summary)
        staging.rename(report)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return summary


__all__ = ['STEPS', 'filter_commits']
