#!/usr/bin/env python3
"""P6 (post hoc, calc-rules.md): honest sellers that the deposit-only interval of 2026-06-25 (BASE1 post hoc query,
supp_body.tex supp:base1) would have failed.

Canonical Base L2 blocks GAP = [47,806,547, 47,808,825] (2,279 blocks) contain only deposit transactions, so no
seller transaction (anchor unit, proof) could be included. For the cost-model sellers of the busy window (set T01t,
six classified data sellers, and BlockRun, set BR), normal mode N, V = 1, w = 0.00173, each seller's least-cost k:

  (a) anchor: a profile epoch e with a sale and A_e = last(e) + a_A in GAP (missed anchor);
  (b) proofs: expected number of sampled sales with proof deadline P_e = M_e + T_p = last(e) + a_A + 31 + T_p in GAP,
      sum over those epochs of c_e * pi * q (c_e the address's per-epoch sale count from epochs_busy.csv.gz, pi the
      seller part's share of the address's sales, q = min(1, n_s / n) the seller's mean sampling rate in k11b), and
      the probability of at least one, 1 - prod (1 - q pi)^c_e;
  loss of one failure: frozen (1 - a) R / Wb * DF(k*) plus b (cost model, lower case), as in P5.

K11/k11b.py is read and executed unchanged in its own namespace (only its final output write is redirected) and the
reproduction of K11/k11b_output.md is checked byte for byte, as in P4.

    python3 -I p6.py --check-only      # reproduction and structural checks only (prints booleans)
    python3 -I p6.py --out results        # the whole calculation (run only when told to)

The functions above main() do not read data and are unit-tested in test_p6.py.
"""
import argparse, datetime as dt, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent
K11 = J / 'K11'

GAP = (47_806_547, 47_808_825)       # supp_body.tex supp:base1 (inclusive; 2,279 blocks)
GAP_UTC = ('2026-06-25 15:47:21', '2026-06-25 17:03:17')
F_BUSY = 47_086_928                  # first block of the busy window (k11b.py LISTW['busy'][1]; R12 conditions file)
BASE_GENESIS_TS = 1_686_789_347      # Base mainnet: block timestamp = genesis + 2 s x block number
BLOCK_S = 2
EPOCH_S = 600                        # epochs_<w>.csv.gz: epoch = floor((t - window start 00:00:00 UTC) / 600 s)
WIN_START_UTC = '2026-06-09 00:00:00'
SETS = ('T01t', 'BR')
V = 1.0


# ================================================================== pure helpers (unit-tested)
def block_ts(b, genesis=BASE_GENESIS_TS, bt=BLOCK_S): return genesis + bt * b


def utc(ts): return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def epoch_bounds(e, F, t0, bt=BLOCK_S, es=EPOCH_S):
    """Blocks [first, last] of aggregate epoch e when block F has time t0 seconds after the window start:
    block b has time t0 + bt (b - F); epoch e holds times [es e, es (e + 1))."""
    first = F + math.ceil((es * e - t0) / bt)
    last = F + math.ceil((es * (e + 1) - t0) / bt) - 1
    return first, last


def deadlines(last, a_A, sv, tp):
    """A_e = last(e) + a_A (R3 (a), R8 (e)); M_e = A_e + tau_V + 1 + T_V = A_e + sv (R4 (a)); P_e = M_e + T_p (R7 (b))."""
    A = last + a_A; M = A + sv
    return A, M, M + tp


def in_gap(x, gap): return gap[0] <= x <= gap[1]


def gap_epochs(nep, F, t0, gap, a_A, sv, tp):
    """Epoch index sets for (a) and (b) and their strict variants (calc-rules.md 2.3):
    a      : A_e in gap                          (seller submitting at its deadline; upper count)
    a_all  : (last(e), A_e] inside gap           (no block after the epoch's end could take the anchor; lower count)
    b      : P_e in gap
    b_all  : (A_e, P_e] inside gap               (no block from the earliest sample value to the deadline)"""
    S = dict(a=[], a_all=[], b=[], b_all=[])
    for e in range(nep):
        _, last = epoch_bounds(e, F, t0)
        A, M, Pd = deadlines(last, a_A, sv, tp)
        if in_gap(A, gap): S['a'].append(e)
        if last + 1 >= gap[0] and A <= gap[1]: S['a_all'].append(e)
        if in_gap(Pd, gap): S['b'].append(e)
        if A + 1 >= gap[0] and Pd <= gap[1]: S['b_all'].append(e)
    return S


