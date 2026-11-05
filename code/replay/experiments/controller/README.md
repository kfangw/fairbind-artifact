# Scenario controller

The controller reads `experiments/scenarios/*.yaml`, expands each parameter
sweep, derives a service profile per run, launches the six processes (anvil,
keeper, verifier, facilitator, seller, buyer) from a manifest, injects the
scenario's fault at the named process, and writes one result envelope per run.
It uses the Python standard library, and PyYAML when installed; otherwise
`yamlsubset.py` parses the block subset the scenario files use.

```sh
python3 experiments/controller --dry-run                      # validate all scenarios, print the plan as JSON
python3 experiments/controller --dry-run --format text --only D1,D2
python3 experiments/controller --manifest local.json --output /tmp/new-runs --only F1,S2
python3 experiments/controller --manifest experiments/controller/i6-manifest.json --run-list hold-period-grid \
    --seed 20260928 --output ./runs/i6 --shard 0/2 --port-base 20000 --skip-existing
```

## Operating point

`experiments/operating-point.json` is the only place that holds `g`, `v`,
`pi`, `h`, `beta`, `alpha`, `c`, the detection ceiling `p`, `L`, `delta_F`,
`L_min`, `caseHorizon`, the hold period, `failureLimit`, the rate-cap fields
and the measured rates, each with its source and status (design, assumption,
derived, measured). At start the controller recomputes every derived entry
from the selected profile (`--profile-name`) and stops on a mismatch
(`controller/operating_point.py`, `check`). Scenario parameters and baseline
configs name these values instead of copying them:

- block expressions over `L`, `L_min`, `delta_F`, `caseHorizon` and
  `hold_period` (for example `L_min/2` or `(delta_F+L)/2`), floored to a block;
  the block symbols are recomputed from the derived profile of each point, so a
  deadline override moves them;
- value expressions over `g`, `v`, `p`, `pi`, `h`, `beta`, `alpha`, `c`,
  `g_over_p` and `failureLimit` (for example `g/(2*p)`);
- `rate:<name>` for a named rate (`top_seller_14d_mean`,
  `top_seller_active_hour`, `top_seller_peak_hour`, `peak_hour_p99`,
  `peak_hour_max`), converted to settlements per block;
- `op:<expression>` inside a baseline config (`experiments/baselines/`).

Every plan entry and result envelope records `operating_point` (path, SHA-256,
profile and values), and a plan entry for a baseline arm records the resolved
`baseline` config.

`--dry-run` validates every scenario file (and the manifest when given) and
prints the planned runs: seed, resolved parameters, profile overrides, the
controller actions, the directives each process receives, unresolved symbols,
profile admission violations and the reasons a run cannot start. It launches
nothing and needs no chain. The tests use this mode.

## Plan

