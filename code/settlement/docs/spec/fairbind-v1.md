# FairBind Version 1 Protocol Specification

Status: Release candidate for implementation
Version: 1.0.0-rc.1
Date: 2026-09-04

## 1. Scope

FairBind adds post-settlement fair exchange to autonomous agent payments. A purchase record binds the payer's authorization to a seller, an immutable service profile, advertised claims, an idempotency key, and a normalized request. A seller-signed receipt later binds the same purchase to the response and the evidence needed by its predicate.

The protocol does not verify every response before settlement. It samples purchases after settlement, assigns bonded verifiers, and provides bounded procedures for redelivery, judgment, appeal, recheck, refund, and penalty. A token bucket bounds the value exposed while a failure moves from settlement to enforcement.

Version 1 supports two service classes:

1. data APIs checked against independent external references;
2. open-weights inference checked with a process-evidence predicate.

The protocol may add service classes without changing the purchase state machine.

## 2. Normative language

The terms MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY, and OPTIONAL are normative requirements.

## 3. Roles

| Symbol | Role | Responsibility |
| --- | --- | --- |
| `A` | buyer | Chooses the idempotency key, signs the payment authorization, stores the response and receipt, and may open a dispute. |
| `S` | seller | Registers an immutable profile, serves the resource, signs receipts, anchors receipt epochs, and answers redelivery requests. |
| `F` | facilitator | Verifies the x402 payload and submits `settle` to the FairBind contract. |
| `C` | FairBind contract | Holds deferred funds, records purchases, selects samples, assigns verifiers, applies deadlines, releases funds, and pays refunds and penalties. |
| `V` | verifier | Retrieves a sampled response, runs the registered predicate, and submits a signed verdict and evidence hash. |
| `K` | keeper | Calls public state transitions after their fixed block deadlines. A keeper has no discretion over the result. |

One entity may operate several roles in a test deployment. Security claims treat their keys and economic interests separately.

## 4. Cryptographic and system assumptions

FairBind version 1 relies on the following assumptions.

1. Keccak-256 is collision resistant and preimage resistant for the encoded inputs used by this specification.
2. EIP-712 signatures are unforgeable for the registered buyer, seller, and verifier keys.
3. The payment token implements EIP-3009 `receiveWithAuthorization`, executes it only when the caller is the payee, and rejects reuse of an authorization nonce.
4. The execution layer provides finality after the configured confirmation policy.
5. At least one keeper calls each eligible public timeout transition within its stated call window.
6. An honest buyer who needs recovery can submit a transaction before the claim deadline.
7. Each predicate declares and measures a false rejection rate and a false acceptance rate for its service profile.
8. Verifier assignment maintains the profile's lower bound on honest effective bond after excluding prior participants in the same case.

Version 1 uses a future block hash as public randomness. The contract MUST record the randomness block before that block is known. A keeper MUST seal the value while the execution layer still exposes that block hash.

## 5. Registered objects

### 5.1 Service profile

A service profile is immutable. Its identifier selects all rules that affect a purchase, including:

- deployment-token scope and service class;
- predicate identifier and request canonicalization identifier;
- epoch length and raw sampling probability;
- lower bound on effective detection probability;
- token-bucket capacity and refill rate;
- maximum exposure rate and enforcement-delay bound;
- deferred-fund and retention periods;
- response, claim, anchor, serve, judgment, appeal, and sealing deadlines;
- maximum request, response, and predicate-evidence sizes, bounded publication
  and review costs, and maximum purchase value;
- seller reserve requirement and verifier penalties;
- verifier bond cap and maximum open-liability fraction;
- beacon delay and beacon slack;
- frozen-pool claim window and the locked forfeiture;
- failure limit, failure window, inconclusive threshold, and inconclusive window;
- freeze timing (`freezeOnInitialFail`) and the minimum judged count before
  the inconclusive threshold applies.

A profile change creates a new `profileId`. It MUST NOT alter an existing profile.

### 5.2 Seller

A seller registration contains `sellerId`, `bondId`, `profileId`, `signingKey`,
`claimsHash`, the block of its last suspension, and lifecycle state. It holds no
bond balance, penalty reservation, or token-bucket state; those belong to the
bond account it names (section 5.4).

A seller MAY accept new settlements only in `ACTIVE` and only while its bond
account is `ACTIVE`, not sanctioned, not frozen, and holds at least the
profile's `sellerPenalty`. Changing the profile, signing key, or advertised
claims requires a new seller registration. A registration names exactly one
bond account for its lifetime, and the bond account's profile MUST equal the
registration's profile.

### 5.3 Verifier

A verifier registration contains `verifierId`, supported service classes, signing key, bond balance, pending liability, and lifecycle state. The effective assignment weight is the smaller of the verifier bond and the profile's verifier bond cap.

A verifier exit request removes it from later checkpoints. It remains eligible
under an already selected historical checkpoint, and bond withdrawal takes
effect only after every assignment and retention window that depends on that
checkpoint has ended.

### 5.4 Bond account

A bond account contains `bondId`, `profileId`, owner, balance, scale factor,
token-bucket state, the failure and inconclusive counters with their window
starts, the deferred and encumbered totals of its registrations, the freeze
state with its trigger nonce, freeze block, and claim deadline, the set of
pending initial-`FAIL` triggers (ADR 0015), and its lifecycle state. Any number of seller registrations MAY name one bond account;
they share its bucket first come, first served, and one failure under any of
them freezes the deferred entries of all of them (section 18).

```text
scaleFactor = floor(balance / sellerPenalty)
capacity    = bucketCapacity    * scaleFactor
refill      = refillPpmPerBlock * scaleFactor
```

The scale factor is recomputed on every top-up and every slash. A slash lowers
it at once and clips the current bucket level to the new capacity. The scale
factor never increases without a token transfer into the bond account, and
adding or removing a registration never changes the bucket level. Only the
account owner may top up (ADR 0022). Every drop of the scale factor updates
the account's recent scale high (`recentScaleHigh`): the level left becomes
the record when it is higher or the record is more than `retentionBlocks`
old, and the drop block is recorded in every case, so the record bounds from
above every scale the account held within `retentionBlocks` before any later
block (section 18).

## 6. Purchase identifiers

The buyer chooses a uniformly random 16-byte idempotency key `k`. The buyer MUST reuse the same `k` for retries of one purchase and MUST NOT intentionally reuse it for another purchase.

The protocol derives two identifiers. Implementations MUST use Solidity ABI encoding with the exact types listed below. They MUST NOT use ambiguous byte concatenation.

```text
keyId = keccak256(abi.encode(
  keccak256("fairbind/key/v1"),
  uint256(chainId),
  address(contractAddress),
  uint32(sellerId),
  address(buyer),
  bytes16(k)
))

nonce = keccak256(abi.encode(
  keccak256("fairbind/v1"),
  uint256(chainId),
  address(contractAddress),
  uint32(sellerId),
  uint32(profileId),
  bytes32(claimsHash),
  address(buyer),
  bytes16(k),
  bytes32(requestHash)
))
```

