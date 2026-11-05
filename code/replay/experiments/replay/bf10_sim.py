"""Brute-force simulator of the edition-10 release (registration R10), written apart from release10.py for its tests.

Standard library only; imports nothing from the replayer. It steps block by block: a cursor per address passes its
next epoch with sales in block t when every condition, met by a transaction in some block x, holds (x < t - keeper):
the epoch is anchored (x = A) and its sample value is on chain (x = M); every sampled sale's proof landed (x = P, the
deadline M + T_p, or M + proof_delay); every sale not accepted is past its dispute window (x = s + T_c) and, if
unsigned, past W_e (x = M + w_b). Several epochs may pass in one block. A sale the buyer accepted is paid in the
anchor transaction (block A). Held money at block t is the value of the sales with s <= t < paid.

Also a reader of a settlement list csv that redoes the replay's sampling (supplementary registration R3 of R8: epoch
e = (block - first block) // 300, beacon SHA-256("fairbind/R20/beacon|<seed>|<e>") hex, digest
SHA-256("fairbind/R20/sample|<beacon>|<address>|<e>|<row>") big endian, rate ppm = min(10^6, ceil(v 10^6 / V))) and
the buyer flags (SHA-256("fairbind/R10/sign|<address>|<row>"), SHA-256("fairbind/R10/accept|<address>|<row>")).
"""
import csv
import hashlib

PPM = 10 ** 6


def deadlines(epoch, p):
    """(A, M, P_honest) of an epoch from the registered formulas."""
    first = p['origin'] + p['epoch_blocks'] * epoch
    a = first + p['epoch_blocks'] - 1 + p['d_A']
    m = a + p['tau_V'] + 1 + p['T_V']
    proof = m + (p['T_p'] if p.get('proof_delay') is None else p['proof_delay'])
    return a, m, proof


def simulate(sales, p, horizon=None):
    """sales: list of dicts with block, value, sampled, accepted, signed (accepted implies signed).
    Returns (paid block per sale, held money per block as a dict block -> value for every block in the span)."""
    n = len(sales)
    paid = [None] * n
    by_epoch = {}
    for i, s in enumerate(sales):
        by_epoch.setdefault((s['block'] - p['origin']) // p['epoch_blocks'], []).append(i)
    epochs = sorted(by_epoch)
    conds = {}
    for e in epochs:
        a, m, proof = deadlines(e, p)
        xs = [a, m]
        for i in by_epoch[e]:
            s = sales[i]
            if s['sampled']:
                xs.append(proof)
            if not s['accepted']:
                xs.append(s['block'] + p['T_c'])
                if not s['signed']:
                    xs.append(m + p['w_b'])
            else:
                paid[i] = a
        conds[e] = xs
    lo = min(s['block'] for s in sales)
    hi = horizon if horizon is not None else max(max(c) for c in conds.values()) + p.get('keeper', 0) + 2
    k = 0
    t = lo
    while k < len(epochs) and t <= hi:
        u = t - p.get('keeper', 0)
        while k < len(epochs) and all(x < u for x in conds[epochs[k]]):
            for i in by_epoch[epochs[k]]:
                if not sales[i]['accepted']:
                    paid[i] = t
            k += 1
        t += 1
    held = {}
    level = 0
    add, sub = {}, {}
    for i, s in enumerate(sales):
        add[s['block']] = add.get(s['block'], 0) + s['value']
        if paid[i] is not None:
            sub[paid[i]] = sub.get(paid[i], 0) + s['value']
    for b in range(lo, hi + 1):
        level += add.get(b, 0) - sub.get(b, 0)
        held[b] = level
    return paid, held


def _digest(text):
    return int.from_bytes(hashlib.sha256(text.encode()).digest(), 'big')


def _thr(ppm, rounding):
    if rounding == 'ceil':
        return -(-ppm * (1 << 256) // PPM)
    return (1 << 256) * ppm // PPM


def read_list(path, vmax, seed, rounding, accept_ppm=0, unsigned_ppm=0, address_col='recipient', block_col='block',
              value_col='value', over_cap=False):
    """{address: [sale dicts]} of the in-cap rows (all rows with over_cap), with block, value, row, epoch, sampled,
    signed, accepted; plus (first block, last block)."""
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    first = min(int(r[block_col]) for r in rows)
    last = max(int(r[block_col]) for r in rows)
    beacons = {}
    out = {}
    tu = None if unsigned_ppm >= PPM else (-(-unsigned_ppm * (1 << 256) // PPM))
    ta = None if accept_ppm >= PPM else (-(-accept_ppm * (1 << 256) // PPM))
    for i, r in enumerate(rows):
        v = int(r[value_col])
        if v > vmax and not over_cap:
            continue
        a = r[address_col].lower()
        b = int(r[block_col])
        e = (b - first) // 300
        ppm = min(PPM, -(-v * PPM // vmax))
        if ppm >= PPM:
            smp = True
        elif ppm == 0:
            smp = False
        else:
            if e not in beacons:
                beacons[e] = hashlib.sha256(f'fairbind/R20/beacon|{seed}|{e}'.encode()).hexdigest()
            smp = _digest(f'fairbind/R20/sample|{beacons[e]}|{a}|{e}|{i}') < _thr(ppm, rounding)
        signed = not (tu is None or (tu > 0 and _digest(f'fairbind/R10/sign|{a}|{i}') < tu))
        accepted = signed and (ta is None or (ta > 0 and _digest(f'fairbind/R10/accept|{a}|{i}') < ta))
        out.setdefault(a, []).append(dict(block=b, value=v, row=i, epoch=e, sampled=smp, signed=signed,
                                          accepted=accepted))
    return out, (first, last)


def address_stats(sales, p, first, last, hold_offset, hour_blocks):
    """The release-dependent columns of addresses_observed.csv for one address, from simulate()."""
    paid, held = simulate(sales, p, horizon=max(last, max(s['block'] for s in sales)) + 20_000)
    points = list(range(first + hold_offset, last + 1, hour_blocks))
    hs = [held.get(t, 0) if t >= min(s['block'] for s in sales) else 0 for t in points]
    done = [(paid[i] - s['block'], s['value']) for i, s in enumerate(sales) if paid[i] is not None and paid[i] <= last]
    open_ = [s['value'] for i, s in enumerate(sales) if paid[i] is None or paid[i] > last]
    out = dict(H_time_average=sum(hs) / len(hs) if hs else None, hold_released_count=len(done),
               hold_open_count=len(open_), hold_open_value=sum(open_), sample_count=sum(s['sampled'] for s in sales),
               buyer_accepted_count=sum(s['accepted'] for s in sales),
               unsigned_count=sum(not s['signed'] for s in sales))
    if done:
        h = sorted(x for x, _ in done)
        n = len(h)
        k = -(-9 * n // 10)                       # inverted cdf at 0.9: the ceil(0.9 n)-th smallest
        out.update(hold_mean=sum(h) / n, hold_p90=h[max(k, 1) - 1], hold_max=h[-1],
                   hold_value_mean=sum(x * v for x, v in done) / sum(v for _, v in done) if sum(v for _, v in done)
                   else None)
    else:
        out.update(hold_mean=None, hold_p90=None, hold_max=None, hold_value_mean=None)
    return out, paid
