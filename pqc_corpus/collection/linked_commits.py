"""Metadata for PR-linked commits that are absent from the frozen Git snapshot.

PR-only commits can lie outside the frozen advertised refs. They are read from
the frozen mirror when present, otherwise fetched into a separate recovery
mirror that borrows the frozen objects. The frozen mirror is never changed.
"""

import os
from pathlib import Path
import re
import subprocess
from typing import Any

from ..common import mirror_name, now

METADATA_FORMAT = '%H%x00%B%x00%an%x00%ae%x00%cn%x00%ce%x00%aI%x00%cI%x00%P'
SHA = re.compile(r'[0-9a-f]{40,64}')


def git(path: Path, *args: str) -> str:
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1'}
    return subprocess.check_output(
        ['git', '-C', str(path), '-c', 'credential.helper=', '-c', 'log.showSignature=false', *args],
        env=env, stderr=subprocess.PIPE, timeout=120,
    ).decode('utf-8', errors='replace')


def find_object_store(candidates: tuple[Path, ...], sha: str) -> Path | None:
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            git(candidate, 'cat-file', '-e', sha + '^{commit}')
            return candidate
        except subprocess.SubprocessError:
            pass
    return None


def fetch_into_recovery_mirror(recovery: Path, mirror: Path, repo: str, sha: str) -> None:
    recovery.mkdir(parents=True, exist_ok=True)
    git(recovery, 'init', '--bare')
    if mirror.exists():
        info = recovery / 'objects/info'
        info.mkdir(parents=True, exist_ok=True)
        (info / 'alternates').write_text(str((mirror / 'objects').resolve()) + '\n')
    git(recovery, 'fetch', '--no-tags', f'https://github.com/{repo}.git', sha)


def linked_metadata(run: Path, repo: str, sha: str) -> dict[str, Any]:
    """Read PR-only objects without changing the frozen source mirror."""
    if not SHA.fullmatch(sha):
        raise ValueError('Invalid linked commit SHA')
    mirror = run / 'mirrors' / mirror_name(repo)
    recovery = run / 'recovery_mirrors' / mirror_name(repo)
    directory = find_object_store((mirror, recovery), sha)
    if directory is None:
        fetch_into_recovery_mirror(recovery, mirror, repo, sha)
        directory = recovery
    output = git(directory, 'show', '-s', f'--format={METADATA_FORMAT}', sha)
    fields = output.rstrip('\n').split('\0')
    if len(fields) != 9 or fields[0] != sha:
        raise ValueError('Unexpected Git metadata output')
    parents = fields[8].split()
    return {
        'repo': repo,
        'sha': sha,
        'message': fields[1].rstrip('\n'),
        'author': {'name': fields[2], 'email': fields[3]},
        'committer': {'name': fields[4], 'email': fields[5]},
        'authored_at': fields[6],
        'committed_at': fields[7],
        'parents': parents,
        'is_merge': len(parents) > 1,
        'collected_at': now(),
        'source': 'selected_pr_linked_object',
        'object_store': str(directory.resolve()),
    }