`keyId` prevents a second successful settlement when the same idempotency key is attached to a different request. `nonce` binds the payment authorization to the seller, profile, advertised claims, buyer, idempotency key, and normalized request.

The contract MUST recompute both values during settlement. It MUST reject settlement if either value conflicts with a recorded purchase.

[`cryptography-v1.md`](cryptography-v1.md) defines the exact ABI types, domain
hashes, signatures, and machine-readable vectors.

## 7. Request canonicalization

The profile's `canonId` selects a versioned canonicalization rule. The rule MUST define the following inputs:

- uppercase HTTP method;
- normalized path;
- normalized query sequence;
- exact request body bytes;
- the names and values of profile-selected headers.

The canonicalization rule MUST define percent encoding, duplicate query keys, empty values, header-name casing, whitespace, repeated headers, and body compression. Implementations MUST reject an unknown `canonId` before requesting a payment signature.

`requestHash` is Keccak-256 over the output of the selected canonicalization
rule. [`canonicalization-v1.md`](canonicalization-v1.md) defines the version 1
byte format, rejection rules, and test vectors.

## 8. Payment negotiation

The x402 version 2 binding is normative in [`x402-v2-integration.md`](x402-v2-integration.md). A compatible resource server advertises the `fairbind` extension, the `eip3009-fairbind-v1` asset transfer method, and the supported payment flow.

The first implementation supports `upfront`. The facilitator commits funds to the FairBind contract before the resource executes. The payment authorization is an EIP-3009 `ReceiveWithAuthorization` that names the FairBind contract as its recipient (ADR 0016).

## 9. Settlement

The facilitator submits:

```text
settle(sellerId, profileId, claimsHash, k, requestHash, authorization, signature)
```

The contract MUST execute the following checks and effects atomically:

1. reject reentrancy;
2. require the seller to be `ACTIVE`;
3. require `profileId` and `claimsHash` to equal the seller registration;
4. recompute `keyId` and `nonce`;
5. reject a used `keyId` or `nonce`;
6. update and consume the seller token bucket;
7. mark `keyId` and `nonce` as in use;
8. call the token's EIP-3009 `receiveWithAuthorization` into the FairBind contract;
9. record the immutable purchase fields and settlement epoch;
10. add the payment amount to the seller's deferred-fund schedule;
11. emit `Settled`.

An external token-call failure MUST revert the entire settlement, including identifier and bucket updates.

The token call MUST be `receiveWithAuthorization`, never `transferWithAuthorization`.
EIP-3009 executes `receiveWithAuthorization` only when the caller is the payee,
and the payee is the FairBind contract, so the buyer's authorization moves funds
only inside a `settle` that records the purchase. A signed authorization is
visible to the facilitator, the seller's resource server, and anyone who reads
the calldata of a `settle` that reverted; under `transferWithAuthorization` any
of them could submit it to the token directly and move the buyer's funds into
the contract with no purchase record and no refund path (ADR 0016). The buyer
therefore signs the `ReceiveWithAuthorization` typed message, which the token
does not accept as a `TransferWithAuthorization`.

When a retry fails because an identifier is already used, the facilitator MUST
query `getPurchase(nonce)` and `purchaseByKey(keyId)`. It returns the recorded
settlement when every immutable purchase field and amount match. It returns an
idempotency conflict when the key identifies another request. Reconciliation is
read-only and never changes `settle` behavior.

## 10. Response receipt

The seller returns the response body and a seller-signed receipt. Non-streaming HTTP responses carry the receipt in `X-FairBind-Receipt`. Streaming responses carry it in a declared HTTP trailer.

The signed receipt contains:

```text
version
chainId
contractAddress
sellerId
profileId
nonce
requestHash
responseHash
claimsHash
predicateCommitment
epoch
issuedAt
signature
```

The response body boundary, 16,384-byte chunking rule, and `responseHash` tree
are fixed by `cryptography-v1.md`. For a body no larger than one chunk, the value
is the ordinary Keccak-256 body hash. The receipt leaf excludes the signature
and hashes the typed receipt fields. The seller signs the EIP-712 digest of that
leaf.

The predicate commitment is a service-class-specific `bytes32` hash. A data API
profile records a reference-time policy, source identifiers, and tolerance-policy
identifier. An open-weights inference profile records process evidence and a
configuration hash that covers the model, precision, batch size, and software
version.

Advertised claims use the canonical manifest and `claimsHash` rule in
`predicate-interface-v1.md`. The receipt's class-specific commitment preimage
must agree with that manifest.

An empty required commitment is a seller violation and produces `FAIL`. It
never counts as `PASS` or `INCONCLUSIVE`. The contract accepts a seller-signed
receipt with an empty commitment only together with a `FAIL` verdict.

The receipt EIP-712 type, body boundary, digest, and signature rules are
normative in [`cryptography-v1.md`](cryptography-v1.md). The receipt leaf equals
the EIP-712 digest.

## 11. Epoch anchoring

For settlement epoch `e`, the seller builds a Merkle tree from pairs of `(nonce, receiptLeaf)`, sorted by ascending nonce. The seller submits:

```text
anchor(sellerId, e, entries, count, publicationHash)
```

`entries` is the list of `(nonce, receiptLeaf)` pairs, level zero of the tree before hashing, 64 bytes per entry. The contract MUST require `count` to equal the number of settlements it recorded for the seller in epoch `e`, the length of `entries` to equal `count`, and the nonces to increase strictly; it computes the root from the list and stores it (ADR 0026). The anchor deadline follows the fixed end of epoch `e + 1`.

The list is published by the anchor transaction itself, so anyone can rebuild the root and any inclusion proof from chain data. Omission of any real purchase is provable by anyone from the public list: two adjacent entries whose nonces bracket the purchase's nonce, or the first or last entry at the ends, show that the nonce is absent, and no receipt is needed. A substituted receipt at the buyer's own nonce is provable only by that buyer, because the proof needs its seller-signed receipt: the anchored leaf at that nonce differs from the signed one. Two seller signatures for the same nonce and different receipt leaves prove equivocation. The seller still publishes its signed receipts and serves inclusion proofs.

[`merkle-v1.md`](merkle-v1.md) defines the leaf and node hashes, odd-node rule,
inclusion proofs, omission boundaries, and equivocation proof.

Failure to anchor by the deadline changes the epoch to `EPOCH_FAILED`. Every purchase in that epoch becomes eligible for an individual refund without a receipt or Merkle proof.

## 12. Randomness and sampling

The anchor records the future `randomBlock` fixed by the formulas in
`lifecycle-v1.md`:

```text
randomBlock = anchorDeadline + 1 + beaconDelayBlocks
```

