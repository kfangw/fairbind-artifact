"""Explicit-state model of the dispute state machine (rule candidate v0.7z, R5 and G 6).

One run explores every execution of a small grid exhaustively (breadth first,
states deduplicated). Time is counted in blocks. Clause references in comments
use the rule document's numbering (R5 (ra) = R5 (d), G6 = G 6, and so on).

Reading choices that the rule text leaves open are configuration flags; see
MC1_correspondence table.md for the mapping from clauses to transitions.
"""
from __future__ import annotations

import copy
from collections import deque

# ----------------------------------------------------------------------------
# configuration


def default_cfg(**kw):
    c = dict(
        # timeline (MC1 plan 2.1)
        D=2,            # d_obs + d_tx: honest tx decided at block b lands in [b+1, b+D]
        d_inc=2,
        A_e=4,          # anchor deadline
        alphas=(3, 4),  # blocks at which an anchor can be accepted
        T_c=6,          # window end E = A_e + T_c
        T_d=3,
        T_x=2,
        T_p_rd=3,       # proof deadline of a response dispute, from its opening
        sample_blocks=(5, 6, 7, 8, 9),  # T_p ends at 9
        t_sig=2,
        H=17,
        rdl=None,       # response deadline eta + r_dl (eta = 0), None = no deadline profile
        prof='P',       # 'P' plaintext, 'C' ciphertext with hash h_ct
        stage='byte',   # 'byte': sample/RD proofs carry bytes (public record); 'hash': no record
        seller='ADV',   # 'ADV', 'WITHHOLD', 'GARBAGE', 'HON'
        buyers=('OBL',),  # per purchase: 'OBL' obliged signing client, 'MAL' unsigned malicious, 'COL' colluding payer
        colluder=True,  # third-party actor X
        # costs (model units)
        c_del=3, c_disc=1, c_k=1, c_sig=1, d_nd=4, d_key=1, d_0=2,
        # honest seller response timing
        hold=False,       # response holding policy (3.4)
        bind_empty=False,  # binding hash empty at settlement (facilitator withheld payload)
        d_resp=1, d_obs=1,
        # reading choices / E5 candidates
        pre_anchor='revert_before_anchor',  # 59 (ga): 'literal','revert_before_anchor','td_from_anchor','revert_before_Ae'
        bundle=True,      # 59 (na): key dispute and decryption challenge in one tx when a valid k is held
        late_trigger=False,  # 59 (da): act on (ri) only after own bundle result (one block later)
        kcrit='leaf',     # 59 (ra): 'leaf' or 'rs'
        dch_always=False,  # 59 (ma): attach a decryption challenge after a bare key dispute even when it matches
        nd_record='answer',  # reading: ND delivery (ct,k) is a contract record at the answer block
        seller_rec_keyp=True,  # honest seller follows the rdl cipher recommendation on payer key disputes
        # self-check variants (plan 6)
        forge=False,       # F1: colluder may forge sigma_W (open payer-side slots)
        single_slot=False,  # F2: one slot per dispute kind
        ack_mode='all',    # F3 'one', F4 'none'
        rdl_record_blocks=False,  # F6: post-deadline record blocks payer ND
        no_post_terminal_dch=False,  # F7
        sampled_opts=(False, True),
        max_states=30_000_000,
        coarse=False,      # plan 2.6 reduction for G2
        x_dch=True,        # colluder's mismatching decryption challenges (only refund the buyer)
        dfs=False,         # depth-first, hash set only (memory bound); traces not shortest
    )
    c.update(kw)
    c['E'] = c['A_e'] + c['T_c']
    c['x_k'] = c['E'] - c['d_inc']
    if c['hold'] and c['bind_empty']:
        c['resp_lo'], c['resp_hi'] = c['d_inc'], c['d_inc'] + c['d_obs'] + c['d_resp']
    else:
        c['resp_lo'], c['resp_hi'] = 0, c['d_resp']
    return c


SLOTS = ('ND_P', 'ND_T', 'KEY_P', 'KEY_T', 'RD_P')
HONEST_OPENERS = ('C', 'W1', 'W2')


def slot_name(kind, side, cfg):
    if cfg['single_slot'] and kind in ('ND', 'KEY'):
        return kind + '_P'  # F2: one slot per kind
    return f'{kind}_{side}'


# ----------------------------------------------------------------------------
# state


class P:
    """Per-purchase state."""
    __slots__ = ('typ', 'ctgood', 'sampled', 'rs', 'rs_ok', 'koff', 'koff_blk', 'signed',
                 'wt_has', 'ack', 'wt_nd', 'sb_seller', 'anc', 'proof', 'pub', 'rec',
                 'slots', 'a_ctk', 'a_k', 'a_sig', 'dch', 'term', 'deps', 'sent',
                 'k_sent', 'gas', 'tp_dep_in', 'payer_opened', 'notes', 'k_flight',
                 'rs_sent', 'k_seen')

    def key(self):
        # Timestamps that no transition or property reads except as "present or not" are
        # keyed by presence. rs, k_seen, pub and rec are read against r_dl only, so they are
        # keyed by presence when the profile has no response deadline (KEY_TIMES False).
        pr = lambda x: x is not None
        if KEY_TIMES[0]:
            rs, ks, pub, rec = self.rs, self.k_seen, self.pub, self.rec
        else:
            rs, ks, rec = pr(self.rs), pr(self.k_seen), pr(self.rec)
            pub = None if self.pub is None else self.pub[0]
        return (self.typ, self.ctgood, self.sampled, rs, self.rs_ok, self.koff,
                pr(self.signed), (pr(self.wt_has[0]), pr(self.wt_has[1])),
                (pr(self.ack[0]), pr(self.ack[1])), self.wt_nd, pr(self.sb_seller), self.anc, self.proof,
                pub, rec, tuple(sorted(self.slots.items())), self.a_ctk, self.a_k,
                self.a_sig, self.dch, self.term[:1] if self.term else None, tuple(sorted(self.deps.items())),
                self.sent, self.gas, self.tp_dep_in, self.payer_opened,
                self.notes, pr(self.k_flight), self.rs_sent, ks)


KEY_TIMES = [True]


