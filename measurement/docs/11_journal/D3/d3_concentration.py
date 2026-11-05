#!/usr/bin/env python3
"""D3 (registration D3_registration.md): wash filters, leave-one-out and size strata on stored outputs only.

No replay, no list re-derivation, no cost-model rerun, no chain query.
Inputs: data/processed/agg_2026-10-21/ (pairs, days, values), R10/results per-address outputs (main, overcap),
R10/R10c/out/r10c_m3_addr_<w>.csv (W_v, NB_m), R10/results/r10_deter_addresses_r10.csv,
K_revision-cost/K10/k10h_output.md (seller rows, per-seller cost shares, BlockRun rows), k10h.py ADDR.
Run: python3 -I docs/11_journal/D3/d3_concentration.py  -> out/d3_results.json, out/d3_output.md
"""
import csv, gzip, hashlib, json, os, re, sys
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
J = os.path.abspath(os.path.join(HERE, '..'))
REPO = os.path.abspath(os.path.join(J, '..', '..'))
AGG = os.path.join(REPO, 'data', 'processed', 'agg_2026-10-21')
RES = os.path.join(J, 'R10', 'results')
M3 = os.path.join(J, 'R10', 'R10c', 'out')
K10 = os.path.join(J, 'K_revision-cost', 'K10')
OUT = os.path.join(HERE, 'out')
os.makedirs(OUT, exist_ok=True)

B_AT = 296297
B = B_AT / 1e6
V = 0.2
LF = 2351
RATE = {'median': 907_200, 'busy': 907_199}
WINS = ['median', 'busy']
SE = '0x325bdf6f7efab24a2210c48c1b64cab2eae1d430'
BR = '0xe9030014f5dae217d0a152f02a043567b16c1abf'
MS = ['1', '3/2', '2', '4']


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def num(x):
    return 0.0 if x in ('', None) else float(x)


lines = []
P = lines.append
res = {'registration_sha256': sha(os.path.join(HERE, 'D3_registration.md')), 'inputs': {}, 'checks': {}, 'R': {}, 'K': {}}

# ---------------- input hashes
sums = {l.split()[1].lstrip('*'): l.split()[0] for l in open(os.path.join(RES, 'SHA256SUMS.txt')) if l.strip()}
for nm in ['r10_results.json', 'r10_deter_addresses_r10.csv'] + [f'r10_addr_{c}_{w}_v0.2.csv' for c in ('main', 'overcap') for w in WINS]:
    h = sha(os.path.join(RES, nm)); assert h == sums[nm], nm; res['inputs']['R10/results/' + nm] = h
for w in WINS:
    res['inputs'][f'R10c/out/r10c_m3_addr_{w}.csv'] = sha(os.path.join(M3, f'r10c_m3_addr_{w}.csv'))
res['inputs']['K10/k10h_output.md'] = sha(os.path.join(K10, 'k10h_output.md'))
res['inputs']['agg/manifest.json'] = sha(os.path.join(AGG, 'manifest.json'))
for w in ('median', 'busy', 'quiet'):
    for k in ('pairs', 'days', 'values'):
        res['inputs'][f'agg/{k}_{w}.csv.gz'] = sha(os.path.join(AGG, f'{k}_{w}.csv.gz'))


# ---------------- seller quantities (D2 2.1)
def rd(name):
    return list(csv.DictReader(gzip.open(os.path.join(AGG, name + '.csv.gz'), 'rt', newline='')))


def seller_q(w):
    Q = {}
    edges = set()
    pairs = rd('pairs_' + w)
    for r in pairs:
        edges.add((r['recipient'].lower(), r['payer'].lower()))
    for r in pairs:
        rec, pay = r['recipient'].lower(), r['payer'].lower()
        n, v = int(r['n']), int(r['value_atomic_sum'])
        q = Q.setdefault(rec, dict(self=0, n=0, payers=0, mx=0, repeat=0, loop=0, means={}, days=0, band=0))
        if pay == rec:
            q['self'] += n; continue
        q['n'] += n; q['payers'] += 1; q['mx'] = max(q['mx'], n)
        if n >= 2: q['repeat'] += 1
        if (pay, rec) in edges: q['loop'] += 1          # r paid its payer p in the same window
        if v % n == 0:
            m = v // n; q['means'][m] = q['means'].get(m, 0) + n
    for r in rd('days_' + w):
        if int(r['n']) >= 1:
            Q.setdefault(r['recipient'].lower(), dict(self=0, n=0, payers=0, mx=0, repeat=0, loop=0, means={}, days=0, band=0))['days'] += 1
    for r in rd('values_' + w):
        if 3 <= int(r['log10_bin']) <= 5:
            Q.setdefault(r['recipient'].lower(), dict(self=0, n=0, payers=0, mx=0, repeat=0, loop=0, means={}, days=0, band=0))['band'] += int(r['n'])
    for q in Q.values():
        q['top'] = q['mx'] / q['n'] if q['n'] else float('nan')
        if q['means']:
            mstar = sorted(q['means'].items(), key=lambda t: (-t[1], t[0]))[0][0]
            q['mstar'] = mstar; q['fix'] = q['means'][mstar] / q['n']
        else:
            q['mstar'] = None; q['fix'] = 0.0
        q['mint'] = q['fix'] >= 0.90 and q['payers'] >= 100 and (q['mstar'] or 0) >= 500_000
        del q['means']
    return Q


