# ADR 0024: Value-proportional sampling with seller-chosen terms, and four case rules

Status: Accepted 2026-10-08. Amends ADR 0004 (bounded profiles), ADR 0011
(bond-keyed rate cap), ADR 0014 (keeper serve), ADR 0018 (per-failure
deduction), ADR 0019 (tiebreak) and ADR 0021 (case horizon, reopened review
seal) in `profile-v1.md` sections 3 and 9, `fairbind-v1.md` sections 12, 16,
17 and 18, `lifecycle-v1.md` section 4 and `contract-interface-v1.md`.
Appends storage slots and router entries; changes no existing ABI entry, no
existing storage slot and no existing encoding. Changes the derived analysis
values of both evaluation profiles and, through `enforcementBlocks` and
`failureLimit`, their `parameterHash`.

The research rules this record implements are the second edition of the design
2 rules (D2-1 to D2-18) and the third edition of lemma C (rules R15 to R22).
The record names each rule by its D2 number.

## Problem

Under a constant sampling rate `s`, the exposure bound of one episode is
`g / (s * p0)`, so the bond grows with the purchase cap `g` divided by `s`.
Sampling a purchase with a probability proportional to its value removes the
`1 / s` factor: the expected exposure of an episode is at most `vmax / p0`
whatever values, times and stopping rule the seller picks, and a deduction of
`b >= vmax / p0` per confirmed failure makes fraud unprofitable for every sales
limit. The contract had one cap per profile, a constant `samplePpm`, and a
unit bucket that only scaled up.

The case rules had four gaps that the longest-path analysis of lemma C found:

1. A sampled purchase whose non-delivery dispute ended as delivered could not
   open its sample case (`openSample` required no case), and `releasePurchase`
   paid it to the seller.
2. A review the seller appealed against an initial `FAIL` that could not
   progress (two lapsed seals, every assignment timing out, or the assignment
   search running dry) ended as a protocol `INCONCLUSIVE`. A seller could buy
   the party reviewer's `PASS` and let the tiebreak lapse.
3. A sample case whose receipt the seller did not put on chain with an
   inclusion proof could not be judged, and ended `INCONCLUSIVE` through the
   keeper serve path. An omitted receipt drawn for sampling ended the same way.
4. `caseHorizon` and `judgmentDelayBlocks` did not budget the delivery
   procedures of the review stages or the delivered-dispute opening; the
   enumerated longest path (30,573 blocks for the data API profile) exceeded
   `judgmentDelayBlocks` (9,380), and a hold period of 31,073 blocks failed
   admission against the loose `caseHorizon` (58,994).

## Decision

1. **Longest path (D2-8, R21).** `judgmentDelayBlocks` is the longest path from
   a settlement to the end of its case:

   ```text
   O_s = 2 * epochBlocks + anchorBlocks + beaconDelayBlocks + sealBlocks + openBlocks
   O_d = responseBlocks + claimBlocks
   O   = max(O_s, O_d, min(O_s, O_d) + 3 * serveBlocks)
   L   = O + 3m * (2 * judgeBlocks + 3 * serveBlocks) + m * (appealBlocks + evidenceBlocks)
           + appealBlocks + 3 * (m - 1) + 2 * (2 * sealBlocks + 3) + 1
   caseHorizon = L + marginBlocks
   ```

   with `m = maxAssignments`. Admission keeps `retentionBlocks >= caseHorizon`,
   `deferBlocks >= retentionBlocks` and `enforcementBlocks >=
   judgmentDelayBlocks`. The data API reference profile with `marginBlocks =
   500` gives `L = 30,573` and `caseHorizon = 31,073`, which is now admissible.

2. **Delivered disputes open their sample case (D2-11, rule 94a).**
   `openSample` also accepts a purchase whose case is `DELIVERED` with trigger
   `NON_DELIVERY` and whose funds are `RELEASABLE`, or `HELD` by an open buyer
   recovery. It rewrites the same case record as a sample case and clears the
   dispute's requester, role, resume state, bundle hash and serve deadlines,
   so the sample case owes its own on-chain response (ADR 0014).
   `releasePurchase` refuses such a purchase with `NotSampled` while it is
   sampled and its sample case has not run.

3. **A stalled seller appeal upholds the initial FAIL (D2-15).** When a case
   with `reviewPath = 1` and `initialVerdict = FAIL` ends through a progress
   failure in the party review or in the tiebreak it leads to, the result is
   `FINAL(FAIL)`: the failure is confirmed, counted and deducted, no review
   verdict pays a wrong-verdict penalty, the appeal deposit goes to the buyer,
   and the inconclusive counters do not move. Buyer appeals and automatic
   rechecks keep the protocol `INCONCLUSIVE`.

