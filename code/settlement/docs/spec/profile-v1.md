# FairBind Service Profiles Version 1

Status: Release candidate for implementation

A service profile fixes every rule that can affect a purchase. The contract
stores the fields needed for enforcement and commits the complete normative
`parameters` object with `parameterHash`. Creating a new profile does not change
an earlier purchase.

The machine-readable profile stores protocol inputs in a `parameters` object.
It computes:

```text
parameterHash = keccak256(UTF8(JCS(parameters)))
```

`JCS` is the JSON Canonicalization Scheme in RFC 8785. The hash excludes the
profile name, profile ID, analysis notes, deployment addresses outside
`parameters`, and the `parameterHash` field itself. Values wider than the safe
JSON integer range use canonical decimal strings. A `predicateId` commits the
separately versioned predicate definition, while each epoch's `publicationHash`
commits its publication manifest. Calibration notes under `analysis` are
non-normative and are bound to an experiment by the recorded repository
revision, not by `parameterHash`.

The machine document nests deadline fields under `deadlineConfig`. Governance
first creates an identical on-chain `DeadlineConfig`, then supplies its
`deadlineConfigId` with the other flattened fields in `ServiceProfileInput`.
`parameterHash` commits the nested values, not the environment-specific numeric
ID. The contract checks the selected configuration and all profile inequalities
at creation. The deployment token is inherited and does not appear in the
profile parameter object.

Profile and deadline-configuration IDs are nonzero identifiers selected by the
governance creation transaction. They are not auto-increment positions and are
excluded from `parameterHash`. Reusing an existing ID always reverts.

## 1. Units

- block fields count execution-layer blocks;
- probability and rate fields use parts per million with `PPM = 1,000,000`;
- payment, bond, deposit, and penalty fields use atomic units of the deployment
  token;
- response and evidence bounds count bytes;
- for a probability below `PPM`, its threshold is
  `floor(probabilityPpm * 2^256 / PPM)`;
- probability `0` is never selected and probability `PPM` is always selected,
  avoiding an unrepresentable `2^256` threshold.

One settlement consumes one token bucket unit. The bucket stores parts per
million of a unit so a profile can refill at less than one settlement per block.
`bucketCapacity`, `refillPpmPerBlock`, and `maxRatePpmPerBlock` are values per
unit of `sellerPenalty`. A bond account of balance `B` uses them multiplied by
`scaleFactor = floor(B / sellerPenalty)`; the bucket belongs to the bond
account, not to a seller registration. `bucketCapacity` is taken from the
measured per-class peak one-hour settlement distribution, not from a window
average, and `bucketCapacityPercentilePpm` records the percentile used (default
the ninety-ninth, `990000`); it is part of the parameter object and therefore of
`parameterHash`, not an on-chain field. Rejection frequency at that capacity is
a reported limitation.
Version 1 rejects a purchase above `maxPurchaseValue`. A service that needs a
wider price range uses separate profiles.

## 2. Structural validation

Profile creation enforces:

```text
classId in {DATA_API, OPEN_WEIGHTS_INFERENCE}
predicateId != 0
canonId != 0
canonicalHeaders are unique, lowercase, and strictly ASCII-sorted
epochBlocks > 0
anchorBlocks > 0
openBlocks > 0
responseBlocks > 0
claimBlocks > 0
serveBlocks > 0
judgeBlocks > 0
evidenceBlocks > 0
appealBlocks > 0
0 < samplePpm <= PPM
0 < effectivePpm <= samplePpm
0 <= recheckPpm <= PPM
0 < sealBlocks <= 255
bucketCapacity > 0
refillPpmPerBlock <= maxRatePpmPerBlock
enforcementBlocks >= judgmentDelayBlocks        (section 3)
maxPurchaseValue > 0
maxBadGain > 0
sellerPenalty > 0
maxPublicationCost > 0
maxReviewCost > 0
maxRequestBytes > 0
disputeDeposit >= maxPublicationCost
appealDeposit >= maxReviewCost
verifierWrongPenalty >= maxReviewCost
ceil(maxResponseBytes / 16384) + 2 <= serveBlocks
0 < verifierExposurePpm <= PPM
0 < maxAssignments <= 3
minVerifiers >= 3 * maxAssignments + 5         (section 5)
strikeLimit > 0
deferBlocks >= retentionBlocks
responseBlocks <= epochBlocks + anchorBlocks
caseHorizon >= judgmentDelayBlocks
claimWindowBlocks == retentionBlocks
beaconDelayBlocks >= 768                        (128 L1 blocks of 12 s on a 2 s chain)
beaconSlackL1Blocks == 0                        (chain without an L1 origin)
failureLimit > 0
failureWindowBlocks > 0
0 < maxInconclusivePpm <= PPM
inconclusiveWindowBlocks > 0
0 <= forfeitVerifierPpm <= PPM
minJudgedCount >= 1
freezeOnInitialFail == false                    (production build; see below)
0 < bucketCapacityPercentilePpm <= PPM          (off chain)
```

