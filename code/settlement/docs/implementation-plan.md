# Implementation Plan

## M0: Specification and repository scaffold

Status: Complete for version `1.0.0-rc.1`

M0 completes when the repository contains the normative protocol, exact
canonicalization and cryptographic formats, contract and lifecycle interfaces,
predicate commitments and evidence, x402 version 2 binding, evaluation profiles,
threat model, architecture,
decision records, upstream revision lock, machine-readable schemas and vectors,
and automated document checks.

No contract behavior belongs in M0.

The M0 artifacts are complete. M1 begins only after a branch passes `make check`
and a reviewer confirms that no unresolved marker remains in a normative file.

## M1: Settlement and exposure accounting

Status: Reference implementation present; baseline tests pass, full acceptance pending

M1 implements seller and profile registration, `keyId` and nonce derivation, EIP-3009 settlement into the contract, token-bucket enforcement, purchase records, deferred funds, and idempotent reconciliation.

Acceptance requires:

- shared Go and Solidity identifier vectors;
- unit and fuzz tests for every settlement rejection;
- invariants for identifier uniqueness, atomic rollback, and fund conservation;
- retry tests for successful, reverted, and uncertain settlements;
- gas snapshots for registration and settlement.

## M2: Anchoring and sampling

Status: Reference implementation present; baseline tests pass, full acceptance pending

M2 implements seller receipt signing, sorted Merkle trees, epoch anchors, fixed future randomness, ledger-nonce sampling, verifier checkpoints, and bounded assignment.

Acceptance requires:

- omission and equivocation tests;
- proof that receipt omission cannot change sample selection;
- snapshot and effective-bond assignment tests;
- tests for stale block hashes, missed anchors, and insufficient verifiers;
- gas snapshots for anchor, seal, sample opening, and assignment.

## M3: Redelivery and refunds

Status: Reference implementation present; baseline tests pass, full acceptance pending

M3 implements buyer and verifier serve requests, seller delivery confirmation, escalation, single-call and chunked publication, epoch failure, disputes, purchase holds, and refunds.

Acceptance requires:

- P2 state exploration over every deadline branch;
- process restart and lost-message tests;
- maximum-response and chunk-order tests;
- conservation tests across release, refund, and seller bond;
- gas snapshots for disputes, publication, finalization, and refunds.

The M3 reference contract passes its eight baseline tests. This does not complete
the acceptance requirements above: deadline state exploration, process recovery,
maximum-response coverage, conservation sequences, and per-call gas snapshots
remain incomplete. Its deployed
bytecode exceeds the EIP-170 mainnet size limit, so M5 must split the contract
into fixed, non-upgradeable modules before public deployment. This packaging
change must preserve the M1 through M3 state transitions and identifiers.

## M4: Judgment and review

Status: Contract reference implementation present; authenticated workers and full acceptance pending

M4 implements the predicate interface, verifier workers, judgment, evidence disclosure, late penalties, party appeal, automatic recheck, third-verifier resolution, and wrong-verdict penalties.

Acceptance requires:

- one representative data API predicate;
- one representative open-weights inference predicate;
- exclusive review-path invariant;
- no-repeat assignment invariant;
- verifier liability invariant;
- simulations that validate the P3 and P4 probability calculations.

## M5: Integrated artifact

Status: Planned

M5 runs buyer, seller, facilitator, verifier, keeper, and controller as separate processes. It adds local deployment, public testnet deployment, fault injection, baseline comparisons, reproducible result envelopes, and an artifact guide.

Acceptance requires:

- one-command local deployment;
- failure tests at each message and transaction boundary;
- comparisons against direct x402 settlement, per-transaction verification, and full-collateral baselines;
- recorded code and upstream revisions for every result;
- clean-checkout reproduction of paper tables and figures.

## Verification baseline (2026-09-08)

At revision `11a38c4`, `make check` passed: specification checks, six Go tests,
and sixteen Solidity tests (M1: four, M2: four, M3: eight). No fuzz or
stateful invariant test entry points were present. The baseline token mock
does not verify authorization signatures, so these tests do not establish
real-token EIP-3009 signature integration.

A forced build with Solidity 0.8.24, optimizer runs 200 and via-IR reproduced
42,781 runtime bytes. `forge build --force --sizes` failed the 24,576-byte
runtime limit. `make check` currently does not include that size gate.
This is a passing reference-test baseline, not deployment readiness.

## Change control

Implementation may tune profile values without changing the proof structure. A change to a frozen version 1 rule requires a decision record and a proof review before code merges.

## Expanded verification and conformance repair (2026-09-08)

The expanded diagnostic suite passes 34 Solidity tests (M1: 12, M2: 8,
M3: 14), including three property fuzz tests with 256 runs each, and five
public-collector unit tests. The initial-assignment repair is documented in
ADR 0006; its pre-seal dispute regression failed before the repair.
The optional signature-validating token mock checks a signed authorization,
tampering, and replay; this is not real USDC integration.

