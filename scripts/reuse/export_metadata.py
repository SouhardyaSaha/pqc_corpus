#!/usr/bin/env python3
"""Write the patch-free view of a release to a new directory."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from trace_issue import SelectedRecord, fragments, strict_json


TABLES = ['commits', 'commits_filtered', 'repositories', 'issues', 'issues_filtered', 'pull_requests']
RESERVED = ['manifest.json', 'source-manifest.json', 'README.txt', 'SHA256SUMS', 'COMPLETE.json',
            'progress.json', 'go-x25519mlkem768-examples.json', 'LICENSE',
            'schemas/commits_metadata.schema.json', 'schemas/repositories.schema.json',
            'schemas/issues.schema.json', 'schemas/pull_requests.schema.json']


def confined(root, relative):
    """Accept only relative POSIX paths resolving inside the designated root."""
    root = root.resolve()
    if not isinstance(relative, str) or not relative or any(ord(c) < 32 or ord(c) == 127 for c in relative):
        raise ValueError(f'Unsafe manifest path: {relative!r}')
    path = PurePosixPath(relative)
    if (path.is_absolute()
            or '..' in path.parts or '\\' in relative or path.as_posix() != relative):
        raise ValueError(f'Unsafe manifest path: {relative!r}')
    target = (root / relative).resolve()
    if target == root or root not in target.parents:
        raise ValueError(f'Manifest path escapes root: {relative!r}')
    return target


def validate_paths(data, output, manifest):
    """Check the entire plan before writing any output, including aliases."""
    sources, targets = set(), {confined(output, path) for path in RESERVED}
    for name in TABLES:
        for meta in manifest['datasets'][name]['files']:
            source = confined(data, meta['path'])
            relative = ((Path(name + '_metadata') / Path(meta['path']).name).as_posix()
                        if name.startswith('commits') else meta['path'])
            target = confined(output, relative)
            if source in sources or target in targets:
                raise ValueError('Duplicate or reserved manifest destination: ' + relative)
            if not source.is_file():
                raise ValueError('Missing source file: ' + meta['path'])
            sources.add(source)
            targets.add(target)


def frozen_inputs(data):
    """Tie the manifest and copied schemas to the named Git revision."""
    snapshot = subprocess.check_output(['git', '-C', str(data), 'rev-parse', 'HEAD'], text=True).strip()
    paths = ['manifest.json'] + [f'schemas/{name}.schema.json' for name in
                                ['commits', 'repositories', 'issues', 'pull_requests']]
    if (data / 'LICENSE').is_file():
        paths.append('LICENSE')
    for relative in paths:
        frozen = subprocess.check_output(['git', '-C', str(data), 'show', f'{snapshot}:{relative}'])
        if confined(data, relative).read_bytes() != frozen:
            raise ValueError('Source worktree differs from frozen Git input: ' + relative)
    return snapshot, strict_json((data / 'manifest.json').read_bytes())


def finalize_output(output):
    """Write the only completion signal after all checksums and files are durable."""
    output = output.resolve()
    marker = output / 'COMPLETE.json'
    if marker.exists():
        raise ValueError('Derivative already has a completion marker')
    required = ['manifest.json', 'source-manifest.json', 'README.txt', 'progress.json']
    if any(not (output / path).is_file() for path in required):
        raise ValueError('Derivative is missing required finalization files')
    manifest = strict_json((output / 'manifest.json').read_bytes())
    for spec in manifest['datasets'].values():
        required.append(spec['schema'])
        required.extend(item['path'] for item in spec['files'])
    if any(not confined(output, path).is_file() for path in required):
        raise ValueError('Derivative is missing a declared data file or schema')
    checksums = {}
    for path in sorted(output.rglob('*')):
        if path.is_file() and path.name not in ('SHA256SUMS', 'COMPLETE.json'):
            relative = path.relative_to(output).as_posix()
            checksums[relative] = hash_file(path)
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    for spec in manifest['datasets'].values():
        for item in spec['files']:
            path = confined(output, item['path'])
            if checksums[item['path']] != item['sha256'] or path.stat().st_size != item['bytes']:
                raise ValueError('Finalized data differs from derivative manifest: ' + item['path'])
    sums = output / 'SHA256SUMS'
    sums.write_text(''.join(f'{digest}  {relative}\n' for relative, digest in sorted(checksums.items())))
    with sums.open('rb') as stream:
        os.fsync(stream.fileno())
    temporary = output / '.COMPLETE.json.tmp'
    write_json(temporary, {'status': 'complete', 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
                          'manifest_sha256': checksums['manifest.json'],
                          'sha256sums_sha256': hash_file(sums), 'checked_files': len(checksums)})
    with temporary.open('rb') as stream:
        os.fsync(stream.fileno())
    temporary.replace(marker)
    directory = os.open(output, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def metadata_records(path, relative, snapshot, file_digest):
    """Yield commits without patch_content, adding _patch and _source descriptors."""
    capture = SelectedRecord(commit=True)
    record_hash = hashlib.sha256()
    line, offset, size = 1, 0, 0

    def finish(newline):
        record = strict_json(capture.metadata)
        if '_patch' in record or '_source' in record:
            raise ValueError('Source collides with derivative descriptor fields')
        if capture.patch is None or 'patch_content' not in record:
            raise ValueError('Commit record has no patch_content string')
        descriptor = capture.patch.summary()
        descriptor['json_string_content_bytes'] = size - int(newline) - len(capture.metadata)
        if descriptor['json_string_content_bytes'] < 0:
            raise ValueError('Invalid patch-size accounting')
        record.pop('patch_content')
        record['_patch'] = descriptor
        record['_source'] = {
            'snapshot_commit': snapshot, 'file': relative, 'line': line,
            'byte_offset': offset, 'record_bytes': size,
            'record_sha256': record_hash.hexdigest(),
        }
        return record

    for fragment, ended in fragments(path):
        file_digest.update(fragment)
        record_hash.update(fragment)
        size += len(fragment)
        capture.feed(fragment)
        if ended:
            file_digest.update(b'\n')
            record_hash.update(b'\n')
            size += 1
            yield finish(True)
            offset += size
            line, size = line + 1, 0
            record_hash = hashlib.sha256()
            capture = SelectedRecord(commit=True)
    if size:
        yield finish(False)


def export_commit_file(source, target, meta, snapshot):
    target.parent.mkdir(parents=True, exist_ok=True)
    source_hash, output_hash = hashlib.sha256(), hashlib.sha256()
    rows = byte_count = 0
    go_examples = []
    with target.open('xb') as out:
        for record in metadata_records(source, meta['path'], snapshot, source_hash):
            raw = (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
            out.write(raw)
            output_hash.update(raw)
            rows += 1
            byte_count += len(raw)
            if record['repo'] == 'golang/go' and 'X25519MLKEM768' in record['message']:
                go_examples.append(record)
    if rows != meta['rows'] or source_hash.hexdigest() != meta['sha256']:
        raise ValueError('Source count/hash differs from frozen manifest: ' + meta['path'])
    if source.stat().st_size != meta['bytes']:
        raise ValueError('Source byte size differs from frozen manifest: ' + meta['path'])
    return {'rows': rows, 'bytes': byte_count, 'sha256': output_hash.hexdigest()}, go_examples


def derivative_schema(source):
    schema = json.loads(source.read_text())
    schema['title'] = 'PQC-Corpus patch-free commit metadata derivative'
    schema['description'] = ('Commit metadata preserving all source fields except patch_content, '
                             'with original patch byte/hash descriptors and source record locators. '
                             'Key: repo, sha; full and filtered views overlap.')
    schema.pop('$id', None)
    schema['required'] = [x for x in schema['required'] if x != 'patch_content'] + ['_patch', '_source']
    schema['properties'].pop('patch_content')
    schema['properties']['_patch'] = {
        'type': 'object', 'additionalProperties': False,
        'required': ['encoding', 'bytes', 'sha256', 'json_string_content_bytes'],
        'properties': {'encoding': {'type': 'string', 'enum': ['utf-8', 'base64']},
                       'bytes': {'type': 'integer'}, 'sha256': {'type': 'string'},
                       'json_string_content_bytes': {'type': 'integer'}},
    }
    schema['properties']['_source'] = {
        'type': 'object', 'additionalProperties': False,
        'required': ['snapshot_commit', 'file', 'line', 'byte_offset', 'record_bytes', 'record_sha256'],
        'properties': {name: {'type': typ} for name, typ in {
            'snapshot_commit': 'string', 'file': 'string', 'line': 'integer',
            'byte_offset': 'integer', 'record_bytes': 'integer', 'record_sha256': 'string',
        }.items()},
    }
    return schema


def export(data, output):
    data, output = data.resolve(), output.resolve()
    if output == data or data in output.parents:
        raise ValueError('Derivative output must be separate from the original release')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Refusing to overwrite a nonempty output directory')
    snapshot, source_manifest = frozen_inputs(data)
    validate_paths(data, output, source_manifest)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        'kind': 'patch-free-reviewer-metadata-derivative',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': {'url': 'https://huggingface.co/datasets/pqc-datasets/pqc-corpus',
                   'snapshot_commit': snapshot, 'manifest_sha256': hash_file(data / 'manifest.json')},
        'transformation': 'Remove only patch_content from commit records; preserve all other original fields and add _patch/_source descriptors. Other JSONL tables are byte-identical copies.',
        'datasets': {},
    }
    progress = {'status': 'running', 'source_snapshot': snapshot, 'completed_files': []}
    examples = {'source_snapshot': snapshot, 'views': {}}
    checksums = {}
    for source_name in ['commits', 'commits_filtered']:
        name = source_name + '_metadata'
        spec = {'files': [], 'rows': 0, 'schema': 'schemas/commits_metadata.schema.json'}
        examples['views'][source_name] = []
        for meta in source_manifest['datasets'][source_name]['files']:
            relative = (Path(name) / Path(meta['path']).name).as_posix()
            print('Exporting ' + meta['path'], flush=True)
            result, candidates = export_commit_file(data / meta['path'], output / relative, meta, snapshot)
            spec['files'].append({'path': relative, **result})
            spec['rows'] += result['rows']
            checksums[relative] = result['sha256']
            examples['views'][source_name].extend(candidates)
            progress['completed_files'].append({'source': meta['path'], 'output': relative, **result})
            write_json(output / 'progress.json', progress)
            write_json(output / 'go-x25519mlkem768-examples.json', examples)
        manifest['datasets'][name] = spec
    for name in ['repositories', 'issues', 'issues_filtered', 'pull_requests']:
        spec = {'files': [], 'rows': 0, 'schema': 'schemas/' + name.removesuffix('_filtered') + '.schema.json'}
        for meta in source_manifest['datasets'][name]['files']:
            target = output / meta['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(data / meta['path'], target)
            digest = hash_file(target)
            if digest != meta['sha256'] or target.stat().st_size != meta['bytes']:
                raise ValueError('Copied table failed integrity check: ' + meta['path'])
            spec['files'].append(dict(meta))
            spec['rows'] += meta['rows']
            checksums[meta['path']] = digest
        manifest['datasets'][name] = spec
    (output / 'schemas').mkdir(exist_ok=True)
    write_json(output / 'schemas/commits_metadata.schema.json', derivative_schema(data / 'schemas/commits.schema.json'))
    for name in ['repositories', 'issues', 'pull_requests']:
        shutil.copyfile(data / f'schemas/{name}.schema.json', output / f'schemas/{name}.schema.json')
    if (data / 'LICENSE').is_file():
        shutil.copyfile(data / 'LICENSE', output / 'LICENSE')
    write_json(output / 'source-manifest.json', source_manifest)
    progress['status'] = 'data-exported-awaiting-completion-marker'
    write_json(output / 'progress.json', progress)
    manifest['data_bytes'] = sum(f['bytes'] for ds in manifest['datasets'].values() for f in ds['files'])
    write_json(output / 'manifest.json', manifest)
    (output / 'README.txt').write_text(
        'PQC-Corpus patch-free reviewer metadata — separate derivative\n\n'
        f'Source snapshot: {snapshot}\n'
        'Source: https://huggingface.co/datasets/pqc-datasets/pqc-corpus\n\n'
        'commits_metadata/ and commits_filtered_metadata/ preserve every original commit field except patch_content. '
        'Messages, paths/change statistics, author fields, timestamps, repository-qualified keys, PR links and eligibility flags remain. '
        'The original release is unchanged. Repository, issue, filtered-issue and PR files are byte-identical copies.\n\n'
        '_patch.encoding repeats patch_encoding. _patch.bytes and _patch.sha256 describe the original Git patch bytes '
        '(base64-decoded when patch_encoding=base64). json_string_content_bytes counts the source JSON-escaped string bytes excluding quotes. '
        '_source identifies the frozen source shard, one-based line, zero-based byte offset, full record byte length '
        'including its newline when present, and SHA-256 of that exact source record.\n\n'
        'No remaining original field is silently discarded. Descriptors are additions to the derivative, not claims of new source data. '
        'Patches can be retrieved from the source snapshot using _source; this derivative cannot supply patch text by itself. '
        'Its metadata schemas replace only the source commit patch field with the two descriptor objects.\n\n'
        'All source data shard hashes/sizes and commit row counts were checked while exporting. SHA256SUMS covers every file in this derivative except itself and COMPLETE.json. '
        'Only COMPLETE.json signals successful finalization; it is written atomically after files and checksums are durable and records their hashes. '
        'The exporter uses bounded chunks and fails above 64 MiB of metadata in one record; patch length does not determine memory usage. '
        'Some metadata records can still be large because changed_files is preserved.\n\n'
        'Full/filtered configurations overlap. Empty PR-link arrays do not establish a direct push. '
        'Raw names, messages and discussion bodies remain, so this is not an anonymized dataset. '
        'Source licensing remains applicable; upstream code/content retains its upstream licenses.\n')
    finalize_output(output)
    print(json.dumps({'output': str(output), 'data_bytes': manifest['data_bytes'],
                      'rows': {k: v['rows'] for k, v in manifest['datasets'].items()},
                      'source_snapshot': snapshot}, indent=2), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    export(args.data, args.output)


if __name__ == '__main__':
    main()
