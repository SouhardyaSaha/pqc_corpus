"""Step 4, squash copies: a pull request's original commit when its squash-merge copy is on the default branch.

A squash merge writes a new commit onto the default branch with the pull
request's change and its number appended to the subject ("... (#29)"). For a
single-commit pull request, the original commit has the same patch id. Within a
repository, non-merge commits with the same patch id and the same subject apart
from a trailing "(#N)", at least one of which carries it, are one change. If
exactly one copy is on the default branch it is kept and the others removed;
otherwise the group is kept whole.
"""

from collections import defaultdict
import re

from .facts import Commit
from .step import Removal

PR_SUFFIX = re.compile(r"\s*\(#\d+\)\s*$")
REASON = "pull-request original of a squash-merge copy on the default branch"


def removals(commits: list[Commit]) -> list[Removal]:
    groups: dict[tuple[str, str], list[Commit]] = defaultdict(list)
    for commit in commits:
        if commit.patch_id and not commit.is_merge:
            groups[(commit.repo, commit.patch_id)].append(commit)
    found = []
    for copies in groups.values():
        if len(copies) < 2:
            continue
        subjects = {PR_SUFFIX.sub("", c.subject) for c in copies}
        if len(subjects) != 1 or not any(PR_SUFFIX.search(c.subject) for c in copies):
            continue
        on_main = [c for c in copies if c.on_default_branch]
        if len(on_main) != 1:
            continue
        found += [Removal(c.repo, c.sha, REASON, on_main[0].sha) for c in copies if c is not on_main[0]]
    return found
