# Facilitator

An x402 version 2 facilitator for the FairBind `eip3009-fairbind-v1` asset
transfer method with the `upfront` flow. It checks a `PaymentPayload`, calls
FairBind `settle`, and returns an x402 `SettlementResponse` with the FairBind
settlement extension.

## Endpoints

| Method and path | Body | Result |
| --- | --- | --- |
| `GET /supported` | none | the single supported kind and the `fairbind` extension |
| `POST /verify` | `{"x402Version":2,"paymentPayload":…,"paymentRequirements":…}` | `{"isValid":…}` from stateless checks only |
| `POST /settle` | same as `/verify` | `SettlementResponse` on success; `{"success":false,"errorReason":…,"transaction":…}` otherwise |

Stateless checks: x402 version, `accepted` equal to `paymentRequirements`,
scheme, network, transfer method, flow, `payTo` and authorization `to` equal
to the contract, the asset equal to the configured deployment token, token
domain name and version, amount equal to the
authorization value, the FairBind-derived nonce, the validity window, and the
EIP-3009 `ReceiveWithAuthorization` signature. The contract repeats every
state-sensitive check.

The facilitator never calls the token itself. The buyer signs
`ReceiveWithAuthorization`, which the token executes only when the caller is
the payee, and the payee is the FairBind contract; `settle` makes that call.
The saved authorization is therefore useless outside `settle`, including the
copy that a reverted `settle` leaves in public calldata (ADR 0016).

`/settle` answers `200` for every settlement outcome and `400` for a malformed
or invalid request. Failure reasons use the binding's identifiers
(`fairbind_key_conflict`, `fairbind_nonce_used`, `fairbind_seller_inactive`,
`fairbind_rate_limited`, `fairbind_value_too_large`, …).

## Idempotency and recovery

Before submitting, the facilitator writes the exact `settle` arguments to the
settlement journal (`runtime/settlement`). Every call, including a retry,
first reconciles through `getPurchase(nonce)` and `purchaseByKey(keyId)`:

- a matching record returns success without a transaction;
- a record for another request under the same key returns
  `fairbind_key_conflict`;
- no record resubmits the same saved arguments.

A saved authorization is replaced only after its transaction reverted and the
ledger has neither the key nor the nonce. A transport failure never permits a
replacement. On start, `Recover` resumes every purchase whose last status is
`submitting`.

## Data directory

```text
<dataDir>/.lock                     exclusive lock held by the running process
<dataDir>/journal/<nonce>.json      runtime/settlement journal record (version 1)
<dataDir>/journal/<nonce>.json.lock per-record journal lock
<dataDir>/attempts/<nonce>.json     facilitator attempt record
```

An attempt record:

```json
{
  "version": 1,
  "nonce": "0x…",
  "status": "submitting | confirmed | rejected | conflict",
  "transactions": ["0x…"],
  "revert": "SellerInactive",
  "updatedAt": 1788480000
}
```

All files are written to a temporary file, fsynced, renamed and followed by a
directory fsync.

## Configuration

```json
{
  "listen": "127.0.0.1:8402",
  "dataDir": "/var/lib/fairbind/facilitator",
  "network": "eip155:31337",
  "rpcUrl": "http://127.0.0.1:8545",
  "chainId": 31337,
  "contract": "0x…",
  "from": "0x…",
  "token": "0x…",
  "tokenName": "MockUSDC",
  "tokenVersion": "2",
  "settlementSchema": "schemas/fairbind-settlement-v1.schema.json"
}
```

`from` must be an account the node signs for through `eth_sendTransaction`
(an anvil unlocked account or a signing proxy). The facilitator holds no
private key.

```sh
go run ./services/facilitator/cmd/fairbind-facilitator -config facilitator.json
```

## Tests

`go test ./services/facilitator/` runs against the in-memory chain in
`services/internal/x402/chain`: settlement and retries without a second
transaction, a lost transaction response followed by a restart, replacement of
a reverted authorization, key conflicts, stateless rejections, and the HTTP
handler.