def new_purchase(typ, ctgood, sampled):
    p = P()
    p.typ = typ
    p.ctgood = ctgood
    p.sampled = sampled
    p.rs = None          # block at which R_S and response (plain) or ct (cipher) reached the buyer
    p.rs_ok = None       # response/ct matches the committed hash
    p.koff = None        # off-chain k: 'good' (H(k)=h_k) or 'bad'
    p.koff_blk = None
    p.signed = None      # block sigma_B was made
    p.wt_has = (None, None)  # block W_i stored sigma_B
    p.ack = (None, None)     # block ack of W_i reached the client
    p.wt_nd = (False, False)  # W_i decided to open ND (never acks after that)
    p.sb_seller = None   # block the seller holds sigma_B
    p.anc = None         # None | ('MISS',) | (blk, beta, u, swap)
    p.proof = None       # sample proof status: None | 'pub' | 'pass' | 'fail'
    p.pub = None         # block of a true public record (FairBind checked bytes / decrypt)
    p.rec = None         # block of the contract record that blocks ND (R5 (ra) delivery limit)
    p.slots = {}         # name -> tuple(open, opener, dep, base, end, how, bundled)
    p.a_ctk = None
    p.a_k = None
    p.a_sig = None
    p.dch = ()           # sorted tuple of (blk, slot) of mismatching decryption challenges
    p.term = None        # (kind, blk)
    p.deps = {}          # slot -> recipient
    p.sent = ()          # honest decisions already taken
    p.k_sent = False
    p.gas = 0            # seller gas spent on answers
    p.tp_dep_in = 0      # deposits the seller received from third-party slots
    p.payer_opened = False
    p.notes = ()         # facts for property checks
    p.k_flight = None    # block honest seller released k off chain
    p.rs_sent = False
    p.k_seen = None      # first block a valid k became available to the client (any route)
    return p


class S:
    __slots__ = ('now', 'pend', 'ps', 'viol', 'oc')

    def key(self):
        return (self.now, self.oc, self.pend, tuple(p.key() for p in self.ps))

    def clone(self):
        s = S.__new__(S)
        s.now = self.now
        s.oc = self.oc
        s.pend = self.pend
        ps = []
        for p in self.ps:
            q = P.__new__(P)
            for f in P.__slots__:
                setattr(q, f, getattr(p, f))
            q.slots = dict(p.slots)
            q.deps = dict(p.deps)
            ps.append(q)
        s.ps = ps
        s.viol = ()
        return s


def addt(t, x):
    return tuple(sorted(set(t) | {x}))


# slot tuple fields
O, OPENER, DEP, BASE, END, HOW, BUND = range(7)


def slot_open(sl):
    return sl is not None and sl[END] is None


# ----------------------------------------------------------------------------
# contract semantics


def anchor_ok(p):
    return p.anc is not None and p.anc[0] != 'MISS'


def answer_for(p, name, cfg):
    """Answer applicable to slot `name` (R5 (ra) (2)): the earliest one that counts.

    ND: sigma_B or (ct, k). Under a response deadline a (ct, k) after eta + r_dl does not
    count as delivery for the payer-side ND (R5 (ra) response deadline paragraph).
    KEY: k or (ct, k)."""
    kind = name.split('_')[0]
    c = []
    # (block, precedence, type): in one block a sigma_B answer takes precedence over (ct, k),
    # as the contract checks sigma_B first (the seller wins at once, R5 (ra))
    if kind == 'ND':
        if p.a_sig is not None:
            c.append((p.a_sig, 0, 'SIG'))
        if p.a_ctk is not None:
            late = cfg['rdl'] is not None and name == 'ND_P' and p.a_ctk > cfg['rdl']
            if not late:
                c.append((p.a_ctk, 1, 'CTK'))
    elif kind == 'KEY':
        if p.a_k is not None:
            c.append((p.a_k, 0, 'K'))
        if p.a_ctk is not None:
            c.append((p.a_ctk, 1, 'K'))
    if not c:
        return None, None
    a, _, typ = min(c)
    return a, typ


def refund(s, p, how, notes):
    if p.term is None:
        p.term = ('REFUND', s.now, how)
        # R5 (ra) (3): unanswered disputes return to opener; answered third-party ones are deferred
        for name, sl in list(p.slots.items()):
            if sl is None or name in p.deps:
                continue
            if slot_open(sl):
                p.slots[name] = sl[:END] + (s.now, 'term') + sl[HOW + 1:]
        return True
    else:
        notes.append('double_refund_attempt')
        return False


def settle_deposit(p, name, to):
    if name in p.deps:
        p.notes = addt(p.notes, 'double_settle')
        return
    p.deps[name] = to
    sl = p.slots[name]
    if name.endswith('_T') and to == 'seller':
        p.tp_dep_in += sl[DEP]
    if to == 'seller' and sl[OPENER] in HONEST_OPENERS:
        p.notes = addt(p.notes, f'honest_dep_to_seller:{name}:{sl[OPENER]}')


def mismatch_in(p, lo, hi):
    return any(lo <= b <= hi for b, _ in p.dch)


def resolve_deposits(s, p, cfg, end_of_block=False):
    """Settle deposits whose outcome is now fixed (R5 (ra) (3), appendix A).
    A deferred third-party judgement waits until block eff + T_x has ended, so a decryption
    challenge in that block still counts."""
    for name, sl in p.slots.items():
        if sl is None or name in p.deps or sl[END] is None:
            continue
        how = sl[HOW]
        opener = sl[OPENER]
        payer = name.endswith('_P')
        kind = name.split('_')[0]
        if kind == 'RD':
            settle_deposit(p, name, 'split' if how == 'passed' else opener)
            continue
        if how == 'sig':
            settle_deposit(p, name, 'seller')
            continue
        if payer:
            settle_deposit(p, name, opener)
            continue
        # third party
        a, typ = answer_for(p, name, cfg)
        if a is None or a > sl[END]:
            settle_deposit(p, name, opener)
            continue
        if typ == 'SIG':
            settle_deposit(p, name, 'seller')
            continue
        eff = max(a, sl[O])
        if s.now < eff + cfg['T_x'] or (s.now == eff + cfg['T_x'] and not end_of_block):
            continue  # judgement deferred until block eff + T_x has ended
        settle_deposit(p, name, opener if mismatch_in(p, eff, eff + cfg['T_x']) else 'seller')


