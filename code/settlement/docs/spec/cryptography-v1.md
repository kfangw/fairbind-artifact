# FairBind Cryptographic Encodings Version 1

Status: Release candidate for implementation

FairBind uses Keccak-256, Solidity ABI encoding, and EIP-712 typed data. A
`bytesN` value follows Solidity ABI rules: it occupies one 32-byte word and is
right-padded with zero bytes. Integers and addresses are left-padded. Every
integer is unsigned and encoded in big-endian ABI form.

## 1. Domain hashes

Implementations compute the following values from the exact UTF-8 strings.

| Name | Input string |
| --- | --- |
| `KEY_DOMAIN` | `fairbind/key/v1` |
| `PURCHASE_DOMAIN` | `fairbind/v1` |
| `HTTP_CANON_DOMAIN` | `fairbind/http-canon/v1` |
| `EPOCH_LEAF_DOMAIN` | `fairbind/epoch-leaf/v1` |
| `EPOCH_NODE_DOMAIN` | `fairbind/epoch-node/v1` |
| `SAMPLE_DOMAIN` | `fairbind/sample/v1` |
| `ASSIGN_DOMAIN` | `fairbind/verifier/v1` |
| `RECHECK_DOMAIN` | `fairbind/recheck/v1` |
| `SERVE_BUNDLE_DOMAIN` | `fairbind/serve-bundle/v1` |
| `RESPONSE_NODE_DOMAIN` | `fairbind/response-node/v1` |

Each table value is `keccak256(UTF8(input string))`. Implementations MUST NOT
include a trailing NUL or newline.

## 2. Purchase identifiers

The exact encodings are:

```text
keyId = keccak256(abi.encode(
  bytes32(KEY_DOMAIN),
  uint256(chainId),
  address(contractAddress),
  uint32(sellerId),
  address(buyer),
  bytes16(idempotencyKey)
))

nonce = keccak256(abi.encode(
  bytes32(PURCHASE_DOMAIN),
  uint256(chainId),
  address(contractAddress),
  uint32(sellerId),
  uint32(profileId),
  bytes32(claimsHash),
  address(buyer),
  bytes16(idempotencyKey),
  bytes32(requestHash)
))
```

The contract recomputes both values. The EIP-3009 authorization `from` MUST
equal `buyer`, `to` MUST equal `contractAddress`, and `nonce` MUST equal the
derived FairBind nonce. The buyer signs it as the EIP-3009
`ReceiveWithAuthorization` primary type under the token's EIP-712 domain:

```text
ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)
```

The type hash is
`0xd099cc98ef71107a616c4f0f941f04c322d8e254fe26b3c6668db87aae413de8`. A
`TransferWithAuthorization` signature over the same fields is not a valid
FairBind payment authorization (ADR 0016).

## 3. EIP-712 domain

FairBind receipts, serve authorizations, and verdicts use this domain:

```text
EIP712Domain(
  string name,
  string version,
  uint256 chainId,
  address verifyingContract
)
```

The values are `name = "FairBind"`, `version = "1"`, the active chain ID, and
the FairBind contract address. A signature for another deployment is invalid.

## 4. Response commitment

After the body boundary below, the implementation splits response bytes into
consecutive 16,384-byte chunks. Every non-final chunk has exactly that length;
the final chunk has 1 through 16,384 bytes. An empty body is represented by one
empty chunk. Each leaf is `keccak256(chunkBytes)`.

When there is one leaf, `responseHash` is that leaf. With multiple leaves, the
implementation constructs a positional binary tree:

```text
parent = keccak256(abi.encode(
  bytes32(RESPONSE_NODE_DOMAIN),
  bytes32(left),
  bytes32(right)
))
```

An unpaired final node is duplicated at every level. The final root is
`responseHash`. This rule equals `keccak256(responseBody)` for a response of at
most 16,384 bytes and permits the contract to verify larger on-chain
publications while storing only chunk hashes.

## 5. Seller receipt

The EIP-712 primary type is:

```text
FairBindReceipt(
  uint8 version,
  uint32 sellerId,
  uint32 profileId,
  bytes32 nonce,
  bytes32 requestHash,
  bytes32 responseHash,
  bytes32 claimsHash,
  bytes32 predicateCommitment,
  uint24 epoch,
  uint64 issuedAt
)
```

The type string used for `typeHash` is the single-line form below with no spaces:

```text
FairBindReceipt(uint8 version,uint32 sellerId,uint32 profileId,bytes32 nonce,bytes32 requestHash,bytes32 responseHash,bytes32 claimsHash,bytes32 predicateCommitment,uint24 epoch,uint64 issuedAt)
```

The wire receipt also carries `chainId` and `contractAddress` so a recipient can
construct the EIP-712 domain. Those two fields do not appear again in the
primary type. The receipt version is `1`.

The response bytes are the entity body after transfer-coding removal and before
content-coding removal. Their `responseHash` follows Section 4. A response that
uses content coding MUST include `content-encoding` in the signed predicate
commitment or in a service-class receipt rule that the profile identifies.

