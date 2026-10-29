"""Step 8, housekeeping: commits that change only project upkeep and never mention PQC.

A commit is removed when it changes no files, or when its diff contains no PQC
term anywhere and it only touches CI configuration, only lock files, only
repository metadata files, or was made by a bot.
"""

import re

from .facts import Commit
from .step import Removal

CI = re.compile(r"^(\.github/|\.gitlab-ci|\.travis|\.circleci/|appveyor|azure-pipelines|\.cirrus"
                r"|Jenkinsfile|\.buildkite/)", re.IGNORECASE)
LOCK_FILES = re.compile(r"(^|/)(Cargo\.lock|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum"
                        r"|poetry\.lock|Gemfile\.lock|composer\.lock|deno\.lock|uv\.lock|Pipfile\.lock)$")
METADATA = re.compile(r"(^|/)(\.gitignore|\.gitattributes|\.editorconfig|\.DS_Store|\.mailmap|CODEOWNERS"
                      r"|\.pre-commit-config\.yaml|\.clang-format|\.prettierrc[^/]*|\.eslintrc[^/]*"
                      r"|LICENSE[^/]*|COPYING[^/]*|\.dockerignore)$", re.IGNORECASE)
KINDS = (("ci_only", CI), ("lock_files_only", LOCK_FILES), ("repository_metadata_only", METADATA))


def kind(commit: Commit) -> str | None:
    if not commit.paths:
        return "empty"
    if commit.pqc_in_diff:
        return None
    for name, rule in KINDS:
        if all(rule.search(path) for path in commit.paths):
            return name
    return "bot" if commit.is_bot else None


def removals(commits: list[Commit]) -> list[Removal]:
    found = []
    for commit in commits:
        label = kind(commit)
        if label:
            found.append(Removal(commit.repo, commit.sha, f"housekeeping ({label}) with no PQC term in the diff"))
    return found
