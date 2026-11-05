"""Worst admissible judgment path: the directives that push every step of a case to its deadline.

The directives apply to the case of every sampled bad sale (the sample is the s-random draw of
the contract; the directives do not choose which sale is detected), so on this path every sampled
bad sale ends in a confirmed failure and the detection probability per bad sale is s. They force
every step to its deadline:
- the seller anchors every epoch at its anchor deadline;
- every assignment of every stage requests serve at its judge deadline and escalates at the
  challenge deadline; the seller redelivers at the serve deadline and publishes at the
  publication deadline;
- initial stage: the first maxAssignments - 1 assignments deliver FAIL at the judge deadline, the
  seller requests evidence at the appeal deadline and nobody discloses it, so the assignment is
  voided by timeoutEvidence in the block after the evidence deadline and replaced; the last
  assignment delivers FAIL at the judge deadline, the seller requests evidence at the appeal
  deadline, the verifier discloses it at the evidence deadline (discloseEvidence admits any sender;
  only the verifier holds the envelope bytes), and the seller appeals at the renewed appeal
  deadline;
- party review and tiebreak: all but the last assignment time out at the judge deadline; the party
  reviewer overturns the FAIL (PASS), which leads to the tiebreak, which confirms the FAIL;
- the keeper lets each review seal lapse once, so every review stage reopens (ADR 0021),
  opens the sample at the end of the open window and makes every other call at its deadline;
- the buyer opens no dispute on the sampled sale (a dispute would make openSample revert) and
  claims only after the case is final.

`schedule(profile)` splits `caseHorizon` (profile-v1 section 3, ADR 0024) into the terms of the
longest case path L_F (`path_budget`, their sum) and `marginBlocks`, which no actor on the case
spends (`margin_unspent`); path_budget + margin_unspent = caseHorizon. A case ends at the latest
caseHorizon - marginBlocks + kappa_Sigma blocks after the bad settlement, kappa_Sigma being the
keeper delays on it. The directives below drive the longest path before ADR 0024; the longest
path of ADR 0024 also opens the sample case after a non-delivery dispute ended as delivered and
lets the tiebreak stall, which the services do not drive yet. The longest sampled path,
the one above, is measured on the contract by contracts/test/WorstPathLength.t.sol and recorded
as L_actual_blocks of the operating point.

Keeper delay: a cell's keeper_delay_budget_blocks (kappa) is a per-case budget. `keeper_delay`
builds the block handed to the keeper: the whole budget is spent on the last keeper call before
the confirmed failure of each case, every other keeper call is prompt, so the keeper delay sum of
a case (kappa_Sigma) equals kappa.
"""
from . import profile as prof

APPLIES_TO = 'every sampled bad sale'
VERIFIER = {
    'initial_non_last_assignments': 'deliver FAIL at the judge deadline; voided by timeoutEvidence '
                                    'in the block after the evidence deadline',
    'review_non_last_assignments': 'time out at the judge deadline',
    'request_serve_at': 'judge_deadline',
    'escalate_at': 'challenge_deadline',
    'verdict_at': 'judge_deadline',
    'disclose_evidence_on_initial_non_last_assignments': False,
    'disclose_evidence_on_initial_last_assignment_at': 'evidence_deadline',
    'initial_verdict': 'FAIL',
    'party_review_verdict': 'PASS',
    'tiebreak_verdict': 'FAIL',
}
SELLER = {
    'anchor_at': 'anchor_deadline',
    'redeliver_at': 'serve_deadline',
    'publish_at': 'publication_deadline',
    'request_evidence_at': 'appeal_deadline',
    'appeal_initial_fail_at': 'renewed_appeal_deadline',
}
KEEPER = {
    'review_seal': 'let the first seal window of every review stage lapse, then seal the reopened stage',
    'call_at': 'deadline',
    'open_sample_at': 'open_window_end',
}
BUYER = {
    'dispute_sampled_sale': False,
    'claim_at': 'after_case_final',
}
KEEPER_DELAY_SPENT_ON = 'last keeper call before the confirmed failure of each case'


def schedule(profile):
    """Block budgets of the worst path, term by term, their sum (path_budget) and the margin
    the path leaves unspent; path_budget + margin_unspent = caseHorizon."""
    p = prof._p(profile)
    d = p['deadlineConfig']
    m = p['maxAssignments']
    terms = [
        ('open', prof.open_horizon(profile)),
        ('assignments_with_redelivery', 3 * m * (2 * d['judgeBlocks'] + 3 * d['serveBlocks'])),
        ('evidence_and_appeals', m * (d['appealBlocks'] + d['evidenceBlocks']) + d['appealBlocks']),
        ('replacement_blocks', 3 * (m - 1)),
        ('review_seals_reopened_once', 2 * (2 * d['sealBlocks'] + 3)),
        ('stalled_review_upholds_fail', 1),
    ]
    path_budget = sum(v for _, v in terms)
    margin = p['marginBlocks']
    horizon = prof.case_horizon(profile)
    if path_budget + margin != horizon:
        raise AssertionError('worst-path budget plus margin differs from caseHorizon')
    return dict(terms=[dict(term=t, blocks=v) for t, v in terms], path_budget=path_budget,
                margin_unspent=margin, case_horizon=horizon, max_replaced_assignments=m - 1)


def directives(profile):
    """Per-process worst-path directive blocks."""
    s = schedule(profile)
    common = dict(judgment_path='worst', applies_to=APPLIES_TO, case_horizon=s['case_horizon'])
    return {
        'verifier': dict(common, **VERIFIER, max_replaced_assignments=s['max_replaced_assignments']),
        'seller': dict(common, **SELLER),
        'keeper': dict(common, **KEEPER),
        'buyer': dict(common, **BUYER),
    }


def keeper_delay(budget_blocks):
    """Keeper directive block for a per-case keeper delay budget (kappa): the whole budget is spent
    on one call, the last keeper call before the confirmed failure of each case; every other call
    is prompt. The per-case keeper delay sum kappa_Sigma is then kappa."""
    budget = int(budget_blocks)
    if budget < 0:
        raise ValueError('keeper_delay_budget_blocks must not be negative')
    return dict(budget_blocks=budget, per='case', spent_on=KEEPER_DELAY_SPENT_ON, other_calls='prompt',
                expected_kappa_sigma=budget)
