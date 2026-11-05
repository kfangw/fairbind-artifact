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
| `rejected_settlement_count` | `settle` calls for `S` that reverted with the rate-limit error | count | facilitator `settle_reverted` rows with the error selector |
| `capital_locked_time_integral` | sum over blocks of (bond balance of `A` + value of `S`'s entries not yet released or lost) | atomic * blocks | ledger; `BondRegistered`, `BondScaled`, `Slashed` |
| `realized_detection_rate` | bad sales (`GT`) of `S` whose case ended in an effective detection, a final `FAIL` or `UNSERVED` / bad sales of `S` settled in epochs that were sealed and whose cases are terminal. Compared with the expected `p` (`effectivePpm`) in the envelope's `detection`. The denominator includes the bad sales settled between the first detection and the freeze; the auxiliary estimator episodes / sum of `first_detection_index` over them is reported beside it | ratio | `CaseOpened`, `CaseFinalized`, `EpochSealed`; `GT` |
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