The default values are `beaconDelayBlocks = 768` (128 L1 blocks of twelve
seconds on a two-second chain, which is also the admission floor), `beaconSlackL1Blocks = 0`, `claimWindowBlocks =
retentionBlocks`, `failureWindowBlocks = inconclusiveWindowBlocks =
retentionBlocks`, and `forfeitVerifierPpm = 500000`.
`forfeitVerifierPpm` is kept in the profile and its encoding and is still
range-checked, but has no effect since ADR 0022: forfeitures are locked in
the contract. `failureLimit` has no fixed default; section 4 derives it per
profile. `maxInconclusivePpm` has no default until natural inconclusive
rates are measured on sampled cases, the only cases the rate counts (ADR 0017);
the evaluation profiles carry a recorded placeholder.
`claimWindowBlocks` is the frozen-pool claim window; it is distinct from
`claimBlocks`, the buyer's dispute-opening period. `minJudgedCount` is the
number of sampled judged cases a window must hold before the inconclusive
threshold can freeze the account (ADR 0020); the evaluation profiles carry 30,
about `6 / theta` at `theta = maxInconclusivePpm / PPM = 0.2`, a placeholder
like the threshold itself. `freezeOnInitialFail` selects whether an initial
`FAIL` freezes and suspends; a production profile freezes at the confirmed
failure.

Every production build enforces all of these rules. The internal hook
`_admissionOverride()` returns false in production; only the test build
`contracts/test/AdmissionOverrideRegistry.sol`, used for deferral sweeps in local
experiments, returns true, and it then skips exactly `retentionBlocks >=
caseHorizon` (section 3, and with it `deferBlocks >= caseHorizon`),
`deferBlocks >= retentionBlocks`, `enforcementBlocks >= judgmentDelayBlocks`
and `freezeOnInitialFail == false`; it admits either freeze timing and
requires `freezeOnInitialFail == true` when `retentionBlocks < caseHorizon`,
where a confirmed failure can come after a release. A profile admitted only by
that build is inadmissible and its results are reported as such.

The profile also enforces the rate condition without division:

```text
bucketCapacity * PPM
  + refillPpmPerBlock * enforcementBlocks
  <= maxRatePpmPerBlock * enforcementBlocks
```

All products use a checked width of at least 128 bits. The three quantities are
per unit of `sellerPenalty`, so the inequality is homogeneous in the scale
factor: once admitted, it holds for every bond account of the profile.
The publication inequality budgets one block for `beginPublication`, one per
response chunk, and one for `finalizePublication`. It is deliberately
conservative; several transactions may share a block.

`canonicalHeaders` is normative but off chain. A buyer checks that the array
advertised in x402 equals the array in the parameter object whose hash is stored
on chain. The contract needs only the resulting `requestHash` and therefore
stores the array through `parameterHash` rather than a dynamic on-chain field.

## 3. Retention and deferral

The latest case opening is (ADR 0024):

```text
sampledOpen = 2 * epochBlocks + anchorBlocks + beaconDelayBlocks + sealBlocks + openBlocks
claimedOpen = responseBlocks + claimBlocks
openHorizon = max(sampledOpen, claimedOpen, min(sampledOpen, claimedOpen) + 3 * serveBlocks)
```

