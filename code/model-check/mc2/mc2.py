"""MC2: explicit-state exhaustive model of the FairBind core settlement rule.

Target: rule candidate v0.8b (R1, R3 (ga)(ma), R4 (ga)(na), R5 (ga) acceptance,
R6 (ga)(na)(da), R7 (ga)-(ra)) as used by Lemma 1(b) of the manuscript
(Lemma A, app_proofs.tex; full proof supp_lemma1b_proof.tex).

One configuration is explored exhaustively, breadth first, states deduplicated.
Time is counted in blocks. The adversary (seller, callers, VRF provider,
buyers) picks every action and its order inside a block; ``tick`` advances the
block. Clause references in comments use the rule's numbering
(R6 (ga)(2) = cursor condition C2, and so on).

Python 3 standard library only.  Usage:  python3 mc2.py --help
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections import deque

# ---------------------------------------------------------------------------
# sale status (R3 (na) per-purchase state)
H, F, PC, PD, PA, RM, RD, RC, PAF = range(9)
ST_NAME = ['held', 'frozen', 'paid_cursor', 'paid_dispute', 'paid_accept',
           'refund_mark', 'refund_dispute', 'refund_claim', 'paid_accept_from_frozen']
PAID = (PC, PD)            # payments to the seller that Lemma 1(b2) speaks of
TO_SELLER = (PC, PD, PA, PAF)
REFUNDED = (RM, RD, RC)

# sale tuple fields
P_, E_, ETA, FR, DK, AN, SM, CS, ST, AC, MK, DS, PNF, FZ = range(14)
# p: profile; e: profile epoch; eta: settlement block; fr: 1 = fraudulent leaf
# (kind L; no proof can pass, G7 soundness on E_nb); dk: dispute kind
# (0 none, 1 ends for seller, 2 ends in refund); an: 1 = in the accepted anchor
# (0 = kind O, settled after the anchor); sm: label (0 undetermined, 1 sampled,
# 2 not sampled); cs: sample case (0 none, 1 open, 2 passed, 3 failed);
# st: status; ac: a_n = 1 recorded; mk: u_n = 1; ds: dispute ended;
# pnf: number of failure records when the sale was paid (-1 not paid);
# fz: 1 if the sale was ever frozen.

# seller tuple fields
CUR, SUSP, BAL, DEP, DED, NDED, REENT, SALES, PE, FAILS, LEDGER, PASSNF = range(12)
# pe entries per (profile, epoch): (anc, val, unit)
#   anc: 0 none, 1 accepted anchor, 2 recorded missed anchor (R3 (ma))
#   val: 0 undetermined, 1 sample value arrived by M_e, 2 none by M_e (all sampled)
#   unit: 1 = release unit marked (R6 (na))
# fails: tuple of (fid, eta_f, nsales_at_record); fid = ('c', sale index) or ('m', pe index)
# ledger: (held, to_seller, refunded, frozen) kept by the transitions themselves
# passnf: number of failure records at the call in which each seller epoch was passed

MUTATIONS = {
    'M1_freeze_next': 'freeze block of a sample failure is eta_i + 1 (the block after the failed sale)',
    'M2_cursor_no_wait': 'cursor drops C2: passes E without waiting for sampled cases to end and records no failure',
    'M3_k_first_only': 'k > 1: cursor checks C0-C3 only for the first profile epoch of E (does not wait for E\'s last profile epoch)',
    'M4_pay_before_freeze': 'inside the cursor call, payment comes before failure records and freezes',
    'M5_freeze_profile_only': 'a failure freezes only sales of the failed sale\'s own profile',
    'M6_dispute_pay_early': 'a dispute that ends for the seller pays at once, not at the later of its end and the cursor',
    'M7_double_declare': 'a failed case can be declared failed a second time (no once guard)',
    'M8_unit_pays': 'a release-unit call pays its unfailed entries',
    'M9_accept_frozen': 'acceptance at the anchor pays a frozen sale',
    'M10_double_pay': 'the cursor pays again a sale already paid by acceptance at the anchor',
    'M11_freeze_cross_seller': 'a failure also freezes other sellers\' sales from eta_f on',
    'R_empty_literal': 'reading: an empty profile epoch is passed "at once" even before it ends (text of R6 (ga)(0) without "ended")',
}


def default_cfg(**kw):
    c = dict(
        sellers=1, profiles=1, epochs=2, k=1,
        smax=2,          # sales per (profile, epoch), 0..smax
        stot=4,          # total sales per seller (bounds the run)
        L=2,             # profile-epoch length T_epoch in blocks
        aA=1,            # anchor deadline offset: A_e = last(e) + aA
        Mgap=1,          # M_e = A_e + Mgap (tau_V + 1 + T_V)
        T_p=1,           # proof deadline: a pass can be recorded up to M_e + T_p
        T_c=2,           # dispute window: W_e := A_e + T_c, cursor needs block > W_e (C3)
        d_inc=1,         # binding wait: a unit with a nonce is accepted only after eta + d_inc
        disputes=False,  # sales may carry a dispute
        marks=True,      # anchor may mark (u_n = 1) or record acceptance (a_n = 1)
        fraud=False,     # explicit fraud bit; off by default: the seller may withhold any proof, and P1 treats every
                         # sampled sale without a pass as fraudulent (a superset of the fraud choices)
        honest=False,    # honest seller: no fraud, anchors after epoch end by A_e, proves every sampled case by T_p, no marks
        max_reentry=1,
        claims=False,    # frozen sales can be claimed (refund to payer); on only in the P4 grid
        units=False,     # separate release-unit calls (otherwise the cursor checks units itself); on in the unit grid and M8
        mutations=(),
        max_states=40_000_000,
    )
    c.update(kw)
    return c


class Model:
    def __init__(self, cfg):
        self.c = cfg
        c = cfg
        self.N, self.P, self.k, self.L = c['epochs'], c['profiles'], c['k'], c['L']
        self.mut = set(c['mutations'])
        for m in self.mut:
            assert m in MUTATIONS, m
        self.nE = (self.N + self.k - 1) // self.k
        Ds = [self.D(e) for e in range(self.N)]
        Ws = [self.W(e) for e in range(self.N)]
        self.Hend = max(max(Ds), max(Ws)) + 2

    # timeline -------------------------------------------------------------
    def last(self, e):
        return self.L * e + self.L - 1

    def A(self, e):          # anchor deadline (R3 (ga))
        return self.last(e) + self.c['aA']

    def M(self, e):          # sample-value deadline (R4 (ga))
        return self.A(e) + self.c['Mgap']

    def D(self, e):          # last block at which a pass can be recorded (R4 (na)); cases open at M_e
        return self.M(e) + self.c['T_p']

    def W(self, e):          # end of the dispute window A_e + T_c (R6 (ga)(3))
        return self.A(e) + self.c['T_c']

    def sE(self, e):         # seller epoch of profile epoch e (R1 (ga))
        return e // self.k

    def pei(self, p, e):
        return p * self.N + e

    # initial state ------------------------------------------------------------
    def init(self):
        pe = tuple((0, 0, 0) for _ in range(self.P * self.N))
        s = (0, 0, 1, 1, 0, 0, 0, (), pe, (), (0, 0, 0, 0), ())
        return (0, tuple(s for _ in range(self.c['sellers'])))

    # helpers -----------------------------------------------------------------
    @staticmethod
    def L_(t):
        return [list(x) for x in t]

    def count(self, sales, p, e):
        return sum(1 for x in sales if x[P_] == p and x[E_] == e)

    def record_failure(self, st_all, si, fid, eta_f, prof=None):
        """R7 (ga)-(da): confirmed failure, narrow freeze from eta_f, deduction, suspension."""
        s = st_all[si]
        sales = s[SALES]
        fails = list(s[FAILS])
        fails.append((fid, eta_f, len(sales)))
        s[FAILS] = tuple(fails)
        led = list(s[LEDGER])
        for j in sales:
            if j[ST] == H and j[ETA] >= eta_f and j[AC] == 0:
                if 'M5_freeze_profile_only' in self.mut and prof is not None and j[P_] != prof:
                    continue
                j[ST] = F
                j[FZ] = 1
                led[0] -= 1
                led[3] += 1
        s[LEDGER] = tuple(led)
        d = min(1, s[BAL])                 # R7 (da): min(b(V*_p), balance), b = 1 unit
        s[BAL] -= d
        s[DED] += d
        s[NDED] += 1
        s[SUSP] = 1
        if 'M11_freeze_cross_seller' in self.mut:
            for sj, o in enumerate(st_all):
                if sj == si:
                    continue
                oled = list(o[LEDGER])
                for j in o[SALES]:
                    if j[ST] == H and j[ETA] >= eta_f and j[AC] == 0:
                        j[ST] = F
                        j[FZ] = 1
                        oled[0] -= 1
                        oled[3] += 1
                o[LEDGER] = tuple(oled)

    def fail_case(self, st_all, si, idx):
        s = st_all[si]
        x = s[SALES][idx]
        x[CS] = 3
        eta_f = x[ETA] + (1 if 'M1_freeze_next' in self.mut else 0)   # R7 (na): s_f = eta of the failed sale
        self.record_failure(st_all, si, ('c', idx), eta_f, prof=x[P_])

    def fail_missed(self, st_all, si, p, e):
        s = st_all[si]
        pe = list(s[PE])
        a, v, u = pe[self.pei(p, e)]
        pe[self.pei(p, e)] = (2, v, u)
        s[PE] = tuple(pe)
        etas = [x[ETA] for x in s[SALES] if x[P_] == p and x[E_] == e]
        self.record_failure(st_all, si, ('m', self.pei(p, e)), min(etas), prof=p)   # freeze from the epoch's first sale

    def pay(self, s, x, kind):
        led = list(s[LEDGER])
        led[0] -= 1
        led[1] += 1
        s[LEDGER] = tuple(led)
        x[ST] = kind
        x[PNF] = len(s[FAILS])

    # pack ---------------------------------------------------------------------
    @staticmethod
    def pack_seller(s):
        s = list(s)
        s[SALES] = tuple(tuple(x) for x in s[SALES])
        return tuple(s)

    def unpack(self, state):
        t, sellers = state
        out = []
        for s in sellers:
            s = list(s)
            s[SALES] = [list(x) for x in s[SALES]]
            out.append(s)
        return t, out

    def pack(self, t, st_all):
        return (t, tuple(self.pack_seller(s) for s in st_all))

    # successor function ----------------------------------------------------------
    def succ(self, state):
        """Yield (label, next_state)."""
        t, sellers = state
        c = self.c
        N, P = self.N, self.P
        for si, s0 in enumerate(sellers):
            sales0 = s0[SALES]
            pe0 = s0[PE]
            # --- settle (R1 (ga), R2; R7 (da) suspension blocks settle) -------------
            if t < N * self.L and s0[SUSP] == 0 and s0[BAL] >= 1 and len(sales0) < c['stot']:
                e = t // self.L
                for p in range(P):
                    if self.count(sales0, p, e) >= c['smax']:
                        continue
                    anc = pe0[self.pei(p, e)][0]
                    frs = (0, 1) if (c['fraud'] and not c['honest']) else (0,)
                    dks = (0, 1, 2) if c['disputes'] else (0,)
                    for fr in frs:
                        for dk in dks:
                            tt, st_all = self.unpack(state)
                            s = st_all[si]
                            an = 0 if anc == 1 else 0   # leaf set at anchor time; after an accepted anchor the sale is kind O
                            s[SALES].append([p, e, t, fr, dk, an, 0, 0, H, 0, 0, 0, -1, 0])
                            led = list(s[LEDGER]); led[0] += 1; s[LEDGER] = tuple(led)
                            yield (f's{si}:settle p{p} fr{fr} dk{dk}', self.pack(tt, st_all))
            # --- re-entry (R7 (ra)) -----------------------------------------------------
            if s0[SUSP] == 1 and s0[REENT] < c['max_reentry'] and t < N * self.L:
                tt, st_all = self.unpack(state)
                s = st_all[si]
                s[DEP] += 1 - s[BAL]
                s[BAL] = 1
                s[SUSP] = 0
                s[REENT] += 1
                yield (f's{si}:reentry', self.pack(tt, st_all))
            # --- anchor (R3 (ga)(na)); acceptance (R5 (ga)); marks (R2 (ma)) ---------------
            for p in range(P):
                for e in range(N):
                    a, v, u = pe0[self.pei(p, e)]
                    if a != 0 or t > self.A(e):
                        continue
                    idxs = [i for i, x in enumerate(sales0) if x[P_] == p and x[E_] == e]
                    if not idxs:
                        continue
                    if any(sales0[i][ETA] > t - c['d_inc'] for i in idxs):
                        continue       # binding wait (R3 (ga)); count must equal settlements, so all are listed
                    if c['honest'] and t <= self.last(e):
                        continue
                    if c['marks'] and not c['honest']:
                        choices = (0, 1, 2)   # 0 plain, 1 mark u_n = 1, 2 accept a_n = 1
                    elif c['marks']:
                        choices = (0, 2)
                    else:
                        choices = (0,)
                    for combo in itertools.product(choices, repeat=len(idxs)):
                        tt, st_all = self.unpack(state)
                        s = st_all[si]
                        pe = list(s[PE]); pe[self.pei(p, e)] = (1, v, u); s[PE] = tuple(pe)
                        led = list(s[LEDGER])
                        for i, ch in zip(idxs, combo):
                            x = s[SALES][i]
                            x[AN] = 1
                            if ch == 1:
                                x[MK] = 1
                                if x[ST] in (H, F):
                                    led[0 if x[ST] == H else 3] -= 1
                                    led[2] += 1
                                    x[ST] = RM
                            elif ch == 2:
                                x[AC] = 1
                                if x[ST] == H:
                                    led[0] -= 1; led[1] += 1
                                    x[ST] = PA
                                elif x[ST] == F and 'M9_accept_frozen' in self.mut:
                                    led[3] -= 1; led[1] += 1
                                    x[ST] = PAF
                        s[LEDGER] = tuple(led)
                        yield (f's{si}:anchor p{p} e{e} {combo}', self.pack(tt, st_all))
            # --- missed anchor record (R3 (ma)) ----------------------------------------
            for p in range(P):
                for e in range(N):
                    a, v, u = pe0[self.pei(p, e)]
                    if a == 0 and t > self.A(e) and self.count(sales0, p, e) > 0:
                        tt, st_all = self.unpack(state)
                        self.fail_missed(st_all, si, p, e)
                        yield (f's{si}:missed p{p} e{e}', self.pack(tt, st_all))
            # --- sample value arrives at M_e with any labels (R4 (ga)) -------------------
            for p in range(P):
                for e in range(N):
                    a, v, u = pe0[self.pei(p, e)]
                    if a == 1 and v == 0 and t == self.M(e):
                        idxs = [i for i, x in enumerate(sales0) if x[P_] == p and x[E_] == e and x[MK] == 0]
                        for combo in itertools.product((1, 2), repeat=len(idxs)):
                            tt, st_all = self.unpack(state)
                            s = st_all[si]
                            pe = list(s[PE]); pe[self.pei(p, e)] = (1, 1, u); s[PE] = tuple(pe)
                            for i, sm in zip(idxs, combo):
                                x = s[SALES][i]
                                x[SM] = sm
                                if sm == 1:
                                    x[CS] = 1
                            yield (f's{si}:value p{p} e{e} {combo}', self.pack(tt, st_all))
            # --- proofs (R4 (na)) ------------------------------------------------------------
            for i, x in enumerate(sales0):
                if x[CS] == 1 and t <= self.D(x[E_]) and x[AN] == 1 and x[FR] == 0:
                    tt, st_all = self.unpack(state)
                    st_all[si][SALES][i][CS] = 2
                    yield (f's{si}:prove {i}', self.pack(tt, st_all))
            # --- declare expired case failed (R4 (na), appendix A call) ---------------------
            for i, x in enumerate(sales0):
                ok = x[CS] == 1 and t > self.D(x[E_])
                if not ok and 'M7_double_declare' in self.mut and x[CS] == 3:
                    ok = sum(1 for f in s0[FAILS] if f[0] == ('c', i)) == 1
                if ok:
                    tt, st_all = self.unpack(state)
                    self.fail_case(st_all, si, i)
                    yield (f's{si}:declare {i}', self.pack(tt, st_all))
            # --- release unit call (R6 (na)) ---------------------------------------------------
            for p in (range(P) if (c['units'] or 'M8_unit_pays' in self.mut) else ()):
                for e in range(N):
                    a, v, u = pe0[self.pei(p, e)]
                    if a != 1 or u == 1 or v == 0:
                        continue
                    idxs = [i for i, x in enumerate(sales0) if x[P_] == p and x[E_] == e]
                    if any(sales0[i][CS] == 1 and t <= self.D(e) for i in idxs):
                        continue    # a sampled entry whose case has not ended: the unit check fails
                    tt, st_all = self.unpack(state)
                    s = st_all[si]
                    for i in idxs:
                        if s[SALES][i][CS] == 1:
                            self.fail_case(st_all, si, i)
                    pe = list(s[PE]); pe[self.pei(p, e)] = (a, v, 1); s[PE] = tuple(pe)
                    if 'M8_unit_pays' in self.mut:
                        for i in idxs:
                            x = s[SALES][i]
                            if x[ST] == H and x[DK] == 0:
                                self.pay(s, x, PC)
                    yield (f's{si}:unit p{p} e{e}', self.pack(tt, st_all))
            # --- release cursor (R6 (ga)(da)) --------------------------------------------------
            r = self.cursor(state, si)
            if r is not None:
                yield (f's{si}:cursor E{s0[CUR]}', r)
            # --- dispute end (R5 (da)(ra), R6 (da) separate payment) ----------------------------
            for i, x in enumerate(sales0):
                if x[DK] != 0 and x[DS] == 0 and t >= x[ETA] + 1:
                    tt, st_all = self.unpack(state)
                    s = st_all[si]
                    y = s[SALES][i]
                    y[DS] = 1
                    led = list(s[LEDGER])
                    if y[DK] == 2:            # dispute fails for the seller: refund (also from frozen)
                        if y[ST] in (H, F):
                            led[0 if y[ST] == H else 3] -= 1
                            led[2] += 1
                            y[ST] = RD
                        s[LEDGER] = tuple(led)
                    else:                    # ends for the seller: paid at the later of its end and the cursor
                        passed = s[CUR] > self.sE(y[E_])
                        if y[ST] == H and (passed or 'M6_dispute_pay_early' in self.mut):
                            self.pay(s, y, PD)
                    yield (f's{si}:dispute_end {i}', self.pack(tt, st_all))
            # --- claim of a frozen sale (R7 (na)) ---------------------------------------------
            if self.c['claims']:
                for i, x in enumerate(sales0):
                    if x[ST] == F:
                        tt, st_all = self.unpack(state)
                        s = st_all[si]
                        s[SALES][i][ST] = RC
                        led = list(s[LEDGER]); led[3] -= 1; led[2] += 1; s[LEDGER] = tuple(led)
                        yield (f's{si}:claim {i}', self.pack(tt, st_all))
        # --- tick ------------------------------------------------------------------------------
        if t < self.Hend:
            tt, st_all = self.unpack(state)
            blocked = False
            for s in st_all:
                pe = list(s[PE])
                for p in range(P):
                    for e in range(N):
                        a, v, u = pe[self.pei(p, e)]
                        n = self.count(s[SALES], p, e)
                        if self.c['honest'] and a == 0 and n > 0 and t == self.A(e):
                            blocked = True          # an honest seller anchors by A_e
                        if a == 1 and v == 0 and t == self.M(e):
                            # no value by M_e: every unmarked sale of e is sampled (R4 (ga)); cases open at M_e
                            pe[self.pei(p, e)] = (1, 2, u)
                            for x in s[SALES]:
                                if x[P_] == p and x[E_] == e and x[MK] == 0:
                                    x[SM] = 1
                                    x[CS] = 1
                if self.c['honest']:
                    for x in s[SALES]:
                        if x[CS] == 1 and t == self.D(x[E_]):
                            blocked = True          # an honest seller proves by T_p
                s[PE] = tuple(pe)
            if not blocked:
                yield ('tick', self.pack(tt + 1, st_all))

    def cursor(self, state, si):
        """R6 (ga): the cursor passes seller epoch E = CUR when C0-C4 hold for every profile epoch of E.
        Inside the call: failure records and freezes first, then payment (R6 (ga)(2), (da))."""
        t, sellers = state
        s0 = sellers[si]
        E = s0[CUR]
        if E >= self.nE:
            return None
        es = list(range(E * self.k, min(self.N, E * self.k + self.k)))
        es_chk = es[:1] if ('M3_k_first_only' in self.mut and self.k > 1) else es
        tt, st_all = self.unpack(state)
        s = st_all[si]
        changed = False
        nfail0 = len(s[FAILS])

        def records():
            nonlocal changed
            for p in range(self.P):
                for e in es_chk:
                    a, v, u = s[PE][self.pei(p, e)]
                    if a == 0 and t > self.A(e) and self.count(s[SALES], p, e) > 0:
                        self.fail_missed(st_all, si, p, e)          # R3 (ma): the cursor records it first
                        changed = True
                    if a == 1 and 'M2_cursor_no_wait' not in self.mut:
                        for i, x in enumerate(s[SALES]):
                            if x[P_] == p and x[E_] == e and x[CS] == 1 and t > self.D(e):
                                self.fail_case(st_all, si, i)    # C2: no pass by T_p -> confirmed failure in this call
                                changed = True

        def conditions():
            for p in range(self.P):
                for e in es_chk:
                    a, v, u = s[PE][self.pei(p, e)]
                    n = self.count(s[SALES], p, e)
                    if n == 0:
                        if t <= self.last(e) and 'R_empty_literal' not in self.mut:
                            return False   # an empty epoch is known empty only after it ends
                        continue
                    if a == 0:
                        return False       # C1
                    if a == 1 and v == 0:
                        return False       # C0
                    if 'M2_cursor_no_wait' not in self.mut:
                        for x in s[SALES]:
                            if x[P_] == p and x[E_] == e and x[CS] == 1:
                                if 'M4_pay_before_freeze' in self.mut and t > self.D(e):
                                    continue
                                return False   # C2
                    else:
                        if t <= self.D(e):
                            return False   # M2 still waits for the proof deadline, but not for the failure record
                    if t <= self.W(e):
                        return False       # C3 (dispute windows; the model has no beta_n = 0 sales, so W_e of the swap window is not used)
            return True                    # C4 by construction: CUR passes seller epochs in order

        def payment():
            if 'M10_double_pay' in self.mut:
                for x in s[SALES]:
                    if x[E_] in es and x[ST] == PA:     # acceptance-paid sale paid again by the cursor
                        led = list(s[LEDGER]); led[1] += 1; s[LEDGER] = tuple(led)
                        x[ST] = PC
            for x in s[SALES]:
                if x[E_] in es and x[ST] == H and (x[DK] == 0 or (x[DK] == 1 and x[DS] == 1)):
                    self.pay(s, x, PC)

        if 'M4_pay_before_freeze' in self.mut:
            if not conditions():
                return None
            payment()
            records()
        else:
            records()
            if not conditions():
                if changed:
                    return self.pack(tt, st_all)    # the call records failures but does not pass E
                return None
            payment()
        s[CUR] = E + 1
        s[PASSNF] = tuple(list(s[PASSNF]) + [nfail0 if 'M4_pay_before_freeze' in self.mut else len(s[FAILS])])
        return self.pack(tt, st_all)


# ---------------------------------------------------------------------------
# properties

def check(model, state, terminal):
    """Return list of (property, message) violations at this state."""
    t, sellers = state
    v = []
    c = model.c
    for si, s in enumerate(sellers):
        sales = s[SALES]
        fails = s[FAILS]
        fpos = {}
        for n, f in enumerate(fails):
            fpos.setdefault(f[0], n)
        # ---- P1: Lemma 1(b) for every detected element i ---------------------------------
        for i, x in enumerate(sales):
            if x[MK] == 1 or x[AC] == 1:
                continue
            a = s[PE][model.pei(x[P_], x[E_])][0]
            kind = None
            if a == 2 or (a == 0 and t > model.A(x[E_])):
                kind = 'M'
                fid = ('m', model.pei(x[P_], x[E_]))
            elif x[SM] == 1 and (x[FR] == 1 or x[AN] == 0 or x[CS] == 3
                                 or (x[CS] == 1 and t > model.D(x[E_]))):
                # kind L: a sampled sale with no pass by T_p. A leaf-fraudulent sale can never pass
                # (soundness on E_nb), so every sampled sale that ends without a pass is treated as
                # an element of I; this covers every choice of which sales are fraudulent.
                kind = 'L' if x[AN] == 1 else 'O'
                fid = ('c', i)
            if kind is None:
                continue
            n = fpos.get(fid)
            if n is not None:
                eta_f, ns = fails[n][1], fails[n][2]
                if eta_f > x[ETA]:
                    v.append(('P1', f's{si} element {i} kind {kind}: freeze block {eta_f} > eta_i {x[ETA]} (b1)'))
            else:
                ns = len(sales)
            E = model.sE(x[E_])
            if s[CUR] > E:
                if n is None or n >= s[PASSNF][E]:
                    v.append(('P1', f's{si} element {i} kind {kind}: cursor passed seller epoch {E} before f(i) (b1)'))
            for j, y in enumerate(sales):
                if j >= ns or y[ETA] < x[ETA]:
                    continue
                if y[ST] in PAID:
                    v.append(('P1', f's{si} element {i} kind {kind}: sale {j} (eta {y[ETA]}) settled before f(i) is paid ({ST_NAME[y[ST]]}) (b2)'))
                if n is not None and y[ST] == H:
                    v.append(('P1', f's{si} element {i} kind {kind}: sale {j} still held after f(i), not frozen (b2)'))
        for j, y in enumerate(sales):
            if y[ST] == PAF:
                v.append(('P1', f's{si} sale {j}: acceptance payment of a frozen sale (b2 last sentence, clause 6a)'))
        # ---- P1-freeze: the freeze-block form, for every confirmed failure ----------------------
        for n, (fid, eta_f, ns) in enumerate(fails):
            for j, y in enumerate(sales[:ns]):
                if y[ETA] >= eta_f and y[MK] == 0 and y[AC] == 0:
                    if y[ST] in PAID:
                        v.append(('P1f', f's{si} failure {fid} (eta_f {eta_f}): sale {j} (eta {y[ETA]}) settled before it is paid ({ST_NAME[y[ST]]})'))
                    if y[ST] == H:
                        v.append(('P1f', f's{si} failure {fid} (eta_f {eta_f}): sale {j} still held, not frozen'))
        # ---- P2: sales paid before a failure precede its freeze block --------------------------
        for n, (fid, eta_f, ns) in enumerate(fails):
            for j, y in enumerate(sales):
                if y[ST] in PAID and y[PNF] <= n and y[ETA] >= eta_f:
                    v.append(('P2', f's{si} sale {j} (eta {y[ETA]}) paid before failure {fid} with eta_f {eta_f}'))
        # ---- P3: one deduction and one suspension per confirmed failure ---------------------------
        if s[NDED] != len(fails):
            v.append(('P3', f's{si}: {s[NDED]} deductions for {len(fails)} failure records'))
        if len(set(f[0] for f in fails)) != len(fails):
            v.append(('P3', f's{si}: a failure is recorded twice: {[f[0] for f in fails]}'))
        if s[BAL] + s[DED] != s[DEP] or s[DED] > s[DEP]:
            v.append(('P3', f's{si}: balance {s[BAL]} + deducted {s[DED]} != deposits {s[DEP]}'))
        if fails and s[REENT] < 1 and s[SUSP] == 0:
            v.append(('P3', f's{si}: not suspended after a failure'))
        # ---- P4: amount conservation (ledger kept by transitions vs statuses) -----------------------
        led = s[LEDGER]
        cnt = [sum(1 for y in sales if y[ST] == H),
               sum(1 for y in sales if y[ST] in TO_SELLER),
               sum(1 for y in sales if y[ST] in REFUNDED),
               sum(1 for y in sales if y[ST] == F)]
        if tuple(cnt) != tuple(led) or sum(led) != len(sales):
            v.append(('P4', f's{si}: ledger (held, seller, refunded, frozen) {led} vs statuses {cnt}, settled {len(sales)}'))
        # ---- P5: honest seller never fails, and is paid at the end ----------------------------------
        if c['honest']:
            if fails:
                v.append(('P5', f's{si}: honest seller has a confirmed failure {fails}'))
            if terminal:
                for j, y in enumerate(sales):
                    if y[ST] not in (PC, PD, PA, RM, RD):
                        v.append(('P5', f's{si}: honest sale {j} ends {ST_NAME[y[ST]]}'))
        # ---- P6: every frozen sale is covered by a failure of its own seller --------------------------
        for j, y in enumerate(sales):
            if y[FZ] == 1:
                if not any(eta_f <= y[ETA] and j < ns for (_, eta_f, ns) in fails):
                    v.append(('P6', f's{si} sale {j} (eta {y[ETA]}) frozen without a covering failure of its seller'))
    return v


# ---------------------------------------------------------------------------
# search

def explore(cfg, stop_on_first=False, want_trace=True):
    """Breadth-first search. With want_trace the parent map keeps full states (small grids);
    otherwise only 64-bit hashes of visited states are kept, and a violation is re-searched
    with traces on the same configuration (explore_trace)."""
    model = Model(cfg)
    init = model.init()
    if want_trace:
        parent = {init: None}
        seen = parent
    else:
        seen = {hash(init)}
    q = deque([init])
    n_term = 0
    n_states = 1
    violations = {}
    t0 = time.time()
    capped = False
    while q:
        st = q.popleft()
        succs = list(model.succ(st))
        terminal = not succs
        if terminal:
            n_term += 1
        for prop, msg in check(model, st, terminal):
            if prop not in violations:
                violations[prop] = dict(msg=msg, trace=trace(parent, st) if want_trace else None)
        if stop_on_first and violations:
            break
        for lab, ns in succs:
            key = ns if want_trace else hash(ns)
            if key not in seen:
                if want_trace:
                    parent[ns] = (st, lab)
                else:
                    seen.add(key)
                n_states += 1
                q.append(ns)
                if n_states >= cfg['max_states']:
                    capped = True
                    q.clear()
                    break
    return dict(states=n_states, terminal=n_term, violations=violations,
                capped=capped, seconds=round(time.time() - t0, 1), Hend=model.Hend,
                dedup='full' if want_trace else 'hash64')


def trace(parent, st):
    out = []
    while parent[st] is not None:
        prev, lab = parent[st]
        out.append(f't={prev[0]} {lab}')
        st = prev
    out.reverse()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--cfg', default='{}', help='JSON overrides of default_cfg')
    ap.add_argument('--stop', action='store_true')
    a = ap.parse_args(argv)
    cfg = default_cfg(**json.loads(a.cfg))
    r = explore(cfg, stop_on_first=a.stop)
    print(json.dumps(dict(cfg=cfg, **r), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