ZERO = dict(self=0, n=0, payers=0, mx=0, repeat=0, loop=0, days=0, band=0, top=float('nan'), mstar=None, fix=0.0, mint=False)
Q = {w: seller_q(w) for w in ('median', 'busy', 'quiet')}


def passes(w, a, col, acc_count=None):
    q = Q[w].get(a, ZERO)
    if col == 'none':
        return True
    if col == 'g100':
        return q['self'] == 0 and q['loop'] == 0 and q['payers'] >= 100
    ok = (q['self'] == 0 and q['loop'] == 0 and not q['mint']
          and (acc_count >= 1 if acc_count is not None else True) and q['band'] >= 1
          and q['payers'] >= 10 and q['n'] > 0 and q['top'] <= 0.50 and q['repeat'] >= 1)
    if col == 'main':
        return ok
    return ok and q['payers'] >= 30 and q['top'] <= 0.20 and q['days'] >= 7


COLS = ['none', 'main', 'strict', 'g100']

# ---------------- R10 per-address
r10 = json.load(open(os.path.join(RES, 'r10_results.json')))


def load_addr(cfg, w):
    return {r['address'].lower(): r for r in csv.DictReader(open(os.path.join(RES, f'r10_addr_{cfg}_{w}_v0.2.csv')))}


A = {}
for w in WINS:
    main, oc = load_addr('main', w), load_addr('overcap', w)
    m3 = {r['address'].lower(): r for r in csv.DictReader(open(os.path.join(M3, f'r10c_m3_addr_{w}.csv')))}
    assert set(main) == set(oc) and len(main) == 415 and set(m3) <= set(main) and len(m3) == 414, w  # m3 covers S1 only
    A[w] = {}
    for a in main:
        A[w][a] = dict(
            scale=int(main[a]['scale']), acc_n=int(main[a]['accepted_count']),
            T=num(main[a]['accepted_value']) * LF / RATE[w] / 1e6, H=num(main[a]['H_time_average']) / 1e6,
            rev=num(main[a]['accepted_value']) / 1e6,
            Toc=num(oc[a]['accepted_value']) * LF / RATE[w] / 1e6, Hoc=num(oc[a]['H_time_average']) / 1e6,
            revoc=num(oc[a]['accepted_value']) / 1e6,
            Wv=(num(m3[a]['W_v']) / 1e6) if a in m3 else None, NB=({m: int(m3[a]['NB_' + m]) for m in MS}) if a in m3 else None)
DET = {r['address'].lower(): r for r in csv.DictReader(open(os.path.join(RES, 'r10_deter_addresses_r10.csv')))}


def metrics(w, S):
    d = A[w]; n = len(S)
    if n == 0:
        return None
    nb = n * B
    sH = sum(d[a]['H'] for a in S); sT = sum(d[a]['T'] for a in S)
    sHo = sum(d[a]['Hoc'] for a in S); sTo = sum(d[a]['Toc'] for a in S)
    L, Lo = nb + sH, nb + sHo
    x = dict(n=n, n_rev=sum(1 for a in S if d[a]['rev'] > 0), rev=sum(d[a]['rev'] for a in S),
             nb=nb, sumH=sH, sumT=sT, L=L,
             Ra=L / (nb + sT), Rb=(sH / sT) if sT > 0 else None, Rc=(L / sT) if sT > 0 else None,
             Rd=(L / (nb + sum(d[a]['Wv'] for a in S))) if all(d[a]['Wv'] is not None for a in S) else None,
             Re={m: (L / (nb + V * sum(d[a]['NB'][m] for a in S))) if all(d[a]['NB'] is not None for a in S) else None for m in MS},
             Rf=Lo / (nb + sTo), Rg=(Lo / sTo) if sTo > 0 else None, rev_oc=sum(d[a]['revoc'] for a in S))
    if w == 'median':
        dd = [DET[a] for a in S if a in DET]
        x['Rh'] = dict(n_mean_m3se_gt=sum(1 for r in dd if num(r['mean_X']) - 3 * num(r['se']) > V),
                       n_mean_gt=sum(1 for r in dd if num(r['mean_X']) > V),
                       max_mean=max((num(r['mean_X']) for r in dd), default=0.0))
    return x


