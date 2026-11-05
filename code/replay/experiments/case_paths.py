"""Enumerate the case state machine as implemented and find the longest path to a confirmed failure.

The tool models one purchase from its settlement block to the block of a confirmed seller failure
(`FINAL(FAIL)` or `UNSERVED`) with every actor calling at the last block the contract admits and
every timeout called in the first block it becomes eligible. It then compares the longest path with
`caseHorizon - marginBlocks` and reports, term by term, the blocks of `caseHorizon` that no failure
path can spend.

Timing conventions (the same as contracts/test/WorstPathLength.t.sol):
- a windowed call lands on its deadline; a timeout lands on deadline + 1;
- the settlement is in the first block of its epoch, which maximizes every epoch-relative wait;
- public progress calls that have no deadline are prompt: `openSample` at the end of the open window
  (the latest block the profile budgets for it; the contract admits a later opening, which is keeper
  delay, not a transition window), `assignVerifier` as soon as the dispute and the epoch seal both
  exist, `finalizeServed` at challengeUntil + 1, `finalizeCase` at the first block after the window
  it closes.

Transitions and windows, with where each was read (C = contract, S = specification):
- open, sampled: anchor in [anchorBase, anchorDeadline], anchorBase = epochEnd(e + 1)
  (C FairBindSampling.anchor, FairBindCore._anchorBase; S lifecycle-v1 section 1); seal in
  (randomBlock, randomBlock + sealBlocks], randomBlock = anchorDeadline + 1 + beaconDelayBlocks
  (C FairBindSampling.anchor/seal); openSample assigns in the same transaction
  (C FairBindSampling.openSample; S lifecycle-v1 sections 1 and 4).
- open, dispute: dispute(WRONG_DELIVERY) through claimUntil = settle + responseBlocks + claimBlocks,
  also after a NON_DELIVERY redelivery that ended DELIVERED (C FairBindDelivery.dispute; S
  lifecycle-v1 sections 2 and 4); assignVerifier needs the sealed epoch
  (C FairBindSampling.assignVerifier, FairBindCore._assignVerifier).
- redelivery of an assignment: requestServe through judgeDue, serveDue = +serveBlocks; served
  through serveDue, challengeUntil = +serveBlocks; escalate through challengeUntil, publishDue =
  +serveBlocks; publication through publishDue; delivery resumes the stage with judgeDue =
  +judgeBlocks; finalizeServed after challengeUntil; timeoutServe after serveDue or publishDue ends
  the case UNSERVED (C FairBindDelivery.requestServe/served/escalate/finalizeServed/timeoutServe,
  FairBindCore._completeDelivery; S lifecycle-v1 sections 4 and 5). One serve request per
  assignment (`serveUsed`).
- judgment: judge through judgeDue = assignment + judgeBlocks; timeoutJudge after it replaces the
  assignment in the same transaction while attempts remain (C FairBindJudgment.judge,
  FairBindSampling.timeoutJudge, FairBindCore._replaceLateAssignment; S lifecycle-v1 section 6).
- last attempt lost: an initial stage of a sampled case with nothing served goes to keeper
  publication (publishDue = +serveBlocks), any other stage ends protocol INCONCLUSIVE
  (C FairBindCore._protocolInconclusive; S lifecycle-v1 section 4, ADR 0014).
- initial verdict: appealUntil = verdict + appealBlocks; requestEvidence (buyer or seller, once per
  assignment, state INITIAL_VERDICT only) through appealUntil, evidenceDue = +evidenceBlocks;
  discloseEvidence through evidenceDue renews appealUntil = +appealBlocks; timeoutEvidence after
  evidenceDue voids and replaces the assignment (C FairBindReview.requestEvidence/
  discloseEvidence, FairBindSampling.timeoutEvidence; S lifecycle-v1 section 6).
- appeal through appealUntil (seller against FAIL, buyer against PASS), review randomBlock =
  appeal + 1; without an appeal finalizeCase after appealUntil ends a FAIL and sends PASS or
  INCONCLUSIVE to the recheck gate with randomBlock = appealUntil + 1 (C FairBindReview.appeal/
  finalizeCase/openAutoRecheck, FairBindCore._openAutoReview; S lifecycle-v1 sections 4 and 7).
- review seal in (randomBlock, randomBlock + sealBlocks]; past it the first lapse reopens with
  randomBlock = block + 1, the second ends INCONCLUSIVE; sealing a party review or tiebreak assigns
  in the same transaction, the recheck gate assigns the AUTO stage when selected
  (C FairBindCore._sealReview, FairBindReview.sealReviewRandomness/finalizeCase; S lifecycle-v1
  section 7, ADR 0021).
- review verdicts: a PARTY or AUTO verdict equal to the initial verdict is final, a different one
  opens the tiebreak with randomBlock = verdict + 1; the tiebreak verdict is final; review stages
  admit neither evidence requests nor appeals (C FairBindJudgment.judge; S lifecycle-v1 sections 4
  and 7, ADR 0019).

Run: python3 experiments/case_paths.py [--profile NAME] [--json]
"""
import argparse
import functools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from controller import profile as prof  # noqa: E402

