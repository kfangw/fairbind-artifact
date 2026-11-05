# ADR 0020: Freeze timing is a profile parameter; minimum judged count before the inconclusive threshold

Status: Accepted 2026-09-28. Amends the amendment of ADR 0012, decision 1
item 1 of ADR 0013, ADR 0015 and the consequence of ADR 0017 on small windows,
in `fairbind-v1.md` sections 5.1, 18, 21.3 and 22, `lifecycle-v1.md`
sections 3, 4 and 10, `profile-v1.md` section 2 and
`contract-interface-v1.md` sections 3, 6 and 10. Adds two fields to
`ServiceProfileInput`, inside `parameterHash`, and re-cuts the pre-deployment
ABI and storage baselines under `test-vectors/deployment/` (precedent: ADR
0013 and ADR 0015).

## Problem 1: the freeze at the initial FAIL stops an honest seller on one verdict

ADR 0012 as implemented freezes the bond account and suspends the seller at the
initial `FAIL`, before any review. The reason given was exposure: between the
initial and the confirmed `FAIL` a failing seller would otherwise keep selling
and entries whose release block passes in that interval would be paid to it.

For an admissible profile the second half of that reason does not hold.
Admission requires `deferBlocks >= retentionBlocks >= caseHorizon`, and
`caseHorizon` bounds the whole case, three review stages and the buyer
recovery procedures included, so every purchase settled since the fraud began
is still held when the failure is confirmed, and the freeze at the confirmed
failure reaches all of it. Only the first half remains: the seller keeps
selling during the review. Under ADR 0018 those sales are not a gain for a
cheating seller either: they land in the frozen window when the failure is
confirmed, are claimable by their buyers, and the confirmed failure costs a
share of the bond.

What the early freeze does cost is borne by the honest seller. A wrongful
initial `FAIL` occurs with probability `u1` per judged case, a wrongful
confirmed one with `u = 2 u1^2` (ADR 0019); at the evaluation values that is
one stop per 25 judged cases against one per 317. Each stop suspends every
sale of the seller for the appeal window and the review, on the say-so of one
verifier, and with ADR 0015 the account stays held until the last pending
initial `FAIL` is decided.

The deferral sweeps of the experiments run profiles whose hold period is below
`caseHorizon`, admitted only by the override build. There the argument above
fails: a confirmed failure can come after entries were released, so those
profiles need the early freeze to bound their exposure at `delta_F`.

## Decision 1: `freezeOnInitialFail`

`ServiceProfileInput` gains `bool freezeOnInitialFail`, part of
`parameterHash`.

1. `false`: an initial `FAIL` neither freezes nor suspends and records no
   pending trigger; `freezeSellerDeferred` reverts for it. The confirmed
   failure freezes, suspends and opens the claim window in one step, so the
   frozen window is the account's unreleased ledger at the confirmed failure,
   including purchases settled between the initial and the confirmed `FAIL`.
   An overturned initial `FAIL` touches nothing.
2. `true`: unchanged behaviour. The initial `FAIL` freezes, suspends and
   records the case as a pending trigger, with the re-anchoring rule of ADR
   0015; the claim window opens at the confirmed failure.
3. Admission. A production build (`_admissionOverride()` false) admits only
   `false`. The admission-override test build admits either, and requires
   `true` when `retentionBlocks < caseHorizon`, because there the confirmed
   failure can come after a release. The evaluation profiles carry `false`;
   the comparison profiles of `contracts/test/repro` and the deferral sweep
   points of the controller carry `true`, and the stateful suite runs both
   (`FAIRBIND_FREEZE_ON_INITIAL_FAIL`).
4. Bounds. `judgmentDelayBlocks` is the delay to the confirmed failure and is
   where the freeze of a production profile lands; `enforcementBlocks >=
   judgmentDelayBlocks` and `B >= g (1/p + Lambda max(0, L - D))` are stated
   for it. `delta_F` of the experiments is the freeze delay only under
   `true`.

The pending-trigger machinery of ADR 0015 stays in the contract and is
exercised only under `true`.

