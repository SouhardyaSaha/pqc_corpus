#!/usr/bin/env python3
"""Inter-rater agreement and precision of PQC-relevance labels for issues and commits."""
import argparse
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

import openpyxl

RATERS = ('Annotator A', 'Annotator B')
PREFIX = re.compile(rb'\{"repo":("(?:[^"\\]|\\.)*"),"corpus":"([^"]*)","sha":"([0-9a-f]+)"')


def as_bool(value, where):
    text = str(value).strip().lower()
    if text in ('true', '1', 'yes'):
        return True
    if text in ('false', '0', 'no'):
        return False
    raise ValueError(f'{where}: expected TRUE or FALSE, got {value!r}')


def load_issue_labels(path):
    book = openpyxl.load_workbook(path, data_only=True)
    labels, ids = {}, {}
    for sheet in RATERS + ('Adjudicated',):
        rows = book[sheet].iter_rows(values_only=True)
        header = next(rows)
        labels[sheet] = {}
        for row in rows:
            record = dict(zip(header, row))
            if not record['P-ID']:
                continue
            url = record['Issue URL']
            if ids.setdefault(url, record['P-ID']) != record['P-ID']:
                raise ValueError(f'{path}: {sheet} gives {url} a different P-ID')
            labels[sheet][url] = as_bool(record['is_pqc_relevant'], f'{path.name} {sheet} {record["P-ID"]}')
    if len({frozenset(value) for value in labels.values()}) != 1:
        raise ValueError(f'{path}: sheets list different issues')
    return labels, ids


def load_commit_labels(path):
    book = openpyxl.load_workbook(path, data_only=True)
    labels, ids = {}, {}
    for rater in RATERS:
        rows = book[rater].iter_rows(values_only=True)
        header = next(rows)
        labels[rater] = {}
        for row in rows:
            record = dict(zip(header, row))
            if not record['R-ID']:
                continue
            key = (record['Repository'], record['commit_sha'])
            if ids.setdefault(key, record['R-ID']) != record['R-ID']:
                raise ValueError(f'{path}: {rater} gives {key} a different R-ID')
            labels[rater][key] = as_bool(record['is_pqc_related'], f'{path.name} {rater} {record["R-ID"]}')
    if len({frozenset(value) for value in labels.values()}) != 1:
        raise ValueError(f'{path}: annotators labelled different commits')
    return labels, ids


def load_adjudication(path):
    rows = iter(openpyxl.load_workbook(path, data_only=True)['PQC relevance review'].iter_rows(values_only=True))
    for row in rows:
        if row and row[0] == 'R-ID':
            header = [str(value).replace('\n', ' ') if value else value for value in row]
            break
    else:
        raise ValueError(f'{path}: no R-ID header in the review sheet')
    review = {}
    for row in rows:
        if not row or not re.fullmatch(r'R\d+', str(row[0] or '')):
            break
        record = dict(zip(header, row))
        review[record['R-ID']] = {
            'proposed': as_bool(record['Proposed is_pqc_related'], f'{path.name} {record["R-ID"]}'),
            'raters': tuple(as_bool(record[name], f'{path.name} {record["R-ID"]}') for name in 'AB'),
            'status': record['Review status'],
        }
    return review


def commit_corpora(directory, wanted):
    # Read only each line's repo, corpus and sha, so patch-bearing shards stay cheap to scan.
    found, population = {}, Counter()
    for part in sorted(directory.glob('*.jsonl')):
        with part.open('rb') as handle:
            at_start, prefix = True, b''
            while chunk := handle.read(1 << 20):
                position = 0
                while position < len(chunk):
                    if at_start:
                        end = chunk.find(b'\n', position)
                        prefix += chunk[position:len(chunk) if end < 0 else end][:512 - len(prefix)]
                        if len(prefix) >= 512 or end >= 0:
                            match = PREFIX.match(prefix)
                            if not match:
                                raise ValueError(f'{part}: unexpected record prefix')
                            key = (json.loads(match.group(1)), match.group(3).decode())
                            population[match.group(2).decode()] += 1
                            if key in wanted:
                                found[key] = match.group(2).decode()
                            at_start, prefix = False, b''
                        if end < 0:
                            break
                        position = end
                    end = chunk.find(b'\n', position)
                    if end < 0:
                        break
                    position, at_start = end + 1, True
    return found, population


def view_directory(release, name):
    for candidate in (release / name, release / f'{name}_metadata'):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f'No {name}/ or {name}_metadata/ in {release}')


def cohen(pairs):
    n = len(pairs)
    both_yes = sum(a and b for a, b in pairs)
    both_no = sum(not a and not b for a, b in pairs)
    only_a = sum(a and not b for a, b in pairs)
    only_b = sum(b and not a for a, b in pairs)
    observed = (both_yes + both_no) / n
    p_a, p_b = (both_yes + only_a) / n, (both_yes + only_b) / n
    chance = p_a * p_b + (1 - p_a) * (1 - p_b)
    kappa = (observed - chance) / (1 - chance) if chance < 1 else 1.0
    mean = (p_a + p_b) / 2
    ac1_chance = 2 * mean * (1 - mean)
    return {
        'n': n,
        'both_true': both_yes, 'both_false': both_no,
        'only_first_true': only_a, 'only_second_true': only_b,
        'observed_agreement': round(observed, 4),
        'cohen_kappa': round(kappa, 4),
        'pabak': round(2 * observed - 1, 4),
        'gwet_ac1': round((observed - ac1_chance) / (1 - ac1_chance), 4),
        'first_true_rate': round(p_a, 4), 'second_true_rate': round(p_b, 4),
    }


