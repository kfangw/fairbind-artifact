# Fault and attack scenarios

Each file defines one scenario read by `experiments/controller`. The table below
states what each scenario checks without reading code. Files are English-only
ASCII and use the block YAML subset that `controller/yamlsubset.py` parses when
PyYAML is not installed.

## Schema

| Field | Content |
| --- | --- |
| `id` | Scenario identifier; equals the file name. |
| `name` | Short title. |
| `property_under_test` | Property codes (below). |
| `preconditions` | Free-text setup statements. |
| `injected_fault` | `process` (one of `buyer`, `seller`, `facilitator`, `verifier`, `keeper`, `anvil`, or a list), `kind` (fault code, below), optional `trigger` and `target`, and free-text `action` and `timing`. |
| `parameters` | Each entry has `default`, an optional `sweep` list and an optional `unit`. |
| `n_seeds` | Runs per sweep point, each with its own seed (see Randomness). |
| `observed_metrics` | `core` (14 fixed metrics), `extended` (11 fixed metrics) and an optional `scenario_specific` list; every id is defined in [`../metrics.md`](../metrics.md) with its formula, unit and source. |
| `expected_outcome` | A falsifiable statement of the expected result. |
| `ground_truth_source` | The same in every file: the controller keeps ground truth outside the runtime processes. |
| `pass_criteria` | Condition applied by the analysis, not by the controller. |
| `notes` | Context for the reader. |

Symbolic parameter defaults: `profile_default` keeps the profile value;
`profile_judgment_delay` is `judgmentDelayBlocks` computed from the profile
(`docs/spec/profile-v1.md` section 3); `profile_penalty_floor` is
`expectedPenaltyFloor` (section 4) for the resolved deferral; expressions such
as `L/2` or `2*L` use the resolved judgment delay `L`. The hold-period grid
names (`T_min`, `T_stop`, `T_catch`, `T_case`, `T_hold`) and `keeper_margin`
are defined in Hold-period grid (I6) below. Any other string (for example
`empirical_seller_rate`) must be supplied at run time with `--set`.

## Randomness

The harness is deterministic apart from the seed. The chain starts from the
same genesis, the controller writes the same directives, and a purchase is
sampled when `keccak256(sample domain, epochRandomness, sellerId, epoch,
nonce)` falls below the threshold, with `epochRandomness` the hash of a fixed
later block. Without a seed the same workload yields the same nonces and the
same block hashes, so repeating a run repeats the same sample draws: it is not
variance.

A seed changes exactly two inputs (`SEED_EFFECTS` in
`controller/runner.py`, copied into every buyer directive and every result
envelope):

- the buyer idempotency key `k` of each purchase, which enters the purchase
  `nonce` and so the sample test of that purchase;
- the order of the buyer's settlements inside each block, which changes the
  block hashes and so the epoch randomness.

Fault timing, verdict timing, rates and deadlines do not depend on the seed.
Each point runs `n_seeds` times with seeds derived from `--seed`, the
scenario id, the point and the repetition; `--repetitions N` overrides
`n_seeds` for every scenario. Every envelope records `randomness` (seed,
repetition, `n_seeds`, the seed effects) and `detection`: the profile's
expected `p` and `pi` beside `realized_detection_rate` and
`realized_sample_rate` of that run (null when the run reported none).

How `n_seeds` was chosen:

