# Verifier worker

`services/verifier` is the verifier process. It watches finalized assignments
for one registered verifier, obtains the seller's serve bundle, evaluates it
with a local predicate pipeline, and submits exactly one signed `judge` call
per assignment. It implements the judgment and deadline rules in
`docs/spec/lifecycle-v1.md` sections 4 to 6 and the `judge` entry point and
events in `docs/spec/contract-interface-v1.md` sections 9 and 12.

```bash
go run ./services/verifier/cmd/fairbind-verifier -config verifier.json
go run ./services/verifier/cmd/fairbind-verifier -config verifier.json -once
```

## Loop

Each pass (`Worker.Tick`) does the following.

1. Read the head block and the finalized block.
2. Scan `VerifierAssigned` logs whose indexed `verifierId` is ours, from the
   saved cursor up to the finalized block, and add their nonces to the watch
   list. The cursor then moves past the finalized block.
3. For each watched nonce, read the case with the finalized ledger adapter
   (`runtime/ledger`). Earlier submissions for the nonce are reconciled first
   (see below).
4. If the active assignment is ours (`stage` 1 to 4, case state `JUDGING`,
   `PARTY_REVIEW`, `AUTO_REVIEW` or `TIEBREAK` respectively), read it again
   with the manifest bindings configured for its profile.
5. Ask the outbox whether a record exists for this assignment.
   - An attempted record is never sent again; it is reconciled.
   - A prepared record that was never attempted is submitted as saved,
     without asking the seller or the predicate again.
   - Without a record: request the serve bundle from the seller, run the
     verifier gate (`runtime/verifier.Check`), run the predicate, and prepare
     the signed verdict (`judgment.Outbox.Prepare`). Preparation stores the
     evidence envelope in the object store and fsyncs the signed record.
6. Submit through `judgment.Outbox.Submit`, which re-reads the finalized
   assignment, writes the attempt marker durably, and only then broadcasts.

The verdict code is `protocol.VerdictCode` of the envelope's verdict name. A
bundle that the gate reports `INCONCLUSIVE` (not bound to the ledger, bad
receipt signature, and so on) is not evaluated; the worker retries the
redelivery on the next pass. A gate `FAIL` is passed to the predicate, whose
envelope must then say `FAIL`.

## Deadlines

A verdict is only prepared or broadcast while
`head + 1 + submitMarginBlocks <= judgeDue`, since `judge` is timely through
`judgeDue`. Past that point the worker logs the case, marks the assignment
`expired`, and sends nothing. The contract's `timeoutJudge` then penalizes and
reassigns; the worker does not try to beat the deadline.

Assignments are discovered and read at the finalized block, so `judgeBlocks`
must comfortably exceed the chain's finality delay plus the evaluation time.

## Worst-path directive

`-directive FILE` (default `$FAIRBIND_DIRECTIVE`) reads the scenario directive
file. With its `worst_path` block (`experiments/controller/worstpath.py`) the
worker reads a case opened by sampling at the latest block and times each call
to the block that includes it (a call sent at head `h` lands in `h + 1`):

1. every assignment of this verifier sends `requestServe` so that it lands at
   the judge deadline, and `escalate` of the served bundle at the challenge
   deadline; the seller's publication renews the judge deadline;
2. in the initial stage every assignment delivers the block's
   `initial_verdict` at the renewed judge deadline; the last one (attempt
   `max_replaced_assignments`) sends `discloseEvidence` with the committed
   envelope from the object store at the evidence deadline when the seller has
   requested it, the others never disclose, so the keeper voids them;
3. in the party review and the tiebreak only the last assignment delivers the
   stage verdict (`party_review_verdict`, `tiebreak_verdict`) at the renewed
   judge deadline; the others are marked `skipped` and time out.

The verdict still comes from the outbox: the worker redelivers, runs the gate
and the predicate, replaces the envelope's verdict with the directed one
(the outbox refuses anything but FAIL on a gate FAIL), prepares it as soon as
the finalized ledger shows the renewed assignment and submits it at the judge
deadline, without `submitMarginBlocks`. Cases not opened by sampling follow
the loop above. `-progress FILE` writes the head block of every completed
pass.

## Reconciliation

A `submitted` or `uncertain` assignment is resolved from finalized data only:

