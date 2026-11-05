# Experiments

This directory will contain reproducible FairBind evaluation runners and analyses. It may reuse statistical components from `agent-payment-arena` at the pinned revision.

The experiment controller obtains ground truth from scenario definitions and injected faults. Runtime subjects cannot read that ground truth. Every result records code, upstream revisions, parameters, seed, sample sizes, and creation time.

## Scenario controller

`controller/` runs the fault and attack scenarios in `scenarios/` against the
six-process deployment and writes one result envelope per run. See
[`controller/README.md`](controller/README.md). The dry run needs no chain:

```sh
python3 experiments/controller --dry-run --format text
```

## Operating point and baselines

`operating-point.json` holds the one set of values (g, v, p, L, rates, ...)
that the controller, the scenarios and the baseline configs in `baselines/`
read. See the "Operating point" section of the controller README.

## Settlement replay rules and predicate calibration

`replay/` fixes the rules the R20 settlement replay will be computed with: the
offline injection model (each entry lost at most once), the per-seller formula
value, the `nF` and `nR` scale rules, the `qX` burst statistic and the input
check tolerance (see [`replay/README.md`](replay/README.md)); the replayer
itself is not written yet. `calibration/c1-config.json` fixes the C1 predicate
study's joint tolerance calibration, near-tolerance wrong-answer strata and
intervals (see [`calibration/README.md`](calibration/README.md)); no C1 code
exists yet.

## Metric definitions

`metrics.md` defines every metric a scenario may name: formula, unit and the
log or event it is computed from.

## Hold-period grid analysis (I6)

`i6_analysis.py` applies the decision rules of `scenarios/I6.yaml` (`analysis`: conditions, Holm
families, pruning) to the result envelopes and observation documents of I6 runs. It reads every
`results/<run_id>.json` below `--runs` (any number of controller output directories), the run's
`runs/<run_id>/observations/collector.json` (or, without it, `collector.jsonl`, in which case the
rules that need per-sale rows report their fields as absent) and, when present,
`runs/<run_id>/ledger.json` for the sealed epochs of the pooled detection counts. Run it from a
clean checkout and write outside the source tree:

```sh
python3 experiments/i6_analysis.py --runs /path/to/i6-output --scenario experiments/scenarios/I6.yaml \
    --out /path/to/i6-analysis
```

- Smoke and non-reportable runs are dropped and counted; failed runs are counted per cell. A
  reportable run is outside the premise when an applicable `fault_observed` item is not ok,
  `injection_draw_mismatch_count` is positive, its keeper delay sum exceeds the keeper margin (not in
  M4-worst) or it is listed in `--manual-exclusions` (`{run_id: reason}`); such runs still enter
  I6-F11a and I6-F11b.
- Every threshold comes from the run's recorded profile and operating point (k, B, g, p, s, h, alpha,
  beta, c, q, r_fill, T_hold, T_case, marginBlocks, T_min, T_catch); runs of different operating
  points (the envelope's `operating_point.sha256`) form separate rows and separate Holm families.
  `threshold_checks` compares the computed values with the numbers the rules state and flags a
  difference.
- Means: run-bootstrap percentile intervals (`--resamples`, default 10,000; fixed seed
  `--bootstrap-seed`, default 20260928) and one-sided bootstrap p values; proportions: exact
  (Clopper-Pearson) intervals and exact binomial tails; Holm at 0.05 per family.
- Outputs: `i6_results.json` (per cell: runs found, failed, excluded and why, statistics, thresholds;
  per condition: families, members, verdicts, evidence; completeness: missing repetitions and absent
  fields per rule), `i6_tables.md` and `table_<name>.csv`. The same inputs give byte-identical files.
- Named options cover the readings a rule leaves open: `--certify-bound`, `--open-episodes`,
  `--f3-f6-statistic`, `--f6-rule`, `--f2-episodes`, `--f2-bound`, `--f12b-scope`, `--pc-episode`, `--p-star`,
  `--v-rounds`, `--ignore-fault-item`.

The tests (`test_i6_analysis.py`) run in `make i6-check`.

## Public collector

`collect_public.py` collects public HTTP responses (including 402) or fixed-range
contract logs. It never signs or submits transactions. Run from a clean checkout
and select a new output directory outside the source tree.

```sh
python3 experiments/collect_public.py --output /tmp/new-public-snapshot http https://example.test/resource
python3 experiments/collect_public.py --output /tmp/new-log-snapshot logs https://example.test/rpc --address 0x1111111111111111111111111111111111111111 --start 100 --end 199 --span 20
```

Replace example URLs and the address with verified public sources. Only
authentication-free sources are supported by this workflow. Logs remain labeled
`unclassified-contract-events`; identifying x402 needs an independent transaction
and facilitator filter. A successful collection is not a completed evaluation
workload. Manifests preserve revisions, parameters, timestamp and payload hash.
The collector tests run as part of `make check`.

## Open-weights execution binding

`inference_binding_run.py` commits a model run into the class-2 receipt
commitment, re-executes it as a verifier, and checks missing-trace, int8-rounding
and swapped-model cases. `--synthetic-seed` uses a seeded random checkpoint for an
offline smoke run; its results describe the pipeline, not a trained model. Steps
and hardware for an 8B-class run are in `runtime/inference/README.md`.