- Every combination of swept parameters is one point; unswept parameters take
  their default. Each point runs the scenario's `n_seeds` times, each with a new
  seed derived from `--seed`, the scenario id, the point and the repetition;
  `--repetitions N` overrides `n_seeds` for every scenario. What a seed changes
  (the buyer key `k` of each purchase, the settlement order inside a block and
  the verifier's per-assignment behavior draw) is `SEED_EFFECTS` in `runner.py`; the buyer receives it in its directive under
  `randomness`. See `experiments/scenarios/README.md`, Randomness.
- Deadline parameters (`responseBlocks`, `claimBlocks`, `serveBlocks`,
  `anchorBlocks`, `judgeBlocks`, `appealBlocks`), `epochBlocks`,
  `maxAssignments`, `dispute_deposit`, `bucket_capacity_q`,
  `refill_rate_lambda_r` and `auto_recheck_prob_pi_v` override the profile.
  When such an override lengthens the case horizon, retention, claim window and
  deferral are raised to it.
- `D_holding_blocks` is an expression over the operating point (`L_min/2`,
  `delta_F`, `(delta_F+L)/2`, `L`, `caseHorizon`, ..., or the hold-period
  grid names `T_min`, `T_stop`, `T_catch`, `T_case`, `T_hold`, which alias
  `L_min`, `delta_F`, `L`, `caseHorizon` and `hold_period`; `keeper_margin` is
  `hold_period - caseHorizon`). Below `caseHorizon` it
  sets `deferBlocks`, `retentionBlocks` and `claimWindowBlocks` to `D` (release
  needs both `releaseBlock` and `retainUntil` to pass, and the claim window must
  equal retention) and sets `freezeOnInitialFail` to `true`, so the freeze
  lands at the initial `FAIL` (the `delta_F` of the sweep; the override build
  requires the flag below the case horizon); `failureWindowBlocks` and
  `inconclusiveWindowBlocks` keep their profile values. Such a run is marked
  `override_used: true`, records
  `override_skipped_checks` (copied from `OVERRIDE_SKIPPED_CHECKS` in
  `controller/profile.py`, the single list of checks the test build
  `contracts/test/AdmissionOverrideRegistry.sol` skips), and is refused unless
  `--allow-inadmissible-profile` is given. A point that violates any check not
  in that list is blocked. At or above `caseHorizon` no override is used: the
  admissible profile runs unchanged, or with the three fields raised to `D` when
  `D` exceeds the profile hold period; with `exact_hold: true` (I6) a `D`
  between `caseHorizon` and the profile hold period lowers them to `D`, which
  is still admissible. The flag reaches the runtime as the
  derived profile document's top-level `admissionOverride` and as
  `FAIRBIND_ADMISSION_OVERRIDE=1` in every process environment, including the
  deploy step's, which then deploys the override build
  (`scripts/local_deploy.py --admission-override`). The grid itself is in
  `experiments/scenarios/README.md`, Deferral grid.
- `P_S_reserve: profile_penalty_floor`
  sets `sellerPenalty` to the expected penalty floor for that deferral and
  the capped rate. `cap_enabled: false` is the `disable_cap` transform
  (`controller/profile.py`): it raises the bucket and rate fields so the cap
  does not bind while the rate condition still holds; there is no contract
  switch for it, and with the cap off a run's exposure is computed from the
  settlement rate actually observed and the run asserts
  `rejected_settlement_count == 0`.
- Any other parameter is passed to the faulted process in its directive
  (for I6: `scale_factor`, `keeper_delay_budget_blocks`, `Lambda_cheater`,
  `seller_role` and `honest_top_up_policy`).
- `--run-list hold-period-grid` plans I6, the hold-period grid of the ADR 0021
  review as revised by the V2 review; it is validated with the other scenarios
  but is not part of the main run and is not run yet.
- A scenario may replace the full product of its sweeps by named `cells`
  (a mapping from cell name to `set`, `sweep`, `repetitions`,
  `min_repetitions`, `rate_class` low or high, `role` cheater, honest,
  positive_control, finite or availability, and `profile`). A finite cell runs
  on the normal path with a prompt keeper at `rate:mean_14d_p99_top400`; an
  availability cell runs on the worst path and sets `assignable_verifiers`;
  only a finite cell that serves honestly afterwards may set `injection:
  honest_error_off`. The plan is then the union of the cells;
  each point carries its cell name, runs its cell's `repetitions` (unless
  `--repetitions` overrides it), and a cell with a `profile` other than the
  selected `--profile-name` (the data API profile when it names none) is not
  planned. An optional `analysis` block records falsification conditions,
  Holm families and the pruning rule; the controller checks that they name
  existing cells, that a family keeps one rate class and that pruning lists
  only low-rate cells with a floor not above their counts. It applies no
  verdict.
