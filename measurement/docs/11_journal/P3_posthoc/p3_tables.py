#!/usr/bin/env python3
"""P3 tables from results/p3.json (post hoc).   python3 -I p3_tables.py results"""
import json, sys
from pathlib import Path
OUT = Path(sys.argv[1]); R = json.load(open(OUT / 'p3.json'))
PER = ['busy', 'median', 'quiet']; WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}
LN = {'lo': 'lower', 'up': 'upper', 'fac': 'facilitator'}
TN = {'RS3': '1a', 'SP0': '0', 'TEE': '1b TEE'}
def pc(x): return '%.2f' % (100 * x)
def rng(xs): return '%s–%s' % (pc(min(xs)), pc(max(xs)))
def ws(x): return x if isinstance(x, str) else '%.3g' % x
def wrng(xs):
    if all(not isinstance(x, str) for x in xs): return '%.3g–%.3g' % (min(xs), max(xs))
    return '/'.join(ws(x) for x in xs)
L = ['**post hoc. registration verdict none.** P3 bundle D Table (`p3.py`, `p3_tables.py`). mode N, σ 1, r 10%, w 0.00173, per seller optimal k. costs revenue relative to %.\n']
M = R['meta']
L.append('k11b_output.md reproduction: %s. REL_M 2,930 (b) path put in value = original value: %s. (c) path reference price = (b): %s.\n' % (
    M['k11b_reproduced'], M['relm2930_equal'], M['grid_base_equal']))

# ---------------- (a)
L.append('## 1. (a) full inspection FI vs FairBind (V 1)\n')
L.append('### 1.1 sum and seller count\n')
L.append('| variant | window | case | FB V 1 sum | FB V 0.2 sum | FI sum | FI proof only | per seller cheaper side mixed | FI cheaper seller (six among) | its revenue share | FI cheaper seller | BlockRun FB V 1 (k) | BlockRun FI (k) |')
L.append('|' + '---|' * 13)
for var, nm in (('FI', 'main'), ('FI_min', 'FI-min'), ('FI_W', 'FI-W'), ('FI_na', 'FI-b')):
    for p in PER:
        for lab in ('lo', 'up', 'fac'):
            c = R[var]['%s|%s' % (p, lab)]
            br = c['br'][0] if c['br'] else None
            L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %d | %s | %s | %s | %s |' % (
                nm, WN[p], LN[lab], pc(c['agg_fb']), pc(c['agg_fb02']), pc(c['agg_fi']), pc(c['agg_fi_proof']), pc(c['agg_mix']),
                c['n_fi_cheaper'], pc(c['share_fi_cheaper']), ', '.join(c['fi_cheaper']) or 'none',
                ('%s (%d)' % (pc(br['fb']), br['fb_k'])) if br else '-', ('%s (%d)' % (pc(br['fi']), br['fi_k'])) if br else '-'))
L.append('\n### 1.2 per seller (main, lower, V 1)\n')
L.append('| window | seller | tier | revenue (USDC) | sales count n | q = n_s/n | per sale proof c_P (USD) | per sale anchor gas | per sale anchor and random value (USD) | ρ = (1−q)c_P / anchor and random value | FB (k) | FI (k) | cheaper side | difference FB − FI (%p) |')
L.append('|' + '---|' * 14)
for p in PER:
    for r in R['FI']['%s|lo' % p]['rows']:
        L.append('| %s | %s | %s | %.2f | %d | %.4f | %.6f | %.0f | %.6f | %.3f | %s (%d) | %s (%d) | %s | %+.2f |' % (
            WN[p], r['a'], TN[r['ck']], r['R'], r['n'], r['q'], r['cpfi'], r['anc_gas_per_sale'], r['anc_vrf_per_sale'], r['rho'],
            pc(r['fb']), r['fb_k'], pc(r['fi']), r['fi_k'], 'FI' if r['fi'] < r['fb'] else 'FB', 100 * (r['fb'] - r['fi'])))
L.append('\n### 1.3 component (main, lower, V 1, per seller revenue relative to %)\n')
keys_fb = ['verify', 'anchor', 'sampvrf', 'release', 'l1', 'frozen', 'deduct', 'capital']
keys_fi = ['verify', 'release', 'l1', 'deduct', 'capital']
L.append('| window | seller | FB: ' + ' | '.join(keys_fb) + ' | FI: ' + ' | '.join(keys_fi) + ' |')
L.append('|' + '---|' * (2 + len(keys_fb) + len(keys_fi)))
for p in PER:
    for r in R['FI']['%s|lo' % p]['rows']:
        L.append('| %s | %s | %s | %s |' % (WN[p], r['a'], ' | '.join(pc(r['fb_parts'].get(k, 0.0)) for k in keys_fb),
                                            ' | '.join(pc(r['fi_parts'].get(k, 0.0)) for k in keys_fi)))
