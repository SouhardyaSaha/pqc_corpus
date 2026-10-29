"""One mined commit reduced to the facts the filter steps need, read in one pass.

Patches can be very large, so each record's patch is read once here and only
what the steps need is kept: its patch id, its content hash for the rebased-copy
step, and whether PQC terms appear in it. A patch over `MAX_PATCH_BYTES` is
treated as unreadable: it counts as mentioning PQC and has no patch id or content
hash, so no keyword step removes it and no duplicate step groups it.
"""

import base64
from dataclasses import dataclass
import re
from typing import Any

from ..terms import mentions_pqc, pqc_named_repository
from .patch_ids import changed_lines, content_hash, patch_id

MAX_PATCH_BYTES = 64 * 1024 * 1024
# Bot accounts: GitHub App logins end in `[bot]`; other bots name themselves "bot".
BOT_NAME = (re.compile(r'\[bot\]', re.IGNORECASE), re.compile(r'(?:^|[-_ ])bot(?:$|[-_ ])', re.IGNORECASE))


@dataclass(frozen=True)
class RepositoryFacts:
    in_fork: bool
    pqc_named: bool


@dataclass(frozen=True)
class Commit:
    repo: str
    sha: str
    subject: str
    is_merge: bool
    parents: tuple[str, ...]
    on_default_branch: bool
    in_merged_pr: bool
    # Message, author key, author time, and files with line counts: equal for rebased copies.
    change_signature: tuple | None
    paths: tuple[str, ...]
    is_bot: bool
    in_fork: bool
    pqc_named_repository: bool
    # A PQC term in the commit message, or in its linked pull requests and their closing issues.
    pqc_in_text: bool
    pqc_in_paths: bool
    pqc_in_changed_lines: bool
    pqc_in_diff: bool
    patch_id: str | None
    content_hash: str | None

    @property
    def key(self) -> tuple[str, str]:
        return self.repo, self.sha

    @property
    def mentions_pqc(self) -> bool:
        """A PQC term anywhere: text, file paths or changed lines."""
        return self.pqc_in_text or self.pqc_in_paths or self.pqc_in_changed_lines


def repository_facts(record: dict[str, Any]) -> RepositoryFacts:
    return RepositoryFacts(
        in_fork=bool(record['is_fork']),
        pqc_named=pqc_named_repository(record['repo'], record['description'] or '', list(record['topics'] or [])),
    )


def is_bot(name: str | None) -> bool:
    return any(rule.search(name or '') for rule in BOT_NAME)


def patch_bytes(record: dict[str, Any]) -> bytes:
    content = record['patch_content']
    return base64.b64decode(content) if record['patch_encoding'] == 'base64' else content.encode('utf-8')


def change_signature(record: dict[str, Any]) -> tuple | None:
    """None without changed files: such a commit is never grouped as a copy."""
    files = record['changed_files']
    if not files:
        return None
    return (
        record['message'] or '', record['author_key'], record['authored_at'],
        tuple(sorted((f['path'], f['additions'], f['deletions']) for f in files)),
    )


def from_record(record: dict[str, Any], repository: RepositoryFacts) -> Commit:
    raw = patch_bytes(record)
    readable = len(raw) <= MAX_PATCH_BYTES
    text = raw.decode('utf-8', 'replace') if readable else None
    paths = tuple(f['path'] for f in record['changed_files'])
    message = record['message'] or ''
    return Commit(
        repo=record['repo'],
        sha=record['sha'],
        subject=message.split('\n', 1)[0].strip(),
        is_merge=len(record['parents']) > 1,
        parents=tuple(record['parents']),
        on_default_branch=record['on_default_branch'],
        in_merged_pr=record['in_merged_pr'],
        change_signature=change_signature(record),
        paths=paths,
        is_bot=is_bot(record['author_name']) or is_bot(record['committer_name']),
        in_fork=repository.in_fork,
        pqc_named_repository=repository.pqc_named,
        pqc_in_text=bool(record['pqc_in_linked_text']) or mentions_pqc(message),
        pqc_in_paths=mentions_pqc(' '.join(paths)),
        pqc_in_changed_lines=True if text is None else mentions_pqc(changed_lines(text)),
        pqc_in_diff=True if text is None else mentions_pqc(text),
        patch_id=patch_id(raw) if readable and raw.strip() else None,
        content_hash=content_hash(raw) if readable else None,
    )
