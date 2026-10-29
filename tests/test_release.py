import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

from pqc_corpus.export import jsonl
from pqc_corpus.export.commits import commits
from pqc_corpus.export.issues import issues
from pqc_corpus.export.pull_requests import pull_requests
from pqc_corpus.export.repositories import repositories
from pqc_corpus.figures import figures
from pqc_corpus.filters.commits import filter_commits
from pqc_corpus.filters.issues import filter_issues
from pqc_corpus.release import release

from fixtures import REPO, author_keys, make_run


class ReleaseTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_release_splits_large_files_and_writes_checksums(self) -> None:
        before = list(jsonl.lines(self.out / 'commits.jsonl'))
        manifest = release(self.out, part_bytes=2000)
        self.assertFalse((self.out / 'commits.jsonl').exists())
        self.assertGreater(len(jsonl.part_files(self.out / 'commits')), 1)
        self.assertEqual(list(jsonl.lines(self.out / 'commits')), before)
        self.assertEqual(manifest['datasets']['commits']['rows'], 5)
        self.assertEqual(manifest['datasets']['issues_filtered']['rows'], 1)
        for name in ('README.md', 'SCHEMA.md', 'LICENSE', 'schemas/pull_requests.schema.json', 'manifest.json'):
            self.assertTrue((self.out / name).exists(), name)
        for line in (self.out / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest)
        for text in [p.read_text() for p in self.out.rglob('*.json')]:
            self.assertNotIn(self.temp.name, text)

    def test_figures_table_counts_come_from_the_release(self) -> None:
        release(self.out)
        figures(self.out, Path(self.temp.name) / 'figures')
        with (Path(self.temp.name) / 'figures' / 'table1.csv').open() as stream:
            table = {row['row']: row for row in csv.DictReader(stream)}
        self.assertEqual(table['Commits']['A'], '5')
        self.assertEqual(table['Pull requests']['total'], '1')
        self.assertEqual(table['Commit–PR links']['A'], '1')
        self.assertEqual(table['General comments']['A'], '3')
        self.assertEqual(table['PRs on GitHub']['A'], '4')
        bins = (Path(self.temp.name) / 'figures' / 'fig3b_commits_per_repository.csv').read_text()
        self.assertIn('1–9,1', bins)


if __name__ == '__main__':
    unittest.main()