ALL = {w: sorted(A[w]) for w in WINS}
S1 = {w: [a for a in ALL[w] if A[w][a]['scale'] <= 77] for w in WINS}
for w in WINS:
    assert len(S1[w]) == 414 and BR not in S1[w] and SE in S1[w]

# ---------------- reproduction checks (registration 5)
ok_all = True
for w in WINS:
    x = metrics(w, S1[w]); rg = r10['main'][w]['V']['0.2']['lock']['S1']
    roc = r10['configs']['overcap'][w]['lock']['S1']
    cks = {
        'Ra': abs(x['Ra'] - rg['rhoL_M']) / rg['rhoL_M'] < 1e-9,
        'Rd': abs(x['Rd'] - rg['rhoL_W']) / rg['rhoL_W'] < 1e-9,
        'Rf': abs(x['Rf'] - roc['rhoL_M']) / roc['rhoL_M'] < 1e-9,
        'Rc_2dp': round(x['Rc'], 2) == {'median': 7.51, 'busy': 9.11}[w],
        'Rg_2dp': round(x['Rg'], 2) == {'median': 1.53, 'busy': 3.10}[w],
    }
    for m in MS:
        cB = rg['cells']['B|' + m]
        sumC = x['nb'] + V * sum(A[w][a]['NB'][m] for a in S1[w])
        cks['sumCB_' + m] = abs(sumC - cB['sumC']) < 1e-6
        cks['ReUpper_' + m] = abs(x['Re'][m] - cB['rhoL_same_upper']) / cB['rhoL_same_upper'] < 1e-9
    if w == 'median':
        cks['Rh_zero'] = x['Rh']['n_mean_m3se_gt'] == 0 and x['Rh']['n_mean_gt'] == 10 and round(x['Rh']['max_mean'], 4) == 0.2080
    res['checks'][w] = cks
    ok_all &= all(cks.values())
res['checks']['all_ok'] = ok_all

# ---------------- variants
def topk(w, base, k, key):
    order = sorted(base, key=lambda a: (-A[w][a][key], a))
    return set(order[:k])


def var_sets(w, col):
    fil = [a for a in ALL[w] if passes(w, a, col, A[w][a]['acc_n'])]
    s = set(fil)
    out = {'ALL': sorted(s), '-SE': sorted(s - {SE}), '-BR': sorted(s - {BR}), '-both': sorted(s - {SE, BR})}
    s1 = s - {BR}
    for k in (1, 2, 5):
        out[f'-top{k}'] = sorted(s1 - topk(w, s1, k, 'rev'))
        out[f'-top{k}oc'] = sorted(s1 - topk(w, s1, k, 'revoc'))
    return out


TOP = {}
for w in WINS:
    s1 = S1[w]
    TOP[w] = {'rev': sorted(s1, key=lambda a: (-A[w][a]['rev'], a))[:10],
              'revoc': sorted(s1, key=lambda a: (-A[w][a]['revoc'], a))[:10]}
    res['R'][w] = {}
    for col in COLS:
        for vn, S in var_sets(w, col).items():
            res['R'][w][f'{col}|{vn}'] = metrics(w, S)
    # strata (registration 4), on S1, none column
    for cfg, key in (('main', 'rev'), ('overcap', 'revoc')):
        pos = sorted([a for a in S1[w] if A[w][a][key] > 0], key=lambda a: (-A[w][a][key], a))
        z = [a for a in S1[w] if A[w][a][key] == 0]
        for nm, S in (('T10', pos[:10]), ('T50', pos[10:50]), ('Trest', pos[50:]), ('Z', z)):
            res['R'][w][f'stratum|{cfg}|{nm}'] = metrics(w, S)

# filter membership of named sellers
NAMED = {'StableEnrich': SE, 'BlockRun': BR}
res['named'] = {w: {nm: {c: passes(w, a, c, A[w][a]['acc_n'] if a in A.get(w, {}) else None) for c in COLS}
                    for nm, a in NAMED.items()} for w in WINS}
