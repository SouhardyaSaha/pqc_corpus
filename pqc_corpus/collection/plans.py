"""Per-repository corpus plans written by the TypeScript corpus search.

File names and keys inside a run directory are the format the frozen run was
collected with, which predates the word "corpus", so they keep the word "tier":
the policy is `tier_policy.json`, the plans are in `tier_plans/`, a plan's corpus
is its `tier` key (`unrated` is corpus C), and the manifest records the policy
hash under `tiering`.
"""

from pathlib import Path
from typing import Any

from ..common import lowercase_slug, read_json

POLICY_FILE = 'tier_policy.json'
PLAN_DIRECTORY = 'tier_plans'
SEARCH_CACHE_DIRECTORY = 'tier_search_cache'


def plan_path(run: Path, repo: str) -> Path:
    return run / PLAN_DIRECTORY / (lowercase_slug(repo) + '.json')


def load_plan(run: Path, repo: str) -> dict[str, Any]:
    """Read a plan and refuse it unless it was made under the run's frozen policy."""
    plan = read_json(plan_path(run, repo))
    manifest = read_json(run / 'manifest.json')
    if plan['policy_sha256'] != manifest['tiering']['policy_sha256']:
        raise ValueError('Corpus plan does not match frozen policy')
    return plan
