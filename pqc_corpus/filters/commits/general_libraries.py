"""Step 7, general libraries: commits with no PQC term in repositories that are not about PQC.

General cryptography and TLS libraries (libcrux, wolfSSL, Bouncy Castle...) are
mostly classical. A commit is removed only if its repository's name, description
and topics are not PQC-related and no PQC term appears in its message, linked
pull-request and issue text, file paths, or changed lines. PQC-named repositories
(for example a single-scheme library whose commits rarely repeat the scheme name)
are never affected.
"""

from .facts import Commit
from .step import Removal

REASON = "no PQC term, in a repository that is not PQC-named"


def removals(commits: list[Commit]) -> list[Removal]:
    return [
        Removal(c.repo, c.sha, REASON)
        for c in commits
        if not c.in_fork and not c.pqc_named_repository and not c.mentions_pqc
    ]
