#!/usr/bin/env python3
"""Draw box plots of repository characteristics by corpus (needs matplotlib)."""
import argparse
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--output', type=Path, default=Path('fig-repositories.pdf'))
args = parser.parse_args()
repos = [json.loads(line) for line in (args.data / 'repositories.jsonl').read_text().splitlines()]


def years(row):
    created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
    fetched = datetime.fromisoformat(row['fetched_at'].replace('Z', '+00:00'))
    return (fetched - created).days / 365.25


panels = [
    ('Stars', lambda r: r['stars'], True),
    ('Forks', lambda r: r['forks'], True),
    ('Age (years)', years, False),
    ('Git commits', lambda r: r['git_commits'], True),
    ('Pull requests on GitHub', lambda r: r['github_pull_requests'], True),
    ('Issues on GitHub', lambda r: r['github_issues'], True),
]
# Fixed color order; axis labels name each corpus.
corpora = [('A', '#2a78d6'), ('B', '#eb6834'), ('C', '#1baf7a')]

plt.rcParams.update({
    'font.family': 'serif', 'font.serif': ['Times New Roman', 'Times', 'STIXGeneral'],
    'font.size': 6.5, 'pdf.fonttype': 42, 'ps.fonttype': 42,
    'axes.linewidth': .5, 'xtick.major.width': .5, 'ytick.major.width': .5,
    'xtick.minor.width': .3,
})
fig, axes = plt.subplots(2, 3, figsize=(3.45, 1.6))
for ax, (title, value, log) in zip(axes.flat, panels):
    # Corpus C has no PRs or issues.
    shown = [(c, col) for c, col in corpora if not (c == 'C' and 'GitHub' in title)]
    data = [[value(r) for r in repos if r['corpus'] == c] for c, _ in shown]
    if log:
        data = [[max(v, 1) for v in d] for d in data]  # zeros drawn at 1 on the log axis
    parts = ax.boxplot(data, vert=False, widths=.55, patch_artist=True, showfliers=True,
                       medianprops={'color': '#1a1a19', 'lw': .8},
                       whiskerprops={'lw': .5}, capprops={'lw': .5},
                       flierprops={'marker': 'o', 'markersize': 1.6, 'markeredgewidth': .3,
                                   'markerfacecolor': 'none', 'markeredgecolor': '#77776f'})
    for box, (_, color) in zip(parts['boxes'], shown):
        box.set(facecolor=color, alpha=.85, edgecolor='#333333', linewidth=.5)
    ax.set_yticks(range(1, len(shown) + 1))
    ax.set_yticklabels([c for c, _ in shown])
    ax.invert_yaxis()
    if log:
        ax.set_xscale('log')
    ax.set_title(title, fontsize=6.5, pad=2)
    ax.grid(axis='x', color='#e4e4df', lw=.4)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=2, pad=1.2)
fig.subplots_adjust(left=.05, right=.98, bottom=.1, top=.92, wspace=.3, hspace=.75)
fig.savefig(args.output)
print(args.output)
