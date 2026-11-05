# Keeper

The keeper calls FairBind public progress transitions after their fixed block
deadlines (`docs/spec/lifecycle-v1.md` sections 1, 2, 4, 5, 8 and 10). Every call
it makes takes only identifiers, so it has no influence on the result. It holds
no verdict key, never calls `judge`, `appeal`, `dispute`, `acceptServe`,
`escalate` or `served`, and signs nothing itself: transactions go through the
node account named in the configuration.

## Actions

| Action | Planned when (at the finalized block `F`) |
| --- | --- |
| `timeoutAnchor(sellerId, epoch)` | epoch has a settlement, no anchor, `F > anchorDeadline(e)` |
| `seal(sellerId, epoch)` | anchored, `randomBlock < F <= sealDeadline` |
| `timeoutSeal(sellerId, epoch)` | anchored, `F > sealDeadline` |
| `openSample(nonce)` | epoch sealed, `isSampled` eligible, no case |
| `assignVerifier(nonce)` | case `ASSIGNING`, epoch sealed |
| `timeoutJudge(nonce)` | judging or review state with an assigned verifier, `F > judgeDue` |
| `sealReviewRandomness(nonce)` | review state without a verifier, `F > randomBlock` |
| `timeoutEvidence(nonce, stage, attempt)` | `INITIAL_VERDICT`, `evidenceDue != 0`, `F > evidenceDue` |
| `finalizeCase(nonce)` | `INITIAL_VERDICT(FAIL)`, `F > appealUntil` |
| `openAutoRecheck(nonce)` | `INITIAL_VERDICT(PASS)` or `INITIAL_VERDICT(INCONCLUSIVE)`, `F > appealUntil + 1` |
| `timeoutServe(nonce)` | `SERVE_WAIT` and `F > serveDue`, or `PUBLISHING` and `F > publishDue` |
| `finalizeServed(nonce)` | `SERVE_CONFIRM`, `F > challengeUntil` |
| `releasePurchase(nonce)` | stored `DEFERRED`/`RELEASABLE`, epoch sealed, no case or a finished case, and all section 2 timing conditions; or a purchase that `purchaseState` reports `FORFEITED` |
| `freezeSellerDeferred(triggerNonce)` | a tracked purchase's own case holds an initial `FAIL` and is not yet terminal, its profile has `freezeOnInitialFail`, and its bond account carries no freeze |
| `releaseFrozen(bondId)` | bond `FROZEN`, not yet `CLAIM_OPEN` |
| `forfeitUnclaimed(bondId)` | bond `CLAIM_OPEN`, `F > claimUntilBlock` |

Reassignment is `timeoutJudge`, `timeoutEvidence` and `assignVerifier`: the
contract penalizes and replaces the late verifier. The keeper serve path is the
same `timeoutJudge` (or an exhausted `assignVerifier`) moving a sampled case to
`SERVE_WAIT` with the keeper as requester, followed by `timeoutServe` or
`finalizeServed`. As requester the keeper neither accepts early nor escalates; it
waits for the public challenge deadline.

Deadlines are read from views pinned to the finalized block hash. The finalized
block never exceeds the block that includes the transaction, so a deadline
passed at `F` has also passed on chain. Before each broadcast the call is
simulated against the latest block; a call that would revert (already done, a
frozen entry, a pending evidence request, an open buyer recovery) is reported
as `rejected` and not sent.

The keeper picks neither call's exact result: `freezeSellerDeferred` is
proposed with a tracked purchase's own nonce as `triggerNonce` whenever that
purchase's case is not yet terminal and holds an initial `FAIL` under a
profile with `freezeOnInitialFail` (read from the profile view), and
`releaseFrozen` is proposed for every bond account the keeper has seen that
carries a freeze not yet at `CLAIM_OPEN`. The contract alone decides whether a
freeze is legitimate or a release is premature; a call the contract would
revert is caught by the pre-broadcast simulation and reported as `rejected`,
same as any other action.

## Worst-path directive