PROFILE_FILE = ROOT / 'profiles' / 'local-evaluation-v1.json'
# Measured with contracts/test/WorstPathLength.t.sol (operating point L_actual_blocks).
MEASURED = {'data-api-fast-v1': 29680, 'open-weights-standard-v1': 91180}

# caseHorizon terms (profile-v1 section 3) the steps are charged to.
TERMS = ('open', 'serve', 'judge', 'evidence', 'appeal', 'slack', 'seal')
NEG = float('-inf')


class Model:
    """Longest-path search over the case states, with one objective per run."""

    def __init__(self, profile):
        p = prof._p(profile)
        d = p['deadlineConfig']
        self.m = p['maxAssignments']
        self.S, self.J = d['serveBlocks'], d['judgeBlocks']
        self.E, self.A, self.Sb = d['evidenceBlocks'], d['appealBlocks'], d['sealBlocks']
        self.recheck = p['recheckPpm'] > 0
        seal_deadline = 2 * p['epochBlocks'] + d['anchorBlocks'] + p['beaconDelayBlocks'] + d['sealBlocks']
        self.open_sampled = seal_deadline + d['openBlocks']
        self.open_dispute = max(d['responseBlocks'] + d['claimBlocks'], seal_deadline)
        self.budget = dict(
            open=prof.open_horizon(profile),
            serve=3 * (2 + 3 * self.m) * self.S,
            judge=3 * self.m * 2 * self.J,
            evidence=3 * self.m * self.E,
            appeal=3 * self.m * 2 * self.A,
            slack=3 * self.m * 2,
            seal=2 * 2 * (self.Sb + 2),
        )
        self.margin = p['marginBlocks']
        self.horizon = prof.case_horizon(profile)
        assert sum(self.budget.values()) + self.margin == self.horizon

    # A move is (label, [(term, blocks), ...], next state). A state is a tuple; terminal states
    # are ('FAIL',) and ('UNSERVED',) (confirmed failures) or ('END',) (no seller failure).
    def moves(self, s):
        kind = s[0]
        S, J, E, A, Sb, m = self.S, self.J, self.E, self.A, self.Sb, self.m
        if kind == 'start':
            trigger = s[1]
            blocks = self.open_sampled if trigger == 'SAMPLE' else self.open_dispute
            label = ('openSample + assign at the end of the open window' if trigger == 'SAMPLE'
                     else 'dispute(WRONG_DELIVERY) at claimUntil + assignVerifier')
            return [(label, [('open', blocks)], ('assigned', trigger, 'I', 0, False, None))]
        if kind == 'assigned':
            _, trig, stage, att, served, iv = s
            judging = ('judging', trig, stage, att, served, iv)
            return [
                ('no redelivery', [], judging),
                ('requestServe at judgeDue, served at serveDue, escalate at challengeUntil, publish at publishDue',
                 [('judge', J), ('serve', 3 * S)], ('judging', trig, stage, att, True, iv)),
                ('requestServe at judgeDue, served at serveDue, finalizeServed after challengeUntil',
                 [('judge', J), ('serve', 2 * S), ('slack', 1)], ('judging', trig, stage, att, True, iv)),
                ('requestServe at judgeDue, no serve, timeoutServe after serveDue',
                 [('judge', J), ('serve', S), ('slack', 1)], ('UNSERVED',)),
                ('requestServe at judgeDue, served, escalated, no publication, timeoutServe after publishDue',
                 [('judge', J), ('serve', 3 * S), ('slack', 1)], ('UNSERVED',)),
            ]
        if kind == 'judging':
            _, trig, stage, att, served, iv = s
            out = []
            for v in ('FAIL', 'PASS', 'INCONCLUSIVE'):
                steps = [('judge', J)]
                if stage == 'I':
                    out.append((f'initial {v} at judgeDue', steps, ('verdict', trig, att, served, v, False)))
                elif stage in ('P', 'A'):
                    nxt = ('final', v) if v == iv else ('seal', trig, 'T', iv, served)
                    out.append((f'{stage} review {v} at judgeDue', steps, nxt))
                else:
                    out.append((f'tiebreak {v} at judgeDue', steps, ('final', v)))
            out.append(('timeoutJudge after judgeDue', [('judge', J), ('slack', 1)],
                        ('lost', trig, stage, att, served, iv)))
            return out
        if kind == 'lost':
            _, trig, stage, att, served, iv = s
            if att + 1 < m:
                return [('replaced in the same transaction', [], ('assigned', trig, stage, att + 1, served, iv))]
            if stage == 'I' and trig == 'SAMPLE' and not served:
                return [('keeper publication, no publish, timeoutServe after publishDue',
                         [('serve', S), ('slack', 1)], ('UNSERVED',)),
                        ('keeper publication, published', [('serve', S)], ('END',))]
            return [('protocol INCONCLUSIVE', [], ('END',))]
        if kind == 'verdict':
            # Initial verdict, appeal window open; `renewed` once evidence was disclosed.
            _, trig, att, served, v, renewed = s
            out = []
            if not renewed:
                out.append(('requestEvidence at appealUntil, no disclosure, timeoutEvidence after evidenceDue',
                            [('appeal', A), ('evidence', E), ('slack', 1)], ('lost', trig, 'I', att, served, None)))
                out.append(('requestEvidence at appealUntil, discloseEvidence at evidenceDue',
                            [('appeal', A), ('evidence', E)], ('verdict', trig, att, served, v, True)))
            if v in ('PASS', 'FAIL'):
                out.append(('appeal at appealUntil', [('appeal', A)], ('seal', trig, 'P', v, served)))
            if v == 'FAIL':
                out.append(('finalizeCase after appealUntil', [('appeal', A), ('slack', 1)], ('FAIL',)))
            elif self.recheck:
                out.append(('recheck gate after appealUntil', [('appeal', A)], ('seal', trig, 'A', v, served)))
            return out
        if kind == 'seal':
            # From the block that fixed randomBlock = block + 1 to the seal that assigns.
            _, trig, stage, iv, served = s
            nxt = ('assigned', trig, stage, 0, served, iv)
            return [('seal at the end of the seal window', [('seal', Sb + 1)], nxt),
                    ('seal lapses, reopened after the window, sealed at the end of the new window',
                     [('seal', 2 * Sb + 3)], nxt),
                    ('seal lapses twice', [('seal', 2 * Sb + 2)], ('END',))]
        if kind == 'final':
            return [('FINAL', [], ('FAIL',) if s[1] == 'FAIL' else ('END',))]
        raise ValueError(s)

    @functools.lru_cache(maxsize=None)
    def best(self, s, objective):
        """Largest value of the objective over the paths from s to a confirmed failure."""
        if s in (('FAIL',), ('UNSERVED',)):
            return 0, ()
        if s == ('END',):
            return NEG, ()
        top, path = NEG, ()
        for label, steps, nxt in self.moves(s):
            rest, tail = self.best(nxt, objective)
            if rest == NEG:
                continue
            gain = sum(b for t, b in steps if objective == 'total' or t == objective)
            if gain + rest > top:
                top, path = gain + rest, ((label, tuple(steps)),) + tail
        return top, path


