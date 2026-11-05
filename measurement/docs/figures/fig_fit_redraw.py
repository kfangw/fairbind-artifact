#!/usr/bin/env python3
"""Redraw of Figure fig:fit for manuscript C28 with figure text of at least 8 pt at the printed width.

Reads the recorded outputs of P10 (docs/11_journal/P10_fit-conditions/results/p10.json) unchanged and draws the same
curves, points, and regions as figure() in docs/11_journal/P10_fit-conditions/p10.py; only the figure size (the IEEE
Access column width, 242.67 pt, so that the PDF is placed at scale 1) and the font sizes differ. No value is
recomputed.

    python3 -I fig_fit_redraw.py     # writes fig_fit.pdf next to this file
"""
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.colors import ListedColormap

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / '11_journal' / 'P10_fit-conditions' / 'results' / 'p10.json'
FS = 8.0
COLW_IN = 242.67355 / 72.27


def main():
    R = json.load(open(SRC, encoding='utf-8'))
    curves = {float(v): (np.array(c['Re']), np.array(c['fb']), np.array(c['fi'])) for v, c in R['curves'].items()}
    rm = R['regmap']
    ms_, vs_, Z, F = np.array(rm['m']), np.array(rm['v']), np.array(rm['Z']), np.array(rm['fb'])
    obs = R['observed']
    plt.rcParams.update({'font.family': 'serif', 'font.serif': ['DejaVu Serif'], 'font.size': FS, 'axes.labelsize': FS,
                         'legend.fontsize': FS, 'xtick.labelsize': FS, 'ytick.labelsize': FS, 'axes.linewidth': 0.6,
                         'lines.linewidth': 1.0, 'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(COLW_IN, 5.1), gridspec_kw=dict(height_ratios=[1.0, 0.95]))
    grays = {0.001: '0.0', 0.01: '0.35', 0.1: '0.6'}
    for v in (0.001, 0.01, 0.1):
        xs, fb, fi = curves[v]
        ax.plot(xs, 100 * fb, '-', color=grays[v], lw=1.1)
        ax.plot(xs, 100 * fi, '--', color=grays[v], lw=0.9)
        if v == 0.001:
            ax.annotate(r'$\bar v$=%g' % v, (xs[-1], 100 * fb[-1]), xytext=(-2, 5), textcoords='offset points', fontsize=FS, ha='right')
        else:
            ax.annotate(r'$\bar v$=%g' % v, (xs[0], 100 * fb[0]), xytext=(-2, 0), textcoords='offset points', fontsize=FS, ha='right', va='center')
    for th in (10, 5):
        ax.axhline(th, color='0.5', lw=0.5, ls=':')
    mk = {'busy': 'o', 'median': 's', 'quiet': '^'}
    for o in obs:
        if o['lab'] != 'lo':
            continue
        fc = 'k' if o['kind'] == 'BR' else 'white'
        ax.plot(o['Re'], 100 * o['fb'], mk[o['win']], ms=3.6, mfc=fc, mec='k', mew=0.6, zorder=5)
    for o in obs:
        if o['lab'] == 'lo' and o['win'] == 'busy' and o['short'] in ('SE', 'BR', 'OS', 'Exa'):
            ax.annotate(o['short'], (o['Re'], 100 * o['fb']), xytext=(3, 3), textcoords='offset points', fontsize=FS)
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlim(1e-3, 3e2); ax.set_ylim(1, 2500)
    ax.set_xlabel('Revenue per active profile epoch $R_e$ (USDC)')
    ax.set_ylabel('Cost share of revenue (%)')
    ax.set_yticks([1, 5, 10, 100, 1000]); ax.set_yticklabels(['1', '5', '10', '100', '1000'])
    h = [Line2D([], [], color='k', ls='-', label='FairBind'), Line2D([], [], color='k', ls='--', label='Full insp.'),
         Line2D([], [], ls='', marker='o', mfc='white', mec='k', ms=3.6, label='busy'),
         Line2D([], [], ls='', marker='s', mfc='white', mec='k', ms=3.6, label='median'),
         Line2D([], [], ls='', marker='^', mfc='white', mec='k', ms=3.6, label='quiet'),
         Line2D([], [], ls='', marker='o', mfc='k', mec='k', ms=3.6, label='BlockRun')]
    ax.legend(handles=h, loc='upper right', ncol=2, frameon=False, handlelength=1.5, columnspacing=0.6,
              handletextpad=0.4, labelspacing=0.25, borderaxespad=0.2)
    ax.set_title('(a) Lower estimate, measured gas, $V$ = 1', fontsize=FS)
    cmap = ListedColormap(['0.80', '0.55', '1.0'])
    bx.pcolormesh(ms_, vs_, Z, cmap=cmap, vmin=-0.5, vmax=2.5, shading='nearest', rasterized=True)
    bx.contour(ms_, vs_, F, levels=[0.05, 0.10], colors=['k', 'k'], linestyles=[':', '-'], linewidths=0.7)
    for o in obs:
        if o['lab'] != 'lo':
            continue
        fc = 'k' if o['kind'] == 'BR' else 'white'
        bx.plot(o['m'], o['v'], mk[o['win']], ms=3.6, mfc=fc, mec='k', mew=0.6, zorder=5)
    bx.set_xscale('log'); bx.set_yscale('log')
    bx.set_xlabel('Sales per active profile epoch $m$')
    bx.set_ylabel(r'Mean sale value $\bar v$ (USDC)')
    h2 = [Patch(fc='0.80', ec='k', lw=0.4, label='FB cheaper, $\\leq$10%'), Patch(fc='0.55', ec='k', lw=0.4, label='FI cheaper, $\\leq$10%'),
          Patch(fc='1.0', ec='k', lw=0.4, label='neither $\\leq$10%'),
          Line2D([], [], color='k', ls='-', lw=0.7, label='FB 10%'), Line2D([], [], color='k', ls=':', lw=0.7, label='FB 5%')]
    bx.legend(handles=h2, loc='upper right', frameon=True, framealpha=0.9, edgecolor='0.7', fancybox=False,
              handlelength=1.5, handletextpad=0.4, labelspacing=0.25, borderaxespad=0.2)
    bx.set_title('(b) Regions, continuously active stylized seller', fontsize=FS)
    fig.tight_layout(h_pad=0.6, pad=0.2)
    fig.savefig(HERE / 'fig_fit.pdf')
    plt.close(fig)


if __name__ == '__main__':
    main()
