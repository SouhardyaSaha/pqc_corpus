import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from pqc_corpus.export import jsonl
from pqc_corpus.export.author_key import AuthorKeys, create_secret
from pqc_corpus.export.commits import commits
from pqc_corpus.export.git_diff import EMPTY_TREE, commit_diff
from pqc_corpus.export.issues import issues
from pqc_corpus.export.pull_requests import pull_requests
from pqc_corpus.export.repositories import repositories

from fixtures import REPO, author_keys, make_run


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.run, self.shas = make_run(Path(self.temp.name))
        self.keys = author_keys(Path(self.temp.name))
        self.eligibility = {(REPO, sha): (name != 'unmerged', name == 'kem', name == 'kem')
                            for name, sha in self.shas.items()}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_commits_carry_files_patch_prs_and_eligibility(self) -> None:
        rows = {r['sha']: r for r in commits(self.run, self.eligibility, self.keys)}
        self.assertEqual(len(rows), 5)
        kem = rows[self.shas['kem']]
        self.assertEqual(kem['corpus'], 'A')
        self.assertEqual(kem['url'], f'https://github.com/{REPO}/commit/{self.shas["kem"]}')
        self.assertEqual(kem['pr_numbers'], [2])
        self.assertEqual(kem['pr_urls'], [f'https://github.com/{REPO}/pull/2'])
        self.assertEqual((kem['on_default_branch'], kem['in_merged_pr'], kem['pqc_in_linked_text']), (True, True, True))
        self.assertEqual(kem['author_key'], self.keys.key('fixture@example.test'))
        self.assertNotEqual(kem['author_key'], hashlib.sha256(b'fixture@example.test').hexdigest())
        self.assertEqual(kem['changed_files'], [
            {'path': 'kem.c', 'status': 'A', 'additions': 1, 'deletions': 0, 'binary': False},
            {'path': 'logo.bin', 'status': 'A', 'additions': None, 'deletions': None, 'binary': True},
        ])
        self.assertEqual((kem['lines_added'], kem['lines_deleted']), (1, 0))
        self.assertIn('GIT binary patch', kem['patch_content'])
        self.assertEqual(kem['author_name'], 'Fixture')
        self.assertNotIn('author_email', kem)
        root = rows[self.shas['root']]
        self.assertTrue(root['patch_content'].startswith('diff --git a/README.md b/README.md\nnew file mode'))
        self.assertEqual(rows[self.shas['unmerged']]['pr_numbers'], [])

    def test_commits_are_ordered_and_need_every_eligibility_observation(self) -> None:
        keys = [r['sha'] for r in commits(self.run, self.eligibility, self.keys)]
        self.assertEqual(keys, sorted(keys))
        partial = dict(list(self.eligibility.items())[1:])
        with self.assertRaises(ValueError):
            list(commits(self.run, partial, self.keys))

    def test_patch_keeps_exact_bytes_when_not_utf8(self) -> None:
        mirror = self.run / 'mirrors' / 'fixture__project.git'
        source = Path(self.temp.name) / 'source'
        (source / 'latin1.txt').write_bytes('caf\xe9\n'.encode('latin-1'))
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=F', '-c', 'user.email=f@example.test',
                        'commit', '-m', 'latin-1'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(mirror), 'fetch', str(source), 'main:main'], check=True,
                       capture_output=True)
        sha = subprocess.check_output(['git', '-C', str(mirror), 'rev-parse', 'main'], text=True).strip()
        parent = subprocess.check_output(['git', '-C', str(mirror), 'rev-parse', 'main^'], text=True).strip()
        encoding, text = commit_diff(mirror, sha, [parent]).encoded_patch
        self.assertEqual(encoding, 'base64')
        self.assertIn(b'caf\xe9', base64.b64decode(text))
        self.assertEqual(commit_diff(mirror, self.shas['root'], []).patch,
                         subprocess.check_output(['git', '-C', str(mirror), 'diff', '--full-index', '--binary',
                                                  EMPTY_TREE, self.shas['root']]))

    def test_issues_attach_own_comments_in_order_and_closing_prs(self) -> None:
        rows = list(issues(self.run))
        self.assertEqual([r['number'] for r in rows], [1, 3])
        first = rows[0]
        self.assertEqual([c['body'] for c in first['comments']], ['First', 'Second'])
        self.assertIsNone(first['comments'][0]['author'])
        self.assertEqual(first['closed_by_prs'], [{'repo': REPO, 'number': 2,
                                                   'url': f'https://github.com/{REPO}/pull/2'}])
        self.assertEqual(rows[1]['comments'], [])
        self.assertEqual(rows[1]['author'], 'ci[bot]')

    def test_repositories_and_jsonl_meta(self) -> None:
        output = Path(self.temp.name) / 'out' / 'repositories.jsonl'
        self.assertEqual(jsonl.write(output, repositories(self.run), run='fixture'), 1)
        record = json.loads(output.read_text())
        self.assertEqual((record['repo'], record['corpus'], record['is_fork']), (REPO, 'A', False))
        self.assertEqual((record['github_pull_requests'], record['github_issues'], record['git_commits']), (4, 3, 5))
        meta = json.loads((output.parent / 'repositories.meta.json').read_text())
        self.assertEqual((meta['rows'], meta['run']), (1, 'fixture'))
        self.assertFalse(list(output.parent.glob('.*incomplete')))
        with self.assertRaises(FileExistsError):
            jsonl.write(output, repositories(self.run))

    def test_pull_requests_carry_commits_closed_issues_discussion_and_reviews(self) -> None:
        (pr,) = list(pull_requests(self.run))
        self.assertEqual((pr['number'], pr['corpus'], pr['merged'], pr['base_branch']), (2, 'A', True, 'main'))
        self.assertEqual(pr['commit_shas'], [self.shas['kem']])
        self.assertEqual(pr['closes_issues'], [{'repo': REPO, 'number': 1,
                                                'url': f'https://github.com/{REPO}/issues/1'}])
        self.assertEqual([c['body'] for c in pr['comments']], ['On PR'])
        self.assertEqual(pr['reviews'][0]['state'], 'APPROVED')
        self.assertEqual(pr['review_comments'][0]['path'], 'kem.c')

    def test_parts_hold_the_same_lines_in_order(self) -> None:
        records = [{'repo': REPO, 'n': i, 'pad': 'x' * 40} for i in range(10)]
        output = Path(self.temp.name) / 'out' / 'parts'
        self.assertEqual(jsonl.write(output, records, part_bytes=200), 10)
        self.assertGreater(len(jsonl.part_files(output)), 1)
        self.assertEqual(list(jsonl.read(output)), records)
        meta = json.loads((output.parent / 'parts.meta.json').read_text())
        self.assertEqual(sum(p['rows'] for p in meta['parts']), 10)


class AuthorKeyTests(unittest.TestCase):
    def test_keys_depend_on_the_secret_and_the_secret_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            one, two = Path(temp) / 'one', Path(temp) / 'two'
            create_secret(one)
            create_secret(two)
            self.assertEqual(one.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                create_secret(one)
            a, b = AuthorKeys(one), AuthorKeys(two)
            self.assertEqual(a.key('x@example.test'), a.key('x@example.test'))
            self.assertNotEqual(a.key('x@example.test'), a.key('y@example.test'))
            self.assertNotEqual(a.key('x@example.test'), b.key('x@example.test'))
            self.assertEqual(len(a.key_id), 16)


if __name__ == '__main__':
    unittest.main()
