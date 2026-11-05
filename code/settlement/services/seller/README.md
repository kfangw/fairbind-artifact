# Seller

A FairBind resource server. It sells protected HTTP resources through the
x402 version 2 `upfront` flow, signs a receipt for each settled purchase,
retains the purchase for `retentionBlocks`, anchors each settlement epoch, and
answers redelivery and publication obligations.

## Request flow

1. The unpaid request carries `X-FairBind-Key` (22 base64url characters) and
   `X-FairBind-Payer`. The server canonicalizes the request with
   `adapters/httpcanon` using the profile's canonical headers, computes
   `requestHash`, stores the offer, and answers `402` with
   `PAYMENT-REQUIRED`: price, `payTo` equal to the contract, and the
   `fairbind` extension (seller, profile, claims and profile hashes,
   deadlines, size limits, a `quoteSeller` snapshot, the inline schema).
2. The paid retry carries `PAYMENT-SIGNATURE`. The server checks the accepted
   entry, that every server-authored extension field equals an issued offer,
   the four key and payer representations, the recomputed `requestHash`, and
   the derived nonce. It saves the purchase with the exact payload, then
   calls the facilitator's `/settle`.
3. Success, `fairbind_settlement_pending` and transport errors are all
   confirmed through `getPurchase` and `purchaseByKey`
   (`protocol.Reconcile`); the facilitator's answer is not trusted alone. An
   unconfirmed outcome answers `402` with a failed `PAYMENT-RESPONSE` and
   keeps the purchase for a retry with the same payload.
4. After confirmation the handler runs once. The server signs the receipt
   (`cryptography-v1`), persists body and receipt, then answers with the body,
   `PAYMENT-RESPONSE` and `X-FairBind-Receipt`. Retries of a delivered
   purchase return the stored response and receipt unchanged, so a nonce never
   receives two different receipts.

## Background work (`Tick`)

- Reconcile purchases left in `settling` by a crash.
- Anchor: for every epoch whose window `[epochEnd(e+1), epochEnd(e+1) +
  anchorBlocks]` is open, read the ledger nonces from `Settled` events, sign
  receipts for settled purchases never fetched, build the sorted receipt tree,
  write the entry list and manifest, and submit
  `anchor(sellerId, e, root, count, publicationHash)`. A lost anchor response
  is resolved from `getAnchor` on the next pass.
- Cases: when a purchase is in `SERVE_WAIT`, record `served(nonce,
  bundleHash)`; when it is in `PUBLISHING`, publish the request, body, receipt
  and signature on chain (single call up to 16,384 bytes, chunked above, with
  chunk progress persisted).
- Retention: after `retainUntil`, with no open case, drop request, body and
  payload; keep the receipt.

With the `worst_path` block of the scenario directive (`-directive FILE`,
default `$FAIRBIND_DIRECTIVE`; `experiments/controller/worstpath.py`) each call
is timed to the block that includes it (sent at block `b`, it lands in
`b + 1`): every epoch is anchored at its anchor deadline, and on a case opened
by sampling the seller records `served` at the serve deadline, lands the last
publication transaction at the publication deadline, requests the evidence of
every initial `FAIL` at the appeal deadline (`requestEvidence`) and appeals
the one whose evidence was disclosed at the renewed appeal deadline. The
requests and the appeal are recorded under `directed` in the purchase record.
The appeal deposit is paid from the owner account, which needs the balance
and allowance. `-progress FILE` writes the head block of every completed
pass.

With the `finite_attack` block (`experiments/controller/finiteattack.py`) the
seller numbers its sales in the order it accepts their payments and cheats on
the first `cheat_sales`: it serves the route's `cheatBodyFile` (same preimage)
when the configuration names one, and marks the record `cheat`. Afterwards
`after` selects the course: `serve_honestly` keeps selling honestly;
`stop_selling` answers new offers and new payments with 503
`seller_not_selling` and keeps serving the sales it accepted; `request_exit`
stops selling the same way and, once its cheated sales are delivered, calls
`requestSellerExit` and `requestBondExit`, then `finalizeSellerExit` and
`finalizeBondExit` as soon as the contract admits them. Progress is kept in
`meta/attack.json` (`accepted`, `cheated`, `refused`, the exit blocks).

## Endpoints

