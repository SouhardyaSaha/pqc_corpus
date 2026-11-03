#!/usr/bin/env python3
"""Draw PR and issue threads per PQC family or concern (needs matplotlib)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--coverage', type=Path, default=Path('coverage.json'))
parser.add_argument('--output', type=Path, default=Path('fig-coverage.pdf'))
args = parser.parse_args()
report = json.loads(args.coverage.read_text())
prs, issues = report['tables']['pull_requests']['counts'], report['tables']['issues']['counts']
repos = report['repositories_either_table']
labels = {
    'ML-KEM / Kyber': 'ML-KEM / Kyber (FIPS 203)', 'ML-DSA / Dilithium': 'ML-DSA / Dilithium (FIPS 204)',
    'SLH-DSA / SPHINCS+': 'SLH-DSA / SPHINCS+ (FIPS 205)', 'FN-DSA / Falcon': 'FN-DSA / Falcon (FIPS 206)',
}
rows = report['families'] + [None] + report['concerns']  # None leaves a gap between the groups

plt.rcParams.update({
    'font.family': 'serif', 'font.serif': ['Times New Roman', 'Times', 'STIXGeneral'],
    'font.size': 6.5, 'pdf.fonttype': 42, 'ps.fonttype': 42,
    'axes.linewidth': .5, 'xtick.major.width': .5, 'ytick.major.width': .5,
})
fig, ax = plt.subplots(figsize=(3.45, 1.75))
height = .38
for y, name in enumerate(rows):
    if name is None:
        continue
    # PRs then issues, with a small gap between them.
    ax.barh(y - height / 2 - .01, prs[name], height, color='#2a78d6', edgecolor='white', linewidth=.4)
    ax.barh(y + height / 2 + .01, issues[name], height, color='#eb6834', edgecolor='white', linewidth=.4)
    ax.text(max(prs[name], issues[name]) + 30, y, f'{repos[name]} repos', va='center', fontsize=5.6, color='#555550')
ax.set_yticks([y for y, n in enumerate(rows) if n])
ax.set_yticklabels([labels.get(n, n) for n in rows if n])
ax.invert_yaxis()
ax.set_xlim(0, max(prs.values()) * 1.24)
ax.set_xlabel('Threads naming the family or concern', labelpad=1.5)
ax.grid(axis='x', color='#e4e4df', lw=.4)
ax.set_axisbelow(True)
for side in ('top', 'right'):
    ax.spines[side].set_visible(False)
ax.tick_params(length=2, pad=1.5)
ax.tick_params(axis='y', length=0)
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color='#2a78d6'), plt.Rectangle((0, 0), 1, 1, color='#eb6834')],
          labels=['Pull requests', 'Issues'], loc='lower right', frameon=False, fontsize=6,
          handlelength=1, handleheight=.8, borderaxespad=.2)
fig.subplots_adjust(left=.415, right=.99, bottom=.15, top=.99)
fig.savefig(args.output)
print(args.output)