The value depends only on the epoch schedule and the profile, never on the
anchor submission block, and the anchor deadline always precedes the beacon
block by `beaconDelayBlocks + 1` blocks. After that block becomes available,
any account may call `seal(sellerId, epoch)`. The contract stores:

```text
epochRandomness = blockhash(randomBlock)
```

The caller cannot select another block. A seal outside the permitted block-hash window fails the epoch safely rather than accepting caller-supplied randomness.

`beaconDelayBlocks` is the settlement-chain equivalent of the L1 beacon delay
`Delta` (at least 128 L1 blocks; 768 blocks on a two-second chain, enforced at
profile admission, `profile-v1.md` section 2). A
deployment that reads the L1 origin block and its RANDAO value indexes the
beacon by the L1 block `l1Origin(anchorDeadline) + Delta` and admits a seal only
within `beaconSlackL1Blocks` L1 blocks of it. Version 1 on a chain without an
L1 origin realizes the delay in settlement-chain blocks with the block hash as
the beacon and requires `beaconSlackL1Blocks == 0`.

A purchase is sampled when:

```text
uint256(keccak256(abi.encode(
  keccak256("fairbind/sample/v1"),
  epochRandomness,
  uint32(sellerId),
  uint24(epoch),
  bytes32(nonce)
))) < sampleThreshold
```

`sampleThreshold` represents the profile's raw sampling probability on the full
256-bit interval. `samplePpm == PPM` selects every purchase without materializing
the unrepresentable integer `2^256`.

Sampling uses nonces already recorded by the contract. Receipt inclusion does not determine eligibility. Any account may call `openSample(nonce)` during the sample-opening window. The caller does not need the receipt or an inclusion proof.

A sampled purchase whose case was never opened is never released. `openSample`
remains callable after the sample-opening window for such a purchase, so the
seller or any keeper can still open it; its funds stay deferred until its case
ends.

## 13. Verifier assignment

The epoch seal stores the purchase-profile verifier-set version and total
effective weight from the latest checkpoint whose checkpoint block is no later
than the anchor deadline. This snapshot is already historical when sealing becomes
possible and therefore cannot depend on the sealing caller. Assignment uses it
for the lifetime of the epoch.

For an assignment round, the contract derives a domain-separated ticket from
the case randomness, nonce, stage, attempt, and round. It maps the ticket into
the cumulative effective-bond tree. `cryptography-v1.md` defines the exact ABI
encoding.

The contract MUST skip a verifier when any of the following conditions holds:

- the verifier already participated in the same case;
- the verifier did not support the purchase service class at the snapshot;
- the new responsibility would make the verifier's open liability exceed the profile fraction of its effective bond;
- the verifier was not eligible at the snapshot.

The contract tries rounds `0` through `minVerifiers - 1`. Each ticket is checked
against the immutable weighted tree and the current exclusion and liability
rules. Failure to find an eligible verifier in that bounded search ends the case
as `INCONCLUSIVE`. `maxAssignments` separately limits assigned verifiers that
may time out within one judgment stage. Because one case can exclude up to
`3 * maxAssignments - 1` verifiers before its last search, a profile is admitted
only with `minVerifiers >= 3 * maxAssignments + 5`, which keeps the probability
that this last search fails at or below `10^-3` for equal-weight verifier sets
(`profile-v1.md` section 5.1, ADR 0023).

[`sortition-v1.md`](sortition-v1.md) fixes checkpoint contents, profile scope,
ascending verifier order, ticket intervals, historical exit liability, and
search exhaustion.

If the latest checkpoint for an active profile has fewer than that profile's
minimum eligible verifiers, the contract MUST stop new seller registrations and
settlements under that profile. Existing cases continue with bounded retries.

## 14. Redelivery

A buyer opens `dispute(NON_DELIVERY)`, which records the serve request and
collects its deposit atomically. An assigned verifier that cannot obtain the
bundle calls `requestServe(nonce)`. The requester then obtains a role-bound
authorization for:

```text
GET /fairbind/serve/{nonce}
```

The authorization signature covers the chain, FairBind contract, nonce, role, and case-opening block. This binding prevents reuse after the case ends.

The seller also serves its registered claims document:

```text
GET /fairbind/claims
```

The response body MUST be the exact bytes whose `keccak256` is the
registration's on-chain `claimsHash`. A verifier MUST check that equality, and
the claims byte bound, before it evaluates the predicate, and MUST NOT judge
from a claims body that fails it. The request, response, header encoding, and
status codes of both endpoints are normative in
[`x402-v2-integration.md`](x402-v2-integration.md) section 13.

The seller has one serve window to return the response bundle off chain and
record `served(nonce, bundleHash)`. This call opens a requester challenge window.
The requester may call `acceptServe` after receipt or `escalate` when the bundle
is unavailable. When neither call arrives, anyone may call `finalizeServed` after
the challenge window. The seller then has a second serve window after escalation
to publish the idempotency key, normalized canonical-request fields, response
bytes, and receipt on chain. Responses above the single-call limit use ordered
chunks.

The contract checks the seller signature, identifier derivation, request hash,
response hash, and profile request and response-size limits. Publication
establishes delivery only after every check succeeds. An invalid publication
reverts; when
no valid publication completes by the deadline, `timeoutServe` establishes
`UNSERVED`.

Delivery recovery does not require a verifier.

## 15. Predicate judgment

An assigned verifier signs and submits, directly or through a relayer:

```text
judge(signedVerdict, verdictSignature, receipt, receiptSignature, merkleProof)
```

The verdict is `PASS`, `FAIL`, or `INCONCLUSIVE`. A sampled case requires the signed receipt and anchor inclusion proof. A buyer dispute opened before anchoring may use the seller-signed receipt without an inclusion proof.

The verifier MUST confirm that the evaluated response hashes to the receipt's
`responseHash`. It then runs the profile predicate and commits the complete
versioned evidence object with `evidenceHash`. The normal evidence body remains
off chain. After a timely `requestEvidence`, the verifier MUST disclose the exact
bytes in transaction calldata within `evidenceBlocks`; the contract checks their
size and hash.

[`predicate-interface-v1.md`](predicate-interface-v1.md) defines predicate
identifiers, commitment envelopes, evidence envelopes, and the conditions for
the three verdicts.

The assignment deadline is fixed when the assignment begins. Missing a judgment
or an evidence-disclosure request by the deadline applies the late penalty and
starts bounded reassignment. A wrong-delivery case opened before its epoch is
sealed waits in `ASSIGNING`; anyone calls `assignVerifier` after the fixed epoch
randomness becomes available. Before deriving an INITIAL assignment ticket, the
contract MUST set the case randomness to the sealed epoch randomness, including
cases opened before sealing. This does not replace review-stage randomness.

## 16. Buyer disputes

The buyer may open one of the following cases before the claim deadline:

- `NON_DELIVERY`, when it did not receive the signed receipt and committed response;
- `WRONG_DELIVERY`, when the response does not satisfy the registered predicate.

