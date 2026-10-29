"""The commit filter's eight steps, applied in order, each to what the previous ones left.

| Step | Module | Removes |
|---|---|---|
| 1 | `eligibility` | commits on no default branch and in no merged pull request |
| 2 | `rebased_copies` | rebased copies of default-branch commits |
| 3 | `merge_repeats` | merge commits that repeat a non-merge commit's patch |
| 4 | `squash_copies` | pull-request originals of squash-merge copies |
| 5 | `merge_commits` | merge commits whose merged work is in the set |
| 6 | `fork_history` | fork history with no PQC term |
| 7 | `general_libraries` | commits with no PQC term in repositories not about PQC |
| 8 | `housekeeping` | CI-only, lock-file-only, metadata-only, bot or empty commits with no PQC term in the diff |

Steps 2-5 remove duplicates: the change stays in the set through its kept copy
or the merged commits. Steps 6-8 depend on the PQC terms in `terms`. Order
matters: step 4 runs after step 3, so a group whose merge copy step 3 removed can
then be recognised as a squash copy.
"""

from typing import Callable

from . import (eligibility, fork_history, general_libraries, housekeeping, merge_commits, merge_repeats,
               rebased_copies, squash_copies)
from .facts import Commit
from .step import Removal

STEPS: tuple[tuple[str, Callable[[list[Commit]], list[Removal]]], ...] = (
    ('eligibility', eligibility.removals),
    ('rebased_copies', rebased_copies.removals),
    ('merge_repeats', merge_repeats.removals),
    ('squash_copies', squash_copies.removals),
    ('merge_commits', merge_commits.removals),
    ('fork_history', fork_history.removals),
    ('general_libraries', general_libraries.removals),
    ('housekeeping', housekeeping.removals),
)


def run(commits: list[Commit]) -> tuple[list[tuple[str, list[Removal]]], list[Commit]]:
    """Each step's removals in order, and the commits that remain."""
    remaining = commits
    results = []
    for name, removals in STEPS:
        removed = removals(remaining)
        results.append((name, removed))
        gone = {(r.repo, r.sha) for r in removed}
        remaining = [c for c in remaining if c.key not in gone]
    return results, remaining
