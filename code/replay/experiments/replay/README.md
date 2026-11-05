# Settlement replay

`replay.py` runs a recorded settlement list through the seller-side admission
rules of the contract (bond bucket, scale, hold period) under the conditions of
`conditions.json`, and computes the observed columns and, offline, the injected
columns. `injection.py` holds the loss model and scale rules the replayer uses;
`rules.py` evaluates the decision rules on a finished run. `make replay-check`
(also part of `make analysis-check`) runs every test here; none needs a chain.

| File | Role |
| --- | --- |
| `conditions.json` | fixed inputs (list hashes and row counts), address groups, the ten conditions, injection settings, decision-rule thresholds |
| `bucket.py` | integer, block-based mirror of `_refilledBucket` / `_consumeBucket` / `registerBond` |
| `inputs.py` | list streaming, reference aggregates, groups A/B/C, input checks |
| `engine.py` | per-address replay (admission, sampling, case openings, `H`, windows) and the vectorised injection model |
| `replay.py` | command line, run envelope, result files |
| `rules.py` | decision rules R20-F1, F3, F4, D1, M1 and checks C1 to C3 |
| `replay_profile.py` | builds `replay-profile-v1.json` and `operating-point-replay.json` from the shared files and the overrides in `conditions.json` |
| `m1_predictions.py` | R20-M1 rejection predictions from the R1 fluid model |
| `input_stats.py` | settlements above the purchase value cap (design 9.8) |
| `baseline.py` | rate-proportional bond baseline `B_vel` (design 9.9) |
| `design2.py`, `design2.json` | the design-2 switches: v_max, sampling by value, unit bond, sales cap grid, hold period and windows, chain block time (section "Design 2") |
| `chain_inputs.py` | joins the daily settlement files of another chain into a replay list, reference aggregates and a conditions file |
| `d2_sweep.py` | one driver for every v_max under every sales cap rule, resumable |
| `d2_report.py` | the report columns of design 2 (comparison form and section 5.2 form) |

Operating-point values (failure limit `k`, `sellerPenalty` `B`, refill, maximum
rate, bucket capacity `q20`, hold period, windows, deadlines) are read from the
replay operating point `operating-point-replay.json` (the default of
`--operating-point`) and the profile file it names, `replay-profile-v1.json`; the
operating point is checked against the profile first
(`controller.operating_point.check`). `k` is recorded in the envelope. `qX` is a
command-line value and must equal `conditions.json` for a reportable run.

### Replay profile (design 9.1, 9.3)

The replay profile is the shared evaluation profile
(`profiles/local-evaluation-v1.json`) with three parameters overridden
(`conditions.json`, `replay_profile.overrides`); every other parameter is equal and
`parameterHash` is recomputed:

| Profile | Parameter | Shared | Replay | Design |
| --- | --- | --- | --- | --- |
| data-api-fast-v1 | `failureLimit` | 16 | 27 | 9.1, pre-certification default k |
| data-api-fast-v1 | `enforcementBlocks` | 10,000 | 13,700 | 9.3, least window that admits `bucketCapacity` qX = 137 |
| open-weights-standard-v1 | `failureLimit` | 27 | 45 | 9.1 |

The shared profile keeps 16 / 27: `scripts/check_spec.py` recomputes its
`failureLimit` from `failureLimitBasis`, and its `parameterHash` is pinned by the
x402 test vectors and the contract tests, so 27 / 45 cannot go there without a new
basis. The replay operating point is the shared one with `profile_file` and
`failureLimit` changed. `python3 experiments/replay/replay_profile.py` checks that
the committed pair equals the build (a test runs it); `--write` rebuilds it after
the shared files change. The envelope records the overrides, the base file and
whether the base is unchanged (`parameters.profile_overrides`).

`enforcementBlocks` enters the contract only in `FairBindCore._validateProfile`
(the rate condition `bucketCapacity * PPM + refill * enforcementBlocks <= maxRate *
enforcementBlocks` and, in a production build, `enforcementBlocks >=
judgmentDelayBlocks`) and in `parameterHash`. No settle, sampling, case or
release rule reads it, so the off-chain replay uses it only for
`profile_capacity_admissible`.

## Running

