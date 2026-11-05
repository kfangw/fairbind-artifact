"""Smallest verifier count for which the last assignment of a worst-path case is unlikely to fail.

Model of the assignment search in `FairBindCore._assignVerifier`:
- the epoch's checkpoint holds N verifiers (the seal requires N >= minVerifiers);
- one search tries rounds 0 .. minVerifiers - 1; each round draws a ticket
  keccak256(ASSIGN_DOMAIN, randomness, nonce, stage, attempt, round) mod totalEffectiveWeight
  and maps it to a verifier by cumulative checkpoint weight, so each round is an independent
  draw with replacement (keccak modelled as a random oracle; the modulo bias is below 2^-160);
- a drawn verifier is skipped when it already took part in the case (`caseParticipation`),
  and the search ends the case (protocol INCONCLUSIVE) when no round finds one;
- equal checkpoint weights are assumed (weight = min(bond, verifierBondCap), so equal bonds at
  or above the cap give equal weights); all verifiers are assumed otherwise eligible (active,
  bond above the minimum, liability headroom).

A worst-path case makes 3 * maxAssignments assignments (maxAssignments per stage for the
initial stage, the party review and the tiebreak), each to a verifier not yet in the case.
The last one therefore faces k = 3 * maxAssignments - 1 excluded verifiers and fails with

    P_last(N, R) = (k / N) ** R,   R = minVerifiers rounds.

For N >= R this is at most (k / R) ** R, reached when exactly minVerifiers verifiers are
registered, so the bound on minVerifiers alone holds for every admitted deployment. The
margin is the smallest integer c with ((3m - 1) / (3m + c)) ** (3m + c) <= target for every
admissible maxAssignments m in 1..3.

Unequal weights: when the k excluded verifiers hold weight share w, P_last = w ** R. With a
weight ratio rho = verifierBondCap / minVerifierBond between the heaviest and lightest
checkpoint entry, w <= k * rho / (k * rho + N - k); `weighted_bound` reports that ceiling.

Run: python3 experiments/verifier_count.py [--target 1e-3] [--json]
"""
import argparse
import json
from fractions import Fraction

MAX_ASSIGNMENTS = (1, 2, 3)


def p_last(k, n, rounds):
    """Probability that one search of `rounds` draws over n equal-weight verifiers hits only the k excluded."""
    if k >= n:
        return Fraction(1)
    return Fraction(k, n) ** rounds


def p_case(m, n, rounds):
    """Probability that some assignment of a 3m-assignment case fails (assignment j faces j excluded)."""
    ok = Fraction(1)
    for j in range(3 * m):
        ok *= 1 - p_last(j, n, rounds)
    return 1 - ok


def smallest_count(m, target):
    """Smallest N (registered = minVerifiers = rounds) with P_last <= target, and every larger N as well."""
    k = 3 * m - 1
    n = 3 * m
    while p_last(k, n, n) > target:
        n += 1
    # (k/n)^n decreases in n for n > k, so every larger count also meets the target.
    return n


def weighted_bound(k, n, rounds, rho):
    share = Fraction(k) * rho / (Fraction(k) * rho + (n - k))
    return share ** rounds


def monte_carlo(m, n, rounds, trials, seed):
    """Simulate the search as implemented (independent draws per round) and count failed last assignments."""
    import random
    rng = random.Random(seed)
    failed = 0
    for _ in range(trials):
        taken = set()
        for j in range(3 * m):
            chosen = None
            for _round in range(rounds):
                v = rng.randrange(n)
                if v not in taken:
                    chosen = v
                    break
            if chosen is None:
                if j == 3 * m - 1:
                    failed += 1
                break
            taken.add(chosen)
    return failed / trials


def derive(target):
    rows = []
    for m in MAX_ASSIGNMENTS:
        n = smallest_count(m, target)
        rows.append({'maxAssignments': m, 'excluded': 3 * m - 1, 'smallestCount': n, 'margin': n - 3 * m,
                     'pLastAtCount': float(p_last(3 * m - 1, n, n)),
                     'pLastOneBelow': float(p_last(3 * m - 1, n - 1, n - 1)),
                     'pCaseAtCount': float(p_case(m, n, n))})
    margin = max(r['margin'] for r in rows)
    for r in rows:
        count = 3 * r['maxAssignments'] + margin
        r['countUnderRule'] = count
        r['pLastUnderRule'] = float(p_last(r['excluded'], count, count))
        r['pCaseUnderRule'] = float(p_case(r['maxAssignments'], count, count))
    table = []
    for n in range(9, 21):
        table.append({'count': n, 'pLast': float(p_last(8, n, n)), 'pCase': float(p_case(3, n, n))})
    return {'target': float(target), 'margin': margin, 'rule': f'minVerifiers >= 3 * maxAssignments + {margin}',
            'perMaxAssignments': rows, 'maxAssignments3Table': table,
            'registered40With14Rounds': float(p_last(8, 40, 14)),
            'registered40With9Rounds': float(p_last(8, 40, 9))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--target', default='1e-3')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--monte-carlo', type=int, default=0, help='trials per maxAssignments (0: skip)')
    ap.add_argument('--rho', type=int, default=0, help='weight ratio for the unequal-weight ceiling (0: skip)')
    a = ap.parse_args()
    target = Fraction(a.target)
    result = derive(target)
    if a.rho:
        result['weightedCeiling'] = {
            str(r['maxAssignments']): float(weighted_bound(r['excluded'], r['countUnderRule'], r['countUnderRule'],
                                                           Fraction(a.rho)))
            for r in result['perMaxAssignments']}
    if a.monte_carlo:
        result['monteCarlo'] = {str(r['maxAssignments']): monte_carlo(
            r['maxAssignments'], r['smallestCount'], r['smallestCount'], a.monte_carlo, 20260929)
            for r in result['perMaxAssignments']}
    if a.json:
        print(json.dumps(result, indent=2))
        return
    print(f"target P_last <= {a.target}; rule: {result['rule']}")
    print('m  k  smallest N  margin  P_last(N)   P_last(N-1)  P_case(N)   N under rule  P_last under rule')
    for r in result['perMaxAssignments']:
        print(f"{r['maxAssignments']}  {r['excluded']}  {r['smallestCount']:>10}  {r['margin']:>6}  "
              f"{r['pLastAtCount']:.3e}   {r['pLastOneBelow']:.3e}    {r['pCaseAtCount']:.3e}   "
              f"{r['countUnderRule']:>12}  {r['pLastUnderRule']:.3e}")
    print('\nmaxAssignments = 3, N = minVerifiers registered:')
    for row in result['maxAssignments3Table']:
        print(f"  N = {row['count']:>2}: P_last = {row['pLast']:.4e}, P_case = {row['pCase']:.4e}")
    for key in ('weightedCeiling', 'monteCarlo'):
        if key in result:
            print(f'{key}: {result[key]}')


if __name__ == '__main__':
    main()