| n_seeds | Scenarios | Reason |
| --- | --- | --- |
| 3 | F1 to F4, S1 to S4, V1, A1, K1, R2 | fixed procedures (timeouts, restarts, redelivery, anchoring, refund paths); the repeats only expose a harness that is not deterministic |
| 10 | S5, D5, H1, I2, K2 | counts and fractions over many sales in one run (burst bound, window, suspended fraction, inconclusive ratio, escaped epochs); the seed moves which purchases are sampled |
| 30 | D1, D2, E1, S6, V2, V3, A2, C1, I1 | a per-run condition (released exposure versus the realized freeze delay, recheck and appeal outcomes, episodes) plus a mean or a frequency; for A2 each run makes `dispute_count` disputes, so at 1,000 disputes and weight 0.1 about 22 standing FAILs are expected per run |
| per cell | I6 | each cell carries its own count (`cells.<name>.repetitions`): 100 at the admissible low-rate cells and the worst-path cells M4-worst, P5-margin and P6, 30 at the other cheater cells and the positive controls, 10 in the honest arm; `n_seeds` (30) applies only when `cells` is absent; the pruning rule never takes a low-rate cell below 60 |
| 100 | D3 | the slow point's released exposure is about g times a geometric count with mean 1/p = 25 and standard deviation about 24.5; with 100 seeds the 95 percent interval half-width is about 4.8 g (19 percent of g/p), so criterion (1) detects only a violation larger than about 5 g; halving the width needs four times the seeds |

## Property codes

| Code | Property |
| --- | --- |
| P1 | A purchase is paid at most once. |
| P2 | A paying buyer receives the response or a refund. |
| P3 | An honest seller keeps its payment. |
| P4 | Verifiers are accountable for late and wrong verdicts. |
| P5 | A rate-optimizing seller is deterred. |
| T5 | With deferral `D >= L`, a bond of `g/p` deters without a rate cap. |
| T6 | With `D < L`, no fixed bond deters without a rate cap. |
| EXPOSURE | Exposure of one bond account stays within `g(1/p + Lambda (L - D)+)`. |

`g` is `maxBadGain`, `p` the effective detection probability, `Lambda` the
settlement rate and `L` the judgment delay in blocks.

## Scenarios

| id | Name | Properties | Fault process | Fault kind | n_seeds |
| --- | --- | --- | --- | --- | --- |
| A1 | Buyer false non-delivery claim | P3 | buyer | `false_non_delivery_claim` | 3 |
| A2 | Buyer and colluding verifier on a false WRONG_DELIVERY | P3, P4 | buyer, verifier | `false_wrong_delivery_collusion` | 30 |
| C1 | Cheater re-enters after suspension and repeats | P5, T5 | seller | `reentering_cheater` | 30 |
| D1 | Deferral grid, fast cheater, cap on and off | T5, T6, EXPOSURE | seller | `calculating_cheater` | 30 |
| D2 | Deferral grid near the freeze delay, slow and fast verifier | T6, EXPOSURE | seller, verifier | `calculating_cheater` | 30 |
| D3 | Deferral at or above L with the cap off: slow cheater, bond levels and g below v | T5, EXPOSURE | seller | `calculating_cheater` | 100 |
| D5 | Fixed challenge window baseline, judgment delay sweep | T6 | seller | `calculating_cheater` | 10 |
| E1 | Honest seller release delay under a false FAIL | P3 | verifier | `wrong_verdict` | 30 |
| F1 | Facilitator stops right after broadcast | P1 | facilitator | `process_restart` | 3 |
| F2 | Response lost | P1 | buyer | `drop_response` | 3 |
| F3 | Seller restart | P1, P2 | seller | `process_restart` | 3 |
| F4 | Settled but no response | P2 | seller | `withhold_response` | 3 |
| H1 | Honest high-rate seller: suspended fraction and delay | P3 | seller, verifier | `honest_high_rate` | 10 |
| I1 | Verifier always INCONCLUSIVE | P4, P5 | seller, verifier | `verifier_always_inconclusive` | 30 |
| I2 | Above-threshold FINAL(INCONCLUSIVE) path for an honest seller | P3 | seller | `natural_inconclusive` | 10 |
| I6 | Hold-period grid: exposure, net gain and honest sanctions across T_hold, bond, rate, scale and keeper delay | T5, T6, EXPOSURE, P3 | seller, keeper | `hold_period_grid` | per cell (10 to 100) |
| K1 | All keepers down | P2, P5 | keeper | `keeper_outage` | 3 |
| K2 | Seal window missed on purpose | P5 | seller, keeper | `seal_withholding` | 10 |
| R2 | Double refund attempts across the three refund paths | P2 | buyer | `double_refund_attempt` | 3 |
| S1 | Anchor omits a receipt | P2 | seller | `omit_receipt_from_anchor` | 3 |
| S2 | Anchor withheld | P2 | seller | `withhold_anchor` | 3 |
| S3 | Redelivery refused | P2 | seller | `refuse_redelivery` | 3 |
| S4 | Response held until the epoch boundary | P5, EXPOSURE | seller | `delay_response` | 3 |
| S5 | Burst at up to 100 times the normal rate, admissible profile | P2, P5, EXPOSURE | seller | `burst_rate` | 10 |
| S6 | Patient defection after a long honest period | P2, P5, EXPOSURE | seller | `patient_defection` | 30 |
| V1 | Verifier idle | P4 | verifier, seller | `verifier_idle` | 3 |
| V2 | Verifier wrong verdict | P3, P4 | verifier | `wrong_verdict` | 30 |
| V3 | Seller and verifier collusion | P4 | seller, verifier | `collusion` | 30 |

