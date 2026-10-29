"""Assemble a release directory: check it, split large files into parts, add the docs, write checksums.

The directory must already hold the mined and filtered files, each either
`name.jsonl` or a `name/` directory of parts, with its `name.meta.json`. For each:

1. a single file larger than the part size is split into `name/part-*.jsonl`; the
   single file is removed only after the parts hold the same lines (this needs
   free space for one more copy of that file);
2. its rows are counted and checked against its meta file.

Then the dataset card, field guide, JSON Schemas and data licence are copied in,
and `manifest.json` (rows, bytes and SHA-256 of every data file) and `SHA256SUMS`
(every file, for `sha256sum -c SHA256SUMS`) are written.
"""

import hashlib
from pathlib import Path
import shutil
from typing import Any

from .common import now, read_json, write_json_atomic
from .export import jsonl
from .paths import PROJECT_ROOT

DATASETS = ('commits', 'commits_filtered', 'issues', 'issues_filtered', 'pull_requests', 'repositories')
REPORTS = ('commits_filtered_report', 'issues_filtered_report')
DOCS = {'README.md': PROJECT_ROOT / 'dataset_card' / 'README.md', 'SCHEMA.md': PROJECT_ROOT / 'SCHEMA.md',
        'LICENSE': PROJECT_ROOT / 'LICENSE-DATA'}
COMPUTED_META = {'name', 'rows', 'sha256', 'bytes', 'parts', 'created_at'}


def locate(directory: Path, name: str) -> Path:
    for candidate in (directory / name, directory / f'{name}.jsonl'):
        if candidate.exists():
            return candidate
    raise SystemExit(f'{directory} has no {name} or {name}.jsonl')


def split(file: Path, part_bytes: int) -> Path:
    """Replace a single file by a directory of parts with the same lines, in order."""
    meta = read_json(jsonl.meta_path(file))
    provenance = {key: value for key, value in meta.items() if key not in COMPUTED_META}
    target = file.with_suffix('')
    # The parts' meta file has the same name as the single file's and replaces it.
    rows = jsonl.write_lines(target, jsonl.lines(file), part_bytes, **provenance, split_from=file.name)
    if rows != meta['rows']:
        raise SystemExit(f'Splitting {file.name} gave {rows} rows, not {meta["rows"]}; the original is kept')
    file.unlink()
    return target


def scan(file: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = size = 0
    with file.open('rb') as stream:
        for line in stream:
            digest.update(line)
            size += len(line)
            rows += bool(line.strip())
    return {'rows': rows, 'bytes': size, 'sha256': digest.hexdigest()}


def check(path: Path, directory: Path) -> dict[str, Any]:
    files = jsonl.part_files(path) if path.is_dir() else [path]
    scanned = [{'path': str(f.relative_to(directory)), **scan(f)} for f in files]
    rows = sum(f['rows'] for f in scanned)
    meta = read_json(jsonl.meta_path(path))
    if rows != meta['rows']:
        raise SystemExit(f'{path.name} has {rows} rows but its meta file says {meta["rows"]}')
    return {'rows': rows, 'bytes': sum(f['bytes'] for f in scanned), 'files': scanned}


def copy_docs(directory: Path) -> None:
    for name, source in DOCS.items():
        shutil.copyfile(source, directory / name)
    schemas = directory / 'schemas'
    schemas.mkdir(exist_ok=True)
    for source in sorted((PROJECT_ROOT / 'schemas').iterdir()):
        shutil.copyfile(source, schemas / source.name)


def write_checksums(directory: Path) -> int:
    files = sorted(p for p in directory.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    lines = []
    for file in files:
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            while block := stream.read(1 << 20):
                digest.update(block)
        lines.append(f'{digest.hexdigest()}  {file.relative_to(directory).as_posix()}\n')
    (directory / 'SHA256SUMS').write_text(''.join(lines))
    return len(lines)


def release(directory: Path, part_bytes: int = jsonl.PART_BYTES) -> dict[str, Any]:
    datasets = {}
    for name in DATASETS:
        path = locate(directory, name)
        if path.is_file() and path.stat().st_size > part_bytes:
            print(f'splitting {path.name} into parts', flush=True)
            path = split(path, part_bytes)
        datasets[name] = {'path': path.name, **check(path, directory)}
        print(f'{name}: {datasets[name]["rows"]} rows, {len(datasets[name]["files"])} file(s)', flush=True)
    copy_docs(directory)
    manifest = {'created_at': now(), 'datasets': datasets,
                'reports': [name for name in REPORTS if (directory / name).is_dir()]}
    write_json_atomic(directory / 'manifest.json', manifest)
    print(f'SHA256SUMS: {write_checksums(directory)} files', flush=True)
    return manifest
