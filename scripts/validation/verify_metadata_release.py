#!/usr/bin/env python3
"""Check an extracted patch-free view without the original patches."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reuse'))
from export_metadata import confined, hash_file
from trace_issue import strict_json


def verify(root):
    root = root.resolve()
    manifest = strict_json((root / 'manifest.json').read_bytes())
    source = strict_json((root / 'source-manifest.json').read_bytes())
    marker = strict_json((root / 'COMPLETE.json').read_bytes())
    assert marker['status'] == 'complete'
    assert marker['manifest_sha256'] == hash_file(root / 'manifest.json')
    assert marker['sha256sums_sha256'] == hash_file(root / 'SHA256SUMS')
    listed = set()
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, relative = line.split('  ', 1)
        assert relative not in listed
        listed.add(relative)
        assert hash_file(confined(root, relative)) == digest, relative
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    assert actual - {'COMPLETE.json', 'SHA256SUMS'} == listed
    assert marker['checked_files'] == len(listed)
    source_files = {f['path']: f for ds in source['datasets'].values() for f in ds['files']}
    full, stats = {}, {}
    sha256 = re.compile(r'^[a-f0-9]{64}$')
    for name, spec in manifest['datasets'].items():
        commit = name.startswith('commits')
        expected_fields = set(strict_json((root / spec['schema']).read_bytes())['properties'])
        keys, rows, size, max_line, encodings = set(), 0, 0, 0, Counter()
        for item in spec['files']:
            path = confined(root, item['path'])
            assert path.stat().st_size == item['bytes']
            assert hash_file(path) == item['sha256']
            file_rows, offset, source_path = 0, 0, None
            with path.open('rb') as stream:
                for raw in stream:
                    file_rows += 1
                    max_line = max(max_line, len(raw))
                    record = strict_json(raw)
                    assert set(record) == expected_fields, (item['path'], file_rows, set(record) ^ expected_fields)
                    identity = ((record['repo'], record['sha']) if commit else
                                (record['repo'], record['number']) if 'number' in record else record['repo'])
                    assert identity not in keys
                    keys.add(identity)
                    if commit:
                        patch, locator = record['_patch'], record['_source']
                        assert patch['encoding'] == record['patch_encoding']
                        assert patch['bytes'] >= 0 and patch['json_string_content_bytes'] >= 0
                        assert sha256.fullmatch(patch['sha256'])
                        assert locator['snapshot_commit'] == manifest['source']['snapshot_commit']
                        assert locator['line'] == file_rows and locator['byte_offset'] == offset
                        assert locator['record_bytes'] > 0 and sha256.fullmatch(locator['record_sha256'])
                        source_path = source_path or locator['file']
                        assert source_path == locator['file']
                        offset += locator['record_bytes']
                        encodings[patch['encoding']] += 1
                        content = {k: v for k, v in record.items() if k != '_source'}
                        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).digest()
                        if name == 'commits_metadata':
                            full[identity] = fingerprint
                        else:
                            assert full.get(identity) == fingerprint, identity
            assert file_rows == item['rows']
            if commit:
                assert offset == source_files[source_path]['bytes']
                assert file_rows == source_files[source_path]['rows']
            else:
                assert item == source_files[item['path']]
            rows += file_rows
            size += item['bytes']
        assert rows == spec['rows']
        stats[name] = {'rows': rows, 'bytes': size, 'max_jsonl_line_bytes': max_line,
                       'patch_encodings': dict(encodings) if commit else None}
    assert sum(s['bytes'] for s in stats.values()) == manifest['data_bytes']
    original_bytes = sum(f['bytes'] for ds in source['datasets'].values() for f in ds['files'])
    return {'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'output': str(root),
            'source_snapshot': manifest['source']['snapshot_commit'], 'all_checks_passed': True,
            'sha256_checked_files': len(listed), 'schema_validation': 'exact top-level field sets, not general JSON Schema conformance',
            'full_filtered_metadata_identical_for_retained_keys': True,
            'source_manifest_data_bytes': original_bytes, 'derivative_data_bytes': manifest['data_bytes'],
            'source_to_derivative_ratio': original_bytes / manifest['data_bytes'],
            'total_directory_file_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
            'datasets': stats, 'manifest_sha256': marker['manifest_sha256'],
            'sha256sums_sha256': marker['sha256sums_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.metadata)
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
