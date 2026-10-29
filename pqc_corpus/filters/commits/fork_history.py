"""Step 6, fork history: commits a fork inherited from its upstream project, with no PQC term.

A fork carries its upstream's whole history. In PQC-Corpus the only fork is
open-quantum-safe/openssh, whose history is mostly OpenSSH development since
1999. A fork's commit is removed only if no PQC term (see `terms`) appears in
its message, linked pull-request and issue text, file paths, or changed lines,
so the fork's own PQC work and upstream PQC work (e.g. sntrup761x25519,
mlkem768x25519) stay.
"""

from .facts import Commit
from .step import Removal

REASON = "fork history with no PQC term in text, paths or changed lines"


def removals(commits: list[Commit]) -> list[Removal]:
    return [Removal(c.repo, c.sha, REASON) for c in commits if c.in_fork and not c.mentions_pqc]