L.append('\n### 1.4 per seller cheaper side (main, upper and facilitator)\n')
L.append('| window | case | ' + ' | '.join(r['a'] for r in R['FI']['busy|lo']['rows']) + ' |')
L.append('|---|---|' + '---|' * len(R['FI']['busy|lo']['rows']))
for p in PER:
    for lab in ('lo', 'up', 'fac'):
        rows = R['FI']['%s|%s' % (p, lab)]['rows']
        L.append('| %s | %s | %s |' % (WN[p], LN[lab], ' | '.join('%s / %s %s' % (pc(r['fb']), pc(r['fi']), 'FI' if r['fi'] < r['fb'] else 'FB') for r in rows)))

# ---------------- (b)
def t4rows(name, c, base=None):
    out = []
    for V in (1.0, 0.2):
        f = lambda lab, key, kind='T01t', per=PER: [c['%s|%g|%s|%s' % (kind, V, p, lab)][key] for p in per]
        le = [sum(x <= 0.10 for x in f(lab, 'agg')) for lab in ('lo', 'up', 'fac')]
        flag = ''
        if base is not None:
            ch = []
            for lab in ('lo', 'up', 'fac'):
                for p in PER:
                    a = c['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10; b = base['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10
                    if a != b: ch.append('%s %s %s' % (LN[lab], WN[p], 'exceeds' if b else 'within'))
            flag = '; '.join(ch) if ch else 'none'
        out.append('| %s | %g | %s | %s | %s | %s (%s) | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %d / %d / %d | %s |' % (
            name, V, rng(f('lo', 'agg')), rng(f('up', 'agg')), rng(f('fac', 'agg')), rng(f('lo', 'se')), ','.join(str(x) for x in f('lo', 'se_k')),
            rng(f('up', 'se')), rng(f('fac', 'se')), rng(f('lo', 'med')), rng(f('up', 'med')), rng(f('fac', 'med')),
            ', '.join(str(x) for x in f('lo', 'n_le10')) + ' / ' + ', '.join(str(x) for x in f('fac', 'n_le10')),
            wrng(f('lo', 'wstar')) if 'wstar' in c['T01t|%g|busy|lo' % V] else '-', wrng(f('up', 'wstar')) if 'wstar' in c['T01t|%g|busy|up' % V] else '-',
            rng(f('lo', 'agg', 'BR', PER[:2])) + ' (quiet %s)' % pc(c['BR|%g|quiet|lo' % V]['agg']),
            rng(f('up', 'agg', 'BR', PER[:2])), rng(f('fac', 'agg', 'BR', PER[:2])), le[0], le[1], le[2], flag))
    return out
HDR = ('| model | V | sum lower | sum upper | sum facil | StableEnrich lower (k) | StableEnrich upper | StableEnrich facil | median lower | median upper | median facil | '
       '10% within count lower / facil (busy, median, quiet) | w* lower | w* upper | BlockRun lower (busy, median) | BlockRun upper | BlockRun facil | sum ≤ 10% window count lower / upper / facil | original value relative to 10% verdict changed cell |')
L.append('\n## 2. (b) per sale release gas 16,800 (Table 4 main cell, range three window)\n')
L.append(HDR); L.append('|' + '---|' * 20)
for name, key in (('original value (K11b)', 'orig'), ('(b) REL_M 16,800', 'na'), ("(b') REL_K −800", 'na1'), ('(b+) scan and tier 0 correction', 'na_plus')):
    L += t4rows(name, R[key], None if key == 'orig' else R['orig'])
L.append('\n### 2.1 per window sum (V 1)\n')
L.append('| model | window | sum lower | sum upper | sum facil | StableEnrich lower (k) | OneSource lower (k) | BlockRun lower (k) |')
L.append('|---|---|---|---|---|---|---|---|')
for name, key in (('original value', 'orig'), ('(b)', 'na'), ("(b')", 'na1'), ('(b+)', 'na_plus')):
    for p in PER:
        c = R[key]; lo = c['T01t|1|%s|lo' % p]; os_ = lo['per']['OneSource']; br = c['BR|1|%s|lo' % p]['per']['BlockRun']
        L.append('| %s | %s | %s | %s | %s | %s (%d) | %s (%d) | %s (%d) |' % (name, WN[p], pc(lo['agg']), pc(c['T01t|1|%s|up' % p]['agg']),
                 pc(c['T01t|1|%s|fac' % p]['agg']), pc(lo['se']), lo['se_k'], pc(os_[0]), os_[1], pc(br[0]), br[1]))

# ---------------- (c)
L.append('\n## 3. (c) price sensitivity ((b) model)\n')
L.append('effective L2 price p = base fee + (multiple − 1) × 0.005 gwei. mark: † reference (0.005, 2,401.44, 2.0) (b) and compared with window sum ≤ 10% verdict changed cell.\n')
L.append('### 3.1 one at a time changed row\n')
L.append(HDR.replace('original value relative to', '(b) reference relative to')); L.append('|' + '---|' * 20)
base = R['sens']['0.005|2401.44|2']['cells']
for key in ('0.005|2401.44|2', '0.01|2401.44|2', '0.02|2401.44|2', '0.005|1840|2', '0.005|2742|2', '0.005|2401.44|1.5', '0.005|2401.44|2.5'):
    bf, eth, m = key.split('|')
    p_ = float(bf) + (float(m) - 1) * 0.005
    L += t4rows('bf %s, ETH %s, m %s (p %.4g)' % (bf, eth, m, p_), R['sens'][key]['cells'], base)
L.append('\n### 3.2 27 combinations (per window busy / median / quiet)\n')
L.append('| base fee | ETH | multiple | p (gwei) | sum V 1 lower | sum V 1 upper | sum V 1 facil | sum V 0.2 lower | sum V 0.2 upper | 10% within count V 1 lower | StableEnrich V 1 lower | BlockRun V 1 lower | FI cheaper seller count lower (FI-b) | changed cell count (b reference) | changed cell count (original value reference) |')
L.append('|' + '---|' * 15)
orig = R['orig']
for key, v in R['sens'].items():
    bf, eth, m = key.split('|'); c = v['cells']
    def cell(V, lab):
        out = []
        for p in PER:
            x = c['T01t|%g|%s|%s' % (V, p, lab)]['agg']
            mk = '†' if (x <= 0.10) != (base['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10) else ''
            out.append(pc(x) + mk)
        return ' / '.join(out)
    nch = sum((c['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10) != (base['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10)
              for V in (1.0, 0.2) for p in PER for lab in ('lo', 'up', 'fac'))
    nch0 = sum((c['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10) != (orig['T01t|%g|%s|%s' % (V, p, lab)]['agg'] <= 0.10)
               for V in (1.0, 0.2) for p in PER for lab in ('lo', 'up', 'fac'))
    L.append('| %s | %s | %s | %.4g | %s | %s | %s | %s | %s | %s | %s | %s | %s | %d | %d |' % (
        bf, eth, m, float(bf) + (float(m) - 1) * 0.005, cell(1.0, 'lo'), cell(1.0, 'up'), cell(1.0, 'fac'), cell(0.2, 'lo'), cell(0.2, 'up'),
        ', '.join(str(c['T01t|1|%s|lo' % p]['n_le10']) for p in PER), ' / '.join(pc(c['T01t|1|%s|lo' % p]['se']) for p in PER),
        ' / '.join(pc(c['BR|1|%s|lo' % p]['agg']) for p in PER), ', '.join(str(v['fi_cheaper']['%s|lo' % p]) for p in PER), nch, nch0))
(OUT / 'p3_tables.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
print('wrote', OUT / 'p3_tables.md')

# ---------------- (a) supplements: tier groups and break-even proof gas (lower case)
GUSD1 = 0.010e-9 * 2401.44                     # USD per gas at the base price (K11b g10b basis, multiplier 2.0)
L1W = {'RS3': 2_132_754_915, 'SP0': 28_173_828_378, 'TEE': 2_157_333_560}
GAS = {'RS3': 86_824, 'SP0': 604_522 + 5_000, 'TEE': 36_440}
X = ['\n## 4. (a) supplement: per tier bundle and split proof gas\n']
X.append('### 4.1 per tier bundle (main, Σcost / Σrevenue)\n')
X.append('| variant | window | case | tier 1a five: FB | FI | FI cheaper count / 5 | FI cheaper revenue share | tier 0 OneSource: FB | FI | TEE BlockRun: FB | FI |')
X.append('|' + '---|' * 11)
SUPP = {}
for var, nm in (('FI', 'main'), ('FI_min', 'FI-min'), ('FI_W', 'FI-W'), ('FI_na', 'FI-b')):
    for p in PER:
        for lab in ('lo', 'up', 'fac'):
            rows = R[var]['%s|%s' % (p, lab)]['rows']
            a = [r for r in rows if r['ck'] == 'RS3']; o = [r for r in rows if r['ck'] == 'SP0'][0]; b = [r for r in rows if r['ck'] == 'TEE'][0]
            Ra = sum(r['R'] for r in a); ch = [r for r in a if r['fi'] < r['fb']]
            fa = sum(r['fb'] * r['R'] for r in a) / Ra; ia = sum(r['fi'] * r['R'] for r in a) / Ra
            SUPP['%s|%s|%s' % (var, p, lab)] = dict(t1a_fb=fa, t1a_fi=ia, t1a_n=len(ch), t1a_share=sum(r['R'] for r in ch) / Ra)
            X.append('| %s | %s | %s | %s | %s | %d | %s | %s | %s | %s | %s |' % (nm, WN[p], LN[lab], pc(fa), pc(ia), len(ch), pc(sum(r['R'] for r in ch) / Ra),
                     pc(o['fb']), pc(o['fi']), pc(b['fb']), pc(b['fi'])))
X.append('\n### 4.2 split proof price (main, lower, V 1)\n')
X.append('two design same proof price c uses if set Δ(c) = C_FB − C_FI = [(C_FB − n_s c_P) − (C_FI − n c_P)] − (n − n_s)(c − c_P), FI becomes cheaper boundary c* = c_P + Δ(c_P) / (n − n_s). g* c* proof L1 share(and tier 0 history read 5,000 gas) without 0.010 gwei, 2,401.44 USD gas changed value. FairBind chosen k and FI chosen k c not rely so(proof term k and independent) this boundary is exact. measured proof gas g_P g* than if small FI cheaper.\n')
X.append('| window | seller | tier | g_P (measured) | g* (split) | g_P / g* | per sale anchor gas | per sale anchor and random value (gas converted) | ρ |')
X.append('|---|---|---|---|---|---|---|---|---|')
for p in PER:
    for r in R['FI']['%s|lo' % p]['rows']:
        fbv = r['fb_parts']['verify'] * r['R']; fiv = r['fi_parts']['verify'] * r['R']
        assert abs(fiv - r['n'] * r['cpfi']) < 1e-9 * max(1, fiv) and abs(fbv - r['ns'] * r['cpfb']) < 1e-9 * max(1, fbv)
        d = (r['fb'] - r['fi']) * r['R']
        cstar = r['cpfi'] + d / (r['n'] - r['ns'])
        l1 = L1W[r['ck']] * 1e-18 * 2401.44
        assert abs(r['cpfi'] - (GAS[r['ck']] * GUSD1 + l1)) < 1e-12, (r['a'], r['cpfi'])
        gstar = (cstar - l1) / GUSD1 - (5_000 if r['ck'] == 'SP0' else 0)
        gp = GAS[r['ck']] - (5_000 if r['ck'] == 'SP0' else 0)
        SUPP['gstar|%s|%s' % (p, r['a'])] = gstar
        X.append('| %s | %s | %s | %s | %s | %.2f | %.0f | %.0f | %.3f |' % (WN[p], r['a'], TN[r['ck']], format(gp, ','), format(int(round(gstar)), ','), gp / gstar if gstar > 0 else float('inf'),
                 r['anc_gas_per_sale'], r['anc_vrf_per_sale'] / GUSD1, r['rho']))
(OUT / 'p3_tables.md').write_text((OUT / 'p3_tables.md').read_text(encoding='utf-8') + '\n'.join(X) + '\n', encoding='utf-8')
json.dump(SUPP, open(OUT / 'p3_supp.json', 'w'), indent=1, ensure_ascii=False)
print('appended sec. 4')

# ---------------- (a) seven sellers (six data sellers and BlockRun)
Y = ['\n### 4.3 seven seller(six and BlockRun) sum (Σcost / Σrevenue)\n',
     '| variant | window | case | seven revenue (USDC) | FB V 1 | FI | mixed | FI cheaper count / 7 | its revenue share |', '|' + '---|' * 9]
for var, nm in (('FI', 'main'), ('FI_min', 'FI-min'), ('FI_W', 'FI-W'), ('FI_na', 'FI-b')):
    for p in PER:
        for lab in ('lo', 'up', 'fac'):
            rows = R[var]['%s|%s' % (p, lab)]['rows']; T = sum(r['R'] for r in rows); ch = [r for r in rows if r['fi'] < r['fb']]
            Y.append('| %s | %s | %s | %.2f | %s | %s | %s | %d | %s |' % (nm, WN[p], LN[lab], T, pc(sum(r['fb'] * r['R'] for r in rows) / T),
                     pc(sum(r['fi'] * r['R'] for r in rows) / T), pc(sum(min(r['fb'], r['fi']) * r['R'] for r in rows) / T), len(ch), pc(sum(r['R'] for r in ch) / T)))
(OUT / 'p3_tables.md').write_text((OUT / 'p3_tables.md').read_text(encoding='utf-8') + '\n'.join(Y) + '\n', encoding='utf-8')