The buyer posts the profile's dispute deposit. A successful claim returns the deposit. A failed claim may pay bounded verification and publication costs from the deposit.

`NON_DELIVERY` enters the redelivery procedure directly. `WRONG_DELIVERY` enters predicate judgment.

## 17. Appeal and automatic recheck

A case executes one review path. A party appeal excludes automatic recheck, and an automatic recheck excludes a later party appeal for the same first verdict.

A buyer or seller may appeal a first verdict of `PASS` or `FAIL` before the appeal deadline by posting the appeal deposit; nobody may appeal `INCONCLUSIVE`. The contract fixes a new randomness block after the appeal transaction and selects a different verifier. A second verdict equal to the first ends the case. A second verdict that differs fixes new randomness and assigns a third, previously unused verifier, whose verdict is final (ADR 0019).

When no party appeals a `PASS` or `INCONCLUSIVE` verdict, any account may seal review randomness after the appeal window. `openAutoRecheck` starts a second review with the profile probability; when not selected, the first verdict is final. Agreement between the first and second verifier ends the case. Disagreement fixes new randomness and assigns a third, previously unused verifier. The third verifier gives the final verdict.

A review stage whose randomness cannot be sealed (the seal window passed or the block hash is unavailable) reopens once (ADR 0021). Since ADR 0025 the reopened stage keeps its randomness block and the hash recorded when it reopened, so the same verifier is drawn; only the end of the reopened window, or a hash already gone at the reopening, ends the stage as a protocol `INCONCLUSIVE` (a seller-appealed review upholds the initial `FAIL`, ADR 0024).

When the final verdict is `PASS` or `FAIL`, each verifier whose verdict differs
from it loses the configured wrong-verdict penalty. An `INCONCLUSIVE` final
verdict applies no wrong-verdict penalty because it establishes no opposing
content result. On the party-review path, an applicable penalty goes to the
appellant when the final verdict differs from the first verdict, that is,
when the appellant won; otherwise, and on the automatic path, it goes to the
immutable penalty treasury. Deposit and late-penalty destinations follow
`lifecycle-v1.md`.

## 18. Funds, refunds, and seller penalties

Each settled purchase creates a deferred fund entry of its seller's bond
account with its release block. A case holds that purchase's funds until
finalization.

`FAIL`, `UNSERVED`, and `EPOCH_FAILED` make the buyer eligible for a full purchase refund. The contract MUST use that purchase's deferred funds first. It MAY use seller bond above the reserved seller penalty only for an exceptional shortfall defined by the profile.

Freeze. A final `FAIL`, an `UNSERVED` outcome, a missed anchor, or a
`FINAL(INCONCLUSIVE)` above the inconclusive threshold freezes every deferred
entry of the seller's bond account that is not yet released, across all
registrations naming that account, and suspends the seller. Under a profile
with `freezeOnInitialFail`, which no production build admits (ADR 0020), an
initial `FAIL` verdict does the same at once. Freezing transfers nothing. It
blocks `releasePurchase` and the release half of case finalization for every
frozen entry. The frozen window is the set of the bond account's unreleased
entries at the freeze block; new settlements under the account are refused
while it is frozen. Without `freezeOnInitialFail` the window is taken at the
confirmed failure and includes every purchase settled during the review. A
confirmed failure while the claim window is already open moves the freeze
block to its own block, so the window then covers every unreleased entry up to
it, including those settled after a reinstatement (ADR 0021).

- Pending triggers. Under `freezeOnInitialFail`, a case with an initial `FAIL`
  is a pending trigger of the bond account from that verdict until the case
  reaches a terminal state, whether or not the account was already frozen when
  the verdict arrived. No settlement is admitted under an account with a
  pending trigger, and `reinstateSeller` is refused for it (ADR 0015). A
  pending trigger holds every unreleased entry of the account from release,
  whatever its settlement block; during an open claim window it does not move
  the freeze block, so its overturn leaves the confirmed window and its claims
  as they were (ADR 0021). Without the flag an initial `FAIL` records no
  trigger and changes no seller state.
- Overturn. If the triggering case ends without a failure and another trigger
  is still pending, the freeze stays in place with the same freeze block and
  re-anchors to the earliest pending trigger; the seller stays suspended. If
  no trigger is left, the freeze is cleared, the suspension it caused is
  lifted, nothing is forfeited, and no failure is recorded.
- Stands. When the failure is final, the claim window opens until
  `finalBlock + claimWindowBlocks`; a later confirmed failure extends it to its
  own `finalBlock + claimWindowBlocks`. The buyer of any frozen entry without a
  refund right of its own may present its seller-signed receipt and, for an
  anchored epoch, its inclusion proof to `claimRefund(nonce, receipt,
  signature, proof)` and receive its purchase amount from the frozen pool,
  once.
- Remainder. After the claim window, `forfeitUnclaimed(bondId)` forfeits the
  unclaimed remainder of the frozen window and locks it in the contract
  (`lockedForfeit`); no function withdraws it (ADR 0022). It never returns to
  the seller, and it never takes an entry settled after the freeze block. A
  frozen entry whose own case is still open at that time is forfeited, and
  locked, when its case ends without a refund right.

Sanction. A final failure is recorded against the bond account and deducts
`sellerPenalty / failureLimit` from its balance, bounded by the balance (ADR
0018); the deduction stays locked in the contract (`lockedForfeit`, ADR 0022).
A failure window opens with the scale `n`, at least one, that is the larger of
the account's scale factor before the opening failure's deduction and its
recent scale high when that is at most `retentionBlocks` old (section 5.4); a
top-up that raises the scale factor while the window is open raises `n` to it
(ADR 0022). To raise the threshold to `n_bar` the account must at some point
have held `n_bar * sellerPenalty`, which only deductions reduce. A long-lived
record can keep a threshold above what the current balance covers; this only
delays the terminal sanction, and every failure still deducts `sellerPenalty /
failureLimit`. The window has the threshold `n * failureLimit` (ADR 0021): the
failure that brings the count within `failureWindowBlocks` to it deducts the
remainder, so that the window charges exactly `n * sellerPenalty`; the seller then becomes `SANCTIONED`, the bond
account admits no further settlement, and no later failure deducts anything.
Before that, a suspended seller returns to `ACTIVE` through `reinstateSeller`
once the bond account is not `FROZEN`, has no pending initial `FAIL` and holds
at least `sellerPenalty`, which after a deduction requires a top-up; the claim
window may still be open (ADR 0021). A reinstatement during the window reopens
the account for settlement; the purchases it then admits are outside the
frozen window and follow the normal schedule until a later confirmed failure
moves the window over them. An exiting seller is frozen, counted and deducted
like any other and cannot finish its exit while its bond account's frozen
pool is open. Normal deferred funds from other purchases MUST NOT replace the
seller penalty.

