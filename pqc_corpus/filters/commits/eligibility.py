"""Step 1, eligibility: keep a commit only if it is on the default branch or in a merged pull request.

This removes commits that exist only on side branches or in pull requests that
were never merged. Both facts are observations recorded when the commits were
mined (`on_default_branch`, `in_merged_pr`).
"""

from .facts import Commit
from .step import Removal

REASON = "not reachable from the default branch and in no merged pull request"


def removals(commits: list[Commit]) -> list[Removal]:
    return [Removal(c.repo, c.sha, REASON) for c in commits if not (c.on_default_branch or c.in_merged_pr)]
