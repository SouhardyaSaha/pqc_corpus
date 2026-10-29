"""A commit's patch and changed files, compared with its first parent.

Policy: first parent, or the empty tree for a root commit; three lines of
context; every path; no rename detection, text conversion or external diff
tools; no indent heuristic (hunks are placed as Git's plain Myers diff places
them); full object IDs; complete Git binary patches. Git runs without the
user's or the system's configuration, so the output depends only on the
objects in the mirror.
"""

import base64
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
DIFF_OPTIONS = ('--no-color', '--no-renames', '--no-textconv', '--no-ext-diff', '--no-indent-heuristic',
                '--full-index')
TIMEOUT_SECONDS = 1800
ENVIRONMENT = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_TERMINAL_PROMPT': '0'}


@dataclass(frozen=True)
class CommitDiff:
    patch: bytes
    changed_files: list[dict]

    @property
    def encoded_patch(self) -> tuple[str, str]:
        """(`utf-8` or `base64`, text): base64 keeps the exact bytes of a patch that is not UTF-8."""
        try:
            return 'utf-8', self.patch.decode('utf-8')
        except UnicodeDecodeError:
            return 'base64', base64.b64encode(self.patch).decode('ascii')


def git(store: Path, *args: str) -> bytes:
    return subprocess.run(['git', '-C', str(store), *args], capture_output=True, check=True,
                          timeout=TIMEOUT_SECONDS, env=ENVIRONMENT).stdout


def base_of(parents: list[str]) -> str:
    return parents[0] if parents else EMPTY_TREE


def changed_files(store: Path, base: str, sha: str) -> list[dict]:
    """`{path, status, additions, deletions, binary}` per file, in Git's order."""
    raw = git(store, 'diff', *DIFF_OPTIONS, '--raw', '--numstat', '-z', base, sha).split(b'\0')
    statuses: list[tuple[str, str]] = []
    counts: dict[str, tuple[int | None, int | None]] = {}
    index = 0
    while index < len(raw) and raw[index]:
        field = raw[index]
        if field.startswith(b':'):
            # `:old_mode new_mode old_id new_id STATUS` then the path.
            statuses.append((field.split()[-1].decode(), raw[index + 1].decode('utf-8', 'surrogateescape')))
            index += 2
        else:
            added, deleted, path = field.split(b'\t', 2)
            binary = added == b'-'
            counts[path.decode('utf-8', 'surrogateescape')] = (
                None if binary else int(added), None if binary else int(deleted))
            index += 1
    files = []
    for status, path in statuses:
        additions, deletions = counts[path]
        files.append({'path': path, 'status': status, 'additions': additions,
                      'deletions': deletions, 'binary': additions is None})
    return files


def commit_diff(store: Path, sha: str, parents: list[str]) -> CommitDiff:
    base = base_of(parents)
    patch = git(store, 'diff', *DIFF_OPTIONS, '--binary', '-U3', base, sha)
    return CommitDiff(patch=patch, changed_files=changed_files(store, base, sha))
