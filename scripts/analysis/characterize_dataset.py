#!/usr/bin/env python3
"""Summarize repositories, views, and linked paths from an audit report."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audit', type=Path, required=True,
                    help='Completed audit JSON produced by audit_dataset.py')
parser.add_argument('--data', type=Path, required=True,
                    help='Dataset checkout containing repositories.jsonl')
parser.add_argument('--output', type=Path, default=Path('characterization.json'),
                    help='Output JSON (default: characterization.json)')
args = parser.parse_args()
AUDIT = args.audit.resolve()
REPOSITORIES = (args.data / 'repositories.jsonl').resolve()
OUTPUT = args.output.resolve()
audit = json.loads(AUDIT.read_text())
repos = [json.loads(line) for line in REPOSITORIES.read_text().splitlines()]
names = sorted(row['repo'] for row in repos)
tables = ['commits', 'commits_filtered', 'pull_requests', 'issues', 'issues_filtered']


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'percent': 100 * numerator / denominator if denominator else None}


def quantile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def distribution(values):
    q1, median, q3 = [quantile(values, p) for p in [.25, .5, .75]]
    return {'repositories': len(values), 'sum': sum(values), 'min': min(values),
            'q1': q1, 'median': median, 'q3': q3, 'iqr_width': q3 - q1, 'max': max(values)}


result = {
    'created_at_utc': datetime.now(timezone.utc).isoformat(),
    'snapshot_commit': audit['snapshot_commit'],
    'inputs': {str(p): {'bytes': p.stat().st_size,
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in [AUDIT, REPOSITORIES]},
    'method': {
        'data_access': 'Existing completed audit JSON plus 179-row repositories.jsonl only; no artifact rescan.',
        'primary_per_repository_denominator': 'All 179 repository records, including zero selected rows.',
        'secondary_per_repository_denominator': 'Only repositories represented by at least one row in the specified table.',
        'quartiles': 'Linear interpolation at (n-1)*p in the sorted counts; Hyndman-Fan type 7.',
        'concentration': 'Sum of counts in the top k repositories for each table independently, divided by all rows of that table; ties ordered by repository name.',
        'language': 'Repository metadata primary language, one label per repository; not changed-file language.',
        'empty_body': 'Exact empty string; disjoint from JSON null. Whitespace-only strings not tested.',
        'triple': 'Distinct (PR repository, PR number, commit SHA, issue repository, issue number), all endpoints present. Triples can share issues, PRs and commits.',
    },
    'per_repository_sizes': {}, 'representation_by_corpus': {}, 'retention': {},
    'body_availability': {}, 'discussion_coverage': {},
}

for table in tables:
    data = audit['datasets'][table]
    counts = data['rows_per_repo']
    all_counts = [counts.get(name, 0) for name in names]
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    assert sum(all_counts) == data['counts']['rows']
    result['per_repository_sizes'][table] = {
        'all_selected_repositories': distribution(all_counts),
        'represented_repositories': distribution(list(counts.values())),
        'zero_row_repositories': len(names) - len(counts),
        'top_concentration': {
            str(k): {**ratio(sum(n for _, n in ranked[:k]), sum(all_counts)),
                     'repositories': [{'repo': name, 'rows': n} for name, n in ranked[:k]]}
            for k in [1, 5, 10]},
    }

for corpus in 'ABC':
    selected = {r['repo'] for r in repos if r['corpus'] == corpus}
    result['representation_by_corpus'][corpus] = {'selected_repositories': len(selected), 'tables': {}}
    for table in tables:
        counts = audit['datasets'][table]['rows_per_repo']
        rows = sum(counts.get(name, 0) for name in selected)
        assert rows == audit['datasets'][table]['corpora'].get(corpus, 0)
        result['representation_by_corpus'][corpus]['tables'][table] = {
            'rows': rows, 'represented_repositories': len(selected.intersection(counts)),
            'coverage': ratio(len(selected.intersection(counts)), len(selected)),
        }

for full, filtered in [('commits', 'commits_filtered'), ('issues', 'issues_filtered')]:
    result['retention'][full] = {
        'rows': ratio(audit['datasets'][filtered]['counts']['rows'], audit['datasets'][full]['counts']['rows']),
        'represented_repositories': ratio(audit['datasets'][filtered]['distinct_repositories'],
                                         audit['datasets'][full]['distinct_repositories']),
        'by_corpus': {c: ratio(audit['datasets'][filtered]['corpora'].get(c, 0),
                               audit['datasets'][full]['corpora'].get(c, 0)) for c in 'ABC'},
    }
links = audit['links']
for label, retained, full in [
    ('pr_commit_edges', 'pr_commit_edges_retained_with_filtered_commits', 'distinct_pr_commit_edges'),
    ('issue_pr_commit_triples', 'fully_linked_issue_pr_commit_triples_filtered', 'fully_linked_issue_pr_commit_triples_full'),
    ('closed_issue_merged_pr_commit_triples', 'fully_linked_closed_issue_merged_pr_commit_triples_filtered',
     'fully_linked_closed_issue_merged_pr_commit_triples_full'),
    ('distinct_issues_in_triples', 'distinct_issues_in_filtered_triples', 'distinct_issues_in_full_triples'),
    ('distinct_prs_in_triples', 'distinct_prs_in_filtered_triples', 'distinct_prs_in_full_triples'),
    ('distinct_commits_in_triples', 'distinct_commits_in_filtered_triples', 'distinct_commits_in_full_triples'),
]:
    result['retention'][label] = ratio(links[retained], links[full])

for table in ['issues', 'pull_requests']:
    data = audit['datasets'][table]
    n = data['counts']['rows']
    null = data['nulls'].get('body', 0)
    empty = data['empty_values'].get('body', 0)
    result['body_availability'][table] = {
        'null': ratio(null, n), 'empty_string': ratio(empty, n),
        'null_or_empty': ratio(null + empty, n),
        'non_null_nonempty_string': ratio(n - null - empty, n),
    }
    for kind in ['comments'] + (['reviews', 'review_comments'] if table == 'pull_requests' else []):
        result['discussion_coverage'][table + ':' + kind] = {
            'records_with_events': ratio(data['counts']['rows_with_' + kind], n),
            'empty_event_arrays': ratio(data['empty_values'].get(kind, 0), n),
            'events_total': data['counts'][kind + '_total'],
            'null_event_authors': ratio(data['counts'][kind + '_null_authors'], data['counts'][kind + '_total']),
        }

languages = Counter(r['language'] for r in repos)
result['primary_languages'] = {
    'repositories': len(repos), 'distinct_non_null_labels': len([x for x in languages if x is not None]),
    'null_labels': languages.get(None, 0),
    'counts': dict(sorted(languages.items(), key=lambda pair: (-pair[1], str(pair[0])))),
}
result['recommended_compact_table'] = [
    {'table': t, 'rows': audit['datasets'][t]['counts']['rows'],
     'represented_repositories': audit['datasets'][t]['distinct_repositories'],
     'denominator_repositories': len(names),
     **{k: result['per_repository_sizes'][t]['all_selected_repositories'][k] for k in ['median', 'q1', 'q3', 'max']},
     'top_five_share_percent': result['per_repository_sizes'][t]['top_concentration']['5']['percent']}
    for t in ['commits', 'commits_filtered', 'pull_requests', 'issues']]
result['recommended_facts'] = [
    'Per-repository size is skewed: among all 179 repositories, full commits median 69 [Q1=15,Q3=282]; the top 5 repositories supply 51.05% of full commits. Use repository-aware sampling/evaluation; these are selected-record counts, not adoption rates.',
    'Filtered view retains 41.74% of commits but 61.33% of complete issue-PR-commit triples (6183/10081), and 45.19% of PR-commit edges. Pick the view according to whether complete linkage or curation is required.',
    'Full linkage has 10,081 triples but only 1,771 distinct PRs, 1,865 issues and 7,637 commits. Treat overlapping triples as dependent examples when constructing trace/retrieval evaluations.',
    'Recorded discussion is uneven: 7,302/11,919 PRs have formal reviews, 2,767/11,919 inline comments, and 6,636/11,919 general comments. Missing event arrays describe the snapshot, not proven collection failure.',
    'Body-based tasks should account for null-or-empty bodies: 566/5,713 issues and 1,552/11,919 PRs. Primary-language metadata has 29 non-null labels across 179 repositories; no per-file language claim follows.',
]
result['interpretation_limits'] = [
    'Corpus inclusion rules differ; these descriptive statistics do not establish adoption prevalence, trends or group effects.',
    'Full and filtered configurations overlap; do not pool them as independent rows.',
    'Absent review arrays and bodies are recorded availability, not externally verified missing collection.',
    'No statistics were computed about null review bodies or substantive review quality; the existing audit did not count those fields.',
]
OUTPUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'output': str(OUTPUT), 'table': result['recommended_compact_table'],
                  'retention': result['retention']}, indent=2))
