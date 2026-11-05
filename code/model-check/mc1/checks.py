"""Properties of the MC1 plan (section 3), checked on every reachable state and every end state."""
from model import anchor_ok, slot_open, HONEST_OPENERS, answer_for


def justified(p, cfg):
    """P10 8.3 received-response table. Returns (justified, block the response reached the buyer)."""
    signed = p.signed is not None
    swap = anchor_ok(p) and p.anc[3]
    if signed:
        if swap and p.anc[1] == 0:
            return False, None, 'swap'
        if cfg['prof'] == 'P':
            return True, p.rs, 'signed_plain'
        if p.k_seen is not None and p.ctgood:
            return True, max(p.rs, p.k_seen), 'signed_cipher_k'
        return False, None, 'signed_cipher_no_valid_k_or_bad_ct' if p.k_seen is None else 'signed_cipher_bad_decrypt'
    # unsigned: (ga) public record, (na) delivery by (ct, k) on chain, (da) off-chain match,
    # (ra) non-delivery. The table fixes which response counts (all routes give the leaf's
    # response here); the block returned is the earliest block at which a route existed, which is
    # what the response-deadline check compares with eta + r_dl (R5 (ra): (ct, k) answer either
    # kind of dispute and are judged by the block they entered)
    times = []
    if p.pub is not None:
        times.append((p.pub[1], 'public_record'))
    if p.a_ctk is not None and p.ctgood:
        times.append((p.a_ctk, 'nd_delivery'))
    if cfg['prof'] == 'P' and p.rs is not None and p.rs_ok:
        times.append((p.rs, 'offchain'))
    if cfg['prof'] == 'C' and p.rs is not None and p.rs_ok and p.k_seen is not None and p.ctgood:
        times.append((max(p.rs, p.k_seen), 'offchain'))
    if times:
        t, why = min(times)
        return True, t, why
    return False, None, 'nondelivery'


def check_state(s, cfg):
    v = []
    for i, p in enumerate(s.ps):
        for n in p.notes:
            if n.startswith('honest_dep_to_seller'):
                v.append('C2')
            if n == 'double_settle':
                v.append('B1')
            if n.startswith('honest_revert'):
                _, actor, slot, reason = n.split(':')
                if reason == 'slot_shared':
                    v.append('I1')
                if reason == 'record' and cfg['rdl'] is not None and slot == 'ND_P' and p.rec is not None \
                        and p.rec > cfg['rdl']:
                    v.append('I1')
            if n.startswith('confirmed_failure') and cfg['seller'] == 'HON':
                v.append('S3')
        for name, sl in p.slots.items():
            if name.endswith('_T') and sl[1] in HONEST_OPENERS:
                v.append('I3')
        # reserve: deposits of the honest team locked at once (client ND, client KEY, W1, W2)
        locked = sum(1 for n, sl in p.slots.items() if sl[1] in HONEST_OPENERS and n not in p.deps)
        if locked > 4:
            v.append('C2')
    return v


def oracle_recipient(p, name, cfg):
    """R5 (ra) (3) and appendix A, written independently of resolve_deposits."""
    sl = p.slots[name]
    opener, end = sl[1], sl[4]
    kind, side = name.split('_')
    if kind == 'RD':
        return 'split' if sl[5] == 'passed' else opener
    a, typ = answer_for(p, name, cfg)
    if a is not None and a > end:
        a, typ = None, None
    if side == 'P':
        if kind == 'ND' and typ == 'SIG':
            return 'seller'
        return opener
    if a is None:
        return opener
    if typ == 'SIG':
        return 'seller'
    eff = max(a, sl[0])
    if any(eff <= b <= eff + cfg['T_x'] for b, _ in p.dch):
        return opener
    return 'seller'


def check_final(f, cfg):
    v = []
    for i, p in enumerate(f.ps):
        # U1
        if p.term is None:
            v.append('U1')
        if any(slot_open(sl) for sl in p.slots.values()):
            v.append('U1')
        for name in p.slots:
            if name not in p.deps:
                v.append('B1')
            elif p.deps[name] != oracle_recipient(p, name, cfg):
                v.append('B2')
        for name, sl in p.slots.items():
            if name.endswith('_P') and p.deps.get(name) == 'seller' and sl[5] != 'sig':
                v.append('I2')
            if cfg['rdl'] is not None and name == 'ND_P' and sl[5] == 'answered':
                a, typ = answer_for(p, name, cfg)
                if typ == 'CTK' and p.a_ctk is not None and p.a_ctk > cfg['rdl']:
                    v.append('I2')
        paid = p.term is not None and p.term[0] == 'PAID'
        if cfg['seller'] != 'HON' and p.typ == 'OBL':
            ok, t, why = justified(p, cfg)
            if paid and not ok:
                v.append('CORE' if why == 'swap' else 'C1')
            if paid and ok and cfg['rdl'] is not None and p.signed is None and t > cfg['rdl']:
                v.append('C1-dl')
        if cfg['seller'] == 'HON' and p.typ in ('OBL', 'MAL'):
            if not paid:
                if cfg['rdl'] is None:
                    v.append('S1')
                else:
                    cls = refund_class(p, cfg)
                    if cls is None:
                        v.append('S1-dl')
            if not p.payer_opened:
                cost = p.gas
                if cost > p.tp_dep_in:
                    v.append('S2')
    return v


def refund_class(p, cfg):
    """Loss branches the rule documents for a response-deadline profile (R5 (ra), check (1))."""
    if p.typ == 'MAL' and cfg['prof'] == 'P':
        return 'unsigned_buyer_plain'
    if p.typ == 'OBL' and p.signed is not None:
        # sigma_B had not reached the seller when the first payer-side dispute opened
        # (acks lost or late; R5 (ra) response-deadline paragraph, G6 head)
        opens = [sl[0] for n, sl in p.slots.items() if n.endswith('_P')]
        if p.sb_seller is None or (opens and p.sb_seller >= min(opens)):
            return 'ack_not_received'
    if p.typ == 'OBL' and p.signed is None and p.rs is not None and (p.rs >= cfg['t_sig']):
        return 'client_could_not_sign'
    if p.typ == 'MAL' and cfg['prof'] == 'C' and p.pub is None and p.a_ctk is None and p.a_k is None:
        # the unsigned buyer holds only a ct it cannot use; the rule calls this refund legitimate
        # (R5 (ra) response-deadline paragraph, "refund is justified"), not a seller loss
        return 'cipher_unsigned_no_content'
    if cfg.get('fix_doc_published') and p.typ == 'MAL' and cfg['prof'] == 'C':
        # fix candidate (MC1_fix proposal.md, G9z 1 grade-1): document the loss of v when the response of an
        # unsigned buyer's sale reaches the chain after eta + r_dl (proof, response dispute, answer)
        return 'cipher_unsigned_published_after_deadline'
    return None
