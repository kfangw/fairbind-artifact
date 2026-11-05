"""Release of the rule edition 10 candidate v0.3 (R4 to R7) with a fixed proof deadline, buyer acceptance and the
narrow freeze (registration R10).

Edition 10 (tiers 0 and 1, detection floor s = 1) has no judge: a sampled sale is closed by the seller's proof, and a
proof missing at the deadline T_p is a confirmed failure that the release call itself processes. With the epoch E of
an address starting at ledger block S(E) (epochs of `epoch_blocks` blocks), the replay path is

  A(E) = S(E) + epoch_blocks - 1 + anchor_delay        anchor deadline A_e; the honest anchor lands at A(E)
  M(E) = A(E) + vrf_response + 1 + vrf_slack            sample value deadline M_e = A_e + tau_V + 1 + T_V; the value
                                                        lands at M(E) (the late end)
  P(E) = M(E) + proof_window                            proof deadline; an honest proof lands at P(E) (fixed deadline,
                                                        default) or at M(E) + proof_delay

The release cursor of the address passes E (R6 (a)) in the first block where all of these hold (a condition met by a
transaction in block x holds from x + 1):

  (0)+(1) the sample value is on chain and E is anchored            M(E) + 1   (A(E) + 1 is earlier)
  (2)     every sampled sale of E (accepted ones included) is final  P(E) + 1   (only when E has a sampled sale)
  (3)     every purchase of E that is not accepted is past the
          dispute window T_c (counted from its settlement)           max s + T_c + 1
          and, if it is unsigned (no buyer signature on the anchor),
          past W_e = M_e + w_b                                       M(E) + w_b + 1
  (4)     every earlier epoch with a sale of the address is passed    R(previous epoch)

and `keeper_delay` blocks later. Epochs without a sale carry no condition. A sale that is not accepted is paid at
R(E). A sale the buyer accepted (a = 1 in a buyer signature confirmed by the anchor, R5 (a)) is paid in the anchor
transaction, at block A(E); it stays in the sample. Acceptance needs a buyer signature, so an unsigned sale is never
accepted. Which sales are signed and accepted is fixed by a hash of the address and the list row (the replay has no
x402 nonce; the row stands in for it), not by any outcome of the replay:

  unsigned  iff SHA-256("fairbind/R10/sign|<address>|<row>")   < ceil(unsigned_ppm * 2^256 / 10^6)
  accepted  iff signed and SHA-256("fairbind/R10/accept|<address>|<row>") < ceil(accept_ppm * 2^256 / 10^6)

(digests read as big-endian unsigned integers; a share of 10^6 ppm takes every sale, 0 none). The accepted sets are
nested in accept_ppm.

A confirmed failure of a sampled sale c in epoch E is processed at block P_fail(E) + 1 = M(E) + proof_window + 1 (the
release call after the deadline). It freezes the sales of the address settled at or after c that are not accepted and
not yet paid (R7 (b)); the cursor still passes E and pays the earlier sales of E. There is no held-settlement cap in
edition 10 (v0.3 section 4), so admission is the bucket of edition 7.

Registration R11 (rule edition 10 candidate v0.6 and later) adds two switches to the same path, both off by default
so that the R10 outputs are unchanged:

  seller_epoch_k   the seller epoch E of v0.6 R1 (a) and R6 (a): k consecutive profile epochs e = kE .. kE + k - 1 with the
                   same boundaries. The cursor passes E in the first block where (0) to (3) hold for every profile epoch
                   e of E, each with its own A(e), M(e), P(e) and W_e; every sale of E that is not accepted is paid at
                   R(E). An accepted sale is still paid at the anchor deadline A(e) of its own profile epoch. k = 1 is
                   the R10 path.
  dispute_from     where the dispute window T_c of a purchase that is not accepted starts: 'settlement' (v0.3 R6 (a)(3),
                   R10: settled + T_c) or 'anchor' (v0.6 R5 (c): every dispute window runs to A_e + T_c). With
                   'anchor' the term of profile epoch e is A(e) + T_c + 1 whatever the settlement block.

Everything here is integer and pure; the functions take ledger blocks.
"""
import hashlib
from dataclasses import dataclass, asdict

import numpy as np

MODES = ('fixed10',)
DISPUTE_FROM = ('settlement', 'anchor')
SIGN_DOMAIN = 'fairbind/R10/sign'
ACCEPT_DOMAIN = 'fairbind/R10/accept'
PPM = 1_000_000
TWO256 = 1 << 256


