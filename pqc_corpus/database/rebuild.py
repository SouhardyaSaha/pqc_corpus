"""Rebuild release records from the database, and check them against the release files.

`verify` compares each rebuilt JSON line with the release's line, so a passing check
means the database holds every data file byte for byte (and so matches SHA256SUMS);
the removal lists and observations are compared row by row.
"""

import csv
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from ..export import jsonl
from ..release import locate
from .tables import COMMITS, FILTERED, PATCH_PARTS, TABLES, Field, ListOf, Table


def restored(field: Field, value: Any) -> Any:
    return bool(value) if field.kind == 'boolean' and value is not None else value


def where(table: Table) -> str:
    return ' AND '.join(f'{field.column} = ?' for field in table.key)


def child_values(db: sqlite3.Connection, table: Table, child: ListOf, key: tuple) -> dict[str, list]:
    columns = ', '.join(field.column for field in child.items)
    rows = db.execute(f'SELECT {columns} FROM {child.table} WHERE {where(table)} ORDER BY position', key).fetchall()
    if child.objects:
        items = [{field.key: restored(field, value) for field, value in zip(child.items, row)} for row in rows]
        return {child.keys[0]: items}
    return {name: [restored(field, row[i]) for row in rows] for i, (name, field) in
            enumerate(zip(child.keys, child.items))}


def patch(db: sqlite3.Connection, key: tuple) -> str:
    rows = db.execute(f'SELECT content FROM {PATCH_PARTS} WHERE repo = ? AND sha = ? ORDER BY part', key)
    return ''.join(content for (content,) in rows)


def record(db: sqlite3.Connection, table: Table, row: sqlite3.Row) -> dict[str, Any]:
    key = tuple(row[field.column] for field in table.key)
    result: dict[str, Any] = {}
    for field in table.fields:
        if isinstance(field, ListOf):
            result.update(child_values(db, table, field, key))
        else:
            result[field.key] = restored(field, row[field.column])
    if table is COMMITS and result['patch_content'] is None:
        result['patch_content'] = patch(db, key)
    return result


def records(db: sqlite3.Connection, table: Table, filtered: str | None = None) -> Iterator[dict[str, Any]]:
    """The records of a table in file order, or those of a filtered set in its order."""
    if filtered:
        joined = ' AND '.join(f'{table.name}.{f.column} = {filtered}.{f.column}' for f in table.key)
        query = f'SELECT {table.name}.* FROM {filtered} JOIN {table.name} ON {joined} ORDER BY {filtered}.position'
    else:
        query = f'SELECT * FROM {table.name} ORDER BY rowid'
    rows = db.cursor()
    rows.row_factory = sqlite3.Row
    for row in rows.execute(query):
        yield record(db, table, row)


def compare_lines(name: str, rebuilt: Iterator[dict[str, Any]], path: Path) -> int:
    rows = 0
    try:
        for rows, (ours, theirs) in enumerate(zip((jsonl.dumps(r) + '\n' for r in rebuilt), jsonl.lines(path),
                                                  strict=True), 1):
            if ours != theirs:
                raise SystemExit(f'{name}: line {rows} rebuilt from the database differs from the release')
    except ValueError:
        raise SystemExit(f'{name}: the database and the release have different row counts') from None
    return rows


def csv_rows(files: list[Path]) -> list[list[str | None]]:
    """The data rows of CSV files, without their header lines; an empty cell is None."""
    rows = []
    for file in files:
        with file.open(newline='', encoding='utf-8') as stream:
            reader = csv.reader(stream)
            next(reader)
            rows.extend([None if value == '' else value for value in row] for row in reader)
    return rows


def compare_csv(db: sqlite3.Connection, table: str, files: list[Path]) -> int:
    ours = [[None if value is None else str(value) for value in row]
            for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
    if ours != csv_rows(files):
        raise SystemExit(f'{table} differs from the release CSV files')
    return len(ours)


def observations_file(directory: Path) -> Path | None:
    """The frozen observations the commits were mined with, if the release has them."""
    return next((directory / 'provenance').glob('frozen_observations_*.jsonl'), None)


def verify(db: sqlite3.Connection, directory: Path) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        counts[table.dataset] = compare_lines(table.dataset, records(db, table), locate(directory, table.dataset))
    for name, table in FILTERED.items():
        counts[name] = compare_lines(name, records(db, table, name), locate(directory, name))
    counts['commit_removals'] = compare_csv(db, 'commit_removals',
                                            sorted((directory / 'commits_filtered_report').glob('*.csv')))
    counts['issue_removals'] = compare_csv(db, 'issue_removals',
                                           sorted((directory / 'issues_filtered_report').glob('*.csv')))
    file = observations_file(directory)
    observations = list(jsonl.read(file)) if file else []
    ours = [{'repo': r, 'sha': s, 'on_default_branch': bool(d), 'in_merged_pr': bool(m),
             'pqc_in_linked_text': None if p is None else bool(p)}
            for r, s, d, m, p in db.execute('SELECT * FROM commit_observations ORDER BY rowid')]
    if ours != observations:
        raise SystemExit('commit_observations differs from the release provenance file')
    counts['commit_observations'] = len(ours)
    return counts
