"""Run MC1 grids.

    python3 run.py <grid> [workers]      # grid is a function name in grids.py

Writes results/<grid>.json (one record per configuration: state count, end states,
outcomes, honest reverts, violated properties with their shortest trace).
"""
import json
import os
import sys
import time

from model import default_cfg, explore, explore_dfs
from checks import check_state, check_final


def run(name, **kw):
    # ciphertext configurations run depth first (memory); plaintext breadth first (shortest traces)
    kw.setdefault('dfs', kw.get('prof', 'P') == 'C')
    cfg = default_cfg(**kw)
    t0 = time.time()
    stats, traces = (explore_dfs if cfg['dfs'] else explore)(cfg, check_state, check_final)
    dt = time.time() - t0
    rec = dict(name=name, cfg={k: v for k, v in cfg.items() if not k.startswith('_') and k != 'max_states'},
               states=stats['states'], edges=stats['edges'], finals=stats['finals'],
               outcomes={str(k): v for k, v in stats['outcomes'].items()},
               honest_reverts=stats['reverts'],
               complete=stats.get('complete', True),
               violations=sorted(traces), traces=traces, seconds=round(dt, 1))
    print(f"{name}: states={stats['states']} finals={stats['finals']} complete={stats.get('complete', True)} "
          f"viol={sorted(traces)} {dt:.1f}s", flush=True)
    return rec


def _job(arg):
    name, kw = arg
    try:
        return run(name, **kw)
    except Exception as e:  # noqa: BLE001 - reported in the results file
        print(f'{name}: ERROR {e!r}', flush=True)
        return dict(name=name, error=repr(e))


if __name__ == '__main__':
    import grids
    from multiprocessing import Pool
    g = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    jobs = getattr(grids, g)()
    os.makedirs('results', exist_ok=True)
    if workers > 1:
        with Pool(workers, maxtasksperchild=1) as pool:
            recs = pool.map(_job, jobs, chunksize=1)
    else:
        recs = [_job(j) for j in jobs]
    with open(f'results/{g}.json', 'w') as f:
        json.dump(recs, f, ensure_ascii=False, indent=1, default=str)