def seller_gap(c, pi, q, Ea, Eb):
    """c: per-epoch sale counts of the address; pi: share of the address's sales that belong to this seller part (1 for
    a whole seller); q: mean sampling rate n_s / n (capped at 1). Returns P(a) = 1 - prod_{Ea} (1 - pi)^c_e (whether
    the part has a sale in an epoch whose anchor deadline is in the gap), the expected sampled proofs due in the gap
    sum_{Eb} q pi c_e, and P(b) = 1 - prod_{Eb} (1 - q pi)^c_e."""
    c = np.asarray(c, float); q = min(1.0, q); x = q * pi
    ca = float(c[list(Ea)].sum()) if len(Ea) else 0.0
    cb = float(c[list(Eb)].sum()) if len(Eb) else 0.0
    Pa = 1.0 - (1.0 - pi) ** ca if pi < 1.0 else (1.0 if ca > 0 else 0.0)
    Pb = 1.0 - (1.0 - x) ** cb if x < 1.0 else (1.0 if cb > 0 else 0.0)
    return dict(sales_a=ca, Pa=Pa, failed_a=bool(Pa == 1.0), exp_b=x * cb, sales_b=cb, Pb=Pb,
                Pany=1.0 - (1.0 - Pa) * (1.0 - Pb))


def loss_per_failure(R, Wb, DF, b, a=0.0, gasf=0.0):
    """Same as P5 (calc-rules.md 2.4): (1 - a) R / Wb * DF + b (+ gasf in the upper case)."""
    fr = (1.0 - a) * R / Wb * DF
    return dict(frozen=fr, b=b, gasf=gasf, total=fr + b + gasf)


def totals(rows):
    Rs = sum(r['R'] for r in rows)
    sh = lambda w: (sum(r['R'] * w(r) for r in rows) / Rs) if Rs > 0 else float('nan')
    return dict(n=len(rows), R=Rs,
                failed_a=sum(1 for r in rows if r['gap']['failed_a']), exp_failed_a=sum(r['gap']['Pa'] for r in rows),
                rev_share_failed_a=sh(lambda r: 1.0 if r['gap']['failed_a'] else 0.0), rev_share_Pa=sh(lambda r: r['gap']['Pa']),
                exp_b=sum(r['gap']['exp_b'] for r in rows), exp_sellers_b=sum(r['gap']['Pb'] for r in rows),
                rev_share_Pb=sh(lambda r: r['gap']['Pb']), exp_sellers_any=sum(r['gap']['Pany'] for r in rows),
                rev_share_Pany=sh(lambda r: r['gap']['Pany']),
                loss_failed_a=sum(r['loss']['total'] for r in rows if r['gap']['failed_a']),
                exp_loss_any=sum(r['gap']['Pany'] * r['loss']['total'] for r in rows))


# ================================================================== k11b namespace
def load_k11b(tag='k11b_p6'):
    src = (K11 / 'k11b.py').read_text(encoding='utf-8')
    a1 = "HERE = os.path.dirname(os.path.abspath(__file__))"
    a2 = "open(HERE + '/k11b_output.md', 'w').write(txt)"
    assert src.count(a1) == 1 and src.count(a2) == 1
    src = src.replace(a1, "HERE = %r" % str(K11)).replace(a2, "_P6_TXT = txt")
    g = {'__name__': tag}
    exec(compile(src, str(K11 / 'k11b.py'), 'exec'), g)
    repro = g['_P6_TXT'] == (K11 / 'k11b_output.md').read_text(encoding='utf-8')
    g['set_gas']('new')
    return g, repro


