"""Summarize results/*.json: one line per configuration, and the traces of each violation.

    python3 report.py results/BP1.json [results/SP1.json ...] [--traces]
"""
import json
import sys

PROPS = ['C1', 'C1-dl', 'C2', 'S1', 'S1-dl', 'S2', 'S3', 'I1', 'I2', 'I3', 'B1', 'B2', 'U1', 'CORE']


def main(paths, traces):
    tot = 0
    for path in paths:
        for r in json.load(open(path)):
            if 'error' in r:
                print(f"{r['name']}: ERROR {r['error']}")
                continue
            tot += r['states']
            v = r['violations']
            print(f"{r['name']:<38} states={r['states']:>9} ends={r['finals']:>8} "
                  f"{'pass' if not v else 'CEX ' + ','.join(v)}")
            if traces:
                for p in v:
                    print(f'  --- {p}')
                    for line in r['traces'][p]:
                        print('   ', line)
    print('total states', tot)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    main(args, '--traces' in sys.argv)
