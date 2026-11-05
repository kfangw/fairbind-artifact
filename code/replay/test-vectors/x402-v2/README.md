# x402 Version 2 Binding Vectors

The four message files contain the decoded JSON objects for one successful
FairBind purchase. `headers.json` contains the standard-base64 encoding of the
compact serialization. Regenerate it after changing a decoded message with
`python3 scripts/check_spec.py --update-x402-headers`, then run `make check`.

The payment authorization signature is an EIP-3009 `ReceiveWithAuthorization`
test signature (ADR 0016) for:

```text
token name: MockUSDC
token version: 2
chain ID: 31337
token: 0x2222222222222222222222222222222222222222
buyer: 0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266
FairBind contract: 0x1111111111111111111111111111111111111111
```

Its digest and signature also appear in `../cryptography-v1.json`. The
transaction hash in `settlement-response.json` is a fixture, not a signed value.

The test performs these checks:

1. decode each header and compare the JSON value with its source file;
2. validate negotiation and settlement `info` against their inline schemas;
3. require the paid extension to preserve every server-authored field and add
   only `idempotencyKey` and `requestHash`;
4. recompute the EIP-3009 digest and FairBind-derived nonce, and require a
   canonical signature encoding;
5. recompute the seller receipt digest and response hash, and require a
   canonical signature encoding;
6. require `payTo`, authorization `to`, and FairBind `contract` to match.
7. require a nonzero `bondId` in the negotiation and payment `info` and in the
   negotiation schema.
