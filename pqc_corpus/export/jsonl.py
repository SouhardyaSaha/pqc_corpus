"""JSON Lines output, written to a temporary sibling and renamed into place.

A dataset file is either one `name.jsonl` file or a `name/` directory of parts
(`part-00000.jsonl`, ...), each at most about `part_bytes`; read the parts in name
order as one file. A path without the `.jsonl` suffix means parts. Every written
file or directory gets a `name.meta.json` beside it with its row count, SHA-256
(per part for a directory) and the given provenance, which should name inputs
without absolute paths. Atomicity applies to the data and to its meta file
separately.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Iterator

from ..common import file_sha256, now, write_json_atomic

PART_BYTES = 1 << 30


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(',', ':'))


def is_parts(path: Path) -> bool:
    return path.suffix != '.jsonl'


def meta_path(path: Path) -> Path:
    return path.with_name(path.name.removesuffix('.jsonl') + '.meta.json')


def part_files(path: Path) -> list[Path]:
    return sorted(path.glob('part-*.jsonl'))


def lines(path: Path) -> Iterator[str]:
    """Every non-empty line of a file or of a directory's parts, each ending in a newline."""
    for file in (part_files(path) if path.is_dir() else [path]):
        with file.open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip():
                    yield line if line.endswith('\n') else line + '\n'


def read(path: Path) -> Iterator[dict[str, Any]]:
    return map(json.loads, lines(path))


class _Part:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream = path.open('w', encoding='utf-8', newline='\n')
        self.digest = hashlib.sha256()
        self.rows = 0
        self.bytes = 0

    def write(self, line: str) -> None:
        data = line.encode('utf-8')
        self.stream.write(line)
        self.digest.update(data)
        self.rows += 1
        self.bytes += len(data)

    def close(self) -> dict[str, Any]:
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        return {'file': self.path.name, 'rows': self.rows, 'bytes': self.bytes, 'sha256': self.digest.hexdigest()}


def write_lines(path: Path, source: Iterable[str], part_bytes: int = PART_BYTES, **provenance: Any) -> int:
    """Write lines (each ending in a newline) to `path`; returns the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'{path} exists; choose a new output path')
    temporary = path.with_name(f'.{path.name}.incomplete')
    if temporary.exists():
        shutil.rmtree(temporary) if temporary.is_dir() else temporary.unlink()
    parts: list[dict[str, Any]] = []
    if is_parts(path):
        temporary.mkdir()
        current = _Part(temporary / 'part-00000.jsonl')
        for line in source:
            if current.rows and current.bytes + len(line.encode('utf-8')) > part_bytes:
                parts.append(current.close())
                current = _Part(temporary / f'part-{len(parts):05d}.jsonl')
            current.write(line)
        parts.append(current.close())
        summary = {'parts': parts}
    else:
        current = _Part(temporary)
        for line in source:
            current.write(line)
        info = current.close()
        parts = [info]
        summary = {'sha256': info['sha256'], 'bytes': info['bytes']}
    temporary.replace(path)
    rows = sum(part['rows'] for part in parts)
    write_json_atomic(meta_path(path), {'name': path.name, 'rows': rows, **summary, 'created_at': now(),
                                        **provenance})
    return rows


def write(path: Path, records: Iterable[dict[str, Any]], part_bytes: int = PART_BYTES, **provenance: Any) -> int:
    """Write one record per line; see the module notes for files and parts."""
    return write_lines(path, (dumps(record) + '\n' for record in records), part_bytes, **provenance)


def identity(path: Path) -> dict[str, Any]:
    """Name and SHA-256 of a dataset file, or of each part of a directory; no absolute path."""
    if path.is_dir():
        return {'name': path.name, 'parts': [{'file': p.name, 'sha256': file_sha256(p)} for p in part_files(path)]}
    return {'name': path.name, 'sha256': file_sha256(path)}