4. **Sample receipts on chain (D2-17).** Opening a sample case sets a receipt
   deadline `serveBlocks` after the opening block. Anyone may put the
   seller-signed receipt and its inclusion proof in the anchored epoch on chain
   with `submitSampleReceipt` until the deadline; a verdict that carries them
   before the deadline does the same. After the deadline,
   `timeoutSampleReceipt` ends a non-terminal sample case without them as
   `UNSERVED`, a confirmed failure. The window runs alongside the first
   judgment window, so the longest path does not change.

5. **Value-proportional sampling with seller-chosen terms (D2-1 to D2-5,
   D2-7, D2-13, D2-14).** Governance may fix, once and before activation, the
   terms of a profile with `setProfileTerms`: the detection floor `p0`, the
   value caps a seller may choose, and the sales tiers `(S, q_S, r_S, k_S)`.
   Admission requires `samplePpm = PPM`, `effectivePpm = p0`, the largest cap
   equal to `maxPurchaseValue` and at least `maxBadGain`, the last tier equal to
   the profile's bucket and failure limit with `sellerPenalty / failureLimit >=
   b(largest cap)`, strictly increasing caps and limits, and for every tier
   `q_S * PPM + r_S * (failureWindowBlocks + caseHorizon) <= S * PPM`.

   A bond account under such a profile is opened with
   `registerBondWithTerms(profileId, amount, valueCap, tier)`; `registerBond`
   refuses the profile. Its unit bond is `B = k_S * b(V*)` with
   `b(v) = ceil(40 * v * PPM / (27 * p0))` and `V*` the highest cap the account
   held within `retentionBlocks`. A small tier never scales above one unit; the
   last tier scales with the balance as before. `settle` refuses a value above
   the account's current cap before it reads the bucket, and records
   `s_ppm = min(PPM, ceil(v * PPM / cap))`. The sample draw of such a purchase
   compares its ledger sample value with `ceil(s_ppm * 2^256 / PPM)`. Every
   confirmed failure deducts `b(V*)`; a failure window takes the limit `n *
   k`, with `k` the highest tier limit held from `retentionBlocks` before the
   window opened through the window.

   `setBondTerms(bondId, valueCap, tier)` changes the terms of an active
   account. Leaving a cap or a limit keeps it as the recent peak for
   `retentionBlocks`. The balance must cover one unit bond at the new terms
   (with `V*`) before they apply; the scale is then recomputed from the
   balance, and a drop is kept as the recent scale high of ADR 0022. The new
   terms apply from the transaction that sets them. Rule D2-14 (b) asks for
   `n * k(S) * b(V')`; read with `n` the scale before the change, the
   requirement grows with every top-up at the old cap and can never be met, so
   the contract reads `n` as the scale after the change, which is at least
   one.

Profiles without terms keep the constant `samplePpm`, the floor threshold and
the profile's bucket, penalty and failure limit.

## Consequences

The router keeps every read function of the shared state, and the modules no
longer carry them; this frees the space the new rules need in each module.

Both evaluation profiles keep their hold periods (60,000 and 132,000 blocks),
which remain above the new horizons (31,073 and 93,081). Their
`enforcementBlocks` rise to the new horizons, the settlement bound `S` of the
failure-limit basis falls with the shorter horizon, and with it
`failureLimit` falls from 16 to 14 and from 27 to 24.

## Assumptions and limits

1. **Randomness (D2-16).** The rules require that no payment of an anchored
   epoch is released or refunded before its sampling randomness is on chain.
   The contract still derives the randomness from a block hash that expires
   after 256 blocks, so an anchored epoch whose seal deadline passes still
   becomes `EPOCH_FAILED` and is refunded. Replacing the randomness source is
   outside this record; the test
   `test_D2_16_openGap_anchoredEpochPastItsSealDeadlineIsRefunded` marks the
   difference.
2. **Recent peaks.** A second change while a peak is recorded keeps the higher
   peak and restarts its period. This overstates `V*` and the recent limit for
   at most `retentionBlocks`, which only raises the bond and the deduction.
3. **Raising the cap.** See decision 5: the balance needed is one unit bond at
   the new terms, not the old scale times it.
4. **Receipt deadline.** A receipt that misses its deadline cannot be posted
   late, and a verdict after the deadline no longer clears it; a keeper is
   expected to call `timeoutSampleReceipt` in the first eligible block.
5. **Keeper and Go services.** The keeper does not yet open a sample case on a
   delivered dispute, call `timeoutSampleReceipt`, or post sample receipts.