The fault kinds added with A2, C1, H1, I1, I2, I6, K1, K2 and R2 are directives: the
faulted process implements the behavior. The services do not read directives
yet (controller README, Processes and manifest), so these scenarios plan and
validate but cannot run until they do.

## Current rules the scenarios assume

- A confirmed failure freezes every unreleased entry of the bond account and
  suspends the seller. With the profile flag `freezeOnInitialFail` (admitted
  only by the override build, and required by it below the case horizon; the
  deferral sweeps use it) the freeze and the suspension land at the initial
  `FAIL` instead and are cleared if the case ends without a failure.
- The claim window opens only when the failure is final; buyers holding
  receipts claim the frozen pool and the remainder is forfeited.
- Suspension is reversible: `reinstateSeller` once the account is not
  `FROZEN`, with no initial `FAIL` pending and at least one `sellerPenalty` in
  the bond account, also while the claim window is still open (ADR 0021). The
  purchases settled after such a re-entry are outside the frozen window; the
  next confirmed failure moves the window over them (`freezeBlock` becomes its
  block), so they are frozen and claimable too.
- Every confirmed failure deducts `sellerPenalty / failureLimit` from the
  bond (ADR 0018). A failure window that opens at scale factor `n` sanctions at
  `n * failureLimit` failures (16 for the data API profile, 27 for open
  weights, at `n = 1`) and the failure that reaches it deducts the remainder,
  so the window costs `n * sellerPenalty` (ADR 0021). A seller that re-enters
  during each claim window keeps counting in the same failure window (C1).
- A review seal that finds no randomness (the seal window passed or the block
  hash is gone) reopens once per review stage on the next block; only a second
  miss in the same stage ends the case as a protocol `INCONCLUSIVE` (ADR 0021,
  K1 variant `review_seal_delayed`).
- An unappealed initial `PASS` or `INCONCLUSIVE` is automatically rechecked
  with probability `recheckPpm`, and a party review that disagrees with the
  initial verdict goes to a tiebreak (ADR 0019).
- A sampled `FINAL(INCONCLUSIVE)` can freeze only once the window holds
  `minJudgedCount` judged cases (ADR 0020).
- A missed anchor is the seller's failure (freeze, suspension, one final
  failure); a missed seal or unavailable randomness fails the epoch with
  refunds and no seller counter (K1, K2).
- `FINAL(INCONCLUSIVE)` above `maxInconclusivePpm` freezes and suspends but is
  never counted toward `failureLimit` and never slashes (I1, I2).

