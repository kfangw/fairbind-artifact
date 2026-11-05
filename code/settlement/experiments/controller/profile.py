"""Service profile arithmetic from docs/spec/profile-v1.md sections 2 to 4."""
import copy
import json
import math

PPM = 1_000_000
UINT32_MAX = 2**32 - 1
# 128 L1 blocks of twelve seconds on a two-second settlement chain.
MIN_BEACON_DELAY_BLOCKS = 768
# Verifiers beyond 3 * maxAssignments (ADR 0023, experiments/verifier_count.py).
VERIFIER_COUNT_MARGIN = 5
DEADLINE_FIELDS = ('anchorBlocks', 'sealBlocks', 'openBlocks', 'responseBlocks', 'claimBlocks', 'serveBlocks',
                   'judgeBlocks', 'evidenceBlocks', 'appealBlocks')


def load_profile(path, name=None):
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    profiles = doc.get('profiles')
    if not isinstance(profiles, list) or not profiles:
        raise ValueError(f'{path}: no profiles')
    if name is None:
        if len(profiles) != 1:
            raise ValueError(f'{path}: several profiles; name one')
        return copy.deepcopy(profiles[0])
    for p in profiles:
        if p.get('name') == name:
            return copy.deepcopy(p)
    raise ValueError(f'{path}: no profile named {name}')


def _p(profile):
    return profile['parameters']


def _int(v):
    return int(v) if isinstance(v, str) else v


def open_horizon(profile):
    """Latest case opening (ADR 0024): the sample opening, the claim deadline, and a sample
    case opened after a buyer non-delivery dispute ended as delivered."""
    p = _p(profile)
    d = p['deadlineConfig']
    sampled = 2 * p['epochBlocks'] + d['anchorBlocks'] + p['beaconDelayBlocks'] + d['sealBlocks'] + d['openBlocks']
    claimed = d['responseBlocks'] + d['claimBlocks']
    return max(sampled, claimed, min(sampled, claimed) + 3 * d['serveBlocks'])


def judgment_delay(profile):
    """Longest case path L_F = L_any (ADR 0024, lemma C third edition): every stage with all
    its assignments and serve procedures, two lapsed review seals, and the block in which a
    stalled seller-appealed review upholds the initial FAIL."""
    p = _p(profile)
    d = p['deadlineConfig']
    m = p['maxAssignments']
    return (open_horizon(profile) + 3 * m * (2 * d['judgeBlocks'] + 3 * d['serveBlocks'])
            + m * (d['appealBlocks'] + d['evidenceBlocks']) + d['appealBlocks'] + 3 * (m - 1)
            + 2 * (2 * d['sealBlocks'] + 3) + 1)


def case_horizon(profile):
    """The longest case path plus the keeper margin (ADR 0024)."""
    return judgment_delay(profile) + _p(profile)['marginBlocks']