res['named_q'] = {w: {nm: {k: v for k, v in Q[w].get(a, ZERO).items()} for nm, a in NAMED.items()} for w in ('median', 'busy', 'quiet')}
res['top10'] = {w: [dict(address=a, rev=A[w][a]['rev'], revoc=A[w][a]['revoc'], q=Q[w].get(a, ZERO)) for a in TOP[w]['rev']] for w in WINS}

# ---------------- K10h (registration 3, 5 K-a)
ktxt = open(os.path.join(K10, 'k10h_output.md'), encoding='utf-8').read().split('\n')
src = open(os.path.join(K10, 'k10h.py'), encoding='utf-8').read()
ADDR = dict(re.findall(r"'(StableEnrich|OneSource|CoinMarketCap|StableApify|Exa|CoinStats)': '(0x[0-9a-f]{40})'", src))
assert len(ADDR) == 6, ADDR
WMAP = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet', 'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}


def base_name(s):
    return s.split('(')[0]


REVK, CK = {}, {}
sec = None
for ln in ktxt:
    if ln.startswith('## '):
        sec = ln.split()[1]
    cells = [c.strip() for c in ln.strip().strip('|').split('|')] if ln.startswith('|') else []
    if sec == '2.' and len(cells) == 13 and cells[0] in WMAP and cells[2].isdigit():
        REVK[(cells[0], base_name(cells[1]))] = float(cells[3])
    if sec == '6.' and len(cells) == 10 and cells[0] in WMAP and cells[1] in ('0.2', '1'):
        CK[(cells[0], cells[1], base_name(cells[2]))] = dict(lo=float(cells[5]), up=float(cells[8]))
    if sec == '3.' and len(cells) >= 6 and cells[0].startswith('BlockRun(tier 1b) ') and cells[2] == '1' and cells[3] == 'none':
        w = WMAP[cells[0].split()[-1]]
        CK[(w, cells[1], 'BlockRun')] = dict(lo=float(cells[4].split('/')[0]), up=float(cells[5].split('/')[0]))
    if sec == '1.' or sec is None:
        pass
# BlockRun revenue from the top table (before section 0), busy and median only
for ln in ktxt[:60]:
    cells = [c.strip() for c in ln.strip().strip('|').split('|')] if ln.startswith('|') else []
    if len(cells) == 4 and cells[1] == 'BlockRun' and cells[0] in WMAP:
        REVK[(cells[0], 'BlockRun')] = float(cells[2].split('/')[1])
res['K']['parsed'] = dict(rev={f'{k[0]}|{k[1]}': v for k, v in REVK.items()}, cost={f'{k[0]}|{k[1]}|{k[2]}': v for k, v in CK.items()})
T01 = ['StableEnrich', 'OneSource', 'CoinMarketCap', 'StableApify', 'Exa', 'CoinStats']
ADDR['BlockRun'] = BR


def kagg(w, Vk, sellers, side):
    have = [s for s in sellers if (w, s) in REVK and (w, Vk, s) in CK]
    if len(have) < len(sellers) or not have:
        return None
    R = sum(REVK[(w, s)] for s in have)
    return sum(CK[(w, Vk, s)][side] * REVK[(w, s)] for s in have) / R if R > 0 else None


def kpass(w, s, col):
    a = ADDR[s]
    acc = A[w][a]['acc_n'] if (w in A and a in A[w]) else None
    return passes(w, a, col, acc)


for w in ('busy', 'median', 'quiet'):
    for col in ('none', 'main', 'strict', 'g100'):
        keep = [s for s in T01 if kpass(w, s, col)]
        for vn, S in (('T01t', keep), ('T01t-SE', [s for s in keep if s != 'StableEnrich']),
                      ('T01t+BR', keep + (['BlockRun'] if kpass(w, 'BlockRun', col) else [])),
                      ('T01t+BR-SE', [s for s in keep if s != 'StableEnrich'] + (['BlockRun'] if kpass(w, 'BlockRun', col) else []))):
            for Vk in ('0.2', '1'):
                for side in ('lo', 'up'):
                    res['K'][f'{w}|{col}|{vn}|V{Vk}|{side}'] = dict(sellers=S, share=kagg(w, Vk, S, side))
# reproduction of the T01t aggregate ranges (k10h_output.md sec. 4)
exp = {('1', 'lo'): (0.042, 0.051), ('0.2', 'lo'): (0.070, 0.073), ('1', 'up'): (0.060, 0.074), ('0.2', 'up'): (0.089, 0.099)}
for (Vk, side), (lo, hi) in exp.items():
    vals = [res['K'][f'{w}|none|T01t|V{Vk}|{side}']['share'] for w in ('busy', 'median', 'quiet')]
    # inputs are printed to 4 decimals (shares) and 2 decimals (revenue), so the check allows 0.001 (deviation D3-1)
    res['checks'][f'K T01t V{Vk} {side}'] = abs(min(vals) - lo) <= 0.001 and abs(max(vals) - hi) <= 0.001
    res['checks'][f'K T01t V{Vk} {side} values'] = [round(min(vals), 5), round(max(vals), 5)]
