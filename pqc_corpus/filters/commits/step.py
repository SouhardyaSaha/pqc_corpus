"""What a filter step removes: the commit, why, and the copy it duplicates (if any)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Removal:
    repo: str
    sha: str
    reason: str
    kept_sha: str | None = None
