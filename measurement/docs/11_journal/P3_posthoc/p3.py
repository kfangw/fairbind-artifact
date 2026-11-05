#!/usr/bin/env python3
"""P3 bundle D (post hoc, calc-rules.md): full inspection against FairBind, measured per-sale release gas, price sensitivity.

K11/k11b.py is read and executed unchanged in its own namespace (only its final output write is redirected) and the
reproduction of k11b_output.md is checked byte for byte. Variants are added by subclassing Grid and by overriding
constants in that namespace.
  (a) FI: hold every sale, one proof call per sale, pay through the same cursor with every sale proven, refund only
       the failed sale; no anchor, no VRF, no freeze, no deduction (calc-rules.md sec. 1).
  (b) per-sale release gas REL_M 2,930 -> 16,800 (SDK/k-multiple_implementation.md 5.3), capacity from the same formula.
  (c) base fee x ETH x multiplier grid on the (b) model.

    python3 -I p3.py --out results
"""
import argparse, json, math, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
K11 = HERE.parent / 'K11'
ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
ARGS = ap.parse_args()
OUT = Path(ARGS.out); OUT.mkdir(parents=True, exist_ok=True)
T0 = time.time()

# ---------------------------------------------------------------- run k11b.py unchanged
src = (K11 / 'k11b.py').read_text(encoding='utf-8')
a1 = "HERE = os.path.dirname(os.path.abspath(__file__))"
a2 = "open(HERE + '/k11b_output.md', 'w').write(txt)"
assert src.count(a1) == 1 and src.count(a2) == 1
src = src.replace(a1, "HERE = %r" % str(K11)).replace(a2, "_P3_TXT = txt")
g = {'__name__': 'k11b_p3'}
exec(compile(src, str(K11 / 'k11b.py'), 'exec'), g)
REPRO = g['_P3_TXT'] == (K11 / 'k11b_output.md').read_text(encoding='utf-8')
print('k11b_output.md reproduced byte for byte:', REPRO, '%.0fs' % (time.time() - T0), flush=True)
assert REPRO

KS = g['KS']; W0 = g['W0']; PER = ['busy', 'median', 'quiet']
Grid0 = g['Grid']
BASE = {n: g[n] for n in ('REL_M', 'REL_K')}
BASE_CPG = {k: tuple(v) for k, v in g['CPG'].items()}; BASE_SP0_UP = g['SP0_UP']
FB_SHARE = 86_824 - 31_315                       # FairBind part of the measured tier-1a call (K11b sens. W)
assert g['CPG']['RS3'][0] == 86_824 and g['CPG']['TEE'][0] == 36_440 and g['CPG']['SP0'][0] == 604_522
G_SW = (136_567 - 43_548) / 31; SP0_ADD = 74_631 + 9_640; SP0_L1F = (5_700 + 1_216) / 5_700
VAR = dict(sw=False)


# ---------------------------------------------------------------- FairBind grid with the P2 b1 sweep switch
class GridFB(Grid0):
    def _c0(self):
        parts = super()._c0()
        if VAR['sw'] and self.prm.mode == 'k10d':
            kk = np.array(KS, float)[:, None]
            parts['sweep'] = self.prm.gusd(G_SW * kk * self.E) / self.R[None, :]
        return parts
g['Grid'] = GridFB


# ---------------------------------------------------------------- full inspection FI (calc-rules.md 1.1)
class GridFI(Grid0):
    FIMIN = False
    def __init__(self, st, V, prm, fimin=False):
        self.FIMIN = fimin
        super().__init__(st, V, prm)
        if not self.ok: return
        cap = float(math.floor((g['TX_CAP'] - g['REL_F'][prm.rd]) / (g['REL_M'] + g['REL_K'])))   # q = 1
        self.capR = np.full(self.N, cap)
        for i, k in enumerate(KS):
            for j, s in enumerate(self.S):
                if s['cnt'] is not None: self.Ur[i, j] = g['splits_from_counts'](s['cnt'], k, cap)
                else: self.Ur[i, j] = g['splits_bound'](s['n'], self.E[i, j], s['m1'], k, cap)
        self.c0parts = self._c0(); self.c0 = sum(self.c0parts.values())

    def _c0(self):
        prm, R, n, E = self.prm, self.R, self.n, self.E
        cp = self.cp.copy()
        if self.FIMIN: cp = cp - np.array([0.0 if c == 'TEE' else prm.gusd(FB_SHARE) for c in self.ck])
        self.cp_fi = cp
        parts = {'verify': np.broadcast_to(cp * n / R, E.shape).copy()}
        if prm.up and prm.curpe: Ru = np.broadcast_to((E[0] + self.Ur[0])[None, :], E.shape).copy()
        else: Ru = E + self.Ur
        self.Ru = Ru; self.Ep = np.broadcast_to(E[0][None, :], E.shape).copy()
        rd = prm.rd
        parts['release'] = prm.gusd(Ru * g['REL_F'][rd] + g['REL_M'] * n[None, :] + g['REL_K'] * n[None, :]) / R
        parts['l1'] = prm.wusd(Ru * g['RW_F'] + g['RW_M'] * n[None, :]) / R
        if prm.fac:
            Ef = np.minimum(self.Ep if prm.fpe else E, n[None, :])
            parts['facil'] = prm.gusd(Ef * g['SETTLE'][rd]['first'] + (n[None, :] - Ef) * g['SETTLE'][rd]['later']) / R
        if prm.up:
            parts['detincl'] = np.broadcast_to(prm.gusd(g['G_DET'] * n) / R, E.shape).copy()
        return parts

    def loss(self, w):
        frz = np.zeros_like(self.E)
        ded = np.full_like(self.E, w)                       # refund of the failed sale only
        if self.prm.up: ded = ded + w * self.n[None, :] * self.prm.gusd(g['G_FAIL']) / self.R[None, :]
        return frz, ded

    def cap(self, r):
        H = np.array([300 * k + self.prm.TP for k in KS], float)[:, None]
        return np.broadcast_to(r * H / self.Wb * (self.days / 365.0), self.E.shape).copy()


