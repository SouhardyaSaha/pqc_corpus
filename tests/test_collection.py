import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from pqc_corpus.collection import eligibility
from pqc_corpus.collection.commit_selection import message_pattern
from pqc_corpus.collection.linked_commits import linked_metadata
from pqc_corpus.collection.prepare import prepare
from pqc_corpus.common import read_json
from pqc_corpus.paths import CONFIG_DIRECTORY, PROJECT_ROOT

from fixtures import REPO, make_run


class FakeGraphQL:
    """Canned `associatedPullRequests` answers; records how many queries were made."""

    def __init__(self, prs: dict[str, list[dict]]) -> None:
        self.prs = prs
        self.queries = 0

    def query(self, text: str, variables: dict) -> dict:
        self.queries += 1
        found = {}
        for key, sha in variables.items():
            if key.startswith('sha'):
                nodes = self.prs.get(sha)
                found['c' + key[3:]] = None if nodes is None else {
                    'associatedPullRequests': {'nodes': nodes, 'pageInfo': {'hasNextPage': False}}}
        return {'repository': found}


class ConfigTests(unittest.TestCase):
    def test_frozen_inputs(self) -> None:
        repositories = read_json(CONFIG_DIRECTORY / 'repositories.json')['repositories']
        self.assertEqual(len(repositories), 179)
        policy = read_json(CONFIG_DIRECTORY / 'corpus_policy.json')
        self.assertEqual((len(policy['terms']), policy['cutoff']), (90, 0.148))
        self.assertFalse(set(policy['terms']) & set(policy['excluded_terms']))
        matcher = message_pattern(policy['terms'])
        self.assertTrue(matcher.search('Implement ML-KEM support'))
        self.assertFalse(matcher.search('A bike ride with a falcon'))
        self.assertFalse(matcher.search('unrelatedPQCword'))

    def test_prepare_freezes_a_new_run_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / 'run'
            prepare(run)
            manifest = read_json(run / 'manifest.json')
            self.assertEqual(len(manifest['repositories']), 179)
            self.assertEqual(len(manifest['tiering']['policy_sha256']), 64)
            with self.assertRaises(ValueError):
                prepare(run)


class EligibilityTests(unittest.TestCase):
    def test_observe_default_branch_and_merged_prs_of_the_same_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run, shas = make_run(Path(temp))
            client = FakeGraphQL({
                shas['feature']: [{'number': 4, 'merged': True, 'title': 'Notes', 'body': None,
                                   'repository': {'nameWithOwner': 'Fixture/Project'},
                                   'closingIssuesReferences': {'nodes': [{'title': 'Add ML-KEM', 'body': ''}]}}],
                shas['unmerged']: [{'number': 6, 'merged': False, 'title': 'Draft', 'body': 'post-quantum',
                                    'repository': {'nameWithOwner': REPO}, 'closingIssuesReferences': None},
                                   {'number': 9, 'merged': True, 'title': 'Kyber', 'body': None,
                                    'repository': {'nameWithOwner': 'other/fork'}}],
            })
            self.assertEqual(eligibility.observe(run, client), 1)
            self.assertEqual(eligibility.observe(run, client), 0)
            self.assertEqual(client.queries, 1)
            observed = eligibility.load(run / 'eligibility.sqlite')
            self.assertEqual(observed[(REPO, shas['feature'])], (True, True, True))
            self.assertEqual(observed[(REPO, shas['unmerged'])], (False, False, True))
            self.assertEqual(observed[(REPO, shas['root'])], (True, False, False))

    def test_load_recorded_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'eligibility.jsonl'
            path.write_text(json.dumps({'repo': 'o/r', 'sha': 'a', 'on_default_branch': False,
                                        'in_merged_pr': True, 'pqc_in_linked_text': None}) + '\n')
            self.assertEqual(eligibility.load(path), {('o/r', 'a'): (False, True, None)})


class GitTests(unittest.TestCase):
    def test_linked_commit_can_be_read_without_changing_frozen_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            mirror = run / 'mirrors/a__b.git'
            mirror.mkdir(parents=True)

            def git(*args: str) -> str:
                return subprocess.check_output(['git', '-C', str(mirror), *args],
                                               stderr=subprocess.DEVNULL, text=True).strip()

            git('init')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.test',
                'commit', '--allow-empty', '-m', 'ordinary change')
            sha = git('rev-parse', 'HEAD')
            before = git('show-ref')
            row = linked_metadata(run, 'a/b', sha)
            self.assertEqual((row['sha'], row['message'], row['parents'], row['is_merge']),
                             (sha, 'ordinary change', [], False))
            self.assertEqual(git('show-ref'), before)

    @unittest.skipUnless(importlib.util.find_spec('pydriller'), 'PyDriller is not installed')
    def test_git_worker_keeps_branches_merges_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, _ = make_run(root)
            source_run = root / 'source_run'
            (source_run / 'mirrors').mkdir(parents=True)
            subprocess.run(['git', 'clone', '--mirror', str(root / 'source'),
                            str(source_run / 'mirrors' / 'fixture__project.git')], check=True, capture_output=True)
            (source_run / 'manifest.json').write_text(json.dumps({'repositories': [{'repo': REPO}]}))
            command = [sys.executable, '-m', 'pqc_corpus.collection.git_history', '--run-dir', str(source_run),
                       '--min-free-gib', '0']
            for _ in range(2):
                result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            db = sqlite3.connect(source_run / 'git.sqlite')
            self.assertEqual(db.execute('SELECT count(*) FROM commits').fetchone()[0], 5)
            self.assertEqual(db.execute("SELECT count(*) FROM commits WHERE json_extract(data,'$.is_merge')=1")
                             .fetchone()[0], 1)
            db.close()
            self.assertEqual(read_json(source_run / 'git_status.json')['status'], 'completed')


class CommandTests(unittest.TestCase):
    def test_help_and_no_collect_refuse_an_unfinished_run(self) -> None:
        result = subprocess.run([sys.executable, '-m', 'pqc_corpus', 'commits', 'mine', '--help'],
                                cwd=PROJECT_ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--no-collect', result.stdout)
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, '-m', 'pqc_corpus', 'issues', 'mine', '--run-dir', temp,
                                     '--output', str(Path(temp) / 'issues.jsonl'), '--no-collect'],
                                    cwd=PROJECT_ROOT, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not a finished run', result.stderr)


if __name__ == '__main__':
    unittest.main()