| Observation at the finalized block | Result |
| --- | --- |
| `VerdictSubmitted(nonce, verifierId)` with our stage and evidence hash | `confirmed` |
| Our transaction's receipt has status 0 | `reverted` |
| The case left our stage and attempt without the event | `missed` |
| Otherwise | stays pending; checked again next pass |

An attempt marker without a transaction hash (crash or lost acknowledgement)
is `uncertain`. The worker never rebroadcasts it: missing evidence of a
transaction is not proof that none was sent. When a case is `missed` or
`reverted`, the operator can inspect the prepared call data in the outbox
record.

## State files

Everything lives under `stateDir`.

| Path | Owner | Content |
| --- | --- | --- |
| `worker.lock` | worker | Exclusive lock; a second process on the same directory refuses to start. |
| `state.json` | worker | Log cursor, watched nonces, and one entry per assignment (status, deadline, verdict, evidence hash, transaction hash). Written atomically. |
| `outbox/<key>.json` | `runtime/judgment` | Signed verdict, receipt, proof and call data. Authoritative for "prepared". |
| `outbox/<key>.attempt` | `runtime/judgment` | Written before the broadcast. Authoritative for "a broadcast may have happened". |
| `outbox/<key>.attempt.tx` | `runtime/judgment` | Transaction hash after an acknowledged broadcast. |
| `objects/<hash>` | `runtime/evidence` | Content-addressed evidence envelopes and referenced objects. |

`state.json` is a tracking aid. The worker consults the outbox before every
submission, so a stale `state.json` after a crash can delay progress but
cannot cause a second broadcast.

## Failure handling

| Failure | Behaviour |
| --- | --- |
| RPC or ledger read error | Logged; the nonce is retried next pass. |
| Seller unreachable or bundle invalid | Logged; retried next pass until the deadline margin. |
| Predicate error (runtime failure, no manifests for the profile) | Logged; retried next pass until the deadline margin. |
| Predicate identifier without a configured pipeline | INCONCLUSIVE fallback envelope, or FAIL when the gate reported FAIL. |
| Profile without configured bindings | Assignment marked `skipped`. |
| Crash after prepare, before the attempt marker | Next run submits the saved record once. |
| Crash after the attempt marker, before or after the broadcast | Next run marks it `uncertain` and reconciles; no resend. |
| Broadcast error or lost acknowledgement | `uncertain`; no resend. |
| Assignment changed before broadcast | `Submit` refuses; the stale entry becomes `expired` once the case moves on. |

## Configuration

```json
{
  "rpcUrl": "http://127.0.0.1:8545",
  "chainId": 31337,
  "contract": "0x...",
  "verifierId": 3,
  "keystore": "/etc/fairbind/verifier.keystore",
  "passwordFile": "/etc/fairbind/verifier.password",
  "castPath": "/usr/local/bin/cast",
  "stateDir": "/var/lib/fairbind-verifier",
  "pollIntervalSeconds": 6,
  "startBlock": 0,
  "maxLogRange": 2000,
  "submitMarginBlocks": 4,
  "relay": { "from": "0x...", "gas": 3000000 },
  "sellers": { "7": "https://seller.example" },
  "profiles": { "4": { "sourceSetHash": "0x...", "tolerancePolicyHash": "0x..." } }
}
```

- `rpcUrl` must be HTTPS or a literal loopback HTTP address.
- `keystore`, `passwordFile` and `castPath` configure `judgment.KeystoreSigner`
  (pinned cast build). The key must be the verifier's registered signing key.
- `relay` configures `judgment.LocalRelay`, which only sends to a loopback RPC
  with an unlocked account. Any account may relay a signed verdict.
- `sellers` maps seller IDs to redelivery base URLs.
- `profiles` holds the manifest hashes the ledger adapter expects per profile.
- Optional: `rpcTimeoutSeconds` (10), `maxEvidenceBytes` (4 MiB),
  `maxClaimsBytes` (65536), `relay.url` (defaults to `rpcUrl`).
- Optional: `dataPredicate` and `inferencePredicate` (below). Without them
  every assignment gets the INCONCLUSIVE fallback envelope.

### Predicate configuration

```json
{
  "dataPredicate": {
    "timeoutSeconds": 15,
    "references": {
      "mode": "replay",
      "replayDir": "runtime/dataworker/testdata/refsource/replay",
      "allowSynthetic": true
    },
    "profiles": {
      "3": { "policyFile": "/etc/fairbind/policy.json", "sourceSetFile": "/etc/fairbind/sources.json" }
    }
  },
  "inferencePredicate": {
    "python": "/usr/bin/python3",
    "script": "runtime/inference/evaluate.py",
    "modelDir": "/models/checkpoint",
    "configDir": "/etc/fairbind/inference-configs",
    "timeoutSeconds": 600
  }
}
```

