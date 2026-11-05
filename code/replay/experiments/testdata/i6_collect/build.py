"""Write the run-directory fixtures of experiments/test_i6_collect.py.

    python3 experiments/testdata/i6_collect/build.py

Each fixture is a small hand-made run: a ledger dump (fairbind-ledger-dump/v1), the ground truth,
the derived profile, the deployment, the directives, keeper events, seller records and verifier
injection records. Nonces are chosen so that the seeded injection draws give the verdicts the
ledger records. The expected metric values are worked out in test_i6_collect.py.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
import collect_run  # noqa: E402

SEED = 20260928
INJECTION = dict(h=0.67, alpha=0.01, beta=0.05, c=0.1)
SELLER, BOND, PROFILE = 1, 1, 1
OWNER = '0x' + '11' * 20
BUYER = '0x' + '22' * 20
PENALTY = 4_000_000  # k * g * ceil(1/p) = 16 * 10,000 * 25
V = 10_000


def h32(label):
    return '0x' + hashlib.sha256(label.encode()).hexdigest()


def tx(label):
    return h32('tx/' + label)


def pick_nonce(label, predicate, want, honest_error_off=False):
    """The first nonce label/i whose stage-1 attempt-0 draws turn the predicate verdict into `want`."""
    params = dict(INJECTION, honestErrorOff=honest_error_off)
    if honest_error_off:
        params.update(alpha=0.0, c=0.0)
    for i in range(10_000):
        nonce = h32(f'{label}/{i}')
        u1 = collect_run.injection_draw(SEED, nonce, 1, 0, 'honesty')
        u2 = collect_run.injection_draw(SEED, nonce, 1, 0, 'outcome')
        if collect_run.injected_verdict(params, predicate, u1, u2)[2] == want:
            return nonce
    raise RuntimeError(label)


def record(nonce, verifier, predicate, honest_error_off=False):
    params = dict(INJECTION, honestErrorOff=honest_error_off)
    if honest_error_off:
        params.update(alpha=0.0, c=0.0)
    u1 = collect_run.injection_draw(SEED, nonce, 1, 0, 'honesty')
    u2 = collect_run.injection_draw(SEED, nonce, 1, 0, 'outcome')
    honest, rule, verdict = collect_run.injected_verdict(params, predicate, u1, u2)
    return dict(version=1, nonce=nonce, stage=1, attempt=0, verifierId=verifier, seed=SEED, params=params,
                gate='READY', predicateVerdict=predicate, applied=True, honestyDraw=u1, honest=honest,
                outcomeDraw=u2, outcomeRule=rule, verdict=verdict)


class Run:
    def __init__(self, name):
        self.dir = HERE / name
        self.events = []
        self.purchases = {}
        self.removals = []

    def ev(self, block, event, label, **args):
        index = sum(1 for e in self.events if e['block'] == block)
        self.events.append(dict(block=block, logIndex=index, tx=tx(label), event=event, args=args))

    def settle(self, block, nonce, epoch, release_block=None):
        self.ev(block, 'Settled', f'settle/{nonce}', nonce=nonce, keyId=h32('k' + nonce), sellerId=SELLER,
                bondId=BOND, profileId=PROFILE, buyer=BUYER, value=str(V), epoch=epoch,
                requestHash=h32('r' + nonce), claimsHash=h32('claims'))
        self.purchases[nonce] = dict(
            nonce=nonce, settledBlock=block, purchaseState=1, purchaseStateName='DEFERRED',
            purchase=dict(nonce=nonce, sellerId=SELLER, profileId=PROFILE, value=str(V), epoch=epoch,
                          settledBlock=block, releaseBlock=release_block or block + 60000, financialState=1),
            case=dict(nonce=nonce, stateName='NONE', state=0, finalVerdict=0, trigger=0, requesterRole=0,
                      stage=0, attempt=0, initialVerdict=0))

    def state(self, nonce, name):
        self.purchases[nonce]['purchaseStateName'] = name

    def case(self, nonce, state, final_verdict, stage=1):
        self.purchases[nonce]['case'].update(stateName=state, finalVerdict=final_verdict, trigger=1, stage=stage,
                                             requesterRole=2)

    def write(self, *, gt, directives, deployment, keeper_rows, records, policy=None, attack=None, verifiers,
              view_block, sealed_versions, extra_profiles=None):
        if self.dir.exists():
            shutil.rmtree(self.dir)
        params = profile_parameters()
        checkpoints = [dict(version=v, verifierIds=ids, weights=['1'] * len(ids), checkpointBlock=b,
                            totalEffectiveWeight=str(len(ids)), setHash=h32(f'set{v}'))
                       for v, (b, ids) in sorted(sealed_versions.items())]
        led = dict(
            format='fairbind-ledger-dump/v1', chainId=31337, contract='0x' + '33' * 20, fromBlock=0,
            toBlock=view_block, viewBlock=view_block, eventSignatures={},
            events=sorted(self.events, key=lambda e: (e['block'], e['logIndex'])),
            views=dict(
                profiles=[dict(profileId=PROFILE, active=True, parameters=params, checkpoints=checkpoints)],
                sellers=[dict(sellerId=SELLER, profileId=PROFILE, bondId=BOND, owner=OWNER, status=1,
                              statusName='ACTIVE')],
                bonds=[dict(bondId=BOND, profileId=PROFILE, owner=OWNER, balance=str(PENALTY), scaleFactor=1,
                            failureWindowScale=1, deferredBalance='0', statusName='ACTIVE')],
                verifiers=verifiers,
                purchases=[self.purchases[n] for n in self.purchases]),
            derived=dict(verifierRemovals=self.removals))
        files = {
            'ledger.json': led,
            'ground-truth.json': gt,
            'shared/profile.json': dict(formatVersion=1, derivedFromScenario='I6', admissionOverride=False,
                                        profiles=[shared_profile()]),
            'proc/deploy/deployment.json': deployment,
        }
        for name, d in directives.items():
            files[f'proc/{name}/directive.json'] = d
        if policy is not None:
            files['proc/deploy/services/seller/data/meta/policy.json'] = policy
        if attack is not None:
            files['proc/deploy/services/seller/data/meta/attack.json'] = attack
        for rec in records:
            key = f"{rec['nonce'][2:]}-{rec['stage']}-{rec['attempt']}-{rec['verifierId']}"
            files[f"proc/deploy/services/verifier/{rec['verifierId']}/state/injection/{key}.json"] = rec
        for rel, doc in files.items():
            path = self.dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')
        events = self.dir / 'proc' / 'keeper' / 'events.jsonl'
        events.parent.mkdir(parents=True, exist_ok=True)
        events.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in keeper_rows))


def shared_profile():
    doc = json.loads((ROOT / 'profiles' / 'local-evaluation-v1.json').read_text())
    p = next(x for x in doc['profiles'] if x['name'] == 'data-api-fast-v1')
    p = json.loads(json.dumps(p))
    p['parameters']['sellerPenalty'] = str(PENALTY)
    p.pop('parameterHash', None)
    return p


def profile_parameters():
    """The on-chain parameters as the ledger dump decodes them (deadline configuration by id)."""
    p = dict(shared_profile()['parameters'])
    p.pop('deadlineConfig')
    p.pop('canonicalHeaders', None)
    p.pop('bucketCapacityPercentilePpm', None)
    p['deadlineConfigId'] = 1
    return p


def verifier_views(ids, removed=()):
    return [dict(verifierId=v, bond='100000000', status=2 if v in removed else 1,
                 statusName='REMOVED' if v in removed else 'ACTIVE') for v in ids]


def directives(run_id, seller_policy, workload_rate, honest_error_off=False, finite=None):
    inj = dict(INJECTION, applies_to='every assignment', honest_error_off=honest_error_off,
               draw='sha256(fairbind/seed/verifier || seed || nonce || stage || attempt || purpose)')
    if honest_error_off:
        inj.update(alpha=0.0, c=0.0)
    seller = dict(seed=SEED, kind='hold_period_grid', parameters={}, seller_policy=seller_policy)
    if finite:
        seller['finite_attack'] = finite
    return dict(
        verifier=dict(seed=SEED, kind=None, parameters={}, judgment_injection=inj),
        seller=seller,
        buyer=dict(seed=SEED, kind=None, parameters={}, workload=dict(rate_per_block=workload_rate)))


def deployment(verifiers, setup_block):
    return dict(formatVersion=1, chainId=31337, contract='0x' + '33' * 20, setupBlock=setup_block,
                seller=dict(sellerId=SELLER, bondId=BOND, profileId=PROFILE), bond=dict(bondId=BOND),
                verifiers=[dict(verifierId=v, assignable=a, bond=b) for v, a, b in verifiers])


def ground_truth(run_id, cell, rule, m, **params):
    base = dict(bad_sale_gain_atomic=V, keeper_delay_budget_blocks=0, judgment_path='normal',
                seller_role='cheater', finite_attack_after='none', scale_factor=1)
    base.update(params)
    return dict(run_id=run_id, scenario='I6', cell=cell, bad_sales_rule=rule, bad_sales_m=m, parameters=base,
                events=[])


def register_setup(run, bonds):
    run.ev(5, 'BondRegistered', 'bond', bondId=BOND, profileId=PROFILE, owner=OWNER, balance=str(PENALTY),
           scaleFactor=1)
    run.ev(6, 'SellerRegistered', 'seller', sellerId=SELLER, bondId=BOND, profileId=PROFILE, owner=OWNER,
           signingKey=OWNER, claimsHash=h32('claims'))
    for i, (vid, bond) in enumerate(bonds):
        run.ev(10 + i, 'VerifierRegistered', f'verifier/{vid}', verifierId=vid, owner=OWNER,
               signingKey='0x' + f'{vid:040x}', classBitmap='2', bond=str(bond))


def cheater():
    """Two episodes of a cheater with a keeper delay budget of 100 blocks.

    Episode 1 (from block 100): n1, n2, n3 settle in epoch 0; n2 is sampled, judged FAIL and final at
    block 2000 (finalizeCase due at 1900, sent 100 blocks late); the account is frozen, n2 refunded,
    n1 paid from the pool, n3 forfeited. Verifier 3 is removed at 3000 and replaced at 3001. The
    seller re-enters at 5100. Episode 2: n4 and n5 settle in epoch 17; n5 is sampled and judged
    PASS; both are released. Verifier 4 holds only minVerifierBond and is not assignable.
    """
    run = Run('cheater')
    register_setup(run, [(1, 100_000_000), (2, 100_000_000), (3, 100_000_000), (4, 1_000_000)])
    n1, n3, n4 = h32('cheater/n1'), h32('cheater/n3'), h32('cheater/n4')
    n2 = pick_nonce('cheater/n2', 'FAIL', 'FAIL')
    n5 = pick_nonce('cheater/n5', 'FAIL', 'PASS')
    run.settle(100, n1, 0)
    run.settle(120, n2, 0)
    run.settle(140, n3, 0)
    run.ev(700, 'Anchored', 'anchor0', sellerId=SELLER, epoch=0, root=h32('root0'), profileId=PROFILE, count=3,
           randomBlock=800, publicationHash=h32('pub0'))
    run.ev(900, 'EpochSealed', 'seal0', sellerId=SELLER, epoch=0, randomness=h32('rand0'),
           verifierSetHash=h32('set1'), sortitionVersion=1, totalEffectiveWeight='4')
    run.ev(950, 'CaseOpened', 'open/n2', nonce=n2, trigger=1, requester=OWNER, heldValue=str(V))
    run.ev(950, 'VerifierAssigned', 'open/n2', nonce=n2, stage=1, attempt=0, verifierId=1, deadline=1250)
    run.ev(1000, 'VerdictSubmitted', 'judge/n2', nonce=n2, stage=1, verifierId=1, verdict=2,
           evidenceHash=h32('ev/n2'))
    run.ev(2000, 'CaseFinalized', 'finalize/n2', nonce=n2, finalVerdict=2, financialState=4)
    run.ev(2000, 'Slashed', 'finalize/n2', actorType=1, actorId=SELLER, nonce=n2, recipient=OWNER,
           amount='250000', reason=4)
    run.ev(2000, 'SellerSuspended', 'finalize/n2', sellerId=SELLER, bondId=BOND, triggerNonce=n2)
    run.ev(2000, 'SellerDeferredFrozen', 'finalize/n2', bondId=BOND, sellerId=SELLER, triggerNonce=n2,
           frozenTotal='20000', frozenAtBlock=2000)
    run.ev(2000, 'ClaimWindowOpened', 'finalize/n2', bondId=BOND, triggerNonce=n2, claimUntilBlock=4900,
           poolBalance='20000')
    run.ev(2100, 'Refunded', 'refund/n2', nonce=n2, buyer=BUYER, value=str(V), source=1)
    run.ev(2200, 'FrozenClaimPaid', 'claim/n1', bondId=BOND, sellerId=SELLER, nonce=n1, buyer=BUYER, value=str(V))
    run.ev(3000, 'Slashed', 'strike/v3', actorType=2, actorId=3, nonce=n2, recipient=OWNER, amount='100000',
           reason=2)
    run.removals.append(dict(verifierId=3, block=3000, logIndex=0, tx=tx('strike/v3'), nonce=n2, strikes=3,
                             strikeLimit=3))
    run.ev(3001, 'VerifierRegistered', 'verifier/5', verifierId=5, owner=OWNER, signingKey='0x' + f'{5:040x}',
           classBitmap='2', bond='100000000')
    run.ev(5000, 'UnclaimedForfeited', 'forfeit', bondId=BOND, nonce=n2, total=str(V), toVerifierPool='0',
           toReserve='0')
    run.ev(5100, 'SellerReinstated', 'reinstate', sellerId=SELLER, bondId=BOND, atBlock=5100)
    run.settle(5200, n4, 17)
    run.settle(5300, n5, 17)
    run.ev(6000, 'EpochSealed', 'seal17', sellerId=SELLER, epoch=17, randomness=h32('rand17'),
           verifierSetHash=h32('set2'), sortitionVersion=2, totalEffectiveWeight='4')
    run.ev(6100, 'CaseOpened', 'open/n5', nonce=n5, trigger=1, requester=OWNER, heldValue=str(V))
    run.ev(6100, 'VerifierAssigned', 'open/n5', nonce=n5, stage=1, attempt=0, verifierId=2, deadline=6400)
    run.ev(6200, 'VerdictSubmitted', 'judge/n5', nonce=n5, stage=1, verifierId=2, verdict=1,
           evidenceHash=h32('ev/n5'))
    run.ev(7000, 'CaseFinalized', 'finalize/n5', nonce=n5, finalVerdict=1, financialState=1)
    run.ev(65200, 'Released', 'release/n4', nonce=n4, sellerId=SELLER, value=str(V))
    run.ev(65300, 'Released', 'release/n5', nonce=n5, sellerId=SELLER, value=str(V))
    for n, s in ((n1, 'REFUNDED'), (n2, 'REFUNDED'), (n3, 'FORFEITED'), (n4, 'RELEASED'), (n5, 'RELEASED')):
        run.state(n, s)
    run.case(n2, 'FINAL', 2)
    run.case(n5, 'FINAL', 1)
    keeper_rows = [
        dict(event='call_sent', status='sent', action='anchor', tx=tx('anchor0'), due=700, delay=0, nonce='',
             epoch=f'{SELLER}:0'),
        dict(event='call_sent', status='sent', action='finalizeCase', tx=tx('finalize/n2'), due=1900, delay=100,
             nonce=n2, epoch=''),
        dict(event='call_sent', status='sent', action='finalizeCase', tx=tx('finalize/n5'), due=7000, delay=0,
             nonce=n5, epoch=''),
        dict(event='case_delay', nonce=n2, kappa=100, kappa_sigma=100, confirmed=True),
        dict(event='call_sent', status='sent', action='reverted', tx=tx('missing'), due=10, delay=0, nonce=n2,
             epoch=''),
    ]
    policy = dict(version=1, role='cheater', scaleFactor=1, reentry='top_up_to_scale_then_reinstate',
                  topUp='before_reentry_to_scale',
                  actions=[dict(block=1001, action='appeal', nonce=n2),
                           dict(block=5099, action='top_up', cause='reentry', amount=250000, target=PENALTY),
                           dict(block=5100, action='reinstate')])
    run.write(
        gt=ground_truth('I6-cheater-r0', 'P2-high', 'all_cheater_episode_sales', None, keeper_delay_budget_blocks=100),
        directives=directives('I6-cheater-r0', dict(role='cheater', appeal_initial_fail=True, scale_factor=1,
                                                    reentry='top_up_to_scale_then_reinstate',
                                                    top_up='before_reentry_to_scale'), 0.05),
        deployment=deployment([(1, True, '100000000'), (2, True, '100000000'), (3, True, '100000000'),
                               (4, False, '1000000')], setup_block=20),
        keeper_rows=keeper_rows, records=[record(n2, 1, 'FAIL'), record(n5, 2, 'FAIL')], policy=policy,
        verifiers=verifier_views([1, 2, 3, 4, 5], removed=(3,)), view_block=70000,
        sealed_versions={1: (20, [1, 2, 3, 4]), 2: (3002, [1, 2, 4, 5])})


def finite_switch():
    """F-switch, m = 2: f1 and f2 are bad, f3 and f4 honest. f2 is sampled, judged FAIL and final at
    block 1500 (a confirmed failure caused by a bad sale); every entry is frozen. f3 is sampled and
    judged PASS with the honest error off."""
    run = Run('finite_switch')
    register_setup(run, [(1, 100_000_000), (2, 100_000_000)])
    f1, f4 = h32('switch/f1'), h32('switch/f4')
    f2 = pick_nonce('switch/f2', 'FAIL', 'FAIL', honest_error_off=True)
    f3 = pick_nonce('switch/f3', 'PASS', 'PASS', honest_error_off=True)
    run.settle(100, f1, 0)
    run.settle(130, f2, 0)
    run.settle(160, f3, 0)
    run.settle(190, f4, 0)
    run.ev(900, 'EpochSealed', 'seal0', sellerId=SELLER, epoch=0, randomness=h32('rand0'),
           verifierSetHash=h32('set1'), sortitionVersion=1, totalEffectiveWeight='2')
    for n, vid, verdict, b in ((f2, 1, 2, 950), (f3, 2, 1, 960)):
        run.ev(b, 'CaseOpened', f'open/{n}', nonce=n, trigger=1, requester=OWNER, heldValue=str(V))
        run.ev(b, 'VerifierAssigned', f'open/{n}', nonce=n, stage=1, attempt=0, verifierId=vid, deadline=b + 300)
        run.ev(b + 50, 'VerdictSubmitted', f'judge/{n}', nonce=n, stage=1, verifierId=vid, verdict=verdict,
               evidenceHash=h32('ev' + n))
    run.ev(1400, 'CaseFinalized', 'finalize/f3', nonce=f3, finalVerdict=1, financialState=1)
    run.ev(1500, 'CaseFinalized', 'finalize/f2', nonce=f2, finalVerdict=2, financialState=4)
    run.ev(1500, 'Slashed', 'finalize/f2', actorType=1, actorId=SELLER, nonce=f2, recipient=OWNER,
           amount='250000', reason=4)
    run.ev(1500, 'SellerSuspended', 'finalize/f2', sellerId=SELLER, bondId=BOND, triggerNonce=f2)
    run.ev(1500, 'SellerDeferredFrozen', 'finalize/f2', bondId=BOND, sellerId=SELLER, triggerNonce=f2,
           frozenTotal='30000', frozenAtBlock=1500)
    for n, s in ((f1, 'FROZEN_CLAIMABLE'), (f2, 'REFUNDABLE'), (f3, 'FROZEN_CLAIMABLE'), (f4, 'FROZEN_CLAIMABLE')):
        run.state(n, s)
    run.case(f2, 'FINAL', 2)
    run.case(f3, 'FINAL', 1)
    run.write(
        gt=ground_truth('I6-switch-r0', 'F-switch', 'first_m', 2, seller_role='finite',
                        finite_attack_after='serve_honestly', finite_attack_cheat_sales=2),
        directives=directives('I6-switch-r0', dict(role='finite', appeal_initial_fail=True, scale_factor=1,
                                                   reentry='none', top_up='none'), 0.0471,
                              honest_error_off=True, finite=dict(cheat_sales=2, after='serve_honestly')),
        deployment=deployment([(1, True, '100000000'), (2, True, '100000000')], setup_block=20),
        keeper_rows=[dict(event='call_sent', status='sent', action='finalizeCase', tx=tx('finalize/f2'), due=1500,
                          delay=0, nonce=f2, epoch='')],
        records=[record(f2, 1, 'FAIL', True), record(f3, 2, 'PASS', True)],
        attack=dict(version=1, accepted=4, cheated=[f1, f2]),
        verifiers=verifier_views([1, 2]), view_block=2000, sealed_versions={1: (20, [1, 2])})


def finite_exit():
    """F-exit, m = 1: g1 is bad and never sampled; the seller exits at 60050 while g1 is still
    deferred, g1 is released at 60100, the bond account exits at 60200. The episode ends without a
    detection at 100 + 60000 + 58994 = 119094."""
    run = Run('finite_exit')
    register_setup(run, [(1, 100_000_000)])
    g1 = h32('exit/g1')
    run.settle(100, g1, 0)
    run.ev(101, 'SellerExitRequested', 'exitreq', sellerId=SELLER, eligibleBlock=60100)
    run.ev(102, 'BondExitRequested', 'bondexitreq', bondId=BOND, eligibleBlock=60102)
    run.ev(900, 'EpochSealed', 'seal0', sellerId=SELLER, epoch=0, randomness=h32('rand0'),
           verifierSetHash=h32('set1'), sortitionVersion=1, totalEffectiveWeight='1')
    run.ev(60050, 'SellerExited', 'sellerexit', sellerId=SELLER, owner=OWNER, amount='0')
    run.ev(60100, 'Released', 'release/g1', nonce=g1, sellerId=SELLER, value=str(V))
    run.ev(60200, 'BondExited', 'bondexit', bondId=BOND, owner=OWNER, amount=str(PENALTY))
    run.state(g1, 'RELEASED')
    run.write(
        gt=ground_truth('I6-exit-r0', 'F-exit', 'first_m', 1, seller_role='finite', finite_attack_after='request_exit',
                        finite_attack_cheat_sales=1),
        directives=directives('I6-exit-r0', dict(role='finite', appeal_initial_fail=True, scale_factor=1,
                                                 reentry='none', top_up='none'), 0.0471,
                              finite=dict(cheat_sales=1, after='request_exit')),
        deployment=deployment([(1, True, '100000000')], setup_block=20), keeper_rows=[], records=[],
        attack=dict(version=1, accepted=1, cheated=[g1]), verifiers=verifier_views([1]), view_block=119100,
        sealed_versions={1: (20, [1])})


def honest():
    """Honest seller, n = 1: h2 is sampled and wrongly judged FAIL (final at 70000, refunded at 70100,
    a deduction topped up at 70001); h3 is sampled and judged PASS. The workload started at block
    100, so the complete failure windows from 100 + T_hold are [60100, 120099] and [120100, 180099];
    the window from 180100 is cut off by the end of the run at 185000."""
    run = Run('honest')
    register_setup(run, [(1, 100_000_000), (2, 100_000_000)])
    h1 = h32('honest/h1')
    h2 = pick_nonce('honest/h2', 'PASS', 'FAIL')
    h3 = pick_nonce('honest/h3', 'PASS', 'PASS')
    run.settle(100, h1, 0)
    run.settle(200, h2, 0)
    run.settle(300, h3, 1)
    run.ev(900, 'EpochSealed', 'seal0', sellerId=SELLER, epoch=0, randomness=h32('rand0'),
           verifierSetHash=h32('set1'), sortitionVersion=1, totalEffectiveWeight='2')
    run.ev(1200, 'EpochSealed', 'seal1', sellerId=SELLER, epoch=1, randomness=h32('rand1'),
           verifierSetHash=h32('set1'), sortitionVersion=1, totalEffectiveWeight='2')
    for n, vid, verdict, b in ((h2, 1, 2, 950), (h3, 2, 1, 1250)):
        run.ev(b, 'CaseOpened', f'open/{n}', nonce=n, trigger=1, requester=OWNER, heldValue=str(V))
        run.ev(b, 'VerifierAssigned', f'open/{n}', nonce=n, stage=1, attempt=0, verifierId=vid, deadline=b + 300)
        run.ev(b + 50, 'VerdictSubmitted', f'judge/{n}', nonce=n, stage=1, verifierId=vid, verdict=verdict,
               evidenceHash=h32('ev' + n))
    run.ev(2000, 'CaseFinalized', 'finalize/h3', nonce=h3, finalVerdict=1, financialState=1)
    run.ev(60100, 'Released', 'release/h1', nonce=h1, sellerId=SELLER, value=str(V))
    run.ev(60300, 'Released', 'release/h3', nonce=h3, sellerId=SELLER, value=str(V))
    run.ev(70000, 'CaseFinalized', 'finalize/h2', nonce=h2, finalVerdict=2, financialState=4)
    run.ev(70000, 'Slashed', 'finalize/h2', actorType=1, actorId=SELLER, nonce=h2, recipient=OWNER,
           amount='250000', reason=4)
    run.ev(70100, 'Refunded', 'refund/h2', nonce=h2, buyer=BUYER, value=str(V), source=1)
    for n, s in ((h1, 'RELEASED'), (h2, 'REFUNDED'), (h3, 'RELEASED')):
        run.state(n, s)
    run.case(h2, 'FINAL', 2)
    run.case(h3, 'FINAL', 1)
    policy = dict(version=1, role='honest', scaleFactor=1, reentry='top_up_to_scale_then_reinstate',
                  topUp='after_each_deduction_to_scale',
                  actions=[dict(block=70001, action='top_up', cause='deduction', deductionBlock=70000,
                                amount=250000, target=PENALTY)])
    run.write(
        gt=ground_truth('I6-honest-r0', 'H', 'none', None, seller_role='honest'),
        directives=directives('I6-honest-r0', dict(role='honest', appeal_initial_fail=True, scale_factor=1,
                                                   reentry='top_up_to_scale_then_reinstate',
                                                   top_up='after_each_deduction_to_scale'), 0.05),
        deployment=deployment([(1, True, '100000000'), (2, True, '100000000')], setup_block=20),
        keeper_rows=[dict(event='call_sent', status='sent', action='finalizeCase', tx=tx('finalize/h2'),
                          due=70000, delay=0, nonce=h2, epoch='')],
        records=[record(h2, 1, 'PASS'), record(h3, 2, 'PASS')], policy=policy,
        verifiers=verifier_views([1, 2]), view_block=185000, sealed_versions={1: (20, [1, 2])})
    summary = run.dir / 'workload' / 'summary.json'
    summary.parent.mkdir(parents=True, exist_ok=True)
    # The fields of services/buyer/workload_summary.go the collector reads.
    summary.write_text(json.dumps(dict(
        blocks=dict(start=100, end=185000, max_blocks=None),
        honest_windows=dict(first_window_start=60100, end_block=360100, windows=5, window_blocks=60000),
        purchases=dict(attempted=3, settled=3), clock=dict(stops=12)), indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    cheater()
    finite_switch()
    finite_exit()
    honest()