- `judgment_path: worst` adds a `worst_path` block to the directives of the
  verifier, seller, keeper and buyer (`controller/worstpath.py`). It applies to
  the case of every sampled bad sale (the sample stays the contract's s-random
  draw, so the detection probability per bad sale on this path is s): the
  seller anchors at the anchor deadline; in the initial stage the first two
  assignments deliver FAIL at the judge deadline, the seller requests evidence
  at the appeal deadline and the assignment is voided by `timeoutEvidence` in
  the block after the evidence deadline, and the last one delivers FAIL, the
  verifier discloses its evidence at the evidence deadline (only the verifier
  holds the envelope; `discloseEvidence` admits any sender) and the seller
  appeals at the renewed appeal deadline; in the review stages all but the
  last assignment time out; every assignment redelivers at the deadlines; the
  party review overturns and the tiebreak confirms; every review seal lapses
  once; the buyer opens no dispute on the sampled sale and claims only after
  the case is final. The plan entry records `worst_path_schedule`: the
  per-term budgets the path can spend and their sum `path_budget`, and
  `margin_unspent` (`marginBlocks`, which no actor spends);
  `path_budget + margin_unspent = caseHorizon`. A worst-path case ends at the
  latest `caseHorizon - marginBlocks + kappa_Sigma` after the bad settlement;
  its actual length `L_actual` is measured on the contract by
  `contracts/test/WorstPathLength.t.sol` (29,680 and 91,180 blocks). The
  services carry the blocks out (`services/*/README.md`, "Worst-path
  directive"); the service harness dry run
  (`services/internal/integration/worstpath_test.go`) reproduces `L_actual` on
  Anvil (below, Dry run).
- `L_actual` and `L_actual_min` are block symbols only once `L_actual_blocks`
  of the profile is recorded in `experiments/operating-point.json` (`value`
  the longest and `min` the shortest measured path; `min` defaults to
  `value`). With the value `null` every expression that names them (the I6
  positive controls use `L_actual_min`, M4-worst uses `L_actual`) stays
  unresolved and the point is blocked.
- `freeze_on_initial_fail: false` keeps the production freeze timing on an
  override point below `caseHorizon` (the I6 positive control); `true` on an
  admissible point is blocked.
- `Lambda_cheater: bucket_max` resolves to `scale_factor * refillPpmPerBlock /
  PPM` of the profile before any cap transform (the sustained bucket rate), and
  `bucket_max_x10` to ten times that.
- A run is blocked when a parameter is still symbolic (supply it with `--set`),
  when it needs a baseline arm (`arm` other than FairBind, `bond_regime:
  full_collateral`), or, unless `--allow-inadmissible-profile`, when the derived
  profile violates `docs/spec/profile-v1.md`.

## Fault injection

| Mechanism | Fault kinds | What the controller does |
| --- | --- | --- |
| restart | `process_restart` | Watches `events.jsonl` of the process for the trigger event, sends SIGKILL to its process group, waits the restart delay in blocks, and starts the same command again. |
| proxy | `drop_response`, `withhold_response`, `delay_response` | Runs an HTTP proxy between buyer and seller. Requests are always forwarded; 2xx responses are dropped or held for `response_delay_blocks` blocks; 402 challenges pass. |
| directive | all other kinds, and `withhold_response` | Writes `{kind, parameters, seed}` to the faulted process's directive file. The process implements the behavior. |

A process that receives no fault directive still gets a directive file with
`kind: null` and the sweep values it needs (for example retry counts). A
controller-side fault is not described to the process.

A finite attack is set by two parameters, `finite_attack_cheat_sales` (m) and
`finite_attack_after` (`serve_honestly`, `stop_selling` or `request_exit`);
the seller alone receives the `finite_attack` block of `finiteattack.py`, and
the plan entry records it as `finite_attack`. The episode columns
(`finite_attack_detection`, `seller_gain_released`, `buyer_refund_amount`,
`buyer_refund_blocks`, experiments/metrics.md) come from
`fairbind-case-paths -finite-attack m`, which takes the first m settled sales
of the seller as the cheated ones; `finiteattack.episode` is the same
reduction for rows the controller assembles itself.

The hold-period harness (fault kind `hold_period_grid`) adds four directive
blocks and a deploy block to every plan entry (`runner.harness_plan`):

- verifier `judgment_injection`: `h`, `alpha`, `beta`, `c` of the operating
  point, `draw`, `applies_to: every assignment`, `honest_error_off`
  (true only with `injection: honest_error_off`, where alpha = c = 0);
- seller `seller_policy`: `role` (cheater, honest, finite),
  `appeal_initial_fail`, `scale_factor`, `reentry`
  (`top_up_to_scale_then_reinstate`, or `none` for a finite attacker) and
  `top_up` (`after_each_deduction_to_scale` for the honest seller, `none` for
  a finite attacker, `before_reentry_to_scale` otherwise; `reentry` is `none`
  exactly when `top_up` is);
- buyer `workload`: `rate_per_block`, `scale_factor`, `dispute_sampled_sale`,
  `appeal_initial_pass` (honest arm only), `claim` (`after_case_final` on the
  worst path, else `when_claimable`), `end` (`episodes` 2, `finite_attack`,
  `honest_windows` 5, or `worst_path_cases` 30 by cell role) and `max_blocks`
  (null: no block cap, the wall-clock limit of the run manifest applies);
- buyer `clock`: the progress files it waits on, `stop_offsets` [-1, 0] and
  `kappa`;
- `harness` (plan entry): `sellerBondScale`, `registeredVerifiers`,
  `assignableVerifiers`, `verifierBondAtomic`, `spareVerifiers`, `cheatBody`,
  `pollMs` for the deploy step (`profile.harness`).

Every plan entry and the envelope's `operating_point` record
`operating_point_k` (`k`): the value of `failureLimit` and the operating-point
entry it was read from. Example directive files of every block shape are
generated from the plan into `services/internal/directive/testdata/i6` as
`<cell>-<process>.json` (`test_i6_plan.py`; regenerate with
`FAIRBIND_WRITE_I6_FIXTURES=1 make i6-check`). The Go parser tests read each
of them for the process in its name. Files there whose name starts with
`invalid-` or with a role name are hand-written Go fixtures; the generator
leaves them alone.

## Processes and manifest

`local-manifest.example.json` shows the format. `processes` must define all
six roles. Commands and `env` values may use `{proc_dir}`, `{directive}`,
`{profile}`, `{seed}`, `{rpc_url}`, `{observations}`, `{events}`,
`{seller_url}` (the proxy address when a proxy is configured), `{repo}`,
`{run_dir}` and the port placeholders; literal braces are written `{{` and
`}}`. The port placeholders come from the port base P (`--port-base`, default
8545): `{rpc_port}` P, `{base_port}` P + 10 (the deploy step's
`FAIRBIND_BASE_PORT`: facilitator, seller, buyer, second buyer), `{seller_port}`
P + 11 (the seller listener) and `{proxy_port}` P + 80; `rpcUrl` and the proxy
`listen` and `upstream` may use only these four. `{ground_truth}` (the ground
truth file of the run) is accepted in the `collector` command only; the
manifest check rejects it anywhere else, and no other process receives it. A
command argument or `env` value that is exactly `$NAME` (upper case) is
replaced by that environment variable; a run stops before it starts when one is
unset or empty. `ready` is `"rpc"`, `{"file": path}` or `{"seconds": n}`. The
optional `deploy` command runs after anvil is ready and receives the derived
profile; its `parameterHash` is stale and must be recomputed by the deploy
step. The optional `collector` runs after the workload, against the live
chain (below).

`i6-manifest.json` runs the hold-period harness: Anvil 1.5.1 from
`$FAIRBIND_ANVIL_151` (`--port {rpc_port} --chain-id 31337 --silent
--prune-history --slots-in-an-epoch 0`, no interval mining; the deploy
step's `FAIRBIND_ANVIL` names the same binary), the keeper (`-lockstep`), the verifier pool
`fairbind-verifier-pool` (every registered verifier in one process), the
facilitator, the seller, the workload driver `fairbind-workload` as the buyer,
and the collector `experiments/collect_run.py --rpc-url {rpc_url} --run-dir
{run_dir} --ground-truth {ground_truth} --out {observations}`. The keeper,
verifier pool and seller write `{proc_dir}/progress.json`
(`{run_dir}/proc/<name>/progress.json`), which the workload driver's clock
reads. The clock mines only after each has reported the head, so each must
act on the head itself: with `--slots-in-an-epoch 0` Anvil's finalized block is
the head (the verifier discovers assignments at the finalized block), and the
keeper runs in lockstep mode (views at the latest block, calls timed to the
next). `--prune-history` without a count keeps only the latest state: with a
count (256), Anvil 1.5.1 slows down with the height (20,000 empty blocks take
4 s from genesis and 23 s from block 40,000) and holds about 30 KB per block;
without one it mines about 25,000 blocks a second at any height and holds about
2 KB per block. Every service reads the latest state (the keeper and verifier
pin the latest block hash and retry the pass when the head moved meanwhile).
Processes start in their own `{proc_dir}`, so the Go commands use
`go -C {repo} run` and the scripts `{repo}/...`.

The example's deploy step is `scripts/deploy-local.sh {profile} {proc_dir}`.
It attaches to the manifest's Anvil through `FAIRBIND_RPC_URL`, deploys the
production build (the admission override test build when
`FAIRBIND_ADMISSION_OVERRIDE=1`), creates the profiles of the derived document
with a recomputed `parameterHash`, registers verifiers, a bond account and a
seller, and writes `deployment.json` and one configuration per service under
`{proc_dir}/services/`. The keeper, verifier, facilitator and seller commands
of the example read those files (`{proc_dir}` of a process is a sibling of the
deploy step's directory). See `deploy/README.md`.

Launch order is anvil, deploy, keeper, verifier, facilitator, seller, buyer. The
buyer is the workload driver: the run ends when it exits, when any other
process exits (a process the controller restarts as a fault is exempt), or at
`runTimeoutSeconds`. Then every process but anvil stops in reverse order
(SIGTERM, then SIGKILL after `stopTimeoutSeconds`); if the run completed, the
collector runs while anvil still serves the chain; anvil stops last. A nonzero
buyer or collector exit fails the run. The envelope records `status`
(`completed`, `failed` or `timeout`), `ended_by` (`workload_exit`,
`process_exit`, `wall_clock_limit`, `deploy_failure` or `controller_error`)
and the reason in `error`; a run that did not complete gets no collector run.

Each process (and the deploy step and the collector) gets `FAIRBIND_PROC_DIR`,
`FAIRBIND_DIRECTIVE`, `FAIRBIND_PROFILE`, `FAIRBIND_SEED`, `FAIRBIND_RPC_URL`,
`FAIRBIND_OBSERVATIONS`, `FAIRBIND_EVENTS`, `FAIRBIND_SELLER_URL` and
`FAIRBIND_RUN_DIR`, on top of the controller's environment (so
`FAIRBIND_ANVIL` and `FAIRBIND_ANVIL_151` pass through). The keeper, verifier, facilitator, seller and
buyer services exist (`services/*/cmd`). The keeper, verifier, seller and
buyer read the `worst_path` block of their directive file and the keeper its
`keeper_delay` block (`-directive`, default `FAIRBIND_DIRECTIVE`); no service
carries out another fault kind or reports trigger events yet, and the buyer is
a daemon with a control API rather than a workload driver that exits; the
example's buyer command is still a placeholder. The example runs verifier 1 only, although the deploy
step registers `minVerifiers` verifiers.

The controller only collects observation rows; the services and the collector
emit them. For I6 the harness must emit, per effective-detection case of the
observed seller (final `FAIL` or `UNSERVED`), `case_path_blocks` (settlement
block to confirmed-failure block) and `case_path_minus_keeper` (the same minus
the keeper delays on the case), and per episode `first_detection_index`
(`experiments/metrics.md`); I6-F11 and the positive-control check read them.
`services/casepath/cmd/fairbind-case-paths` computes `case_path_blocks`,
`keeper_delay_sum_blocks`, `case_path_minus_keeper` and, for a worst-path run,
`worst_path_case_blocks` and whether each case followed the worst path, from
the chain and the keeper's call log (every sent call carries its due block);
`first_detection_index` needs the ground truth of the bad sales and is not
emitted yet.

## Dry run

`TestWorstPathDirectiveDataAPI` and `TestWorstPathDirectiveOpenWeightsTiming`
(`FAIRBIND_INTEGRATION=1`) deploy a profile with forced sampling, start every
service with the worst-path directives, settle one purchase in the first block
of an epoch and advance Anvil from deadline to deadline: at the block before
each deadline the case, epoch and review views name (and at the deadline
itself, and both shifted by kappa) the harness waits until every service
reports a completed pass at the current head (`-progress`) before it mines
further, so a call a service times to the next block lands in it.

| Profile | kappa | L (blocks) | kappa_Sigma | L - kappa_Sigma | contract `L_actual` | worst path |
| --- | --- | --- | --- | --- | --- | --- |
| data-api-fast-v1 | 0 | 29,680 | 0 | 29,680 | 29,680 | yes |
| data-api-fast-v1 | 100 | 29,780 | 100 | 29,680 | 29,680 | yes |
| open-weights-standard-v1 windows, data predicate | 0 | 91,180 | 0 | 91,180 | 91,180 | yes |

Every keeper call other than the delayed one landed in the block it was due.
The open-weights row uses the epoch, deadlines, `maxAssignments` and amounts
of that profile with `classId` 1 and the experimental data predicate, since
the local deployment has no open-weights seller route or inference pipeline;
the path length depends only on the epoch, the deadlines and
`maxAssignments`. The dry run registers 40 verifiers: each of the nine
assignments of a worst-path case needs a verifier that has not taken part in
the case, drawn within `minVerifiers` rounds. With the nine verifiers the
former admission bound allowed, the last draw missed the one verifier left
with probability (8/9)^9 (about 0.35) and the case ended as a protocol
INCONCLUSIVE. The profiles now require `minVerifiers = 14` (ADR 0023), which
the deploy step registers by default; the last draw then fails with
probability (8/14)^14 (about 4e-4), and (8/40)^14 with 40 verifiers.

## Run selection and resumption

- `--only-cells A,B` keeps the runs of the named cells (an unknown name is an
  error).
- `--shard K/N` (0 <= K < N) keeps the runs whose run id falls in shard K:
  the first 8 bytes of SHA-256 of the run id, modulo N. The N shards cover the
  plan exactly once, and a run's shard does not depend on the other flags.
- `--port-base P` sets the port placeholders; parallel shards take port bases
  at least 100 apart and separate `--output` directories or the same one.
- `--skip-existing` skips a run that has a result envelope (whatever its
  status) and restarts a run that has output but no envelope (an interrupted
  run: its run directory is removed first). Without it, existing output is an
  error.
- `--keep-logs none|failed|all` (default `all`) removes the `output.log` of
  every process after the run, keeps them only for runs that did not
  complete, or keeps them all. Observations, directives and the ground truth
  are always kept.

All of them apply to `--dry-run` as well; its output records `selection`.

## Output

```text
<output>/runs/<run_id>/shared/profile.json      derived profile and harness block (read by processes)
<output>/runs/<run_id>/proc/<name>/             directive.json, events.jsonl, output.log
<output>/runs/<run_id>/observations/*.jsonl     {"metric", "value", "observation_id"} rows
<output>/ground-truth/<run_id>.json             controller only
<output>/results/<run_id>.json                  result envelope
```

Ground truth (the injected fault, expected outcome, expected verdict, the
cell, the timeline of controller actions and `bad_sales_rule`) is written
outside the run directory and its path is given to the collector only.
`bad_sales_rule` names the bad sales of the observed seller:
`all_cheater_episode_sales` for a cheater (every sale of every episode),
`first_m` for a finite attacker (`bad_sales_m` is m) and `none` for an honest
seller; it is null outside the hold-period harness and the finite attack. This
is a convention for cooperating processes under one user account, not a
sandbox.

The envelope records the scenario and its file hash, the FairBind revision,
whether the tree was dirty, upstream revisions from `UPSTREAMS.lock.json`,
resolved parameters, profile overrides, the judgment delay, the seed, creation,
start and finish times, process commands and exit codes, controller actions,
the cell, `operating_point_k`, `harness` and `base_seed`
(`runner.envelope_fields`), `execution` (port base, ports, RPC URL and log
policy), and every metric named by the scenario (each defined in `experiments/metrics.md`, whose SHA-256 the
envelope records under `metric_definitions`). A metric without observations is listed
in `missing_metrics`; it is never reported as zero. `randomness` records the
seed, the repetition, `n_seeds` and the seed effects; `detection` records the
profile's expected `p` and `pi` beside the run's `realized_detection_rate` and
`realized_sample_rate` (null when not observed). A run from a dirty tree
requires `--allow-dirty` and is marked `reportable: false`. Pass criteria are
applied by the analysis, not by the controller.

Every run records `requested_D_holding_blocks` (the resolved `D`, or null),
`effective_hold_period_blocks` (`max(deferBlocks, retentionBlocks)` in the
derived profile), `override_used` and `override_skipped_checks`. See "Plan"
above.