def consts(g):
    """Deadline constants of mode N from the k11b namespace (calc-rules.md 1.2)."""
    ch, md = g['CH']['N'], g['MODES']['N']
    assert ch['a_A'] == md['DA'] and ch['SV'] == md['SV'] and ch['TP'] == md['TP']
    assert g['EPB'] * BLOCK_S == EPOCH_S
    return dict(a_A=ch['a_A'], SV=ch['SV'], TP=ch['TP'], EPB=g['EPB'])


def structural_checks(g, t0):
    """Booleans only (no seller value): the gap and the window's first block in the k11b data conventions."""
    win0 = dt.datetime.strptime(WIN_START_UTC, '%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc).timestamp()
    chk = dict(
        first_block=(g['LISTW']['busy'][1] == F_BUSY),
        gap_in_window=(F_BUSY <= GAP[0] <= GAP[1] <= g['LISTW']['busy'][2]),
        gap_len=(GAP[1] - GAP[0] + 1 == 2_279),
        gap_utc=((utc(block_ts(GAP[0])), utc(block_ts(GAP[1]))) == GAP_UTC),
        t0=(block_ts(F_BUSY) - win0 == t0),
        lists_missing=(g['LINFO'].get('busy') == 'missing'),       # LCNT busy is from epochs_busy.csv.gz
        nep=all(len(g['LCNT'][('busy', nm)]) == 21 * 144 for nm in g['ADDR']))
    return chk


def seller_rows(g, st, E, per='busy'):
    prm = g['LOm']('N'); gr = g['G'](st, V, prm)
    if not gr.ok: return []
    o = gr.opt(g['W0']); ki = o['ki']
    addr_n = {r['seller']: int(r['sales']) for r in g['SUMALL'][per]}
    rows = []
    for j, s in enumerate(gr.S):
        base = s['base']; c = g['LCNT'][(per, base)]
        assert int(round(c.sum())) == addr_n[base], base             # aggregate counts = summary sales of the address
        pi = float(gr.n[j]) / addr_n[base]
        q = float(gr.ns[j]) / float(gr.n[j])
        i = int(ki[j])
        rows.append(dict(seller=gr.a_[j], base=base, R=float(gr.R[j]), n=float(gr.n[j]), ns=float(gr.ns[j]), pi=pi, q=q,
                         k=int(g['KS'][i]), DF=float(gr.DFk[i, 0]),
                         loss=loss_per_failure(float(gr.R[j]), float(gr.Wb), float(gr.DFk[i, 0]), float(gr.b), a=float(prm.a)),
                         gap=seller_gap(c, pi, q, E['a'], E['b']), gap_all=seller_gap(c, pi, q, E['a_all'], E['b_all'])))
    return rows


def run(g, t0, sets=SETS, F=F_BUSY, gap=GAP, nep=21 * 144, per='busy'):
    C = consts(g)
    E = gap_epochs(nep, F, t0, gap, C['a_A'], C['SV'], C['TP'])
    res = dict(consts=C, t0=t0, F=F, gap=list(gap), epochs={k: list(v) for k, v in E.items()},
               epoch_blocks={str(e): list(epoch_bounds(e, F, t0)) for e in sorted(set(sum(E.values(), [])))})
    for st0 in sets:
        st = '%s:%s' % (st0, per)
        rows = seller_rows(g, st, E, per)
        res[st0] = dict(rows=rows, totals=totals(rows),
                        totals_all=totals([dict(r, gap=r['gap_all']) for r in rows]))
    return res


# ================================================================== main path (real data)
T0_OFF = 3      # seconds: block F_BUSY is at 2026-06-09 00:00:03 UTC (checked in structural_checks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out'); ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()
    T0 = time.time()
    g, repro = load_k11b()
    print('k11b_output.md reproduced byte for byte:', repro, '%.0fs' % (time.time() - T0), flush=True)
    assert repro
    chk = structural_checks(g, T0_OFF)
    print('structural checks:', chk, flush=True)
    META = dict(k11b_reproduced=repro, checks=chk, GAP=GAP, GAP_UTC=GAP_UTC, F_BUSY=F_BUSY, T0_OFF=T0_OFF, V=V, W0=g['W0'],
                consts=consts(g), k11b_sha256=hashlib.sha256((K11 / 'k11b.py').read_bytes()).hexdigest(),
                p6_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if args.check_only: return
    assert args.out, '--out is required'
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT; OUT.mkdir(parents=True, exist_ok=True)
    if not all(chk.values()):
        with open(OUT / 'p6.json', 'w') as fh: json.dump(dict(meta=META, verdict='withheld: reproduction failure'), fh, indent=1, ensure_ascii=False)
        print('checks failed: no values reported'); sys.exit(2)
    RES = dict(meta=META, **run(g, T0_OFF))
    write_outputs(RES, OUT)
    print('wrote', OUT, '%.0fs' % (time.time() - T0))


def write_outputs(RES, OUT):
    with open(OUT / 'p6.json', 'w') as fh: json.dump(RES, fh, indent=1, ensure_ascii=False, allow_nan=True)
    (OUT / 'p6_tables.md').write_text(tables(RES), encoding='utf-8')
    sums = ''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f) for f in ('p6.json', 'p6_tables.md'))
    (OUT / 'SHA256SUMS.txt').write_text(sums, encoding='ascii')