Full acceptance remains pending: stateful invariant exploration, uncertain
settlement/process recovery, and module deployment limits are unresolved.
Core section 13 refers to effective-bond liability, while profile-v1 uses
actual bond. The new liability test characterizes the current actual-bond
behavior and does not resolve or approve this specification conflict.
Clean-commit result logs are maintained in the research artifact manifest.

## Fixed-module packaging

ADR 0007 splits the implementation into a typed router and six immutable modules.
The expanded suite has 39 tests, including module direct-call, constructor,
shared-lock checks, and a characterization of the active-sample buyer-recovery
gap. The original runtime ABI and all 28 storage fields match across the seven
components. Every runtime is below 24,576 bytes and every initcode including
constructor arguments below 49,152 bytes. `make check` now includes these gates.
`scripts/local_deploy.py` deploys an ephemeral local Anvil with normal limits and
verifies artifact code and immutable configuration, recording a clean revision.
Public deployment and complete M4-M5 remain pending. Historical monolith size
statements above describe their named baselines rather than this configuration.

## Independent recovery and durable settlement

ADR 0008 implements the user-selected effective-bond liability bound and an
independent buyer delivery record alongside existing content cases. Explicit
buyer delivery/publication selectors avoid requester ambiguity. A seller failure
closes both routes, returns both buyer deposits on refund, and cancels outstanding
assignment liability. Release also returns an INCONCLUSIVE quality-dispute deposit
to the buyer as the lifecycle already required. The original storage prefix is
preserved; three mappings are appended.

`runtime/settlement` persists exact purchase identity and authorization before
submission, serializes access with an OS file lock, and reconciles a consistent
finalized ledger before any resubmission. Tests include a separate process dying
after a test ledger commits but before acknowledgement. This establishes the
journal/controller path with a fake ledger, not live USDC or full M5 integration.

At that baseline, M4 still required evidence/appeal deadline coordination and
reserved verifier penalty funding. ADR 0009 below supersedes that pending status.

## Independent predicate diagnostics and bounded action sequences

The data-reference comparison kernel has eight tests. The optional native TOPLOC
adapter has six tests; three require the pinned CPU environment. Three public-model
prefill inputs are diagnostic data, not a workload or error calibration. Both kernels
still require authenticated receipt/policy/source bindings in the future worker.
The read-only collector now preserves allowlisted JSON-RPC responses and errors.

M1 also includes a 64-action fuzz sequence that varies keys, amounts, token failure
and block advances, checking custody, payer funds, key/nonce consistency and failed
bucket rollback after every action. This is bounded settlement exploration, not a
complete M1-M4 invariant harness. Combined judgment invariants still require broader state exploration beyond
the bounded M4 regression scenarios below.

## Judgment and review contract implementation (ADR 0009)

The user approved full appeal renewal after evidence disclosure and per-assignment
maximum penalty reservations. The fixed deployment now has eight modules plus the
router. Judgment authenticates the existing signed-verdict encoding and seller
receipt, requiring anchored receipt inclusion for sampled cases. Evidence, bounded
replacement, party appeal, automatic recheck, third-verifier resolution and terminal
capital/deposit accounting are implemented. The Go protocol package hashes signed
verdicts against the existing normative vector; it is not a verifier worker.

The expanded regression suite contains 75 Solidity tests: 17 M1, nine M2, 19 M3,
20 M4 judgment/review and ten M4 capital tests. These cover concurrent penalties,
cross-profile conservative envelopes, evidence timing, exclusive paths, no-repeat
assignment, buyer recovery during review, and removed-verifier withdrawal. Logs
from the clean committed revision, not this description, establish execution.

Authenticated data/inference workers, six-process integration, full state exploration
and P3/P4 probability validation remain incomplete. Assignment availability and
enforcement lower bounds are not established by the functional evaluation profile.
Its analysis explicitly records that limitation. The retention horizon assumes a
bounded cumulative keeper delay; it is not unconditional liveness under arbitrary
inactivity. The clean local deployment uses a mock token and proves no public-chain
or real-USDC integration. Original paper PDFs remain on their recorded baselines.

## Authenticated input and experimental data worker components

The HTTP adapter now normalizes original request bytes and checks normative
vectors. The verifier gate authenticates purchase identifiers, canonical claims,
real seller signatures, response roots and both commitment preimages. READY
permits a comparison; it is not PASS. The local data worker connects this gate to
the separately user-approved ADR 0010 experimental policy and strict Python codec.
Trusted ledger and independent-reference adapters are required caller boundaries.
They are not implemented or simulated as authenticated production data here.
Evidence storage, assignment polling, verdict signing/submission, inference model
execution binding and full process integration remain incomplete. Tests use public
test keys and synthetic references; no empirical predicate calibration is claimed.