`dataPredicate` registers `DataPredicate` under the experimental
decimal-median predicate (`runtime/dataworker.PolicyID`).

- `profiles` maps a profile ID to the operator's tolerance policy
  (`dataworker.Policy`) and source set (`dataworker.SourceSet`) files. They are
  decoded strictly; when `profiles[id]` of the top-level bindings names
  `tolerancePolicyHash` or `sourceSetHash`, the canonical hash of the file must
  equal it or the configuration is rejected. Every source must be in
  `refsource.DefaultRegistry`; configuration never supplies an endpoint. The
  manifests are written to the object store at startup, so a fallback
  envelope for the profile can reference them.
- `references.mode` is `replay` (saved raw objects in `replayDir`, no network;
  `allowSynthetic` accepts the synthetic fixtures, which carry no TLS chain)
  or `live` (HTTPS capture now; `captureDir`, if set, keeps every raw object).
  `rootsFile` optionally replaces the system roots with a PEM file.
- `timeoutSeconds` bounds reference collection (default 15).

`inferencePredicate` registers `InferencePredicate` under
`OPEN_WEIGHTS_TOPLOC_V1`. `python` and `script` run `evaluate.py`;
`modelDir` is one local checkpoint, keyed by the weight manifest hash computed
at startup (the same layout as `runtime/inference/model.py`
`weight_manifest`); every `*.json` file in `configDir` is a configuration
manifest keyed by the Keccak-256 of its exact bytes. `timeoutSeconds` bounds
one re-execution (default 600). All four paths are required.

Relative paths resolve against the working directory of the process.

## Seller redelivery endpoints

```text
POST {base}/fairbind/v1/serve    {"nonce":"0x..","stage":1,"attempt":0,"verifierId":3}
                                 -> serve bundle, schemas/fairbind-serve-bundle-v1.schema.json
GET  {base}/fairbind/v1/claims   -> the exact registered claims bytes
```

The worker checks the receipt domain and `bundleHash`
(`docs/spec/cryptography-v1.md` section 8), then the gate binds every field to
the finalized ledger. Seller responses are untrusted input.

## Predicate pipelines

`Predicate` receives the assignment, the authenticated bundle and the gate
result, stores every object its envelope references, and returns the envelope.
`Registry` dispatches by service class; `PredicateRouter` dispatches by
predicate identifier.

- `DataPredicate` runs `runtime/dataworker.Pipeline` with the operator's
  source set and tolerance policy for the profile. It stores the source set,
  policy, reference set (raw replay objects), comparison record, full evidence
  object and an implementation object. `referenceResponsesHash` and
  `comparisonHash` reference the reference set and comparison record, so a
  second verifier can re-derive the verdict (`dataworker.Rederive`).
- `InferencePredicate` runs `runtime/inference.Pipeline`. `traceHash`
  references the canonical inference evidence object; the configuration
  manifest is stored under `configHash` when the operator holds it.
- A predicate identifier without a registered pipeline (the gate also accepts
  the normative `DATA_API_REFERENCE_V1`, which has no pipeline here) gets an
  INCONCLUSIVE envelope, or FAIL when the gate reported FAIL. The manifest
  objects that envelope references must already be in the object store.

A pipeline returning an error (bundle not judged, runtime failure, missing
manifests for the profile) prepares nothing; the worker retries until the
deadline margin. The command builds a `PredicateRouter` from `dataPredicate`
and `inferencePredicate` (`NewPredicateRouter`) and logs the registered
predicate identifiers at startup.

## Tests

`go test ./services/verifier/...` runs without a chain. `directed_test.go`
covers the worst-path step decisions, the disclosure encoding and one
schedule end to end (serve, escalation, early preparation, verdict at the
deadline, disclosure only on the last initial assignment, review assignments
left to time out). The ledger, chain,
seller and relay are in-memory fakes; the predicate is a fake in the loop
tests and the real data pipeline over the replay fixtures in
`TestDataPipelineEndToEnd`; signatures use the pinned
`cast` binary on `PATH`. The restart tests stop a pass at a chosen point, reopen
the state directory, and count broadcasts.
