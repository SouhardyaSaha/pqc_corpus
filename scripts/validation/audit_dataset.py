#!/usr/bin/env python3
"""Audit a release offline: hashes, schemas, keys, links, and removal ledgers."""
import argparse
import base64
import collections
import codecs
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import time


class PatchString:
    """Validate/decode one JSON string incrementally; retain only a short excerpt."""
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.pending = ''
        self.characters = 0
        self.excerpt = ''
        self.base64_valid = True
        self.base64_pending = ''
        self.base64_finished = False

    def feed(self, raw, final=False):
        text = self.pending + self.decoder.decode(raw, final=final)
        cut = len(text) if final else max(0, len(text) - 12)
        if not final:
            slash = text.rfind('\\', 0, cut)
            if slash >= 0:
                start = slash
                while start > 0 and text[start - 1] == '\\':
                    start -= 1
                if (slash - start + 1) % 2 == 1:
                    end = slash + (6 if text[slash + 1:slash + 2] == 'u' else 2)
                    if end > cut:
                        cut = slash
            surrogate = re.search(r'\\u[dD][89aAbB][0-9a-fA-F]{2}$', text[:cut])
            if surrogate:
                start = surrogate.start()
                run = start
                while run > 0 and text[run - 1] == '\\':
                    run -= 1
                if (start - run + 1) % 2 == 1:
                    cut = start
        part, self.pending = text[:cut], text[cut:]
        decoded = json.loads('"' + part + '"')
        self.characters += len(decoded)
        self.excerpt += decoded[:max(0, 10000 - len(self.excerpt))]
        if self.base64_valid:
            b = self.base64_pending + decoded
            take = len(b) if final else len(b) // 4 * 4
            current, self.base64_pending = b[:take], b[take:]
            try:
                if self.base64_finished and current:
                    raise ValueError('Content after padding')
                base64.b64decode(current, validate=True)
                self.base64_finished = self.base64_finished or '=' in current
            except ValueError:
                self.base64_valid = False
        if final and self.pending:
            raise ValueError('Incomplete patch string')


def records(path, project_patch, file_digest):
    """Parse every record, decoding patch strings in bounded pieces."""
    if not project_patch:
        with path.open('rb') as source:
            for raw in source:
                file_digest.update(raw)
                yield json.loads(raw), len(raw), hashlib.sha256(raw).hexdigest(), None, False
        return
    marker = b',"patch_content":"'
    closing_quote = re.compile(rb'(?<!\\)(?:\\\\)*"')
    prefix = suffix = pending = b''
    phase, patch, record_size, record_digest = 'prefix', None, 0, hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            file_digest.update(chunk)
            parts = chunk.split(b'\n')
            for i, piece in enumerate(parts):
                ended = i < len(parts) - 1
                if not piece and not ended:
                    continue
                record_digest.update(piece)
                record_size += len(piece)
                if ended:
                    record_digest.update(b'\n')
                    record_size += 1
                if phase == 'prefix':
                    prefix += piece
                    at = prefix.find(marker)
                    if at >= 0:
                        piece = prefix[at + len(marker):]
                        prefix = prefix[:at] + b',"patch_content":""'
                        patch, phase = PatchString(), 'patch'
                    else:
                        piece = b''
                if phase == 'patch':
                    data = pending + piece
                    match = closing_quote.search(data)
                    if match:
                        at = match.end() - 1
                        patch.feed(data[:at], final=True)
                        suffix = data[at + 1:]
                        pending, phase = b'', 'suffix'
                    else:
                        cut = max(0, len(data) - 16)
                        while cut > 0 and data[cut - 1] == 92:
                            cut -= 1
                        patch.feed(data[:cut])
                        pending = data[cut:]
                elif phase == 'suffix':
                    suffix += piece
                if ended:
                    if phase == 'patch':
                        raise ValueError('Unclosed patch string: ' + str(path))
                    row = json.loads(prefix + suffix)
                    if patch is not None:
                        row['patch_content'] = patch.excerpt
                    yield row, record_size, record_digest.hexdigest(), patch.characters if patch else None, not patch.base64_valid if patch else False
                    prefix = suffix = pending = b''
                    phase, patch, record_size, record_digest = 'prefix', None, 0, hashlib.sha256()
    if record_size:
        raise ValueError('Missing final newline: ' + str(path))