## Problem 2: the first sampled inconclusive of a window freezes on its own

ADR 0017 already notes that in a window with few sampled cases the first
sampled `FINAL(INCONCLUSIVE)` exceeds any threshold `maxInconclusivePpm < PPM`
on its own: one inconclusive out of one judged case is a rate of one. A seller
whose first judged case of a window happens to be unjudgeable is frozen,
suspended and taken through a claim window for a rate estimated from one
sample.

## Decision 2: `minJudgedCount`

`ServiceProfileInput` gains `uint32 minJudgedCount`, part of `parameterHash`,
admitted with `minJudgedCount >= 1`. The threshold test of ADR 0013 decision 2
applies only when the window's judged count, counting the case itself, is at
least `minJudgedCount`; below it a sampled `FINAL(INCONCLUSIVE)` is counted but
never freezes. The evaluation profiles carry 30, a placeholder of about
`6 / theta` at `theta = maxInconclusivePpm / PPM = 0.2`: the threshold cannot
be crossed with fewer than about six inconclusives, so the estimate rests on
at least that many. A value of one restores the old rule.

## Consequences

- An honest seller under a production profile is stopped only by a confirmed
  failure. The sales it makes during a review of a wrongful initial `FAIL`
  are never frozen.
- A cheating seller under a production profile keeps selling for the length
  of the review; those sales are held, claimable and covered by the exposure
  bound, and each confirmed failure costs it a share of the bond.
- The inconclusive freeze needs `minJudgedCount` sampled judgments in the
  window before it can fire. With ADR 0017 counting sampled cases only, a
  window of a low-volume seller may never reach it; the rate limit is then
  inactive for that seller, and its profile should set the count from its
  sampled judged-case rate.
- The struct change moves `parameterHash` and changes the ABI of
  `createServiceProfile` and `getServiceProfile` and the storage layout of
  `profiles`. The contract has not been deployed; the baselines
  `test-vectors/deployment/monolith-abi.json` and `monolith-storage.json` are
  re-cut from the build, as ADR 0013 and ADR 0015 did.

## Properties

- P1: unchanged.
- P2: unchanged for admissible profiles: every purchase settled since the
  fraud began is still held at the confirmed failure, so the frozen window and
  the claim path cover the same purchases whichever timing the profile uses.
  For an override profile below `caseHorizon` the early freeze is required.
- P3: strengthened. A wrongful initial `FAIL` no longer costs an honest seller
  a suspension; only a wrongful confirmed failure does, at `u` rather than
  `u1`. The inconclusive freeze rests on at least `minJudgedCount` samples.
- P4: unchanged.

## Regression

`contracts/test/FairBindFailureCosts.t.sol`:

- `freezeOnInitialFail = false` on the production build: an initial `FAIL`
  leaves the account unfrozen, the seller `ACTIVE` and no trigger pending, and
  `freezeSellerDeferred` reverts; the confirmed failure freezes at that block,
  suspends and opens the claim window, and a purchase settled between the two
  verdicts is claimable from the frozen window (the old rule froze and
  suspended at the initial `FAIL`); an overturned initial `FAIL` changes
  nothing on the account;
- `freezeOnInitialFail = true` on the override build: the initial `FAIL`
  still freezes, suspends and records a pending trigger, and the claim window
  keeps the earlier freeze block;
- admission: the production build rejects `true` and accepts `false`; the
  override build accepts either above the case horizon, rejects `false` below
  it, and both reject `minJudgedCount = 0`;
- `minJudgedCount = 2`: a window whose first judged case is `INCONCLUSIVE`
  does not freeze (the old rule froze), and a later inconclusive above the
  threshold with the count met does.

`contracts/test/invariant/LifecycleObserver.sol` tracks pending triggers and
initial-`FAIL` suspensions only under `true`; the coverage test requires the
overturn of a `FROZEN` account only under `true`, since without the flag an
overturned initial `FAIL` never froze anything; `run.sh` runs the suite under
both settings.
