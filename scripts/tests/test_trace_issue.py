"""Offline checks for reuse/trace_issue.py on small fixtures; stdlib only."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'reuse' / 'trace_issue.py'
spec = importlib.util.spec_from_file_location('trace_issue', SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
REPO = 'RustCrypto/KEMs'
SHAS = [str(number) * 40 for number in range(1, 6)]


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def fixture(root):
    issue = {'repo': REPO, 'corpus': 'A', 'number': 46,
             'url': f'https://github.com/{REPO}/issues/46', 'title': 'Update to FIPS 203',
             'state': 'closed', 'comments': [{}] * 5,
             'closed_by_prs': [{'repo': REPO, 'number': 47}]}
    pr = {'repo': REPO, 'corpus': 'A', 'number': 47,
          'url': f'https://github.com/{REPO}/pull/47', 'title': 'Implement final standard',
          'merged': True, 'comments': [{}] * 6, 'reviews': [{}], 'review_comments': [],
          'commit_shas': SHAS}
    rows, patches = [], {}
    for number, sha in enumerate(SHAS):
        patch = ('diff --git a/kem.c b/kem.c\n+é\\quoted "text"\t🦉\n' * (50000 if number == 4 else 1)).encode()
        if number == 2:
            patch = b'diff --git a/legacy.c b/legacy.c\n+caf\xe9\n'
        patches[sha] = patch
        try:
            content, encoding = patch.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError:
            content, encoding = base64.b64encode(patch).decode(), 'base64'
        rows.append({'repo': REPO, 'corpus': 'A', 'sha': sha,
                     'url': f'https://github.com/{REPO}/commit/{sha}', 'message': 'Update\nFull body',
                     'changed_files': [{'path': f'ml-kem/file-{number}.rs'}],
                     'lines_added': 1, 'lines_deleted': 0, 'patch_encoding': encoding,
                     'patch_content': content, 'fetched_at': '2026-09-21T00:00:00Z'})
    write_rows(root / 'issues.jsonl', [issue])
    write_rows(root / 'pull_requests.jsonl', [pr])
    full = root / 'commits' / 'part-00000.jsonl'
    full.parent.mkdir()
    # A large irrelevant line must never be passed to json.loads or retained.
    with full.open('wb') as stream:
        stream.write(b'{"repo":"AAA/noise","corpus":"A","sha":"noise","patch_content":"')
        for _ in range(256):
            stream.write(b'x' * (64 * 1024))
        stream.write(b'"}\n')
        for row in rows:
            stream.write((json.dumps(row, ensure_ascii=False) + '\n').encode())
    write_rows(root / 'commits_filtered' / 'part-00000.jsonl', rows[:3])
    return rows, patches


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='trace-fixture-', dir=HERE)
        self.root = Path(self.temp.name)
        self.rows, self.patches = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_full_trace_bounds_memory_and_preserves_patch_hashes(self):
        tracemalloc.start()
        result = demo.trace(self.root, REPO, 46)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLess(peak, 2 * 1024 * 1024)
        self.assertEqual(result['issue']['comments'], 5)
        pr, = result['pull_requests']
        self.assertEqual((pr['number'], pr['linked_commits'], pr['present_commits']), (47, 5, 5))
        self.assertEqual((pr['comments'], pr['reviews'], pr['inline_comments']), (6, 1, 0))
        for commit in pr['commits']:
            patch = self.patches[commit['sha']]
            self.assertEqual(commit['patch']['sha256'], hashlib.sha256(patch).hexdigest())
            self.assertEqual(commit['patch']['bytes'], len(patch))
            self.assertNotIn('patch_content', commit)
            self.assertEqual(len(commit['changed_paths']), 1)
            self.assertEqual(commit['source']['file'], 'commits/part-00000.jsonl')
        self.assertEqual(result['missing_commits'], [])
        print(f'Bounded-reader peak traced allocation: {peak:,} bytes')

    def test_filtered_view_reports_each_missing_sha(self):
        result = demo.trace(self.root, REPO, 46, filtered=True)
        self.assertEqual(result['pull_requests'][0]['present_commits'], 3)
        self.assertEqual([item['sha'] for item in result['missing_commits']], SHAS[3:])
        self.assertTrue(all(item['absent_from'] == 'commits_filtered' for item in result['missing_commits']))

    def test_missing_links_are_reported_and_unordered_shards_are_scanned(self):
        issue = json.loads((self.root / 'issues.jsonl').read_text())
        issue['closed_by_prs'].append({'repo': 'external/project', 'number': 99})
        write_rows(self.root / 'issues.jsonl', [issue])
        # Later shards can revisit a repository, so the reader must not stop early.
        write_rows(self.root / 'commits_filtered' / 'part-00001.jsonl', [
            {**self.rows[0], 'repo': 'ZZZ/later', 'sha': 'other'}, self.rows[3]])
        result = demo.trace(self.root, REPO, 46, filtered=True)
        self.assertEqual(result['missing_pull_requests'], [{'repo': 'external/project', 'number': 99}])
        self.assertEqual(result['pull_requests'][0]['present_commits'], 4)
        self.assertEqual(result['missing_commits'][0]['sha'], SHAS[4])
        self.assertIsNone(demo.trace(self.root, REPO, 999)['issue'])

    def test_json_escape_boundaries_and_cli_output(self):
        raw = 'é🦉\\"\n\t\u0000'.encode()
        encoded = json.dumps(raw.decode(), ensure_ascii=True).encode()[1:]
        digest = demo.PatchDigest('utf-8')
        for byte in encoded:
            digest.feed(bytes([byte]))
        self.assertEqual(digest.summary()['sha256'], hashlib.sha256(raw).hexdigest())
        output = self.root / 'trace.json'
        run = subprocess.run([sys.executable, '-B', str(SCRIPT), '--data', str(self.root),
                              '--repo', REPO, '--issue', '46', '--filtered', '--output', str(output)],
                             text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(output.read_text())['pull_requests'][0]['linked_commits'], 5)

    def test_incomplete_download_is_not_reported_as_missing_link(self):
        manifest = {'datasets': {'issues': {'files': [
            {'path': 'issues.jsonl', 'bytes': (self.root / 'issues.jsonl').stat().st_size + 1}]}}}
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Download incomplete'):
            demo.trace(self.root, REPO, 46)


if __name__ == '__main__':
    unittest.main(verbosity=2)
