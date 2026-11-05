"""Settlement replay engine: seller-side admission, sampling, held funds and injection.

One replay takes the recorded settlements of the replayed addresses, one condition
(profile, scale rule, burst value q) and one seed, and computes per address:

- admission through the bond bucket (bucket.Bucket, exact contract arithmetic);
- the entries sampled by the sealed randomness of their epoch, and their case opening
  blocks on the prompt path (see `case_open_block`);
- held funds H(t), sampled every hour, rebuilt twice: from a settle/release event
  ledger and from the accepted list (`h_list`), so that the two can be compared;
- epochs with a settlement, sealed epochs, fixed judgment windows below minJudgedCount;
- the injection model of injection.py (wrongful confirmed failures drawn per sampled case,
  each entry lost at most once), vectorised over entries, with `draws` draws per setting.

Everything that depends on the seed is derived with SHA-256 from the seed, so a replay is a
pure function of its inputs.
"""
import bisect
import hashlib
import math
import random
from fractions import Fraction

import numpy as np

import design2
import release8
import release10
from bucket import Bucket, PPM

SAMPLE_DOMAIN = 'fairbind/R20/sample'
BEACON_DOMAIN = 'fairbind/R20/beacon'
ORDER_DOMAIN = 'fairbind/seed/order'
INJECT_DOMAIN = 'fairbind/R20/inject'
HOUR_BLOCKS = 1800


def digest_int(text, nbytes=32):
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:nbytes], 'big')