The last term is a sample case opened on a purchase whose buyer non-delivery
dispute ended as delivered: the dispute opens at the latest at the earlier of
the claim deadline and the sample-open deadline, and its serve procedure takes
at most three serve windows.

The judgment delay `L` is the longest path from a settlement to the end of its
case, and so to the block at which a confirmed failure freezes the account:

```text
m = maxAssignments
judgmentDelayBlocks = openHorizon
  + 3 * m * (2 * judgeBlocks + 3 * serveBlocks)
  + m * (appealBlocks + evidenceBlocks) + appealBlocks
  + 3 * (m - 1)
  + 2 * (2 * sealBlocks + 3)
  + 1
```

Each of the three judgment stages can use `m` assignments, each with a full
serve procedure (serve, challenge, publication) and a renewed judge window; the
initial stage adds one evidence window and one renewed appeal window per
assignment and the final appeal window; each replaced assignment costs one
block; each of the two review seals can lapse once and reopen (ADR 0021); and a
stalled seller-appealed review upholds the initial `FAIL` one block after its
last judge deadline (ADR 0024). The value equals the longest path `L_F = L_any`
that lemma C of the design 2 analysis enumerates from the contract with every
actor at the last admitted block and every deadline-free call in the first
block it is valid, and `contracts/test/WorstPathLength.t.sol` drives it on the
contract. The sample receipt deadline runs alongside the first judgment window
and adds nothing. The contract exposes the value as
`judgmentDelayBlocks(profileId)`.

The case horizon is the longest path plus the keeper margin:

```text
caseHorizon = judgmentDelayBlocks + marginBlocks
```

`marginBlocks` bounds the total delay of the deadline-free public calls on a
case path (`kappa_Sigma`). Because a release is allowed in the block in which it
becomes valid, a margin of 500 blocks covers `kappa_Sigma <= 499`.

The data API reference profile gives `openHorizon = 2,760`,
`judgmentDelayBlocks = 30,573` and, with `marginBlocks = 500`,
`caseHorizon = 31,073`; the open-weights profile gives 5,768, 92,081 and,
with `marginBlocks = 1,000`, 93,081. The evaluation profiles keep
`deferBlocks`, `retentionBlocks`, `claimWindowBlocks`, `failureWindowBlocks`
and `inconclusiveWindowBlocks` at 60,000 and 132,000, which exceed these
horizons; a design 2 profile sets all five to `caseHorizon` (31,073 on the
reference case).

The normative parameter object records `marginBlocks`; non-normative analysis
notes explain its calibration. Profile admission requires `retentionBlocks >=
caseHorizon`, `deferBlocks >= retentionBlocks` and `enforcementBlocks >=
judgmentDelayBlocks`. An implementation may use a tighter machine-checked
state bound, but it must include every numeric input to that derivation in
`parameterHash` and preserve P2. At the moment a failure is final nothing sold
in the exposure window has been released, and the freeze of `fairbind-v1.md`
section 18 reaches all of it.

## 4. Effective detection and seller penalty

The profile records raw sampling probability separately from effective detection
probability. With conditional honest verifier share `h` and false acceptance
rate `beta`, the conservative lower bound is:

```text
effectivePpm / PPM
  <= samplePpm / PPM * a1 * a2 * e * (h * (1 - beta))^2
```

Here `a1` and `a2` lower-bound successful eligible assignment on the relevant conditional histories after all exclusions and reserved capital; `e` lower-bounds timely enforcement. These are history-uniform assumptions, not pooled averages. The simpler squared term applies only when these three factors are one. The wrong-initial-verifier P4 path has its own recheck probability and is not this seller-detection bound.

The profile document records measured or assumed `h`, `beta`, the confidence
interval, dataset, software revision, and sample count. The contract does not
recompute this empirical bound.

For expected-loss sizing, define:

