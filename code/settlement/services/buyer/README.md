# Buyer

A FairBind buyer. It buys protected HTTP resources through the x402 version 2
`upfront` flow, keeps receipts, verifies inclusion after the seller's anchor,
and pursues non-delivery disputes and refunds.

## Purchase state machine

| State | Meaning and next step |
| --- | --- |
| `new` | A random idempotency key is saved. The unpaid request is sent; a `5xx` or transport error keeps the state. |
| `offered` | The offer passed validation and the signed `PaymentPayload` is saved before it is sent. The same payload is resent until a valid receipt arrives. |
| `received` | The response and a valid receipt are stored. Once the epoch is anchored the buyer fetches `/fairbind/proofs/{nonce}` and verifies it against the root from `getAnchor`. |
| `proven` | Inclusion is verified. |
| `disputed` | A `NON_DELIVERY` case is open. |
| `delivered` | The case ended `DELIVERED` but the body could not be read back from chain. |
| `refunded` | The contract paid the purchase amount back. |
| `abandoned` | The authorization expired and neither the nonce nor the key is on the ledger. |
| `failed` | The offer was refused before anything was signed. |

Offer validation: x402 version 2, an `exact` option on the configured network
with `eip3009-fairbind-v1` and `upfront`, `payTo` and `info.contract` equal to
the contract, amount within `maxPrice` and the profile's `maxPurchaseValue`,
the asset equal to the profile token, the known canonicalization, and
seller, profile, claims hash, deadlines and size limits equal to the chain
views. The buyer computes `requestHash` itself from the request it sends and
derives `keyId` and `nonce` (`protocol.DeriveKeyID`, `protocol.DeriveNonce`).
The EIP-3009 authorization is a `ReceiveWithAuthorization` under the token's
EIP-712 domain from the accepted entry, with `to` equal to the contract and the
derived nonce. The token accepts it only from the contract, so it can be spent
only through `settle` (ADR 0016).

A receipt is valid when it names this chain and contract, the purchase nonce,
request hash, seller, profile and claims hash, the settlement epoch, a
nonzero predicate commitment, the hash of the received body, and recovers to
the seller's registered signing key.

Background steps (`Tick`, also `POST /purchases/{id}/advance`):

- `offered`: after `responseDue` without a valid receipt, open
  `dispute(nonce, NON_DELIVERY, zero receipt, empty signature)`.
- `disputed`: in `SERVE_CONFIRM`, fetch `/fairbind/serve/{nonce}` with a
  buyer `FairBindServeAuthorization` (valid until the challenge deadline),
  check the bundle hash against the case, the request hash, the predicate
  preimage and the receipt, then `acceptServe`; otherwise `escalate`. After a
  serve or publication deadline passes, call `timeoutServe`. In `UNSERVED`,
  call `claimRefund(nonce)`. In `DELIVERED` after publication, read the body
  from the chain.
- `received` or `proven`: when the seller's bond account has an open claim
  window and `purchaseState` is `FROZEN_CLAIMABLE`, call
  `claimRefund(nonce, receipt, signature, proof)` (the proof is empty when the
  epoch was never anchored). When the anchor deadline passed without an
  anchor, call `claimEpochFailure` and `claimRefund`.

## Worst-path directive

With the `worst_path` block of the scenario directive (`-directive FILE`,
default `$FAIRBIND_DIRECTIVE`) the buyer opens no NON_DELIVERY dispute, so a
sampled sale is never turned into a dispute case, and claims a purchase from
a frozen bond only once the purchase's own case has ended.

## Control API

The API has no authentication; the command refuses a non-loopback address.

| Method and path | Result |
| --- | --- |
| `POST /purchases` with `{"method":"GET","url":"…","headers":[["Accept","application/json"]],"body":"<base64>"}` | the new purchase record |
| `GET /purchases` | purchase ids |
| `GET /purchases/{id}` | one record |
| `POST /purchases/{id}/advance` | run the next steps now |

## Data directory

```text
<dataDir>/.lock                    exclusive process lock
<dataDir>/purchases/<key>.json     purchase record, keyed by the idempotency key
```

A record holds `version`, `idempotencyKey`, the request, `state`, `reason`,
the offer, the signed payload, `nonce`, `requestHash`, `sellerId`, `epoch`,
`responseDue`, `claimUntil`, the settlement response, the response body and
its source (`http`, `serve` or `publication`), the receipt, the inclusion
proof and anchored root, and the hashes of transactions the buyer sent. Every
write is a temporary file, fsync, rename and directory fsync.

## Configuration

```json
{
  "listen": "127.0.0.1:8090",
  "dataDir": "/var/lib/fairbind/buyer",
  "network": "eip155:31337",
  "rpcUrl": "http://127.0.0.1:8545",
  "chainId": 31337,
  "contract": "0x…",
  "keyFile": "/etc/fairbind/buyer.key",
  "maxPrice": 10000,
  "tickSeconds": 2
}
```

The key signs authorizations and serve authorizations. Transactions are sent
through `eth_sendTransaction` from the key's address, so the node must sign
for it (for example an anvil account). Disputes need the profile's dispute
deposit approved for the contract; this service does not send approvals.

```sh
go run ./services/buyer/cmd/fairbind-buyer -config buyer.json
```

## Tests

`go test ./services/buyer/` uses the in-memory chain and a stub seller: a
purchase with receipt and inclusion proof, a restart that resends the saved
payload without a new authorization, abandonment of an expired unsettled
authorization, a non-delivery case accepted after serve across a restart, an
invalid receipt leading to a dispute and a mismatching bundle to escalation,
timeout and refund, a receipt claim in an open claim window, the
epoch-failure refund, and offer validation.
