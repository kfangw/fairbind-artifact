#!/usr/bin/env python3
"""One driver for the design-2 runs of a chain: every v_max of the choice list under every sales cap rule.

    d2_sweep.py --chain base --settlements LIST.csv --reference-dir REF --conditions-file COND.json
                --out OUT [--prior-settlements PRIOR.csv] [--vmax 0.1,0.2,1]
                [--modes auto-zero-reject,prior14] [--draws N] [--parallel 2] [--time-limit SECONDS]
                [--block-time SECONDS] [-- more replay.py arguments]

Each configuration (v_max, sales cap rule) is one `replay.py --design 2` run of condition 1, seed 0, written to
OUT/<chain>_v<v_max>_<mode>/. The driver does not change any rule or number. A configuration whose `run.json`
exists is finished and skipped. With `--time-limit` the driver stops cleanly when the time is used up, after
saving the injection state per address (OUT/.ckpt/<tag>/), and exits with status 3; the same command continues
where it stopped and gives the files an uninterrupted run gives. Status 0: every configuration is finished.

The modes are those of `--sales-cap`: auto-zero-reject (the main result), prior14 (the contrast line), cross.
A mode that needs the 14 days before the window (prior14) is skipped with a note when no prior list is given.
"""
import argparse
import json
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

DEFAULT_VMAX = ('0.1', '0.2', '1')
DEFAULT_MODES = ('auto-zero-reject', 'prior14')
STOPPED = 3


class Stop(Exception):
    """The time limit is used up."""


def tag_of(chain, vmax, mode, block_time=None):
    tag = f'{chain}_v{vmax}_{mode}'
    return tag if block_time is None else f'{tag}_bt{block_time}'


def replay_args(a, vmax, mode, out):
    argv = ['--settlements', a.settlements, '--conditions-file', a.conditions_file, '--reference-dir', a.reference_dir,
            '--qx', '137', '--conditions', '1', '--repetitions', '1', '--design', '2', '--vmax', vmax,
            '--sales-cap', mode, '--chain', a.chain, '--out', str(out)]
    if a.prior_settlements and mode == 'prior14':
        argv += ['--prior-settlements', a.prior_settlements]
    if a.block_time:
        argv += ['--block-time', a.block_time]
    if a.draws is not None:
        argv += ['--draws', str(a.draws)]
    return argv + list(a.extra)


def run_one(argv, ckpt_dir, deadline):
    """replay.main(argv) with the per-address injection loop checkpointed in ckpt_dir; raises Stop when the
    deadline passes."""
    import replay
    ckpt_dir = Path(ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    original = replay.inject_address
    state = {}

    def save(seed, st, accum):
        path = ckpt_dir / f'seed{seed}.pkl'
        with open(f'{path}.tmp', 'wb') as f:
            pickle.dump(dict(rows=st['rows'], data=accum.data), f, protocol=4)
        os.replace(f'{path}.tmp', path)
        st['last'] = time.time()

    def wrapper(seller, arr, *, seed, accum, **kw):
        st = state.get(seed)
        if st is None:
            st = state[seed] = dict(rows={}, last=time.time(), new=0)
            path = ckpt_dir / f'seed{seed}.pkl'
            if path.exists():
                with open(path, 'rb') as f:
                    saved = pickle.load(f)
                st['rows'] = saved['rows']
                accum.data = saved['data']
        if seller in st['rows']:
            return st['rows'][seller]
        if deadline is not None and time.time() > deadline:
            if st['new']:
                save(seed, st, accum)
            raise Stop()
        rows = original(seller, arr, seed=seed, accum=accum, **kw)
        st['rows'][seller] = rows
        st['new'] += 1
        if time.time() - st['last'] > 25:
            save(seed, st, accum)
        return rows

    replay.inject_address = wrapper
    try:
        replay.main(argv)
    finally:
        replay.inject_address = original


def configurations(a):
    vmaxes = [v for v in a.vmax.split(',') if v]
    modes = [m for m in a.modes.split(',') if m]
    out = []
    for v in vmaxes:
        for m in modes:
            out.append((v, m))
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if '--' in argv:
        i = argv.index('--')
        argv, extra = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--chain', default='base')
    p.add_argument('--settlements', required=True)
    p.add_argument('--reference-dir', required=True)
    p.add_argument('--conditions-file', required=True)
    p.add_argument('--prior-settlements', default=None)
    p.add_argument('--out', required=True)
    p.add_argument('--vmax', default=','.join(DEFAULT_VMAX))
    p.add_argument('--modes', default=','.join(DEFAULT_MODES))
    p.add_argument('--draws', type=int, default=None)
    p.add_argument('--block-time', default=None)
    p.add_argument('--parallel', type=int, default=1, help='configurations run at the same time (processes)')
    p.add_argument('--time-limit', type=float, default=None, help='seconds of work in this call')
    p.add_argument('--deadline', type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument('--one', default=None, help=argparse.SUPPRESS)     # internal: "vmax|mode"
    a = p.parse_args(argv)
    a.extra = extra
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.one is not None:                                           # one configuration, in this process
        vmax, mode = a.one.split('|')
        tag = tag_of(a.chain, vmax, mode, a.block_time)
        try:
            run_one(replay_args(a, vmax, mode, out / tag), out / '.ckpt' / tag, a.deadline)
        except Stop:
            print(f'{tag}: STOPPED', flush=True)
            return STOPPED
        print(f'{tag}: COMPLETE', flush=True)
        return 0
    deadline = None if a.time_limit is None else time.time() + a.time_limit
    todo, skipped = [], []
    for vmax, mode in configurations(a):
        tag = tag_of(a.chain, vmax, mode, a.block_time)
        if mode == 'prior14' and not a.prior_settlements:
            skipped.append(dict(tag=tag, reason='no prior list for this chain'))
        elif not (out / tag / 'run.json').exists():
            todo.append((vmax, mode, tag))
    (out / 'sweep.json').write_text(json.dumps(dict(
        chain=a.chain, vmax=a.vmax.split(','), modes=a.modes.split(','), skipped=skipped, draws=a.draws,
        block_time=a.block_time, settlements=a.settlements, prior=a.prior_settlements), indent=1) + '\n')
    status = 0
    running = []

    def reap(block):
        nonlocal status
        for proc, tag in list(running):
            if block or proc.poll() is not None:
                rc = proc.wait()
                running.remove((proc, tag))
                if rc == STOPPED:
                    status = STOPPED
                elif rc != 0:
                    raise SystemExit(f'{tag}: replay failed with status {rc}')

    me = [sys.executable, str(Path(__file__).resolve())]
    base = ['--chain', a.chain, '--settlements', a.settlements, '--reference-dir', a.reference_dir,
            '--conditions-file', a.conditions_file, '--out', a.out]
    if a.prior_settlements:
        base += ['--prior-settlements', a.prior_settlements]
    if a.draws is not None:
        base += ['--draws', str(a.draws)]
    if a.block_time:
        base += ['--block-time', a.block_time]
    if deadline is not None:
        base += ['--deadline', repr(deadline)]
    for vmax, mode, tag in todo:
        while len(running) >= max(1, a.parallel):
            time.sleep(1)
            reap(False)
        if deadline is not None and time.time() > deadline:
            status = STOPPED
            break
        cmd = me + base + ['--one', f'{vmax}|{mode}']
        if extra:
            cmd += ['--'] + extra
        running.append((subprocess.Popen(cmd), tag))
    while running:
        reap(True)
    return status


if __name__ == '__main__':
    sys.exit(main())
