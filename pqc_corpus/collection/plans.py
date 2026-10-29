"""Per-repository tier plans written by the TypeScript tier search."""

from pathlib import Path
from typing import Any

from ..common import lowercase_slug, read_json


def plan_path(run: Path, repo: str) -> Path:
    return run / 'tier_plans' / (lowercase_slug(repo) + '.json')


def load_plan(run: Path, repo: str) -> dict[str, Any]:
    """Read a plan and refuse it unless it was made under the run's frozen policy."""
    plan = read_json(plan_path(run, repo))
    manifest = read_json(run / 'manifest.json')
    if plan['policy_sha256'] != manifest['tiering']['policy_sha256']:
        raise ValueError('Tier plan does not match frozen policy')
    return plan