def setvar(relm=None, relk=None, sw=False, sp0=False, tee=None):
    g['REL_M'] = BASE['REL_M'] if relm is None else relm
    g['REL_K'] = BASE['REL_K'] if relk is None else relk
    VAR['sw'] = sw
    cpg = dict(BASE_CPG)
    if sp0: cpg['SP0'] = (BASE_CPG['SP0'][0] + SP0_ADD, BASE_CPG['SP0'][1] * SP0_L1F)
    if tee is not None: cpg['TEE'] = (tee, BASE_CPG['TEE'][1])
    g['CPG'].clear(); g['CPG'].update(cpg)
    g['SP0_UP'] = BASE_SP0_UP + (SP0_ADD if sp0 else 0)
    g['_G'].clear()


def basis(bf, eth):
    key = 'p3_%g_%g' % (bf, eth)
    g['BASIS'][key] = (bf, eth); return key


def PRM(lab, bk='g10b', mult=2.0):
    if lab == 'lo': return g['LOm']('N', basis=bk, mult=mult)
    if lab == 'up': return g['UPm']('N', basis=bk, mult=mult)
    return g['LOm']('N', True, basis=bk, mult=mult)


LABS = ('lo', 'up', 'fac')
def FB(st, V, prm): return g['G'](st, V, prm)


def fb_cells(bk='g10b', mult=2.0, wstar=True):
    o = {}
    for V in (1.0, 0.2):
        for p in PER:
            for kind in ('T01t', 'BR'):
                st = kind + ':' + p
                for lab in LABS:
                    gr = FB(st, V, PRM(lab, bk, mult))
                    if not gr.ok: continue
                    r = gr.opt(W0)
                    c = dict(agg=r['agg'], med=r['med'], n_le10=int((r['tot'] <= 0.10).sum()), N=gr.N, R=float(gr.R.sum()),
                             per={gr.a_[i]: [float(r['tot'][i]), int(KS[r['ki'][i]])] for i in range(gr.N)})
                    if kind == 'T01t':
                        j = [i for i, a in enumerate(gr.a_) if a.startswith('StableEnrich')][0]
                        c['se'] = float(r['tot'][j]); c['se_k'] = int(KS[r['ki'][j]])
                    if wstar and lab in ('lo', 'up'):
                        ws = gr.wstar('agg'); c['wstar'] = ws if isinstance(ws, str) else float(ws)
                    o['%s|%g|%s|%s' % (kind, V, p, lab)] = c
    return o


