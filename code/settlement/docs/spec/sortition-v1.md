# FairBind Verifier Sortition Version 1

Status: Release candidate for implementation

This document fixes verifier-set snapshots and the mapping from an assignment
ticket to a verifier. Snapshots are profile-specific because minimum bond and
weight cap are profile parameters.

## 1. Effective set

For profile `p`, a verifier belongs to a new checkpoint when all conditions hold:

- its status is `ACTIVE`;
- its class bitmap contains `p.classId`;
- its bond is at least `p.minVerifierBond`;
- its signing key and owner are nonzero.

Its checkpoint weight is:

```text
weight = min(verifierBond, p.verifierBondCap)
```

Entries sort by ascending `uint32 verifierId`. Zero-weight entries are omitted.
A checkpoint is valid for new settlement only when its entry count is at least
`p.minVerifiers`.

## 2. Checkpoint

`checkpointVerifierTree(profileId)` stores an immutable version containing:

```text
profileId
version
checkpointBlock
verifierIds[]
weights[]
totalEffectiveWeight
setHash
```

Versions start at one and increase by one per profile. The arrays have equal
nonzero length and strictly increasing verifier IDs. The set commitment is:

```text
setHash = keccak256(abi.encode(
  keccak256("fairbind/verifier-set/v1"),
  uint32(profileId),
  uint64(version),
  uint32[](verifierIds),
  uint96[](weights)
))
```

The contract derives entries from its registry; a caller cannot supply or omit
one. Since ADR 0025 each version also stores, in the order of `verifierIds`,
each verifier's liability room at `checkpointBlock`:

```text
reserve = max(verifierLatePenalty, verifierWrongPenalty)
room    = 0                                             if bond < reservedPenalties + reserve
room    = max(0, min(bond - reservedPenalties - reserve, cap) * fraction / 1e6 - lockedLiability)
```

with `cap` and `fraction` as in `profile-v1.md` section 5 (the profile values
while the verifier holds no liability, the conservative values otherwise),
capped at `2^96 - 1`. The room is not part of `setHash`; it is reported by
`getCheckpointHeadroom` and the `VerifierHeadroomCheckpointed` event. A call
that would reproduce the latest `setHash` contents and the latest room returns
that version and does not create another.

## 3. Epoch selection

At epoch sealing, the contract selects the latest checkpoint for the purchase
profile whose `checkpointBlock <= anchorDeadline`, by binary search over the
versions, whose checkpoint blocks never decrease. The beacon block lies
`beaconDelayBlocks + 1` blocks after `anchorDeadline` (`lifecycle-v1.md` section
1), so the checkpoint is fixed before the beacon exists. It stores the version,
`setHash`, and total weight in the anchor view. A later verifier mutation or
checkpoint cannot change that epoch.

New settlements require the latest checkpoint for their profile to contain at
least `minVerifiers`. An exit or class-removal request excludes a verifier from
later checkpoints but not from an already selected historical checkpoint. The
verifier's bond remains locked until every epoch and case that can use that
checkpoint has ended.

## 4. Ticket mapping

Given `ticket` from `cryptography-v1.md`, define cumulative weights in ascending
verifier ID order. The selected verifier is the unique entry `j` satisfying:

```text
sum(weights[0:j]) <= ticket < sum(weights[0:j+1])
```

The contract then applies case-local exclusion and the checkpoint room: the
selected verifier is unavailable when it already took part in the case or
when `purchaseValue + maxReviewCost` exceeds its room in the epoch's
checkpoint (ADR 0025, decision 126). The verifier's current status, bond and
open liability do not enter, so cases opened after the checkpoint block cannot
change which candidate is eligible.
If the selected verifier is unavailable for that case, it increases `round`,
derives a new ticket, and retries through round `minVerifiers - 1`. It does not
delete or renormalize an entry after seeing the ticket. Search exhaustion is
`INCONCLUSIVE`, except in the initial stage of a sampled case, which waits for
a redraw (section 5.1, ADR 0028).

Rounds draw independently with replacement. If the verifiers already in the
case hold a share `w` of the checkpoint weight, the search fails with
probability `w^minVerifiers`; with `N` equal weights and `k` excluded verifiers
this is `(k / N)^minVerifiers`. `profile-v1.md` section 5.1 sizes
`minVerifiers` against it.

## 5. Liability and exit

Assignment locks `purchaseValue + maxReviewCost` and reserves the larger
verifier penalty. A verifier remains bound by its checkpoint weight even after
requesting exit. A penalty reduces withdrawable bond but cannot release
existing liability. Since ADR 0025 new liability needs room in the checkpoint
only, not in the verifier's current effective-bond fraction: a verifier that
is full now may be assigned, and if it does not answer the judgment timeout
replaces it with the next candidate. Locked liability may therefore exceed the
current limit, and a penalty takes at most the remaining bond.

Finalizing a case releases its assignment liability. Finalizing verifier exit
requires zero locked liability and the end of every retention window whose
selected checkpoint contains that verifier.

### 5.1 Redraw of a waiting case (ADR 0028)

A waiting case records the version of its last search and that search's
block, `searchBlock`. A redraw uses the first checkpoint written in a block
after `searchBlock`:

```text
v           = latest version with checkpointBlock <= searchBlock, plus one
randomBlock = checkpointBlock(v) + 1 + beaconDelayBlocks
value       = blockhash(randomBlock), read after randomBlock, within 256 blocks
ticket      = keccak256(abi.encode(ASSIGN_DOMAIN, value, nonce, stage, attempt, round))
              mod totalEffectiveWeight(v)
```

The redraw applies section 4 to checkpoint `v` and its room. Later versions
do not change it. Without a version `v` the call reverts; before
`randomBlock + 1` it reverts. When the hash is no longer served, when `v` has
fewer than `minVerifiers` entries, or when the search is exhausted again, `v`
counts as searched at the current block and the case keeps waiting. After a
redraw that assigns, every later assignment of the case uses checkpoint `v`,
and every later initial attempt uses `value` instead of the epoch value. As in
section 3, the checkpoint is fixed before its value exists.

A verifier of checkpoint `v` is not held by an epoch exit lock; an assigned
verifier is held by its locked liability.

## 6. Conformance

The fixed set ordering and interval rule are language-neutral.
[`../../test-vectors/sortition-v1.json`](../../test-vectors/sortition-v1.json)
fixes checkpoint ABI bytes, `setHash`, and both sides of every cumulative ticket
boundary. M2 adds independent Solidity and Go consumers of that fixture.

ADR 0009 strengthens admission to the post-reserved-penalty effective bond formula in profile-v1.md. A submitted verdict retains its assignment liability and maximum penalty reservation until final case resolution. A voided assignment releases its own liability after the late penalty, and can never be selected again for that purchase. The profile floor is checked at checkpoint construction; ADR 0025 removes the
check at assignment.
