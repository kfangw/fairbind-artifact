# FairBind Receipt Merkle Tree Version 1

Status: Release candidate for implementation

Each seller builds one ordered receipt tree for each settlement epoch. The tree
confirms that a seller committed a particular receipt. Sampling remains a
separate computation over ledger-recorded nonces.

## 1. Entries and order

An entry is `(nonce, receiptLeaf)`, where both values are `bytes32` and
`receiptLeaf` is the EIP-712 receipt digest. Entries sort by `nonce` interpreted
as an unsigned 256-bit big-endian integer. Duplicate nonces are invalid.

The entry hash is:

```text
entryHash = keccak256(abi.encode(
  bytes32(EPOCH_LEAF_DOMAIN),
  bytes32(nonce),
  bytes32(receiptLeaf)
))
```

## 2. Tree construction

The sorted entry hashes form level zero. Each higher level pairs adjacent nodes
without reordering them:

```text
parent = keccak256(abi.encode(
  bytes32(EPOCH_NODE_DOMAIN),
  bytes32(left),
  bytes32(right)
))
```

When a level has an odd number of nodes, its last node is paired with itself.
The rule repeats until one root remains. A nonempty settlement epoch MUST have a
nonempty tree. An epoch with no settlements has no anchor and uses the zero root
only in views.

The tree commits to `count` outside the hash. The contract accepts an anchor only
when `count` equals its settlement count for the seller and epoch. The anchor
carries the `(nonce, receiptLeaf)` pairs in order, 64 bytes per entry; the
contract requires the list length to equal `count` and the nonces to increase
strictly, hashes each pair to its entry hash and computes the root by this rule
(ADR 0026). A proof also
carries `count` so the verifier can enforce the expected tree height and odd-node
duplication rule.

## 3. Inclusion proof

An inclusion proof contains:

```text
nonce
receiptLeaf
index
count
siblings[]
```

`index` is the zero-based position in the sorted entry list. At each level, the
low bit of the current index determines whether the current node is left or
right. If an odd last node has no peer, its proof sibling MUST equal the current
node. The verifier hashes the pair, divides the index by two, and replaces the
level count with its ceiling divided by two. The proof succeeds only when it
consumes every sibling, ends at index zero and count one, and matches the anchor
root.

An inclusion proof does not prove by itself that the entry belongs to a real
purchase. The anchor transaction carries the complete list of pairs, and the
contract has checked that its nonces increase strictly, so every list position
holds a distinct nonce in order. The omission procedure uses adjacent positions.

## 4. Omission proof

Anyone proves omission of a settled purchase by submitting its nonce and either
two adjacent listed entries or one boundary entry, each as a `(nonce,
receiptLeaf)` pair with its inclusion proof. Neither the omitted purchase nor
the bounding entries need a receipt or a signature; a bounding entry may be a
filler that belongs to no purchase. The contract reads the seller and epoch of
the omitted nonce from its purchase record and uses that epoch's anchor.

An interior proof contains valid inclusion proofs for indices `i` and `i + 1`
with the anchored root and count and satisfies:

```text
left.nonce < omitted.nonce < right.nonce
```

A lower-bound proof uses the entry at index zero and satisfies
`omitted.nonce < first.nonce`. An upper-bound proof uses the entry at index
`count - 1` and satisfies `last.nonce < omitted.nonce`. A one-entry list uses
its single entry for either bound. An epoch with a settlement always has a
nonempty list, because `count` is at least one.

Because the anchor enforced strictly ascending nonces, such a bracket shows
that the omitted nonce is absent from the list. Count equality then means that
for every filler in the list some real purchase is absent, and each absent
purchase is provable in this way. The guarantee is: omission of any real
purchase is provable by anyone from the public list.

A listed nonce with another receipt leaf is not omission. Its buyer proves the
substitution with `proveMisanchoredReceipt`: its seller-signed receipt, the
anchored leaf at its nonce, and that entry's inclusion proof. The contract
checks the receipt against the purchase and the signature, and accepts when
the anchored leaf differs from the receipt's digest. Nonces are unique in the
list, so that entry is the seller's only commitment for the purchase. The
failure is recorded as equivocation. A substituted receipt at the buyer's own
nonce is provable only by that buyer, because the proof needs its signed
receipt.

## 5. Equivocation proof

Two valid seller-signed receipts prove equivocation when they have the same
chain, contract, seller, profile, nonce, request hash, claims hash, and epoch but
different `receiptDigest` values. Neither receipt needs an inclusion proof. The
contract rejects byte-identical duplicates.

An accepted omission, misanchored-receipt or equivocation proof finalizes the affected purchase as a
seller failure. It applies the same per-purchase refund and one-time seller
penalty rules as `EPOCH_FAILED`.

## 6. Availability

The `(nonce, receiptLeaf)` pairs are in the anchor transaction's call data, so
the list the root commits to, and every inclusion proof over it, is available
whenever the anchor is. The seller publishes the signed receipts and proof
material no later than the anchor transaction. It creates a manifest conforming to
[`../../schemas/epoch-publication-v1.schema.json`](../../schemas/epoch-publication-v1.schema.json)
and submits:

```text
publicationHash = keccak256(UTF8(JCS(manifest)))
```

The manifest binds the seller, profile, epoch, root, count, content-addressed
entry-list hash, and an HTTPS or IPFS retrieval location. The `createdAt` value
is advisory and is not a protocol deadline. Off-chain unavailability starts the
serve procedure and does not prevent `openSample` because sampling uses the
purchase ledger.

The examples in
[`../../test-vectors/merkle-v1.json`](../../test-vectors/merkle-v1.json) are
normative.
