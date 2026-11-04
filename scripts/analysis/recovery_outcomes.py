#!/usr/bin/env python3
"""Count PR commit lists that exceed GitHub's 250-commit cap and were rebuilt from Git."""
import argparse
import json
from pathlib import Path

CAP = 250

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True, help='Full release or patch-free view')
parser.add_argument('--output', type=Path, default=Path('recovery-outcomes.json'))
args = parser.parse_args()

links, at_cap, recovered = 0, [], []
with (args.data / 'pull_requests.jsonl').open(encoding='utf-8') as handle:
    for line in handle:
        pull = json.loads(line)
        count = len(pull['commit_shas'])
        links += count
        # The API never returns more than the cap, so a longer list was rebuilt from Git.
        if count > CAP:
            recovered.append({'repo': pull['repo'], 'number': pull['number'], 'commits': count})
        elif count == CAP:
            at_cap.append({'repo': pull['repo'], 'number': pull['number']})

beyond = sum(item['commits'] - CAP for item in recovered)
report = {
    'cap': CAP,
    'pr_commit_links': links,
    'recovered_prs': len(recovered),
    'recovered_repositories': sorted({item['repo'] for item in recovered}),
    'links_in_recovered_prs': sum(item['commits'] for item in recovered),
    'links_beyond_cap': beyond,
    'links_beyond_cap_share': round(beyond / links, 4),
    # A list left capped would hold exactly 250 commits.
    'prs_at_cap': at_cap,
    'recovered': sorted(recovered, key=lambda item: -item['commits']),
}
args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in report.items() if key != 'recovered'}, indent=2))