```text
expectedDetectionCount = ceil(PPM / effectivePpm)
postDetectionCount = ceil(maxRatePpmPerBlock * max(0, judgmentDelayBlocks - deferBlocks) / PPM)
expectedPenaltyFloor = maxBadGain
  * (expectedDetectionCount + postDetectionCount)
```

This is the `kappa_Sigma = 0` case of the bond requirement
`B >= g * (1/p + r_max * max(0, T_catch + kappa_Sigma - T_hold))` per unit of
`sellerPenalty`, with `r_max = maxRatePpmPerBlock / PPM` a parameter of the
bond account, `T_catch = judgmentDelayBlocks`, `T_hold = deferBlocks` and
`kappa_Sigma` the sum of keeper delays on the path to the confirmed failure
(`penalty_floor` in `experiments/controller/profile.py` takes it as
`keeper_delay_sum`, default 0). With `deferBlocks >= judgmentDelayBlocks +
kappa_Sigma` the second term is zero and the requirement no longer depends on
the settlement rate.

The profile MUST set `sellerPenalty >= expectedPenaltyFloor`. A deployment that
claims a high-probability bound also records a failure probability `delta`,
computes the geometric-tail count from the research proof, and sets the penalty
no lower than that larger bound. All ceiling operations round against the
seller.

The contract reserves `sellerPenalty` per unit of scale factor in each bond
account and charges it through confirmed failures: `sellerPenalty /
failureLimit` on each counted failure and the remainder on the failure that
brings the count within the failure window to its threshold, so that one
window charges exactly its threshold's worth (ADR 0018). A failure window
of scale `n` (at least one) has the threshold `n * failureLimit` and charges
`n * sellerPenalty` (ADR 0021). `n` is the larger of the scale factor before
the opening failure's deduction and the highest scale the account left
through a drop within the preceding `retentionBlocks` (at least `caseHorizon`,
which includes the keeper margin), and a top-up that raises the scale factor during the window
raises `n` (ADR 0022). Deductions stay locked in the contract. Bond above
that value may cover only the exceptional shortfall rule in the profile.

`failureLimit` bounds the probability that an honest seller is wrongly
sanctioned within one failure window. It uses an explicit review model. A
verifier errs against an honest seller either because it is non-honest and
votes to convict, or because it is honest and the predicate falsely rejects:

```text
w1 = max(c, alpha) * (1 - h) + h * alpha
```

where `alpha` is the predicate false rejection rate, `h` the same conditional
honest verifier share used for detection above, and `c` the conviction
collusion share: the fraction of non-honest verifier weight that votes `FAIL`
against an honest seller. `c = 1` is the worst case, in which every non-honest
verifier convicts every honest seller it is assigned. `c * (1 - h) + h *
alpha` is an upper bound on one verifier's error only when `c >= alpha`: a
non-honest verifier that does not collude still runs the predicate and errs at
`alpha`, so `c` is replaced by `max(c, alpha)`, which matters only for the
`c = 0` row below.

A wrongful confirmed failure needs two independently drawn verifiers to err,
on every path (ADR 0019). Per judged case, with `s_re = recheckPpm / PPM`:

- an initial `FAIL`, appealed by the seller, confirmed by the party-review
  verifier drawn excluding the first: `w1^2`;
- the same initial `FAIL` overturned by the party reviewer and confirmed by
  the tiebreak the disagreement leads to: `w1 * (1 - w1) * w1 <= w1^2` (ADR
  0021; ADR 0019 omitted this path);
- an initial `PASS` appealed by an adversarial buyer with probability `b_a`,
  taken as one (`buyerAppealsEveryPass`), flipped by the party reviewer and
  confirmed by the tiebreak: the correct initial `PASS` is bounded by one, and
  the party reviewer and the third verifier each err with probability at most
  `w1`, so the path has `b_a * w1^2`;
- an initial `PASS` not appealed, automatically rechecked with probability
  `s_re`, flipped and confirmed by the tiebreak: `(1 - b_a) * s_re * w1^2`.

```text
u = w1^2 * (2 + b_a + (1 - b_a) * s_re) = 3 * w1^2   at b_a = 1
```