`predicateCommitment` is always `bytes32`. A service-class codec hashes its
canonical evidence commitment before the seller constructs the receipt. The
value cannot be zero when the profile requires evidence.

The implementation computes:

```text
receiptStructHash = keccak256(abi.encode(
  bytes32(receiptTypeHash),
  uint8(1),
  uint32(sellerId),
  uint32(profileId),
  bytes32(nonce),
  bytes32(requestHash),
  bytes32(responseHash),
  bytes32(claimsHash),
  bytes32(predicateCommitment),
  uint24(epoch),
  uint64(issuedAt)
))

receiptDigest = keccak256(
  bytes.concat(hex"1901", domainSeparator, receiptStructHash)
)

receiptLeaf = receiptDigest
```

The seller signs `receiptDigest` with the registered signing key. Signatures use
the 65-byte `r || s || v` format, require a low `s`, and use `v` equal to 27 or
28. The contract rejects a malleable signature or a recovered address that does
not equal the seller registration snapshot for the purchase.

## 6. Serve authorization

The buyer or assigned verifier signs this EIP-712 type before using the off-chain
serve endpoint:

```text
FairBindServeAuthorization(bytes32 nonce,uint8 role,uint64 caseOpenedBlock,uint64 validUntil)
```

`role` is `1` for `BUYER` and `2` for `VERIFIER`. `validUntil` is a block number
and MUST NOT exceed the active serve deadline. The server checks the current
case, the opening block, the deadline, and the recovered signer. A verifier
signature is valid only for the verifier assigned to the current stage and
attempt.

## 7. Verifier verdict

A verifier signs the following EIP-712 type so a relayer may submit the verdict:

```text
FairBindVerdict(uint8 version,bytes32 nonce,uint8 stage,uint8 attempt,uint32 verifierId,uint8 verdict,bytes32 evidenceHash)
```

`version` is `1`. `verdict` is `1` for `PASS`, `2` for `FAIL`, and `3` for
`INCONCLUSIVE`. `stage` is `1` for the initial judgment, `2` for party review,
`3` for automatic review, and `4` for the tiebreaker. `attempt` is zero based
within that stage. The contract verifies that `stage`, `attempt`, and
`verifierId` name the active assignment. A verdict cannot be reused after
timeout or reassignment.

## 8. Serve bundle

A served response bundle is identified by:

```text
bundleHash = keccak256(abi.encode(
  bytes32(SERVE_BUNDLE_DOMAIN),
  bytes32(nonce),
  bytes16(idempotencyKey),
  bytes32(requestHash),
  bytes32(responseHash),
  bytes32(receiptDigest),
  bytes32(predicateCommitment)
))
```

The bundle conforms to
[`../../schemas/fairbind-serve-bundle-v1.schema.json`](../../schemas/fairbind-serve-bundle-v1.schema.json)
and carries the normalized `CanonicalRequest`, response body, receipt,
predicate-commitment preimage, and any available inclusion proof. A requester
recomputes their hashes and the expression above before calling `acceptServe`.
The proof is omitted from the hash because more than one valid proof transport
may represent the same anchored entry.

## 9. Random selection hashes

Sampling uses:

```text
sampleValue = uint256(keccak256(abi.encode(
  bytes32(SAMPLE_DOMAIN),
  bytes32(epochRandomness),
  uint32(sellerId),
  uint24(epoch),
  bytes32(nonce)
)))
```

`epochRandomness` is `blockhash(randomBlock)` with `randomBlock =
anchorDeadline + 1 + beaconDelayBlocks` (`lifecycle-v1.md` section 1). The
sampling predicate itself is unchanged: it runs over ledger nonces, never over
receipt leaves.

The purchase is sampled when `samplePpm == PPM`, or when `samplePpm < PPM` and
`sampleValue < sampleThreshold`. A zero probability is never selected. Automatic
recheck applies the same boundary rule to `recheckPpm` and `recheckThreshold`.

Verifier assignment uses:

```text
assignmentValue = uint256(keccak256(abi.encode(
  bytes32(ASSIGN_DOMAIN),
  bytes32(caseRandomness),
  bytes32(nonce),
  uint8(stage),
  uint8(attempt),
  uint32(round)
)))

ticket = assignmentValue % totalEffectiveWeight
```

Automatic recheck selection uses:

```text
recheckValue = uint256(keccak256(abi.encode(
  bytes32(RECHECK_DOMAIN),
  bytes32(reviewRandomness),
  bytes32(nonce)
)))
```

The recheck opens when `recheckValue < recheckThreshold`.

## 10. Test vectors

[`../../test-vectors/cryptography-v1.json`](../../test-vectors/cryptography-v1.json)
contains exact domain, identifier, receipt, signature, sample, assignment, and
recheck values. The private keys in that file are public test fixtures and MUST
NOT secure a deployment.