# ================================================================== tables
def u2(x): return format(x, ',.2f')
def p4_(x): return '%.4f' % x


def tables(R):
    C = R['consts']; E = R['epochs']
    L = ['**all values post hoc calculations registered verdict none.** `p6.py` output. busy window, mode N, V 1, w 0.00173, per seller optimal k, lower case. amount USD.\n',
         'k11b_output.md reproduction: %s. structure check: %s.\n' % (R['meta']['k11b_reproduced'], all(R['meta']['checks'].values())),
         'gap block %s~%s (%s~%s UTC). a_A %d, M_e − A_e %d, T_p %d. anchor deadline in a gap falling epoch(a): %s; around interval whole(a_all): %s. '
         'proof deadline in a gap falling epoch(b): %s; interval whole(b_all): %s.\n' % (
             format(R['gap'][0], ','), format(R['gap'][1], ','), *R['meta']['GAP_UTC'], C['a_A'], C['SV'], C['TP'],
             E['a'], E['a_all'], E['b'], E['b_all'])]
    for st0, title in (('T01t', 'classified data seller six(T01t)'), ('BR', 'BlockRun(BR)')):
        if st0 not in R: continue
        D = R[st0]
        L.append('\n## %s\n' % title)
        L.append('| seller | revenue R | π | q = n_s/n | k | (a) failure | P(a) | (b) expected sample proof | P(b ≥ 1) | P(failure) | failure one time loss (freeze + b) | (a_all) P | (b_all) expected |')
        L.append('|' + '---|' * 13)
        for r in D['rows']:
            gp, ga = r['gap'], r['gap_all']
            L.append('| %s | %s | %s | %s | %d | %s | %s | %s | %s | %s | %s (%s + %s) | %s | %s |' % (
                r['seller'], u2(r['R']), p4_(r['pi']), p4_(r['q']), r['k'], 'yes' if gp['failed_a'] else 'no', p4_(gp['Pa']),
                '%.3f' % gp['exp_b'], p4_(gp['Pb']), p4_(gp['Pany']), u2(r['loss']['total']), u2(r['loss']['frozen']), u2(r['loss']['b']),
                p4_(ga['Pa']), '%.3f' % ga['exp_b']))
        for nm, T in (('main definition', D['totals']), ('interval whole(below computed)', D['totals_all'])):
            L.append('\n%s total: seller %d, (a) failure %d (expected %.3f), its revenue share %.2f%% (expected %.2f%%); (b) expected sample proof %.3f, one at least seller expected count %.3f (revenue share %.2f%%); '
                     'failure seller expected count %.3f (revenue share %.2f%%); (a) failure seller loss sum %s, expected loss sum %s.' % (
                         nm, T['n'], T['failed_a'], T['exp_failed_a'], 100 * T['rev_share_failed_a'], 100 * T['rev_share_Pa'], T['exp_b'],
                         T['exp_sellers_b'], 100 * T['rev_share_Pb'], T['exp_sellers_any'], 100 * T['rev_share_Pany'], u2(T['loss_failed_a']),
                         u2(T['exp_loss_any'])))
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
