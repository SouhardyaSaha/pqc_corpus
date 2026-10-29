"""Step 5, merge commits: merge commits whose merged work is already in the set.

A merge commit's first-parent diff combines the changes of the commits it
merges. When the merged branch's tip (the merge's second parent) is itself in
the set, those changes are already counted there, so the merge commit would
count them again (German, Adams & Hassan, 2016: a merge has no change of its
own). Only the tip is checked, not every merged commit.
"""

from .facts import Commit
from .step import Removal

REASON = "merge commit whose merged branch tip is in the set"


def removals(commits: list[Commit]) -> list[Removal]:
    present = {c.key for c in commits}
    return [
        Removal(c.repo, c.sha, REASON, c.parents[1])
        for c in commits
        if c.is_merge and len(c.parents) > 1 and (c.repo, c.parents[1]) in present
    ]