`failureLimitBasis.recheckPathIncluded`, `buyerAppealsEveryPass` and
`tiebreakOnPartyReview` record that these paths are present.

`c` enters only `failureLimit`. The detection bound earlier in this section keeps
the worst case against the buyer: it assumes that all non-honest weight
colludes with a cheating seller. The two assumptions are not in tension. A
coalition that shields a cheating seller gains from that seller's revenue; a
coalition that convicts an honest seller gains nothing directly, pays the
wrong-verdict penalty when the seller wins on review, and must be drawn twice
in a row for the same case. `c` is a stated assumption, not a measurement, and
the profile records it as `convictionCollusionPpm`.

Each settlement is judged with probability `pi = samplePpm / PPM`, so it
becomes a wrongful confirmed failure with probability `q = pi * u`. The
failure counter runs over a fixed window of `W = failureWindowBlocks`; a
confirmed failure inside `[w, w + W]` can come from a case opened on a
settlement up to `caseHorizon` blocks before `w`, so the settlements that can
contribute are those in `[w - caseHorizon, w + W]`, bounded from the rate
fields at scale factor one:

```text
S = ceil(bucketCapacity
  + refillPpmPerBlock * (failureWindowBlocks + caseHorizon) / PPM)
```

and `failureLimit` is the least `k` with `C(S, k) * q^k <= 10^-6`, a union
bound on the binomial tail `P[X >= k]`. A bond account with scale factor `n`
settles up to `n` times as many purchases; the contract therefore sanctions a
failure window of scale `n` only at `n * failureLimit` failures (ADR 0021).
The settlements that can fail within a window starting at `w` come from `[w -
caseHorizon, w + W]`, so `n` must cover the scale over that whole range: the
contract opens the window at the highest scale the account held within
`retentionBlocks >= caseHorizon` before `w` (read before the opening failure's
deduction) and raises it with a top-up during the window (ADR 0022). An
account that settles at scale two and is deducted to one would otherwise face
`P[Bin(2S, q) >= k]`, about 270 times the target. By the Chernoff bound `P[Bin(nS, q) >= nk] <= (exp(-S *
D(k/S || q)))^n` the per-window probability does not grow with `n`
(`exp(-S * D)` is `4.6e-07` and `6.3e-09` at the evaluation values). Buyer-opened
disputes are not counted in `S`, and a dispute gets the same two-verifier
bound. The profile analysis records every input, `c`, `w1`
(`initialWrongFailPpm`), `u`, `S`, the resulting bound and the exact binomial
tail in `failureLimitBasis`, marked unmeasured, and `scripts/check_spec.py`
recomputes `failureLimit`, the bound and the tail from them in exact
rationals, reading `recheckPpm` and `samplePpm`.

At the evaluation values `c = 0.1`, `h = 0.67` (both assumptions, not
measurements), `alpha = 0.01`, `s_re = recheckPpm / PPM = 0.2` and
`pi = 0.1`, `w1 = 0.033 + 0.0067 = 0.0397`, `u = 3 * 0.0397^2 = 0.00472827`
(`wrongFinalFailPpm = 4729`) and `q = 0.000472827`. The data API profile has
`S = 4,574` settlements per 60,000-block window plus its 31,073-block case
horizon and `failureLimit = 14` (union bound `5.51e-07`, exact tail
`7.43e-08`); the open-weights profile has `S = 11,275` per 132,000-block window
plus its 93,081-block horizon and `failureLimit = 24` (union bound
`4.37e-07`, exact tail `2.71e-09`). The exact tail alone would satisfy the
target at `k = 13` and `k = 20`, so the union bound costs 1 and 4 steps.
With `b_a = 0` (no adversarial buyer appeals) the limits are 12 and 20. The
expected number of wrongful confirmed failures per window is `S * q`, about
2.16 and 5.33, and each one suspends the seller, opens the claim window on its
frozen pool and deducts `sellerPenalty / failureLimit` from its bond (ADR
0018). Over a year of two-second blocks, 262.8 and 119.5 windows, the
honest-seller terminal-sanction probability at scale factor one is at most
`1.45e-04` and `5.22e-05` by the union bound (`1.95e-05` and `3.23e-07` by the
exact tail). The settlement bounds use the case horizon of ADR 0024; before it
they were 5,970 and 13,147, with limits 16 and 27.