| Path | Purpose |
| --- | --- |
| any configured route | the protected resource |
| `GET /fairbind/serve/{nonce}` | serve bundle; requires `X-FairBind-Serve-Authorization` |
| `GET /fairbind/claims` | the exact registered claims document (hashes to the registration `claimsHash`) |
| `GET /fairbind/proofs/{nonce}` | inclusion proof against the anchored root |
| `GET /fairbind/epochs/{e}/entries` | sorted entry list (canonical JSON), hashed into `entriesHash` |
| `GET /fairbind/epochs/{e}/manifest` | epoch manifest, hashed into `publicationHash` |

`X-FairBind-Serve-Authorization` is standard base64 of
`{"role":1|2,"caseOpenedBlock":N,"validUntil":N,"signature":"0x…"}`, where the
signature is the `FairBindServeAuthorization` EIP-712 signature of the buyer
(role 1) or the assigned verifier (role 2). `validUntil` may not exceed the
active serve deadline and must not have passed.

`GET /fairbind/serve/{nonce}` answers `400` for a malformed header, `404` for
an unknown nonce or a case that already ended, `401` when the authorization
does not verify (wrong signature, wrong signer, or an expired or mismatched
`caseOpenedBlock`/`validUntil`), and `404` again when authenticated but the
bundle itself is unavailable.

## Data directory

```text
<dataDir>/.lock                   exclusive process lock
<dataDir>/offers/<key>-<payer>.json   issued offers (key, payer, requestHash, issued infos, expiry)
<dataDir>/purchases/<nonce>.json  purchase record
<dataDir>/epochs/<epoch>.json     anchor record (entries, root, manifest, publicationHash, state)
<dataDir>/meta/cursor.json        {"version":1,"nextEpoch":N}
```

A purchase record holds `state` (`settling`, `settled`, `delivered`,
`rejected`, `pruned`), the identifiers, the canonical request, the paid
payload, the settlement response, epoch, `settledBlock`, `retainUntil`, the
response and preimage, the signed receipt, and the served bundle hash and
publication progress. An anchor record's `state` is `submitting`, `anchored`,
`empty` or `missed`. Every write is a temporary file, fsync, rename and
directory fsync.

## Configuration

```json
{
  "listen": "127.0.0.1:8080",
  "dataDir": "/var/lib/fairbind/seller",
  "publicUrl": "https://api.example.test",
  "network": "eip155:31337",
  "rpcUrl": "http://127.0.0.1:8545",
  "chainId": 31337,
  "contract": "0x…",
  "owner": "0x…",
  "sellerId": 7,
  "signingKeyFile": "/etc/fairbind/seller.key",
  "facilitatorUrl": "http://127.0.0.1:8402",
  "serviceName": "Example API",
  "serviceClass": "data-api",
  "profileHash": "0x…",
  "canonicalHeaders": ["accept"],
  "price": 10000,
  "maxTimeoutSeconds": 60,
  "tokenName": "MockUSDC",
  "tokenVersion": "2",
  "extensionSchema": "schemas/fairbind-extension-v1.schema.json",
  "settlementSchema": "schemas/fairbind-settlement-v1.schema.json",
  "claimsFile": "claims.json",
  "tickSeconds": 2,
  "routes": [{
    "path": "/v1/quote",
    "description": "Signed market quote",
    "mimeType": "application/json",
    "bodyFile": "quote.json",
    "preimage": {"kind": "data-api", "referenceTime": "1788480000",
      "sourceSetHash": "0x…", "tolerancePolicyHash": "0x…"}
  }]
}
```

`owner` must be the seller owner and an account the node signs for through
`eth_sendTransaction`. Instead of `signingKeyFile`, `keystore` with
`castPath`, `keystorePath` and `passwordFile` signs receipts through
`runtime/judgment.KeystoreSigner`. At start the server checks that the signer
recovers to the registered signing key. Profile values (canonicalization,
deadlines, size limits, epoch schedule) come from the chain; the profile
document supplies `serviceClass`, `profileHash` and `canonicalHeaders`.
`claimsFile` is the exact claims document; the server refuses to start unless
its keccak256 equals the seller registration's `claimsHash`.

```sh
go run ./services/seller/cmd/fairbind-seller -config seller.json
```

## Tests

`go test ./services/seller/` uses the in-memory chain and a facilitator stub:
receipt and idempotent replay, negotiation rejections, a lost settlement
outcome followed by a restart, anchoring at the window with a lost anchor
response and restart, proofs, manifest and entry hashes, retention pruning,
and the serve, escalation and publication path in single-call and chunked
form across a restart. `directed_test.go` checks the worst-path schedule: the
review decision table and each call one block before its deadline.