The reference directory holds `sellers_dune_top400.csv` and
`sellers_dune_all4400.csv`; the list directory holds `facilitators.csv` and, for
the replay period, `input_check_per_address.csv`.

```sh
# Input checks (row count, hash, time range, facilitator set, per-address tolerance;
# for the prior period also the burst statistic qX on its last seven days).
python3 experiments/replay/replay.py check-input --period replay_period \
    --settlements $LISTS/settlements_2026-09-08_2026-09-22.csv --reference-dir $REF
python3 experiments/replay/replay.py check-input --period prior_period \
    --settlements $LISTS/settlements_prior_14d_2026-08-25_2026-09-07.csv --reference-dir $REF

# List-only inputs, before the run (no replay quantity).
python3 experiments/replay/input_stats.py --settlements $LISTS/settlements_2026-09-08_2026-09-22.csv \
    --out $OUT/input_stats.json
python3 experiments/replay/baseline.py list-only --settlements $LISTS/settlements_2026-09-08_2026-09-22.csv \
    --reference-dir $REF --out $OUT/baseline_list_only
python3 experiments/replay/m1_predictions.py --r1 $R1/r1.py --reference-dir $REF --out $OUT/m1_predictions.csv

# Timing pass: full computation, writes only timing.json (rows, wall time, peak memory).
python3 experiments/replay/replay.py --settlements $LISTS/settlements_2026-09-08_2026-09-22.csv \
    --reference-dir $REF --qx 137 --conditions 1,2,3,4,5 --timing-only --out $OUT/timing

# Real run (only once the run is formally started), from a clean checkout.
python3 experiments/replay/replay.py --settlements $LISTS/settlements_2026-09-08_2026-09-22.csv \
    --reference-dir $REF --qx 137 --conditions 1,2,3,4,5 --out $OUT/run --design-record $DESIGN_DOC \
    --m1-predictions $OUT/m1_predictions.csv [--jobs 2] [--k-role default|certified]
python3 experiments/replay/rules.py $OUT/run [$OUT/run-certified-k] \
    --m1-predictions $OUT/m1_predictions.csv --out $OUT/rules.json
python3 experiments/replay/baseline.py compare $OUT/run --baseline $OUT/baseline_list_only.json \
    --out $OUT/baseline_compare.json
```

`--fold first|second` replays one half of the list with full buckets and writes
only the rejection columns (the cross-fit path; not used when `qX` comes from
the prior period). `--addresses reduced` replays groups A, B and C only.
`--alpha-upper` adds the fourth injection setting. `--draws` defaults to 1,000.

A run is `reportable` only when the working tree is clean, the list is the
registered replay-period list and its span equals `rate_blocks`, `qX` matches,
the conditions run are the registered set `run_conditions` (1-5, design 9.2), the
operating point is the registered replay operating point, agrees with its
profile and its base profile is unchanged, every group list hash matches
(including group C), and, with `--k-role default`, the failure limit of each
profile run equals the pre-certification default in `conditions.json`
(`k_default`, 27 / 45). The reasons are listed in `not_reportable_reasons`.
Before anything is replayed the run recomputes the nF and nR scales from the
reference aggregate over `rate_blocks` and stops if they differ from
`expected_scales` (design 9.5). `rules.py` and `baseline.py compare` refuse a run
that is not reportable.

The envelope records the design record under `inputs.design_record` and, as
common rule 3 of the design README names it, under `preregistration` (the same
object: path and SHA-256), the M1 prediction file and its hash
(`inputs.m1_predictions`), and every registered condition that was not run with
its reason (`conditions_not_run`). `rules.py` lists the conditions run and not
run, and evaluates R20-M1 only when the prediction file it is given has the hash
the envelope recorded.

## Design 2

`replay.py --design 2` switches the settlement replay to the rules of design 2 (amount cap, sampling in
proportion to the value, a unit bond from the failure limit, a sales cap per address, a hold period shorter than
the case horizon). Nothing of it is read without `--design 2`, and a design-1 run is byte-identical to the
registered run. The choices live in `design2.json`; the options are named in `parameters.options` and
`design2` of the run envelope. `--d2-edition 2` (the default) is the second edition of the rules,
`--d2-edition 1` repeats the first edition (`--tau`, one failure limit, a floor bond, windows from the first
block, hold periods 30,180 / 51,780 / 60,000, a burst multiplier instead of a sales cap).