def tx_open(s, i, kind, side, opener, bundled, cfg, notes):
    """Open a dispute (R5 (da), (ra)). Returns revert reason or None."""
    p = s.ps[i]
    name = slot_name(kind, side, cfg)
    now = s.now
    if p.term is not None:
        return 'terminal'
    if now > cfg['E']:
        return 'window'
    if p.anc is not None and p.anc[0] == 'MISS':
        return 'no_leaf'
    base = now
    pre = not anchor_ok(p) or p.anc[0] > now
    mode = cfg['pre_anchor']
    if mode == 'revert_before_Ae' and now < cfg['A_e']:
        return 'before_Ae'
    if pre:
        if mode in ('revert_before_anchor', 'revert_before_Ae'):
            return 'before_anchor'
        if mode == 'td_from_anchor':
            base = None  # resolved when the anchor is accepted
        # 'literal': accepted, T_d counted from the opening block
    if kind == 'KEY' and cfg['prof'] != 'C':
        return 'not_cipher'
    if kind == 'RD' and side != 'P':
        return 'rd_payer_only'
    if p.slots.get(name) is not None:
        prev = p.slots[name][OPENER]
        if cfg['single_slot'] and opener in HONEST_OPENERS and prev not in HONEST_OPENERS + ('B',):
            return 'slot_shared'
        return 'slot_used'
    if kind == 'ND':
        if anchor_ok(p) and p.anc[1] == 1:
            return 'beta1'
        if p.rec is not None:
            late_ok = (cfg['rdl'] is not None and side == 'P' and p.rec > cfg['rdl']
                       and not cfg['rdl_record_blocks'])
            if not late_ok:
                return 'record'
    if bundled is not None:
        # bundled decryption challenge: ct must match h_ct, k must match h_k of the leaf (R5 (ra) (4))
        if bundled == 'badk':
            return 'bundle_hash'
    dep = {'ND': cfg['d_nd'], 'KEY': cfg['d_key'], 'RD': cfg['d_0']}[kind]
    p.slots[name] = (now, opener, dep, base, None, None, bundled is not None)
    if side == 'P':
        p.payer_opened = True
    if kind == 'ND' and p.a_sig is not None:
        # R5 (ra) (2): an answer already on chain becomes the answer of a later dispute;
        # sigma_B answers a non-delivery dispute, which ends for the seller at once
        p.slots[name] = (now, opener, dep, base, now, 'sig', False)
        resolve_deposits(s, p, cfg)
        return None
    if kind == 'RD' and p.proof in ('pub', 'pass'):
        p.slots[name] = (now, opener, dep, base, now, 'passed', False)
        resolve_deposits(s, p, cfg)
        return None
    if bundled is not None:
        mism = not p.ctgood
        if mism:
            p.dch = addt(p.dch, (now, name))
            refund(s, p, 'dch_bundled', notes)
    resolve_deposits(s, p, cfg)
    return None


def tx_answer(s, i, typ, cfg, notes):
    """Seller answer (R5 (ra) (2)): CTK = (ct, k), K = k, SIG = sigma_B."""
    p = s.ps[i]
    now = s.now
    if p.term is not None or not anchor_ok(p) or p.anc[0] > now:
        return 'no'
    if typ == 'SIG' and (p.sb_seller is None or p.sb_seller > now):
        return 'no'
    kinds = {'CTK': ('ND', 'KEY'), 'K': ('KEY',), 'SIG': ('ND',)}[typ]
    targets = []
    for name, sl in p.slots.items():
        if not slot_open(sl) or name.split('_')[0] not in kinds:
            continue
        base = sl[BASE] if sl[BASE] is not None else p.anc[0]
        if now > base + cfg['T_d']:
            continue
        a, _ = answer_for(p, name, cfg)
        if a is None:
            targets.append(name)
    if not targets:
        return 'no'
    if typ == 'CTK':
        if p.a_ctk is not None:
            return 'no'
        p.a_ctk = now
        if cfg['prof'] == 'C' or True:
            if p.k_seen is None:
                p.k_seen = now
        # delivery record (R5 (ra) delivery limit) when it answers a non-delivery dispute
        if any(t.startswith('ND') for t in targets) or any(
                n.startswith('ND') and slot_open(sl) for n, sl in p.slots.items()):
            if p.rec is None:
                p.rec = now
            if p.ctgood and p.pub is None:
                p.pub = ('nd', now)
        p.gas = p.gas + cfg['c_del']
    elif typ == 'K':
        if p.a_k is not None:
            return 'no'
        p.a_k = now
        if p.k_seen is None:
            p.k_seen = now
        p.gas = p.gas + cfg['c_k']
    else:
        if p.a_sig is not None:
            return 'no'
        p.a_sig = now
        p.gas = p.gas + cfg['c_sig']
        for name, sl in list(p.slots.items()):
            if slot_open(sl) and name.startswith('ND'):
                p.slots[name] = sl[:END] + (now, 'sig') + sl[HOW + 1:]
    resolve_deposits(s, p, cfg)
    return None


def tx_dch(s, i, target, cfg, notes, mism=None):
    """Decryption challenge on an open ND (after its answer) or KEY (R5 (ra) (4))."""
    p = s.ps[i]
    now = s.now
    sl = p.slots.get(target)
    if sl is None:
        return 'no_slot'
    a, typ = answer_for(p, target, cfg)
    kind = target.split('_')[0]
    if mism is None:
        mism = not p.ctgood
    if sl[END] is not None:
        # after a terminal state: only the deferred third-party deposit judgement uses it
        if cfg['no_post_terminal_dch'] or not target.endswith('_T') or a is None:
            return 'ended'
        eff = max(a, sl[O])
        if now > eff + cfg['T_x'] or target in p.deps:
            return 'late'
        if mism:
            p.dch = addt(p.dch, (now, target))
        resolve_deposits(s, p, cfg)
        return None
    if kind == 'ND':
        if a is None or typ != 'CTK':
            return 'no_answer'
        if now > max(a, sl[O]) + cfg['T_x']:
            return 'late'
    if mism:
        p.dch = addt(p.dch, (now, target))
        refund(s, p, 'dch', notes)
    resolve_deposits(s, p, cfg)
    return None


def freeze_all(s, how, notes):
    """Confirmed failure: narrow freeze, refund by claim (R7). Applies to every unpaid purchase."""
    for p in s.ps:
        if p.term is None:
            p.term = ('FREFUND', s.now, how)
            for name, sl in list(p.slots.items()):
                if slot_open(sl):
                    p.slots[name] = sl[:END] + (s.now, 'term') + sl[HOW + 1:]
            p.notes = addt(p.notes, 'confirmed_failure:' + how)


