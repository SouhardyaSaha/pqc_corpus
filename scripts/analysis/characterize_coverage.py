#!/usr/bin/env python3
"""Count PR and issue threads that name each PQC family or engineering concern."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

FAMILIES = {
    'ML-KEM / Kyber': r'\bml[-_ ]?kem|\bkyber|\bfips[-_ ]?203\b',
    'ML-DSA / Dilithium': r'\bml[-_ ]?dsa\b|dilithium|\bfips[-_ ]?204\b',
    'SLH-DSA / SPHINCS+': r'\bslh[-_ ]?dsa\b|sphincs|\bfips[-_ ]?205\b',
    'FN-DSA / Falcon': r'\bfn[-_ ]?dsa\b|\bfalcon[-_ ]?(?:512|1024)\b|\bfips[-_ ]?206\b',
    'HQC': r'\bhqc\b',
    'Classic McEliece': r'mceliece',
    'FrodoKEM': r'\bfrodo',
    'XMSS / LMS': r'\bxmss|\blms\b|\bsp[-_ ]?800[-_ ]?208\b',
}
CONCERNS = {
    'Hybrid key exchange': r'x25519[-_ ]?(?:ml[-_ ]?kem|kyber)|(?:secp256r1|p256|p384|secp384r1)[-_ ]?(?:ml[-_ ]?kem|kyber)'
                           r'|\bx[-_]?wing\b|hybrid[-_ ](?:kem|key[-_ ]exchange|key[-_ ]agreement|pq|post[-_ ]quantum)',
    'Constant time / side channels': r'constant[-_ ]time|side[-_ ]channel|timing[-_ ](?:leak|attack|side)|kyberslash',
    'Known-answer tests / vectors': r'known[-_ ]answer|\bkats?\b|test[-_ ]vectors?|\bacvp\b|wycheproof',
}
PATTERNS = {name: re.compile(rx, re.I) for name, rx in {**FAMILIES, **CONCERNS}.items()}
# Drop HTML comments and template checklist questions before matching.
TEMPLATE = re.compile(r'<!--.*?-->|^\s*[-*]\s*\[[^\]]*\][^\n]*\?[^\n]*$', re.S | re.M)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--output', type=Path, default=Path('coverage.json'))
args = parser.parse_args()

result = {'families': list(FAMILIES), 'concerns': list(CONCERNS), 'patterns': {k: p.pattern for k, p in PATTERNS.items()}, 'tables': {}}
repos_any = defaultdict(set)
quarterly = defaultdict(Counter)
for table in ('pull_requests', 'issues'):
    counts, repos, digest, rows, matched = Counter(), defaultdict(set), hashlib.sha256(), 0, 0
    with (args.data / f'{table}.jsonl').open('rb') as source:
        for line in source:
            digest.update(line)
            row = json.loads(line)
            rows += 1
            text = (row.get('title') or '') + '\n' + TEMPLATE.sub('', row.get('body') or '')
            created = row['created_at']
            quarter = f"{created[:4]}Q{(int(created[5:7]) - 1) // 3 + 1}"
            hits = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
            matched += any(name in FAMILIES for name in hits)
            for name in hits:
                counts[name] += 1
                repos[name].add(row['repo'])
                repos_any[name].add(row['repo'])
                quarterly[name][quarter] += 1
    result['tables'][table] = {
        'sha256': digest.hexdigest(), 'rows': rows, 'rows_naming_any_family': matched,
        'counts': {name: counts[name] for name in PATTERNS},
        'repositories': {name: len(repos[name]) for name in PATTERNS},
    }
result['repositories_either_table'] = {name: len(repos_any[name]) for name in PATTERNS}
result['quarterly_threads'] = {name: dict(sorted(quarterly[name].items())) for name in PATTERNS}
repos = [json.loads(line) for line in (args.data / 'repositories.jsonl').read_text().splitlines()]
result['primary_language'] = dict(Counter(r.get('language') or 'none' for r in repos).most_common())
result['interpretation'] = ('Lexical mentions in PR/issue titles and bodies; threads can count toward several '
    'rows. Not adoption, implementation, deployment, or verified PQC relevance. 2026 covers the '
    'collection interval only (through 2026-09-24).')
args.output.write_text(json.dumps(result, indent=2) + '\n')
for table, summary in result['tables'].items():
    print(table, summary['rows'], 'rows;', summary['rows_naming_any_family'], 'name a family')
    for name in PATTERNS:
        print(f"  {name:32s} {summary['counts'][name]:6d} {summary['repositories'][name]:4d}")
print('repositories in either table:', result['repositories_either_table'])