Sensitivity to `c`, with `h = 0.67`, `alpha = 0.01`, `s_re = 0.2`, `b_a = 1`
and `pi = 0.1` fixed, at the current horizons and hold periods. `k_union` is
the profile rule; `k_exact` is the least `k` whose exact binomial tail is at
most `10^-6` (computed with log-gamma floating-point sums, which agree with
the exact rationals at the profile values); `S * q` is the expected number of
wrongful confirmed failures per window. The `c = 0` row uses `max(c, alpha) =
alpha`, since `c * (1 - h) + h * alpha` bounds a verifier's error only for `c
>= alpha`.

| `c` | `w1` | `u` | data API `S * q` | data API `k_union` / `k_exact` | open-weights `S * q` | open-weights `k_union` / `k_exact` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.3367 | 0.340101 | 155.56 | 414 / 218 | 383.46 | 1005 / 479 |
| 0.5 | 0.1717 | 0.088443 | 40.45 | 119 / 75 | 99.72 | 278 / 151 |
| 0.2 | 0.0727 | 0.015856 | 7.25 | 29 / 24 | 17.88 | 59 / 42 |
| 0.1 | 0.0397 | 0.004728 | 2.16 | 14 / 13 | 5.33 | 24 / 20 |
| 0.05 | 0.0232 | 0.001615 | 0.74 | 9 / 9 | 1.82 | 13 / 12 |
| 0 | 0.0100 | 0.000300 | 0.14 | 5 / 5 | 0.34 | 7 / 7 |

A deployment that cannot defend `c` well below one must take the larger limit
from this table, and accepts that a limit in the tens or hundreds lets a
cheating seller absorb correspondingly many confirmed failures before the
sanction; each of them still suspends, freezes and costs one share of the
penalty.

## 5. Verifier capital

Assignment weight is:

```text
effectiveWeight = min(verifierBond, verifierBondCap)
```

An assignment is eligible only when the verifier bond is at least
`minVerifierBond` and the new liability would satisfy:

```text
newReserve = max(verifierLatePenalty, verifierWrongPenalty)
postPenaltyBond = verifierBond - reservedPenalties - newReserve
newCap = min(activeConservativeCap, verifierBondCap)
newFraction = min(activeConservativeFraction, verifierExposurePpm)
lockedLiability + purchaseValue + maxReviewCost
  <= min(postPenaltyBond, newCap) * newFraction / PPM