def tx_anchor(s, beta, u, swap, cfg, notes):
    for i, p in enumerate(s.ps):
        b = beta[i] if beta[i] is not None else 0
        p.anc = (s.now, b, u[i], swap[i])
        # pre-anchor disputes with T_d from the anchor block (59 (ga) option 3)
        for name, sl in list(p.slots.items()):
            if sl is not None and sl[BASE] is None:
                p.slots[name] = sl[:BASE] + (s.now,) + sl[BASE + 1:]
        if b == 1:
            for name, sl in list(p.slots.items()):
                pass
        if u[i]:
            if p.term is None:
                p.term = ('UREFUND', s.now, 'unanswered_mark')
                for name, sl in list(p.slots.items()):
                    if slot_open(sl):
                        p.slots[name] = sl[:END] + (s.now, 'term') + sl[HOW + 1:]
        resolve_deposits(s, p, cfg)


def tx_swap_proof(s, i, cfg, notes):
    p = s.ps[i]
    if anchor_ok(p) and p.anc[3] and p.anc[1] == 0 and p.signed is not None:
        freeze_all(s, 'swap', notes)
        for q in s.ps:
            resolve_deposits(s, q, cfg)
        return None
    return 'no'


def tx_proof(s, i, publish, cfg, notes):
    p = s.ps[i]
    if p.proof in ('pub', 'pass'):
        return 'no'
    pub_possible = cfg['stage'] == 'byte' and (cfg['prof'] == 'P' or p.ctgood)
    if publish and pub_possible:
        p.proof = 'pub'
        if p.rec is None:
            p.rec = s.now
        if p.pub is None:
            p.pub = ('proof', s.now)
        if cfg['prof'] == 'C' and p.k_seen is None:
            p.k_seen = s.now
    else:
        p.proof = 'pass'
    # an open response dispute passes
    sl = p.slots.get('RD_P')
    if slot_open(sl):
        p.slots['RD_P'] = sl[:END] + (s.now, 'passed') + sl[HOW + 1:]
    resolve_deposits(s, p, cfg)
    return None


# ----------------------------------------------------------------------------
# block end: expiries, honest decisions


def expiries(s, cfg, notes):
    now = s.now
    for i, p in enumerate(s.ps):
        for name, sl in list(p.slots.items()):
            if not slot_open(sl):
                continue
            kind = name.split('_')[0]
            base = sl[BASE]
            if base is None:
                continue
            if kind == 'RD':
                if now >= base + cfg['T_p_rd']:
                    p.slots[name] = sl[:END] + (now, 'failed') + sl[HOW + 1:]
                    refund(s, p, 'rd_failed', notes)
                continue
            a, typ = answer_for(p, name, cfg)
            if a is None:
                if now >= base + cfg['T_d']:
                    p.slots[name] = sl[:END] + (now, 'noanswer') + sl[HOW + 1:]
                    refund(s, p, f'{name}_noanswer', notes)
            else:
                eff = max(a, sl[O])
                if now >= eff + cfg['T_x']:
                    p.slots[name] = sl[:END] + (now, 'answered') + sl[HOW + 1:]
        # sample case failure
        if p.sampled and p.proof is None and now >= cfg['sample_blocks'][-1] and p.anc is not None:
            if p.anc[0] != 'MISS' and not p.anc[2]:
                p.proof = 'fail'
                freeze_all(s, 'sample', notes)
    # anchor missing
    if now >= cfg['A_e'] and s.ps[0].anc is None:
        for p in s.ps:
            p.anc = ('MISS',)
        freeze_all(s, 'anchor_missing', notes)
    for p in s.ps:
        resolve_deposits(s, p, cfg, end_of_block=True)


def add_pend(s, lo, hi, i, actor, kind, arg=None):
    # Identical payer-side openings by several honest parties (client, W1, W2) decided at the same
    # block share a window; whichever lands first opens the slot and the others revert with the
    # same reason. Only one is kept (no property depends on which honest party opened).
    if kind == 'open' and actor in HONEST_OPENERS:
        for (lo2, hi2, i2, a2, k2, arg2) in s.pend:
            if (lo2, hi2, i2, k2, arg2) == (lo, hi, i, kind, arg) and a2 in HONEST_OPENERS:
                return
    s.pend = tuple(sorted(s.pend + ((lo, hi, i, actor, kind, arg),)))


def sent(p, tag):
    return tag in p.sent


def mark(p, tag):
    p.sent = addt(p.sent, tag)


def own_payer_open(p, kind):
    sl = p.slots.get(kind + '_P')
    return slot_open(sl)


def client_has_valid_k(p, cfg):
    swap_hk = anchor_ok(p) and p.anc[3]
    if p.koff == 'good':
        if cfg['kcrit'] == 'leaf' and swap_hk:
            pass  # R_S's k does not match the leaf h_k in a swap (h_k differs)
        else:
            return True, 'off'
    if p.a_k is not None or p.a_ctk is not None:
        return True, 'chain'
    if p.pub is not None and cfg['prof'] == 'C':
        return True, 'chain'
    return False, None


