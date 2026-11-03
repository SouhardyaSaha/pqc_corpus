#!/usr/bin/env python3
"""Draw quarterly threads per PQC family from coverage.json (needs matplotlib)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--coverage', type=Path, default=Path('coverage.json'))
parser.add_argument('--output', type=Path, default=Path('fig-activity.pdf'))
args = parser.parse_args()
quarterly = json.loads(args.coverage.read_text())['quarterly_threads']

plt.rcParams.update({
    'font.family': 'serif', 'font.serif': ['Times New Roman', 'Times', 'STIXGeneral'],
    'mathtext.fontset': 'stix', 'font.size': 7, 'pdf.fonttype': 42, 'ps.fonttype': 42,
    'axes.linewidth': .5, 'xtick.major.width': .5, 'ytick.major.width': .5,
})
quarters = [f'{y}Q{q}' for y in range(2018, 2027) for q in range(1, 5)][:-1]  # through 2026Q3
x = list(range(len(quarters)))
# Fixed color order; line styles and labels identify series in print.
series = [
    ('ML-KEM / Kyber', 'ML-KEM', '#2a78d6', '-'),
    ('ML-DSA / Dilithium', 'ML-DSA', '#eb6834', '--'),
    ('SLH-DSA / SPHINCS+', 'SLH-DSA', '#1baf7a', '-.'),
    ('Hybrid key exchange', 'Hybrid KEX', '#eda100', ':'),
]
fig, ax = plt.subplots(figsize=(3.45, 1.55))
# NIST milestones, numbered as in the caption.
milestones = ['2022Q3', '2023Q3', '2024Q3', '2025Q1']
top = max(quarterly[name].get(q, 0) for name, *_ in series for q in quarters)
for n, q in enumerate(milestones, 1):
    i = quarters.index(q)
    ax.axvline(i, ymax=.93, color='#9a9a94', lw=.5, ls=(0, (2, 2)), zorder=0)
    ax.text(i, top * 1.0, str(n), ha='center', va='center', fontsize=6, color='#444440')
for name, short, color, style in series:
    y = [quarterly[name].get(q, 0) for q in quarters]
    ax.plot(x, y, color=color, lw=1.3, ls=style, solid_capstyle='round')
    ax.annotate(short, (x[-1], y[-1]), xytext=(3, 0), textcoords='offset points',
                va='center', fontsize=6, color='#222222')
ax.set_xlim(0, len(quarters) - 1)
ax.set_ylim(0, top * 1.07)
ax.set_xticks([quarters.index(f'{y}Q1') for y in range(2018, 2027)])
ax.set_xticklabels([str(y) for y in range(2018, 2027)])
ax.set_ylabel('Threads per quarter')
ax.grid(axis='y', color='#e4e4df', lw=.4)
ax.set_axisbelow(True)
for side in ('top', 'right'):
    ax.spines[side].set_visible(False)
ax.tick_params(length=2, pad=1.5)
fig.subplots_adjust(left=.12, right=.85, bottom=.13, top=.97)
fig.savefig(args.output)
print(args.output)
