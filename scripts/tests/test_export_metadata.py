#!/usr/bin/env python3
"""Offline fixtures for the patch-free derivative, including bounded memory."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reuse'))
import export_metadata as exporter
import trace_issue


class ExportFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'source.jsonl'

    def record(self, patch, encoding='utf-8'):
        return {'repo': 'fixture/project', 'corpus': 'B', 'sha': 'a' * 40,
                'message': 'Keep this message', 'parents': ['b' * 40],
                'pr_numbers': [9], 'changed_files': [{'path': 'src/fixture.go', 'additions': 2}],
                'patch_encoding': encoding, 'patch_content': patch,
                'on_default_branch': True, 'in_merged_pr': False,
                'pqc_in_linked_text': None, 'extra_future_field': {'keep': [None, False, 4]}}

    def read(self):
        digest = hashlib.sha256()
        records = list(exporter.metadata_records(self.path, 'commits/part-00000.jsonl', 'fixture-sha', digest))
        self.assertEqual(digest.hexdigest(), hashlib.sha256(self.path.read_bytes()).hexdigest())
        return records

    def test_utf8_all_remaining_fields_and_exact_patch_descriptor(self):
        patch = 'diff \\ literal\\ud800 quote"\nemoji🙂 tab\t é\n'
        original = self.record(patch)
        raw = (json.dumps(original, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
        self.path.write_bytes(raw)
        old_chunk = trace_issue.CHUNK
        try:
            trace_issue.CHUNK = 7
            row, = self.read()
        finally:
            trace_issue.CHUNK = old_chunk
        self.assertEqual({k: v for k, v in row.items() if k not in ('_patch', '_source')},
                         {k: v for k, v in original.items() if k != 'patch_content'})
        self.assertEqual(row['_patch']['sha256'], hashlib.sha256(patch.encode()).hexdigest())
        self.assertEqual(row['_patch']['bytes'], len(patch.encode()))
        self.assertEqual(row['_patch']['json_string_content_bytes'], len(json.dumps(patch).encode()) - 2)
        self.assertEqual(row['_source']['record_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(row['_source']['record_bytes'], len(raw))

    def test_base64_hash_is_original_git_bytes(self):
        original_bytes = b'\xff\x00binary\n\xfe'
        row = self.record(base64.b64encode(original_bytes).decode(), 'base64')
        self.path.write_text(json.dumps(row, separators=(',', ':')) + '\n')
        metadata, = self.read()
        self.assertEqual(metadata['_patch']['bytes'], len(original_bytes))
        self.assertEqual(metadata['_patch']['sha256'], hashlib.sha256(original_bytes).hexdigest())

    def test_empty_patch_and_final_line_without_newline_have_exact_offsets(self):
        a = (json.dumps(self.record(''), separators=(',', ':')) + '\n').encode()
        b = json.dumps(self.record('second'), separators=(',', ':')).encode()
        self.path.write_bytes(a + b)
        first, second = self.read()
        self.assertEqual(first['_patch']['bytes'], 0)
        self.assertEqual(second['_source']['line'], 2)
        self.assertEqual(second['_source']['byte_offset'], len(a))
        self.assertEqual(second['_source']['record_bytes'], len(b))

    def test_descriptor_collision_fails_instead_of_dropping_existing_field(self):
        row = self.record('patch')
        row['_patch'] = 'existing value'
        self.path.write_text(json.dumps(row, separators=(',', ':')) + '\n')
        with self.assertRaisesRegex(ValueError, 'collides'):
            self.read()

    def test_unterminated_patch_fails(self):
        self.path.write_bytes(b'{"repo":"fixture/project","patch_encoding":"utf-8","patch_content":"broken')
        with self.assertRaises(ValueError):
            self.read()

    def test_padding_is_sticky_across_empty_decoded_fragments(self):
        patch = trace_issue.PatchDigest('base64')
        patch.feed(b'Zg==')
        with self.assertRaisesRegex(ValueError, 'padding'):
            patch.feed(b'\\u005ag=="')

    def test_malformed_utf8_patch_is_rejected_at_any_boundary(self):
        for content in (b'\xff', b'\xe2\x82', b'\xc0\xaf'):
            for chunk in (1, 7):
                with self.subTest(content=content, chunk=chunk):
                    patch = trace_issue.PatchDigest('utf-8')
                    with self.assertRaises(UnicodeError):
                        raw = content + b'"'
                        for i in range(0, len(raw), chunk):
                            patch.feed(raw[i:i + chunk])

    def test_literal_utf8_across_fragment_boundaries(self):
        patch = trace_issue.PatchDigest('utf-8')
        raw = 'é🙂'.encode()
        for byte in raw + b'"':
            patch.feed(bytes([byte]))
        self.assertEqual(patch.summary()['sha256'], hashlib.sha256(raw).hexdigest())

    def test_unicode_escape_rejects_signs_and_whitespace(self):
        for raw in (b'\\u+041"', b'\\u 041"', b'\\ud800\\u+041"'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'Unicode escape'):
                trace_issue.PatchDigest('utf-8').feed(raw)

    def test_duplicate_keys_rejected_including_second_patch(self):
        for extra in (b',"patch_content":"second"', b',"repo":"changed"',
                      b',"nested":{"x":1,"x":2}'):
            self.path.write_bytes(b'{"repo":"fixture/project","patch_encoding":"utf-8",'
                                  b'"patch_content":"first"' + extra + b'}\n')
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'Duplicate'):
                self.read()

    def test_path_confinement_and_duplicate_destinations(self):
        root = Path(self.temporary.name).resolve()
        inside = root / 'inside'
        inside.mkdir()
        (inside / 'escape').symlink_to(root, target_is_directory=True)
        for path in ('../escape', '/absolute', 'a/../../b', './alias', 'a//alias',
                     'escape/source.jsonl', 'windows\\path', 'new\nline'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                exporter.confined(inside, path)
        self.path.write_bytes(b'{}\n')
        manifest = {'datasets': {name: {'files': []} for name in exporter.TABLES}}
        manifest['datasets']['issues']['files'] = [{'path': 'source.jsonl'}] * 2
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            exporter.validate_paths(root, root / 'output', manifest)

    def test_completion_marker_requires_files_and_binds_checksums(self):
        output = Path(self.temporary.name) / 'output'
        output.mkdir()
        with self.assertRaisesRegex(ValueError, 'required'):
            exporter.finalize_output(output)
        self.assertFalse((output / 'COMPLETE.json').exists())
        for name, content in {'manifest.json': '{"datasets":{}}', 'source-manifest.json': '{}',
                              'progress.json': '{"status":"data-exported"}', 'README.txt': 'fixture'}.items():
            (output / name).write_text(content)
        exporter.finalize_output(output)
        marker = json.loads((output / 'COMPLETE.json').read_text())
        self.assertEqual(marker['status'], 'complete')
        self.assertEqual(marker['sha256sums_sha256'], exporter.hash_file(output / 'SHA256SUMS'))
        self.assertEqual(marker['checked_files'], 4)
        self.assertNotIn('COMPLETE.json', (output / 'SHA256SUMS').read_text())

    def test_finalization_rejects_data_changed_after_export(self):
        output = Path(self.temporary.name) / 'output'
        output.mkdir()
        for name in ['source-manifest.json', 'progress.json', 'schema.json']:
            (output / name).write_text('{}')
        (output / 'README.txt').write_text('fixture')
        (output / 'data.jsonl').write_bytes(b'tampered\n')
        exporter.write_json(output / 'manifest.json', {'datasets': {'fixture': {
            'schema': 'schema.json', 'files': [{'path': 'data.jsonl', 'bytes': 3,
                                               'sha256': hashlib.sha256(b'{}\n').hexdigest()}]}}})
        with self.assertRaisesRegex(ValueError, 'differs'):
            exporter.finalize_output(output)
        self.assertFalse((output / 'COMPLETE.json').exists())

    def test_large_patch_does_not_materialize_patch_in_memory(self):
        size = 12 * 1024 * 1024
        block = b'a' * (64 * 1024)
        with self.path.open('wb') as out:
            out.write(b'{"repo":"fixture/project","corpus":"B","sha":"a","patch_encoding":"utf-8","patch_content":"')
            for _ in range(size // len(block)):
                out.write(block)
            out.write(b'","message":"retained"}\n')
        tracemalloc.start()
        rows = list(exporter.metadata_records(self.path, 'fixture.jsonl', 'fixture', hashlib.sha256()))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(rows[0]['_patch']['bytes'], size)
        self.assertEqual(rows[0]['message'], 'retained')
        self.assertLess(peak, 2 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main(verbosity=2)