def honest_decisions(s, cfg):
    b = s.now
    D = cfg['D']
    lo, hi = b + 1, b + D
    if cfg['late_trigger']:
        lo, hi = b + 2, b + D + 1
    for i, p in enumerate(s.ps):
        anc = anchor_ok(p) and p.anc[0] <= b
        if p.typ == 'OBL':
            # G6 (na)(ga): sign only while observed block < t_sig, after a valid R_S and response/ct
            if (p.signed is None and p.term is None and b < cfg['t_sig'] and p.rs is not None
                    and p.rs_ok and (cfg['rdl'] is None or p.rs <= cfg['rdl'])):
                p.signed = b
                if cfg['ack_mode'] == 'none':
                    p.sb_seller = b
                    mark(p, 'gave_sb')
            # DC4: give sigma_B to the seller after the acks of all watchtowers
            if p.signed is not None and not sent(p, 'gave_sb') and p.term is None and \
                    b <= cfg['E'] + cfg['T_d']:
                n_ack = sum(1 for a in p.ack if a is not None)
                need = 1 if cfg['ack_mode'] == 'one' else 2
                if n_ack >= need:
                    p.sb_seller = b
                    mark(p, 'gave_sb')
            if p.term is not None:
                continue
            # G6 (ra): automatic ND for an unsigned sale after t_sig and the accepted anchor
            if p.signed is None and b >= cfg['t_sig'] and anc and not sent(p, 'C_ND'):
                mark(p, 'C_ND')
                add_pend(s, lo, hi, i, 'C', 'open', ('ND', 'P', None))
            # watchtowers: ND when sigma_B not stored at that time (G6 head)
            if b >= cfg['t_sig'] and anc:
                for w in (0, 1):
                    if p.wt_has[w] is None and not p.wt_nd[w] and not sent(p, f'W{w+1}_ND'):
                        mark(p, f'W{w+1}_ND')
                        wn = list(p.wt_nd)
                        wn[w] = True
                        p.wt_nd = tuple(wn)
                        add_pend(s, lo, hi, i, f'W{w+1}', 'open', ('ND', 'P', None))
            # G6 (da): swap proof
            if p.signed is not None and anc and p.anc[3] and p.anc[1] == 0 and not sent(p, 'SWAP'):
                mark(p, 'SWAP')
                add_pend(s, lo, hi, i, 'C', 'swap', None)
            mism = not p.ctgood
            hk, route = client_has_valid_k(p, cfg)
            # decryption challenge on an answered ND (own or third-party), signed or unsigned
            if anc and p.a_ctk is not None and mism and not sent(p, 'DCH_ND'):
                tgt = None
                for nm in ('ND_P', 'ND_T'):
                    sl = p.slots.get(nm)
                    if slot_open(sl):
                        a, typ = answer_for(p, nm, cfg)
                        if typ == 'CTK':
                            tgt = nm
                            break
                if tgt is not None:
                    mark(p, 'DCH_ND')
                    add_pend(s, lo, hi, i, 'C', 'dch', tgt)
            if cfg['prof'] == 'C' and p.signed is not None and anc:
                swap_leaf = p.anc[3]
                if hk and mism and not sent(p, 'KEYFIX'):
                    # G6 (sa): mismatch known
                    if own_payer_open(p, 'KEY'):
                        if not sent(p, 'DCH_KEY'):
                            mark(p, 'DCH_KEY')
                            mark(p, 'KEYFIX')
                            add_pend(s, lo, hi, i, 'C', 'dch', 'KEY_P')
                    elif own_payer_open(p, 'ND'):
                        a, typ = answer_for(p, 'ND_P', cfg)
                        if typ == 'CTK':
                            mark(p, 'KEYFIX')  # handled by DCH_ND above
                        # else wait: exception of G6 (sa)
                    elif not sent(p, 'C_KEY'):
                        mark(p, 'C_KEY')
                        mark(p, 'KEYFIX')
                        bund = 'ok'
                        if swap_leaf and cfg['kcrit'] == 'rs' and route == 'off':
                            bund = 'badk'
                        if cfg['bundle']:
                            add_pend(s, lo, hi, i, 'C', 'open', ('KEY', 'P', bund))
                        else:
                            add_pend(s, lo, hi, i, 'C', 'open', ('KEY', 'P', None))
                            mark(p, 'SEP_DCH')
                # separate challenge after own key dispute landed (59 (na) option 2)
                if sent(p, 'SEP_DCH') and own_payer_open(p, 'KEY') and not sent(p, 'DCH_KEY'):
                    mark(p, 'DCH_KEY')
                    add_pend(s, lo, hi, i, 'C', 'dch', 'KEY_P')
                # no valid k by x_k: bare key dispute (unless own payer ND open)
                if not hk and b >= cfg['x_k'] and not sent(p, 'C_KEY') and not own_payer_open(p, 'ND'):
                    mark(p, 'C_KEY')
                    add_pend(s, lo, hi, i, 'C', 'open', ('KEY', 'P', None))
                # seller answered the bare key dispute: check and challenge
                if own_payer_open(p, 'KEY') and (p.a_k is not None or p.a_ctk is not None) and \
                        (mism or cfg['dch_always']) and not sent(p, 'DCH_KEY'):
                    mark(p, 'DCH_KEY')
                    add_pend(s, lo, hi, i, 'C', 'dch', 'KEY_P')
        if cfg['seller'] == 'HON' and p.term is None:
            honest_seller_decisions(s, i, p, b, cfg)
    if cfg['seller'] == 'HON' and b == 2 and not any(x[4] == 'anchor' for x in s.pend) and s.ps[0].anc is None:
        add_pend(s, b + 1, b + D, -1, 'S', 'anchor', None)


def honest_seller_decisions(s, i, p, b, cfg):
    lo, hi = b + 1, b + cfg['D']
    if not anchor_ok(p) or p.anc[0] > b:
        return
    # answer newly opened disputes within D (R5 (ra))
    for name, sl in sorted(p.slots.items()):
        if not slot_open(sl):
            continue
        kind = name.split('_')[0]
        a, _ = answer_for(p, name, cfg)
        if kind == 'RD':
            if not sent(p, 'S_RD'):
                mark(p, 'S_RD')
                add_pend(s, lo, hi, i, 'S', 'proof', True)
            continue
        if a is not None:
            continue
        if kind == 'ND':
            typ = 'SIG' if p.sb_seller is not None else 'CTK'
        else:
            typ = 'K'
            if (cfg['rdl'] is not None and cfg['prof'] == 'C' and name == 'KEY_P'
                    and p.sb_seller is None and cfg['seller_rec_keyp']):
                # recommendation: no k on a payer-side key dispute of a sale without sigma_B
                if not any(slot_open(x) and n == 'KEY_T' for n, x in p.slots.items()):
                    continue
        tag = f'S_{typ}'
        if not sent(p, tag + f'@{name}'):
            mark(p, tag + f'@{name}')
            add_pend(s, lo, hi, i, 'S', 'answer', typ)
    if p.sampled and p.proof is None and b >= cfg['sample_blocks'][0] - 1 and not sent(p, 'S_PROOF'):
        mark(p, 'S_PROOF')
        add_pend(s, lo, hi, i, 'S', 'proof', True)


# ----------------------------------------------------------------------------
# transitions