Second edition (a run of condition 1, seed 0 on the Base tuning list):

```sh
python3 experiments/replay/replay.py --design 2 --vmax 0.2 --sales-cap auto-zero-reject \
    --settlements $LISTS/settlements_2026-09-08_2026-09-22.csv --reference-dir $REF --qx 137 \
    --conditions 1 --repetitions 1 --out $OUT/run
# the contrast: the cap is fitted on the 14 days before the window (no record: cap 10)
python3 experiments/replay/replay.py --design 2 --vmax 0.2 --sales-cap prior14 \
    --prior-settlements $LISTS/settlements_prior_14d_2026-08-25_2026-09-07.csv ...
# every v_max under both rules, resumable (exit status 3: call again)
python3 experiments/replay/d2_sweep.py --chain base --settlements ... --reference-dir $REF \
    --conditions-file experiments/replay/conditions.json --prior-settlements ... --out $OUT/sweep \
    --parallel 2 --time-limit 170
python3 experiments/replay/d2_report.py --columns $OUT/sweep/base_v*_* --json $OUT/columns.json --csv $OUT/columns.csv
```

| Switch | Meaning |
| --- | --- |
| `--vmax 0.1 / 0.2 / 1` (`--tau`) | amount cap v_max in USDC (D2-1). A settlement above it is rejected before the bucket and counted apart; the sampling rate of a row is `min(1, ceil(v / v_max))` in ppm (D2-2, D2-3) |
| `--sales-cap S` | the same cap for every address; `S` is on the grid 10, 30, 100, 300, 1000, 3245 * n (D2-7 (b)). Below 3245 the bucket is `q_S = max(1, round(137 S / 3245))`, `r_S = floor((S - q_S) 10^6 / Lambda)` ppm per block, `Lambda` = failure window + hold period; 3245 * n is the main bucket (137, 50,000 ppm) times n |
| `--sales-cap auto-zero-reject` | per address the least grid cap that rejects nothing in the replayed window itself (decision 93, main result) |
| `--sales-cap prior14` | the same rule fitted on the 14 days before the window; an address without a fitting record (value at most v_max) gets 10 (the contrast line) |
| `--sales-cap cross` | each half of the window runs with the cap fitted on the other half (a stand-in for the contrast where no earlier record exists) |
| `--d2-k`, `--k-w` | failure limit: a table by cap (`k_table` of `design2.json`, w = 0.015 or 0.004728, target 5e-7), `--d2-k 27` for one value, `--d2-k 10:5,30:7,...` for a table |
| unit bond | edition 2: `b = ceil((40/27) v_max / p0)`, `B = k(S) b` in atomic units; the deduction of one confirmed failure is exactly `b`; an address at 3245 n pays `n B`. `--bond-rule floor-fraction` is the first edition's `floor((40/27) k v_max / p0)` |
| `--hold`, `--failure-window` | edition 2: hold period = failure window = inconclusive window = 31,073 blocks of 2 s (`L_F + 500`, `L_F` = 30,573), converted to the chain's block time; the windows are fixed windows on multiples of their length in ledger blocks (`--window-align absolute`; `first-block` is the first edition) |
| `--chain`, `--block-time` | base, polygon or solana: block time and address case from `design2.json`; `--block-time` replaces the block time. Every duration of the profile is kept in seconds and converted to blocks (rounded up), refill rates per block scale with the block time |
| `--threshold-rounding` | edition 2 default `ceil` (D2-3); `contract` is the floor of the contract function |
| `--injection-settings` | edition 2 default: `main` (w = 0.004728) and `w_0.015` |
| `--confirm-delay case / settlement` | when an injected failure is confirmed: `case` (default) at the case opening plus the judgment and appeal horizon (7,512 blocks of 2 s); `settlement` at the settlement of the sampled entry plus the longest measured path (30,573 blocks), the sensitivity of D2-8. The draws are the same |

