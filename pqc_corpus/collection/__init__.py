"""Collect a run (see docs/COLLECTION.md).

Modules:
    prepare           freeze a new run directory from config/
    pipeline          per repository: corpus search, GitHub API, Git source, commit selection
    git_history       clone and freeze a mirror; mine every commit's metadata (PyDriller)
    plans             read the corpus plans written by the corpus search
    commit_selection  select a repository's commits for its corpus
    linked_commits    read pull-request commits that are missing from the frozen mirror
    eligibility       observe on_default_branch and in_merged_pr for every selected commit
    github_client     GraphQL access for the eligibility stage
"""
