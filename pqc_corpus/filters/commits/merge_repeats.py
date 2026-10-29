"""Step 3, merge repeats: a merge commit whose patch repeats a non-merge commit of the same repository.

A merge has no change of its own (German, Adams & Hassan, 2016). When a merge's
first-parent diff has the same patch id as a non-merge commit in the same
repository (typically a single-commit pull request merged with a merge commit),
the merge commit is the copy: it is removed and the non-merge commit kept.
"""

from collections import defaultdict

from .facts import Commit
from .step import Removal

REASON = "merge commit repeats the patch of a non-merge commit"


def removals(commits: list[Commit]) -> list[Removal]:
    groups: dict[tuple[str, str], list[Commit]] = defaultdict(list)
    for commit in commits:
        if commit.patch_id:
            groups[(commit.repo, commit.patch_id)].append(commit)
    found = []
    for copies in groups.values():
        merges = [c for c in copies if c.is_merge]
        normal = [c for c in copies if not c.is_merge]
        if merges and normal:
            found += [Removal(m.repo, m.sha, REASON, normal[0].sha) for m in merges]
    return found