def penalty_floor(profile, defer_blocks=None, max_rate_ppm=None, keeper_delay_sum=0):
    """expectedPenaltyFloor = g * (ceil(PPM / effectivePpm) + ceil(maxRate * (L + kappa - D)+ / PPM)).

    kappa (keeper_delay_sum, kappa_Sigma) is the sum of the keeper delays on the path to the
    confirmed failure. The admission rule of profile-v1 section 4 is the kappa = 0 case; the
    bond curve and the I6 exposure prediction pass the keeper delay of the point, since the
    confirmed failure lands at most T_catch + kappa after the bad settlement.
    """
    p = _p(profile)
    d = p['deferBlocks'] if defer_blocks is None else defer_blocks
    rate = p['maxRatePpmPerBlock'] if max_rate_ppm is None else max_rate_ppm
    if keeper_delay_sum < 0:
        raise ValueError('keeper_delay_sum must not be negative')
    post = -(-rate * max(0, judgment_delay(profile) + keeper_delay_sum - d) // PPM)
    return _int(p['maxBadGain']) * (-(-PPM // p['effectivePpm']) + post)


def disable_cap(profile):
    """The 'cap off' transform: raise the bucket and rate fields so the settle bucket never
    rejects a call in practice. There is no contract switch for this; it is these field values.

    maxRatePpmPerBlock is set to UINT32_MAX (4294967295), refillPpmPerBlock to half of that
    (2147483647, so the rate condition below still holds), enforcementBlocks is raised to at
    least the judgment delay L, and bucketCapacity is set to the largest value the rate
    condition still allows for that enforcement window, capped at UINT32_MAX:

        bucketCapacity = min(UINT32_MAX, (maxRatePpmPerBlock - refillPpmPerBlock)
                              * enforcementBlocks // PPM)

    The rate condition bucketCapacity * PPM + refill * enforcement <= maxRate *
    enforcement still holds, so the result can be admissible when D >= L. With
    the cap off, a run's exposure is computed from the settlement rate Lambda
    actually observed in that run (not an assumed maximum), and the run
    asserts that no settle call was ever rejected for the rate
    (rejected_settlement_count == 0).
    """
    p = _p(profile)
    p['enforcementBlocks'] = max(p['enforcementBlocks'], judgment_delay(profile))
    p['maxRatePpmPerBlock'] = UINT32_MAX
    p['refillPpmPerBlock'] = UINT32_MAX // 2
    p['bucketCapacity'] = min(UINT32_MAX, (UINT32_MAX - UINT32_MAX // 2) * p['enforcementBlocks'] // PPM)


# The admission checks that the test build contracts/test/AdmissionOverrideRegistry.sol skips
# (FairBindCore._admissionOverride). This tuple is the single list: the controller copies it into
# every plan entry and result envelope that uses the override, and the READMEs point here.
# 'deferBlocks >= caseHorizon' is not a separate contract check; it follows from the first two.
OVERRIDE_SKIPPED_CHECKS = ('retentionBlocks >= caseHorizon', 'deferBlocks >= caseHorizon',
                           'deferBlocks >= retentionBlocks', 'enforcementBlocks >= judgmentDelayBlocks',
                           'freezeOnInitialFail == false')
# Fields a deferral sweep point sets to D. failureWindowBlocks and inconclusiveWindowBlocks
# keep their profile values so that the failure count and the inconclusive rate mean the same
# thing at every point.
D_SWEEP_FIELDS = ('deferBlocks', 'retentionBlocks', 'claimWindowBlocks')


def admissibility(profile):
    """Return the admission rules the profile violates (empty when admissible)."""
    p = _p(profile)
    L = judgment_delay(profile)
    horizon = case_horizon(profile)
    checks = [
        ('deferBlocks >= retentionBlocks', p['deferBlocks'] >= p['retentionBlocks']),
        ('deferBlocks >= caseHorizon', p['deferBlocks'] >= horizon),
        ('retentionBlocks >= caseHorizon', p['retentionBlocks'] >= horizon),
        ('claimWindowBlocks == retentionBlocks', p['claimWindowBlocks'] == p['retentionBlocks']),
        ('enforcementBlocks >= judgmentDelayBlocks', p['enforcementBlocks'] >= L),
        ('bucketCapacity > 0', p['bucketCapacity'] > 0),
        ('refillPpmPerBlock <= maxRatePpmPerBlock', p['refillPpmPerBlock'] <= p['maxRatePpmPerBlock']),
        ('rate condition', p['bucketCapacity'] * PPM + p['refillPpmPerBlock'] * p['enforcementBlocks']
         <= p['maxRatePpmPerBlock'] * p['enforcementBlocks']),
        ('sellerPenalty >= expectedPenaltyFloor', _int(p['sellerPenalty']) >= penalty_floor(profile)),
        ('0 < sealBlocks <= 255', 0 < p['deadlineConfig']['sealBlocks'] <= 255),
        ('responseBlocks <= epochBlocks + anchorBlocks',
         p['deadlineConfig']['responseBlocks'] <= p['epochBlocks'] + p['deadlineConfig']['anchorBlocks']),
        ('0 < maxAssignments <= 3', 0 < p['maxAssignments'] <= 3),
        (f'minVerifiers >= 3 * maxAssignments + {VERIFIER_COUNT_MARGIN}',
         p['minVerifiers'] >= 3 * p['maxAssignments'] + VERIFIER_COUNT_MARGIN),
        ('0 <= recheckPpm <= PPM', 0 <= p['recheckPpm'] <= PPM),
        ('beaconDelayBlocks >= 768', p['beaconDelayBlocks'] >= MIN_BEACON_DELAY_BLOCKS),
        # The production build freezes only at the confirmed failure; the override build
        # admits either timing and requires the initial-FAIL freeze below the case horizon.
        ('freezeOnInitialFail == false', p['freezeOnInitialFail'] is False),
        ('minJudgedCount >= 1', p['minJudgedCount'] >= 1),
    ]
    for field in ('deferBlocks', 'retentionBlocks', 'epochBlocks', 'bucketCapacity', 'maxRatePpmPerBlock',
                  'refillPpmPerBlock', 'enforcementBlocks'):
        checks.append((f'{field} fits uint32', 0 <= p[field] <= UINT32_MAX))
    return [name for name, ok in checks if not ok]


def ceil_ppm(fraction):
    return int(math.ceil(fraction * PPM - 1e-9))
