#!/usr/bin/env python3
"""Trace an issue through its closing PRs to their commits and patches."""

import argparse
import base64
import codecs
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys


CHUNK = 64 * 1024
MAX_METADATA = 64 * 1024 * 1024
STRING = rb'"(?:[^"\\]|\\.)*"'
IDENTITY = re.compile(
    rb'^\s*\{\s*"repo"\s*:\s*(' + STRING + rb')\s*,\s*"corpus"\s*:\s*'
    + STRING + rb'\s*,\s*"(sha|number)"\s*:\s*(' + STRING + rb'|-?\d+)\s*[,}]'
)
PATCH_START = re.compile(rb',\s*"patch_content"\s*:\s*"')
SPECIAL = re.compile(rb'["\\\x00-\x1f]')
ESCAPES = {ord('"'): b'"', ord('\\'): b'\\', ord('/'): b'/',
           ord('b'): b'\b', ord('f'): b'\f', ord('n'): b'\n',
           ord('r'): b'\r', ord('t'): b'\t'}


def unique_object(pairs):
    """Reject ambiguous objects instead of accepting the last duplicate key."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON object key: {key!r}')
        result[key] = value
    return result


def strict_json(data):
    return json.loads(data, object_pairs_hook=unique_object)


class PatchDigest:
    """Incrementally decode one JSON string and hash the original Git patch bytes."""

    def __init__(self, encoding):
        if encoding not in ('utf-8', 'base64'):
            raise ValueError(f'Unsupported patch encoding: {encoding!r}')
        self.encoding = encoding
        self.pending = b''
        self.base64_tail = b''
        self.base64_ended = False
        self.digest = hashlib.sha256()
        self.size = 0
        self.finished = False
        self.utf8 = codecs.getincrementaldecoder('utf-8')('strict')

    def decoded(self, data):
        # Validate JSON string text across arbitrary UTF-8 fragment boundaries.
        self.utf8.decode(data, final=False)
        if self.encoding == 'base64':
            if self.base64_ended and data:
                raise ValueError('Data follows base64 padding')
            data = self.base64_tail + data
            length = len(data) // 4 * 4
            encoded, self.base64_tail = data[:length], data[length:]
            self.base64_ended = self.base64_ended or b'=' in encoded
            data = base64.b64decode(encoded, validate=True)
        self.digest.update(data)
        self.size += len(data)

    def feed(self, fragment):
        """Return bytes after the closing quote, or None while inside the string."""
        data = self.pending + fragment
        self.pending = b''
        position = 0
        while position < len(data):
            match = SPECIAL.search(data, position)
            if match is None:
                self.decoded(data[position:])
                return None
            self.decoded(data[position:match.start()])
            position = match.start()
            char = data[position]
            if char == ord('"'):
                self.utf8.decode(b'', final=True)
                if self.base64_tail:
                    raise ValueError('Incomplete base64 patch')
                self.finished = True
                return data[position + 1:]
            if char != ord('\\'):
                raise ValueError('Unescaped control character in patch JSON')
            if len(data) - position < 2:
                break
            escape = data[position + 1]
            if escape in ESCAPES:
                self.decoded(ESCAPES[escape])
                position += 2
                continue
            if escape != ord('u'):
                raise ValueError('Invalid JSON escape in patch')
            if len(data) - position < 6:
                break
            if not re.fullmatch(rb'[0-9a-fA-F]{4}', data[position + 2:position + 6]):
                raise ValueError('Invalid Unicode escape in patch')
            code = int(data[position + 2:position + 6], 16)
            consumed = 6
            if 0xD800 <= code <= 0xDBFF:
                if len(data) - position < 12:
                    break
                if data[position + 6:position + 8] != b'\\u':
                    raise ValueError('Unpaired Unicode surrogate in patch')
                if not re.fullmatch(rb'[0-9a-fA-F]{4}', data[position + 8:position + 12]):
                    raise ValueError('Invalid Unicode escape in patch')
                low = int(data[position + 8:position + 12], 16)
                if not 0xDC00 <= low <= 0xDFFF:
                    raise ValueError('Unpaired Unicode surrogate in patch')
                code = 0x10000 + ((code - 0xD800) << 10) + low - 0xDC00
                consumed = 12
            self.decoded(chr(code).encode('utf-8'))
            position += consumed
        self.pending = data[position:]
        return None

    def summary(self):
        if not self.finished:
            raise ValueError('Unterminated patch_content string')
        return {'encoding': self.encoding, 'bytes': self.size,
                'sha256': self.digest.hexdigest()}


class SelectedRecord:
    def __init__(self, commit):
        self.commit = commit
        self.metadata = bytearray()
        self.patch = None

    def feed(self, fragment):
        if self.patch is not None and not self.patch.finished:
            tail = self.patch.feed(fragment)
            if tail is not None:
                self.metadata.extend(tail)
        else:
            self.metadata.extend(fragment)
            if self.commit and self.patch is None:
                match = PATCH_START.search(self.metadata)
                if match:
                    # Keep the complete JSON object, replacing only the large value.
                    prefix = bytes(self.metadata[:match.end() - 1])
                    before = strict_json(prefix + b'null}')
                    self.patch = PatchDigest(before['patch_encoding'])
                    content = bytes(self.metadata[match.end():])
                    self.metadata = bytearray(prefix + b'""')
                    tail = self.patch.feed(content)
                    if tail is not None:
                        self.metadata.extend(tail)
        if len(self.metadata) > MAX_METADATA:
            raise ValueError('Selected record metadata exceeds 64 MiB')

    def finish(self):
        record = strict_json(self.metadata)
        if self.commit:
            if self.patch is None:
                raise ValueError('Commit record has no patch_content field')
            record['_patch'] = self.patch.summary()
            record.pop('patch_content')
        return record


def fragments(path):
    """Yield (fragment, end_of_line), never allocating a complete large line."""
    with path.open('rb') as stream:
        while block := stream.read(CHUNK):
            start = 0
            while (end := block.find(b'\n', start)) >= 0:
                yield block[start:end], True
                start = end + 1
            if start < len(block):
                yield block[start:], False


def read_records(path, targets, commit=False):
    """Find requested composite keys; skip all other line bodies before JSON parsing."""
    if not targets:
        return {}
    expected = sum(len(identities) for identities in targets.values())
    paths = sorted(path.glob('part-*.jsonl')) if path.is_dir() else [path]
    if not paths or any(not item.is_file() for item in paths):
        raise FileNotFoundError(f'Missing JSONL data: {path}')
    found = {}
    for part in paths:
        prefix = bytearray()
        decided = False
        capture = None
        key = None
        line = 1

        def finish():
            if capture is not None:
                if key in found:
                    raise ValueError(f'Duplicate record key: {key}')
                record = capture.finish()
                record['_source'] = {'file': part.relative_to(path.parent).as_posix(), 'line': line}
                found[key] = record
            elif not decided and prefix.strip():
                raise ValueError(f'{part}:{line}: expected repo, corpus, sha/number field order')

        for fragment, ended in fragments(part):
            if not decided:
                prefix.extend(fragment)
                match = IDENTITY.match(prefix)
                if match:
                    repo = json.loads(match.group(1))
                    identity = json.loads(match.group(3))
                    key = (repo, identity)
                    decided = True
                    if identity in targets.get(repo, set()):
                        capture = SelectedRecord(commit)
                        capture.feed(prefix)
                    prefix.clear()
                elif len(prefix) > CHUNK:
                    raise ValueError(f'{part}:{line}: identity not found within 64 KiB')
            elif capture is not None:
                capture.feed(fragment)
            if ended:
                finish()
                if len(found) == expected:
                    return found
                prefix.clear()
                decided, capture, key = False, None, None
                line += 1
        # JSONL readers may also accept a final record without its trailing newline.
        if decided or prefix:
            finish()
    return found


def data_path(directory, name):
    manifest = directory / 'manifest.json'
    if manifest.is_file():
        declared = json.loads(manifest.read_text(encoding='utf-8'))['datasets'][name]
        for item in declared['files']:
            file = directory / item['path']
            if not file.is_file() or file.stat().st_size != item['bytes']:
                raise ValueError(f'Download incomplete: {file}; expected {item["bytes"]:,} bytes. '
                                 'Finish downloading the release before tracing links.')
    for candidate in (directory / name, directory / (name + '.jsonl')):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f'No {name}/ or {name}.jsonl in {directory}')


def commit_summary(record):
    return {'sha': record['sha'], 'url': record['url'],
            'subject': (record.get('message') or '').split('\n', 1)[0],
            'changed_paths': [item['path'] for item in record['changed_files']],
            'lines_added': record['lines_added'], 'lines_deleted': record['lines_deleted'],
            'patch': record['_patch'], 'source': record['_source']}


def trace(directory, repo, number, filtered=False):
    view = 'commits_filtered' if filtered else 'commits'
    result = {'repo': repo, 'issue_number': number, 'commit_view': view,
              'issue': None, 'pull_requests': [], 'missing_pull_requests': [],
              'missing_commits': []}
    issues = read_records(data_path(directory, 'issues'), {repo: {number}})
    issue = issues.get((repo, number))
    if issue is None:
        result['note'] = 'Requested issue is absent from the collected issue file.'
        return result
    result['issue'] = {key: issue[key] for key in ('url', 'title', 'state')}
    result['issue']['comments'] = len(issue['comments'])
    wanted_prs = defaultdict(set)
    for link in issue['closed_by_prs']:
        wanted_prs[link['repo']].add(link['number'])
    prs = read_records(data_path(directory, 'pull_requests'), wanted_prs)
    wanted_commits = defaultdict(set)
    for pr in prs.values():
        wanted_commits[pr['repo']].update(pr['commit_shas'])
    commits = read_records(data_path(directory, view), wanted_commits, commit=True)
    for pr_repo, numbers in sorted(wanted_prs.items()):
        for pr_number in sorted(numbers):
            pr = prs.get((pr_repo, pr_number))
            if pr is None:
                result['missing_pull_requests'].append({'repo': pr_repo, 'number': pr_number})
                continue
            linked = [commits[(pr_repo, sha)] for sha in pr['commit_shas'] if (pr_repo, sha) in commits]
            missing = [sha for sha in pr['commit_shas'] if (pr_repo, sha) not in commits]
            result['pull_requests'].append({
                'repo': pr_repo, 'number': pr_number, 'url': pr['url'], 'title': pr['title'],
                'merged': pr['merged'], 'comments': len(pr['comments']),
                'reviews': len(pr['reviews']), 'inline_comments': len(pr['review_comments']),
                'linked_commits': len(pr['commit_shas']), 'present_commits': len(linked),
                'commits': [commit_summary(record) for record in linked],
            })
            for sha in missing:
                item = {'repo': pr_repo, 'sha': sha, 'absent_from': view}
                if item not in result['missing_commits']:
                    result['missing_commits'].append(item)
    if not wanted_prs:
        result['note'] = 'No closing PR link is recorded; other implementation links may exist.'
    elif result['missing_pull_requests'] or result['missing_commits']:
        result['note'] = ('Links can target uncollected records; filtered views can omit linked commits. '
                          'Absence from this view does not establish absence from GitHub.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--repo', default='RustCrypto/KEMs')
    parser.add_argument('--issue', type=int, default=46)
    parser.add_argument('--filtered', action='store_true', help='Use commits_filtered; report absent linked SHAs')
    parser.add_argument('--output', type=Path, help='Write the JSON summary here instead of stdout')
    args = parser.parse_args()
    try:
        result = trace(args.data, args.repo, args.issue, args.filtered)
        output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding='utf-8')
        else:
            sys.stdout.write(output)
        return 0 if result['issue'] is not None else 1
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f'trace_issue: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
