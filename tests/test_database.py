import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from pqc_corpus.database import build as database
from pqc_corpus.database.rebuild import records, verify
from pqc_corpus.database.tables import COMMITS, ISSUES, TABLES
from pqc_corpus.database.build import json_keys
from pqc_corpus.export import jsonl
from pqc_corpus.export.commits import commits
from pqc_corpus.export.issues import issues
from pqc_corpus.export.pull_requests import pull_requests
from pqc_corpus.export.repositories import repositories
from pqc_corpus.filters.commits import filter_commits
from pqc_corpus.filters.issues import filter_issues
from pqc_corpus.paths import PROJECT_ROOT
from pqc_corpus.release import release

from fixtures import REPO, author_keys, make_run


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        run, shas = make_run(root)
        self.out = root / 'release'
        observed = {(REPO, sha): (name != 'unmerged', name == 'kem', True) for name, sha in shas.items()}
        jsonl.write(self.out / 'commits.jsonl', commits(run, observed, author_keys(root)), run='fixture')
        jsonl.write(self.out / 'issues.jsonl', issues(run), run='fixture')
        jsonl.write(self.out / 'pull_requests.jsonl', pull_requests(run), run='fixture')
        jsonl.write(self.out / 'repositories.jsonl', repositories(run), run='fixture')
        filter_commits(self.out / 'commits.jsonl', self.out / 'repositories.jsonl',
                       self.out / 'commits_filtered.jsonl', self.out / 'commits_filtered_report', workers=1)
        filter_issues(self.out / 'issues.jsonl', self.out / 'issues_filtered.jsonl',
                      self.out / 'issues_filtered_report')
        observations = [{'repo': REPO, 'sha': sha, 'on_default_branch': d, 'in_merged_pr': m,
                         'pqc_in_linked_text': p} for (_, sha), (d, m, p) in observed.items()]
        (self.out / 'provenance').mkdir()
        (self.out / 'provenance' / 'frozen_observations_2026-09-29.jsonl').write_text(
            ''.join(json.dumps(r) + '\n' for r in observations))
        release(self.out, part_bytes=2000)
        self.db_path = root / 'pqc_corpus.db'

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_tables_cover_every_schema_field_in_order(self) -> None:
        for table in TABLES:
            schema = json.loads((PROJECT_ROOT / 'schemas' / f'{table.dataset}.schema.json').read_text())
            self.assertEqual(json_keys(table), list(schema['properties']), table.dataset)

    def test_database_reproduces_every_release_line(self) -> None:
        counts = database.build(self.out, self.db_path)
        self.assertEqual(counts['commits'], 5)
        self.assertEqual(counts['commits_filtered'], 3)
        self.assertEqual(counts['commit_observations'], 5)
        db = sqlite3.connect(self.db_path)
        try:
            rebuilt = [jsonl.dumps(r) + '\n' for r in records(db, COMMITS)]
            self.assertEqual(rebuilt, list(jsonl.lines(self.out / 'commits')))
            self.assertEqual(db.execute('SELECT count(*) FROM commit_patch_parts').fetchone()[0], 0)
            linked = db.execute('SELECT count(*) FROM commit_pull_requests JOIN pull_requests '
                                'ON pull_requests.repo = commit_pull_requests.repo '
                                'AND pull_requests.number = commit_pull_requests.pr_number').fetchone()[0]
            self.assertGreater(linked, 0)
            self.assertIn('SHA256SUMS', dict(db.execute('SELECT key, value FROM about')))
        finally:
            db.close()

    def test_oversized_patches_are_stored_in_pieces(self) -> None:
        with mock.patch.object(database, 'PATCH_LIMIT', 40), mock.patch.object(database, 'PATCH_PIECE_CHARS', 10):
            database.build(self.out, self.db_path)
        db = sqlite3.connect(self.db_path)
        try:
            split = db.execute('SELECT count(*) FROM commits WHERE patch_content IS NULL').fetchone()[0]
            self.assertGreater(split, 0)
            self.assertGreater(db.execute('SELECT count(*) FROM commit_patch_parts').fetchone()[0], split)
            verify(db, self.out)
        finally:
            db.close()

    def test_a_changed_value_fails_the_check_and_keeps_no_database(self) -> None:
        original = database.load_table

        def tamper(db: sqlite3.Connection, table, rows):
            count = original(db, table, rows)
            if table is ISSUES:
                db.execute('UPDATE issue_comments SET body = body || ? WHERE position = 0', ('!',))
            return count

        with mock.patch.object(database, 'load_table', tamper), self.assertRaises(SystemExit) as stopped:
            database.build(self.out, self.db_path)
        self.assertIn('issues: line', str(stopped.exception))
        self.assertFalse(self.db_path.exists())

    def test_an_existing_output_is_not_replaced(self) -> None:
        self.db_path.write_text('keep')
        with self.assertRaises(FileExistsError):
            database.build(self.out, self.db_path)
        self.assertEqual(self.db_path.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