def probability_threshold(ppm):
    """FairBindCore._probabilityThreshold over 2^256."""
    if ppm == 0:
        return 0
    if ppm == PPM:
        return 2**256 - 1
    top = 2**256 - 1
    return (top // PPM) * ppm + ((top % PPM + 1) * ppm) // PPM


class ReplayData:
    """Settlements of the replayed addresses, per address, in file order.

    blocks, values, row (index in the file), pos (position in its block), plus the size of
    every block holding more than one settlement of the list, and the list totals."""

    def __init__(self):
        self.per = {}
        self.block_size = {}
        self.total_rows = 0
        self.total_value = 0
        self.first_block = None
        self.last_block = None
        self.first_seconds = None
        self.cap_rows = None
        self.cap_value = None


def load(path, columns, addresses, iter_rows, utc_seconds, block_range=None, cap=None, norm=str.lower):
    """Streams a settlement list once and keeps the rows of `addresses`.

    block_range=(lo, hi) keeps only rows with lo <= block <= hi (a fold); the list totals
    are taken over the same range. `cap` (design 2) also counts the list rows with value at most cap.
    `norm` maps a recipient field to the key of `addresses` (lower case for hex addresses; the identity for
    base58 addresses, which are case sensitive)."""
    wanted = set(addresses)
    data = ReplayData()
    if cap is not None:
        data.cap_rows = data.cap_value = 0
    tmp = {a: ([], [], [], []) for a in addresses}
    current, pos = None, 0
    for i, row in enumerate(iter_rows(path, columns)):
        block = int(row[0])
        if block_range is not None and not (block_range[0] <= block <= block_range[1]):
            continue
        if block != current:
            if current is not None and pos > 1:
                data.block_size[current] = pos
            current, pos = block, 0
        if data.first_block is None:
            data.first_block = block
            data.first_seconds = utc_seconds(row[1])
        data.last_block = block
        value = int(row[7])
        data.total_rows += 1
        data.total_value += value
        if cap is not None and value <= cap:
            data.cap_rows += 1
            data.cap_value += value
        rec = norm(row[5])
        if rec in wanted:
            t = tmp[rec]
            t[0].append(block)
            t[1].append(value)
            t[2].append(i)
            t[3].append(pos)
        pos += 1
    if current is not None and pos > 1:
        data.block_size[current] = pos
    for a, (b, v, r, p) in tmp.items():
        data.per[a] = (np.array(b, dtype=np.int64), np.array(v, dtype=np.int64),
                       np.array(r, dtype=np.int64), np.array(p, dtype=np.int64))
    return data


# ---------------------------------------------------------------- ordering and admission

_perm_cache = {}


def block_rank(seed, block, size):
    """Submission rank of each position of a block: a permutation drawn from
    SHA-256("fairbind/seed/order|seed|block") (controller SEED_EFFECTS, intra_block_order)."""
    key = (seed, block)
    ranks = _perm_cache.get(key)
    if ranks is None:
        order = list(range(size))
        random.Random(digest_int(f'{ORDER_DOMAIN}|{seed}|{block}')).shuffle(order)
        ranks = [0] * size
        for r, p in enumerate(order):
            ranks[p] = r
        if len(_perm_cache) > 200_000:
            _perm_cache.clear()
        _perm_cache[key] = ranks
    return ranks


def submission_order(blocks, pos, seed, block_size):
    """Indices of one address's rows in submission order: by block, and within a block by the
    seeded permutation of the whole block."""
    n = len(blocks)
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    rank = pos.copy()
    dup = np.flatnonzero(np.r_[False, blocks[1:] == blocks[:-1]] | np.r_[blocks[:-1] == blocks[1:], False])
    for i in dup:
        b = int(blocks[i])
        rank[i] = block_rank(seed, b, block_size[b])[int(pos[i])]
    return np.lexsort((rank, blocks))


def admit(local_blocks, capacity, refill_ppm, scale, registered_block):
    """Bucket admission of settlements at `local_blocks` (in submission order)."""
    bucket = Bucket(capacity, refill_ppm, scale, registered_block)
    cap = bucket.cap_ppm
    rate = refill_ppm * scale
    balance, updated = bucket.balance_ppm, bucket.updated_block
    out = np.zeros(len(local_blocks), dtype=bool)
    for i, b in enumerate(local_blocks.tolist()):
        level = balance + (b - updated) * rate
        if level > cap:
            level = cap
        if level >= PPM:
            balance, updated = level - PPM, b
            out[i] = True
    return out


def admit_segments(local_blocks, capacity, refill_ppm, segments, origin):
    """Admission with a multiplier that changes at given blocks: `segments` is a list of
    (first local block, scale), or of (first local block, scale, capacity, refill ppm) when the bucket
    itself differs between the parts (a sales cap that changes); every part runs a bucket that starts
    full at its first block."""
    out = np.zeros(len(local_blocks), dtype=bool)
    bounds = [s[0] for s in segments] + [None]
    for seg, end in zip(segments, bounds[1:]):
        start, scale = seg[0], seg[1]
        cap_i, refill_i = (seg[2], seg[3]) if len(seg) == 4 else (capacity, refill_ppm)
        lo = np.searchsorted(local_blocks, start, side='left')
        hi = len(local_blocks) if end is None else np.searchsorted(local_blocks, end, side='left')
        out[lo:hi] = admit(local_blocks[lo:hi], cap_i, refill_i, scale, start if start > origin else origin)
    return out


# ---------------------------------------------------------------- epochs and cases

def epoch_of(local_block, p):
    return (local_block - p['epochOrigin']) // p['epochBlocks']


def case_open_block(epoch, p):
    """Prompt path of an honest seller and keeper: the anchor lands in its window, the beacon
    block is anchorBase + anchorBlocks + 1 + beaconDelayBlocks (fixed by the anchor deadline,
    FairBindSampling.anchor), seal and openSample are called in the first block after it."""
    base = p['epochOrigin'] + (epoch + 2) * p['epochBlocks'] - 1
    random_block = base + p['deadlineConfig']['anchorBlocks'] + 1 + p['beaconDelayBlocks']
    return random_block + 1


def sampled(seller, epochs, rows, seed, ppm, rounding='contract'):
    """Sample draw of each accepted row. `ppm` is one rate for every row (design 1) or an array with
    the rate of each row (design 2, D2-3: the threshold follows the row's value; a row at PPM is
    sampled without a comparison). The hash input is the same in both, so a row has the same
    random number whatever its rate."""
    beacons = {}
    out = np.zeros(len(rows), dtype=bool)
    if np.ndim(ppm) == 0:
        threshold = probability_threshold(ppm)
        per_row = None
    else:
        per_row = np.asarray(ppm).tolist()
        thresholds = {}
    for i, (e, r) in enumerate(zip(epochs.tolist(), rows.tolist())):
        if per_row is not None:
            rate = per_row[i]
            if rate >= PPM:
                out[i] = True
                continue
            threshold = thresholds.get(rate)
            if threshold is None:
                threshold = thresholds[rate] = design2.threshold_of(rate, rounding)
        beacon = beacons.get(e)
        if beacon is None:
            beacon = beacons[e] = hashlib.sha256(f'{BEACON_DOMAIN}|{seed}|{e}'.encode()).hexdigest()
        out[i] = digest_int(f'{SAMPLE_DOMAIN}|{beacon}|{seller}|{e}|{r}') < threshold
    return out


def release8_open_blocks(epochs, p, timing, origin_ledger, local_origin):
    """Ledger block of the seal and case opening of each epoch for the cursor release: the prompt path
    (case_open_block) or, with timing.open_offset, that many blocks after the epoch's first block."""
    out = {}
    for e in np.asarray(epochs).tolist():
        if timing.open_offset is None:
            o = case_open_block(int(e), p)
        else:
            o = p['epochOrigin'] + int(e) * p['epochBlocks'] + timing.open_offset
        out[int(e)] = o - local_origin + origin_ledger
    return out


# ---------------------------------------------------------------- held funds

def h_ledger(blocks, values, hold, points):
    """H at each point from an event ledger: +value at the settle block, -value at the
    release block (settled + hold, a keeper releasing at releaseBlock); events at a block are
    applied before the reading at that block."""
    events = sorted([(b, v) for b, v in zip(blocks.tolist(), values.tolist())]
                    + [(b + hold, -v) for b, v in zip(blocks.tolist(), values.tolist())])
    out, level, j = [], 0, 0
    for t in points:
        while j < len(events) and events[j][0] <= t:
            level += events[j][1]
            j += 1
        out.append(level)
    return out


def held_blocks(blocks, values, release, lo, hi):
    """Sum over the sales of value x (number of blocks t in [lo, hi] with settled <= t < release): the numerator of
    the continuous time average of the held money over [lo, hi] (registration R11; R10d M1 called it the continuous
    average). A sale not released by `hi` is held to `hi`. Exact integer arithmetic (chunked sums of int64 products)."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    release = np.asarray(release, dtype=np.int64)
    if len(blocks) == 0 or hi < lo:
        return 0
    d = np.maximum(np.minimum(release, hi + 1) - np.maximum(blocks, lo), 0)
    prod = values * d
    n = len(prod)
    return sum(int(x) for x in np.add.reduceat(prod, np.arange(0, n, 4096)))


def h_list(blocks, values, hold, points):
    """H_list(t): value of accepted entries settled after t - hold and at or before t."""
    prefix = np.r_[0, np.cumsum(values)]
    pts = np.asarray(points, dtype=np.int64)
    hi = np.searchsorted(blocks, pts, side='right')
    lo = np.searchsorted(blocks, pts - hold, side='right')
    return (prefix[hi] - prefix[lo]).tolist()


# ---------------------------------------------------------------- one address, one condition

def replay_address(seller, arrays, *, seed, p, capacity, scale, origin_ledger, local_origin,
                   end_ledger, block_size, window_blocks, first_seconds, observed=True,
                   cap=None, sample_tau=None, rounding='contract', segments=None, refill_ppm=None,
                   align='first-block', hour_blocks=HOUR_BLOCKS, block_seconds=2, release=None, unlimited=False):
    """Admission and observed quantities of one address. Returns (row, accepted arrays).

    `unlimited` (registration R11, sales cap mode 'none'): no bucket; every settlement that passes the value cap (or
    every settlement, with the edition-10 over-cap acceptance) is admitted. The rule editions 10 candidate v0.6 and
    later have no count limit on settlements; the bucket of edition 7 stays as the labelled legacy variant.

    Design 2 (all None in design 1): `cap` rejects a settlement with value above it before the
    bucket (D2-1) and counts it apart from the rate rejections; `sample_tau` gives each accepted
    row the sampling rate s_ppm(v) of its value (D2-2, D2-3); `segments` lists
    (first ledger block, multiplier) or (first ledger block, multiplier, capacity, refill ppm) when the
    bucket changes during the window (two-fold source); `refill_ppm` replaces the profile's refill (a
    sales cap below the main cap has its own refill); `align` places the fixed judgment windows on the
    first block of the list ('first-block') or on multiples of their length ('absolute', D2-9);
    `hour_blocks` and `block_seconds` are the chain's (blocks per hour, seconds per block).

    `release` (None: edition 7, a sale is released at settled + deferBlocks) is a release8.Release8: the sale is
    released when the address's release cursor passes its epoch (D2-39), and with `release.h_n` set a
    settlement is rejected while N_h settlements are held (D2-42). The held funds, the hold lengths and the
    array `release` of the accepted sales follow the cursor; sampling, case openings and windows do not change."""
    if release is not None and segments is not None:
        raise ValueError('the cursor release takes one bucket per address (no segments)')
    # Edition 10 (release10.Release10): bucket admission of edition 7, release by release10.epoch_release.
    r10 = isinstance(release, release10.Release10)
    if r10 and release.timing.accept_over_cap:
        cap = None          # tiers 0 and 1 accept a sale above V and sample it with probability 1 (s_ppm caps at PPM)
    blocks, values, rows, pos = arrays
    order = submission_order(blocks, pos, seed, block_size)
    blocks, values, rows = blocks[order], values[order], rows[order]
    local = blocks - origin_ledger + local_origin
    ok = np.ones(len(blocks), dtype=bool) if cap is None else values <= cap
    refill = p['refillPpmPerBlock'] if refill_ppm is None else refill_ppm
    capped = None
    if unlimited and (release is None or not r10):
        raise ValueError('admission without a bucket (sales cap none) is defined for the edition-10 release only')
    if release is not None and not r10:
        # Sampling depends on the row and its epoch only, so it is drawn for every in-cap row before admission
        # (the held-settlement cap needs the case of each sale); the accepted rows get the same draws as below.
        ok_local, ok_rows, ok_values = local[ok], rows[ok], values[ok]
        ok_epochs = epoch_of(ok_local, p)
        ok_smp = sampled(seller, ok_epochs, ok_rows, seed,
                         p['samplePpm'] if sample_tau is None else design2.s_ppm(ok_values, sample_tau), rounding)
        open_of = release8_open_blocks(np.unique(ok_epochs), p, release.timing, origin_ledger, local_origin)
        n_cap = release8.hold_cap(capacity, refill, scale, release.h_n)
        passed, capped_ok = release8.admit_cursor(
            blocks[ok], ok_epochs, ok_smp, open_of, release.timing, capacity=capacity, refill_ppm=refill,
            scale=scale, registered_block=local_origin, local_blocks=ok_local, n_cap=n_cap)
        capped = np.zeros(len(blocks), dtype=bool)
        capped[ok] = capped_ok
    elif unlimited:
        passed = np.ones(int(ok.sum()), dtype=bool)
    elif segments is None:
        passed = admit(local[ok], capacity, refill, scale, local_origin)
    else:
        seg_local = [(seg[0] - origin_ledger + local_origin,) + tuple(seg[1:]) for seg in segments]
        passed = admit_segments(local[ok], capacity, refill, seg_local, local_origin)
    if cap is None:
        acc = passed
    else:
        acc = np.zeros(len(blocks), dtype=bool)
        acc[ok] = passed
    a_blocks, a_values, a_rows = blocks[acc], values[acc], rows[acc]
    attempted = len(blocks)
    accepted = int(acc.sum())
    cap_rejected = attempted - int(ok.sum())
    rate_rejected = attempted - accepted - cap_rejected - (0 if capped is None else int(capped.sum()))
    out = dict(address=seller, scale=scale, q=capacity, bucket_capacity=capacity * scale,
               attempted_count=attempted, attempted_value=int(values.sum()),
               accepted_count=accepted, accepted_value=int(a_values.sum()),
               rejected_count=rate_rejected,
               rejection_rate=rate_rejected / attempted if attempted else None)
    if cap is not None:
        out.update(cap_rejected_count=cap_rejected, cap_rejected_value=int(values[~ok].sum()),
                   rate_rejected_count=rate_rejected,
                   rate_rejected_value=int(values[ok & ~acc].sum()),
                   scale_segments=None if segments is None else [list(s) for s in segments])
    if r10:
        out.update(rate_rejected_count=rate_rejected, admission='unlimited' if unlimited else 'bucket')
        if cap is None:
            # Over-cap acceptance: nothing is rejected by the value cap; the columns are written as 0, not empty, so
            # that the design-2 group sums are formed as in a run with the cap.
            out.update(cap_rejected_count=0, cap_rejected_value=0, rate_rejected_value=int(values[~acc].sum()),
                       scale_segments=None)
    elif release is not None:
        out.update(rate_rejected_count=rate_rejected, hold_cap_N_h=n_cap,
                   hold_cap_rejected_count=int(capped.sum()), hold_cap_rejected_value=int(values[capped].sum()))
    if not observed:
        return out, None
    hold = p['deferBlocks']
    a_local = a_blocks - origin_ledger + local_origin
    epochs = epoch_of(a_local, p)
    if release is not None and not r10:
        smp = ok_smp[passed]
        s_prob = None if sample_tau is None else design2.s_ppm(a_values, sample_tau) / PPM
    elif sample_tau is None:
        smp = sampled(seller, epochs, a_rows, seed, p['samplePpm'])
        s_prob = None
    else:
        ppms = design2.s_ppm(a_values, sample_tau)
        smp = sampled(seller, epochs, a_rows, seed, ppms, rounding)
        s_prob = ppms / PPM
    s_epochs = epochs[smp]
    open_local = np.array([case_open_block(int(e), p) for e in s_epochs.tolist()], dtype=np.int64)
    open_ledger = open_local - local_origin + origin_ledger
    uniq = np.unique(epochs)
    end_local = end_ledger - origin_ledger + local_origin
    sealed = sum(1 for e in uniq.tolist() if case_open_block(e, p) - 1 <= end_local)
    # Hourly readings from T_hold after the start to the end of the replay.
    points = list(range(origin_ledger + hold, end_ledger + 1, hour_blocks))
    signed10 = accepted10 = None
    if release is None:
        rel = None
        h_led = h_ledger(a_blocks, a_values, hold, points)
        h_lst = h_list(np.sort(a_blocks), a_values[np.argsort(a_blocks, kind='stable')], hold, points)
    elif r10:
        signed10, accepted10 = release10.buyer_flags(seller, a_rows, release.timing)
        rel, _ = release10.epoch_release(
            a_blocks, epochs, smp, accepted10, signed10,
            lambda e: p['epochOrigin'] + e * p['epochBlocks'] - local_origin + origin_ledger, p['epochBlocks'],
            release.timing)
        h_led = release8.h_ledger_release(a_blocks, a_values, rel, points)
        h_lst = release8.h_list_release(a_blocks, a_values, rel, points)
    else:
        rel, _ = release8.epoch_release(a_blocks, epochs, smp, open_of, release.timing)
        h_led = release8.h_ledger_release(a_blocks, a_values, rel, points)
        h_lst = release8.h_list_release(a_blocks, a_values, rel, points)
    h_mean = sum(h_led) / len(h_led) if h_led else None
    h_lst_mean = sum(h_lst) / len(h_lst) if h_lst else None
    # Clock hours of accepted settlements (two-second blocks from the first row's time).
    bt = Fraction(block_seconds)
    hours = (first_seconds * bt.denominator + bt.numerator * (a_blocks - origin_ledger)) // (3600 * bt.denominator)
    peak = int(np.bincount(hours - hours.min()).max()) if accepted else 0
    rate_acc = accepted / window_blocks
    vbar = int(a_values.sum()) / accepted if accepted else None
    # Fixed judgment windows from the start; a sampled case counts at its opening block.
    iw = p['inconclusiveWindowBlocks']
    edges = design2.window_edges(origin_ledger, end_ledger, iw, align)
    n_windows = len(edges) - 1
    judged = np.histogram(open_ledger, bins=edges)[0] if n_windows else np.zeros(0)
    settled = np.histogram(a_blocks, bins=edges)[0] if n_windows else np.zeros(0)
    active = settled > 0
    below = active & (judged < p['minJudgedCount'])
    hold_stats = None
    if rel is not None:
        hold_stats = release8.hold_summary(a_blocks, a_values, rel, end_ledger)
        h_form = rate_acc * (vbar or 0) * (hold_stats['hold_value_mean'] or 0)
    else:
        h_form = rate_acc * (vbar or 0) * hold
    out.update(
        rate_acc_per_hour=rate_acc * hour_blocks, peak_hour_accepted=peak, mean_value=vbar,
        H_formula=h_form, H_time_average=h_mean, H_max=max(h_led) if h_led else None,
        H_list_time_average=h_lst_mean,
        H_ledger_list_max_abs_diff=max((abs(x - y) for x, y in zip(h_led, h_lst)), default=0),
        sample_count=int(smp.sum()), epochs_with_settlement=int(len(uniq)), epochs_sealed=int(sealed),
        judgment_windows=int(active.sum()), judgment_windows_below=int(below.sum()),
        judgment_window_settlements=int(settled[active].sum()),
        judgment_window_settlements_below=int(settled[below].sum()))
    # Sampled cases by opening block, each with the settlement block of its entry (R20-C2 assigns a
    # drawn failure to the failure window of that settlement, design 9.6).
    if s_prob is not None:
        out.update(expected_samples=float(s_prob.sum()), sample_variance=float((s_prob * (1 - s_prob)).sum()),
                   s_bar=float(s_prob.mean()) if accepted else None)
    case_order = np.argsort(open_ledger, kind='stable')
    arrays_out = dict(blocks=np.sort(a_blocks), values=a_values[np.argsort(a_blocks, kind='stable')],
                      cases=open_ledger[case_order], case_settled=a_blocks[smp][case_order],
                      h=np.asarray(h_led, dtype=np.int64), windows_settled=settled)
    if rel is not None:
        out.update(hold_stats)
        out['hold_histogram'] = release8.hold_histogram(a_blocks, rel, end_ledger, release8.HOLD_EDGES)
        out['revenue_per_hold'] = (None if hold_stats['hold_value_mean'] is None
                                   else int(a_values.sum()) / window_blocks * hold_stats['hold_value_mean'])
        by_block = np.argsort(a_blocks, kind='stable')
        arrays_out['release'] = rel[by_block]
        arrays_out['sampled'] = smp[by_block]
        arrays_out['epochs'] = epochs[by_block]
    if r10:
        over = a_values > sample_tau if sample_tau is not None else np.zeros(len(a_values), dtype=bool)
        # Continuous time average of the held money (R11): over the whole window [first block, end] and over the
        # span of the hourly readings [first block + hold, end]; the numerator is exact.
        n_full = held_blocks(a_blocks, a_values, rel, origin_ledger, end_ledger)
        n_hold = held_blocks(a_blocks, a_values, rel, origin_ledger + hold, end_ledger)
        span_full, span_hold = end_ledger - origin_ledger + 1, end_ledger - (origin_ledger + hold) + 1
        out.update(buyer_accepted_count=int(accepted10.sum()), buyer_accepted_value=int(a_values[accepted10].sum()),
                   unsigned_count=int((~signed10).sum()), unsigned_value=int(a_values[~signed10].sum()),
                   sampled_accepted_count=int((smp & accepted10).sum()),
                   over_cap_accepted_count=int(over.sum()), over_cap_accepted_value=int(a_values[over].sum()),
                   H_cont_sum_blocks=n_full, H_cont_average=n_full / span_full,
                   H_cont_average_from_hold=(n_hold / span_hold) if span_hold > 0 else None,
                   has_revenue=int(a_values.sum()) > 0)
        by_block = np.argsort(a_blocks, kind='stable')
        arrays_out['accepted'] = accepted10[by_block]
        arrays_out['signed'] = signed10[by_block]
        arrays_out['rows'] = a_rows[by_block]
    if s_prob is not None:
        arrays_out['s_prob'] = s_prob[np.argsort(a_blocks, kind='stable')]
    return out, arrays_out


# ---------------------------------------------------------------- injection

def union_length(starts, length, lo, hi):
    """Blocks of [lo, hi] covered by the union of [s, s + length) over sorted starts (every
    interval has the same length, so each one is cut only by the next start)."""
    if len(starts) == 0 or length <= 0:
        return 0
    s = np.minimum(np.maximum(starts, lo), hi + 1)
    e = np.maximum(np.minimum(starts + length, hi + 1), s)
    nxt = np.empty_like(s)
    nxt[:-1] = s[1:]
    nxt[-1] = hi + 1
    return int((np.minimum(e, nxt) - s).sum())


def bin_uniform(x, edges, weights=None):
    """np.histogram over equal-width integer bins [e_j, e_j+1), without its overhead."""
    n = len(edges) - 1
    if n <= 0:
        return np.zeros(0)
    width = int(edges[1] - edges[0])
    idx = (np.asarray(x) - int(edges[0])) // width
    ok = (idx >= 0) & (idx < n)
    if weights is None:
        return np.bincount(idx[ok], minlength=n)
    return np.bincount(idx[ok], weights=np.asarray(weights)[ok], minlength=n)


def draw_failures(cases, w, delay, end, rng):
    """Confirmation blocks of the wrongful confirmed failures of one draw: each sampled case
    fails with probability w and is confirmed at its opening block plus `delay`. Failures
    confirmed after the last block of the replay are dropped."""
    return draw_failures_detail(cases, None, w, delay, end, rng)[0]


def draw_failures_detail(cases, case_settled, w, delay, end, rng):
    """draw_failures, also returning the settlement blocks of every drawn case (before the
    failures confirmed after the last block are dropped), with the same random numbers."""
    if len(cases) == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    hit = rng.random(len(cases)) < w
    f = np.sort(cases[hit] + delay)
    settled = case_settled[hit] if case_settled is not None else np.zeros(0, dtype=np.int64)
    return f[f <= end], settled


def no_failure_result(blocks, values, fw_edges):
    total = int(values.sum())
    nfw = len(fw_edges) - 1
    return dict(failures=0, principal=0, penalty=0, revenue=total, lost_sales=0, suspended_blocks=0,
                claim_open_blocks=0, fw_failures=np.zeros(nfw, dtype=np.int64), fw_loss=np.zeros(nfw),
                fw_revenue=bin_uniform(blocks, fw_edges, values), refunded=0, forfeited=0,
                refund_time_median=None, refund_time_max=None)


FREEZE_SCOPES = ('full', 'detected-onward')


def narrow_lost(blocks, f, f_settled, hold):
    """Entries frozen under the scope 'detected-onward', for sorted failures f and the settlement block
    f_settled[j] of the sampled sale that made failure j. Entry b is frozen by failure j when
    f_settled[j] <= b <= f[j] and b + hold > f[j]; it belongs to the first such j and is counted once.
    Returns (lost mask, index of the failure per entry, -1 where not lost).

    The first failure at or after b is `first`; the failures j >= first whose sale is not later than b are
    found along the chain j -> ns[j] (ns[j] is the next failure with a strictly earlier sale), because a
    failure skipped by the chain has a sale not earlier than that of its predecessor and so is later than b.
    A failure that releases b before it (f[j] - hold >= b) ends the search, since later ones do too."""
    F = len(f)
    f_settled = np.asarray(f_settled)
    if len(f_settled) < F:
        raise ValueError('every failure needs the settlement block of its sampled sale')
    c = f_settled[:F]
    n = len(blocks)
    lost = np.zeros(n, dtype=bool)
    li = np.full(n, -1, dtype=np.int64)
    ns = np.full(F, F, dtype=np.int64)
    stack, cl = [], c.tolist()
    for j in range(F):
        while stack and cl[stack[-1]] > cl[j]:
            ns[stack.pop()] = j
        stack.append(j)
    first = np.searchsorted(f, blocks, side='left')        # first failure at or after the entry
    active = np.flatnonzero(first < F)
    j = first[active]
    while len(active):
        b = blocks[active]
        live = b > f[j] - hold
        active, j, b = active[live], j[live], b[live]
        hit = c[j] <= b
        lost[active[hit]] = True
        li[active[hit]] = j[hit]
        active, j = active[~hit], ns[j[~hit]]
        keep = j < F
        active, j = active[keep], j[keep]
    return lost, li


def evaluate_failures(blocks, values, f, *, hold, reentry, claim_probs, share, rng, start, end, fw_edges,
                      claim_window, fw_revenue_all=None, scope='full', f_settled=None):
    """Loss of one address for one draw's failures `f` (sorted), one result per claim
    probability. The array form of injection.seller_loss: suspended from f to f + 1 + reentry,
    the new principal loss of failure i is every accepted entry settled after the previous
    failure block and at or before f_i and still unreleased at f_i (settled + hold > f_i); each
    failure deducts `share` (B / k). A claimed frozen entry is refunded at its failure block,
    an unclaimed one is forfeited at the end of the claim window.

    `scope` is the freeze scope: 'full' (default) freezes every unreleased entry settled since the previous
    freeze; 'detected-onward' (needs `f_settled`, the settlement block of the sampled sale of each failure)
    freezes only the entries settled at or after that sale.

    `f` holds the confirmed failures only: FINAL(FAIL) of a sampled case (D2-6 (a)), which stops the
    account, opens the claim period, counts toward the failure limit and deducts one share. The model has
    no FINAL(INCONCLUSIVE) above the threshold (D2-6 (b), which would stop the account and open the claim
    period without a count or a deduction) and no purchaser dispute, so a sampled purchase that ended
    delivered is one sample like any other (decision 94a) and nothing else adds to `f`."""
    F = len(f)
    if F == 0:
        r = no_failure_result(blocks, values, fw_edges)
        return [dict(r) for _ in claim_probs]
    i = np.searchsorted(f, blocks, side='left')
    if reentry > 0:
        idx = i - 1
        susp = (idx >= 0) & (blocks < f[np.maximum(idx, 0)] + 1 + reentry)
        acc = ~susp
        lost_sales = int(values[susp].sum())
    else:
        acc = None
        lost_sales = 0
    revenue = int(values.sum()) - lost_sales
    if scope == 'full':
        ic = np.minimum(i, F - 1)
        lost = (i < F) & (blocks > f[ic] - hold)
    elif scope == 'detected-onward':
        # Freeze only the held entries settled at or after the failed sampled sale; earlier ones are
        # released on their normal schedule. Everything else is as for the scope 'full'.
        if f_settled is None:
            raise ValueError("scope 'detected-onward' needs f_settled")
        lost, i = narrow_lost(blocks, f, f_settled, hold)
    else:
        raise ValueError(f'unknown freeze scope {scope}')
    if acc is not None:
        lost &= acc
    lb, lv, li = blocks[lost], values[lost], i[lost]
    per_failure = np.bincount(li, weights=lv, minlength=F)
    principal = int(lv.sum())
    if principal > revenue:
        raise AssertionError('entry counted twice: principal loss above revenue')
    fw_fail = bin_uniform(f, fw_edges)
    fw_principal = bin_uniform(f, fw_edges, per_failure)
    if acc is None:
        fw_revenue = bin_uniform(blocks, fw_edges, values) if fw_revenue_all is None else fw_revenue_all
    else:
        fw_revenue = bin_uniform(blocks[acc], fw_edges, values[acc])
    base = dict(failures=F, principal=principal, penalty=share * F, revenue=revenue, lost_sales=lost_sales,
                suspended_blocks=union_length(f, 1 + reentry, start, end),
                claim_open_blocks=union_length(f, claim_window, start, end),
                fw_failures=fw_fail, fw_loss=fw_principal + share * fw_fail, fw_revenue=fw_revenue)
    lt = f[li] - lb
    results = []
    for phi in claim_probs:
        if phi >= 1:
            claimed = None
        elif phi <= 0 or len(lb) == 0:
            claimed = np.zeros(len(lb), dtype=bool)
        else:
            claimed = rng.random(len(lb)) < phi
        times = lt if claimed is None else lt[claimed]
        refunded = principal if claimed is None else int(lv[claimed].sum())
        r = dict(base)
        r.update(refunded=refunded, forfeited=principal - refunded,
                 refund_time_median=float(np.median(times)) if len(times) else None,
                 refund_time_max=int(times.max()) if len(times) else None)
        results.append(r)
    return results


def inject_draw(blocks, values, cases, *, w, delay, hold, reentry, claim_probs, share, rng,
                start, end, fw_edges, claim_window):
    """One draw for one address and one reentry delay (draw_failures, then evaluate_failures)."""
    f = draw_failures(cases, w, delay, end, rng)
    return evaluate_failures(blocks, values, f, hold=hold, reentry=reentry, claim_probs=claim_probs, share=share,
                             rng=rng, start=start, end=end, fw_edges=fw_edges, claim_window=claim_window)


def draw_rng(seed, setting, seller, draw):
    """SHA-256("fairbind/R20/inject|replay seed|setting|seller|draw"), first 16 bytes, PCG64."""
    return np.random.Generator(np.random.PCG64(digest_int(f'{INJECT_DOMAIN}|{seed}|{setting}|{seller}|{draw}', 16)))