def exec_pending(s, j, cfg, notes):
    lo, hi, i, actor, kind, arg = s.pend[j]
    s.pend = s.pend[:j] + s.pend[j + 1:]
    if kind == 'anchor':
        beta = [1 if (p.sb_seller is not None and p.sb_seller <= s.now) else 0 for p in s.ps]
        u = [False for p in s.ps]
        tx_anchor(s, beta, u, [False] * len(s.ps), cfg, notes)
        return f'S anchor beta={beta} u={[int(x) for x in u]}'
    p = s.ps[i]
    if kind == 'open':
        k, side, bund = arg
        r = tx_open(s, i, k, side, actor, bund, cfg, notes)
        if r is not None and actor in HONEST_OPENERS:
            p.notes = addt(p.notes, f'honest_revert:{actor}:{k}_{side}:{r}')
        return f'{actor} open {k}_{side}' + (' +DCH' if bund else '') + (f' [reverts: {r}]' if r else '')
    if kind == 'dch':
        r = tx_dch(s, i, arg, cfg, notes)
        return f'{actor} DCH on {arg}' + (f' [reverts: {r}]' if r else '')
    if kind == 'swap':
        r = tx_swap_proof(s, i, cfg, notes)
        return f'{actor} swap proof' + (f' [reverts: {r}]' if r else '')
    if kind == 'answer':
        r = tx_answer(s, i, arg, cfg, notes)
        return f'{actor} answer {arg}' + (f' [no effect: {r}]' if r else '')
    if kind == 'proof':
        r = tx_proof(s, i, arg, cfg, notes)
        return f'{actor} proof publish={arg}'
    raise ValueError(kind)


def adversary_moves(s, cfg):
    """List (label, fn) for adversarial and network moves at the current block.
    fn(t) mutates a clone and returns None when the move is valid, else a reason (discarded).

    Equivalences used (not reductions of behaviour): an off-chain k with H(k) != h_k is handled
    by the client exactly as no k (G6 (sa)), and an R_S or response that fails the client's check
    exactly as none (G6 (ga), (ra)); neither enters the received-response table. So only valid
    content is sent, at any block or never."""
    now = s.now
    moves = []
    seller = cfg['seller']
    for i, p in enumerate(s.ps):
        # ---- off-chain: seller -> buyer
        if not p.rs_sent and p.typ != 'COL':
            if seller == 'HON':
                if cfg['resp_lo'] <= now <= cfg['resp_hi']:
                    moves.append((f'S->B{i+1} R_S+response ok', lambda s, i=i: _rs(s, i, True)))
            elif p.typ == 'OBL':
                moves.append((f'S->B{i+1} R_S+response ok', lambda s, i=i: _rs(s, i, True)))
        if cfg['prof'] == 'C' and p.typ == 'OBL' and p.koff is None:
            if seller == 'HON':
                if p.k_flight is not None and now >= p.k_flight:
                    moves.append((f'net: k reaches B{i+1}', lambda s, i=i: _k(s, i, 'good')))
            elif p.signed is not None:
                moves.append((f'S->B{i+1} k good', lambda s, i=i: _k(s, i, 'good')))
        # ---- network: sigma_B to watchtowers and acks
        if p.typ == 'OBL' and p.signed is not None and cfg['ack_mode'] != 'none' and \
                not sent(p, 'gave_sb') and p.term is None:
            for w in (0, 1):
                if p.wt_has[w] is None and not p.wt_nd[w]:
                    moves.append((f'net: sigma_B reaches W{w+1}', lambda s, i=i, w=w: _wt(s, i, w)))
                if p.wt_has[w] is not None and not p.wt_nd[w] and p.ack[w] is None:
                    moves.append((f'net: ack of W{w+1} reaches B{i+1}', lambda s, i=i, w=w: _ack(s, i, w)))
        if seller == 'HON':
            continue
        # ---- seller on-chain (adversarial modes)
        if i == 0 and s.ps[0].anc is None and now in cfg['alphas']:
            moves.extend(_anchor_combos(s, cfg))
        if anchor_ok(p) and p.anc[0] <= now and p.term is None:
            for typ in ('CTK', 'K', 'SIG'):
                if typ == 'K' and cfg['prof'] != 'C':
                    continue
                if typ == 'SIG' and p.sb_seller is None:
                    continue
                moves.append((f'S answer {typ} (B{i+1})', lambda s, i=i, typ=typ: tx_answer(s, i, typ, cfg, [])))
            if p.sampled and p.proof is None and now in cfg['sample_blocks']:
                # the proof carries the bytes exactly in the byte stage (R4 (na), R5 (ra) delivery limit)
                moves.append((f'S sample proof (B{i+1})', lambda s, i=i: tx_proof(s, i, cfg['stage'] == 'byte', cfg, [])))
            if slot_open(p.slots.get('RD_P')):
                moves.append((f'S RD proof (B{i+1})', lambda s, i=i: tx_proof(s, i, True, cfg, [])))
    # ---- third-party actor X, MAL buyer
    for i, p in enumerate(s.ps):
        if p.term is not None:
            # deferred deposit judgement: X may challenge (only mismatches matter)
            if not p.ctgood and cfg['colluder'] and cfg['x_dch']:
                for nm in ('ND_T', 'KEY_T'):
                    if nm in p.slots and nm not in p.deps:
                        moves.append((f'X DCH on {nm} (after terminal)',
                                      lambda s, i=i, nm=nm: _grow_dch(s, i, nm, cfg)))
            continue
        actors = []
        if cfg['colluder']:
            actors.append(('X', 'T'))
            if cfg['forge']:
                actors.append(('X', 'P'))
        if p.typ == 'MAL':
            actors.append(('B', 'P'))
        for actor, side in actors:
            kinds = ['ND', 'KEY'] if cfg['prof'] == 'C' else ['ND']
            if actor == 'B':
                kinds = kinds + ['RD']
            for k in kinds:
                if p.slots.get(slot_name(k, side, cfg)) is not None:
                    continue
                tag = ' [forged sigma_W]' if actor == 'X' and side == 'P' else ''
                moves.append((f'{actor} open {k}_{side} (B{i+1}){tag}',
                              lambda s, i=i, k=k, side=side, actor=actor: tx_open(s, i, k, side, actor, None, cfg, [])))
                if k == 'KEY' and not p.ctgood:
                    moves.append((f'{actor} open KEY_{side}+DCH (B{i+1}){tag}',
                                  lambda s, i=i, side=side, actor=actor: tx_open(s, i, 'KEY', side, actor, 'ok', cfg, [])))
        if cfg['colluder'] and not p.ctgood and cfg['x_dch']:
            for nm in ('ND_P', 'ND_T', 'KEY_P', 'KEY_T'):
                if slot_open(p.slots.get(nm)):
                    moves.append((f'X DCH on {nm} (B{i+1})', lambda s, i=i, nm=nm: _refund_dch(s, i, nm, cfg)))
    return moves