What changed in the older scenarios: S5 now runs the admissible profile and
predicts flat released exposure with the cap off (the rate-dependent case is
D1 and D2), with the rate window taken over `enforcementBlocks`; S6 predicts
deterrence through the freeze and claims instead of a penalty at the first
failure, and its full-collateral comparison moved to the run list (arm B4); V1
branches on whether the seller publishes on the keeper path; S2 checks the
freeze, the suspension, the failure count and reinstatement; E1 uses the
profile `appealBlocks`, keeps runs in which the wrongful `FAIL` is upheld and
reports them as a separate outcome class, and measures
`first_fail_to_freeze_blocks`; D5 sweeps the judgment delay in hours,
including the fairbind values, against three window readings of B6.

## Main run list

`run-list.json` names the scenario and arm combinations of a run;
`--run-list main` plans them. The main run puts every scenario except I6 on the
fairbind arm (I6 has its own run, `--run-list hold-period-grid`, planned and
validated but not run yet), S5 (burst) on B0a, B0b, B1, B2, B4, B6, B7a and B7b, S6 (patient
defection) on B1, B4, B6, B7a and B7b, and D5 on B6. Both readings of B7 are in
it. A baseline arm's run is planned with its resolved config and blocked until
its policy adapter exists.

## Deferral grid

D1, D2, D3 and E1 place the deferral `D` on one grid. All six values are
expressions over the operating point (`experiments/operating-point.json`) and
are recomputed from the derived profile of each run.

| Point | Data API (blocks) | Open weights (blocks) | Region |
| --- | --- | --- | --- |
| `L_min/2` | 584 | 1,334 | a: `D < L_min`; every release rule leaks |
| `L_min` | 1,168 | 2,668 | b: `L_min <= D < delta_F`; leaks only when the realized freeze delay exceeds `D` |
| `delta_F` | 3,971 | 18,003 | c: `delta_F <= D < L`; nothing settled after the detected sale is released before the freeze |
| `(delta_F+L)/2` | 6,675 | 29,707 | c |
| `L` | 9,380 | 41,412 | `D = L` |
| `caseHorizon` | 58,994 (profile hold 60,000) | 130,526 (profile hold 132,000) | admissible profile, no override |

`L_min = epochBlocks + anchorBlocks + beaconDelayBlocks` is the delay no
seller can shorten; `delta_F = openHorizon + maxAssignments * (judgeBlocks + 1)
+ evidenceBlocks` is the worst-case delay from a bad settlement to the freeze at
its initial FAIL under `freezeOnInitialFail`, which every override point sets;
`L` is `judgmentDelayBlocks` (to the final FAIL, where a production profile
freezes).

How a point is built (`controller/scenario.py`, `resolve`):

- `D < caseHorizon`: `deferBlocks`, `retentionBlocks` and `claimWindowBlocks`
  (which must equal retention) are set to `D`. `failureWindowBlocks` and
  `inconclusiveWindowBlocks` keep their profile values, so the failure count and
  the inconclusive rate mean the same at every point. The run is marked
  `override_used: true` and needs the override build and
  `--allow-inadmissible-profile`.
- `D >= caseHorizon`: no override. At or below the profile hold period the
  profile runs unchanged (the `caseHorizon` point therefore runs the admissible
  profile with its 60,000-block hold); above it the three fields are raised to
  `D`. A scenario that sets `exact_hold: true` (I6) lowers the three fields to
  `D` between the case horizon and the profile hold as well, which is still
  admissible.

The checks the override build skips are listed once, in
`OVERRIDE_SKIPPED_CHECKS` in `controller/profile.py`; the controller copies that
list into `override_skipped_checks` of every plan entry and result envelope
that uses the override, and blocks a point that violates any other check. Every
run records `requested_D_holding_blocks`, `effective_hold_period_blocks`
(`max(deferBlocks, retentionBlocks)`), `override_used` and
`override_skipped_checks`.

## Hold-period grid (I6)

I6 is the grid of the ADR 0021 review as revised by the V2 review, used later;
the controller plans and validates it (`--run-list hold-period-grid`) but it is
not run yet. It is not the product of every axis: the scenario lists named
cells (`cells`), each a partial grid with its own repetition count, and the
judgment rules the analysis applies to them (`analysis`). The axes are:

| Symbol | Operating-point name | Data API (blocks) | Open weights (blocks) |
| --- | --- | --- | --- |
| `T_min/2` | `L_min/2` | 584 | 1,334 |
| `T_min` | `L_min` | 1,168 | 2,668 |
| `T_stop` | `delta_F` | 3,971 | 18,003 |
| `(T_stop+T_catch)/2` | `(delta_F+L)/2` | 6,675 | 29,707 |
| `T_catch` | `L` (`judgmentDelayBlocks`) | 9,380 | 41,412 |
| `T_case` | `caseHorizon` | 58,994 | 130,526 |
| `T_hold` | `hold_period` (deployed) | 60,000 | 132,000 |

- Bond levels: 0, `g/(2p)`, `g/p` and `k * g * ceil(1/p)` (`failureLimit`,
  the default), realized as in D3.
- Rates: low (`1/(10*p*D)`), the p99 of the 14-day average rate
  (`rate:mean_14d_p99_top400`), the bucket rate `bucket_max` (`scale_factor *
  refillPpmPerBlock / PPM`, the sustained capacity of the account) and, with
  the cap off only, `bucket_max_x10`.
- Scale factor 1, 3 and 7; keeper delay 0, `keeper_margin/2`, `keeper_margin`
  and `keeper_margin + 100` (`keeper_margin = T_hold - T_case`). The keeper
  delay `keeper_delay_budget_blocks` is a per-case sum (kappa_Sigma): the
  keeper directive's `keeper_delay` block spends the whole budget on the last
  keeper call before each confirmed failure and makes every other call
  promptly, so every effective-detection case has kappa_Sigma = kappa.
- `judgment_path`: `normal`, or `worst` (below).

| Cells | What they vary | Repetitions |
| --- | --- | --- |
| M1 | seven hold periods x three rates (admissible and comparison points apart) | 100 at the admissible low-rate points, 30 otherwise |
| M2 | `T_case`, `T_hold` x bond 0, `g/(2p)`, `g/p` x three rates | 100 low rate, 30 otherwise |
| M3 | `T_min/2`, cap off, three rates (Theorem 2) | 30 |
| M4 | `T_hold`, cap off, `bucket_max` and `bucket_max_x10`, bond `g/p`, normal path: a check of the cap-off code path (exposure near zero is predicted) | 30 |
| M4-worst | as M4 on the worst path with keeper delay `T_hold - L_actual`, so the case ends at `T_hold`: the introduction's falsification condition on the admissible profile | 100 |
| P1 | scale 3 and 7 | 100 low rate, 30 bucket rate |
| P2 | keeper delay within the margin, and past it (`T_case` + 100, `T_hold` with `keeper_margin + 100`) | 100 low rate, 30 bucket rate |
| P3 | `g = v/2` | 100 |
| P4 | the open-weights profile (planned only with `--profile-name open-weights-standard-v1`) | 100 low rate, 30 bucket rate |
| P5 | worst path at the bucket rate: keeper delay at the margin, and two positive controls relative to `L_actual` (P5-over: keeper delay `T_hold - L_actual + 100`; P5-short-hold: prompt keeper and a hold `L_actual - 100` on the override build with `freezeOnInitialFail = false`) | 100, controls 30 |
| P6 | corner: worst path, scale 7, keeper delay at the margin, bucket rate | 100 |
| H | honest arm at scale 1, 3 and 7 with the fixed top-up policy | 10 |