The operating point check runs in the design-2 mode of `controller.operating_point.check`: the hold period may
be below `caseHorizon`, it must cover the longest measured path `L_actual` (30,573 blocks in edition 2).
The replay has no purchaser dispute, no seal and no review: D2-11, D2-15, D2-16 and D2-17 change no replay
number. Only `FINAL(FAIL)` draws are confirmed failures; `FINAL(INCONCLUSIVE)` above the threshold (D2-6 (b))
is not in the model, so it is neither counted nor deducted. A tuning-period run is an implementation check,
not an evaluation.

The run envelope lists the complete fixed windows (`design2_windows`: failure windows from the end of the hold
period and judgment windows from the first block, with their first and last edge), the chain and its block time
(`design2.chain`), the hash of the list and, for `prior14`, of the prior list.

Other chains: `chain_inputs.py build --chain polygon --dir <daily files> [--prior-dir <daily files>] --out DIR`
joins `settlements_YYYY-MM-DD.csv.gz` files (checking them against `manifest.jsonl`), counts the recipients of
the list into reference aggregates and writes a conditions file with the group sizes of the chain (A is the top
1%). Run `replay.py --conditions-file DIR/conditions_<chain>.json --reference-dir DIR/ref --chain <chain>`.
Base58 addresses keep their case (`inputs.normalize`).

### Release cursor of rule edition 8 (`--release cursor8`)

`--release hold` (the default) is the release of rule edition 7: a sale is released `deferBlocks` after its
settlement, and nothing of the switch below is read. `--release cursor8` (design 2, second edition, with
`--freeze-scope detected-onward` and `--confirm-delay case`) releases by the seller's release cursor of rule
edition 8 (D2-39, `release8.py`): an epoch is paid when it is sealed (the block of its case opening on the replay's
prompt path), every sampled case of it is final (opening + `--r8-case-length`, default the confirmation delay of an
injected failure), every buyer window is closed (settlement + `--r8-buyer-window`, 1,860; with `--r8-bind-window`
also W_e = sample value block + w_b) and every earlier epoch of the address is paid. A condition met in block x
holds from x + 1; `--r8-keeper-delay` adds blocks to the cursor call; `--r8-open-offset` opens the case that many
blocks after the epoch start instead of the prompt path. `--r8-hold-window H_N` adds the held-settlement cap of
D2-42: a settlement reverts (the bucket is not consumed) while `ceil(q_S + r_S H_N)` accepted settlements of the
address are unpaid. Sampling, case openings, windows and the injected failures are the same as under the hold;
held funds, `H_formula` (with the value-weighted mean hold) and the frozen set follow the cursor (a failure freezes
every sale from its sampled sale up to the failure, none of which the cursor has paid). The observed rows add
`R8_ROW_COLUMNS` (hold-length statistics and histogram, revenue over one mean hold, cap rejections); the envelope
and `condition.json` add `release8`. `r8_deter.py` runs the fraud replay of `d2_deter_narrow.py` under the cursor
(variants `r8`, `r8_p035` and, as a check against the stored J7 output, `narrow7`). `test_release8.py` pins the
hold-mode outputs on the synthetic list to their hashes before the switch existed.

## Conditions as implemented

Seeds: `controller.scenario.run_seed(20260928, 'R20', condition, repetition)`.

| Id | Profile | Scale rule | q | Seeds |
| --- | --- | --- | --- | --- |
| 1 | data-api-fast-v1 | nF = max(1, ceil(rbar / r_fill)) | qX | 3 |
| 2 | data-api-fast-v1 | n1 = 1 | qX | 1 |
| 3 | data-api-fast-v1 | nF | q20 = profile `bucketCapacity` | 1 |
| 4 | data-api-fast-v1 | nR = max(1, ceil(rbar / r_max)) | qX | 1 |
| 5 | data-api-fast-v1 | n1 | q20 | 1 |
| 6-10 | open-weights-standard-v1 | as 1-5 | as 1-5 | 1 |

This run replays conditions 1-5 only (design 9.2); 6-10 are reported as not run
until the open-weights `sellerPenalty` is set from `B >= k * g * ceil(1/p)` (225
USDC at k = 45) and entered in the design.

`rbar` is the address's settlement count in the reference aggregate over
`rate_blocks` = 619,111 blocks (option W344). The bucket of an address at scale `n` has capacity `n * q` and refills
`n * refillPpmPerBlock` per block; it starts full. Injection settings (w = 3 w1²,
w1 = c(1 - h) + h alpha, h, c, alpha from the operating point): `main`,
`collusion_worst` (c = 1), `operator_is_verifier` (h = 1), each with reentry delay
0 and 1,800 blocks and claim probability 1 and 0.5, 1,000 draws per replay.

