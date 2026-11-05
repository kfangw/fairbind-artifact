"""Release by the seller's release cursor (rule edition 8, D2-39) and the held-settlement cap (D2-42).

Edition 7 releases a sale a fixed hold after its settlement (`deferBlocks`). Edition 8 pays a seller epoch
when the seller's release cursor passes it. The cursor passes epoch E (ledger blocks of one address) only when

  R1  E is sealed (on the replay's prompt path: the seal and the case opening are in block `open(E)`);
  R2  every sampled sale of E has its case in a final state (case end `open(E) + case_length`, or the end
      block given for that case, e.g. an injected failure);
  R3  the buyer window of every purchase of E is closed (`settled + buyer_window`; on unsigned accounts also
      W_e = M_e + bind_window with M_e the block of the sample value, `open(E) - 1` in the replay);
  R4  every earlier epoch of the address has been passed.

A condition met by a transaction in block x holds from block x + 1 (so the order of transactions inside one
block never matters), and the cursor moves `keeper_delay` blocks after the last condition holds. Every sale
of E is paid in that block R(E): it is held at every block t < R(E) and released at R(E). Epochs without a
sale of the address are passed at once and carry no condition.

The held-settlement cap (D2-42) rejects a new settlement when the address already has `n_cap` settlements that
are neither paid nor refunded (the replay has no refunds, so: settled, accepted and R > t). A rejected
settlement does not consume the bond bucket (the call reverts). `n_cap = ceil(q_S + r_S H_N)` with the bucket
of the address (`hold_cap`).

Everything here is integer and pure. The functions take ledger blocks; `open_of_epoch` maps an epoch number
to the ledger block of its seal and case opening.
"""
import heapq
from dataclasses import dataclass, asdict

import numpy as np

from bucket import PPM

MODES = ('hold', 'cursor8')


@dataclass(frozen=True)
class CursorTiming:
    """Path constants of the cursor release (ledger blocks)."""
    case_length: int                 # case opening -> final state, every sampled case not given its own end
    buyer_window: int = 1860         # T_response + T_claim of the evaluated data profile (D2-39 (b) 3)
    bind_window: int = None          # w_b (unsigned accounts); None: receipt-signed account, no W_e
    keeper_delay: int = 0            # kappa_r: blocks from the last condition to the cursor transaction
    open_offset: int = None          # None: the replay's prompt path (engine.case_open_block);
                                     # int: the case opens open_offset blocks after the epoch's first block

    def describe(self):
        return asdict(self)


@dataclass(frozen=True)
class Release8:
    """The cursor release of one run: path constants and the hold window H_N of the held-settlement cap
    (None: no cap)."""
    timing: CursorTiming
    h_n: int = None

    def describe(self):
        return dict(mode='cursor8', h_n=self.h_n, **self.timing.describe())