def validate(value, schema, errors, path='$'):
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    actual = ('null' if value is None else 'boolean' if isinstance(value, bool)
              else 'integer' if isinstance(value, int) else 'number' if isinstance(value, float)
              else 'string' if isinstance(value, str) else 'array' if isinstance(value, list)
              else 'object' if isinstance(value, dict) else 'unknown')
    number_matches = (actual == 'integer' and 'number' in types) or (
        actual == 'number' and 'integer' in types and value.is_integer())
    if types and actual not in types and not number_matches:
        errors[path + ':type'] += 1
        return
    if 'enum' in schema and value not in schema['enum']:
        errors[path + ':enum'] += 1
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errors[path + '.' + key + ':missing'] += 1
        for key, item in value.items():
            if key in schema.get('properties', {}):
                validate(item, schema['properties'][key], errors, path + '.' + key)
            elif schema.get('additionalProperties') is False:
                errors[path + '.' + key + ':additional'] += 1
    elif isinstance(value, list) and 'items' in schema:
        for item in value:
            validate(item, schema['items'], errors, path + '[]')


def dist(values):
    if not values:
        return {}
    s = sorted(values)
    return {'n': len(s), 'min': s[0], 'median': statistics.median(s),
            'p95_nearest_rank': s[max(0, (95 * len(s) + 99) // 100 - 1)], 'max': s[-1], 'sum': sum(s)}


def normtime(value):
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(datetime.timezone.utc).isoformat()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def run(root, output, wait_for_files=False):
    manifest = json.loads((root / 'manifest.json').read_text())
    audit = {'snapshot_commit': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
             'audit_started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'dataset_path': str(root.resolve()), 'manifest_created_at': manifest['created_at'],
             'method': 'Exhaustive JSON parsing, published-schema keyword validation, checksums, keys, links and subset comparison; no live GitHub validation or semantic relevance adjudication.',
             'schema_validation_keywords': ['type', 'required', 'properties', 'additionalProperties', 'items', 'enum'],
             'datasets': {}, 'files': {}}
    indexes = {}
    repos = {}
    pr_commits, commit_prs = set(), set()
    pr_issues, issue_prs = set(), set()
    filtered_commits, filtered_issues = set(), set()
    pr_info, issue_info = {}, {}
    showcase_commits = []
    sample_targets = {('RustCrypto/KEMs', 47)}
    duplicate_shas = collections.Counter()
    full_urls = collections.Counter()
    commit_observations = {}
    order = ['repositories', 'issues', 'issues_filtered', 'pull_requests', 'commits', 'commits_filtered']
    for name in order:
        dset = manifest['datasets'][name]
        base = name.removesuffix('_filtered')
        schema = json.loads((root / 'schemas' / (base + '.schema.json')).read_text())
        counts = collections.Counter()
        corpora, by_repo, nulls, empty, enums = (collections.Counter() for _ in range(5))
        schema_errors, date_errors = collections.Counter(), collections.Counter()
        dates, sizes, field_names = {}, collections.defaultdict(list), collections.Counter()
        index = {}
        urls = collections.Counter()
        noncanonical_urls = []
        largest_record = None
        file_bounds = {}
        file_order = sorted(dset['files'], key=lambda f: (
            not ((root / f['path']).is_file() and (root / f['path']).stat().st_size == f['bytes']), f['path'])) if wait_for_files else dset['files']
        for meta in file_order:
            path = root / meta['path']
            digest, nrows, nbytes = hashlib.sha256(), 0, 0
            if wait_for_files and (not path.is_file() or path.stat().st_size != meta['bytes']):
                print('Waiting for complete release file ' + str(path), flush=True)
                while not path.is_file() or path.stat().st_size != meta['bytes']:
                    time.sleep(5)
            if not path.is_file() or path.stat().st_size != meta['bytes']:
                raise ValueError('Missing or incompletely hydrated release file: ' + str(path))
            print('Reading ' + str(path), flush=True)
            first_key = last_key = None
            if path.is_file():
                for row, raw_size, record_hash, patch_chars, invalid_base64 in records(path, base == 'commits', digest):
                    nbytes += raw_size
                    nrows += 1
                    validate(row, schema, schema_errors)
                    counts['rows'] += 1
                    key = (row['repo'], row.get('sha', row.get('number', '')))
                    if first_key is None:
                        first_key = key
                    if largest_record is None or raw_size > largest_record['json_line_bytes']:
                        largest_record = {'key': key, 'file': meta['path'], 'line': nrows,
                                          'json_line_bytes': raw_size, 'patch_characters': patch_chars}
                    if key in index:
                        counts['duplicate_primary_keys'] += 1
                    if last_key is not None and key < last_key:
                        counts['out_of_order_rows'] += 1
                    last_key = key
                    index[key] = record_hash
                    urls[row['url']] += 1
                    segment = {'commits': '/commit/', 'issues': '/issues/', 'pull_requests': '/pull/', 'repositories': ''}[base]
                    expected_url = 'https://github.com/' + row['repo'] + segment + str(row.get('sha', row.get('number', '')))
                    if row['url'] != expected_url:
                        counts['urls_different_from_repo_and_record_key'] += 1
                        if len(noncanonical_urls) < 20:
                            noncanonical_urls.append({'key': key, 'actual_url': row['url'], 'constructed_url': expected_url})
                    if name in ['issues', 'pull_requests', 'commits']:
                        full_urls[row['url']] += 1
                    corpora[row['corpus']] += 1
                    by_repo[row['repo']] += 1
                    for field, value in row.items():
                        field_names[field] += 1
                        if value is None:
                            nulls[field] += 1
                        if (value == '' or value == []) and (field != 'patch_content' or not patch_chars):
                            empty[field] += 1
                        if field.endswith('_at') and value:
                            try:
                                timestamp = normtime(value)
                                if field not in dates:
                                    dates[field] = {'min': timestamp, 'max': timestamp}
                                dates[field]['min'] = min(dates[field]['min'], timestamp)
                                dates[field]['max'] = max(dates[field]['max'], timestamp)
                            except (ValueError, TypeError):
                                date_errors[field] += 1
                    if name != 'repositories':
                        if row['repo'] not in repos:
                            counts['missing_repository'] += 1
                        elif repos[row['repo']]['corpus'] != row['corpus']:
                            counts['repository_corpus_mismatch'] += 1
                    if base == 'repositories':
                        repos[row['repo']] = row
                        enums['language:' + str(row['language'])] += 1
                        enums['is_fork:' + str(row['is_fork'])] += 1
                        for field in ['stars', 'forks', 'git_commits', 'github_issues', 'github_pull_requests']:
                            if row[field] is not None:
                                sizes[field].append(row[field])
                    elif base in ['issues', 'pull_requests']:
                        enums['state:' + row['state']] += 1
                        for field in ['comments', 'reviews', 'review_comments', 'commit_shas', 'closes_issues', 'closed_by_prs']:
                            if field not in row:
                                continue
                            values = row[field]
                            counts[field + '_total'] += len(values)
                            counts['rows_with_' + field] += bool(values)
                            sizes[field].append(len(values))
                            if field in ['comments', 'reviews', 'review_comments']:
                                timefield = 'submitted_at' if field == 'reviews' else 'created_at'
                                times = [normtime(x[timefield]) for x in values if x[timefield]]
                                counts[field + '_out_of_order_records'] += times != sorted(times)
                                counts[field + '_null_authors'] += sum(x['author'] is None for x in values)
                        if name == 'issues':
                            issue_info[key] = row
                            for pr in row['closed_by_prs']:
                                issue_prs.add((pr['repo'], pr['number'], row['repo'], row['number']))
                        elif name == 'issues_filtered':
                            filtered_issues.add(key)
                        elif name == 'pull_requests':
                            pr_info[key] = row
                            enums['merged:' + str(row['merged'])] += 1
                            counts['duplicate_commit_shas_in_pr_arrays'] += len(row['commit_shas']) - len(set(row['commit_shas']))
                            for sha in row['commit_shas']:
                                pr_commits.add((row['repo'], row['number'], sha))
                            for issue in row['closes_issues']:
                                pr_issues.add((row['repo'], row['number'], issue['repo'], issue['number']))
                            if row['repo'] in ['open-quantum-safe/liboqs', 'open-quantum-safe/oqs-provider'] and row['merged'] and row['closes_issues'] and 1 <= len(row['commit_shas']) <= 10 and row['reviews']:
                                sample_targets.add(key)
                    elif base == 'commits':
                        for field in ['on_default_branch', 'in_merged_pr', 'pqc_in_linked_text', 'patch_encoding']:
                            enums[field + ':' + str(row[field])] += 1
                        counts['rows_with_pr_numbers'] += bool(row['pr_numbers'])
                        counts['pr_numbers_total'] += len(row['pr_numbers'])
                        counts['duplicate_pr_numbers_in_commit_arrays'] += len(row['pr_numbers']) - len(set(row['pr_numbers']))
                        counts['merge_commits'] += len(row['parents']) > 1
                        counts['root_commits'] += len(row['parents']) == 0
                        counts['empty_patches'] += not patch_chars
                        counts['rows_with_binary_changes'] += any(x['binary'] for x in row['changed_files'])
                        counts['changed_files_total'] += len(row['changed_files'])
                        counts['binary_files_total'] += sum(x['binary'] for x in row['changed_files'])
                        counts['line_added_total_mismatches'] += sum(x['additions'] or 0 for x in row['changed_files']) != row['lines_added']
                        counts['line_deleted_total_mismatches'] += sum(x['deletions'] or 0 for x in row['changed_files']) != row['lines_deleted']
                        counts['pr_urls_mismatch'] += row['pr_urls'] != ['https://github.com/' + row['repo'] + '/pull/' + str(n) for n in row['pr_numbers']]
                        counts['unobserved_pqc_flag_despite_eligibility'] += row['pqc_in_linked_text'] is None and (row['on_default_branch'] or row['in_merged_pr'])
                        sizes['patch_characters'].append(patch_chars)
                        sizes['json_line_bytes'].append(raw_size)
                        sizes['changed_files'].append(len(row['changed_files']))
                        sizes['lines_added'].append(row['lines_added'])
                        sizes['lines_deleted'].append(row['lines_deleted'])
                        if row['patch_encoding'] == 'base64':
                            counts['invalid_base64_patches'] += invalid_base64
                        if name == 'commits':
                            duplicate_shas[row['sha']] += 1
                            commit_observations[key] = {f: row[f] for f in ['on_default_branch', 'in_merged_pr', 'pqc_in_linked_text']}
                            for n in row['pr_numbers']:
                                commit_prs.add((row['repo'], n, row['sha']))
                            if any((row['repo'], n) in sample_targets for n in row['pr_numbers']):
                                sample = {k: v for k, v in row.items() if k != 'patch_content'}
                                sample['patch_excerpt'] = row['patch_content'][:10000]
                                sample['patch_characters'] = patch_chars
                                showcase_commits.append(sample)
                        else:
                            filtered_commits.add(key)
                    if name.endswith('_filtered'):
                        if key not in indexes[base]:
                            counts['not_in_full_set'] += 1
                        elif index[key] != indexes[base][key]:
                            counts['different_raw_record_from_full_set'] += 1
            audit['files'][meta['path']] = {'rows': nrows, 'bytes': nbytes, 'sha256': digest.hexdigest(),
                                             'matches_manifest_rows': nrows == meta['rows'],
                                             'matches_manifest_bytes': nbytes == meta['bytes'],
                                             'matches_manifest_sha256': digest.hexdigest() == meta['sha256']}
            file_bounds[meta['path']] = (first_key, last_key)
            save(output, audit)
        previous_last = None
        for path in sorted(file_bounds):
            first_key, last_key = file_bounds[path]
            if previous_last is not None and first_key is not None and first_key < previous_last:
                counts['out_of_order_rows'] += 1
            if last_key is not None:
                previous_last = last_key
        indexes[name] = index
        audit['datasets'][name] = {'counts': dict(counts), 'corpora': dict(corpora), 'rows_per_repo': dict(by_repo),
                                   'nulls': dict(nulls), 'empty_values': dict(empty), 'enums': dict(enums),
                                   'schema_errors': dict(schema_errors), 'date_errors': dict(date_errors),
                                   'date_ranges_utc': dates, 'distributions': {k: dist(v) for k, v in sizes.items()},
                                   'field_presence': dict(field_names), 'distinct_repositories': len(by_repo)}
        audit['datasets'][name]['distinct_urls'] = len(urls)
        audit['datasets'][name]['duplicate_url_examples'] = [(u, n) for u, n in urls.items() if n > 1][:20]
        audit['datasets'][name]['urls_different_from_repo_and_record_key_examples'] = noncanonical_urls
        audit['datasets'][name]['largest_record'] = largest_record
        save(output, audit)
    commits, issues, prs = indexes['commits'], indexes['issues'], indexes['pull_requests']
    linked_pi = {e for e in pr_issues if (e[2], e[3]) in issues}
    linked_ip = {e for e in issue_prs if (e[0], e[1]) in prs}
    pc_by_pr = collections.defaultdict(set)
    for repo, number, sha in pr_commits:
        if (repo, sha) in commits:
            pc_by_pr[(repo, number)].add(sha)
    full_triples = {(prrepo, num, sha, irepo, inum) for prrepo, num, irepo, inum in linked_pi
                    for sha in pc_by_pr[(prrepo, num)]}
    kept_triples = {t for t in full_triples if (t[0], t[2]) in filtered_commits and (t[3], t[4]) in filtered_issues}
    closed_merged_triples = {t for t in full_triples if pr_info[t[:2]]['merged'] and
                             issue_info[(t[3], t[4])]['state'] == 'closed'}
    audit['links'] = {
        'distinct_pr_commit_edges': len(pr_commits), 'distinct_commit_pr_edges': len(commit_prs),
        'pr_commit_edges_missing_commit': len({e for e in pr_commits if (e[0], e[2]) not in commits}),
        'commit_pr_edges_missing_pr': len({e for e in commit_prs if (e[0], e[1]) not in prs}),
        'pr_commit_not_reciprocated': len(pr_commits - commit_prs), 'commit_pr_not_reciprocated': len(commit_prs - pr_commits),
        'distinct_pr_issue_edges': len(pr_issues), 'distinct_issue_pr_edges': len(issue_prs),
        'pr_issue_edges_with_issue_present': len(linked_pi), 'pr_issue_edges_with_issue_absent': len(pr_issues - linked_pi),
        'issue_pr_edges_with_pr_present': len(linked_ip), 'issue_pr_edges_with_pr_absent': len(issue_prs - linked_ip),
        'pr_issue_edges_cross_repository': sum(e[0] != e[2] for e in pr_issues),
        'issue_pr_edges_cross_repository': sum(e[0] != e[2] for e in issue_prs),
        'in_dataset_pr_issue_not_reciprocated': len(linked_pi - issue_prs),
        'in_dataset_issue_pr_not_reciprocated': len(linked_ip - pr_issues),
        'pr_issue_edges_with_issue_absent_examples': sorted(pr_issues - linked_pi)[:20],
        'issue_pr_edges_with_pr_absent_examples': sorted(issue_prs - linked_ip)[:20],
        'issue_pr_number_collisions_same_repo': len(set(issues) & set(prs)),
        'unique_commit_shas': len(duplicate_shas), 'shas_in_multiple_repositories': sum(n > 1 for n in duplicate_shas.values()),
        'fully_linked_issue_pr_commit_triples_full': len(full_triples),
        'fully_linked_issue_pr_commit_triples_filtered': len(kept_triples),
        'fully_linked_closed_issue_merged_pr_commit_triples_full': len(closed_merged_triples),
        'fully_linked_closed_issue_merged_pr_commit_triples_filtered': len(closed_merged_triples & kept_triples),
        'distinct_issues_in_full_triples': len({(t[3], t[4]) for t in full_triples}),
        'distinct_prs_in_full_triples': len({t[:2] for t in full_triples}),
        'distinct_commits_in_full_triples': len({(t[0], t[2]) for t in full_triples}),
        'distinct_issues_in_filtered_triples': len({(t[3], t[4]) for t in kept_triples}),
        'distinct_prs_in_filtered_triples': len({t[:2] for t in kept_triples}),
        'distinct_commits_in_filtered_triples': len({(t[0], t[2]) for t in kept_triples}),
        'pr_commit_edges_retained_with_filtered_commits': sum((e[0], e[2]) in filtered_commits for e in pr_commits)}
    audit['links']['distinct_full_artifact_urls'] = len(full_urls)
    audit['repository_count_comparison'] = []
    for repo, metadata in repos.items():
        if metadata['corpus'] != 'A':
            continue
        for name, field in [('issues', 'github_issues'), ('pull_requests', 'github_pull_requests')]:
            observed = audit['datasets'][name]['rows_per_repo'].get(repo, 0)
            if metadata[field] != observed:
                audit['repository_count_comparison'].append({'repo': repo, 'table': name,
                                                             'classification_time_metadata_count': metadata[field],
                                                             'collected_rows': observed})
    reports = {}
    for base in ['commits', 'issues']:
        report_dir = root / (base + '_filtered_report')
        summary = json.loads((report_dir / 'summary.json').read_text())
        removed, report_counts = set(), []
        for step in summary['steps']:
            with (report_dir / step['file']).open(newline='') as f:
                rows = list(csv.DictReader(f))
            keys = {(r['repo'], r['sha'] if base == 'commits' else int(r['number'])) for r in rows}
            report_counts.append({'name': step['name'], 'actual_rows': len(rows), 'reported_rows': step['removed'],
                                  'unique_keys': len(keys), 'previously_removed_keys': len(keys & removed),
                                  'keys_not_in_full_set': len(keys - indexes[base].keys())})
            removed |= keys
        difference = indexes[base].keys() - indexes[base + '_filtered'].keys()
        reports[base] = {'steps': report_counts, 'unique_removed_keys': len(removed),
                         'reported_removals_equal_actual_full_minus_filtered': removed == difference}
    audit['filter_reports'] = reports
    checksum_failures, checksum_n = [], 0
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest_expected, filename = line.split(None, 1)
        filename = filename.lstrip('* ')
        if filename in audit['files']:
            digest_actual = audit['files'][filename]['sha256']
        else:
            h = hashlib.sha256()
            with (root / filename).open('rb') as f:
                for buf in iter(lambda: f.read(4 * 1024 * 1024), b''):
                    h.update(buf)
            digest_actual = h.hexdigest()
        checksum_n += 1
        if digest_actual != digest_expected:
            checksum_failures.append(filename)
    audit['sha256sums'] = {'files_checked': checksum_n, 'failures': checksum_failures}
    observations = collections.Counter()
    observation_keys = set()
    with (root / 'provenance/frozen_observations_2026-09-29.jsonl').open() as f:
        for raw in f:
            row = json.loads(raw)
            observations['rows'] += 1
            for k, v in row.items():
                if isinstance(v, bool) or v is None:
                    observations[k + ':' + str(v)] += 1
            if 'repo' in row and 'sha' in row:
                key = (row['repo'], row['sha'])
                if key in observation_keys:
                    observations['duplicate_keys'] += 1
                observation_keys.add(key)
                if key in commit_observations:
                    for field, value in commit_observations[key].items():
                        observations[field + '_mismatches_against_commit'] += row.get(field) != value
    audit['frozen_observations'] = dict(observations)
    audit['frozen_observations']['distinct_repo_sha'] = len(observation_keys)
    audit['frozen_observations']['commits_without_observation'] = len(commits.keys() - observation_keys)
    audit['frozen_observations']['observations_without_commit'] = len(observation_keys - commits.keys())
    failure_count_names = ['duplicate_primary_keys', 'out_of_order_rows', 'missing_repository',
                           'repository_corpus_mismatch', 'line_added_total_mismatches',
                           'line_deleted_total_mismatches', 'pr_urls_mismatch',
                           'unobserved_pqc_flag_despite_eligibility', 'invalid_base64_patches',
                           'not_in_full_set', 'different_raw_record_from_full_set']
    failure_count_names += [k + '_out_of_order_records' for k in ['comments', 'reviews', 'review_comments']]
    structural_passed = all(not d['schema_errors'] and not d['date_errors'] and
                            all(d['counts'].get(k, 0) == 0 for k in failure_count_names)
                            for d in audit['datasets'].values())
    files_passed = not checksum_failures and all(all(f[k] for k in
                        ['matches_manifest_rows', 'matches_manifest_bytes', 'matches_manifest_sha256'])
                        for f in audit['files'].values())
    link_failures = ['pr_commit_edges_missing_commit', 'commit_pr_edges_missing_pr',
                     'pr_commit_not_reciprocated', 'commit_pr_not_reciprocated',
                     'in_dataset_pr_issue_not_reciprocated', 'in_dataset_issue_pr_not_reciprocated',
                     'issue_pr_number_collisions_same_repo']
    links_passed = all(audit['links'][k] == 0 for k in link_failures)
    filters_passed = all(v['reported_removals_equal_actual_full_minus_filtered'] and
                        all(s['actual_rows'] == s['reported_rows'] == s['unique_keys'] and
                            s['previously_removed_keys'] == s['keys_not_in_full_set'] == 0
                            for s in v['steps']) for v in reports.values())
    provenance_passed = (audit['frozen_observations']['commits_without_observation'] == 0 and
                         audit['frozen_observations']['observations_without_commit'] == 0 and
                         observations['duplicate_keys'] == 0 and
                         all(observations[f + '_mismatches_against_commit'] == 0 for f in
                             ['on_default_branch', 'in_merged_pr', 'pqc_in_linked_text']))
    audit['validation'] = {'structural_checks_passed': structural_passed,
                           'file_integrity_passed': files_passed,
                           'internal_links_passed': links_passed,
                           'filter_ledgers_passed': filters_passed,
                           'frozen_observations_passed': provenance_passed,
                           'all_checked_invariants_passed': all([structural_passed, files_passed,
                                                                links_passed, filters_passed, provenance_passed])}
    audit['audit_completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save(output, audit)
    save(output.with_name('showcase-candidates.json'), {
        'prs': [pr_info[k] for k in sorted(sample_targets) if k in pr_info],
        'issues': [r for k, r in issue_info.items() if any((p['repo'], p['number']) in sample_targets for p in r['closed_by_prs'])],
        'commits': [dict(r, in_filtered_set=(r['repo'], r['sha']) in filtered_commits) for r in showcase_commits]})
    print(json.dumps({'scan_complete': True, 'validation': audit['validation'],
                      'datasets': {k: v['counts']['rows'] for k, v in audit['datasets'].items()},
                      'links': audit['links']}, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('dataset', type=Path)
    p.add_argument('--output', type=Path, default=Path('dataset-audit.json'))
    p.add_argument('--wait-for-files', action='store_true', help='Audit hydrated shards first, wait for remaining files; verify order in canonical shard order.')
    a = p.parse_args()
    run(a.dataset, a.output, a.wait_for_files)
