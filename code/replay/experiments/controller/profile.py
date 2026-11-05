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
    p = _p(profile)
    d = p['deadlineConfig']
    return max(2 * p['epochBlocks'] + d['anchorBlocks'] + p['beaconDelayBlocks'] + d['sealBlocks'] + d['openBlocks'],
               d['responseBlocks'] + d['claimBlocks'])


def judgment_delay(profile):
    p = _p(profile)
    d = p['deadlineConfig']
    m = p['maxAssignments']
    judgment = m * (d['judgeBlocks'] + 1) + d['evidenceBlocks']
    # Appeal window, one party review and the tiebreak it can lead to (ADR 0019).
    appeal = d['appealBlocks'] + 2 * (1 + m * (d['judgeBlocks'] + 1))
    return open_horizon(profile) + judgment + appeal + 1


def case_horizon(profile):
    p = _p(profile)
    d = p['deadlineConfig']
    m = p['maxAssignments']
    return (open_horizon(profile) + 3 * (2 + 3 * m) * d['serveBlocks']
            + 3 * m * (2 * d['judgeBlocks'] + d['evidenceBlocks'] + 2 * d['appealBlocks'] + 2)
            # Two review seals, each of which may reopen once (ADR 0021).
            + 2 * 2 * (d['sealBlocks'] + 2) + p['marginBlocks'])


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


# Poll interval of the services in the hold-period harness: the pollIntervalMs the local deploy step
# writes into the keeper configuration (scripts/local_setup.py).
HARNESS_POLL_MS = 100
# Purchases the buyer is funded for when a plan names no expected count (the deploy step's own
# default).
DEFAULT_BUYER_PURCHASES = 1000


def assignable_bond_floor(profile):
    """Smallest verifier bond with which a verifier without open cases takes an assignment of a
    purchase of maxPurchaseValue (FairBindCore assignment loop): bond >= minVerifierBond and
    (bond - reserve) * verifierExposurePpm / PPM >= maxPurchaseValue + maxReviewCost, with reserve
    the larger of verifierLatePenalty and verifierWrongPenalty."""
    p = _p(profile)
    reserve = max(_int(p['verifierLatePenalty']), _int(p['verifierWrongPenalty']))
    liability = _int(p['maxPurchaseValue']) + _int(p['maxReviewCost'])
    return max(_int(p['minVerifierBond']), reserve + -(-liability * PPM // p['verifierExposurePpm']))


def harness(profile, scale_factor, assignable_verifiers, spare_verifiers=None, buyer_purchases=None):
    """The `harness` block the deploy step reads beside the profile (not ground truth).

    - sellerBondScale: the seller's bond account holds sellerBondScale * sellerPenalty;
    - assignableVerifiers verifiers register with verifierBondAtomic (verifierBondCap, at least
      assignable_bond_floor); the profile's minVerifiers is a contract admission check, so when
      fewer are assignable the others (registeredVerifiers - assignableVerifiers) register with
      minVerifierBond, which must stay below the floor so that they are never assigned;
    - spareVerifiers identities are prepared but not registered: the pool registers one with the
      same bond in the block after a verifier is removed (default: one per registered verifier);
    - cheatBody: the seller holds a wrong body for every response (the same preimage, a wrong value);
    - pollMs: the poll interval of every service;
    - buyerPurchases: the purchases the buyer is funded for (the run's expected count with margin,
      runner.expected_purchases).
    """
    p = _p(profile)
    registered = max(assignable_verifiers, p['minVerifiers'])
    return dict(sellerBondScale=scale_factor, registeredVerifiers=registered,
                assignableVerifiers=assignable_verifiers, verifierBondAtomic=str(p['verifierBondCap']),
                spareVerifiers=registered if spare_verifiers is None else spare_verifiers,
                cheatBody=True, pollMs=HARNESS_POLL_MS,
                buyerPurchases=DEFAULT_BUYER_PURCHASES if buyer_purchases is None else int(buyer_purchases))


def harness_violations(profile, block):
    """Reasons a harness block cannot run on the profile (empty when it can)."""
    p = _p(profile)
    floor = assignable_bond_floor(profile)
    errors = []
    if _int(block['verifierBondAtomic']) < floor:
        errors.append(f'verifierBondAtomic {block["verifierBondAtomic"]} is below the assignable floor {floor}')
    if _int(block['verifierBondAtomic']) > _int(p['verifierBondCap']):
        errors.append('verifierBondAtomic exceeds verifierBondCap')
    if block['registeredVerifiers'] > block['assignableVerifiers'] and _int(p['minVerifierBond']) >= floor:
        errors.append(f'verifiers at minVerifierBond {p["minVerifierBond"]} would be assignable (floor {floor}); '
                      f'the profile cannot register {block["registeredVerifiers"]} verifiers with only '
                      f'{block["assignableVerifiers"]} assignable')
    if block['registeredVerifiers'] < p['minVerifiers']:
        errors.append(f'registeredVerifiers {block["registeredVerifiers"]} is below minVerifiers {p["minVerifiers"]}')
    scale = block['sellerBondScale']
    if isinstance(scale, bool) or not isinstance(scale, int) or scale < 1:
        errors.append('sellerBondScale must be a positive integer')
    return errors
