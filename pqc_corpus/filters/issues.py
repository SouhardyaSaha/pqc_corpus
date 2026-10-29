"""Filter the mined issues: remove issues opened by bot accounts.

GitHub names every GitHub App account with a `[bot]` suffix (dependabot[bot],
github-actions[bot]...), and such issues are automated reports, mirrors of
issues in sister repositories, or policy notices rather than developers
describing a problem. Comments by bots inside human-written issues are kept.
"""

import csv
import json
from pathlib import Path
from typing import Any, Iterator

from ..common import now, write_json_atomic
from ..export import jsonl

REASON = 'opened by a bot account'


def is_bot_issue(issue: dict[str, Any]) -> bool:
    return (issue['author'] or '').endswith('[bot]')


def filter_issues(issues: Path, output: Path, report: Path) -> dict[str, Any]:
    """Copy the kept issue lines unchanged to `output`; list removals in the new `report` directory."""
    if report.exists():
        raise ValueError(f'{report} exists; choose a new report directory')
    report.mkdir(parents=True)
    counts = {'mined': 0}
    with (report / '01_bot_issues.csv').open('x', newline='') as removed:
        writer = csv.writer(removed)
        writer.writerow(['repo', 'number', 'author', 'url', 'reason'])

        def kept() -> Iterator[str]:
            for line in jsonl.lines(issues):
                issue = json.loads(line)
                counts['mined'] += 1
                if is_bot_issue(issue):
                    writer.writerow([issue['repo'], issue['number'], issue['author'], issue['url'], REASON])
                else:
                    yield line

        written = jsonl.write_lines(output, kept(), filtered_from=issues.name)
    mined = counts['mined']
    summary = {
        'created_at': now(), 'inputs': {'issues': jsonl.identity(issues)}, 'mined': mined,
        'steps': [{'step': 1, 'name': 'bot_issues', 'removed': mined - written, 'remaining': written,
                   'file': '01_bot_issues.csv'}],
        'filtered': written, 'output': jsonl.identity(output),
    }
    write_json_atomic(report / 'summary.json', summary)
    return summary