Inconclusive. The inconclusive rate of the bond account is measured on sampled
cases only: a final content verdict of a case opened by `openSample` counts as
judged, and a sampled `FINAL(INCONCLUSIVE)` also counts as inconclusive. Above
`maxInconclusivePpm`, once the window holds at least `minJudgedCount` judged
cases (ADR 0020), a sampled `FINAL(INCONCLUSIVE)` freezes and suspends as
above, but it is never counted toward `failureLimit`, never deducts from the
bond, and never makes a verifier wrong. A final content verdict of a party dispute changes
neither counter, and a disputed `FINAL(INCONCLUSIVE)` ends without seller
failure whatever the rate (ADR 0017); a disputed `FINAL(FAIL)` is a failure as
above. The case state `INCONCLUSIVE` reached through unavailable randomness, an
exhausted assignment search, or the final assignment timeout changes no counter
and no seller state.

Funds from a purchase with no open case become releasable after its claim and
retention conditions, unless the purchase was sampled and its case was never
opened, its entry is frozen or forfeited, or its bond account has a pending
initial `FAIL` (ADR 0021). A public call performs release; the seller does
not control eligibility.

## 19. Seller rate limit

Each bond account has one token bucket whose capacity and refill rate are the
profile's unit values times the account's scale factor (section 5.4).
Settlement under any registration naming the account consumes exactly one
bucket unit. The contract updates the bucket before the external token call
and reverts the update when settlement fails. `N` registrations under one bond
account admit no more settlements per window than one.

Profile admission MUST enforce the exposure condition recorded by the analysis,
read per unit of `sellerPenalty`:

```text
B >= g * (1/p + r_max * max(0, T_catch + kappa_Sigma - T_hold))
enforcementBlocks >= L
```

with `r_max = maxRatePpmPerBlock / PPM`, `T_catch = L` the judgment delay of
`profile-v1.md` section 3, `T_hold = deferBlocks`, and `kappa_Sigma` the sum
of keeper delays on the path to the confirmed failure. Profile admission
checks the `kappa_Sigma = 0` case (`expectedPenaltyFloor`, `profile-v1.md`
section 4); a bond computed for a point with late keepers uses its
`kappa_Sigma`. With `deferBlocks >= L + kappa_Sigma`, which every admissible
profile satisfies for keeper delays within its margin, the freeze of section
18 reaches everything a detected seller sold, the rate term is zero, and the
rate limit is defence in depth rather than a required component.

The specification records raw sampling probability and effective detection probability separately. Bond sizing MUST use the effective probability, which includes verifier error and review behavior.

[`profile-v1.md`](profile-v1.md) fixes profile units, admission inequalities,
retention bounds, economic calculations, and evaluation-only initial values.

## 20. Public timeout transitions

Every nonterminal state has a public transition whose result depends only on contract state and block number. Version 1 includes at least:

```text
seal(sellerId, epoch)
openSample(nonce)
assignVerifier(nonce)
timeoutAnchor(sellerId, epoch)
timeoutSeal(sellerId, epoch)
timeoutServe(nonce)
timeoutJudge(nonce)
timeoutEvidence(nonce, stage, attempt)
sealReviewRandomness(nonce)
openAutoRecheck(nonce)
claimEpochFailure(nonce)
finalizeCase(nonce)
claimRefund(nonce)
releasePurchase(nonce)
freezeSellerDeferred(triggerNonce)
releaseFrozen(bondId)
forfeitUnclaimed(bondId)
```

`reinstateSeller` is not a public progress call; it is the seller owner's choice.

No transition may leave funds locked indefinitely after the maximum number of
verifier assignments. A freeze ends by overturn or by forfeiture after the claim
window.

The exact deadline formulas, financial state, case state, and fund priority are
normative in [`lifecycle-v1.md`](lifecycle-v1.md).

## 21. State machines and contract surface

### 21.1 Purchase and case

The purchase and its optional case follow these transitions:

```text
NONE to SETTLED by settle
SETTLED to ASSIGNING by openSample or dispute(WRONG_DELIVERY)
SETTLED to REDELIVERY by dispute(NON_DELIVERY)
ASSIGNING to JUDGING by assignVerifier after epoch randomness is sealed
REDELIVERY to DELIVERED by buyer acceptServe, finalizeServed, or valid publication
JUDGING to REDELIVERY by an assigned verifier's requestServe
REDELIVERY to JUDGING by verifier acceptServe, finalizeServed, or valid publication
REDELIVERY to UNSERVED by timeout after no valid final publication
JUDGING to INITIAL_VERDICT by an initial judge
JUDGING to ASSIGNING by bounded timeout reassignment
JUDGING(SAMPLE, initial stage) to PUBLISHING(KEEPER) after the final assignment
  timeout, when the seller has not served
  (ADR 0014: no off-chain redelivery step on this path)
ASSIGNING(SAMPLE, initial stage) to WAITING_ASSIGNMENT after an exhausted
  assignment search, purchase held (ADR 0028)
WAITING_ASSIGNMENT to JUDGING by a redraw on the first checkpoint written after
  the search, from a value fixed after that checkpoint (ADR 0028)
PUBLISHING(KEEPER) to INCONCLUSIVE by valid publication
PUBLISHING(KEEPER) to UNSERVED by timeout after no valid final publication
JUDGING to INCONCLUSIVE after the final assignment timeout otherwise
INITIAL_VERDICT(PASS or FAIL) to PARTY_REVIEW by appeal
INITIAL_VERDICT(PASS or INCONCLUSIVE) to AUTO_REVIEW by selected automatic recheck
INITIAL_VERDICT to FINAL when no review is selected
PARTY_REVIEW or AUTO_REVIEW to FINAL when the second verdict agrees
PARTY_REVIEW or AUTO_REVIEW to TIEBREAK when the second verdict disagrees
TIEBREAK to FINAL by the third verdict
FINAL(FAIL) or UNSERVED to REFUNDED by claimRefund
FINAL(PASS or INCONCLUSIVE) or DELIVERED to RELEASED after fund conditions
SETTLED to RELEASED after fund conditions when no case opens and it is not sampled
DEFERRED to DEFERRED(frozen) by a freeze of its bond account
DEFERRED(frozen) to DEFERRED by releaseFrozen or an overturn of the last pending trigger
DEFERRED(frozen) to FROZEN_CLAIMABLE when the bond account's claim window opens
FROZEN_CLAIMABLE to REFUNDED by claimRefund with a receipt
FROZEN_CLAIMABLE to FORFEITED by forfeitUnclaimed
```

A purchase ends released, refunded, or forfeited, never two of the three.

Opening a case holds the individual purchase funds. `UNSERVED` is a contract-checked result and has no seller appeal. Party appeal applies only to `PASS` and `FAIL` content verdicts.

### 21.2 Epoch

