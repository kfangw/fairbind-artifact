# FairBind Binding for x402 Version 2

Status: Release candidate for implementation
FairBind extension key: `fairbind`
Asset transfer method: `eip3009-fairbind-v1`
Payment flow: `upfront`

## 1. Compatibility target

This binding targets x402 version 2 at the revision in `UPSTREAMS.lock.json`.
The relevant upstream documents are the
[core v2 specification](https://github.com/x402-foundation/x402/blob/2cc7e9a6880c08433b692666032862bcbea51187/specs/x402-specification-v2.md),
[HTTP transport](https://github.com/x402-foundation/x402/blob/2cc7e9a6880c08433b692666032862bcbea51187/specs/transports-v2/http.md),
and [exact EVM binding](https://github.com/x402-foundation/x402/blob/2cc7e9a6880c08433b692666032862bcbea51187/specs/schemes/exact/scheme_exact_evm.md).

FairBind defines a new exact-EVM asset transfer method. The binding is
wire-compatible with x402 version 2: the headers, the `PaymentRequired`,
`PaymentPayload` and `SettlementResponse` objects, and the facilitator
`/supported`, `/verify` and `/settle` endpoints keep their x402 shapes. It is
not a stock exact-EVM payment, and an unmodified x402 client or facilitator
cannot take part:

- the client derives the authorization nonce from the purchase
  (`cryptography-v1.md` section 2) instead of choosing a random one;
- the client signs the EIP-3009 `ReceiveWithAuthorization` typed message, not
  `TransferWithAuthorization`, with the FairBind contract as `to`;
- the facilitator calls FairBind `settle`; the contract, not the facilitator,
  calls the token, and the token call is `receiveWithAuthorization`.

The last two points close the stranded-authorization path of ADR 0016. A
stock facilitator submits `transferWithAuthorization` to the token itself. With
a transfer-typed authorization naming the contract, that call, or the same call
by anyone who copies the authorization from a `settle` that reverted, would move
the buyer's funds into the contract with no purchase record. EIP-3009 executes
`receiveWithAuthorization` only when the caller is the payee, so the FairBind
authorization can be spent only through `settle`, and the token rejects it as a
`TransferWithAuthorization`. Existing facilitators must add this method before
they advertise support.

The first binding supports only `upfront`. Its order is:

```text
settle -> protected resource -> response
```

The resource server does not call facilitator `/verify` in this flow.

## 2. HTTP encoding

The x402 headers use RFC 4648 standard base64 of a compact UTF-8 JSON object.
The encoder retains required `=` padding. JSON object member order has no
semantic meaning. Header fixtures select one order so implementations can test
their encoder.

| Header | Direction | Decoded object |
| --- | --- | --- |
| `PAYMENT-REQUIRED` | server to buyer | x402 `PaymentRequired` |
| `PAYMENT-SIGNATURE` | buyer to server | x402 `PaymentPayload` |
| `PAYMENT-RESPONSE` | server to buyer | x402 `SettlementResponse` |
| `X-FairBind-Receipt` | server to buyer | FairBind seller receipt |

`X-FairBind-Key` uses unpadded base64url because it carries raw 16-byte data,
not JSON. `X-FairBind-Receipt` uses standard base64 of compact JSON.

## 3. Initial request

The first unpaid request contains:

```text
X-FairBind-Key: ABEiM0RVZneImaq7zN3u_w
X-FairBind-Payer: 0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266
```

The resource server requires exactly 22 base64url characters for the key and
decodes them to 16 bytes. The payer is an advisory EVM address at this stage. It
is not authentication. On the paid retry it MUST equal
`payload.authorization.from`.

The first request already contains every profile-selected canonical header. The
resource server computes `requestHash` before constructing `PaymentRequired` and
retains it with the offered key for the response timeout. It MUST NOT put the
hash in the unpaid response, because the buyer computes it independently.

## 4. PaymentRequired

The server returns HTTP `402` and a `PAYMENT-REQUIRED` header whose decoded
object follows this structure:

```text
{
  "x402Version": 2,
  "error": "Payment required",
  "resource": {
    "url": "https://api.example.test/v1/quote",
    "description": "Signed market quote",
    "mimeType": "application/json",
    "serviceName": "FairBind Test API"
  },
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:31337",
    "amount": "10000",
    "asset": "0x2222222222222222222222222222222222222222",
    "payTo": "0x1111111111111111111111111111111111111111",
    "maxTimeoutSeconds": 60,
    "extra": {
      "assetTransferMethod": "eip3009-fairbind-v1",
      "paymentFlow": "upfront",
      "name": "MockUSDC",
      "version": "2"
    }
  }],
  "extensions": {
    "fairbind": {
      "info": {
        "version": 1,
        "contract": "0x1111111111111111111111111111111111111111",
        "sellerId": 7,
        "profileId": 3,
        "bondId": 1,
        "serviceClass": "data-api",
        "predicateId": "0x...",
        "canonId": "0x...",
        "claimsHash": "0x...",
        "profileHash": "0x...",
        "canonicalHeaders": ["accept", "content-type", "x-model"],
        "quotedAtBlock": 5300,
        "remaining": 20,
        "responseBlocks": 60,
        "claimBlocks": 1800,
        "maxRequestBytes": 65536,
        "maxResponseBytes": 65536,
        "retentionBlocks": 22000
      },
      "schema": <inline negotiation schema>
    }
  }
}
```

The wire value represented by `<inline negotiation schema>` is the complete
object in `schemas/fairbind-extension-v1.schema.json` with its top-level `$id`,
`title`, and `description` members removed. The server inlines it. It does not
use an external or absolute `$ref`. Every `$ref` is a same-document JSON Pointer
fragment beginning with `#`. A recipient MUST NOT resolve a network or file
reference while validating an x402 extension.

The server derives the contract, seller, profile, claims, canonical headers,
deadlines, and size limits from contract state and the profile document. It
derives `quotedAtBlock` and `remaining` from one `quoteSeller` call. Those two
fields are advisory snapshots. `remaining` reads the bucket of the seller's bond
account, which every registration under that account shares, so settlements
through another registration can consume it. Their values may become stale
before settlement, and settlement remains the authority.

`bondId` identifies the bond account the seller registration points to. The
buyer compares it against the seller registration on chain; a mismatch is
`fairbind_profile_mismatch`.

`accepts[0].payTo` MUST equal `extensions.fairbind.info.contract`. The selected
asset MUST equal the immutable deployment token. The requested amount MUST be no
larger than the profile's `maxPurchaseValue`. The request and any later on-chain
publication MUST remain within `maxRequestBytes`.

## 5. PaymentPayload

The buyer validates `PaymentRequired`, reconstructs `requestHash`, derives
`keyId` and `nonce`, and creates the EIP-3009 authorization. The paid retry's
decoded `PAYMENT-SIGNATURE` object has the x402 v2 fields `x402Version`,
`resource`, `accepted`, `payload`, and `extensions`.

The buyer copies the selected `accepts` entry to `accepted`. It copies the
server's complete `fairbind` extension, including the inline schema, without
deleting or replacing a server field. It then adds these two fields to
`extensions.fairbind.info`:

```json
{
  "idempotencyKey": "0x00112233445566778899aabbccddeeff",
  "requestHash": "0x6e6717945809f177d93714f3750a01da09d79ca8245518f15a475df062373246"
}
```

The paid request MUST contain the same `X-FairBind-Key` and
`X-FairBind-Payer`. The server checks all four representations: HTTP key,
extension key, HTTP payer, and authorization payer.

The authorization contains decimal strings for `value`, `validAfter`, and
`validBefore`, as required by the x402 exact EVM binding. It satisfies:

```text
authorization.from  = X-FairBind-Payer
authorization.to    = accepted.payTo = fairbind.info.contract
authorization.value = accepted.amount
authorization.nonce = FairBind-derived nonce
```

The payment signature is the EIP-3009 `ReceiveWithAuthorization` signature
defined by the selected token, over the same six fields as the x402 exact EVM
payload. `accepted.extra.name` and `accepted.extra.version` supply its EIP-712
domain values. FairBind does not replace the token's domain; it selects the
EIP-3009 receive type instead of the transfer type (ADR 0016). A facilitator
MUST reject a payload whose signature verifies only as a
`TransferWithAuthorization`, and MUST NOT submit the authorization to the token
itself.

The resource server compares the parsed server-authored extension fields with
the offer it issued. It does not compare raw JSON bytes or object order. A
changed, missing, or newly added server-authored field produces
`fairbind_extension_echo_mismatch`.

## 6. Settlement

The resource server sends the standard x402 `/settle` request to a facilitator
that advertises this combination from `/supported`:

```text
x402Version = 2
scheme = exact
network = selected CAIP-2 network
extra.assetTransferMethod = eip3009-fairbind-v1
extra.paymentFlow = upfront
extensions includes fairbind
```

The facilitator performs stateless checks when possible and then submits
FairBind `settle`, which pulls the payment with `receiveWithAuthorization`. The contract repeats every state-sensitive and
security-sensitive check. Success means that the contract durably holds the
purchase amount in `DEFERRED`. It does not mean that the seller has received the
funds or delivered the resource.

A successful x402 `SettlementResponse` follows this structure:

```text
{
  "success": true,
  "transaction": "0x...",
  "network": "eip155:31337",
  "payer": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266",
  "amount": "10000",
  "extensions": {
    "fairbind": {
      "info": {
        "version": 1,
        "purchase": "0x...",
        "keyId": "0x...",
        "sellerId": 7,
        "profileId": 3,
        "epoch": 14,
        "financialState": "DEFERRED"
      },
      "schema": <inline settlement schema>
    }
  }
}
```

The inline settlement schema is
`schemas/fairbind-settlement-v1.schema.json` with its top-level `$id` and title
removed. The resource server returns this object in `PAYMENT-RESPONSE` after the
protected handler finishes.

The facilitator may also return an internal `EXTENSION-RESPONSES` sidechannel.
That header is not forwarded to the buyer and never substitutes for the standard
settlement response or the on-chain purchase record.

## 7. Protected response and receipt

The resource server executes the protected handler only after successful
settlement or successful reconciliation of an earlier settlement. It computes
the response hash, predicate commitment, and seller EIP-712 receipt under
`cryptography-v1.md`.

The server encodes the compact receipt JSON in standard base64 and sends it in
`X-FairBind-Receipt`. For a streaming response it declares the header as an HTTP
trailer before sending the body. A non-streaming response sends a normal header.

`PAYMENT-RESPONSE` proves the facilitator's settlement result. The seller
receipt binds the request and response. The on-chain transaction remains the
authority for settlement state.

## 8. Retry and reconciliation

A retry of one purchase reuses the entire `PaymentPayload`, EIP-3009 signature,
`X-FairBind-Key`, and normalized protected request. The buyer does not choose a
new authorization nonce while the original settlement is uncertain.

When `/settle` returns `settlement_pending`, it includes a nonempty transaction
hash. The server polls that transaction and queries `purchaseByKey` and
`getPurchase`. It returns the recorded success when the key, nonce, buyer,
seller, profile, claims, request hash, and amount all match. It returns
`fairbind_key_conflict` when the key identifies another request. It constructs a
new authorization only after the earlier transaction has failed finally and no
FairBind record exists.

## 9. HTTP status and cache rules

| Condition | Status | Required x402 header |
| --- | --- | --- |
| missing payment | `402` | `PAYMENT-REQUIRED` |
| malformed FairBind or x402 input | `400` | none required |
| valid payment that settlement rejects | `402` | `PAYMENT-RESPONSE` |
| internal failure before a settlement result | `500` | none required |
| settled and resource returned | resource status, normally `200` | `PAYMENT-RESPONSE` and `X-FairBind-Receipt` |

Responses with `PAYMENT-REQUIRED`, failed `PAYMENT-RESPONSE`, or
buyer-specific reconciliation data use `Cache-Control: no-store`. A successful
protected response uses at least `Cache-Control: private` unless a stricter
policy already applies.

## 10. Error identifiers

FairBind-specific failures use stable lowercase identifiers:

```text
fairbind_extension_missing
fairbind_extension_invalid
fairbind_extension_echo_mismatch
fairbind_profile_mismatch
fairbind_claims_mismatch
fairbind_unknown_canon
fairbind_canonicalization_failed
fairbind_request_hash_mismatch
fairbind_nonce_mismatch
fairbind_key_used
fairbind_key_conflict
fairbind_nonce_used
fairbind_seller_inactive
fairbind_rate_limited
fairbind_value_too_large
fairbind_settlement_pending
fairbind_receipt_missing
```

Clients branch on identifiers rather than human-readable text. The adapter maps
contract custom errors to this list without discarding the original selector or
transaction hash from diagnostic logs.

## 11. Unsupported combinations

Version 1 rejects:

- x402 version 1 messages;
- a scheme other than `exact`;
- a payment flow other than `upfront`;
- an asset transfer method other than `eip3009-fairbind-v1`;
- a token without EIP-3009 `receiveWithAuthorization`;
- a `payTo` value different from the FairBind contract;
- a token different from the deployment token;
- missing, changed, or externally referenced extension data;
- an unknown canonicalization rule;
- a request above the profile's purchase or response bound.

Support for `authorization`, `escrow`, another token, or another asset transfer
method requires a new binding version or a separately tested capability.

## 12. Conformance vectors

The decoded message fixtures and exact header encodings under
[`../../test-vectors/x402-v2/`](../../test-vectors/x402-v2/) are normative.

## 13. Seller redelivery endpoints

A FairBind seller serves two unpaid endpoints next to its protected resources.
They carry no x402 headers and are not part of the payment exchange. The
bundle and claims formats are fixed by `cryptography-v1.md` and
`predicate-interface-v1.md`; this section fixes the HTTP surface. Error
responses use `Content-Type: application/json` and the body
`{"error":"<identifier>"}`.

### 13.1 Claims document

```text
GET /fairbind/claims
```

The request has no parameters and needs no authorization. The response is
`200` with `Content-Type: application/json` and a body that is exactly the
claims document the seller registration commits to: the bytes
`UTF8(JCS(claims))` of `predicate-interface-v1.md`, so that

```text
keccak256(body) == claimsHash
```

for the `claimsHash` of the seller registration on chain (`getSeller`), which
every purchase and receipt of that registration repeats. The seller returns
the stored bytes unchanged; it does not re-serialize them. Because a change of
claims requires a new registration, the body of one registration never
changes, and the response MAY be cached (`Cache-Control: public,
max-age=86400, immutable`). A seller MUST refuse to start when its configured
claims document does not hash to its registration's `claimsHash`.

A verifier fetches the claims document together with the serve bundle and,
before it evaluates the predicate, checks that the body is no longer than its
configured claims bound and that `keccak256(body)` equals the purchase's
`claimsHash`. A body that fails either check is not used: the verifier does
not judge from it, and its gate ends the evaluation as `INCONCLUSIVE` (reason
`claims_binding`) rather than `PASS` or `FAIL`. The check authenticates the
claims against the chain, not against the seller's server, so the endpoint
needs no signature.

### 13.2 Serve bundle

```text
GET /fairbind/serve/{nonce}
X-FairBind-Serve-Authorization: base64(JSON)
```

`{nonce}` is the purchase nonce as `0x`-prefixed hex of 32 bytes, in either
letter case. The header carries the standard base64 encoding of the JSON object

```json
{"role":2,"caseOpenedBlock":123,"validUntil":456,"signature":"0x..."}
```

whose signature is the `FairBindServeAuthorization` of `cryptography-v1.md`
section 6. On success the response is `200` with the serve bundle version 1
JSON and `Cache-Control: no-store`. The seller evaluates the conditions in
this order and answers the first that holds:

| Condition | Status | `error` |
| --- | --- | --- |
| `{nonce}` is not a 32-byte hex value | `400` | `invalid_nonce` |
| header missing, not strict base64, not the JSON object above, or a signature that is not hex | `400` | `serve_authorization_malformed` |
| the chain could not be read (at this or a later check) | `500` | `serve_authorization_check_failed` |
| no case is open for the nonce, or its case already ended (`NONE`, `DELIVERED`, `UNSERVED`, `INCONCLUSIVE`, `FINAL`) | `404` | `unknown_purchase` |
| `caseOpenedBlock` differs from the case, `validUntil` exceeds the active deadline (`serveDue`, `challengeUntil` or `publishDue` in the serve states), the current block is past `validUntil`, or no signer can be recovered | `401` | `serve_authorization_invalid` |
| `role` is neither `1` (`BUYER`) nor `2` (`VERIFIER`) | `400` | `serve_authorization_malformed` |
| the recovered signer is not the purchase buyer (role `1`) or the signing key of the verifier assigned to the case (role `2`) | `401` | `serve_authorization_invalid` |
| the authorization is valid but the seller holds no retained response | `404` | `fairbind_receipt_missing` |

In a judging state, where no serve deadline applies, `validUntil` bounds the
authorization by itself; the reference verifier sets it to the assignment's
`judgeDue`. A `KEEPER` requester has no serve authorization role and cannot use this
endpoint (ADR 0014).