# ---------------------------------------------------------------- (a) per-seller comparison
def compare(bk='g10b', mult=2.0, fimin=False, detail=True):
    o = {}
    for p in PER:
        for lab in LABS:
            prm = PRM(lab, bk, mult)
            rows = []
            for kind in ('T01t', 'BR'):
                st = kind + ':' + p
                fb = FB(st, 1.0, prm)
                if not fb.ok: continue
                fb02 = FB(st, 0.2, prm)
                fi = GridFI(st, 1.0, prm, fimin=fimin)
                rfb = fb.opt(W0); rfi = fi.opt(W0); r02 = fb02.opt(W0)
                dfb = fb.comp(W0)[2] if detail else None
                for j in range(fb.N):
                    kb, kf = rfb['ki'][j], rfi['ki'][j]
                    R = float(fb.R[j]); n = float(fb.n[j]); ns = float(fb.ns[j]); q = ns / n
                    row = dict(kind=kind, a=fb.a_[j], ck=fb.ck[j], R=R, n=n, ns=ns, q=q,
                               fb=float(rfb['tot'][j]), fb_k=int(KS[kb]), fb02=float(r02['tot'][j]),
                               fi=float(rfi['tot'][j]), fi_k=int(KS[kf]),
                               fi_verify=float(fi.c0parts['verify'][kf, j]), cpfi=float(fi.cp_fi[j]), cpfb=float(fb.cp[j]))
                    if detail:
                        fbp = {k: float(v[j]) for k, v in dfb.items()}
                        fip = {k: float(v[kf, j]) for k, v in fi.c0parts.items()}
                        frz, ded = fi.loss(W0); fip['deduct'] = float(ded[kf, j]); fip['capital'] = float(fi.cap(0.10)[kf, j]); fip['frozen'] = 0.0
                        row['fb_parts'] = fbp; row['fi_parts'] = fip
                        anc_vrf_usd = (fbp['anchor'] + fbp['sampvrf']) * R          # USD over the window
                        row['A'] = float(fb.Ap[kb, j]); row['Ep'] = float(fb.Ep[kb, j]); row['x'] = n / row['A']
                        row['anc_vrf_per_sale'] = anc_vrf_usd / n
                        row['rho'] = (1 - q) * row['cpfi'] / row['anc_vrf_per_sale']
                        row['anc_gas_per_sale'] = float(fbp['anchor'] * R / n / prm.gusd(1.0))
                    rows.append(row)
            six = [r for r in rows if r['kind'] == 'T01t']
            RS = sum(r['R'] for r in six)
            cheaper = [r for r in six if r['fi'] < r['fb']]
            o['%s|%s' % (p, lab)] = dict(
                rows=rows, agg_fb=sum(r['fb'] * r['R'] for r in six) / RS, agg_fb02=sum(r['fb02'] * r['R'] for r in six) / RS,
                agg_fi=sum(r['fi'] * r['R'] for r in six) / RS, agg_mix=sum(min(r['fb'], r['fi']) * r['R'] for r in six) / RS,
                agg_fi_proof=sum(r['fi_verify'] * r['R'] for r in six) / RS,
                n_fi_cheaper=len(cheaper), share_fi_cheaper=sum(r['R'] for r in cheaper) / RS, R6=RS,
                fi_cheaper=[r['a'] for r in cheaper],
                br=[dict((k, r[k]) for k in ('fb', 'fi', 'fb02', 'fb_k', 'fi_k')) for r in rows if r['kind'] == 'BR'])
    return o


RES = {'meta': dict(k11b_reproduced=REPRO, FB_SHARE=FB_SHARE, REL_M0=BASE['REL_M'], REL_K0=BASE['REL_K'], W0=W0)}

# pass: original cells
setvar(); RES['orig'] = fb_cells(); print('orig', '%.0fs' % (time.time() - T0), flush=True)
setvar(relm=2_930); chk = fb_cells(wstar=False)
RES['meta']['relm2930_equal'] = all(abs(chk[k]['agg'] - RES['orig'][k]['agg']) == 0 for k in chk)
# (a)
setvar(); RES['FI'] = compare(); print('FI', '%.0fs' % (time.time() - T0), flush=True)
RES['FI_min'] = compare(fimin=True)
setvar(tee=36_440 + FB_SHARE); RES['FI_W'] = compare()
setvar(relm=16_800); RES['FI_na'] = compare()
# (b)
setvar(relm=16_800); RES['na'] = fb_cells(); print('na', '%.0fs' % (time.time() - T0), flush=True)
setvar(relm=16_800, relk=-800); RES['na1'] = fb_cells()
setvar(relm=16_800, sw=True, sp0=True); RES['na_plus'] = fb_cells()
# (c)
setvar(relm=16_800)
bk0 = basis(0.005, 2401.44)
c0 = fb_cells(bk0, 2.0, wstar=False)
RES['meta']['grid_base_equal'] = all(c0[k]['agg'] == RES['na'][k]['agg'] for k in c0)
RES['sens'] = {}
for bf in (0.005, 0.010, 0.020):
    for eth in (1840.0, 2401.44, 2742.0):
        for m in (1.5, 2.0, 2.5):
            bk = basis(bf, eth)
            one = sum([bf != 0.005, eth != 2401.44, m != 2.0]) <= 1
            cell = fb_cells(bk, m, wstar=one)
            cmp_ = compare(bk, m, detail=False)
            RES['sens']['%g|%g|%g' % (bf, eth, m)] = dict(cells=cell, fi_cheaper={k: v['n_fi_cheaper'] for k, v in cmp_.items()},
                                                          fi_share={k: v['share_fi_cheaper'] for k, v in cmp_.items()})
    print('sens bf', bf, '%.0fs' % (time.time() - T0), flush=True)
setvar()
print('meta', RES['meta'], flush=True)
json.dump(RES, open(OUT / 'p3.json', 'w'), indent=1, ensure_ascii=False)
print('wrote p3.json', '%.0fs' % (time.time() - T0))
