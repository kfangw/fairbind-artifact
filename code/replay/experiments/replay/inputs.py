"""Settlement lists, reference aggregates, address groups and the input checks.

A settlement list is the extraction CSV with the columns of conditions.json
(`block_number, block_time_utc, tx_hash, tx_index, trace_address, recipient, payer,
value_atomic, facilitator`), sorted by block, transaction index and trace address.
Every reader here streams the file once and keeps only what it needs.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import injection as inj

HERE = Path(__file__).resolve().parent
CONDITIONS_PATH = HERE / 'conditions.json'
BLOCK_SECONDS = 2


ADDRESS_CASE = 'lower'


def set_address_case(mode):
    """'lower' (hex addresses, the default) or 'keep' (base58 addresses are case sensitive)."""
    global ADDRESS_CASE
    if mode not in ('lower', 'keep'):
        raise ValueError(f'unknown address case {mode}')
    ADDRESS_CASE = mode


def normalize(address):
    """The key under which a recipient is kept: lower case for hex addresses, unchanged otherwise."""
    return address.lower() if ADDRESS_CASE == 'lower' else address


def load_conditions(path=CONDITIONS_PATH):
    raw = Path(path).read_bytes()
    doc = json.loads(raw)
    if doc.get('kind') != 'fairbind-settlement-replay-conditions' or doc.get('formatVersion') != 1:
        raise ValueError(f'{path}: not a conditions file')
    doc['_sha256'] = hashlib.sha256(raw).hexdigest()
    doc['_path'] = str(path)
    return doc


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def list_hash(addresses, trailing_newline=True):
    text = '\n'.join(normalize(a) for a in addresses) + ('\n' if trailing_newline else '')
    return hashlib.sha256(text.encode()).hexdigest()


def utc_seconds(text):
    """'2026-09-08 00:00:03' (optionally with fractional seconds or ' UTC') to POSIX seconds."""
    text = text.replace(' UTC', '').split('.')[0]
    return int(datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp())


def iter_rows(path, columns):
    """Yields the rows of a settlement list as lists of strings, checking the header."""
    with open(path, newline='', encoding='ascii') as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != columns:
            raise ValueError(f'{path}: header {header} is not {columns}')
        for row in reader:
            yield row


# ---------------------------------------------------------------- reference aggregates

def load_top400(path):
    """Addresses in rank order (row order of the file) with their settlement counts."""
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return [(normalize(r['seller_id']), int(r['settlements'])) for r in rows]


def load_all_addresses(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return [(normalize(r['recipient']), int(r['settlements'])) for r in rows]


def nearest_rank(sorted_values, percentile):
    """ceil(percentile / 100 * N)-th smallest value (the rank rule of injection.p99)."""
    n = len(sorted_values)
    rank = -(-Fraction(percentile, 100) * n // 1)
    return sorted_values[max(1, int(rank)) - 1]


def group_c(all_addresses, cond):
    """Group C: for each percentile, the addresses whose 14-day mean rate is closest to that
    percentile of the mean rates of every address (ties: more settlements, then address string).
    Mean rate is settlements over the rate denominator (rate_blocks, option W344); it orders exactly
    as settlements do, so the list does not depend on the denominator."""
    spec = cond['groups']['C']
    window = cond.get('rate_blocks', cond['window_blocks'])
    rates = sorted(Fraction(s, window) for _, s in all_addresses)
    out, used = {}, set()
    for pct in spec['percentiles']:
        target = nearest_rank(rates, pct)
        ranked = sorted(all_addresses, key=lambda a: (abs(Fraction(a[1], window) - target), -a[1], a[0]))
        picked = [a for a, _ in ranked if a not in used][:spec['per_percentile']]
        used.update(picked)
        out[f'p{pct}'] = dict(target_per_block=str(target), addresses=picked)
    return out


def groups(top400, all_addresses, cond):
    """Address groups by rank; checks every registered list hash. Returns (groups, hash report)."""
    addrs = [a for a, _ in top400]
    g = cond['groups']
    lo, hi = g['A']['ranks']
    out = {
        'all400': addrs[g['all400']['ranks'][0] - 1:g['all400']['ranks'][1]],
        'A': addrs[lo - 1:hi],
        'B': [addrs[r - 1] for r in range(g['B']['rank_from'], g['B']['rank_to'] + 1, g['B']['rank_step'])],
    }
    out['AB'] = out['A'] + out['B']
    c = group_c(all_addresses, cond)
    for key, entry in c.items():
        out[f'C_{key}'] = entry['addresses']
    out['C'] = [a for key in sorted(c, key=lambda k: -int(k[1:])) for a in c[key]['addresses']]
    report = {}
    for name in ('all400', 'A', 'B', 'AB', 'C'):
        got = list_hash(out[name])
        want = g[name]['sha256']
        report[name] = dict(count=len(out[name]), sha256=got, registered=want,
                            match=None if want is None else got == want)
    return out, report, c


# ---------------------------------------------------------------- input checks

def check_input(path, cond, period, *, reference_per_address=None, top400=None, facilitators_path=None,
                expect_hash=True, qx=False):
    """The registered input checks on one settlement list; reads the list once.

    Reports the SHA-256 and row count against the registered values, the time range and
    first/last block, rows off the two-second block formula, ordering and duplicate
    violations, zero values and the largest value (the purchase value cap the replay must
    admit), the facilitator set and its hash, and, with a per-address reference, the
    tolerance rule of injection.input_check over the reference addresses. With qx=True
    (prior period), recomputes the burst statistic on the registered seven-day window.
    No replay quantity is computed here.
    """
    spec = cond['inputs'][period]
    columns = cond['inputs']['columns']
    report = {'file': str(path), 'period': period}
    report['sha256'] = sha256_file(path)
    report['sha256_registered'] = spec['sha256']
    report['sha256_match'] = report['sha256'] == spec['sha256']
    rows = 0
    first = last = None
    t0 = b0 = None
    off_formula = order_violations = zero_values = 0
    max_value = 0
    seen = set()
    duplicates = 0
    prev_key = None
    facilitators = {}
    counts = {}
    qx_start = qx_end = None
    hourly = {}
    if qx:
        qx_start, qx_end = (utc_seconds(t) for t in spec['qx_window_utc'])
    qx_rows = 0
    for row in iter_rows(path, columns):
        block = int(row[0])
        t = utc_seconds(row[1])
        rows += 1
        if first is None:
            first = (block, row[1])
            t0, b0 = t, block
        last = (block, row[1])
        if t - t0 != BLOCK_SECONDS * (block - b0):
            off_formula += 1
        key = (block, int(row[3]), row[4])
        if prev_key is not None and key < prev_key:
            order_violations += 1
        prev_key = key
        ident = (row[2], row[4])
        if ident in seen:
            duplicates += 1
        seen.add(ident)
        value = int(row[7])
        if value == 0:
            zero_values += 1
        if value > max_value:
            max_value = value
        fac = row[8].lower()
        facilitators[fac] = facilitators.get(fac, 0) + 1
        rec = normalize(row[5])
        counts[rec] = counts.get(rec, 0) + 1
        if qx and qx_start <= t < qx_end:
            qx_rows += 1
            hour = (t - qx_start) // 3600
            per = hourly.setdefault(rec, {})
            per[hour] = per.get(hour, 0) + 1
    report.update(rows=rows, rows_registered=spec['rows'], rows_match=rows == spec['rows'],
                  first_block=first[0], first_time_utc=first[1], last_block=last[0], last_time_utc=last[1],
                  blocks_match=(first[0] == spec['first_block'] and last[0] == spec['last_block']),
                  rows_off_block_time_formula=off_formula, order_violations=order_violations,
                  duplicate_tx_trace=duplicates, zero_value_rows=zero_values, max_value_atomic=max_value,
                  distinct_recipients=len(counts))
    fac_sorted = sorted(facilitators)
    fhash = hashlib.sha256('\n'.join(fac_sorted).encode()).hexdigest()
    freg = cond['inputs']['facilitators']
    report['facilitators'] = dict(count=len(fac_sorted), sha256_sorted_no_trailing_newline=fhash,
                                  match=(len(fac_sorted) == freg['count']
                                         and fhash == freg['sha256_sorted_joined_no_trailing_newline']))
    if facilitators_path is not None:
        with open(facilitators_path, newline='', encoding='utf-8') as f:
            listed = {r['facilitator'].lower(): int(r['calls']) for r in csv.DictReader(f)}
        report['facilitators']['file_set_match'] = set(listed) == set(facilitators)
        if period == 'replay_period':
            report['facilitators']['file_counts_match'] = listed == facilitators
    if reference_per_address is not None:
        if top400 is None:
            raise ValueError('the per-address check needs the top-400 list')
        tol = cond['inputs']['check_tolerance']
        per = {a: (counts.get(a, 0), ref) for a, ref in reference_per_address}
        top = {a: per[a] if a in per else (counts.get(a, 0), ref) for a, ref in top400}
        result = inj.input_check(rows, cond['inputs']['expected_total'], top,
                                 total_ppm=tol['total_ppm'], address_ppm=tol['address_ppm'])
        all_diffs = [actual - ref for actual, ref in per.values()]
        extra = sorted(set(counts) - {a for a, _ in reference_per_address})
        report['per_address'] = dict(
            within_tolerance=result['within_tolerance'], total_difference=result['total_difference'],
            top400_difference_sum=result['difference_sum'], top400_difference_max=result['difference_max'],
            top400_over_tolerance=result['addresses_over_tolerance'],
            all_reference_difference_sum=sum(abs(d) for d in all_diffs),
            all_reference_difference_max=max((abs(d) for d in all_diffs), default=0),
            all_reference_nonzero=sum(1 for d in all_diffs if d),
            addresses_not_in_reference=len(extra))
    if qx:
        peaks = {a: list(h.values()) for a, h in hourly.items()}
        report['qx'] = dict(window_utc=spec['qx_window_utc'], window_rows=qx_rows,
                            window_rows_registered=spec['qx_window_rows'], addresses=len(peaks),
                            value=inj.qx_statistic(peaks), registered=cond['q']['qX'])
        report['qx']['match'] = (report['qx']['value'] == cond['q']['qX']
                                 and qx_rows == spec['qx_window_rows'])
    checks = [report['rows_match'], report['blocks_match'], report['facilitators']['match'],
              off_formula == 0, order_violations == 0, duplicates == 0]
    if expect_hash:
        checks.append(report['sha256_match'])
    if 'per_address' in report:
        checks.append(report['per_address']['within_tolerance'])
    if 'qx' in report:
        checks.append(report['qx']['match'])
    report['pass'] = all(checks)
    return report