## Output

`OUT/run.json` (or `timing.json`): inputs with SHA-256 (list, aggregates,
conditions file, operating point, profile file, design record), code revision and
dirty flag, parameters (qX, q20, k per profile, draws, seeds, settings, the
named options below, whether each profile admits its bucket capacity), group
hashes, conditions, per-run wall time and peak memory, `reportable` and its
reasons. Per condition and seed, `condition-NN-seed-R/`:

- `addresses_observed.csv`: one row per replayed address (scale, q, attempted,
  accepted, rejected and rejection rate, `rbar_acc` and peak clock hour, mean
  value, H formula / time average / maximum, `nB` and `nB + H`, sample count,
  epochs with a settlement and sealed, judgment windows and those below
  `minJudgedCount`, by count and by settlements);
- `groups_observed.csv`: table R20-1 rows (rank 1, rank 2, ranks 3-44, B, C p90 /
  p75 / p50, the three nR-underassigned addresses, A, all replayed);
- `addresses_injection.csv`: per address, setting, reentry delay and claim
  probability: mean and 2.5 / 97.5 percentiles of freeze fraction, failures,
  principal and B/k loss, refunded and forfeited principal, revenue, loss over
  revenue, lost sales, refund time; the standard deviation of the freeze
  fraction, `rate_acc_per_block` and the sample count (R20-C1); per-window
  failures (by confirmation block), loss and revenue; per-window failures by the
  settlement block of their case with their standard deviation, and sampled cases
  by settlement window (R20-C2); formula value and its ratio; k(n) reach; seller
  fraud is not applicable;
- `groups_injection.csv`: table R20-2 rows, group sums per draw;
- `condition.json`: seed, q, k, B/k, failure-window edges, confirmation delay,
  sample rate, replay blocks and `rate_blocks`.

List cells (per-window values) are JSON arrays of numbers.

Result files contain no wall-clock values; rows and keys are sorted, so a run is
byte-reproducible (`--jobs` does not change them).

## Named options

Where the design leaves a choice open, the replayer implements one named option
and records it in the envelope (`parameters.options`): W344 (every rate over the
list span `rate_blocks`, 619,111 blocks, design 9.5), E0 (local block numbering), O-prompt (case opening at the first block
after the beacon), J-open (a case counts in its judgment window at its opening
block), W1 (judgment windows with at least one settlement), R-prompt (release at
`settled + deferBlocks`), X-drop (failures after the last block dropped),
S-model (suspension of `injection.seller_loss`), P-confirm (refund at the
confirmed failure), G-sum (group values are sums), F-half (fold boundary at half
the window), C2-settle (R20-C2 by the settlement window of each case, design
9.6), C1-tau (R20-C1 bound with the suspension length `1 + tau_re`), P-replay
(the replay profile). Offline sampling uses SHA-256 of a seeded per-epoch beacon in place
of `keccak256(SAMPLE_DOMAIN, blockhash, ...)`: the same Bernoulli(samplePpm)
selection, not the same entries as a chain run.

## On-chain cross-check (not run here)

The admission arithmetic is pinned by `test_bucket.py` against the contract
code and its tests. The optional cross-check replays a few addresses on a local
chain and compares:

1. `make deploy-local RUN_DIR=$R PROFILE=experiments/replay/replay-profile-v1.json`
   after raising `maxPurchaseValue` to the largest value of the list (reported by
   `check-input`) and, for qX conditions, `bucketCapacity` to `q`; record the new
   `parameterHash`. The replay profile's `enforcementBlocks` 13,700 admits
   `bucketCapacity` 137 (`profile_capacity_admissible` in the envelope); the shared
   profile's 10,000 does not.
2. Register one bond per address with `n * sellerPenalty` at the block the
   replay maps to the first list block (option E0), then submit each address's
   settlements at their local blocks in the seeded submission order
   (`engine.submission_order`), one synthetic buyer key per payer.
