# Metric definitions

Every metric a scenario names in `observed_metrics` is defined here, and only
here. `controller/scenario.py` reads the ids from the tables below and rejects
a scenario that names any other metric. A process or the collector reports a
metric as rows `{"metric": id, "value": ..., "observation_id": ...}`; a metric
without rows is listed as missing in the result envelope, never as zero.

## Notation and conventions

- `S` is the observed seller and `A` its bond account; `v_i` is the price of
  purchase `i` (the profile's `maxPurchaseValue`, `v` in the operating point),
  `g_i` the seller's gain on a bad sale (`bad_sale_gain_atomic` when the
  scenario sets it, otherwise `g` of the operating point).
- Ground truth (`GT`) is the controller's record of which sales were bad,
  which disputes were false and which verdicts were wrong
  (`<output>/ground-truth/<run_id>.json`). It is joined with the chain only in
  the collector, after the run.
- Chain events are the events of `docs/spec/contract-interface-v1.md`, read by
  the collector from the run's chain; gas values come from the transaction
  receipts.
- An entry of `S` "reaches `S`" when it has a `Released` event; it "is lost to
  `S`" when its value leaves the deferred ledger by `Refunded`,
  `FrozenClaimPaid` or `UnclaimedForfeited`.
- The observation window runs from the first settlement of the run to the
  drain block, the first block at which every entry settled in the run has
  reached `S` or been lost to it. A run that times out before draining reports
  the window it reached and sets `drained = false` in its observation ids.
- Units: `atomic` is the token's smallest unit (six decimals); `blocks` are
  settlement-chain blocks (two seconds); `ratio` is a number in [0, 1]; a
  `list` value is an array with one element per item named in the formula.

## Core metrics (every scenario, in this order)

| id | Formula | Unit | Source |
| --- | --- | --- | --- |
| `double_settlement_rate` | purchases `(buyer, sellerId, k)` with more than one `Settled` event / distinct purchases attempted | ratio | `Settled`; buyer attempt log |
| `post_settlement_unrecovered_rate` | settled purchases whose buyer received neither the response with the receipt's `responseHash` nor a refund (`Refunded` or `FrozenClaimPaid` to that buyer) by the drain block / settled purchases | ratio | `Settled`, `Refunded`, `FrozenClaimPaid`; buyer `response_received` rows |
| `released_exposure` | sum of `g_i` over bad sales `i` (`GT`) of `S` that reached `S` | atomic | `Released`; `GT` |
| `anchor_gas_per_epoch` | mean `gasUsed` of the `anchor` transactions of `S` | gas | receipts |
| `retention_storage_bytes` | bytes the seller keeps for receipts and responses at the end of the window | bytes | seller `retention_bytes` rows |
| `captured_funds_time_average` | (1 / window length) * sum over blocks of the value of `S`'s entries not yet released or lost | atomic | ledger rebuilt from `Settled`, `Released`, `Refunded`, `FrozenClaimPaid`, `UnclaimedForfeited` |
| `false_positive_recovery_amount` | sum of `v_i` over honest sales (`GT`) of an honest `S` that were lost to `S` | atomic | same ledger; `GT` |
| `locked_capital` | bond balance of `A` posted at registration plus top-ups | atomic | `BondRegistered`, `BondScaled` |
| `gas_per_settlement` | mean `gasUsed` of `settle` | gas | receipts |
| `gas_per_judgment` | mean `gasUsed` of `judge` | gas | receipts |
| `gas_per_dispute` | mean `gasUsed` of `dispute` | gas | receipts |
| `gas_per_call` | one element per FairBind entry point called in the run: `{function, count, mean, max}` of `gasUsed` | list of gas | receipts, by function selector |
| `recovery_time_blocks` | refund block minus settlement block, one element per refunded purchase | list of blocks | `Settled`, `Refunded`, `FrozenClaimPaid` |
| `judgment_delay_distribution` | `CaseFinalized` block minus the purchase's settlement block, one element per case | list of blocks | `Settled`, `CaseFinalized` |