@dataclass(frozen=True)
class Timing10:
    """Path constants of the edition-10 release (blocks) and the buyer shares (ppm)."""
    anchor_delay: int = 100           # d_A: A_e = last block of the epoch + d_A
    vrf_response: int = 100           # tau_V
    vrf_slack: int = 50               # T_V
    proof_window: int = 1800          # T_p
    dispute_window: int = 1800        # T_c, from the settlement of the purchase
    bind_window: int = 300            # w_b (W_e = M_e + w_b for unsigned sales)
    proof_delay: int = None           # None: an honest proof lands at the deadline M_e + T_p; int: at M_e + proof_delay
    keeper_delay: int = 0             # kappa_r
    accept_ppm: int = 0               # buyer acceptance share a (of signed sales)
    unsigned_ppm: int = 0             # share of unsigned sales
    accept_over_cap: bool = False     # True: sales above V are accepted and sampled with probability 1 (tiers 0, 1)
    seller_epoch_k: int = 1           # k: profile epochs per seller epoch (v0.6 R1 (a)); 1 is the R10 path
    dispute_from: str = 'settlement'  # 'settlement' (v0.3, R10) or 'anchor' (v0.6 R5 (c): A_e + T_c)

    def __post_init__(self):
        if int(self.seller_epoch_k) < 1:
            raise ValueError('seller_epoch_k must be >= 1')
        if self.dispute_from not in DISPUTE_FROM:
            raise ValueError(f'dispute_from must be one of {DISPUTE_FROM}')
        for k in ('anchor_delay', 'vrf_response', 'vrf_slack', 'proof_window', 'dispute_window', 'bind_window',
                  'keeper_delay'):
            if getattr(self, k) < 0:
                raise ValueError(f'{k} must be >= 0')
        if self.proof_delay is not None and not 0 <= self.proof_delay <= self.proof_window:
            raise ValueError('proof_delay must lie in [0, proof_window]')
        for k in ('accept_ppm', 'unsigned_ppm'):
            if not 0 <= getattr(self, k) <= PPM:
                raise ValueError(f'{k} must lie in [0, 10^6]')

    def describe(self):
        return asdict(self)


@dataclass(frozen=True)
class Release10:
    """The edition-10 release of one run."""
    timing: Timing10
    mode: str = 'fixed10'

    def describe(self):
        return dict(mode=self.mode, **self.timing.describe())


def check_epoch_length(timing, epoch_blocks):
    """Admissibility check (1) of v0.3 appendix A: T_epoch >= tau_V + 1 + T_V."""
    if epoch_blocks < timing.vrf_response + 1 + timing.vrf_slack:
        raise ValueError('epoch shorter than tau_V + 1 + T_V')


def schedule(epoch_start, epoch_blocks, timing):
    """(A, M, P_honest, P_fail) of an epoch starting at ledger block `epoch_start`."""
    a = epoch_start + epoch_blocks - 1 + timing.anchor_delay
    m = a + timing.vrf_response + 1 + timing.vrf_slack
    p_fail = m + timing.proof_window
    p_honest = p_fail if timing.proof_delay is None else m + timing.proof_delay
    return a, m, p_honest, p_fail


