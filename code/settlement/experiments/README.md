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
