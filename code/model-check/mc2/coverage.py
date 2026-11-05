"""Non-vacuity check for MC2: which statuses and events the search reaches (results/coverage.json)."""
import json
import os
from collections import deque

from mc2 import (Model, default_cfg, ST_NAME, SALES, FAILS, REENT, CUR, ST, AN, SM, DK, ETA, F, PC)

CFGS = [dict(epochs=2, smax=2, stot=2, disputes=True),
        dict(epochs=2, k=2, smax=2, stot=2, profiles=2)]


def cover(kw):
    m = Model(default_cfg(**kw))
    init = m.init()
    seen = {init}
    q = deque([init])
    cov = set()
    while q:
        s = q.popleft()
        for sel in s[1]:
            for x in sel[SALES]:
                cov.add('status ' + ST_NAME[x[ST]])
                if x[AN] == 0 and x[SM] == 1:
                    cov.add('kind O sale sampled')
                if x[ST] == F and x[DK] == 1:
                    cov.add('disputed sale frozen')
            for f in sel[FAILS]:
                cov.add('failure ' + {'c': 'sample case', 'm': 'missed anchor'}[f[0][0]])
            if sel[REENT]:
                cov.add('re-entry')
            if len(sel[FAILS]) >= 2:
                cov.add('two failures in one run')
            if sel[CUR] == m.nE:
                cov.add('cursor passed every seller epoch')
            if sel[REENT] and any(x[ST] == PC and x[ETA] > min(f[1] for f in sel[FAILS]) for x in sel[SALES]):
                cov.add('cursor pays a later-episode sale after re-entry')
        for _, n in m.succ(s):
            if n not in seen:
                seen.add(n)
                q.append(n)
    return dict(cfg=kw, states=len(seen), reached=sorted(cov))


if __name__ == '__main__':
    out = [cover(kw) for kw in CFGS]
    os.makedirs('results', exist_ok=True)
    json.dump(out, open('results/coverage.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