## Extended metrics (every scenario, in this order)

| id | Formula | Unit | Source |
| --- | --- | --- | --- |
| `cheater_net_gain` | `sum_i g_i` over bad sales of `S` settled in the window, minus `sum_j v_j` over every entry `j` of `S` (bad or honest) lost to `S`, minus seller penalties charged to `A` (`SellerSanctioned.penalty` and seller `Slashed`). This is `S`'s gain against selling honestly: a released bad sale adds `g`, a lost entry costs its price. Sales not made while suspended are not included (next row) | atomic | ledger; `SellerSanctioned`, `Slashed`; `GT` |
| `sales_lost_while_suspended` | `v` times the purchases the workload offered to `S` that were refused because `S` was `SUSPENDED` or `SANCTIONED` or `A` was frozen; reported beside `cheater_net_gain`, never folded into it | atomic | buyer `settlement_refused` rows with the revert selector; `SellerSuspended`, `SellerReinstated`, `SellerSanctioned` |
| `exposure_vs_bond` | `released_exposure` / `sellerPenalty` of the deployed profile | ratio (may exceed 1) | as above; derived profile |
| `buyer_recovery_rate` | purchases with a refund right that were refunded or paid by claim / purchases with a refund right (bad sales per `GT`, undelivered purchases, and entries in a frozen pool whose buyer holds a receipt) | ratio | `Refunded`, `FrozenClaimPaid`, `ClaimWindowOpened`; `GT` |
| `honest_seller_delay_blocks` | `Released` block minus `Settled` block, one element per honest sale (`GT`) of an honest `S` | list of blocks | `Settled`, `Released` |
| `honest_seller_suspended_fraction` | blocks in which an honest `S` (`GT`) was `SUSPENDED` / blocks in the window | ratio | `SellerSuspended`, `SellerReinstated`, `FrozenReleased` |
| `frozen_amount` | `frozenTotal` of each `SellerDeferredFrozen` event of `A` | list of atomic | `SellerDeferredFrozen` |
| `rejected_settlement_count` | settlements the contract refused with `RateLimitExceeded` (the rate cap): the facilitator's settlement attempts, one per purchase nonce, whose final status is `rejected` with that revert name, whether the refusal came from the simulation before sending or from a mined revert. Attempts refused for any other reason, and payloads the facilitator rejects before the contract (signature, window, nonce checks), are not counted; the I6 collector also reports `rejected_settlements_by_revert`, the rejected attempts by revert name. Absent when the facilitator's attempt store is not in the run directory | count | facilitator `data/attempts/<nonce>.json` (`status`, `revert`) |
| `capital_locked_time_integral` | sum over blocks of (bond balance of `A` + value of `S`'s entries not yet released or lost) | atomic * blocks | ledger; `BondRegistered`, `BondScaled`, `Slashed` |
| `realized_detection_rate` | bad sales (`GT`) of `S` whose case ended in an effective detection, a final `FAIL` or `UNSERVED` / bad sales of `S` settled in epochs that were sealed and whose cases are terminal. The I6 collector's per-sale rows carry `detection_eligible`: the sale's epoch was sealed, its sampling window (through `sealDeadline + openBlocks`, `sealDeadline` = the `Anchored` random block + `sealBlocks`) ended at or before the view block, and the sale has no case or a terminal one. Compared with the expected `p` (`effectivePpm`) in the envelope's `detection`. The denominator includes the bad sales settled between the first detection and the freeze; the auxiliary estimator episodes / sum of `first_detection_index` over them is reported beside it | ratio | `CaseOpened`, `CaseFinalized`, `EpochSealed`; `GT` |
| `realized_sample_rate` | purchases with a sample-triggered `CaseOpened` / purchases settled in sealed epochs. Compared with the expected `pi` (`samplePpm`) | ratio | `CaseOpened`, `EpochSealed`, `Settled` |

## Scenario-specific metrics

| id | Formula | Unit | Source |
| --- | --- | --- | --- |
| `effective_hold_period_blocks` | `max(deferBlocks, retentionBlocks)` of the deployed profile | blocks | controller plan (also in the envelope) |
| `freeze_delay_blocks` | `frozenAtBlock` of each `SellerDeferredFrozen` minus the settlement block of its trigger purchase | list of blocks | `SellerDeferredFrozen`, `Settled` |
| `first_fail_to_freeze_blocks` | `frozenAtBlock` minus the block of the initial `FAIL` verdict of the trigger case | list of blocks | `VerdictSubmitted`, `SellerDeferredFrozen` |
| `fail_overturn_blocks` | block at which the freeze caused by an initial `FAIL` is cleared (`FrozenReleased`) minus the block of that `FAIL`, one element per overturned `FAIL` | list of blocks | `VerdictSubmitted`, `FrozenReleased` |
| `frozen_then_released_count` | entries of `A` frozen and later released to `S` by `FrozenReleased` or a later `Released` | count | `SellerDeferredFrozen`, `FrozenReleased`, `Released` |
| `seller_penalty_charged` | sum of `Slashed` amounts with `actorType` 1 against `A`: one share (`reason` 4) per counted confirmed failure and the remainder (`reason` 1, also `SellerSanctioned.penalty`) at `failureLimit` (ADR 0018) | atomic | `Slashed`, `SellerSanctioned` |
| `suspension_count` | `SellerSuspended` events of `S` | count | `SellerSuspended` |
| `reinstatement_count` | `SellerReinstated` events of `S` | count | `SellerReinstated` |
| `final_failure_count` | final `FAIL` outcomes recorded against `A` in the window | count | `CaseFinalized`, `SellerSanctioned.failureCount` |
| `episode_net_gain` | `cheater_net_gain` restricted to one episode (from a reinstatement, or the start, to the next claim window close), one element per episode | list of atomic | as `cheater_net_gain`, split at `SellerReinstated` |
| `achieved_settlement_rate` | `Settled` events of `S` / blocks in which `S` was `ACTIVE` | settlements per block | `Settled`, seller state events |
| `wrongful_final_fail_count` | final `FAIL` outcomes on purchases that `GT` marks correct | count | `CaseFinalized`; `GT` |
| `honest_seller_pool_loss` | sum of `v_i` over entries of an honest `S` lost to `S` after a final `FAIL` that `GT` marks wrong | atomic | ledger; `CaseFinalized`; `GT` |
| `attacker_refund_gain` | refunds and claim payouts received by the attacking buyer on purchases `GT` marks correct, minus the attacker's dispute and appeal deposits not returned | atomic | `Refunded`, `FrozenClaimPaid`, `DepositResolved`; `GT` |
| `inconclusive_ratio_observed` | `inconclusiveCount / judgedCount` of the last `InconclusiveRecorded` event of `A` | ratio | `InconclusiveRecorded` |
| `epoch_failed_count` | `EpochFailed` events of `S`, one element per reason code: `{reason, count}` | list | `EpochFailed` |
| `sample_escape_rate` | bad sales (`GT`) of `S` that were in a failed epoch or were sampled without an opened case by the drain block / bad sales of `S` | ratio | `EpochFailed`, `CaseOpened`; `GT` |
| `unopened_sample_count` | purchases that the sealed randomness selects but that have no `CaseOpened` by the drain block | count | `EpochSealed`, `CaseOpened`; the sample rule of `docs/spec/fairbind-v1.md` section 12 |
| `refund_payout_count` | payouts to buyers (`Refunded`, `FrozenClaimPaid`), one element per purchase that received any | list of count | `Refunded`, `FrozenClaimPaid` |
| `double_refund_count` | purchases whose buyer received more than one payout, or payouts summing above the purchase value | count | same |
| `false_claim_deposit_forfeiture_rate` | false disputes (`GT`) whose deposit went to the seller (`DepositResolved` recipient = seller) / false disputes | ratio | `DepositResolved`; `GT` |
| `leak_amount` | baseline arms: sum of `v_i` over bad sales (`GT`) not refunded to the buyer by the drain block | atomic | adapter ledger; `GT` |
| `refusal_rule_trigger_rate` | admissions refused by an arm's exposure-ceiling rule / admission attempts | ratio | adapter log |
| `settle_retry_count` | `settle` submissions by the facilitator per purchase | list of count | facilitator `settle_submitted` rows |
| `keyId_duplicate_detection_rate` | second settlements with a used `keyId` that reverted / such attempts | ratio | facilitator rows with the revert selector |
| `retry_settle_attempt_count` | buyer retries per purchase | list of count | buyer attempt log |
| `state_recovery_time_blocks` | block of the first successful response after a seller restart minus the restart block | blocks | controller `process_restarted`; seller `response_sent` rows |
| `omission_proof_submission_rate` | `proveOmission` calls / receipts omitted from an anchor (`GT`) | ratio | receipts; `GT` |
| `omission_proof_gas` | `gasUsed` of each `proveOmission` | list of gas | receipts |
| `late_response_dispute_rate` | disputes opened on responses delivered after `responseDue` / such responses | ratio | `CaseOpened`; buyer `response_received` rows |
| `burst_exposure` | `v` times the settlements of `S` confirmed inside the burst window (`GT`) | atomic | `Settled`; `GT` |
| `verifier_slash_amount` | sum of `Slashed` amounts against verifiers | atomic | `Slashed` |
| `reassignment_count` | `VerifierAssigned` events per case beyond the first, one element per case | list of count | `VerifierAssigned` |
| `appeal_reversal_rate` | appeals whose final verdict differs from the appealed verdict / appeals | ratio | `ReviewSelected`, `CaseFinalized` |
| `wrong_verdict_penalty_amount` | sum of `verifierWrongPenalty` slashes | atomic | `Slashed` |
| `collusion_detection_rate` | colluding `PASS` verdicts (`GT`) reversed by recheck / colluding `PASS` verdicts | ratio | `ReviewSelected`, `CaseFinalized`; `GT` |
| `buyer_deposit_loss` | dispute and appeal deposits of the attacking buyer that went to the seller (`DepositResolved` with the buyer as payer and the seller as recipient), summed over the run's disputes; reported beside `attacker_refund_gain` | atomic | `DepositResolved`; `GT` |
| `review_reseal_count` | `ReviewResealed` events of cases of `S`, one element per review stage: `{stage, count}` (ADR 0021) | list | `ReviewResealed` |
| `review_protocol_inconclusive_count` | cases of `S` that ended as a protocol `INCONCLUSIVE` in a review stage after a missed review seal (`CaseFinalized` with verdict 3 and case state `INCONCLUSIVE`, preceded by a `ReviewResealed` of the same stage) | count | `ReviewResealed`, `CaseFinalized` |
| `configured_settlement_rate` | the rate the seller directive asked the workload to settle at, in settlements per block, after the controller resolved `bucket_max` to `scale_factor * refillPpmPerBlock / PPM` (and `bucket_max_x10` to ten times that) | settlements per block | seller directive; derived profile |
| `freeze_on_initial_fail` | the `freezeOnInitialFail` flag of the deployed profile (true on every override point of the hold-period grid) | boolean | derived profile (also in the envelope) |
| `keeper_delay_sum_blocks` | per effective-detection case of `S`, the sum over the keeper calls on its path of (block of the call minus the first block at which the call was due), kappa_Sigma of the case; the controller gives each case the budget `keeper_delay_budget_blocks`, spent on the last keeper call before the confirmed failure (every other call prompt), so every case records kappa_Sigma = `keeper_delay_budget_blocks` | list of blocks | keeper `call_sent` rows with the due block; keeper directive `keeper_delay` |
| `honest_sanctions_per_window` | `SellerSanctioned` events of the honest seller that runs beside `S` on its own bond account, per `failureWindowBlocks` of the observation window | count per window | `SellerSanctioned`; derived profile |
| `second_episode_exposure` | `released_exposure` restricted to the second episode (from the first `SellerReinstated` of `S` to the next claim window close); null when the run has no second episode | atomic | as `released_exposure`, split at `SellerReinstated` |
| `second_episode_net_gain` | `episode_net_gain` of the second episode alone | atomic | as `episode_net_gain` |
| `post_detection_leak` | gain of the bad sales (`GT`) settled after the settlement block of the first detected bad sale of an episode that were released to `S`, one element per episode (zero when the worst path ends within the hold period) | list of atomic | `Settled`, `Released`; `GT` |
| `releases_after_reentry` | bad sales (`GT`) settled after a `SellerReinstated` of `S` and released to it, counted in cells whose keeper delay or hold period leaves the margin (`T_hold - T_case`) overrun | count | `SellerReinstated`, `Settled`, `Released`; `GT` |
| `keeper_delay_sum_max_blocks` | largest per-case sum of keeper delays on the path to a confirmed failure of `S` (kappa_Sigma), and whether it exceeded the keeper margin | blocks | keeper `call_sent` rows with the due block |
| `honest_top_up_count` | `topUpBond` calls of the honest seller's owner; under the fixed policy one per deduction, each restoring the balance to exactly `n * sellerPenalty` | count | `BondScaled`, honest seller directive |
| `honest_max_window_scale` | largest `getFailureWindowScale` of the honest seller's bond account over the run's failure windows (ADR 0022) | count | `getFailureWindowScale` at each `SellerSanctioned` or window end |
| `worst_path_case_blocks` | on the worst-path directives, for every effective-detection case of `S` (final `FAIL` or `UNSERVED`), blocks from the settlement block of the purchase to the block of its confirmed failure minus the kappa_Sigma of the case, one element per case (the `case_path_minus_keeper` elements of the worst-path cases); at most `caseHorizon - marginBlocks` (no actor spends `marginBlocks`). `L_actual` is the largest element over the effective-detection cases of the dry run and `L_actual_min` the smallest; both are recorded in the operating point | list of blocks | `Settled`, `CaseFinalized`; keeper `call_sent` rows with the due block; worst-path directive |
| `case_path_blocks` | for every effective-detection case of `S` (final `FAIL` or `UNSERVED`), blocks from the settlement block of the purchase to the block of its confirmed failure (`CaseFinalized`), one element per case, on every judgment path | list of blocks | `Settled`, `CaseFinalized` |
| `case_path_minus_keeper` | `case_path_blocks` minus the sum of keeper delays on that case's path (kappa_Sigma of the case), one element per case in the same order; the case-horizon lemma bounds it by `caseHorizon - marginBlocks` | list of blocks | `Settled`, `CaseFinalized`; keeper `call_sent` rows with the due block |
| `first_detection_index` | per episode, the number K of bad sales (`GT`) of `S` counted in settlement order from the start of the episode up to and including the first one whose case ended in an effective detection; an episode that ends without a detection (censored) contributes all of its bad sales as K and is flagged `censored`. One element per episode, censored ones included. The auxiliary detection-rate estimator is (episodes with a detection) / sum(K) over all episodes, so censored episodes add to the denominator only | list of `{K, censored}` | `Settled`, `CaseFinalized`; `GT` |
| `finite_attack_detection` | on a finite-attack directive (`controller/finiteattack.py`), per episode: `with_detection` when `A` had a confirmed failure caused by one of the cheated sales (a final `FAIL` or `UNSERVED` case) before every cheated sale reached `S` or was lost to it, `without_detection` when every cheated sale reached `S` or was lost to it first, `open` when the run ended before either | `with_detection`, `without_detection` or `open` | `Settled`, `CaseFinalized`, `ClaimWindowOpened`, `SellerSuspended`, `Released`; `GT` (the first `finite_attack_cheat_sales` settled sales of `S`) |
| `seller_gain_released` | on a finite-attack directive, per episode, the sum of `v_i` over the cheated sales that reached `S` (released, or releasable at the end of the run) | atomic | `Released`, `purchaseState`; `GT` |
| `buyer_refund_amount` | on a finite-attack directive, per episode, the sum of `v_i` over the cheated sales repaid to their buyers (`Refunded`, `FrozenClaimPaid`); the part still claimable at the end of the run is reported apart as `buyer_refund_owed` in the observation | atomic | `Refunded`, `FrozenClaimPaid`, `purchaseState`; `GT` |
| `buyer_refund_blocks` | on a finite-attack directive, per episode, for every repaid cheated sale, blocks from its settlement block to the block of its repayment, one element per repaid sale in settlement order | list of blocks | `Settled`, `Refunded`, `FrozenClaimPaid`; `GT` |

## Hold-period harness metrics (I6)

`experiments/collect_run.py` computes these for one run of the hold-period harness from the ledger
dump (`fairbind-ledger-dump/v1`), the ground truth and the run's service records, and also reports
the ids of the tables above that the ledger determines (`released_exposure`, `cheater_net_gain`,
`exposure_vs_bond`, `realized_detection_rate`, `realized_sample_rate`, `frozen_amount`,
`recovery_time_blocks`, `judgment_delay_distribution`, `false_positive_recovery_amount`,
`honest_seller_delay_blocks`, `honest_seller_suspended_fraction`, `effective_hold_period_blocks`,
`configured_settlement_rate`, `achieved_settlement_rate`, `freeze_on_initial_fail`,
`freeze_delay_blocks`, `seller_penalty_charged`, `suspension_count`, `reinstatement_count`,
`final_failure_count`, `wrongful_final_fail_count`, `honest_sanctions_per_window`,
`honest_top_up_count`, `honest_max_window_scale`, the episode and case-path lists). Gas, buyer
attempt and retention metrics come from other rows.

Conventions of this section:

- Rows carry numbers or lists only (the result envelope rejects other values): a boolean is `1` or
  `0`, a column that has no element in a run is an empty list (for example `y_f` outside the finite
  attack, `bond_exit_finalized_block` without a bond exit), and a scalar with no value (a rate with
  an empty denominator, `second_episode_*` without a second episode) has no row.
- Bad sales (`GT`): `bad_sales_rule` `all_cheater_episode_sales` makes every settled sale of `S`
  bad, `first_m` the first `bad_sales_m` settled sales of `S` in settlement order (block, log
  index), `none` no sale.
- An entry of `S` is reached (`Released`, or `RELEASABLE` at the end of the run, then at its
  `releaseBlock`), lost (`REFUNDED`, `FORFEITED`, `FROZEN_CLAIMABLE` or `REFUNDABLE` at the end of
  the run: frozen entries count as lost to `S`) or open.
- A confirmed failure is a case of `S` that ended `FINAL` with verdict `FAIL` (at its last
  `CaseFinalized`) or `UNSERVED` (at the first `ClaimWindowOpened` or `SellerSuspended` it
  triggered, else at the keeper's `timeoutServe`). kappa_Sigma of a case is the sum over the keeper
  `call_sent` rows of its nonce or of its epoch (`sellerId:epoch`) that landed between its settlement
  and its confirmed failure of (landing block - due block)+, the landing block read from the ledger
  event of the call's transaction (a call without a router event, such as a reverted one, is not on
  the path).
- Episodes of a cheater or honest seller: the sales settled from the first settlement, and from
  every `SellerReinstated` of `S`, up to the next one; the episode ends at the first confirmed
  failure of `S` at or after its start. The finite-attack episode: every sale settled up to its end
  block, the settlement block of the m-th bad sale plus T_hold plus T_case, or earlier the first
  confirmed failure of a bad sale. T_hold is `effective_hold_period_blocks` and T_case the
  `caseHorizon` of the derived profile.
- B is `sellerPenalty` and k `failureLimit` of the deployed profile; B/k is `sellerPenalty /
  failureLimit` rounded down, the share the contract deducts per confirmed failure.
- `episode_net_gain` is evaluated per entry: a reached bad sale adds `g`, a lost bad sale adds
  `g - v`, a lost honest sale subtracts `v`, and the seller `Slashed` amounts on the episode's sales
  are subtracted; an open entry adds nothing (it equals the definition above once every entry of the
  episode is resolved). `post_detection_leak` counts the bad sales after the first detected one in
  settlement order.
- In the honest arm `S` is the honest seller: `honest_sanctions_per_window` is its `SellerSanctioned`
  events in the complete `honest_windows` divided by their number; `honest_top_up_count` counts the
  `top_up` actions with cause `deduction` of the seller policy log (`meta/policy.json`; `topUpBond`
  emits no event unless the scale factor changes); `honest_max_window_scale` is the largest of the
  registration scale factor, every `BondScaled` new scale factor and the end-of-run
  `getFailureWindowScale` (the dump holds no per-window view).

| id | Formula | Unit | Source |
| --- | --- | --- | --- |
| `episode_exposure` | per episode, the sum of `g` over the bad sales of the episode that reached `S` (exposure X), one element per episode | list of atomic | `Settled`, `Released`, `purchaseState`; `GT` |
| `y_f` | per finite-attack episode, the sum of `g` over its bad sales that reached `S` by the episode end block, minus B/k when the episode ended at a confirmed failure of a bad sale; null while the episode is open; empty outside the finite attack | list of atomic | `Settled`, `Released`, `CaseFinalized`, `ClaimWindowOpened`, `SellerSuspended`; derived profile; `GT` |
| `episode_end_mode` | per episode, `with_detection` (ended at a confirmed failure; in the finite attack, of a bad sale), `without_detection` (finite attack: the end block passed without one) or `open` (the run ended first) | list of strings | as `y_f` |
| `episode_end_block` | per episode, its end block (null while open) | list of blocks | as `y_f` |
| `buyer_refund_paid` | per episode, the sum of `Refunded` and `FrozenClaimPaid` values paid on its bad sales | list of atomic | `Refunded`, `FrozenClaimPaid`; `GT` |
| `buyer_refund_paid_blocks` | for every repaid bad sale in settlement order, the block of its first repayment minus its settlement block | list of blocks | `Settled`, `Refunded`, `FrozenClaimPaid`; `GT` |
| `buyer_unrecovered_amount` | per episode, the sum of `v` over its bad sales that reached `S` or ended `FORFEITED` | list of atomic | `purchaseState`, `Released`; `GT` |
| `verdict_counts_by_truth` | `{truth, stage, PASS, FAIL, INCONCLUSIVE, UNSERVED}` per truth (`bad`, `honest`) and stage (`initial`, `party`, `auto`, `tiebreak` from `VerdictSubmitted`; `final` from the terminal case state) | list | `VerdictSubmitted`, `getCase`; `GT` |
| `operating_point_k` | `failureLimit` of the deployed profile | count | `getServiceProfile` |
| `verifier_registered_count` | `VerifierRegistered` events at or before the deployment's `setupBlock` (without a deployment, before the first settlement of `S`) | count | `VerifierRegistered`; deployment |
| `verifier_assignable_count` | those whose registered bond is at least the assignable floor (`controller/profile.py` `assignable_bond_floor`) | count | `VerifierRegistered`; profile |
| `verifier_min_bond_ok` | 1 when every verifier the deployment marks assignable (every one registered at setup when it marks none) and every later registration holds at least the assignable floor, else 0 | 0 or 1 | same |
| `verifier_removed_count` | verifiers moved to `REMOVED` by strikes (the ledger's `verifierRemovals`) | count | `Slashed` (actorType 2); ledger dump |
| `verifier_removal_rate_per_case` | `verifier_removed_count` / sample-triggered cases of `S` | ratio (may exceed 1) | ledger dump, `CaseOpened` |
| `verifier_replacement_count` | `VerifierRegistered` events after the setup block | count | `VerifierRegistered` |
| `assignable_min_between_removal_and_replacement` | per removal in block order, paired with the registrations after setup in block order, the smallest number of registered, not removed or exited verifiers at or above the assignable floor from the removal block up to the block before its replacement | list of count | same |
| `assignment_failure` | per case of `S` that ended by the protocol INCONCLUSIVE path (state `INCONCLUSIVE`, `FINAL` with verdict 3, or an initial-stage keeper publication) while its last stage had fewer than `maxAssignments` assignments, no INCONCLUSIVE verdict and fewer than two reseals: `{nonce, stage, cause, block, assignable_count}`, cause `participation` or `strike_removal` when the verifiers of the epoch's checkpoint are all used by the case or removed by then, else `liability_or_draw`; `block` is the block of the case's last event before the failure and `assignable_count` the number of registered, not removed or exited verifiers at or above the assignable floor at that block (the count of `assignable_min_between_removal_and_replacement`) | list | `VerifierAssigned`, `VerdictSubmitted`, `ReviewSelected`, `ReviewResealed`, `EpochSealed`; checkpoints |
| `post_switch_confirmed_failures` | on a finite attack that serves honestly after its bad sales, `{FAIL, UNSERVED}`: confirmed failures of its honest sales by kind; empty otherwise | list | `getCase`; `GT` |
| `seller_exit_finalized_block` | block of every `SellerExited` of `S` | list of blocks | `SellerExited` |
| `seller_exit_deferred_entries` | per `SellerExited`, entries of `S` settled by then that had neither reached `S` nor been repaid or forfeited by then | list of count | same, `Released`, `Refunded`, `FrozenClaimPaid`, `UnclaimedForfeited` |
| `bond_exit_finalized_block` | block of every `BondExited` of `A` | list of blocks | `BondExited` |
| `bond_exit_deferred_balance` | per `BondExited`, the value of the entries of `S` settled by then that had neither reached `S` nor been repaid or forfeited by then (deferred or frozen) | list of atomic | as `seller_exit_deferred_entries` |
| `bond_exit_open_sampled_cases` | per `BondExited`, sample-triggered cases of `S` opened by then and neither finalized nor confirmed by then | list of count | `CaseOpened`, `CaseFinalized` |
| `honest_windows` | with `bad_sales_rule` `none`, the complete windows of `failureWindowBlocks` laid end to end from the workload start (`workload/summary.json` `start_block`, else the first settlement of `S`) plus T_hold, a window cut off by the end of the run left out: `{start, end, wrongful_confirmed_failures, sanctioned}` with the confirmed failures of honest sales and the `SellerSanctioned` events of `S` in `[start, end]`; empty otherwise | list | `CaseFinalized`, `SellerSanctioned`; `GT` |
| `wrongful_final_fail_per_sampled_case` | with `bad_sales_rule` `none`: sample-triggered cases of honest sales that ended `FINAL` with `FAIL` / sample-triggered cases of honest sales in a terminal state | ratio | `CaseOpened`, `getCase`; `GT` |
| `injection_draw_mismatch_count` | fields of the verifier injection records that differ from their re-derivation: the draws u of purposes `honesty` and `outcome` (SHA-256 of "fairbind/seed/verifier", uint64_be(seed), the 32-byte nonce, uint8(stage), uint8(attempt) and the purpose in ASCII, concatenated; u = (uint64_be(first 8 digest bytes) >> 11) / 2^53), the honesty decision, the outcome rule, the verdict, the seed and the probabilities of the verifier directive | count | `injection/<key>.json`; verifier directive |
| `fault_observed` | one `{item, applicable, ok, reason}` per check that the injected behavior happened: `bad_responses` (finite attack: the seller's cheated sales equal `GT`), `predicate_matches_truth` (every judged assignment's predicate verdict is `FAIL` on a bad sale and `PASS` on an honest one), `injection_log` (every verdict submitted on an injected assignment has a record with the same verdict and no re-derivation differs), `kappa_sigma` (budget > 0: every effective-detection case has kappa_Sigma equal to the budget, in the collector and in the keeper's `case_delay` row), `worst_path_structure` (worst path: every confirmed failure of a sampled bad sale follows the worst path of `controller/worstpath.py`), `post_switch_no_confirmed_failure`, `verifier_bonds` (`verifier_min_bond_ok`), `replacement_next_block` (every removal replaced in the next block); an item that does not apply has `ok` true | list | the inputs of the rows above |
