#!/usr/bin/env python3
"""K13: forge logs -> logs/k13_gas.tsv and logs/k13_slots.tsv (registration 3.5, supplementary registration 1 sec. 7).
Reads the lines 'K13\t...' and 'K13SLOTS\t...' of k13_gas_run<n>.log(.gz). release_one rows get P, m, sig = '-'
(supplementary registration 1, 7.1). Fails on a duplicate row within a run or on a failed test.
Run: python3 -I docs/11_journal/K13/k13_tsv.py docs/11_journal/K13/logs
"""
import sys, os, gzip, re
sys.dont_write_bytecode = True
D = sys.argv[1]
gas, slots = [], []
for n in (1, 2, 3):
    p = os.path.join(D, 'k13_gas_run%d.log.gz' % n)
    txt = gzip.open(p, 'rt', encoding='utf-8').read() if os.path.exists(p) else open(p[:-3], encoding='utf-8').read()
    assert 'FAIL' not in re.sub(r'K13.*', '', txt), 'failed test in run %d' % n
    seen = set()
    for line in txt.splitlines():
        f = line.strip().split('\t')
        if f[0] == 'K13':
            v, ev, P, m, sig, slot, g, fl = f[1:9]
            if ev == 'release_one': P = m = sig = '-'
            key = (v, ev, P, m, sig, slot); assert key not in seen, key; seen.add(key)
            gas.append([v, ev, P, m, sig, slot, str(n), g, fl, '0'])
        elif f[0] == 'K13SLOTS':
            v, m, sig, slot, new, upd = f[1:7]
            slots.append([v, m, sig, slot, str(n), new, upd])
    print('run', n, 'rows', len(seen))
with open(os.path.join(D, 'k13_gas.tsv'), 'w', encoding='ascii', newline='\n') as fh:
    fh.write('\t'.join(['variant', 'event', 'P', 'm', 'sig', 'slot', 'run', 'tx_gas', 'eip7623_floor', 'l1_fee_node_wei']) + '\n')
    for r in gas: fh.write('\t'.join(r) + '\n')
with open(os.path.join(D, 'k13_slots.tsv'), 'w', encoding='ascii', newline='\n') as fh:
    fh.write('\t'.join(['variant', 'm', 'sig', 'slot', 'run', 'new_slots', 'updated_slots']) + '\n')
    for r in slots: fh.write('\t'.join(r) + '\n')
print('gas rows', len(gas), 'slot rows', len(slots))