def hold_cap(capacity, refill_ppm, scale, h_n):
    """N_h = ceil(q_S + r_S H_N) in settlements, for a bucket of capacity `capacity * scale` settlements and
    refill `refill_ppm * scale` ppm per block (D2-42 (b)). None when H_N is None (no cap)."""
    if h_n is None:
        return None
    total = capacity * scale * PPM + refill_ppm * scale * h_n
    return -(-total // PPM)


def epoch_release(blocks, epochs, sampled, open_block, timing, case_end=None):
    """Release block of every sale under the cursor.

    `blocks` (ledger), `epochs` and `sampled` are per sale in any order with `epochs` non-decreasing in
    `blocks`; `open_block` is a dict epoch -> ledger block of seal and case opening; `case_end` (optional,
    per sale) overrides the final block of a sampled sale's case (-1 or a value below the opening: use
    `open + case_length`). Returns an int64 array of release blocks, one per sale, and a dict
    epoch -> (R(E), the condition that set it: 'seal', 'case', 'buyer', 'bind' or 'cursor')."""
    blocks = np.asarray(blocks, dtype=np.int64)
    epochs = np.asarray(epochs, dtype=np.int64)
    sampled = np.asarray(sampled, dtype=bool)
    n = len(blocks)
    out = np.zeros(n, dtype=np.int64)
    if n == 0:
        return out, {}
    order = np.lexsort((blocks, epochs))
    e_sorted = epochs[order]
    cut = np.flatnonzero(np.r_[True, e_sorted[1:] != e_sorted[:-1], True])
    prev = None
    detail = {}
    for a, b in zip(cut[:-1], cut[1:]):
        idx = order[a:b]
        e = int(e_sorted[a])
        o = int(open_block[e])
        terms = [('seal', o + 1), ('buyer', int(blocks[idx].max()) + timing.buyer_window + 1)]
        s_idx = idx[sampled[idx]]
        if len(s_idx):
            ends = np.full(len(s_idx), o + timing.case_length, dtype=np.int64)
            if case_end is not None:
                given = np.asarray(case_end, dtype=np.int64)[s_idx]
                ends = np.where(given >= o, given, ends)
            terms.append(('case', int(ends.max()) + 1))
        if timing.bind_window is not None:
            terms.append(('bind', (o - 1) + timing.bind_window + 1))
        why, r = max(terms, key=lambda x: x[1])
        r += timing.keeper_delay
        if prev is not None and prev > r:
            # passed in the same transaction as the epoch before it (D2-39 (a): one call, several epochs)
            why, r = 'cursor', prev
        detail[e] = (r, why)
        out[idx] = r
        prev = r
    return out, detail


def admit_cursor(blocks, epochs, sampled, open_block, timing, *, capacity, refill_ppm, scale, registered_block,
                 local_blocks, n_cap):
    """Bucket admission (bucket.Bucket arithmetic, as engine.admit) with the held-settlement cap.

    The sales are in submission order (`blocks` ledger, `local_blocks` the same in local numbering for the
    bucket). Returns (accepted mask, rejected-by-the-cap mask). With `n_cap` None this is engine.admit.
    The held count at block t is the number of accepted sales with release > t; the sales of the epoch being
    filled are held (their release is after the epoch), earlier epochs are released by `epoch_release` on
    the sales accepted so far, which is final once the epoch is over."""
    blocks = np.asarray(blocks, dtype=np.int64)
    epochs = np.asarray(epochs, dtype=np.int64)
    sampled = np.asarray(sampled, dtype=bool)
    n = len(blocks)
    acc = np.zeros(n, dtype=bool)
    capped = np.zeros(n, dtype=bool)
    cap = capacity * scale * PPM
    rate = refill_ppm * scale
    balance, updated = cap, registered_block
    pending = []                  # min-heap of release blocks of accepted sales of closed epochs
    cur_epoch, cur = None, []     # the epoch being filled and the indices accepted in it
    prev_release = None
    for i in range(n):
        b, e, t_local = int(blocks[i]), int(epochs[i]), int(local_blocks[i])
        if e != cur_epoch:
            if cur:
                r, _ = epoch_release(blocks[cur], epochs[cur], sampled[cur], open_block, timing)
                rr = int(r[0])
                if prev_release is not None and prev_release > rr:
                    rr = prev_release
                prev_release = rr
                for _ in cur:
                    heapq.heappush(pending, rr)
            cur_epoch, cur = e, []
        level = balance + (t_local - updated) * rate
        if level > cap:
            level = cap
        if level < PPM:
            continue
        if n_cap is not None:
            while pending and pending[0] <= b:
                heapq.heappop(pending)
            if len(pending) + len(cur) >= n_cap:
                capped[i] = True
                continue
        balance, updated = level - PPM, t_local
        acc[i] = True
        cur.append(i)
    return acc, capped


def hold_summary(blocks, values, release, end):
    """Hold-length statistics of one address: count-weighted quantiles (p50, p90, p99, max) and means (by count
    and by value) over the sales released by `end`, and the count and value of sales still held at `end`."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    release = np.asarray(release, dtype=np.int64)
    done = release <= end
    h = (release - blocks)[done]
    v = values[done]
    out = dict(hold_released_count=int(done.sum()), hold_open_count=int((~done).sum()),
               hold_open_value=int(values[~done].sum()))
    if len(h):
        q = np.quantile(h, [0.5, 0.9, 0.99], method='inverted_cdf')
        out.update(hold_mean=float(h.mean()), hold_value_mean=float((h * v).sum() / v.sum()) if v.sum() else None,
                   hold_p50=int(q[0]), hold_p90=int(q[1]), hold_p99=int(q[2]), hold_max=int(h.max()))
    else:
        out.update(hold_mean=None, hold_value_mean=None, hold_p50=None, hold_p90=None, hold_p99=None, hold_max=None)
    return out


def hold_histogram(blocks, release, end, edges):
    """Counts of released sales by hold length over `edges` (blocks; the last bin is open on the right)."""
    blocks = np.asarray(blocks, dtype=np.int64)
    release = np.asarray(release, dtype=np.int64)
    h = (release - blocks)[release <= end]
    idx = np.searchsorted(np.asarray(edges), h, side='right') - 1
    idx = np.clip(idx, 0, len(edges) - 1)
    return np.bincount(idx, minlength=len(edges)).astype(np.int64)


HOLD_EDGES = (0, 1000, 2000, 2600, 3000, 4000, 5000, 5600, 7000, 9000, 12000, 15000, 20000, 25000, 31073)


def h_ledger_release(blocks, values, release, points):
    """engine.h_ledger with a release block per sale: +value at the settlement, -value at the release; the
    events of a block are applied before the reading at that block."""
    ev_b = np.r_[np.asarray(blocks, dtype=np.int64), np.asarray(release, dtype=np.int64)]
    ev_v = np.r_[np.asarray(values, dtype=np.int64), -np.asarray(values, dtype=np.int64)]
    order = np.argsort(ev_b, kind='stable')
    ev_b, cum = ev_b[order], np.cumsum(ev_v[order])
    idx = np.searchsorted(ev_b, np.asarray(points, dtype=np.int64), side='right')
    cum = np.r_[0, cum]
    return cum[idx].tolist()


def h_list_release(blocks, values, release, points):
    """H at each point from two sorted lists (settlements and releases): value settled at or before t minus value
    released at or before t. The same quantity as h_ledger_release by another route (a consistency check)."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    release = np.asarray(release, dtype=np.int64)
    pts = np.asarray(points, dtype=np.int64)
    ob, orl = np.argsort(blocks, kind='stable'), np.argsort(release, kind='stable')
    pb = np.r_[0, np.cumsum(values[ob])]
    pr = np.r_[0, np.cumsum(values[orl])]
    return (pb[np.searchsorted(blocks[ob], pts, side='right')] - pr[np.searchsorted(release[orl], pts, side='right')]).tolist()
