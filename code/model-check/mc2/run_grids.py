"""MC2 grid driver: runs the configurations of MC2_plan.md section 3 and writes results/<name>.json.

python3 run_grids.py [group ...]   groups: main, honest, sellers2, mut, reading (default: all)
"""
from __future__ import annotations

import json
import os
import sys
import time

from mc2 import default_cfg, explore

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'results')

ORDERS = {          # (T_p, T_c): deadline order of the proof deadline D_e = M_e + T_p and the window end W_e = A_e + T_c
    'D=W': (1, 2),
    'W<D': (2, 1),
    'W>D': (1, 3),
}


def grids():
    """Grid as run (MC2_results.md 2 (sec.) records the change from the plan's grid and why)."""
    g = []
    D = ORDERS['D=W']
    # main, one profile, up to 3 sales in a profile epoch, 3 in all
    for N in (2, 3, 4):
        for k in (1, 2):
            for oname, (tp, tc) in ORDERS.items():
                if N == 4 and oname != 'D=W':
                    continue
                g.append(('main', f'main_P1_N{N}_k{k}_{oname}_s3',
                          dict(epochs=N, k=k, smax=3, stot=3, T_p=tp, T_c=tc)))
    g.append(('main', 'main_P1_N2_k1_D=W_s4', dict(epochs=2, k=1, smax=3, stot=4)))
    # main with disputes, 2 sales
    for N in (2, 3, 4):
        for k in (1, 2):
            g.append(('main', f'main_P1_N{N}_k{k}_D=W_s2_disp',
                      dict(epochs=N, k=k, smax=2, stot=2, disputes=True)))
    # main, two profiles of one account, 2 sales
    for N in (2, 3, 4):
        for k in (1, 2):
            for oname, (tp, tc) in ORDERS.items():
                if N > 2 and oname != 'D=W':
                    continue
                g.append(('main', f'main_P2_N{N}_k{k}_{oname}_s2',
                          dict(profiles=2, epochs=N, k=k, smax=2, stot=2, T_p=tp, T_c=tc)))
    g.append(('main', 'main_P2_N2_k1_D=W_s3', dict(profiles=2, epochs=2, k=1, smax=2, stot=3)))
    # separate release-unit calls; claims of frozen sales (P4)
    for k in (1, 2):
        g.append(('main', f'units_P1_N2_k{k}_s3', dict(epochs=2, k=k, smax=3, stot=3, units=True)))
    g.append(('main', 'claims_P1_N2_k1_s3', dict(epochs=2, k=1, smax=3, stot=3, claims=True)))
    # honest seller (P5)
    for P, sm, st in ((1, 3, 3), (2, 2, 2)):
        for N in (2, 3, 4):
            for k in (1, 2):
                g.append(('honest', f'honest_P{P}_N{N}_k{k}_s{st}',
                          dict(profiles=P, epochs=N, k=k, smax=sm, stot=st, honest=True)))
    for N in (2, 3):
        g.append(('honest', f'honest_P1_N{N}_k1_s2_disp',
                  dict(epochs=N, k=1, smax=2, stot=2, honest=True, disputes=True)))
    # two sellers (freeze isolation, P6)
    for k in (1, 2):
        g.append(('sellers2', f'sellers2_N2_k{k}_s1', dict(sellers=2, epochs=2, k=k, smax=1, stot=1)))
    g.append(('sellers2', 'sellers2_N3_k1_s1', dict(sellers=2, epochs=3, k=1, smax=1, stot=1)))
    # deliberate rule changes (each must give a counterexample)
    base = dict(epochs=2, k=1, smax=2, stot=2)
    muts = [
        ('M1_freeze_next', dict(base, stot=3)),
        ('M2_cursor_no_wait', dict(base)),
        ('M3_k_first_only', dict(base, k=2)),
        ('M4_pay_before_freeze', dict(base)),
        ('M5_freeze_profile_only', dict(base, profiles=2)),
        ('M6_dispute_pay_early', dict(base, disputes=True)),
        ('M7_double_declare', dict(base)),
        ('M8_unit_pays', dict(base)),
        ('M9_accept_frozen', dict(base)),
        ('M10_double_pay', dict(base)),
        ('M11_freeze_cross_seller', dict(base, sellers=2, stot=1)),
    ]
    for m, cfg in muts:
        g.append(('mut', f'mut_{m}', dict(cfg, mutations=(m,))))
    # reading check of the empty-epoch clause
    g.append(('reading', 'reading_R_empty_literal',
              dict(epochs=2, k=1, smax=2, stot=2, disputes=True, mutations=('R_empty_literal',))))
    return g


def run_one(item):
    grp, name, kw = item
    path = os.path.join(OUT, name + '.json')
    if os.path.exists(path):
        return name, None
    cfg = default_cfg(**kw)
    small = grp in ('mut', 'reading')
    r = explore(cfg, stop_on_first=small, want_trace=small)
    if r['violations'] and not small:
        # re-search with full states to get a trace of the first violation
        r2 = explore(dict(cfg, max_states=3_000_000), stop_on_first=True, want_trace=True)
        r['trace_rerun'] = r2['violations']
    r['cfg'] = cfg
    r['group'] = grp
    r['name'] = name
    with open(path, 'w') as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    return name, r


def main(argv):
    import multiprocessing as mp
    workers = 3
    groups = set(a for a in argv if not a.startswith('-')) or {'main', 'honest', 'sellers2', 'mut', 'reading'}
    os.makedirs(OUT, exist_ok=True)
    items = [x for x in grids() if x[0] in groups]
    items.sort(key=lambda x: -(x[2].get('stot', 4) * 10 + x[2].get('epochs', 2) + 5 * x[2].get('profiles', 1)))
    with mp.Pool(workers, maxtasksperchild=1) as pool:
        for name, r in pool.imap_unordered(run_one, items):
            if r is None:
                continue
            print(f"{name}: states {r['states']:,} terminal {r['terminal']:,} "
                  f"viol {sorted(r['violations'])} capped {r['capped']} {r['seconds']:.0f}s", flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
