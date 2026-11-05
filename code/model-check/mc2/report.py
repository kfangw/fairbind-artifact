"""Summarise results/*.json into markdown tables for MC2_results.md."""
import glob
import json
import os

rows = []
for p in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', '*.json'))):
    if p.endswith('coverage.json'):
        continue
    r = json.load(open(p))
    rows.append(r)

for grp in ('main', 'honest', 'sellers2', 'mut', 'reading'):
    rs = [r for r in rows if r['group'] == grp]
    if not rs:
        continue
    print(f'\n### {grp}\n')
    print('| configuration | state count | end state count | counterexample found property | complete | seconds |')
    print('|---|---|---|---|---|---|')
    tot = 0
    for r in rs:
        tot += r['states']
        v = ', '.join(sorted(r['violations'])) or 'none'
        print(f"| {r['name']} | {r['states']:,} | {r['terminal']:,} | {v} | {'first at counterexample stopped' if r['group'] in ('mut', 'reading') else ('no(upper)' if r['capped'] else 'yes')} | {r['seconds']:.0f} |")
    print(f'\nsum: configuration {len(rs)}, state {tot:,}')
    if grp in ('mut', 'reading'):
        for r in rs:
            print(f"\n{r['name']}:")
            for k, v in sorted(r['violations'].items()):
                print(f"- {k}: {v['msg']}")
                if v.get('trace'):
                    print('  - path: ' + '; '.join(v['trace']))
