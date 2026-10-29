"""Freeze a new run directory: the repository list and the corpus policy.

The repository list and the policy (search terms and cutoff) come from `config/`.
Each is copied into the run once; a run with a manifest is never prepared again,
so every later stage reads the same frozen inputs. Inside the run the policy is
`tier_policy.json` and the per-repository corpus decisions are `tier_plans/`, the
names the collector uses. The policy file's SHA-256 is recorded in the manifest,
and the corpus search refuses plans made under a different policy.
"""

import hashlib
from pathlib import Path
from typing import Any

from ..common import now, read_json, write_json_atomic
from ..paths import CONFIG_DIRECTORY

RUN_DIRECTORIES = ('tier_plans', 'tier_search_cache', 'mirrors', 'recovery_mirrors', 'logs', 'git_sources')


def is_prepared(run: Path) -> bool:
    return (run / 'manifest.json').exists()


def prepare(run: Path, config: Path = CONFIG_DIRECTORY) -> None:
    """Write `tier_policy.json` and `manifest.json` into a new run directory."""
    if is_prepared(run):
        raise ValueError(f'{run} is already prepared; its frozen inputs are not replaced')
    repositories: list[dict[str, Any]] = read_json(config / 'repositories.json')['repositories']
    names = [entry['repo'].lower() for entry in repositories]
    if len(names) != len(set(names)):
        raise ValueError('config/repositories.json lists a repository twice')
    policy = {**read_json(config / 'corpus_policy.json'), 'created_at': now()}
    run.mkdir(parents=True, exist_ok=True)
    write_json_atomic(run / 'tier_policy.json', policy)
    policy_hash = hashlib.sha256((run / 'tier_policy.json').read_bytes()).hexdigest()
    write_json_atomic(run / 'manifest.json', {
        'schema_version': 2,
        'created_at': now(),
        'sources': [{'path': str((config / name).resolve()),
                     'sha256': hashlib.sha256((config / name).read_bytes()).hexdigest()}
                    for name in ('repositories.json', 'corpus_policy.json')],
        'scope': {'pr_states': 'all', 'issue_states': 'all', 'date_filter': None},
        'tiering': {'policy_sha256': policy_hash},
        'repositories': sorted(repositories, key=lambda entry: entry['repo'].lower()),
    })
    for directory in RUN_DIRECTORIES:
        (run / directory).mkdir(exist_ok=True)
    print(f'Prepared {run}: {len(repositories)} repositories', flush=True)
