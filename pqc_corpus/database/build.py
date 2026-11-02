"""Load a release directory into one SQLite file, then check it reproduces the release.

The database is written to a temporary sibling and renamed into place only after
`verify` has rebuilt every data file from it byte for byte; atomicity applies to the
database file.
"""

import csv
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator

from ..common import now
from ..export import jsonl
from ..release import locate
from .rebuild import observations_file, verify
from .tables import COMMITS, FILTERED, INDEX_SQL, PATCH_LIMIT, PATCH_PARTS, TABLES, Field, ListOf, Table, schema_sql

# Characters per stored piece of an oversized patch: at most 4 UTF-8 bytes each, so a
# piece stays below SQLite's value limit.
PATCH_PIECE_CHARS = PATCH_LIMIT // 4
BATCH = 500


def stored(field: Field, value: Any) -> Any:
    return int(value) if field.kind == 'boolean' and value is not None else value


def json_keys(table: Table) -> list[str]:
    return [key for field in table.fields for key in (field.keys if isinstance(field, ListOf) else (field.key,))]


def child_rows(key: tuple, child: ListOf, record: dict[str, Any]) -> Iterator[tuple]:
    if child.objects:
        for position, item in enumerate(record[child.keys[0]]):
            if list(item) != [field.key for field in child.items]:
                raise ValueError(f'{child.keys[0]} item of {key} has fields {list(item)}')
            yield (*key, position, *(stored(field, item[field.key]) for field in child.items))
        return
    lists = [record[name] for name in child.keys]
    if len({len(values) for values in lists}) > 1:
        raise ValueError(f'{key}: {", ".join(child.keys)} differ in length')
    for position, values in enumerate(zip(*lists)):
        yield (*key, position, *(stored(field, value) for field, value in zip(child.items, values)))


def oversized(patch: str) -> bool:
    return len(patch) * 4 > PATCH_LIMIT and len(patch.encode('utf-8')) > PATCH_LIMIT


class Loader:
    def __init__(self, db: sqlite3.Connection, table: Table) -> None:
        self.db = db
        self.table = table
        self.keys = json_keys(table)
        self.scalars = [field for field in table.fields if isinstance(field, Field)]
        self.children = [field for field in table.fields if isinstance(field, ListOf)]
        self.pending: dict[str, list[tuple]] = {}

    def add(self, record: dict[str, Any]) -> None:
        key = tuple(record[field.key] for field in self.table.key)
        if list(record) != self.keys:
            raise ValueError(f'{self.table.dataset} record {key} has fields {list(record)}')
        row = [stored(field, record[field.key]) for field in self.scalars]
        if self.table is COMMITS and oversized(record['patch_content']):
            patch = record['patch_content']
            row[[field.key for field in self.scalars].index('patch_content')] = None
            pieces = range(0, len(patch), PATCH_PIECE_CHARS)
            self.queue(PATCH_PARTS, [(*key, part, patch[start:start + PATCH_PIECE_CHARS])
                                     for part, start in enumerate(pieces)])
        self.queue(self.table.name, [tuple(row)])
        for child in self.children:
            self.queue(child.table, list(child_rows(key, child, record)))
        if len(self.pending[self.table.name]) >= BATCH:
            self.flush()

    def queue(self, table: str, rows: list[tuple]) -> None:
        self.pending.setdefault(table, []).extend(rows)

    def flush(self) -> None:
        for table, rows in self.pending.items():
            if rows:
                marks = ', '.join('?' * len(rows[0]))
                self.db.executemany(f'INSERT INTO {table} VALUES ({marks})', rows)
        self.pending.clear()


def load_table(db: sqlite3.Connection, table: Table, records: Iterable[dict[str, Any]]) -> int:
    loader = Loader(db, table)
    rows = 0
    for rows, record in enumerate(records, 1):
        loader.add(record)
    loader.flush()
    return rows