`-directive FILE` (default `$FAIRBIND_DIRECTIVE`) reads the scenario directive
file (`services/internal/directive`). With its `worst_path` block
(`experiments/controller/worstpath.py`) the keeper times every call to the
block that includes it: it reads views at the latest block `L`, compares
deadlines with `L + 1` and simulates against the pending block, so a timeout
lands in the block after its deadline. `seal` lands in the last block of the
seal window and `openSample` in the last block of the open window. On a case
opened by sampling, the first seal window of each review stage lapses:
`finalizeCase` in the block after it reopens the seal (ADR 0021), and
`sealReviewRandomness` lands in the last block of the reopened window. The
`keeper_delay` block's `budget_blocks` (kappa) delays one call per case by
kappa blocks: the last keeper call before the confirmed failure on this path,
the `timeoutJudge` that replaces the next-to-last tiebreak assignment (the
reopened tiebreak seal when a stage has one assignment). Without a
`worst_path` block the keeper keeps the finalized-block schedule above.

Every logged call carries `due` (the first block the call is due; for a
timeout the block after its deadline), `nonce` (the case of a per-purchase
call) or `epoch` (`sellerId:epoch`), so the keeper delay of a call is its
inclusion block minus `due`. `-events FILE` (default `$FAIRBIND_EVENTS`)
appends the sent calls as `call_sent` rows. `-progress FILE` writes
`{"head":N}` after every pass, the head block the pass started from; a harness
that advances a local chain waits for it before mining further.

## Idempotency and restarts

The state file holds the scanned block, the tracked purchases, epochs and bonds,
and one record per in-flight action. An action key names the call and the state
it answers (for example the nonce, stage, attempt and `judgeDue`). The record is
written before broadcast, so a crash during broadcast does not cause an
immediate resend. The same key is sent again only after `resendAfterBlocks`
finalized blocks without a state change. Records whose action is no longer
planned are dropped. Settlement events are scanned from `startBlock` once, in
chunks of `maxLogRange`; a restart resumes after the scanned block. Every write
is atomic (temporary file, fsync, rename, directory fsync), and an exclusive
lock on `<stateFile>.lock` prevents two keepers from sharing one file. A
finalized block below the scanned block stops the tick with an error.

Purchases leave the tracked set once they are `REFUNDABLE`, `REFUNDED`,
`RELEASED` or `FORFEITED`, have an `UNSERVED` case, or have no case in a failed
epoch. Refunds, epoch-failure claims and frozen-pool claims are left to buyers.

## Configuration

```json
{
  "rpcUrl": "http://127.0.0.1:8545",
  "chainId": 31337,
  "contract": "0x1111111111111111111111111111111111111111",
  "from": "0x2222222222222222222222222222222222222222",
  "gas": 3000000,
  "stateFile": "/var/lib/fairbind/keeper-state.json",
  "startBlock": 0,
  "pollIntervalMs": 1000,
  "rpcTimeoutMs": 10000,
  "maxLogRange": 2000,
  "resendAfterBlocks": 20,
  "actions": ["timeoutAnchor", "timeoutServe"]
}
```

`actions` is optional; when omitted every action is enabled. Unknown fields are
rejected. The RPC must be HTTPS or literal loopback HTTP. Transactions use
`runtime/judgment.LocalRelay`, which accepts only a loopback node with an
unlocked `from` account; a public deployment needs a different sender.

```sh
go run ./services/keeper/cmd/fairbind-keeper -config keeper.json
go run ./services/keeper/cmd/fairbind-keeper -config keeper.json -once
```

Each sent, rejected or failed action is written to standard output as one JSON
line.

## Tests

`go test ./services/keeper/...` uses an in-memory fake chain and sender. The
worst-path tests (`directive_test.go`) check the window-end seal and sample
opening, prompt timeouts in the block after the deadline, the lapsed and
reopened review seal, the default for a dispute-opened case, and the delay
budget on the tiebreak replacement (and on the tiebreak seal with one
assignment per stage). The
tests cover inclusive deadlines (no call at the deadline, a call one block
later), each release condition, reassignment with a new attempt, the keeper
serve path, review progress, forfeiture after the claim window, freezing a
bond on an untried initial `FAIL` (and skipping one already frozen or already
terminal), releasing a frozen bond (and the contract rejecting a premature
release), rejection by simulation, resend after the configured window, intent
recorded before broadcast, restart from the state file, the state-file lock,
chunked log scans and configuration checks. A fake JSON-RPC server checks view
decoding and block hash pinning. The tests do not run against a real node.

## Limits

- The keeper does not call `claimEpochFailure`, `claimRefund` or the
  independent buyer-recovery selectors (`timeoutBuyerServe`,
  `finalizeBuyerServed`).
- `seal` is decided at the finalized block. On a chain whose finality lag
  approaches `sealBlocks` the window can close before the finalized view sees it.
- Rejected actions are simulated again on every tick until their state changes.