def bootstrap(rows, statistic, key, rounds, seed):
    rng = random.Random(seed)
    values = sorted(statistic([rng.choice(rows) for _ in rows])[key] for _ in range(rounds))
    return [values[int(.025 * rounds)], values[int(.975 * rounds) - 1]]


def wilson(hits, n, z=1.96):
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 4), round(centre + half, 4)]


def proportion(labels):
    hits, n = sum(labels), len(labels)
    return {'n': n, 'true': hits, 'precision': round(hits / n, 4), 'wilson_95ci': wilson(hits, n)}


def weighted(groups, population, z=1.96):
    # Weight each corpus by its share of the view, with finite-population correction.
    total = sum(population[group] for group in groups)
    estimate = variance = 0.0
    for group, labels in groups.items():
        n, share, p = len(labels), population[group] / total, sum(labels) / len(labels)
        estimate += share * p
        variance += share ** 2 * p * (1 - p) / n * (1 - n / population[group])
    half = z * math.sqrt(variance)
    return {'population': {group: population[group] for group in sorted(groups)},
            'precision': round(estimate, 4),
            'normal_95ci': [round(max(0.0, estimate - half), 4), round(min(1.0, estimate + half), 4)]}


def precision_report(labels, corpus, population=None):
    groups = {}
    for key, label in labels.items():
        groups.setdefault(corpus[key], []).append(label)
    report = {'unweighted': proportion(list(labels.values())),
              'by_corpus': {group: proportion(values) for group, values in sorted(groups.items())}}
    if population:
        report['weighted_by_corpus'] = weighted(groups, population)
    return report


def run_issues(args):
    labels, ids = load_issue_labels(args.workbook)
    urls = sorted(ids, key=ids.get)
    pairs = [tuple(labels[rater][url] for rater in RATERS) for url in urls]

    # A and B agreements keep their label; their disagreements take the adjudicated label.
    final, settled = {}, {}
    for url, (a, b) in zip(urls, pairs):
        adjudicated = labels['Adjudicated'][url]
        if a == b and adjudicated != a:
            raise ValueError(f'{ids[url]}: adjudicated label overrides an A-B agreement')
        final[url] = adjudicated
        if a != b:
            settled[ids[url]] = {'url': url, 'A': a, 'B': b, 'label': adjudicated}

    agreement = cohen(pairs)
    agreement['cohen_kappa_95ci_bootstrap'] = bootstrap(pairs, cohen, 'cohen_kappa', args.rounds, args.seed)
    report = {
        'label': 'is_pqc_relevant',
        'raters': list(RATERS),
        'issues': len(urls),
        'bootstrap': {'rounds': args.rounds, 'seed': args.seed},
        'agreement': agreement,
        'adjudicated': settled,
    }
    if args.release:
        with (args.release / 'issues_filtered.jsonl').open(encoding='utf-8') as handle:
            records = [json.loads(line) for line in handle]
        corpus = {record['url']: record['corpus'] for record in records if record['url'] in final}
        if set(corpus) != set(final):
            raise ValueError(f'{len(set(final) - set(corpus))} annotated issues are not in issues_filtered')
        population = Counter(record['corpus'] for record in records)
        report['precision'] = precision_report(final, corpus, population)
    else:
        report['precision'] = proportion(list(final.values()))
    return report


def run_commits(args):
    labels, ids = load_commit_labels(args.workbook)
    review = load_adjudication(args.workbook)
    keys = sorted(ids, key=ids.get)
    pairs = [tuple(labels[rater][key] for rater in RATERS) for key in keys]

    # A and B agreements keep their label; their disagreements take the adjudicated label.
    final, settled = {}, {}
    for key, (a, b) in zip(keys, pairs):
        if a == b:
            final[key] = a
            continue
        entry = review.get(ids[key])
        if entry is None or entry['raters'] != (a, b):
            raise ValueError(f'{ids[key]}: no matching adjudication for an A-B disagreement')
        final[key] = settled[ids[key]] = entry['proposed']

    agreement = cohen(pairs)
    agreement['cohen_kappa_95ci_bootstrap'] = bootstrap(pairs, cohen, 'cohen_kappa', args.rounds, args.seed)
    report = {
        'label': 'is_pqc_related',
        'raters': list(RATERS),
        'commits': len(keys),
        'bootstrap': {'rounds': args.rounds, 'seed': args.seed},
        'agreement': agreement,
        'adjudicated': {rid: {'label': label, 'status': review[rid]['status']} for rid, label in sorted(settled.items())},
    }
    if args.release:
        corpus, population = commit_corpora(view_directory(args.release, 'commits'), set(keys))
        filtered, filtered_population = commit_corpora(view_directory(args.release, 'commits_filtered'), set(keys))
        if set(corpus) != set(keys):
            raise ValueError(f'{len(set(keys) - set(corpus))} annotated commits are not in the commit view')
        report['precision'] = {
            'commits': precision_report(final, corpus, population),
            'commits_filtered': precision_report({key: final[key] for key in filtered}, filtered, filtered_population),
        }
    else:
        report['precision'] = {'commits': proportion(list(final.values()))}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=10000)
    parser.add_argument('--seed', type=int, default=20261103)
    parser.add_argument('--release', type=Path, help='Release or patch-free view; weights precision by corpus')
    commands = parser.add_subparsers(dest='command', required=True)
    issues = commands.add_parser('issues', help='Issue workbook with annotators A and B and their adjudication')
    issues.add_argument('workbook', type=Path)
    issues.add_argument('--output', type=Path, default=Path('issue-agreement.json'))
    commits = commands.add_parser('commits', help='Commit workbook with annotators A and B and their adjudication')
    commits.add_argument('workbook', type=Path)
    commits.add_argument('--output', type=Path, default=Path('commit-agreement.json'))
    args = parser.parse_args()

    report = run_issues(args) if args.command == 'issues' else run_commits(args)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