```text
OPEN to CLOSED at the fixed epoch end
CLOSED to ANCHORED by anchor
CLOSED to EPOCH_FAILED after the anchor deadline
ANCHORED to SEALED by seal, also after the seal deadline (ADR 0029)
ANCHORED to EPOCH_FAILED by timeoutSeal after the anchor deadline, only when
  the epoch's checkpoint holds fewer than minVerifiers verifiers (ADR 0029)
```

An epoch that fails because the seller never anchored is a seller failure: it
freezes the bond account, suspends the seller, opens the claim window at once,
and counts once toward `failureLimit`. An anchored epoch whose sampling value
has not arrived stays `ANCHORED` and releases nothing; it fails only through
the checkpoint shortage of ADR 0029, which refunds its purchases but changes no
seller state and no counter.

### 21.3 Seller

```text
NONE to ACTIVE by registerSeller naming an active bond account
ACTIVE to SUSPENDED on a final failure, a missed anchor, a FINAL(INCONCLUSIVE)
  above the threshold, or (freezeOnInitialFail only) an initial FAIL; a final
  failure deducts one share of the penalty, the others nothing
SUSPENDED to ACTIVE when the last pending trigger of the freeze that suspended
  it is overturned (freezeOnInitialFail only; no other conditions)
SUSPENDED to ACTIVE by reinstateSeller when the bond account is not FROZEN
  (its claim window may be open, ADR 0021), no initial FAIL on it is pending,
  and it holds at least sellerPenalty
ACTIVE or SUSPENDED to SANCTIONED when the bond account's final failures in
  failureWindowBlocks reach failureWindowScale * failureLimit; the remainder
  of the window's failureWindowScale * sellerPenalty is charged, once
ACTIVE, SUSPENDED, or SANCTIONED to EXITING by requestSellerExit
EXITING to EXITED after retentionBlocks, once the bond account is neither
  FROZEN nor CLAIM_OPEN and has no pending initial FAIL
```

`SUSPENDED`, `SANCTIONED`, `EXITING`, and `EXITED` sellers cannot accept new settlements.

The bond account has its own machine:

```text
NONE to ACTIVE by registerBond with balance >= sellerPenalty
ACTIVE to ACTIVE by topUpBond (owner only) or a slash (scale factor recomputed)
ACTIVE to EXITING by requestBondExit
EXITING to EXITED when every registration is EXITED, no entry is deferred,
  no freeze is pending, and retentionBlocks have passed
```

and a freeze machine:

```text
NONE or CLAIM_CLOSED to FROZEN by a freeze trigger; a confirmed failure of an
  unfrozen account passes through FROZEN to CLAIM_OPEN in one transaction
FROZEN to FROZEN, re-anchored to the earliest pending trigger, when the
  trigger case ends without failure and another initial FAIL is pending
FROZEN to NONE or CLAIM_CLOSED when the trigger case ends without failure and
  no initial FAIL is pending
FROZEN to CLAIM_OPEN when the triggering failure is final
CLAIM_OPEN to CLAIM_OPEN, reopened for settlement, by reinstateSeller
CLAIM_OPEN to CLAIM_OPEN when another failure is final, moving freezeBlock to
  finalBlock, closing the account to settlement until the next
  reinstatement, and extending claimUntilBlock to finalBlock +
  claimWindowBlocks if that is later (ADR 0021)
CLAIM_OPEN to CLAIM_CLOSED by forfeitUnclaimed after claimUntilBlock
```

### 21.4 Verifier

```text
NONE to ACTIVE by registration with sufficient bond
ACTIVE to ACTIVE after a penalty with one added strike
ACTIVE to REMOVED when strikes reach the profile threshold
ACTIVE to EXITING by requestVerifierExit
EXITING to EXITED after every dependent assignment and appeal window ends
```

### 21.5 Required entry points

The exact ABI, enum order, access rules, views, events, and errors are normative
in [`contract-interface-v1.md`](contract-interface-v1.md). The contract interface
includes at least:

```text
createDeadlineConfig
createServiceProfile
setServiceProfileActive
pauseNewSettlements
nominateGovernance
acceptGovernance
nominateGuardian
acceptGuardian
registerBond
topUpBond
requestBondExit
finalizeBondExit
registerSeller
requestSellerExit
finalizeSellerExit
reinstateSeller
registerVerifier
topUpVerifierBond
setVerifierClasses
requestVerifierExit
finalizeVerifierExit
checkpointVerifierTree
settle
anchor
timeoutAnchor
seal
timeoutSeal
openSample
assignVerifier
requestServe
served
acceptServe
escalate
finalizeServed
publish
beginPublication
publishChunk
finalizePublication
judge
requestEvidence
discloseEvidence
timeoutEvidence
dispute
appeal
sealReviewRandomness
openAutoRecheck
timeoutServe
timeoutJudge
proveOmission
proveMisanchoredReceipt
proveEquivocation
claimEpochFailure
finalizeCase
claimRefund
releasePurchase
freezeSellerDeferred
releaseFrozen
claimRefund(nonce, receipt, receiptSignature, proof)
forfeitUnclaimed
```

Governance functions that create profiles or deadline configurations MUST NOT
modify existing purchase rules. The version 1 contract is not upgradeable.
[`governance-v1.md`](governance-v1.md) defines the delayed admission controls and
the emergency pause boundary.

### 21.6 Events and custom errors

Every persistent administrative, registration, settlement, epoch, serve,
publication, case, evidence, review, fund, and penalty transition emits the
event fixed by `contract-interface-v1.md`. The same document fixes public error
selectors for authorization, configuration, availability, identifiers, payment
authorization, deadlines, sizes, proofs, assignments, transitions, and token
transfers. Implementations MUST NOT substitute string reverts for those listed
conditions.

## 22. Required invariants

An implementation MUST test the following invariants.

1. At most one successful purchase exists for one `keyId`.
2. At most one successful purchase exists for one authorization nonce.
3. A purchase never changes seller, profile, claims hash, buyer, request hash, amount, or epoch.
4. A sampled purchase is determined from the ledger nonce and fixed epoch randomness.
5. A seller cannot reduce the sample population by omitting a receipt leaf.
6. A verifier is not assigned twice to one case.
7. A case executes no more than one review path.
8. Verifier open liability never exceeds the profile limit relative to effective bond.
9. A purchase is released, refunded, or forfeited, never two of the three.
10. A refund uses its purchase's deferred funds before unreserved seller bond.
11. The seller penalty of a bond account is charged only by confirmed
    failures: `sellerPenalty / failureLimit` per counted failure and the
    remainder at the window's threshold `n * failureLimit`, each bounded by the
    balance, so one failure window of scale `n` (at least one) charges at most
    `n * sellerPenalty` (ADR 0018, ADR 0021). `n` is never below the scale
    factor before the opening failure's deduction, the recent scale high within
    `retentionBlocks`, or a scale reached by a top-up while the window is open
    (ADR 0022).
12. Every nonterminal state reaches a terminal state through bounded public
    calls; a freeze ends by overturn or by forfeiture after the claim window.
