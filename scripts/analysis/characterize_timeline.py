#!/usr/bin/env python3
"""Count PRs per year and total the pre-selection GitHub inventories."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--output', type=Path, default=Path('timeline.json'))
args = parser.parse_args()
years, dates, fetched = Counter(), [], []
digest = hashlib.sha256()
with (args.data / 'pull_requests.jsonl').open('rb') as source:
    for line in source:
        digest.update(line)
        row = json.loads(line)
        years[row['created_at'][:4]] += 1
        dates.append(row['created_at'])
        fetched.append(row['fetched_at'])
repos = [json.loads(line) for line in (args.data / 'repositories.jsonl').read_text().splitlines()]
result = {
    'source': 'pull_requests.jsonl', 'sha256': digest.hexdigest(),
    'rows': sum(years.values()), 'created_by_year': dict(sorted(years.items())),
    'latest_created_at': max(dates), 'latest_fetched_at': max(fetched),
    'before_2024_08_13': sum(date < '2024-08-13' for date in dates),
    'on_or_after_2024_08_13': sum(date >= '2024-08-13' for date in dates),
    'repository_metadata_totals': {
        key: sum(row[key] for row in repos)
        for key in ('github_pull_requests', 'github_issues', 'git_commits')
    },
    'interpretation': 'PR creation activity in the selected corpus; 2026 is partial. '
        'Not deployment dates, adoption prevalence, or a causal standardization effect. '
        'Repository inventories and scanned Git histories precede selection; linked '
        'commit recovery and differing observation times prevent a recall interpretation.',
}
args.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
