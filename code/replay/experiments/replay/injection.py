"""Offline injection model and scale rules for the R20 settlement replay.

The replayer itself (the tool that drives the recorded settlements through the
contract) is a later task. This module fixes the rules its results are computed
with, so that they can be reviewed and tested before any replay runs:

- the per-seller loss model: a confirmed failure freezes every unreleased entry
  settled after the previous freeze block, so each entry is lost at most once;
- the per-seller formula value 1 - exp(-s*w*r*T_hold) + s*w*B/(k*v);
- the scale assignment rules nF (main) and nR (secondary);
- the qX burst statistic and the columns a half replay may feed;
- the tolerance rule of the input check.

Everything is exact where the inputs are integers (blocks, atomic amounts,
counts) and uses floats only for the exponential of the formula value.
"""
import bisect
import math
import random
from fractions import Fraction

# Columns that the two half replays of the cross-fit may feed. Every other column
# (H, sample counts, epoch counts, windows below n_min, injection columns) comes
# from one replay over the whole 14 days, run with the larger of the two half
# values of q.
HALF_REPLAY_COLUMNS = frozenset({'rejected_count', 'rejection_rate', 'R20-F3', 'R20-M1'})
FULL_REPLAY_COLUMNS = frozenset({'H_time_average', 'H_max', 'H_formula', 'sample_count', 'epoch_count',
                                 'windows_below_n_min', 'injection'})
# The replay window: 14 days of two-second blocks.
REPLAY_BLOCKS = 604_800