With `judgment_path: worst` every process that acts on the case of a sampled
bad sale receives a `worst_path` block in its directive
(`experiments/controller/worstpath.py`). The directives apply to every sampled
bad sale; the sample stays the contract's s-random draw, so on this path every
sampled bad sale is detected and the detection probability per bad sale is s.
In the initial stage the first two assignments deliver FAIL at the judge
deadline, evidence is requested at the appeal deadline and the assignment is
voided by `timeoutEvidence` in the block after the evidence deadline; the last
one delivers FAIL, its evidence is disclosed at the evidence deadline and the
seller appeals at the renewed appeal deadline. In the review stages all but
the last assignment time out at the judge deadline, the party review overturns
and the tiebreak confirms. Every assignment redelivers through serve,
challenge and publication at the deadlines, and the keeper lets every review
seal lapse once so that each review stage reopens. The buyer opens no dispute
on the sampled sale (a dispute would make `openSample` revert) and claims only
after the case is final. The plan entry records the per-term budget of
`caseHorizon` (`worst_path_schedule`): the terms the path can spend
(`path_budget`) and `marginBlocks`, which no actor spends (`margin_unspent`).
A worst-path case therefore ends at the latest `caseHorizon - marginBlocks +
kappa_Sigma` blocks after the bad settlement, and the terms are upper bounds
(the review stages admit neither evidence requests nor appeals). The actual
length `L_actual`, from the settlement of the sampled bad sale to its confirmed
failure minus kappa_Sigma, is measured on the contract
(`contracts/test/WorstPathLength.t.sol`: 29,680 blocks for data-api-fast-v1,
91,180 for open-weights-standard-v1; the shorter path in which the non-last
initial assignments time out at the judge deadline gives 25,480 and 83,980,
and a case opened by a buyer dispute on an unsampled sale 29,672 and 91,712)
and recorded in the operating point (`L_actual_blocks`, `value` the longest and
`min` the shortest measured path) before the main run. The positive controls
are defined relative to the shortest path (P5-over `kappa = T_hold -
L_actual_min + 100`, P5-short-hold `T_hold = L_actual_min - 100`) and M4-worst
relative to the longest (`kappa = T_hold - L_actual`); until they are recorded
their points are unresolved and blocked. A positive control fails if `L = 0`
(no post-detection leak) in every run of the cell; then the harness did not
reach the boundary and I6 results are not used. In P5-margin and P6 the case
ends `G = T_hold - L_actual - kappa` blocks before `T_hold`, so their
predicted exposure is `g * (1 - s)^(r*G + 1) / s`.

The honest arm's owner tops the bond up to exactly `n * sellerPenalty` in the
block after each per-failure deduction and never otherwise
(`honest_top_up_policy`), so under the maximum-scale rule of ADR 0022
(decision 16, implemented in the contract) its window threshold stays the one
the window opened with. The honest arm runs this one policy only; the
scale-history branches it does not reach are covered by the unit and stateful
contract tests. A cheater that re-enters after a confirmed failure tops its
bond account up to `n * sellerPenalty` (`n * B`), not only the `B` that
reinstatement needs, so that the second episode of the scale 3 and 7 cells
runs at the same scale.

`analysis` records the falsification conditions I6-F1 to I6-F11b (F10: the
realized detection rate pooled over a cell against the analytical lower bound
`s * (h * (1 - beta))^2`, one-sided exact binomial, Holm over the admissible
normal-path cells; the worst-path cells M4-worst, P5-margin and P6 are listed
as `descriptive_cells`, since their directives detect every sampled bad sale
and their detection probability is `s`. F11a: an effective-detection case
whose path minus kappa_Sigma is longer than `T_case - marginBlocks` falsifies
the window count of the case-horizon lemma; F11b: such a path longer than
`T_case`, or a post-detection leak in a run whose `kappa_Sigma` is at most the
keeper margin, falsifies the admissibility condition, and a leak without any
long case is attributed to the freeze at the confirmed failure; both on a
single observation, without Holm correction), the positive-control check (a
control fails if `L = 0` in every run and is marked for investigation with a
leak in fewer than 27 of 30 runs), the Holm families (F1, F4 and F5 split by
episode and by low and high rate; F9 over the three scales; F10 over the
admissible normal-path cells), and the pruning rule: if the compute budget
requires, the low-rate cells in the listed order drop from 100 to 60
repetitions, never below, and a second-episode judgment needs at least 30 runs
with a finished second episode. The controller validates these references (cells named by a
condition, family or pruning order exist; a family keeps one rate class; the
pruning order lists only low-rate cells) and applies no verdict.