```

`maxReviewCost` bounds review calldata, the profile's gas-price policy, and
service-class compute cost. `verifierLatePenalty` covers at least one replacement.
`verifierWrongPenalty` and `appealDeposit` each cover at least `maxReviewCost`.

### 5.1 Verifier count

One case can use `3 * maxAssignments` distinct verifiers: `maxAssignments`
attempts in each of the initial stage, the review stage and the tiebreak, each
excluding every verifier already in the case. One assignment search tries
`minVerifiers` independent weighted draws over the epoch's checkpoint of `N >=
minVerifiers` verifiers (`sortition-v1.md` section 4). With equal weights, the
search for the last assignment of such a case, facing `k = 3 * maxAssignments -
1` excluded verifiers, finds nobody with probability

```text
P_last = (k / N)^minVerifiers <= (k / minVerifiers)^minVerifiers
```

and the case ends as a protocol `INCONCLUSIVE`. The admission margin 5 is the
smallest constant for which `P_last <= 10^-3` at `N = minVerifiers` for every
`maxAssignments` in `1..3` (ADR 0023): at `maxAssignments = 3` the least
admissible count 14 gives `P_last = (8/14)^14 = 3.96e-4`, and 13 would give
`1.82e-3`. `experiments/verifier_count.py` reproduces the computation. The bound
assumes equal checkpoint weights and verifiers otherwise eligible; a verifier
skipped for liability, removal or bond lowers the effective `N`.

## 6. Deposits

`maxPublicationCost` bounds the on-chain fallback at `maxRequestBytes` and
`maxResponseBytes` under the profile gas-price policy. `disputeDeposit` is at
least that amount.
`appealDeposit` covers bounded review and delay costs. A profile cannot rely on
a deposit to fund purchase-principal refunds. The experiment reports deposit
adequacy under the measured gas-price distribution.

## 7. Initial evaluation profiles

[`../../profiles/local-evaluation-v1.json`](../../profiles/local-evaluation-v1.json)
contains two functional profiles:

- `data-api-fast-v1`, with a 300-block epoch and a 600-block judgment window;
- `open-weights-standard-v1`, with a 1,800-block epoch and a 3,600-block
  judgment window.

Both use a 10 percent raw sampling rate, an 1,800-block appeal window, a 20 percent automatic recheck rate, three assignment attempts per
stage, fourteen minimum eligible verifiers (section 5.1), a bounded settlement rate, and finite
response and evidence sizes; both freeze at the confirmed failure
(`freezeOnInitialFail = false`), require 30 sampled judged cases before the
inconclusive threshold applies, and carry failure limits of 14 and 24 per unit
of scale factor with hold periods of 60,000 and 132,000 blocks. Their
economic values use a six-decimal mock token.

These values support deterministic local and public-testnet experiments. They do
not support a production security claim. A paper result MUST record measured
`h`, false rejection and acceptance rates, effective detection, enforcement
delay, gas cost, and the resolved profile hash.

## 8. Production admission

Mainnet profile activation remains disabled until the repository contains:

- measured predicate error rates with confidence intervals;
- a verifier composition and conditional honest-share analysis;
- an enforcement-delay distribution under faults;
- gas and publication-cost bounds;
- expected and high-probability seller penalty calculations;
- an independent contract security review;
- a deployment-specific governance and incident-response record.

ADR 0009: subtraction must be feasible before admission. When no liability is open,
the current profile initializes the conservative cap/fraction. The envelope may
remain stricter until all liabilities close, then resets. Penalties use only their
own reservation and release unused reservation on void/finalization. Liability is
retained after a signed verdict until the case is resolved. minVerifierBond is
checked again at assignment. A verifier exit also requires zero reserved penalties.
The horizon budgets both the initial and post-serve judgment window per attempt,
one evidence window and two appeal windows per attempt conservatively. Public
progress requires the bounded keeper availability assumption; marginBlocks must
cover its documented total cumulative delay over the whole case, not merely one keeper call. No indefinite keeper absence is covered by a finite
retention bound. Positive maxBadGain, maxPublicationCost, maxReviewCost and both
verifier penalties, the seller penalty floor and publication/response inequalities
are enforced at creation.

The initial functional profiles explicitly set conditionalDetectionBoundEstablished=false.
Their effectivePpm is an unvalidated design input used to exercise accounting,
not an established protection guarantee. check_spec checks only an idealized
necessary ceiling based on h and beta; it cannot validate the conditional a1, a2,
or e assumptions. Production admission and empirical protection claims remain
blocked until those bounds are justified.

## 9. Value-proportional sampling and seller-chosen terms (ADR 0024)

A profile may carry design 2 terms, fixed once by governance before
activation (`setProfileTerms`): the detection floor `p0` (`detectFloorPpm`),
the value caps a seller may choose, and the sales tiers. Each tier is a sales
limit `S`, a bucket capacity `q_S`, a refill rate `r_S` (ppm per block) and a
failure limit `k_S`. Admission requires:

```text
samplePpm == PPM and effectivePpm == detectFloorPpm
valueCaps strictly increasing, valueCaps[last] == maxPurchaseValue >= maxBadGain
tiers strictly increasing in S, q_S >= 1, k_S >= 1, r_S <= maxRatePpmPerBlock
q_S * PPM + r_S * (failureWindowBlocks + caseHorizon) <= S * PPM   for every tier
last tier: (q, r, k) == (bucketCapacity, refillPpmPerBlock, failureLimit)
sellerPenalty / failureLimit >= b(valueCaps[last])
```

with `b(v) = ceil(40 * v * PPM / (27 * detectFloorPpm))`, the deduction of one
confirmed failure (design 2 rule D2-5). The interval `failureWindowBlocks +
caseHorizon` holds every settlement that can produce a confirmed failure
inside one failure window, so `S` is the largest number a tier's bucket admits
there. The reference tiers at `failureWindowBlocks = caseHorizon = 31,073`
(interval 62,146 blocks) meet the inequality with `ceil(q_S + r_S * 62,146 /
PPM) = S`:

| `S` | `q_S` | `r_S` | `k_S` (w = 0.015) | `k_S` (w = 0.004728) |
| --- | --- | --- | --- | --- |
| 10 | 1 | 144 | 5 | 4 |
| 30 | 1 | 466 | 7 | 5 |
| 100 | 4 | 1,544 | 11 | 8 |
| 300 | 13 | 4,618 | 19 | 11 |
| 1,000 | 42 | 15,415 | 38 | 20 |
| 3,245 (base) | 137 | 50,000 | 87 | 39 |

`k_S` is the least `k` with `P[Bin(S, w) >= k] <= 5 * 10^-7`, every
settlement of an honest seller assumed sampled; the contract does not
recompute it.

A bond account under such a profile records its value cap `vmax` and tier. Its
unit bond is `B = k_S * b(V*)`, where `V*` is the highest cap it held within
the last `retentionBlocks`; only the base tier scales with the balance, a
smaller tier holds at most one unit. A settlement above the current cap is
refused before the bucket is read. A settlement records
`s_ppm = min(PPM, ceil(v * PPM / vmax))` with the cap in force, and the sample
draw compares its ledger sample value with `ceil(s_ppm * 2^256 / PPM)`, or
selects it without a comparison at `s_ppm = PPM`. Every confirmed failure
deducts `b(V*)`; a failure window at scale `n` sanctions at `n * k`, where `k`
is the highest tier limit the account held from `retentionBlocks` before the
window opened through the window.

Changing the terms (`setBondTerms`): leaving a cap or a limit keeps it as the
recent peak for `retentionBlocks`; the balance must cover one unit bond at the
new terms before they apply, the scale is recomputed from the balance and a
drop is kept as the recent scale high (ADR 0022). The new terms apply from the
transaction that sets them.


### 9.1 Commitment and first activation (ADR 0025)

The terms are part of the normative parameters: the profile document carries
them in `parameters.designTwoTerms` (`detectFloorPpm`, `valueCaps`, `tiers`)
together with

```text
termsHash = keccak256(abi.encode(
  keccak256("fairbind/profile-terms/v1"),
  uint32(detectFloorPpm),
  uint96[](valueCaps),
  SalesTier[](tiers)))        // SalesTier = (uint32 S, uint32 q_S, uint32 r_S, uint32 k_S)
```

so `parameterHash` commits them. `setProfileTerms(profileId, termsHash,
detectFloorPpm, valueCaps, tiers)` reverts unless the terms reproduce
`termsHash`, stores it, and reverts for a profile that has ever been active:
an account opened without terms must never be read as a tiered account. Under
terms `failureWindowBlocks = inconclusiveWindowBlocks = retentionBlocks`
(design 2 rule D2-9). The bond terms field holding `vmax` is
`sampleScaleValue`.

`profiles/design2-v1.json` holds the two reference documents, data API
(`retentionBlocks = 31,073`, tier interval 62,146 blocks, the table above) and
inference (`retentionBlocks = 92,581`, interval 185,162 blocks). The design 2
rules give no inference tier table; that document keeps the data API sales
limits and their `k_S` and derives every tier, the base tier included, from
`r_S = floor((S - q_S) * PPM / 185,162)`: refill rates 48, 156, 518, 1,549,
5,173 and 16,785. `scripts/check_spec.py` recomputes `termsHash`,
`parameterHash` and the tier inequality of both.