def _ceil(x):
    x = Fraction(x)
    return -(-x.numerator // x.denominator)


def mean_rate(settlements, blocks):
    """Average settlements per block over the replay period (an exact fraction)."""
    if blocks <= 0:
        raise ValueError('blocks must be positive')
    return Fraction(settlements, blocks)


def scale_nF(settlements, blocks, r_fill):
    """Main rule: n = max(1, ceil(rbar / r_fill)). The bucket's sustained capacity is n * r_fill."""
    return max(1, _ceil(mean_rate(settlements, blocks) / Fraction(r_fill)))


def scale_nR(settlements, blocks, r_max):
    """Secondary rule: n = max(1, ceil(rbar / r_max)). Can leave rbar above n * r_fill."""
    return max(1, _ceil(mean_rate(settlements, blocks) / Fraction(r_max)))


def under_assigned(settlements, blocks, n, r_fill):
    """True when the mean rate exceeds the sustained capacity n * r_fill of the assigned scale."""
    return mean_rate(settlements, blocks) > n * Fraction(r_fill)


def p99(values):
    """Nearest-rank 99th percentile: the ceil(0.99 * N)-th smallest value."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError('no values')
    return ordered[_ceil(Fraction(99, 100) * len(ordered)) - 1]


def qx_statistic(hourly_counts_by_address):
    """qX = p99 over every receiving address of that address's highest one-hour count in the
    seven-day window. The argument maps each address to its hourly settlement counts in the
    window (168 values, or fewer for an address active part of the week)."""
    peaks = []
    for address, counts in hourly_counts_by_address.items():
        counts = list(counts)
        if len(counts) > 168:
            raise ValueError(f'{address}: more than 168 hours in a seven-day window')
        peaks.append(max(counts) if counts else 0)
    return p99(peaks)


def full_replay_q(q_first_half, q_second_half):
    """q of the single 14-day replay under the cross-fit: the larger half value."""
    return max(q_first_half, q_second_half)


def column_source(column):
    """'half' when the column may come from the two half replays, 'full' otherwise."""
    return 'half' if column in HALF_REPLAY_COLUMNS else 'full'


def input_check(total_rows, expected_total, per_address, total_ppm=1000, address_ppm=5000):
    """Tolerance rule of the input check (not a falsification condition).

    Within tolerance when |total_rows - expected_total| <= expected_total * 0.1 percent and,
    for every address, |actual - expected| <= max(1, expected * 0.5 percent). per_address maps
    an address to (actual, expected). Returns a report with every difference, their sum and
    maximum, and whether the replay may start on this extraction.
    """
    diffs = {a: actual - expected for a, (actual, expected) in per_address.items()}
    over = sorted(a for a, (actual, expected) in per_address.items()
                  if abs(actual - expected) > max(1, Fraction(expected * address_ppm, 1_000_000)))
    total_ok = abs(total_rows - expected_total) <= Fraction(expected_total * total_ppm, 1_000_000)
    return {
        'within_tolerance': total_ok and not over,
        'total_difference': total_rows - expected_total,
        'addresses_over_tolerance': over,
        'address_differences': diffs,
        'difference_sum': sum(abs(d) for d in diffs.values()),
        'difference_max': max((abs(d) for d in diffs.values()), default=0),
    }


def formula_value(s, w, rate, t_hold, bond, k, value):
    """Per-seller loss over revenue: 1 - exp(-s*w*rate*T_hold) + s*w*B/(k*v).

    The first term is the share of settlements frozen (each at most once), the second the
    share the per-failure deduction B/k adds. Only the second can take the ratio above one.
    """
    return 1 - math.exp(-s * w * rate * t_hold) + s * w * bond / (k * value)


def draw_failures(cases, w, confirm_delay, rng):
    """Draws a wrongful confirmed failure for each sampled case with probability w.

    cases are the case-opening blocks of the seller's sampled cases in the replay; a drawn
    case is confirmed at its opening block plus confirm_delay (judgmentHorizon + appealHorizon
    + 1). Returns the sorted confirmation blocks.
    """
    return sorted(c + confirm_delay for c in cases if rng.random() < w)


def seller_loss(settlements, confirm_blocks, t_hold, penalty_share, reentry_delay=0):
    """Loss of one honest seller under injected wrongful confirmed failures.

    settlements: (settled_block, value) of the accepted settlements in replay order. An entry
    is released at settled_block + t_hold. confirm_blocks: blocks of the wrongful confirmed
    failures. At a confirmed failure f the account freezes; the new principal loss is every
    entry settled after the previous freeze block and at or before f that is still unreleased
    at f (settled_block + t_hold > f). An entry of an earlier frozen window is never counted
    again: the later failure moves freezeBlock but creates no new pool. Each failure also
    deducts penalty_share (B/k). The seller is suspended from f and re-enters at f + 1 +
    reentry_delay (the first block the contract admits, plus the injected delay); a
    settlement in between is rejected and counted as lost sales, not as loss.
    """
    failures = sorted(confirm_blocks)
    accepted, lost_sales = [], 0
    for block, value in settlements:
        # The latest failure strictly before this block decides whether the seller is suspended.
        i = bisect.bisect_left(failures, block) - 1
        if i >= 0 and block < failures[i] + 1 + reentry_delay:
            lost_sales += value
        else:
            accepted.append((block, value))
    blocks = [b for b, _ in accepted]
    prefix = [0]
    for _, value in accepted:
        prefix.append(prefix[-1] + value)
    principal, previous, last_hi = 0, None, 0
    per_failure = []
    for f in failures:
        # Entries settled in (max(previous freeze block, f - t_hold), f]: after the previous
        # freeze block and still unreleased at f.
        low = f - t_hold if previous is None else max(previous, f - t_hold)
        lo = bisect.bisect_right(blocks, low)
        hi = bisect.bisect_right(blocks, f)
        if lo < last_hi and hi > lo:
            raise AssertionError('entry counted twice')
        new = prefix[hi] - prefix[lo] if hi > lo else 0
        last_hi = max(last_hi, hi)
        per_failure.append(new)
        principal += new
        previous = f
    revenue = sum(v for _, v in accepted)
    penalty = penalty_share * len(failures)
    return {
        'accepted_count': len(accepted),
        'principal_loss': principal,
        'penalty_loss': penalty,
        'loss': principal + penalty,
        'revenue': revenue,
        'lost_sales': lost_sales,
        'per_failure_principal': per_failure,
        'failures': len(failures),
        # R20-C3: principal loss never exceeds revenue when each entry is counted once.
        'counted_once': principal <= revenue,
    }


def injection_row(settlements, cases, *, s, w, t_hold, bond, k, confirm_delay, draws, seed,
                  reentry_delay=0, window_blocks=REPLAY_BLOCKS):
    """Mean injected loss over revenue for one seller over `draws` draws, beside its formula value.

    Returns the Monte Carlo mean, the 2.5 and 97.5 percentiles, and formula_value, the
    per-seller comparison of R20-D1. The formula takes the average rate of the accepted
    settlements over the whole replay window (window_blocks, 14 days; not the span from the
    seller's first to its last settlement, which inflates the rate of a seller active only part
    of the window) and the mean value of the accepted settlements; both are pooled over the
    draws, since suspension rejects different settlements in each draw.
    """
    if not settlements:
        raise ValueError('no settlements')
    rng = random.Random(seed)
    share = bond // k
    if window_blocks <= 0:
        raise ValueError('window_blocks must be positive')
    ratios = []
    accepted_count, accepted_value = 0, 0
    for _ in range(draws):
        failures = draw_failures(cases, w, confirm_delay, rng)
        r = seller_loss(settlements, failures, t_hold, share, reentry_delay)
        if not r['counted_once']:
            raise AssertionError('R20-C3: principal loss above revenue')
        ratios.append(r['loss'] / r['revenue'] if r['revenue'] else 0.0)
        accepted_count += r['accepted_count']
        accepted_value += r['revenue']
    ratios.sort()
    rate = accepted_count / draws / window_blocks
    mean_value = accepted_value / accepted_count if accepted_count else 0
    f = formula_value(s, w, rate, t_hold, bond, k, mean_value) if accepted_count else None
    mean = sum(ratios) / len(ratios)
    return {
        'loss_over_revenue_mean': mean,
        'loss_over_revenue_p2_5': ratios[int(0.025 * (len(ratios) - 1))],
        'loss_over_revenue_p97_5': ratios[int(0.975 * (len(ratios) - 1))],
        'formula_value': f,
        'accepted_rate_per_block': rate,
        'accepted_mean_value': mean_value,
        'ratio_to_formula': mean / f if f else None,
        'draws': draws,
    }