def _grow_dch(s, i, nm, cfg):
    n = len(s.ps[i].dch)
    r = tx_dch(s, i, nm, cfg, [])
    if r is None and len(s.ps[i].dch) == n:
        return 'nochange'
    return r


def _refund_dch(s, i, nm, cfg):
    r = tx_dch(s, i, nm, cfg, [])
    if r is None and s.ps[i].term is None:
        return 'nochange'
    return r


def _anchor_combos(s, cfg):
    out = []
    import itertools
    per = []
    for p in s.ps:
        opts = []
        has_sb = p.sb_seller is not None and p.sb_seller <= s.now
        betas = (0, 1) if has_sb else (0,)
        for beta in betas:
            for u in (False, True):
                swaps = (False,)
                if cfg['seller'] == 'ADV' and p.signed is not None and beta == 0 and not u:
                    swaps = (False, True)
                for sw in swaps:
                    opts.append((beta, u, sw))
        per.append(opts)
    for combo in itertools.product(*per):
        beta = [c[0] for c in combo]
        u = [c[1] for c in combo]
        sw = [c[2] for c in combo]
        out.append((f'S anchor beta={beta} u={[int(x) for x in u]} swap={[int(x) for x in sw]}',
                    lambda s, beta=beta, u=u, sw=sw: tx_anchor(s, beta, u, sw, cfg, [])))
    return out


def _rs(s, i, ok):
    p = s.ps[i]
    p.rs_sent = True
    p.rs = s.now
    p.rs_ok = ok


def _k(s, i, o):
    p = s.ps[i]
    p.koff = o
    p.koff_blk = s.now
    if o == 'good' and p.k_seen is None:
        p.k_seen = s.now


def _wt(s, i, w):
    p = s.ps[i]
    h = list(p.wt_has)
    h[w] = s.now
    p.wt_has = tuple(h)


def _ack(s, i, w):
    p = s.ps[i]
    a = list(p.ack)
    a[w] = s.now
    p.ack = tuple(a)


def honest_seller_offchain(s, cfg):
    """Honest seller releases k off chain once it holds sigma_B (G6 (sa) order)."""
    if cfg['seller'] != 'HON' or cfg['prof'] != 'C':
        return
    for p in s.ps:
        if p.sb_seller is not None and p.k_flight is None:
            p.k_flight = s.now


def coarse_ok(s, lab, off, cfg):
    """Plan 2.6 reduction: off-chain messages only at blocks {0, t_sig - 1, t_sig} (or never);
    seller answers only one block after a dispute opens or at the end of its T_d."""
    now = s.now
    if off:
        return now in (0, cfg['t_sig'] - 1, cfg['t_sig'])
    if ' answer ' in lab:
        ok = set()
        for p in s.ps:
            for sl in p.slots.values():
                if sl is not None and sl[END] is None:
                    base = sl[BASE] if sl[BASE] is not None else now
                    ok |= {sl[O] + 1, base + cfg['T_d']}
        return now in ok
    return True


def can_advance(s, cfg):
    for (lo, hi, i, actor, kind, arg) in s.pend:
        if hi <= s.now:
            return False
    if cfg['seller'] == 'HON':
        for p in s.ps:
            if not p.rs_sent and p.typ != 'COL' and s.now >= cfg['resp_hi']:
                return False
    if cfg['seller'] in ('WITHHOLD', 'GARBAGE'):
        if s.ps[0].anc is None and s.now >= cfg['alphas'][-1]:
            return False
        for p in s.ps:
            if p.sampled and p.proof is None and anchor_ok(p) and not p.anc[2] and \
                    p.term is None and s.now >= cfg['sample_blocks'][-1]:
                return False
    return True


def advance(s, cfg):
    notes = []
    expiries(s, cfg, notes)
    honest_decisions(s, cfg)
    honest_seller_offchain(s, cfg)
    s.now += 1


def successors(s, cfg):
    """Off-chain moves (messages) commute with on-chain transactions inside a block, because
    honest agents decide only at the end of a block and the contract reads no off-chain state.
    They are therefore scheduled before the first on-chain transaction of the block (s.oc)."""
    out = []
    for j, (lo, hi, i, actor, kind, arg) in enumerate(s.pend):
        if lo <= s.now <= hi:
            t = s.clone()
            lab = exec_pending(t, j, cfg, [])
            t.oc = True
            out.append((f'b{s.now}: {lab}', t))
    for lab, fn in adversary_moves(s, cfg):
        off = lab.startswith('S->') or lab.startswith('net:')
        if off and s.oc:
            continue
        if cfg['coarse'] and not coarse_ok(s, lab, off, cfg):
            continue
        t = s.clone()
        if fn(t) is not None:
            continue
        if not off:
            t.oc = True
        out.append((f'b{s.now}: {lab}', t))
    if s.now < cfg['H'] and can_advance(s, cfg):
        t = s.clone()
        advance(t, cfg)
        t.oc = False
        out.append((None, t))
    return out


def quiescent(s, cfg):
    """True when no later move can change any outcome, deposit or property."""
    if s.pend:
        return False
    for p in s.ps:
        if any(slot_open(sl) for sl in p.slots.values()):
            return False
        if any(n not in p.deps for n in p.slots):
            return False  # a deferred third-party judgement is pending
        if p.term is None:
            if s.now <= cfg['E'] + 1 or s.now <= cfg['sample_blocks'][-1]:
                return False
            if p.anc is None:
                return False
        if cfg['seller'] == 'HON' and not p.rs_sent and p.typ != 'COL':
            return False
    return True


def final_close(s, cfg):
    """At H: expire, then pay what is left (cursor) and settle."""
    t = s.clone()
    expiries(t, cfg, [])
    for p in t.ps:
        if p.term is None and all(not slot_open(sl) for sl in p.slots.values()):
            p.term = ('PAID', t.now, 'cursor')
        resolve_deposits(t, p, cfg, end_of_block=True)
    return t


