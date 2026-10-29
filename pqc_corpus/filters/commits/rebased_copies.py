"""Step 2, rebased copies: commits that are rebased copies of a commit on the default branch.

When a pull request is merged by rebasing, GitHub writes new commits onto the
default branch. The pull request's original commits keep their own SHAs and
stay in the merged pull request, so both versions pass step 1. A copy is
removed only when all of these hold:

1. it has the same message, author name, author time, and changed files with
   the same per-file line counts as another commit of the set;
2. its patch is byte-identical to that commit's, ignoring only the
   `index <blob>..<blob>` lines (blob ids can differ, the content cannot);
3. among the copies with that identical patch, exactly one is reachable from the
   default branch: that one is kept, and the copies that are not reachable from
   the default branch (present only through a merged pull request) are removed.

Groups where no copy, or more than one copy, is on the default branch are kept
whole: which copy is the original is not clear there, and two copies on the
default branch may be a change genuinely applied twice. Copies whose patch
could not be read are kept.
"""

from collections import defaultdict

from .facts import Commit
from .step import Removal

REASON = "rebased copy of a default-branch commit"


def removals(commits: list[Commit]) -> list[Removal]:
    groups: dict[tuple, list[Commit]] = defaultdict(list)
    for commit in commits:
        if commit.change_signature is not None:
            groups[commit.change_signature].append(commit)
    found = []
    for group in groups.values():
        if len(group) < 2:
            continue
        by_content: dict[str, list[Commit]] = defaultdict(list)
        for commit in group:
            if commit.content_hash is not None:
                by_content[commit.content_hash].append(commit)
        for copies in by_content.values():
            kept = [c for c in copies if c.on_default_branch]
            if len(copies) < 2 or len(kept) != 1:
                continue
            found += [Removal(c.repo, c.sha, REASON, kept[0].sha) for c in copies if not c.on_default_branch]
    return found
