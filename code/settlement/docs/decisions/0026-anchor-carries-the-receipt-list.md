# ADR 0026: The anchor carries the receipt list

Status: Accepted 2026-10-12, revised the same day after code review 3 of
IMPL2. Amends ADR 0024 and ADR 0025 (assumption A-LEAF) in `fairbind-v1.md`
section 11, `merkle-v1.md` sections 2 to 6 and `contract-interface-v1.md`
sections 7 and 10. Changes the signatures of `anchor` and `proveOmission`,
adds `proveMisanchoredReceipt` and the error `EntriesNotAscending`; changes no
event, no storage slot, no tree encoding and no inclusion proof format.

The research decision this record implements is decision 130 of the project
record (2026-10-12): assumption A-LEAF (A7), "the seller publishes its receipt
list", becomes a contract rule.

## Problem

An anchor committed to a root and a count. The ordered list behind the root
lived off chain, in the seller's publication (`merkle-v1.md` section 6), and
the protocol assumed the seller published it. A buyer needs that list to see
that its receipt is in the tree and, when it is not, to prove the omission.

The first version of this record put the entry hashes in the anchor and kept
the omission proof of `merkle-v1.md` version 1, which needed the omitted
buyer's signed receipt and two seller-signed neighbour receipts at adjacent
positions in nonce order. Review 3 showed that the contract checked only the
list length: a seller could put a filler in the omitted purchase's place,
anchor fillers only, or anchor the list out of order, and in each case no
omission proof could be formed. It also showed that a seller could anchor a
different leaf at a buyer's position and nothing on chain could show it.

## Decision

1. **The list is an argument of `anchor`, as pairs.** `anchor(sellerId, epoch,
   entries, count, publicationHash)` takes `ReceiptEntry[] entries`, where
   `ReceiptEntry` is `(bytes32 nonce, bytes32 receiptLeaf)`
   (`FairBindMerkle.ReceiptEntry`), 64 bytes of call data per entry.
2. **Checks.** The existing checks stay: seller owner, active seller, nonzero
   `publicationHash`, `count` nonzero and equal to the settlement count, state
   `NONE`, the anchor window. `anchor` also requires `entries.length == count`
   (`CountMismatch`) and strictly increasing nonces (`EntriesNotAscending`),
   which makes the list sorted and free of repeated nonces. Both checks read
   call data only; the contract does not read a purchase record per entry.
3. **The contract computes the root.** `FairBindMerkle.computeRoot` hashes each
   pair to `entryHash = keccak256(abi.encode(EPOCH_LEAF_DOMAIN, nonce,
   receiptLeaf))` and applies the rule of `merkle-v1.md` section 2: adjacent
   nodes pair left to right under `EPOCH_NODE_DOMAIN`, an odd last node pairs
   with itself, one entry's hash is the root. This is the rule
   `FairBindMerkle.verify` checks. A zero root reverts `InvalidConfiguration`.
4. **Omission is provable by anyone from the public list.**
   `proveOmission(nonce, left, leftProof, right, rightProof, boundary)` takes
   the nonce of a settled purchase and the bounding entries as pairs with
   inclusion proofs against the anchor of that purchase's seller and epoch.
   Interior: indices `i` and `i + 1`, `left.nonce < nonce < right.nonce`.
   Lower: index 0, `nonce < right.nonce`. Upper: index `count - 1`,
   `left.nonce < nonce`. A one-entry list uses its entry for either bound; a
   settled epoch never has an empty list. No receipt and no signature is
   needed, and a bounding entry may be a filler. Because nonces strictly
   increase, a bracket proves absence; because the length equals the
   settlement count, each filler leaves some real purchase absent. The old
   signed-neighbour form is removed: no other check depended on it.
5. **A substituted leaf is provable by its buyer.**
   `proveMisanchoredReceipt(receipt, signature, anchoredLeaf, proof)` takes a
   seller-signed receipt, the leaf the anchor holds at the receipt's nonce and
   that entry's inclusion proof. It checks the receipt against the purchase
   and the seller's signing key, and accepts when `anchoredLeaf` differs from
   the receipt digest. Nonces are unique in the list, so that entry is the
   seller's only commitment for the purchase. The failure goes through
   `_sellerFailure(nonce, EQUIVOCATION)`, the path of `proveEquivocation`:
   the purchase becomes `REFUNDABLE`, the case trigger is `EQUIVOCATION`, and
   the confirmed failure, deduction and freeze are those of a double
   signature. Like `proveOmission` it needs an anchored root and reverts after
   the purchase's `retainUntil`.
