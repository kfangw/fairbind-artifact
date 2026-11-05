#!/usr/bin/env python3
"""R20-M1 rejection predictions from the R1 fluid model (design 5.5, 9.7).

    m1_predictions.py --r1 PATH/r1.py --reference-dir DIR --out m1_predictions.csv

For every group A address this runs `simulate_seller` of the R1 script unchanged (its activity
approximation: active_hours - 1 hours at rate_per_active_hour, then one hour at
rate_per_hour_peak, the bucket full at the start, fluid token-bucket ODE) with the replay's
bucket at scale nF: refill n * r_fill per hour and capacity n * qX, where r_fill is the
data-API refillPpmPerBlock of the replay profile and qX the fixed burst capacity. The scale is
the nF rule on the reference count over rate_blocks (option W344). Inputs are the reference
aggregate and the model only, never replay results.

The CSV has `address` and `predicted_rejection_rate` (the columns rules.py reads) and the model
inputs; a JSON file beside it records the R1 script hash, the parameters, and the addresses
whose active_hours the script clamps to its 336-hour window. Its own imports of the R1 helper
module (bond_gap2) are not needed by simulate_seller and are replaced by a stub that raises if
called.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import types
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'experiments'))

import inputs  # noqa: E402
import replay  # noqa: E402
from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402

PROFILE = 'data-api-fast-v1'
COLUMNS = ['address', 'rank', 'scale', 'lambda_max_per_hour', 'bucket_capacity', 'active_hours',
           'rate_per_active_hour', 'rate_per_hour_peak', 'demanded', 'predicted_rejected',
           'predicted_rejection_rate']


def load_r1(path):
    """The R1 module, with its unused helper import stubbed."""
    if 'bond_gap2' not in sys.modules:
        stub = types.ModuleType('bond_gap2')

        def unavailable(*_a, **_k):
            raise RuntimeError('bond_gap2 is not available; simulate_seller does not use it')
        stub.load_config2 = stub.effective_p = stub.percentile = unavailable
        sys.modules['bond_gap2'] = stub
    spec = importlib.util.spec_from_file_location('r1_model', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['r1_model'] = module
    spec.loader.exec_module(module)
    return module


def predictions(r1, sellers_csv, cond, profile, block_seconds):
    """Rows of the prediction file for group A, in rank order."""
    p = profile['parameters']
    qx = cond['q']['qX']
    top = inputs.load_top400(sellers_csv)
    lo, hi = cond['groups']['A']['ranks']
    group_a = top[lo - 1:hi]
    scale = replay.scales(group_a, 'nF', p, replay.rate_blocks(cond))
    refill_per_hour = Fraction(p['refillPpmPerBlock'], 1_000_000) * 3600 / block_seconds
    model_rows = {s['seller_id'].lower(): s for s in r1.load_sellers(str(sellers_csv))}
    rows, clamped = [], []
    for rank, (a, _) in enumerate(group_a, start=lo):
        n = scale[a]
        seller = model_rows[a]
        if seller['active_hours'] > r1.HOURS_IN_WINDOW:
            clamped.append(dict(address=a, active_hours=seller['active_hours']))
        lam = float(n * refill_per_hour)
        q = n * qx
        sim = r1.simulate_seller(seller, lam, q)
        rows.append(dict(address=a, rank=rank, scale=n, lambda_max_per_hour=lam, bucket_capacity=q,
                         active_hours=seller['active_hours'], rate_per_active_hour=seller['rate_per_active_hour'],
                         rate_per_hour_peak=seller['rate_per_hour_peak'], demanded=sim['demanded'],
                         predicted_rejected=sim['rejected'], predicted_rejection_rate=sim['fraction_rejected']))
    return rows, clamped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--r1', required=True, help='the R1 script (batch1/R1/r1.py)')
    ap.add_argument('--reference-dir', required=True)
    ap.add_argument('--conditions-file', default=str(inputs.CONDITIONS_PATH))
    ap.add_argument('--operating-point', default=None)
    ap.add_argument('--out', required=True, help='CSV path; the metadata goes to the same path with .json')
    a = ap.parse_args(argv)
    cond = inputs.load_conditions(a.conditions_file)
    op_path = a.operating_point or replay.default_operating_point(cond)
    op = opt.load(op_path)
    profile = prof.load_profile(ROOT / op['profile_file'], PROFILE)
    errors = opt.check(op, profile)
    if errors:
        raise SystemExit('operating point and profile disagree: ' + '; '.join(errors))
    sellers_csv = Path(a.reference_dir) / cond['inputs']['top400']['file_name']
    r1 = load_r1(a.r1)
    rows, clamped = predictions(r1, sellers_csv, cond, profile, op['chain']['block_seconds'])
    out = Path(a.out)
    with open(out, 'w', newline='', encoding='ascii') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(v) if isinstance(v, float) else v) for k, v in r.items()})
    meta = dict(kind='fairbind-r20-m1-predictions', model='R1 fluid model, simulate_seller, unchanged',
                code=replay.git_state(),
                r1=dict(path=str(a.r1), sha256=hashlib.sha256(Path(a.r1).read_bytes()).hexdigest()),
                sellers=dict(path=str(sellers_csv), sha256=inputs.sha256_file(sellers_csv)),
                conditions_file=dict(path=cond['_path'], sha256=cond['_sha256']),
                operating_point=dict(path=op['_path'], sha256=op['_sha256']),
                profile=PROFILE, qX=cond['q']['qX'], refillPpmPerBlock=profile['parameters']['refillPpmPerBlock'],
                scale_rule='nF', rate_blocks=replay.rate_blocks(cond), group='A', addresses=len(rows),
                hours_in_window=r1.HOURS_IN_WINDOW, active_hours_clamped=clamped,
                output=dict(path=str(out), sha256=inputs.sha256_file(out)))
    out.with_suffix('.json').write_text(json.dumps(meta, indent=1, sort_keys=True) + '\n')
    print(f'{out}: {len(rows)} addresses, sha256 {meta["output"]["sha256"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
