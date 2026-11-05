#!/usr/bin/env python3
"""Input statistics of a settlement list (design 9.8): settlements above the purchase value cap.

    input_stats.py --settlements CSV [--out input_stats.json]

The data-API profile caps a purchase at maxPurchaseValue (0.01 USDC, 10,000 atomic units); the
recorded settlements can be larger. The replay uses the values as they are, so this reports,
from the list alone, how many settlements and how much value lie strictly above the cap, with
the totals and the shares. No replay quantity is computed.
"""
import argparse
import json
import sys
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


def above_cap(path, columns, cap):
    """Counts and atomic values of all settlements and of those with value > cap."""
    count = value = count_above = value_above = 0
    for row in inputs.iter_rows(path, columns):
        v = int(row[7])
        count += 1
        value += v
        if v > cap:
            count_above += 1
            value_above += v
    return dict(cap_atomic=cap, total_count=count, total_value_atomic=value, above_cap_count=count_above,
                above_cap_value_atomic=value_above,
                above_cap_count_share=count_above / count if count else None,
                above_cap_value_share=value_above / value if value else None)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--settlements', required=True)
    ap.add_argument('--conditions-file', default=str(inputs.CONDITIONS_PATH))
    ap.add_argument('--operating-point', default=None)
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    cond = inputs.load_conditions(a.conditions_file)
    op = opt.load(a.operating_point or replay.default_operating_point(cond))
    profile = prof.load_profile(ROOT / op['profile_file'], PROFILE)
    cap = int(profile['parameters']['maxPurchaseValue'])
    sha = inputs.sha256_file(a.settlements)
    period = next((k for k, v in cond['inputs'].items() if isinstance(v, dict) and v.get('sha256') == sha), None)
    report = dict(kind='fairbind-r20-input-stats', design_section='9.8', code=replay.git_state(),
                  settlements=dict(path=str(a.settlements), sha256=sha, period=period),
                  profile=PROFILE, profile_file=op['profile_file'], token_decimals=op['chain']['token_decimals'],
                  **above_cap(a.settlements, cond['inputs']['columns'], cap))
    text = json.dumps(report, indent=1, sort_keys=True) + '\n'
    if a.out:
        Path(a.out).write_text(text)
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