6. **Nothing else moves.** The list is not stored. `AnchorView`, the
   `Anchored` event (root and count), `publicationHash`, `randomBlock`,
   `sealDeadline`, the state machine and `timeoutAnchor` are unchanged.

What the rule guarantees: omission of any real purchase is provable by anyone
from the public list; a substituted receipt at the buyer's own nonce is
provable only by that buyer (needs its signed receipt).

## Consequences

The list costs 64 bytes of call data per entry, one entry hash per entry and
one node hash per parent. `test_anchorGasByListLength` measures the anchor
call frame (`lastCallGas`, router storage and the sampling module cooled
first, the purchase count written to storage), counts the call data bytes,
and fails if a frame value moves more than 5% from the table. Nonces ascend
with a 4-byte rank above 28 pseudo-random bytes; leaves are pseudo-random.

| Entries | Call frame gas | Call data bytes | Zero bytes | Call data gas (EIP-2028) | EIP-7623 tokens | Standard cost | EIP-7623 floor | Transaction gas |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 108,928 | 260 | 157 | 2,276 | 569 | 132,204 | 26,690 | 132,204 |
| 10 | 113,949 | 836 | 159 | 11,468 | 2,867 | 146,417 | 49,670 | 146,417 |
| 100 | 154,606 | 6,596 | 181 | 103,364 | 25,841 | 278,970 | 279,410 | 279,410 |
| 1,000 | 563,890 | 64,196 | 411 | 1,022,204 | 255,551 | 1,607,094 | 2,576,510 | 2,576,510 |
| 3,245 | 1,644,343 | 207,876 | 963 | 3,314,460 | 828,615 | 4,979,803 | 8,307,150 | 8,307,150 |

Standard cost is `21,000 + call data gas + call frame gas`; the EIP-7623
floor is `21,000 + 10 * tokens`; a transaction after Prague pays the larger.
From 1 to 3,245 entries the frame grows by 473.3 gas per entry, the call data
by 1,021.0 gas per entry and the tokens by 255.25 per entry (floor 2,552.5 gas
per entry). The floor exceeds the standard cost from 100 entries on. The
anchor writes slots from zero only, so there is no refund. Rollup data fees
are not included.

The router grows to 10,692 bytes and the sampling module to 19,949 bytes,
both under the 24,576-byte limit.

The services pass the pairs: `chain.Writer.Anchor` takes `[]x402.Entry`, the
seller service sends the entries `BuildTree` sorted by nonce (and rejected
repeats in), and the fake chain checks the order and computes the root as the
contract does. The recorded router ABI changes in the `anchor` and
`proveOmission` entries and gains `proveMisanchoredReceipt` and
`EntriesNotAscending`; the contract has not been deployed.

## Assumptions and limits

1. **Entries are checked for order, not for content.** The contract does not
   check that a listed nonce is a purchase of the epoch or that a listed leaf
   is a signed receipt. Fillers are therefore allowed, and each one is paid
   for by an absent real purchase whose omission anyone can prove.
2. **A substituted leaf needs its buyer.** A seller that anchors another leaf
   at a real purchase's nonce (J2 in the design 2 rule) is exposed only by a
   holder of the signed receipt, which is the buyer or the seller. A keeper
   without the receipt cannot prove it.
3. **Call data availability.** The list is as available as the chain's
   transaction history. On a rollup whose call data is pruned from the data
   availability layer after a window, availability after that window depends
   on archive nodes.
4. **One transaction per anchor.** The list length must equal the settlement
   count in a single call, so the largest epoch a seller can anchor is set by
   the transaction gas limit. `test_anchorEntryLimitPerTransaction` measures
   it with the data above: 11,742 entries fit a 30,000,000 gas transaction
   (29,999,860 gas; 11,743 entries need 30,002,420) and 6,562 entries fit a
   16,777,216 gas transaction (EIP-7825; 16,775,900 gas; 6,563 need
   16,778,460). In both cases the EIP-7623 floor binds. Under the evaluation
   rule a bucket admits 137 + 0.05 per block over 300 blocks, 152 purchases
   per multiplier unit in a 10-minute epoch, so one transaction covers a
   multiplier of at most 77 (30,000,000) or 43 (16,777,216). The busiest
   replayed Base seller has multiplier 536, that is 81,472 purchases per
   epoch, whose anchor would need at least about 208.0 million gas (the floor
   alone): 7 transactions at 30,000,000 or 13 at 16,777,216. Such a seller
   cannot anchor in this version and its epochs fail by `timeoutAnchor`. A
   seller above the limit must anchor in chunks, which is left to the next
   version.
