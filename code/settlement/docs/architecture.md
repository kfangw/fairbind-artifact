# Architecture

## Repository boundary

FairBind owns the post-settlement protocol. It does not copy the full payment gateway or evaluation arena into this repository.

The runtime has three layers:

1. The protocol layer defines transport-independent identifiers, receipts,
   Merkle operations, cases, and the versioned predicate interface.
2. The contract layer holds funds and enforces the state machine, deadlines, sampling, assignment, refunds, and penalties.
3. The adapter layer maps x402 version 2 messages and an EIP-3009 authorization to the protocol layer.

Experimental code observes these layers through public messages, events, and trace files. It must not import private runtime state to obtain ground truth.

## Upstream use

`stablecoin-x402-gateway` remains an external reference rail. FairBind may adapt its EIP-3009, contract-recipient, journal, and failure-injection patterns. A future gateway change should expose a general settlement backend or x402 version 2 adapter rather than embed FairBind states in the gateway policy interface.

`agent-payment-arena` remains an external evaluation tool. FairBind may use its result envelope, repeated execution, paired statistics, and frontier reporting. Integration should use a versioned trace schema or HTTP backend. FairBind contract behavior must not be reimplemented inside the arena fake gateway.

## Process boundary

The complete evaluation deploys the following processes separately:

- buyer client;
- seller resource server and receipt store;
- FairBind-aware facilitator;
- verifier worker;
- keeper;
- experiment controller.

Separate processes allow the evaluation to stop, restart, delay, or partition one role without changing the others.

## Data boundary

Contract storage contains identifiers, immutable profile references, funds,
anchors, case states, assignments, verdicts, evidence hashes, and deadlines. A
normal response body or evidence object remains off chain. If delivery or
evidence disclosure is escalated, its bounded bytes appear in transaction
calldata but are not copied into contract storage.

The seller stores response bundles, signed receipts, ordered epoch leaves, and Merkle proofs. Verifiers store evidence objects addressed by `evidenceHash`. Experiment traces record public actions and injected faults without secret keys.

## Language boundary

Solidity implements the contract state machine. Go implements shared protocol
code, predicate adapters, and runtime services. Python implements experiment
orchestration, predicate calibration, and statistical analysis. Cross-language
test vectors prevent identifier, commitment, and signature drift.

## Dependency policy

The repository does not use Git submodules. CI checks out upstream projects at the revisions in `UPSTREAMS.lock.json` only for integration jobs. Runtime packages should depend on stable public interfaces or copied minimal interfaces with license notices, not upstream internal packages.