13. Failed token transfers leave identifiers, counters, the bond account's
    bucket, and balances unchanged.
14. Deadline configurations and service profiles never change after creation.
15. Every successful settlement uses the deployment token and a value no larger than its profile limit.
16. A receipt, serve authorization, or verdict from another chain, contract, assignment, or case opening is invalid.
17. Dispute deposits, appeal deposits, and penalties can reach only the fixed
    destinations in `lifecycle-v1.md`.
18. No frozen entry is released, refunded, or forfeited before the triggering
    case's appeal window closes.
19. Refunds paid from a frozen pool never exceed the pool, and each purchase is
    paid at most once.
20. A frozen-pool claim is accepted only with a valid seller-signed receipt for
    the purchase's seller, profile, epoch, chain, and contract, only for an
    entry of the frozen bond account, and only inside the claim window.
21. An overturned failure releases exactly the entries it froze and forfeits
    nothing.
22. Forfeited value and per-failure deductions stay in the contract: each
    adds to `lockedForfeit`, which no function decreases, and none of it
    reaches the seller, the verifier reward pool or the penalty treasury (ADR
    0022). The contract's token balance is at least the sum of bond balances,
    deferred balances, verifier bonds and `lockedForfeit`.
23. Settlements admitted against one bond account in any `enforcementBlocks`
    window do not exceed its configured maximum, however many registrations
    name it.
24. A seller registration names exactly one bond account for its lifetime;
    adding or removing a registration never raises a bucket level; the scale
    factor never rises without a token transfer into the account.
25. A bond account is sanctioned at most once, only at the threshold
    `failureWindowScale * failureLimit` of its current failure window, and
    nothing is deducted from it after the sanction; an overturned failure
    leaves no recorded failure, no recorded inconclusive and no deduction.
26. A protocol `INCONCLUSIVE` (unavailable review randomness, exhausted
    search, final assignment timeout) never changes seller state or any
    counter. A missing epoch value changes nothing at all: the epoch stays
    `ANCHORED` (ADR 0029).
27. A sampled purchase is never released unless its case was opened and ended;
    in particular never while its case is in `WAITING_ASSIGNMENT` (ADR 0028).
    No entry is released before `deferBlocks` blocks since its settlement in
    which no case of its bond account waited (ADR 0029).
28. Under `freezeOnInitialFail`, while a bond account has a pending initial
    `FAIL`, no settlement is admitted under it, its freeze is not released,
    and no seller of it returns to `ACTIVE`; the pending count equals the
    number of its cases that have had an initial `FAIL` and are not terminal.
    Without the flag an initial `FAIL` changes no bond or seller state and
    the pending count is always zero.
29. A payment authorization accepted by `settle` moves the buyer's funds only
    inside a `settle` that records its purchase; a direct token call by any
    other party cannot spend it (ADR 0016).
30. Only a final content verdict of a sampled case changes a bond account's
    judged or inconclusive count; a party dispute never does (ADR 0017).
31. A second verdict that differs from the initial verdict, on the party or
    the automatic path, never ends a case; the third verdict does (ADR 0019).
32. An unappealed initial `INCONCLUSIVE` reaches `FINAL` only through the
    recheck gate, with the same selection rule as an initial `PASS`.
33. A sampled `FINAL(INCONCLUSIVE)` freezes only when the window's judged
    count, including it, is at least `minJudgedCount` (ADR 0020).
34. A confirmed failure while the claim window is open leaves every
    unreleased entry settled up to its block in the frozen window: no
    principal settled before a confirmed failure of a bond account is released
    to its seller, including purchases settled after a reinstatement during
    the window (ADR 0021).
35. The frozen pool, the frozen-pool claims and the forfeiture cover only
    entries settled no later than the freeze block; an entry settled after it
    is neither claimable nor forfeited until a later confirmed failure moves
    the freeze block over it, and no entry is claimed twice.
36. A review stage reopens its seal at most once; a case ends as a protocol
    `INCONCLUSIVE` for missing review randomness only after its stage has
    reopened (ADR 0021).
37. An exiting seller or bond account is frozen and deducted like an active
    one, and a seller registration does not reach `EXITED` while its bond
    account is `FROZEN` or `CLAIM_OPEN` or has a pending initial `FAIL`.
38. No entry of an anchored epoch is released or refunded before the epoch's
    sampling value is on chain, except through the checkpoint shortage of
    `timeoutSeal`, which counts nothing against the seller (ADR 0029).
39. The release clock of a bond account stops exactly in the blocks in which
    at least one of its sampled cases is in `WAITING_ASSIGNMENT`; the recent
    value cap, the recent sanction limit, the recent scale high and the bond
    exit lock count the same unpaused blocks (ADR 0029).

## 23. Security properties

The implementation and evaluation use four named properties.

- P1, payment at most once: retries and restarts cannot create a second payment for one purchase key.
- P2, delivery or refund: an honest buyer obtains the seller-signed receipt and committed response or a full refund within bounded blocks.
- P3, honest seller protection: the probability that a compliant seller loses funds after an incorrect final failure verdict has a stated upper bound.
- P4, verifier accountability: missed deadlines have deterministic penalties, while incorrect content verdicts have the appeal and recheck guarantees stated by the verifier model.

The proof obligations and implementation locations are tracked in [`traceability.md`](traceability.md).

## 24. Non-goals

Version 1 does not provide:

- atomic fair exchange;
- per-transaction correctness verification;
- confidentiality from an assigned verifier;
- a universal predicate for arbitrary services;
- protection after buyer-key compromise;
- consensus-layer reorganization or censorship resistance beyond the selected chain profile;
- a zero-knowledge proof that the seller's full receipt tree equals the full settlement set;
- learning verifiers or sellers across protocol instances.

## 25. Implementation sequence

Implementation follows five milestones:

1. settlement, identifier checks, token bucket, and deferred funds;
2. epoch anchoring, fixed randomness, ledger-nonce sampling, and verifier snapshots;
3. direct redelivery, disputes, publication, chunking, and refunds;
4. judgment, appeal, automatic recheck, reassignment, and verifier penalties;
5. separate buyer, seller, facilitator, verifier, and keeper processes with fault injection.

Milestone acceptance criteria are defined in [`../implementation-plan.md`](../implementation-plan.md).

## Fixed deployment packaging

The version 1 reference deployment MAY use constructor-fixed delegate modules.
All purchase-facing entry points MUST retain one settlement address. Modules MUST
share the exact storage layout, token, treasury, verifier reward pool, and
reentrancy lock. A deployment
MUST reject invalid module configuration and verify module code against its build
artifacts. Module mappings MUST NOT change after construction. Packaging MUST NOT
change identifiers, receipt domains, fund priority, selection or timeout semantics.

## Independent recovery and effective liability (ADR 0008)

