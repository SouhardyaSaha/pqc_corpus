from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from pqc_corpus.filters.commits import filter_commits
from pqc_corpus.filters.commits.facts import Commit, is_bot
from pqc_corpus.filters.commits.steps import run
from pqc_corpus.filters.issues import filter_issues
from pqc_corpus.filters.terms import SCHEME_NAMES, mentions_pqc, pqc_named_repository

BASE = Commit(repo='o/r', sha='0', subject='Change', is_merge=False, parents=('p',), on_default_branch=True,
              in_merged_pr=False, change_signature=None, paths=('src/a.c',), is_bot=False, in_fork=False,
              pqc_named_repository=True, pqc_in_text=False, pqc_in_paths=False, pqc_in_changed_lines=False,
              pqc_in_diff=False, patch_id=None, content_hash=None)


def commit(sha: str, **changes) -> Commit:
    return replace(BASE, sha=sha, **changes)


def removed_by(commits: list[Commit]) -> dict[str, str]:
    results, _ = run(commits)
    return {r.sha: name for name, removals in results for r in removals}


class TermTests(unittest.TestCase):
    def test_every_scheme_name_matches(self) -> None:
        for name in SCHEME_NAMES:
            with self.subTest(name=name):
                self.assertTrue(mentions_pqc(f'Add {name} support'))

    def test_ordinary_words_and_identifiers_do_not_match(self) -> None:
        self.assertFalse(mentions_pqc('use less memory and cross-compile untrusted code'))
        self.assertTrue(mentions_pqc('X25519MLKEM768 and falcon-512'))
        self.assertTrue(pqc_named_repository('o/lattice-tools', '', []))
        self.assertFalse(pqc_named_repository('o/tls', 'A TLS library', ['networking']))


class CommitStepTests(unittest.TestCase):
    def test_eligibility_keeps_default_branch_or_merged_pr(self) -> None:
        removed = removed_by([commit('main'), commit('pr', on_default_branch=False, in_merged_pr=True),
                              commit('side', on_default_branch=False)])
        self.assertEqual(removed, {'side': 'eligibility'})

    def test_rebased_copy_needs_same_signature_same_content_and_one_copy_on_main(self) -> None:
        same = {'change_signature': ('m', 'author', 't', ()), 'content_hash': 'h'}
        removed = removed_by([commit('kept', **same),
                              commit('copy', on_default_branch=False, in_merged_pr=True, **same),
                              commit('other', on_default_branch=False, in_merged_pr=True,
                                     change_signature=same['change_signature'], content_hash='different')])
        self.assertEqual(removed, {'copy': 'rebased_copies'})

    def test_duplicates_merges_and_squash_copies(self) -> None:
        removed = removed_by([
            commit('single', patch_id='x'),
            commit('merge', is_merge=True, parents=('p', 'single'), patch_id='x'),
            commit('squashed', subject='Fix (#7)', patch_id='y'),
            commit('original', subject='Fix', patch_id='y', on_default_branch=False, in_merged_pr=True),
            commit('tip'),
            commit('merge2', is_merge=True, parents=('p', 'tip'), patch_id='z'),
        ])
        self.assertEqual(removed, {'merge': 'merge_repeats', 'original': 'squash_copies',
                                   'merge2': 'merge_commits'})

    def test_keyword_steps_never_remove_a_commit_mentioning_pqc(self) -> None:
        removed = removed_by([
            commit('fork', in_fork=True),
            commit('fork-pqc', in_fork=True, pqc_in_changed_lines=True),
            commit('general', pqc_named_repository=False),
            commit('general-pqc', pqc_named_repository=False, pqc_in_text=True),
            commit('ci', paths=('.github/workflows/ci.yml',)),
            commit('ci-pqc', paths=('.github/workflows/ci.yml',), pqc_in_diff=True),
            commit('empty', paths=()),
            commit('bot', is_bot=True),
            commit('code'),
        ])
        self.assertEqual(removed, {'fork': 'fork_history', 'general': 'general_libraries',
                                   'ci': 'housekeeping', 'empty': 'housekeeping', 'bot': 'housekeeping'})

    def test_bot_names(self) -> None:
        self.assertTrue(is_bot('dependabot[bot]'))
        self.assertTrue(is_bot('release-bot'))
        self.assertFalse(is_bot('Abbott'))


def mined_commit(sha: str, message: str, path: str, patch: str, prs: list[int], **changes) -> dict:
    record = {'repo': 'o/r', 'corpus': 'A', 'sha': sha, 'message': message, 'author_name': 'A',
              'author_key': 'e', 'pqc_in_linked_text': False, 'authored_at': '2024-01-01T00:00:00Z', 'committer_name': 'A', 'committed_at': '2024-01-01T00:00:00Z',
              'parents': ['p'], 'pr_numbers': prs, 'on_default_branch': True, 'in_merged_pr': bool(prs),
              'changed_files': [{'path': path, 'status': 'M', 'additions': 1, 'deletions': 0, 'binary': False}],
              'patch_encoding': 'utf-8', 'patch_content': patch}
    return {**record, **changes}


def write_lines(path: Path, records: list[dict]) -> None:
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))


class FilterCommandTests(unittest.TestCase):
    def test_commit_filter_uses_linked_text_and_copies_lines_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_lines(root / 'repositories.jsonl', [{'repo': 'o/r', 'is_fork': False, 'description': 'TLS',
                                                       'topics': []}])
            commits = [mined_commit('a', 'Refactor', 'src/x.c', '+x\n', [5], pqc_in_linked_text=True),
                       mined_commit('b', 'Refactor', 'src/y.c', '+y\n', []),
                       mined_commit('c', 'Draft', 'src/z.c', '+mlkem\n', [], on_default_branch=False,
                                    pqc_in_linked_text=None)]
            write_lines(root / 'commits.jsonl', commits)
            summary = filter_commits(root / 'commits.jsonl', root / 'repositories.jsonl',
                                     root / 'filtered.jsonl', root / 'report', workers=2)
            sequential = filter_commits(root / 'commits.jsonl', root / 'repositories.jsonl',
                                        root / 'filtered_1.jsonl', root / 'report_1', workers=1)
            self.assertEqual(sequential['steps'], summary['steps'])
            lines = (root / 'filtered.jsonl').read_text().splitlines()
            self.assertEqual(lines, [json.dumps(commits[0])])
            self.assertEqual((summary['mined'], summary['filtered']), (3, 1))
            self.assertEqual([s['removed'] for s in summary['steps']], [1, 0, 0, 0, 0, 0, 1, 0])
            self.assertTrue((root / 'report' / '07_general_libraries.csv').exists())
            with self.assertRaises(ValueError):
                filter_commits(root / 'commits.jsonl', root / 'repositories.jsonl',
                               root / 'filtered.jsonl', root / 'report')

    def test_issue_filter_removes_bot_authored_issues(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            issues = [{'repo': 'o/r', 'number': 1, 'author': 'alice', 'url': 'u1'},
                      {'repo': 'o/r', 'number': 2, 'author': 'github-actions[bot]', 'url': 'u2'},
                      {'repo': 'o/r', 'number': 3, 'author': None, 'url': 'u3'}]
            write_lines(root / 'issues.jsonl', issues)
            summary = filter_issues(root / 'issues.jsonl', root / 'filtered.jsonl', root / 'report')
            kept = [json.loads(line)['number'] for line in (root / 'filtered.jsonl').read_text().splitlines()]
            self.assertEqual(kept, [1, 3])
            self.assertEqual((summary['mined'], summary['filtered']), (3, 2))


if __name__ == '__main__':
    unittest.main()