def initial_states(cfg):
    import itertools
    res = []
    n = len(cfg['buyers'])
    ctg_opts = (True,) if cfg['seller'] in ('HON', 'WITHHOLD') else (True, False)
    for ctgs in itertools.product(ctg_opts, repeat=n):
        for smp in itertools.product(cfg['sampled_opts'], repeat=n):
            s = S()
            s.now = 0
            s.pend = ()
            s.ps = [new_purchase(cfg['buyers'][k], ctgs[k], smp[k]) for k in range(n)]
            s.viol = ()
            s.oc = False
            res.append(s)
    return res


def _dig(k):
    # 64-bit tuple hash; for 1e7 states the chance of any collision is about 3e-6
    return hash(k)


def explore(cfg, check_state, check_final):
    """BFS over reachable states (deduplicated by a 128-bit digest of the state).
    check_state(s) and check_final(s) return lists of violated property ids.
    Returns stats and the first (shortest) counterexample trace per property."""
    KEY_TIMES[0] = cfg['rdl'] is not None
    seen = {}
    labels = {}
    lab_list = []

    def lab_id(lab):
        if lab not in labels:
            labels[lab] = len(lab_list)
            lab_list.append(lab)
        return labels[lab]

    q = deque()
    for s0 in initial_states(cfg):
        d = _dig(s0.key())
        if d not in seen:
            seen[d] = (None, lab_id('init ' + _init_label(s0)))
            q.append(s0)
    cex = {}
    finals = 0
    edges = 0
    outcomes = {}
    reverts = {}
    while q:
        s = q.popleft()
        d = _dig(s.key())
        if cfg.get('progress') and len(seen) >= cfg.setdefault('_next', 200000):
            cfg['_next'] += 200000
            print('  ..', len(seen), 'states, queue', len(q), 'now', s.now, flush=True)
        for v in check_state(s, cfg):
            if v not in cex:
                cex[v] = (d, None)
        qui = quiescent(s, cfg)
        succ = [] if qui else successors(s, cfg)
        if (s.now >= cfg['H'] and not s.pend) or qui:
            f = final_close(s, cfg)
            finals += 1
            out = tuple((p.typ, p.term[0] if p.term else None) for p in f.ps)
            outcomes[out] = outcomes.get(out, 0) + 1
            for p in f.ps:
                for n in p.notes:
                    if n.startswith('honest_revert'):
                        reverts[n] = reverts.get(n, 0) + 1
            for v in check_final(f, cfg):
                if v not in cex:
                    cex[v] = (d, f)
        for lab, t in succ:
            edges += 1
            td = _dig(t.key())
            if td not in seen:
                seen[td] = (d, lab_id(lab) if lab is not None else None)
                q.append(t)
                if len(seen) > cfg['max_states']:
                    raise RuntimeError('state limit')
    traces = {}
    for v, (dd, f) in cex.items():
        tr = trace(seen, dd, lab_list)
        if f is not None:
            tr.append('end: ' + describe(f))
        traces[v] = tr
    return dict(states=len(seen), edges=edges, finals=finals, outcomes=outcomes, reverts=reverts), traces


def explore_dfs(cfg, check_state, check_final):
    """Depth-first variant: the visited set holds 64-bit state hashes only and each stack entry
    carries its own path (shared tails), so memory is bounded by the set and the stack depth."""
    KEY_TIMES[0] = cfg['rdl'] is not None
    seen = set()
    stack = []
    for s0 in initial_states(cfg):
        d = _dig(s0.key())
        if d not in seen:
            seen.add(d)
            stack.append((s0, ('init ' + _init_label(s0), None)))
    cex = {}
    finals = edges = 0
    outcomes = {}
    reverts = {}

    def unroll(path):
        out = []
        while path is not None:
            out.append(path[0])
            path = path[1]
        return out[::-1]

    while stack:
        s, path = stack.pop()
        if cfg.get('progress') and len(seen) >= cfg.setdefault('_next', 500000):
            cfg['_next'] += 500000
            print('  ..', len(seen), 'states, stack', len(stack), flush=True)
        for v in check_state(s, cfg):
            if v not in cex:
                cex[v] = unroll(path)
        if partial_stop(cex, seen, cfg):
            break
        qui = quiescent(s, cfg)
        succ = [] if qui else successors(s, cfg)
        if (s.now >= cfg['H'] and not s.pend) or qui:
            f = final_close(s, cfg)
            finals += 1
            out = tuple((p.typ, p.term[0] if p.term else None) for p in f.ps)
            outcomes[out] = outcomes.get(out, 0) + 1
            for p in f.ps:
                for n in p.notes:
                    if n.startswith('honest_revert'):
                        reverts[n] = reverts.get(n, 0) + 1
            for v in check_final(f, cfg):
                if v not in cex:
                    cex[v] = unroll(path) + ['end: ' + describe(f)]
        for lab, t in succ:
            edges += 1
            td = _dig(t.key())
            if td not in seen:
                seen.add(td)
                stack.append((t, (lab, path) if lab is not None else path))
    complete = not stack
    return dict(states=len(seen), edges=edges, finals=finals, outcomes=outcomes, reverts=reverts,
                complete=complete), cex


def partial_stop(cex, seen, cfg):
    """Stop early (search not exhaustive, reported as partial) when a property listed in
    cfg['stop_on'] has a counterexample, or at the state cap."""
    if any(v in cex for v in cfg.get('stop_on', ())):
        return True
    return len(seen) > cfg['max_states']


def describe(f):
    out = []
    for i, p in enumerate(f.ps):
        out.append(f'B{i+1}({p.typ}) term={p.term} signed={p.signed} anc={p.anc} rs={p.rs} rs_ok={p.rs_ok} '
                   f'koff={p.koff} ctgood={p.ctgood} pub={p.pub} rec={p.rec} a_ctk={p.a_ctk} a_k={p.a_k} '
                   f'a_sig={p.a_sig} dch={p.dch} slots={p.slots} deps={p.deps} gas={p.gas} '
                   f'tp_in={p.tp_dep_in} sb_seller={p.sb_seller} acks={p.ack} wt_has={p.wt_has} notes={p.notes}')
    return ' | '.join(out)


def _init_label(s):
    return ' '.join(f'B{i+1}:{p.typ} ctgood={int(p.ctgood)} sampled={int(p.sampled)}' for i, p in enumerate(s.ps))


def trace(seen, d, lab_list):
    out = []
    while d is not None:
        parent, lid = seen[d]
        if lid is not None:
            out.append(lab_list[lid])
        d = parent
    out.reverse()
    return out