def load_filtered(db: sqlite3.Connection, name: str, table: Table, records: Iterable[dict[str, Any]]) -> int:
    rows = [(position, *(record[field.key] for field in table.key)) for position, record in enumerate(records)]
    db.executemany(f'INSERT INTO {name} VALUES ({", ".join("?" * (len(table.key) + 1))})', rows)
    return len(rows)


def load_csv(db: sqlite3.Connection, table: str, files: list[Path], integers: set[str]) -> int:
    """Rows of the removal CSVs, whose header must match the table; an empty cell becomes NULL."""
    columns = [name for _, name, *_ in db.execute(f'PRAGMA table_info({table})')]
    rows = []
    for file in files:
        with file.open(newline='', encoding='utf-8') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != columns:
                raise ValueError(f'{file.name} has columns {reader.fieldnames}, not {columns}')
            for row in reader:
                rows.append(tuple(None if value == '' else int(value) if name in integers else value
                                  for name, value in row.items()))
    db.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" * len(columns))})', rows)
    return len(rows)


def load_observations(db: sqlite3.Connection, file: Path) -> int:
    rows = [(r['repo'], r['sha'], int(r['on_default_branch']), int(r['in_merged_pr']),
             None if r['pqc_in_linked_text'] is None else int(r['pqc_in_linked_text'])) for r in jsonl.read(file)]
    db.executemany('INSERT INTO commit_observations VALUES (?, ?, ?, ?, ?)', rows)
    return len(rows)


def about(directory: Path) -> dict[str, str]:
    """Provenance kept as text: the release's checksums, meta files and filter summaries."""
    values = {'built_at': now(), 'source': directory.name,
              'SHA256SUMS': (directory / 'SHA256SUMS').read_text(encoding='utf-8')}
    for file in sorted(directory.glob('*.meta.json')) + [directory / 'manifest.json']:
        values[file.name] = file.read_text(encoding='utf-8')
    for report in ('commits_filtered_report', 'issues_filtered_report'):
        values[f'{report}/summary.json'] = (directory / report / 'summary.json').read_text(encoding='utf-8')
    return values


def build(directory: Path, output: Path) -> dict[str, int]:
    """Write `output` from the release in `directory`; returns the rows per table loaded."""
    if output.exists():
        raise FileExistsError(f'{output} exists; choose a new output path')
    temporary = output.with_name(f'.{output.name}.incomplete')
    temporary.unlink(missing_ok=True)
    db = sqlite3.connect(temporary)
    counts: dict[str, int] = {}
    try:
        db.execute('PRAGMA journal_mode = OFF')
        db.execute('PRAGMA synchronous = OFF')
        db.executescript(schema_sql())
        for table in TABLES:
            counts[table.name] = load_table(db, table, jsonl.read(locate(directory, table.dataset)))
            db.commit()
            print(f'{table.name}: {counts[table.name]} rows', flush=True)
        for name, table in FILTERED.items():
            counts[name] = load_filtered(db, name, table, jsonl.read(locate(directory, name)))
        counts['commit_removals'] = load_csv(db, 'commit_removals',
                                             sorted((directory / 'commits_filtered_report').glob('*.csv')), {'step'})
        counts['issue_removals'] = load_csv(db, 'issue_removals',
                                            sorted((directory / 'issues_filtered_report').glob('*.csv')), {'number'})
        observations = observations_file(directory)
        counts['commit_observations'] = load_observations(db, observations) if observations else 0
        db.executemany('INSERT INTO about VALUES (?, ?)', about(directory).items())
        for statement in INDEX_SQL:
            db.execute(statement)
        db.execute('ANALYZE')
        db.commit()
        db.execute('PRAGMA journal_mode = DELETE')
        print('checking the database against the release', flush=True)
        verify(db, directory)
    finally:
        db.close()
    temporary.replace(output)
    return counts


def main(directory: Path, output: Path) -> None:
    counts = build(directory, output)
    print(json.dumps(counts, indent=1))
    print(f'{output}: {output.stat().st_size / 1e9:.1f} GB, reproduces every data file of {directory.name}')
