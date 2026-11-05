# Durable one-shot judgment submission

`Outbox.RunOnce` composes a trusted finalized `Source` (implemented by
`runtime/ledger.Client`), authenticated seller bundle, trusted local `Evaluator`,
canonical evidence retention, verdict signing, and fresh-read submission.
`Prepare`, `Load` and `Submit` expose the same steps separately. The evaluator must
actually run the comparison and store its replay objects, not accept a peer's
asserted verdict. This package validates cryptographic bindings, not the truth of
arbitrary caller-supplied content decisions.

Preparation verifies the seller receipt and input gate, assignment state/stage,
deadline, evidence identity and commitment preimage, sample inclusion proof,
profile evidence limit, and availability of content-addressed references. Exact
canonical evidence is persisted before signing. The returned verifier signature
is independently recovered against the ledger's assigned signing key. Judge
calldata uses the existing contract ABI; a test compares every byte with cast.

The outbox directory must have an existing trusted parent. Creation fsyncs that
parent. A Unix file lock serializes preparation/submission, and immutable hard-link
publication plus file/directory fsync persists prepared records. One assignment
key cannot acquire a conflicting evidence hash. Before broadcasting, Submit loads
the same saved record, reads a fresh finalized assignment, rechecks signatures,
calldata, proof, limits, canonical evidence and every referenced object, then
persists an attempt marker. A submitted transaction hash is acknowledgement only,
not confirmation of a mined successful judgment.

A crash or error after the attempt marker leaves an uncertain outcome. A restart
can `Load` the prepared message and marker but cannot automatically resubmit it.
Even a crash just before broadcast requires explicit reconciliation; this
conservative behavior can miss a deadline. Transaction receipt/event tracking and
a safe retry/reconciliation policy are still required. Never delete a marker to
blindly retry. This package provides no marker-reset or retention-deletion API.

`KeystoreSigner` uses an operator-owned encrypted keystore and password file via
the pinned cast executable. No private key is part of bundles, records, returned
errors or production command-line arguments. Tests import only public fixture key
1 into an ephemeral encrypted keystore. File paths are trusted operator config.

`LocalRelay` requires literal loopback HTTP, a pinned chain/contract and an unlocked
local test account. It rechecks chain ID and uses `eth_sendTransaction`; it cannot
broadcast to a public endpoint. Signatures and calldata are real; relay tests use
a fake JSON-RPC server, not a deployed-contract end-to-end transaction. Existing
Solidity tests remain the contract baseline. The source RPC is trusted and a
finalized read can lag live state, so the contract may reject a stale submission.

For class 1, implementation, source-set, policy, reference-response and comparison
objects must exist. Class 2 additionally requires trace and configuration objects;
large model artifacts and reproduced activation execution remain an external
content-addressed retrieval obligation. Store presence proves bytes, not source
independence, scientific calibration or execution correctness.

Not complete: real reference fetching, concrete dataworker-to-evidence evaluator,
periodic event/assignment discovery, disclosure transaction service, transaction
confirmation/reconciliation, six-process operation or public-chain deployment.
The one-shot APIs use supplied interfaces so these missing pieces cannot silently
be replaced with untrusted input flags.