The user-approved liability bound is the profile fraction of
`min(currentVerifierBond, verifierBondCap)`. The detailed profile and assignment
code MUST use this same bound. Exhaustion MUST remain an explicit INCONCLUSIVE
outcome rather than an assumed successful assignment, except in the initial
stage of a sampled case, where it is an explicit wait for a redraw with the
purchase held (ADR 0028).

A valid buyer NON_DELIVERY claim with an existing case MUST have an independent
recovery record and deposit. It MUST NOT replace judgment identity or deadlines.
Concurrent messages and publication MUST use their explicit buyer-recovery
selectors and the same receipt, request, response, size, and deadline checks.
While recovery is open, seller release MUST fail even if judgment becomes
INCONCLUSIVE or otherwise terminal. Successful recovery MUST preserve an active
judgment hold. Seller failure MUST close both routes, cancel outstanding assignment
liability exactly once, and preserve both deposit balances for the single refund.
New claims after refund eligibility, refund, or seller release MUST fail.
The independent record may be opened once per purchase within the original claim
window; it does not extend that window. See ADR 0008 for the selector mapping and
allocation rules. M4 transitions MUST preserve these financial guards.

## ADR 0009 conformance

Evidence disclosure renews the initial appeal window and its fixed automatic randomness block. Assignment reserves its maximum verifier penalty before testing the effective-bond liability fraction. The normative horizon, conservative multi-profile envelope, terminal fund routing and bounded progress rules are in profile-v1.md and lifecycle-v1.md. These changes implement the user's explicit decisions; previous formulas without reservation or renewed deadlines are superseded.

## ADR 0024: value-proportional sampling and four case rules

These rules amend sections 9, 12, 16, 17, 18 and 20.

1. **Sampling under a profile with terms (section 12).** A purchase of a bond
   account with value cap `vmax` is sampled with probability
   `s_ppm / PPM`, `s_ppm = min(PPM, ceil(v * PPM / vmax))`, fixed at
   settlement with the cap in force. The draw keeps the ledger-nonce sample
   value of this section and compares it with `ceil(s_ppm * 2^256 / PPM)`; at
   `s_ppm = PPM` the purchase is sampled without a comparison. Section 9
   refuses `v > vmax` before the bucket is read. Profiles without terms keep
   the constant `samplePpm` and the threshold of this section.
2. **Delivered disputes (section 16).** A purchase whose `NON_DELIVERY`
   dispute ended as `DELIVERED` and that is sampled opens its sample case like
   an undisputed purchase, also while a buyer recovery is open. The case
   record is rewritten as a sample case; the dispute's requester, role,
   bundle hash and serve deadlines are cleared. Such a purchase is not
   released before its sample case has run.
3. **Stalled seller appeal (section 17).** A review the seller appealed
   against an initial `FAIL`, including the tiebreak it leads to, that ends
   through a progress failure (two lapsed seals, the last assignment timing
   out or voided, or no eligible verifier) ends `FINAL(FAIL)`: the failure is
   confirmed and counted, no review verdict pays a wrong-verdict penalty, the
   appeal deposit goes to the buyer, and the inconclusive counters do not
   move. Buyer appeals and automatic rechecks still end as a protocol
   `INCONCLUSIVE`.
4. **Sample receipt (sections 15 and 20).** The receipt of a sample case and
   its inclusion proof in the anchored epoch must be on chain within
   `serveBlocks` of the case opening (`submitSampleReceipt`, or a verdict
   that carries them in time). After the deadline the public call
   `timeoutSampleReceipt` ends the case `UNSERVED`, a confirmed failure; an
   omitted receipt drawn for sampling ends the same way.
5. **Deductions (section 18).** Under a profile with terms each confirmed
   failure deducts `b(V*) = ceil(40 * V* * PPM / (27 * p0))`, where `V*` is the
   highest cap the account held within `retentionBlocks`, and the unit bond is
   `k_S * b(V*)`.

The randomness rule of the design 2 analysis (no payment of an anchored epoch
is released or refunded before its randomness is on chain) was not
implemented by this record; ADR 0029 implements it.

## ADR 0025: checkpoint-time eligibility, a reseal that keeps its block, committed terms

1. **Verifier eligibility (section 13, decision 126).** A checkpoint records
   each verifier's liability room at its block (`sortition-v1.md` section 2).
   Every assignment of an epoch sealed on that checkpoint skips a candidate
   only when it already took part in the case or when the case liability
   exceeds its room in the checkpoint. The verifier's current status, bond and
   open liability do not enter: cases opened after the checkpoint block, in
   any order, cannot make a candidate ineligible, and the first assignment of
   a case follows the checkpoint table. A candidate that is full now is still
   assigned; if it does not answer, the judgment timeout replaces it within
   `maxAssignments`. A penalty takes at most the verifier's remaining bond.
2. **Review reseal (section 17).** A reopened review seal keeps its
   randomness block and the hash recorded when it reopened; the reopened
   window ends `sealBlocks + 1` blocks after the reopening.
3. **Profile terms (section 5).** Terms are fixed only on a profile that has
   never been active, against `termsHash`, the commitment the profile
   document carries inside the parameters that `parameterHash` commits. Under
   terms both counting windows equal `retentionBlocks`.
4. **Late sample verdict (section 15).** A verdict on a sample case after its
   receipt deadline, with the receipt not on chain, ends the case `UNSERVED`
   in the same call.
5. **Invariant 8 as amended.** Each assignment fits its verifier's room in the
   epoch's checkpoint; locked liability may exceed the verifier's current
   effective-bond limit.

Liability locked before a checkpoint block is part of that checkpoint's room,
so a seller who keeps honest verifiers full across checkpoint blocks still
lowers the honest share of the first assignment (ADR 0025, limit 1).

## ADR 0029: an anchored epoch waits for its value, and a waiting case stops the release clock

1. **Epoch value (section 21.2, design 2 rule D2-16).** `seal` is valid after
   `randomBlock` while `blockhash(randomBlock)` is served, also after
   `sealDeadline`; without the value it reverts and the epoch stays
   `ANCHORED`. `timeoutSeal` ends an anchored epoch as `EPOCH_FAILED` (reason
   `VERIFIER_SET_UNAVAILABLE`) only after the anchor deadline and only when the
   epoch's checkpoint, the latest written at or before that deadline, is
   missing or holds fewer than `minVerifiers` verifiers; its purchases are
   refunded through `claimEpochFailure` and nothing is counted against the
   seller. `sealDeadline` keeps its role in the release and keeper rules.
2. **Release clock (section 18, design 2 rule D2-21).** A block in which at
   least one sampled case of a bond account is in `WAITING_ASSIGNMENT` is
   paused for that account. An entry settled in block `s` is released only
   when `block.number - pausedSince(s) >= releaseBlock`, where
   `pausedSince(s)` is the number of paused blocks from `s` up to the current
   block. `V*` (the recent value cap), the recent sanction limit, the recent
   scale high of ADR 0022 and the bond exit lock end after `retentionBlocks`
   unpaused blocks.
