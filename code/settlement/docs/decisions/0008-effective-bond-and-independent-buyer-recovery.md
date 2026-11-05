# ADR 0008: Effective-bond liability and independent buyer recovery

Status: User selected both decisions on 2026-09-08; implementation and targeted regression checks complete; clean-revision results recorded separately

## Decisions

Use min(current verifier bond, immutable profile bond cap) for the open-liability
fraction. This resolves the core/profile conflict in favor of the core bound.
Ticket weights remain the committed checkpoint weights; current eligibility and
liability headroom are checked when assigning. No claim is made that exhausted
search supplies a positive detection lower bound.

When a purchase already has a case, a valid buyer NON_DELIVERY dispute opens a
separate buyer recovery record, publication accumulator, and deposit balance.
The existing judgment record, assigned verifier, and its liability remain intact.
The isolated legacy recovery flow remains available. Concurrent recovery uses
explicit buyerServed, acceptBuyerServe, finalizeBuyerServed, escalateBuyerServe,
timeoutBuyerServe, and buyer publication selectors, so messages cannot target
the wrong requester. Buyers may open the separate record at most once per
purchase before claimUntil and after responseDue. Final financial states reject
new claims. The ordinary dispute entry point chooses the independent record
when a case already exists; getBuyerRecovery exposes that record.

The separate flow uses the same delivery deadlines, signature, request binding,
response hashing, size limits, and ordered publication rules. Acceptance or
publication closes only buyer recovery and retains an active judgment hold.
An open buyer recovery always blocks seller release, including when assignment
ends INCONCLUSIVE. Seller failure closes both routes, releases any outstanding
assignment liability once, and enables one refund of principal plus both buyer
deposit balances. Successful delivery assigns its separate deposit to the seller. A prior quality
dispute ending INCONCLUSIVE returns its deposit to the buyer, as lifecycle section
9 already requires; the old release path incorrectly paid it to the seller. A buyer recovery deposit is distinct from a prior quality
dispute deposit; neither overwrites the other.

Starting or restarting chunk publication resets the matching chunk counter as
well as its accumulator. No old chunks survive a new declared publication.

## Property review

P1 identifiers and settlement are unchanged. P2 gains an enforceable path without
requiring an active verifier's cooperation. Chain inclusion and buyer escalation
within deadlines remain necessary. P3 preserves disclosure/acceptance rules and
charges the existing dispute amount for an additional independent claim. P4
preserves judgment state while recovery runs; a confirmed seller failure cancels
the assignment and releases liability without asserting verifier fault. The
future M4 must use this shared closure rule and cannot finalize a financially
refunded purchase or bypass an independent recovery hold.

The added mappings are append-only. This is a fresh immutable deployment, not an
upgrade or migration. Original ABI selectors and storage prefix remain checked.
Regression evidence covers both orderings, deposit conservation, publication,
repeated calls, liability release, and the effective cap boundary. Full M4/M5
acceptance and adversarial conditional-probability proofs remain separate work.
