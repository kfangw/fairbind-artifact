"""Grid definitions (MC1 plan 2.6, 4, 6). Each function returns a list of (name, cfg overrides)."""
import itertools


def _profiles(rdls=(None, 1, 3)):
    for prof, rdl, t_sig, stage in itertools.product(('P', 'C'), rdls, (2, 4), ('byte', 'hash')):
        yield dict(prof=prof, rdl=rdl, t_sig=t_sig, stage=stage)


def _nm(prefix, d):
    return f"{prefix}-{d['prof']}-rdl{d['rdl']}-t{d['t_sig']}-{d['stage']}"


def BP1():
    """Buyer protection, one obliged client, adversarial seller (union of behaviours) and colluder."""
    # plaintext: full move set, breadth first; ciphertext: no colluder mismatching DCH (it only
    # refunds the buyer), depth first (memory)
    return [(_nm('BP1', d), dict(seller='ADV', buyers=('OBL',), x_dch=(d['prof'] == 'P'),
                                 dfs=(d['prof'] == 'C'), **d))
            for d in _profiles()]


def BP1_modes():
    """The two narrower seller behaviours, reported separately (subsets of ADV)."""
    out = []
    for mode in ('WITHHOLD', 'GARBAGE'):
        for d in _profiles(rdls=(None,)):
            out.append((_nm('BP1' + mode[:2], d), dict(seller=mode, buyers=('OBL',), **d)))
    return out


def SP1():
    """Seller protection: honest seller, obliged client B1 or malicious unsigned buyer B2, third parties."""
    out = []
    for b in ('OBL', 'MAL'):
        for d in _profiles():
            out.append((_nm('SP1' + b, d), dict(seller='HON', buyers=(b,), **d)))
    return out


def G2():
    """Two purchases in one run (coarse timing, plan 2.6), depth first (memory), t_sig = 2."""
    out = []
    for d in _profiles(rdls=(None,)):
        if d['stage'] != 'byte' or d['t_sig'] != 2:
            continue
        out.append((_nm('G2BP', d), dict(seller='ADV', buyers=('OBL', 'COL'), coarse=True, dfs=True,
                                         x_dch=False, **d)))
        out.append((_nm('G2SP', d), dict(seller='HON', buyers=('OBL', 'MAL'), coarse=True, dfs=True, **d)))
    return out


def E5_pre_anchor():
    out = []
    for mode in ('literal', 'revert_before_anchor', 'td_from_anchor', 'revert_before_Ae'):
        for prof in ('P', 'C'):
            base = dict(prof=prof, rdl=None, t_sig=2, stage='byte')
            out.append((f'E5ga-{mode}-SP-{prof}', dict(seller='HON', buyers=('OBL',), pre_anchor=mode, **base)))
            out.append((f'E5ga-{mode}-SPMAL-{prof}', dict(seller='HON', buyers=('MAL',), pre_anchor=mode, **base)))
            if prof == 'P':  # buyer side of (ga) concerns the client's opening time, profile-independent
                out.append((f'E5ga-{mode}-BP-{prof}', dict(seller='ADV', buyers=('OBL',), pre_anchor=mode, **base)))
    return out


def E5_client():
    out = []
    for t_sig in (2, 4):
        base = dict(prof='C', rdl=None, t_sig=t_sig, stage='byte', seller='ADV', buyers=('OBL',),
                    x_dch=False, dfs=True)
        out.append((f'E5na-separate-t{t_sig}', dict(bundle=False, **base)))
        out.append((f'E5da-late-t{t_sig}', dict(late_trigger=True, **base)))
        out.append((f'E5ra-rs-t{t_sig}', dict(kcrit='rs', **base)))
        out.append((f'E5ma-always-t{t_sig}', dict(dch_always=True, **base)))
    return out


def E5_rdl():
    out = []
    for rdl in range(1, 7):
        for hold, bind in ((False, False), (True, False), (True, True)):
            for prof in ('P', 'C'):
                out.append((f'E5rdl-{rdl}-hold{int(hold)}-empty{int(bind)}-{prof}',
                            dict(seller='HON', buyers=('OBL',), prof=prof, rdl=rdl, t_sig=4,
                                 stage='hash', hold=hold, bind_empty=bind, colluder=False,
                                 sampled_opts=(False,), d_obs=0)))
    # d_obs = 0, d_tx = 2 keeps D = 2 and lets the holding condition T_rs > d_inc + d_obs + d_resp
    # (3.4) hold inside the grid (T_rs = t_sig = 4 > 3)
    return out


def E5_dkey():
    out = []
    for dk in (0, 1, 2):  # c_k = 1
        for rdl in (None, 3):
            out.append((f'E5dkey-{dk}-rdl{rdl}', dict(seller='HON', buyers=('OBL',), prof='C', rdl=rdl,
                                                      t_sig=2, stage='hash', d_key=dk)))
    return out


def SELF():
    base = dict(prof='C', rdl=None, t_sig=2, stage='hash', seller='ADV', buyers=('OBL',), x_dch=False, dfs=True)
    return [
        ('F1-forge', dict(forge=True, stop_on=('C1',), **base)),
        ('F2-single-slot', dict(single_slot=True, **base)),
        ('F3-ack-one', dict(ack_mode='one', **base)),
        ('F4-ack-none', dict(ack_mode='none', **base)),
        ('F5-Tx1', dict(T_x=1, **base)),
        ('F6-rdl-record', dict(rdl_record_blocks=True, **dict(base, rdl=1, prof='P', stage='byte'))),
        ('F7-no-post-terminal-dch', dict(no_post_terminal_dch=True, **base)),
        ('F8-tsig9-breaks-check11', dict(**dict(base, t_sig=9))),
    ]


def SELF_F1():
    base = dict(prof='C', rdl=None, t_sig=2, stage='hash', seller='ADV', buyers=('OBL',), x_dch=False, dfs=True)
    return [('F1-forge', dict(forge=True, stop_on=('C1',), **base))]


def SP1_MALC():
    """The unsigned-buyer ciphertext configurations with a response deadline, before and after
    the documentation fix of MC1_fix proposal.md (one fix round)."""
    out = []
    for fix in (True,):  # the unfixed runs are the SP1 ones
        for d in _profiles(rdls=(1, 3)):
            if d['prof'] != 'C':
                continue
            out.append((_nm('SP1MAL' + ('fix' if fix else ''), d),
                        dict(seller='HON', buyers=('MAL',), fix_doc_published=fix, **d)))
    return out


def BP1_rerun():
    """The two BP1 configurations whose C1-dl came from the checker's choice of block (MC1_results.md 9 (sec.) 12)."""
    return [(n, kw) for n, kw in BP1() if n in ('BP1-C-rdl3-t2-byte', 'BP1-C-rdl3-t4-byte')]