Result columns, per point: released exposure and net gain of the first and of
the second episode (`released_exposure`, `second_episode_exposure`,
`episode_net_gain`, `second_episode_net_gain`), `post_detection_leak`,
`releases_after_reentry` in the margin-overrun cells, the configured and
achieved rates, `realized_detection_rate` (final `FAIL` and `UNSERVED` in the
numerator) with the auxiliary estimator episodes with a detection / sum of
`first_detection_index` over all episodes (censored ones included), `keeper_delay_sum_max_blocks`,
`worst_path_case_blocks`, `case_path_blocks` and `case_path_minus_keeper` per
effective-detection case, and for the honest arm
`honest_sanctions_per_window`, `honest_top_up_count` and
`honest_max_window_scale`.

## Falsifying the D >= L arm

A fast cheater cannot tell a bond of `g/p` from no bond at `D >= L`: its first
`1/p` bad sales settle within a few blocks of the detected one, so every one of
them is still held at the freeze, and with `g = v` the frozen pool returns
exactly what it gained. D3 therefore adds three things:

- a slow point, `Lambda_cheater = 1/(10*p*D)` with `D` the effective hold
  period: about 2.5 bad sales per hold period, so the expected time to the first
  detected bad sale is about `10 D` and the bad sales before it are released;
  this is the `g/p` term of the exposure bound;
- bond levels 0, `g/(2p)` and `g/p` (`bond_fraction_of_g_over_p`); the two
  lower levels are below the penalty floor every build enforces, so the
  controller declares a smaller `maxBadGain` (used only in that floor) and the
  seller keeps its true gain `bad_sale_gain_atomic`; a bond of 0 becomes the
  smallest admissible penalty;
- `g = v/2`, so the frozen pool (`v` per frozen sale) and the gain (`g` per bad
  sale) no longer cancel.

D3's `expected_outcome` states the predicted released exposure and net gain for
each point and its `pass_criteria` states how each prediction fails. Within one
episode the bond is charged one share, `sellerPenalty / failureLimit`, per
confirmed failure (ADR 0018); deterrence over repeated episodes is C1's
question.

D5 applies to baseline arm B6, which has a fixed challenge window and no
deferral; it sweeps the judgment delay against the window instead.

## Cap off

"Cap off" (`cap_enabled: false`, used by D1, D2 and S5) is the
`disable_cap` transform in `experiments/controller/profile.py`: it raises
`maxRatePpmPerBlock` to the max uint32 (4294967295), `refillPpmPerBlock` to
half of that (2147483647), `enforcementBlocks` to at least the judgment
delay `L`, and `bucketCapacity` to the largest value the rate condition
still allows over that window, capped at the max uint32. The settle bucket
then never rejects a call in practice. There is no contract switch for this;
it is only these profile field values, and the existing rate condition
(`bucketCapacity * PPM + refill * enforcement <= maxRate * enforcement`)
still holds. With the cap off, the exposure formula uses the settlement rate
`Lambda` actually observed in the run rather than an assumed maximum, and
the run asserts `rejected_settlement_count == 0`.

`P_S_reserve: profile_penalty_floor` is the `expectedPenaltyFloor` of the
profile that is actually deployed, so it is computed after the cap transform.
With the cap off and `D < L` that floor uses the uncapped rate field and is
very large (about 3.0e11 atomic units at `D = L_min/2` for the data API
profile); the override build still enforces `sellerPenalty >=
expectedPenaltyFloor`, so a penalty sized for the capped rate could not be
deployed at those points. The penalty is charged only when final failures reach
`failureLimit`, so within one episode it does not change the released exposure
that D1 and D2 measure.
