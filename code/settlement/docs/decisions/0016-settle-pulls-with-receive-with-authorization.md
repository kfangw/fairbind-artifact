# ADR 0016: Settle pulls the payment with receiveWithAuthorization

Status: Accepted 2026-09-26. Revises the token call of `fairbind-v1.md`
sections 4 and 9, the payment authorization type of `cryptography-v1.md`
section 2, and the compatibility statement and payload rules of
`x402-v2-integration.md` sections 1, 5, 6 and 11.

## Problem

`settle` moved the payment with EIP-3009
`transferWithAuthorization(from = buyer, to = C, ...)`, where `C` is the
FairBind contract. `transferWithAuthorization` may be submitted by any caller:
the signed message is the only authority the token checks.

The signed authorization is not private. The facilitator holds it, the seller's
resource server forwards it, and the calldata of every `settle` that reverted
publishes it, for example a `settle` rejected with `RateLimitExceeded`,
`BondNotActive` or `Paused`. Whoever holds it can call the token directly:

```text
token.transferWithAuthorization(buyer, C, value, validAfter, validBefore, nonce, v, r, s)
```

The call succeeds, the buyer's funds move into `C`, and the token marks the
nonce as used. No purchase is recorded: no `keyId`, no deferred entry, no case,
no refund path. The funds are stranded in `C`, and the buyer cannot settle the
same purchase again because the token refuses the used nonce.

This is not only a hostile case. A stock x402 exact-EVM facilitator executes
exactly this call by default: its settlement step for an EIP-3009 payload is
`transferWithAuthorization` to `payTo`, and `payTo` is `C`. A resource server
that points a FairBind offer at a stock facilitator strands every payment.

## Decision

`settle` pulls the payment with EIP-3009 `receiveWithAuthorization`.

1. Token call. `settle` calls
   `receiveWithAuthorization(from, to, value, validAfter, validBefore, nonce, v, r, s)`
   with `to = C`. EIP-3009 requires `msg.sender == to` for this function, and the
   caller is `C`, so the call is valid only when `C` makes it, and `C` makes it
   only inside `settle`, after every admission check and in the same
   transaction that records the purchase.
2. Signed type. The buyer signs the EIP-712 primary type
   `ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)`
   under the token's own domain. The six fields and the nonce derivation are
   unchanged. The token does not accept this signature as a
   `TransferWithAuthorization`, because the type hash differs, so a direct
   `transferWithAuthorization` with the FairBind authorization fails signature
   recovery.
3. Facilitator. The facilitator verifies the `ReceiveWithAuthorization`
   signature and calls `settle`. It never calls the token.
4. Wire. The x402 message shapes, headers and facilitator endpoints are
   unchanged. The binding is wire-compatible with x402 version 2 but is not a
   stock exact-EVM payment: the client derives the nonce, signs the receive
   type, and the facilitator calls `C.settle`. `x402-v2-integration.md`
   section 1 states this instead of implying that an unmodified facilitator
   works.
5. Token requirement. The deployment token must implement EIP-3009
   `receiveWithAuthorization` with the `msg.sender == to` check. Circle USDC
   (FiatToken version 2 and later) does.

The ABI of `settle` is unchanged. The struct keeps the name
`TransferAuthorization`; only the function the contract calls on the token and
the type the buyer signs change.

## Consequences

- A signed FairBind authorization moves the buyer's funds only through a
  `settle` that records the purchase. A reverted `settle` leaves the
  authorization unspent and reusable for a later `settle` of the same purchase,
  as the retry rules of `x402-v2-integration.md` section 8 assume.
- A stock facilitator that ignores the transfer method and submits the payload
  to the token fails: `transferWithAuthorization` rejects the signature, and
  `receiveWithAuthorization` rejects the caller. The buyer loses nothing.
- Every cross-language payment vector changes: the type hash, struct hash,
  digest and signature in `test-vectors/cryptography-v1.json`, and the payment
  signature in `test-vectors/x402-v2/`. The purchase identifiers do not change.
- The repository mock token implements both functions. The baseline
  reproduction of a plain upfront payment (`ReproA` A1) still models a stock
  facilitator with `transferWithAuthorization` to the seller wallet, which is
  the rail FairBind is compared against.

## Properties

- P1: strengthened. Before, an authorization for a purchase could move funds
  without the purchase record, so "payment at most once" held for recorded
  purchases but a payment could exist with no record. Now every token movement
  under a FairBind authorization is the effect of one `settle` that recorded
  one purchase; identifier derivation and uniqueness are unchanged.
- P2: strengthened. Funds of a stranded authorization had no delivery or refund
  path; that state is no longer reachable.
- P3: unchanged.
- P4: unchanged.

## Regression

`contracts/test/FairBindM1.t.sol`:

- `testStrandedAuthorizationCannotBeSpentOutsideSettle`: a `settle` reverts with
  `RateLimitExceeded`; a direct `receiveWithAuthorization` with the published
  authorization from any caller other than `C` reverts; a direct
  `transferWithAuthorization` with the same signature reverts on signature
  recovery; the buyer balance, the custody balance and the token nonce are
  unchanged; the same authorization then settles through `settle`.
- `testTransferTypedAuthorizationIsStrandableAndRejectedBySettle`: the old
  wire (a `TransferWithAuthorization` signature naming `C`) is refused by
  `settle`, and the same authorization submitted directly by a third party
  moves the buyer's funds into `C` with no purchase record, which is the
  behaviour this decision removes from the FairBind path.

`services/internal/x402/x402_test.go` checks that the vector signature
recovers the buyer as a `ReceiveWithAuthorization` and does not as a
`TransferWithAuthorization`. `scripts/check_spec.py` checks the recorded
primary type and type hash.

## Alternatives considered

Keep `transferWithAuthorization` and rely on the facilitator. Rejected: the
authorization is public after any reverted `settle`, and the default behaviour
of a stock facilitator is the harmful call.

Use `permit` and `transferFrom`. Rejected: an allowance outlives the purchase,
the permit can likewise be executed by anyone, and it changes the x402 payload
shape.

Record a purchase when funds arrive without one. Rejected: the contract has no
callback on an EIP-3009 transfer, and no request, seller or profile is bound to
a bare transfer, so there is nothing to record.