3. Compare, per address, the `Settled` count and the `RateLimitExceeded`
   reverts with `accepted_count` / `rejected_count`, and H from the
   `Settled` / `Released` ledger with `H_time_average` / `H_max`.
4. The injection cross-check (addresses of rank 1, 10 and 44, one seed) needs the
   verifier-directive harness: feed the drawn failures as verdict directives and
   compare freeze blocks and losses with `addresses_injection.csv`. Until then
   every injection row carries `onchain_crosscheck = not run`.

## Scale assignment

| Rule | Role | Scale of a receiving address |
| --- | --- | --- |
| `nF` | main condition | `max(1, ceil(rbar / r_fill))` |
| `nR` | secondary condition | `max(1, ceil(rbar / r_max))` |
| `n1` | control | 1 |

`rbar` is the address's mean settlement count per block over the replay period
(settlements over `rate_blocks`, the 619,111-block span of the list, option W344); `r_fill`
and `r_max` are the operating-point values (`refillPpmPerBlock` and
`maxRatePpmPerBlock` over `PPM`). A bucket's sustained capacity is `n *
r_fill`, so only `nF` admits the mean rate of every address: `nR` divides by
`r_max` and leaves an address whose mean exceeds `n * r_fill` rejected for
good (`under_assigned`). `nR` is reported beside `nF` to show what that
under-assignment does to rejections and to `H`; its under-assigned addresses
are reported apart.

## Burst capacity `qX`

`qX` is the p99 (nearest rank) over every receiving address of that
address's highest one-hour settlement count within a seven-day window
(`qx_statistic`). The population is every receiving address in the window,
not the replayed top 400. The same seven-day window is used on the period
before the replay and on each half of a cross-fit, so the two paths compute
the same statistic.

With the cross-fit, the two half replays feed only the rejection columns
(`rejected_count`, `rejection_rate`) and the checks that read them (R20-F3,
R20-M1). `H`, sample and epoch counts, windows below `n_min` and every
injection column come from one replay of the whole 14 days, run with the
larger of the two half values of `q` (`full_replay_q`, `column_source`).

## Input check

The extracted settlement list is compared with the aggregate query before the
replay starts (`input_check`). It is within tolerance when the row count
differs from the aggregate total by at most 0.1 percent and every address's
count differs from its aggregate by at most `max(1, 0.5 percent)`. The report
carries every per-address difference, their sum and their maximum. Outside
tolerance, the extraction is repeated once after checking the period
boundaries; if it is still outside, the new list becomes the reference and
ranks, groups and scales are recomputed from it before the replay. The check
looks at the extraction only, never at replay results.

## Injection model

The replay's verifier passes every sampled case, so no freeze happens in the
replay itself. Wrongful confirmed failures are injected afterwards, offline,
per seller (`draw_failures`, `seller_loss`, `injection_row`):

1. Each sampled case becomes a wrongful confirmed failure with probability
   `w`, confirmed at its opening block plus `judgmentHorizon + appealHorizon
   + 1`.
2. At a confirmed failure `f` the account freezes. The **new** principal loss
   is the value of every accepted entry settled after the previous freeze
   block and at or before `f` that is still unreleased at `f` (`settled +
   T_hold > f`). A later failure moves `freezeBlock` but creates no new pool,
   so an entry is lost at most once. The first failure counts every
   unreleased entry.
3. Each failure also deducts `B / k` (the per-failure share).
4. The seller is suspended from `f` and re-enters at `f + 1 + tau_re`; `tau_re`
   is an injected setting (0 and 1,800 blocks). A settlement in between is
   rejected and reported as lost sales, not as loss.
5. R20-C3: the principal loss of a seller never exceeds its accepted revenue;
   a draw that breaks this is an implementation error.

Every injection row carries the per-seller formula value

```text
1 - exp(-s * w * rbar_acc * T_hold) + s * w * B / (k * vbar)
```

(`formula_value`), with `rbar_acc` the number of the seller's settlements
accepted in the replay divided by `rate_blocks` (619,111 blocks, W344), not by
the span from its first to its last settlement, and `vbar` the mean value of
those settlements. The first term is the frozen share of
settlements, the second the share the `B / k` deduction adds; only the second
can take loss over revenue above one. R20-D1 compares the Monte Carlo mean of
loss over revenue with this value seller by seller (`ratio_to_formula`). At
the data API bucket rate (0.05 per block) the first term is 0.758.

## Checks R20-C1 and R20-C2

R20-C1 (design 5.5, 9.7) uses the bound of manuscript v1.5 section 6.4: the
expected frozen fraction is at most `s * r * w * tau_re`. In the injection model a
failure suspends the seller from `f` to `f + 1 + tau_re`, so `rules.py` takes
`tau = 1 + tau_re` (option C1-tau) and `r = rbar_acc`. Per address, setting and
reentry delay, the check fails when the Monte Carlo mean of the freeze fraction
exceeds the bound by more than 1.96 standard errors; rows with a bound above 1
are left out.

R20-C2 (design 9.6) counts each drawn failure in the failure window of its case's
settlement block and compares the Monte Carlo mean per window with `s * w *
(accepted settlements of the window)`, with the 95% interval of the mean.

Both checks compare with `s` times the accepted count, so a seller whose sampled
count happens to differ from `s` times its accepted count by more than the
injection noise can be flagged with a correct implementation. Each result also
carries `conditional_on_samples`, the same comparison with the replay's sampled
cases in place of `s` times the accepted count; it does not change the verdict.

## List-only computations

These read the list and the reference aggregates, never replay results.

- `input_stats.py` (design 9.8): count and value of the settlements strictly
  above the data-API `maxPurchaseValue` (10,000 atomic units), their shares, and
  the totals.
- `m1_predictions.py` (design 9.7): per group A address, the rejection rate of
  `simulate_seller` of the R1 script (run unchanged; its unused helper import is
  stubbed) with refill `n * r_fill` per hour and capacity `n * qX`, `n` the nF
  scale. The CSV has the columns `rules.py --m1-predictions` reads; the JSON
  beside it records the script hash and the addresses whose `active_hours` the
  script clamps to its 336-hour window. Pass the file to the run
  (`--m1-predictions`) so that its hash is in the envelope.
- `baseline.py list-only` (design 9.9): per replayed address
  `B_vel(a) = k * g * (ceil(1/p) + ceil(r_a * L))` with `r_a` the highest
  clock-hour count in the list over 1,800 blocks, `L = T_case` (58,994), `g` and
  `p` of the data-API profile and `k` = 27; the variants V-mean (`r_a` = count over
  `rate_blocks`), V-path (`L = L_actual`, 29,680) and V-amount (`vbar_a` in place
  of `g`, on both sides); the FairBind values `n_a * B` and `n_a * k * g *
  ceil(1/p)` (nF scales); group sums for rank 1, rank 2, ranks 3-44, A, B and all
  replayed addresses; median, minimum and maximum of `B_vel(a) / (n_a * B)`. All
  amounts in atomic units. `baseline.py compare RUN_DIR` adds `n_a * B + H_max`
  of condition 1 (per seed and the seed mean) from a finished reportable run.

## Registration R11 (rule edition 10 candidate v0.6 and later)

R11 replays the rule as written for tiers 0 and 1 with s = 1. Nothing of it is read without `--release fixed10`,
and with the switches below at their defaults a `fixed10` run gives the R10 output (plus the new columns).

| Switch | Meaning |
| --- | --- |
| `--sales-cap none` | no bucket: every settlement that reaches admission is admitted (v0.6 R2 (a) has no count limit). `auto-zero-reject` is the labelled legacy variant (the bucket of edition 7, as in R8 and R10). Needs `fixed10` |
| `--r10-accept-over-cap` | a sale above V is admitted and sampled with probability 1 (R10 sensitivity, R11 main setting) |
| `--r10-dispute-from anchor` | every dispute window runs to A_e + T_c (v0.6 R5 (c)); `settlement` (default) is the R10 path, T_c from the settlement |
| `--r10-seller-epoch-k k` | k consecutive profile epochs form one seller epoch (v0.6 R1 (a), R6 (a)); the cursor passes the seller epoch when conditions (0) to (3) hold for each of its profile epochs and pays every sale not accepted at that block; an accepted sale is paid at the anchor deadline of its own profile epoch |
| `--r10-save-sales` | `sales.npz` and `sales_addresses.json` per condition: block, value, payment block, epoch, list row, sampled, accepted and signed of every accepted sale |
| `--preset r11-main` | `--release fixed10 --r10-accept-over-cap --sales-cap none --r10-dispute-from anchor --freeze-scope detected-onward --r10-save-sales`; a switch given explicitly wins |

New per-address columns of a `fixed10` run: `admission` (`bucket` or `unlimited`), `H_cont_sum_blocks` (exact
numerator: sum over the sales of value times the blocks of the window in which the sale is held, a sale not paid by the
last block held to it), `H_cont_average` (over every block of the window, `[first block, last block]`),
`H_cont_average_from_hold` (over `[first block + hold, last block]`, the span of the hourly readings that give
`H_time_average`), and `has_revenue` (accepted value above 0). `condition.json` adds `admission`,
`addresses_with_revenue`, `sales_file` and `preset`. With over-cap acceptance the value-cap rejection columns are
written as 0 (R10 left them empty).

`r11_compute.py` aggregates the R11 outputs (registration sections 5 to 9): held money under the three definitions
(continuous average over `[first + hold, last]`, the main one; over the whole window; the hourly average of R10),
baselines over the replay's sale set (sales above V included), the sets S1r (judgement set), S1, S2, S3, S1a, S2a, the
k table, both fraud replays, the gates G0 to G6 and the decision rules JA11, JD11, JM11 (replay side), JX11. It takes
`--docs` (the research repository's docs/ for the stored edition-7 outputs, E8b and the R10 aggregates) and
`--registration` (the sealed registration, its `.sha256` beside it). `run_r11.sh` is the cloud driver (`gate`,
`prepare`, `run`, `status`): G0 checks with `git ls-remote origin main` that the commit carrying the sealed
registration is on origin/main before anything runs; steps are resumable and the sensitivity runs go in parallel;
`sales.npz` stays in the scratch directory and its SHA-256 goes into `r11_sales_sha256.txt`. `r10_deter.py run` also
takes `--anchor-delay` (a_A; 120 under v0.7c, 100 in R10). Tests: `test_r11_compute.py` (hand-computed fixtures, the
gates on real synthetic output, the G0 gate against a local bare origin).

`r11_k_sweep.py --k 1,2,3,6 --out OUT -- <replay.py arguments>` runs one `replay.py` per k (resumable) and writes
`k_sweep.json` / `k_sweep.csv` with the held money and hold lengths per k over every address and over the addresses with
revenue. `r10_deter.py run` takes the same admission and release switches (`--sales-cap none`, `--accept-over-cap`,
`--seller-epoch-k`, `--dispute-from`) so that the fraud replay can use the main setting. Tests: `test_r11.py`.

## Registration R12 (cost setting against deployable bonds)

R12 adds no change to the replayer; it adds three files. `r12_compute.py` aggregates the replays of the cost setting
(V 1, M_e - A_e = 31 blocks, w_b 1,800, seller epoch multiple k in {1, 2, 4, 8, 16, 32}) and of a bridge run (the R11
main setting at V 1, k = 1, whose `addresses_observed.csv` must equal R11's byte for byte), picks a per-seller k from
the release cost and the capital cost of the held money, and compares FairBind with a history bond (twice the largest
daily revenue of the 14 days before, times the lag), a declared rate-cap bond (rejecting and unsecured variants) and
the R11 ceiling: locked money, the per-seller worst uncovered exposure against the bound V per seller, time averages,
and the buyers' dispute-fee reserve for the open purchases. Every number the registration fixes sits in one JSON block
of the registration (`json r12-registered`) and in `REGISTERED`; every command first checks that the two are equal key
by key, `print-flags` gives `run_r12.sh` the replay flags from that block, and records are compared whole
(`compare_record`), so that an expectation cannot silently drop a key. `selfcheck` runs the real replayer with the
registered flags on the synthetic list of `test_replay` and the whole aggregation before any window is replayed.
`test_r12_compute` holds the synthetic tests (brute force of the exposure, the rate-cap admission, the numerators from
`sales.npz`, the k choice in rationals, the day-coverage gate of the prior list, the run-record checks).

    bash experiments/replay/run_r12.sh prepare    # S0, tests, S1 (synthetic selfcheck), window and prior lists
    nohup bash experiments/replay/run_r12.sh run > /dev/null 2>&1 &