## Finalized ledger, evidence and one-shot submission components

The finalized ledger adapter pins all ABI reads to one canonical block hash and
rechecks chain/block identity. The evidence package matches the frozen canonical
vector and persists immutable content-addressed objects. The judgment outbox
composes authenticated evaluation, durable evidence, verifier signature recovery,
exact judge calldata, fresh assignment checks and an attempt-before-broadcast
record. Encrypted-keystore signing uses the pinned cast build; the relay permits
only loopback test RPC. No contract semantics or normative encodings change.

Tests cover strict envelopes, concurrent object writes, changed snapshots, real
fixture signatures, ABI equality, restart after uncertain send, reference tampering
and loopback restrictions. RPC tests are simulated; no real-network finality or
deployed end-to-end judgment is established. Actual reference collection, a
concrete evaluator/evidence bridge, periodic polling, disclosure service, confirmed
receipt tracking and explicit uncertain-send reconciliation remain incomplete.

## Bond accounts, freeze, and suspension (ADRs 0011 to 0013)

The fixed deployment now has nine modules plus the router. The ninth module,
`FairBindBond`, holds bond-account registration and exit, seller registration
under a bond, reinstatement, and the frozen-pool entry points
(`freezeSellerDeferred`, `releaseFrozen`, the receipt overload of `claimRefund`,
`forfeitUnclaimed`). Evidence request and disclosure moved from the judgment
module to the review module to keep both under the EIP-170 limit. The router and
every module take the immutable verifier reward pool as a fifth constructor
address. The module check compares the router ABI and storage layout with the
baselines recorded for this revision under `test-vectors/deployment/`; the
earlier baselines described the version before bond accounts.

## Failure cost, review paths, and freeze timing (ADRs 0018 to 0020)

Status: Implemented; contract, keeper, ledger adapter, controller and profile
document updated together, regression and stateful tests in place.

Every counted confirmed failure deducts `sellerPenalty / failureLimit` from the
bond and the terminal failure the remainder (ADR 0018). A party review that
disagrees with the initial verdict goes to the tiebreak, an unappealed initial
`INCONCLUSIVE` passes the recheck gate like a `PASS`, `judgmentDelayBlocks`
budgets the tiebreak, and `failureLimit` is derived per settlement over
`failureWindowBlocks + caseHorizon` with every `PASS` appealed (ADR 0019).
`ServiceProfileInput` gains `freezeOnInitialFail` (false in every production
profile; the override build admits true and requires it below the case
horizon) and `minJudgedCount` (ADR 0020). The struct change re-cuts the ABI
and storage baselines under `test-vectors/deployment/` before any deployment.
The stateful suite runs under both freeze timings
(`contracts/test/invariant/run.sh`).

## Scaled failure threshold, re-entry, and reopened review seal (ADR 0021)

Status: Implemented; contract, regression and stateful tests, profile
document, specification, controller and scenarios updated together. I6 is
planned and validated, not run.

A failure window sanctions at `n * failureLimit` for the scale factor `n` at
which it opened, and charges `n * sellerPenalty` in all. `reinstateSeller` is
admitted while the claim window is open; the purchases settled afterwards are
kept apart from the frozen window until a later confirmed failure moves
`freezeBlock` over them, and `forfeitUnclaimed` takes only the frozen window.
A review seal that finds no randomness reopens once per stage.
`finalizeSellerExit` waits for the frozen pool. The `failureLimit` model counts
the initial `FAIL` overturned on appeal and confirmed by the tiebreak (`u = 3
w1^2`); the case horizon budgets the reopened seals, and the evaluation hold
periods become 60,000 and 132,000 blocks with limits 16 and 27. The judgment
timeouts moved from the judgment module to the sampling module to keep every
module under the EIP-170 limit; the storage layout gains three appended
mappings and the router three views and one event, and the baselines under
`test-vectors/deployment/` are re-cut. The stateful suite runs a second
mutation build (`contracts/test/invariant/ReentryMutation.sol`) that must be
rejected.

## Window scale, top-up access, and locked forfeiture (ADR 0022)

Status: Implemented; contract, regression and stateful tests, integration
test, specification and deployment baselines updated together. The I6 cells,
the worst-path directives (planned, not consumed by any service yet), the R20
injection model and the C1 calibration configuration are in `experiments/`;
none of them has been run.

A failure window opens at the larger of the scale factor before the opening
deduction and the highest scale the account left within `retentionBlocks`,
and a top-up during the window raises its scale. `topUpBond` is owner-only.
Forfeited remainders and per-failure deductions stay in the contract
(`lockedForfeit`, no withdrawal); `forfeitVerifierPpm` and the reward-pool
constructor argument are kept for encoding and deployment stability and have
no effect. Storage appends `recentScaleHigh` and `lockedForfeit`; the router
gains `getRecentScaleHigh` and `getLockedForfeit`; no `parameterHash` moves.

