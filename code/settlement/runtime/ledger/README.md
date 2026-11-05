# Finalized assignment reader

`New(Config)` fixes one RPC URL, chain ID and contract address. HTTPS is required
except for literal loopback HTTP used by local Anvil. Redirects, unbounded response
bodies, zero chain/contract configuration and nonpositive timeouts are rejected.
`Read(ctx, nonce, ManifestBindings)` obtains the `finalized` block, performs all
`eth_call` operations with EIP-1898 `{blockHash, requireCanonical: true}`, then
rechecks that block by number and the chain ID before returning. There is no
fallback to `latest` or number-only calls when a provider lacks EIP-1898 support.

The static tuple decoders follow `FairBindCore.sol` exactly: purchase, seller,
profile and case, followed by the assigned verifier when present and the epoch
anchor for a SAMPLE case. Both exact byte lengths and Solidity integer/address
padding are checked. The returned assignment includes the finalized block,
assignment stage/attempt/deadline, signer key, current evidence hash, retention
bound and anchored receipt-proof root/count.

This is a trusted-RPC adapter, not a consensus verifier. A dishonest provider can
forge mutually consistent responses; the operator must select a trusted endpoint.
A finalized assignment may lag the live execution state. Callers must validate
that the assignment is actionable and reconcile again before signing/submission;
contract checks remain authoritative when state changes after the read.

`ManifestBindings` are caller-supplied expectations, not facts authenticated by
this reader. The verifier gate must hash canonical claims against the on-chain
`ClaimsHash` and compare those bindings before a predicate result is usable.
`MaxClaimsBytes` is a local operator bound; request, response and evidence bounds
come from the immutable profile. This package neither fetches seller bundles nor
polls events, stores secrets, signs verdicts or submits transactions.

`go test -count=1 ./runtime/ledger` uses a fake JSON-RPC server. It checks hash pins
on all calls, assigned signing keys and sample anchors, changed chain/block,
malformed ABI, relationship mismatch, oversized/error RPC responses and unsafe
configuration. These tests do not establish real-network finality or availability.