res['checks']['all_ok'] = res['checks']['all_ok'] and all(v for k, v in res['checks'].items() if k.startswith('K ') and not k.endswith('values'))
res['K']['membership'] = {w: {s: {c: kpass(w, s, c) for c in COLS} for s in T01 + ['BlockRun']} for w in ('busy', 'median', 'quiet')}
res['K']['seller_q'] = {w: {s: Q[w].get(ADDR[s], ZERO) for s in T01 + ['BlockRun']} for w in ('busy', 'median', 'quiet')}

json.dump(res, open(os.path.join(OUT, 'd3_results.json'), 'w'), indent=1, ensure_ascii=False, default=str)

# ---------------- text output
def f(x, d=4):
    return '-' if x is None else (f'{x:.{d}f}')


P('# D3 output (d3_concentration.py)\n')
P(f"registration SHA-256 {res['registration_sha256']}\n")
P('## reproduction check\n')
for k, v in res['checks'].items():
    P(f'- {k}: {v}')
P('')
for w in WINS:
    P(f'## R10, {w}\n')
    P('| cell | n | revenue with n | upper within revenue | R-a ρ_L^M | R-b ΣH/ΣT | R-c L/ΣT | R-d ρ_L^W | R-e B(1) | R-e B(4) | R-f oc ρ^M | R-g oc L/ΣT | R-h |')
    P('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for k, x in res['R'][w].items():
        if x is None:
            P(f'| {k} | 0 | | | | | | | | | | | |'); continue
        rh = x.get('Rh'); rhs = f"{rh['n_mean_m3se_gt']} / {rh['n_mean_gt']} / {rh['max_mean']:.4f}" if rh else ''
        P(f"| {k} | {x['n']} | {x['n_rev']} | {x['rev']:.2f} | {f(x['Ra'])} | {f(x['Rb'])} | {f(x['Rc'], 2)} | {f(x['Rd'])} | "
          f"{f(x['Re']['1'])} | {f(x['Re']['4'])} | {f(x['Rf'])} | {f(x['Rg'], 2)} | {rhs} |")
    P('')
P('## K10h pooled cost share (σ 1, w 0.00173, carry-over none)\n')
P('| window | column | set | seller | V 0.2 lower | V 0.2 upper | V 1 lower | V 1 upper |')
P('|---|---|---|---|---|---|---|---|')
for w in ('busy', 'median', 'quiet'):
    for col in COLS:
        for vn in ('T01t', 'T01t-SE', 'T01t+BR', 'T01t+BR-SE'):
            g = lambda Vk, s: res['K'][f'{w}|{col}|{vn}|V{Vk}|{s}']['share']
            S = res['K'][f'{w}|{col}|{vn}|V1|lo']['sellers']
            P(f"| {w} | {col} | {vn} | {', '.join(S)} | {f(g('0.2','lo'))} | {f(g('0.2','up'))} | {f(g('1','lo'))} | {f(g('1','up'))} |")
P('')
P('## name named seller filter both\n')
for w in ('median', 'busy', 'quiet'):
    for s in T01 + ['BlockRun']:
        q = Q[w].get(ADDR[s], ZERO)
        P(f"- {w} {s}: self {q['self']}, n {q['n']}, payers {q['payers']}, top {f(q['top'], 3)}, repeat {q['repeat']}, loop {q['loop']}, "
          f"days {q['days']}, band {q['band']}, mint {q['mint']} | " + ', '.join(f'{c} {res["K"]["membership"][w][s][c]}' for c in COLS))
P('')
P('## top 10 (main upper within revenue order)\n')
for w in WINS:
    for t in res['top10'][w]:
        q = t['q']
        P(f"- {w} {t['address']}: rev {t['rev']:.2f}, oc rev {t['revoc']:.2f}, payers {q['payers']}, top {f(q['top'], 3)}, self {q['self']}, loop {q['loop']}, days {q['days']}, mint {q['mint']} | "
          + ', '.join(f'{c} {passes(w, t["address"], c, A[w][t["address"]]["acc_n"])}' for c in COLS))
open(os.path.join(OUT, 'd3_output.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('\n'.join(lines[:12]))
print('checks all_ok', res['checks']['all_ok'])