def usage(path):
    used = {t: 0 for t in TERMS}
    for _, steps in path:
        for t, b in steps:
            used[t] += b
    return used


UNUSED_REASONS = {
    'serve': 'the two buyer NON_DELIVERY procedures of the serve term: a buyer procedure on the case '
             'ends before claimUntil (conversion to WRONG_DELIVERY is timely only through claimUntil), '
             'inside the open term, and an independent buyer recovery never moves the case',
    'evidence': 'the evidence windows of the review stages: requestEvidence is admitted only in '
                'INITIAL_VERDICT',
    'appeal': 'both appeal windows of every review-stage assignment (appeal and requestEvidence only in '
              'INITIAL_VERDICT), and the renewed appeal window of every replaced initial assignment '
              '(the window is renewed only by a disclosure, after which timeoutEvidence no longer applies)',
    'slack': 'one block of the per-assignment +2 of the last assignment of each stage: it is never '
             'replaced, so it spends at most the finalizeServed block after its challenge window',
    'seal': 'one block per review stage: a lapsed seal reopens in the block after the window and the '
            'reopened seal ends one block after its random block, 2 * sealBlocks + 3 of 2 * (sealBlocks + 2)',
    'open': 'none',
    'judge': 'none',
}


def analyse(profile):
    model = Model(profile)
    name = profile['name']
    total, path = max((model.best(('start', t), 'total') for t in ('SAMPLE', 'DISPUTE')), key=lambda r: r[0])
    sampled, sampled_path = model.best(('start', 'SAMPLE'), 'total')
    dispute, _ = model.best(('start', 'DISPUTE'), 'total')
    used = usage(path)
    terms = []
    for t in TERMS:
        most = max(model.best(('start', trig), t)[0] for trig in ('SAMPLE', 'DISPUTE'))
        terms.append(dict(term=t, budget=model.budget[t], longest_path_uses=used[t], most_any_path_uses=most,
                          unusable=model.budget[t] - most,
                          reason=UNUSED_REASONS[t] if model.budget[t] - most else 'none'))
    return dict(
        profile=name, maxAssignments=model.m, caseHorizon=model.horizon, marginBlocks=model.margin,
        caseHorizon_minus_margin=model.horizon - model.margin,
        longest=total, longest_sampled=sampled, longest_dispute=dispute,
        measured=MEASURED.get(name), exceeds_measured=MEASURED.get(name) is not None and total > MEASURED[name],
        unspent_by_longest=model.horizon - model.margin - total,
        terms=terms, unusable_total=sum(t['unusable'] for t in terms),
        longest_path=[dict(step=label, blocks=sum(b for _, b in steps)) for label, steps in path],
        longest_sampled_path_uses=usage(sampled_path),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--profile-file', default=str(PROFILE_FILE))
    ap.add_argument('--profile', action='append', help='profile name (default: every profile of the file)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    doc = json.loads(Path(a.profile_file).read_text())
    names = a.profile or [p['name'] for p in doc['profiles']]
    results = [analyse(prof.load_profile(a.profile_file, n)) for n in names]
    if a.json:
        print(json.dumps(results, indent=2))
        return
    print('profile                     longest  sampled  dispute  measured  caseHorizon-margin  unusable')
    for r in results:
        print(f"{r['profile']:<26} {r['longest']:>8} {r['longest_sampled']:>8} {r['longest_dispute']:>8} "
              f"{r['measured'] or '-':>9} {r['caseHorizon_minus_margin']:>19} {r['unusable_total']:>9}")
    for r in results:
        print(f"\n{r['profile']}: caseHorizon {r['caseHorizon']} = terms + margin {r['marginBlocks']}")
        for t in r['terms']:
            print(f"  {t['term']:<9} budget {t['budget']:>7}  longest {t['longest_path_uses']:>7}  "
                  f"any path {t['most_any_path_uses']:>7}  unusable {t['unusable']:>6}  {t['reason']}")
        print('  longest path:')
        at = 0
        for step in r['longest_path']:
            at += step['blocks']
            print(f"    {at:>7}  +{step['blocks']:<6} {step['step']}")


if __name__ == '__main__':
    main()