def threshold(ppm):
    """ceil(ppm * 2^256 / 10^6); None for ppm >= 10^6 (always), 0 for ppm = 0 (never)."""
    if ppm >= PPM:
        return None
    return -(-ppm * TWO256 // PPM)


def _below(domain, address, row, thr):
    if thr is None:
        return True
    if thr == 0:
        return False
    d = hashlib.sha256(f'{domain}|{address}|{row}'.encode()).digest()
    return int.from_bytes(d, 'big') < thr


def buyer_flags(address, rows, timing):
    """(signed, accepted) boolean arrays for the list rows of one address (lowercase 0x address)."""
    rows = np.asarray(rows, dtype=np.int64).tolist()
    tu, ta = threshold(timing.unsigned_ppm), threshold(timing.accept_ppm)
    signed = np.array([not _below(SIGN_DOMAIN, address, r, tu) for r in rows], dtype=bool)
    accepted = np.array([s and _below(ACCEPT_DOMAIN, address, r, ta) for s, r in zip(signed.tolist(), rows)],
                        dtype=bool)
    return signed, accepted


def seller_epoch_of(epochs, timing):
    """Seller epoch E = floor(e / k) of each profile epoch e (v0.6 R1 (a): k consecutive profile epochs, same boundaries)."""
    return np.asarray(epochs, dtype=np.int64) // int(timing.seller_epoch_k)


def epoch_release(blocks, epochs, sampled, accepted, signed, epoch_start, epoch_blocks, timing):
    """Payment block of every sale. `blocks` (ledger), `epochs` (profile epochs), `sampled`, `accepted`, `signed` are per
    sale with `epochs` non-decreasing in `blocks`; `epoch_start(e)` gives the ledger block where profile epoch e starts.
    Returns an int64 array and a dict seller epoch E -> dict(R, why, A, M, P, P_fail, epochs); with k = 1 the seller
    epoch is the profile epoch and A, M, P, P_fail are its deadlines, with k > 1 they are those of the last profile epoch
    of E that has a sale and `epochs` lists the profile epochs of E with a sale."""
    blocks = np.asarray(blocks, dtype=np.int64)
    epochs = np.asarray(epochs, dtype=np.int64)
    sampled = np.asarray(sampled, dtype=bool)
    accepted = np.asarray(accepted, dtype=bool)
    signed = np.asarray(signed, dtype=bool)
    if (accepted & ~signed).any():
        raise ValueError('an accepted sale must be signed')
    n = len(blocks)
    out = np.zeros(n, dtype=np.int64)
    if n == 0:
        return out, {}
    sellers = seller_epoch_of(epochs, timing)
    order = np.lexsort((blocks, epochs, sellers))
    e_sorted, s_sorted = epochs[order], sellers[order]
    cut = np.flatnonzero(np.r_[True, s_sorted[1:] != s_sorted[:-1], True])
    prev = None
    detail = {}
    for lo, hi in zip(cut[:-1], cut[1:]):
        idx_E = order[lo:hi]
        E = int(s_sorted[lo])
        terms = []
        e_list = []
        a = m = p_h = p_f = None
        ecut = np.flatnonzero(np.r_[True, e_sorted[lo + 1:hi] != e_sorted[lo:hi - 1], True]) + lo
        for elo, ehi in zip(ecut[:-1], ecut[1:]):
            idx = order[elo:ehi]
            e = int(e_sorted[elo])
            e_list.append(e)
            a, m, p_h, p_f = schedule(int(epoch_start(e)), epoch_blocks, timing)
            terms.append(('sample', m + 1))
            if sampled[idx].any():
                terms.append(('proof', p_h + 1))
            open_idx = idx[~accepted[idx]]
            if len(open_idx):
                if timing.dispute_from == 'anchor':
                    terms.append(('dispute', a + timing.dispute_window + 1))
                else:
                    terms.append(('dispute', int(blocks[open_idx].max()) + timing.dispute_window + 1))
                if (~signed[open_idx]).any():
                    terms.append(('bind', m + timing.bind_window + 1))
            out[idx[accepted[idx]]] = a
        why, r = max(terms, key=lambda x: x[1])
        r += timing.keeper_delay
        if prev is not None and prev > r:
            why, r = 'cursor', prev
        prev = r
        out[idx_E[~accepted[idx_E]]] = r
        detail[E] = dict(R=r, why=why, A=a, M=m, P=p_h, P_fail=p_f, epochs=e_list)
    return out, detail


def fraud_x(blocks, values, release, epochs, sampled, accepted, epoch_start, epoch_blocks, timing, end):
    """Released fraudulent proceeds X (atomic) of one address that sells only fraudulent goods, s = 1: every sampled
    sale fails at its deadline. `blocks` sorted ascending, the other arrays aligned. Returns (X, f, c) with f the
    block of the first confirmed failure (-1 when none falls in the window) and c the settlement block of its sale.

    X sums the sales that are not accepted, are paid by `end`, and are not frozen: with a failure at f <= end, the
    sales settled before c, the seller epoch of c (its profile epoch when k = 1) being passed no earlier than
    f + keeper_delay; without one, every such sale with release <= end (a sale settled at or after c then has
    release > end)."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    release = np.asarray(release, dtype=np.int64)
    epochs = np.asarray(epochs, dtype=np.int64)
    sampled = np.asarray(sampled, dtype=bool)
    open_ = ~np.asarray(accepted, dtype=bool)
    if len(blocks) > 1 and (np.diff(blocks) < 0).any():
        raise ValueError('blocks must be sorted')
    s_idx = np.flatnonzero(sampled)
    if len(s_idx) == 0:
        return int(values[open_ & (release <= end)].sum()), -1, -1
    i = int(s_idx[0])
    c, e_c = int(blocks[i]), int(epochs[i])
    f = schedule(int(epoch_start(e_c)), epoch_blocks, timing)[3] + 1
    if f > end:
        return int(values[open_ & (release <= end)].sum()), -1, c
    sellers = seller_epoch_of(epochs, timing)
    r = np.where(sellers == sellers[i], np.maximum(release, f + timing.keeper_delay), release)
    return int(values[open_ & (blocks < c) & (r <= end)].sum()), f, c


def exact_expectation(blocks, values, s_prob, release, accepted, end):
    """sum_j v_j 1{not accepted_j} 1{R_j <= end} prod_{l: s_l <= s_j} (1 - pi_l) for s = 1 (atomic, float): the
    expectation of X over the sampling draws when the release blocks do not depend on them near the window end."""
    blocks = np.asarray(blocks, dtype=np.int64)
    q = 1.0 - np.asarray(s_prob, dtype=np.float64)
    prefix = np.r_[1.0, np.cumprod(q)]
    k = np.searchsorted(blocks, blocks, side='right')
    keep = (~np.asarray(accepted, dtype=bool)) & (np.asarray(release) <= end)
    return float((np.asarray(values, dtype=np.float64) * keep * prefix[k]).sum())
