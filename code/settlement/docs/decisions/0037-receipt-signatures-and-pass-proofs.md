# ADR 0037: Receipt signatures, PASS proofs and measured costs

Status: Accepted 2026-10-19. Adds a proof profile and receipt signatures,
and amends ADR 0034 (seller proofs) for proof profiles and the deposit of a
delivered non-delivery dispute for profiles that measure costs. A profile
whose exchange terms were never set behaves as before; `settle`,
`openSample`, `dispute`, `releasePurchase`, a confirmed failure and the
seller calls of the delivery ladder read one more storage slot.

## Context

A vote profile judges a sampled response through bonded verifiers. Where
the predicate is a check of a numeric response against a signed price feed,
the contract can decide the case itself from the signed update, so no
verifier, appeal or review is needed. That only holds when the response the
contract judges is the one the buyer received. A receipt signed by the
seller does not show that: the seller can anchor a receipt whose response
differs from what the buyer got. The buyer's own signature over the
encrypted response, given before the buyer can read it, binds the two and
keeps the exchange fair: the buyer cannot read the response without
signing, and the seller cannot be paid for a response it did not commit to.

The seller's share of a dispute deposit also needs a bound tied to what the
seller spent. A constant share lets a seller provoke disputes and keep the
difference between the constant and its real cost.

## Decision

1. **Terms.** `setExchangeTerms(profileId, Input)` fixes, once and before
   the profile is active, the judgment (VOTE or PROOF; a vote profile takes
   receipt signatures unless `receiptSigOff` is set, which leaves only the
   measured costs, and a proof profile always takes them), the cost
   constants (price cap pi in token units per ETH, gFixTx, gFixCall, bEnv),
   the receipt-signature constants (T_bundle, T_key, g_1271, L_r, L_sig,
   c_key, the response tag) and, for PROOF, T_p, delta_ref, max_skew, the
   verifier contract, the feed id and the tolerance. `termsHash` commits to
   every input, including the admission inputs. The admission checks are:
   (1) c_key = keyGas * gasPriceCap + keyBytes * l1PriceCap <=
   maxPublicationCost, the largest PASS proof fits 120,000 bytes of call
   data and keyGas the profile's block share; (2) T_bundle + T_key + slack <
   responseBlocks + claimBlocks; (3) T_bundle + posting slack + d_conf <=
   anchorBlocks; (4) c_pub = pubGas * gasPriceCap + pubBytes * l1PriceCap
   <= maxPublicationCost (c_pub = c_key under receipt signatures); and
   delta_ref >= delta_fresh + max_skew + the settlement delay. The posting
   slack of (3) covers the inclusion of two transactions, the posting and
   the separate match (item 4). keyBytes and pubBytes are the byte counts
   the L1 fee bound of item 6 charges. Receipt signatures exclude the
   side-gain grade and PROOF excludes batch terms in either order:
   `setExchangeTerms` refuses them after batch terms, and `setBatchTerms`
   refuses batch terms under a PROOF profile and the side-gain grade under
   a VOTE_SIG profile set before.
2. **Bundles.** For each purchase the seller sends the buyer ct =
   Enc_ek(psi || pad(r)), h_ek = keccak256(ek), h_r = keccak256(tag || psi ||
   pad(r)) and the receipt leaf. Enc is the keccak key stream bound to the
   nonce (block i is keccak256(ek, nonce, i)); psi is 32 bytes; pad appends
   0x80 and zero bytes to L_r. The buyer signs, before it can decrypt,
   EIP-712 `FairBindReceiptSignature(seller, nonce, ctHash, ekHash,
   responseHash, leaf)` under a domain whose salt is the profile's
   parameter hash; `seller` is the registered signing key of the
   purchase's seller.
3. **Posting.** Only the seller posts: `postReceipt` carries its signature
   `FairBindReceiptPost` over the bundle, `postReceipts` one signature
   `FairBindReceiptPostList(listHash, count)` over a list of one seller's
   purchases. Each signature is checked by ecrecover first and then, for a
   key with code, by ERC-1271 with gas cap g_1271 (and L_sig for the
   seller); a call with less gas left than g_1271 * 64 / 63 plus a margin
   reverts. A nonce whose purchase does not exist, whose slot is filled,
   whose anchor deadline passed or whose buyer signature fails is skipped;
   a purchase of another seller reverts the call. One slot per nonce holds
   h_n = keccak256(H(ct), h_ek, h_r, leaf) with its low bit cleared.
4. **Binding.** `matchAnchor` checks, by the epoch's anchor deadline A_e,
   the preimage of h_n with the anchored leaf and its merkle-v1 path in the
   unit that holds the nonce (the anchor root for one unit), and sets the
   low bit. A posting, in its own transaction or carried by a PASS proof,
   only checks and stores h_n; the match is a separate call, by anyone, for
   several nonces. Only a bound purchase is a sale: after A_e
   `refundUnbound` refunds any other, once and without a failure; such a
   purchase opens no sample case and is never released. No refund, of an
   unbound purchase or by a dispute, returns its unit to the seller's
   bucket, so a window of length Lambda still admits at most S settlements.
5. **PROOF judgment.** `openProofSample` opens the sample case of a bound,
   sampled purchase (`PROOF_WAIT`, due open + T_p). `openProofDispute` is the
   buyer's dispute with d0 (key dispute or wrong delivery), due open + T_p.
   `prove(nonce, flags, PassProof)` carries ek, ct, issuedAt and the one
   update message; the contract decrypts, recomputes h_r and the receipt
   leaf (the purchase's receipt with that response hash and the profile's
   predicate commitment at the buyer's validAfter), compares h_n, unpads,
   asks the verifier for the first update at or after validAfter
   (`parsePriceFeedUpdatesUnique`), requires it within max_skew and the
   response within the tolerance. Without a PASS proof by the deadline
   (`timeoutProof`), or with an absent input (`proveAbsence`) or a FAIL
   proof (flag 2), a sample case is a confirmed failure and a dispute the
   refund alone; the purchase's sample case stays after a dispute refund. A
   purchase with a PASS proof passes later cases at once. The call data must
   be the canonical encoding of the arguments.
6. **Measured cost.** A key dispute that passes pays the seller min(c_key,
   c) and the buyer the rest, c = pi * ((g + gFix) * basefee +
   UB(|xhat| + bEnv)) / 1e18 rounded down, UB the predeploy
   `GasPriceOracle.getL1FeeUpperBound`, g the gas since the call's entry
   less a seller ERC-1271 check, |xhat| the length of the canonical
   encoding (less the seller's 1271 signature). UB takes the unsigned size
   only, adds the 68 signature bytes itself and bounds the FastLZ size, so
   the L1 share does not depend on the content and the seller cannot pick
   inputs that compress well; bEnv bounds the unsigned envelope fields
   outside the call data (type, chain id, nonce, gas fields, recipient,
   value, access list), the signature excluded. A later measured call of
   the same transaction takes UB(|xhat| + bEnv) - UB(bEnv). The fixed share
   (gFixTx and UB(bEnv) with its size floor) counts once per transaction
   through a transient mark that postings and anchors also set. Priority
   fees never count. A profile with exchange terms activates only where UB
   answers (`setServiceProfileActive` reverts otherwise, as before Fjord or
   without the predeploy), so an L1 share of zero where the oracle has no
   code is left to test chains.
7. **Delivered share.** Under measured costs the seller calls of the
   non-delivery ladder (`served`, `publish`, `beginPublication`,
   `publishChunk`, `finalizePublication` and their buyer-recovery forms, and
   `discloseKey` of a VOTE_SIG profile) add their measured cost to the
   dispute; each stage once. When the dispute ends as delivered the seller
   takes min(maxPublicationCost, the sum); the rest is locked under a vote
   profile without receipt signatures and returned under VOTE_SIG. A lapsed
   non-delivery dispute of a VOTE_SIG profile is the refund alone; the
   purchase's sample case still opens and a failure of it counts without a
   second refund.
8. **The seller's proof.** Under PROOF, `selfProve` uses the purchase's PASS
   proof on a frozen entry of the open claim window (no proof bond); it is
   confirmed when the order condition of ADR 0034 holds and reserved
   otherwise. `releaseSelfProven` pays it once the release rules hold and
   more than retentionBlocks unpaused blocks have passed since settlement
   (T_rcpt). A confirmed failure of the purchase voids it.
9. **Deployment.** `requireExchangeTerms`, by governance, once, makes
   every later activation need exchange terms. The evaluation setting
   deployment calls it before activating any profile, so every vote profile
   it runs has exchange terms (receipt signatures by default); a vote
   profile activated without them runs the base rules and is
   outside the exchange-terms guarantees. The existing tests leave it off.
10. **Modules.** Extension modules 15 (`FairBindExchange`), 16
   (`FairBindPassProof`) and 17 (`FairBindSelfProof`); hook 25 (a failure
   voids the seller's proof) and 26 (deposits of a delivered dispute).
   `ExchangeStore` sits at `keccak256("fairbind.exchange.store.v1")`.
11. **Binding proof start.** `proveMisanchoredReceipt` keeps no start
   at the SAMPLE value (the start of rule D2-19 (h) is withdrawn): it is taken from the
   anchor on, also before the epoch's SAMPLE value, through the purchase's
   `retainUntil`. The SAMPLE request carries the profile and A only, so an
   epoch with a missed anchor, or none, gets its value the same way (rule
   8.2 row 25).
12. **Window checks.** The terms carry the binding proof window F_max
   (`bindWindow`) and the slack of a binding proof (`bindSlack`).
   `setExchangeTerms` requires 0 < F_max <= retentionBlocks (check 6).
   Activation requires, under the source in force, 2 * epochBlocks +
   anchorBlocks + (D_S + T_V, or 1 + beaconDelayBlocks on the block hash
   path) + bindSlack <= F_max (check 7), and L_F + marginBlocks - 1 <= F_max
   < retentionBlocks with L_F the longest sample-case path (the path
   enumeration): O_s + T_p + 1 for a proof profile, the batched path for a
   batched vote profile, and the judgment delay of the profile check
   otherwise. A batched profile also needs retentionBlocks >= L_F +
   marginBlocks at activation, with or without exchange terms, because the
   profile check counts the judgment delay of the earlier rules, and
   (6 * maxAssignments + 4) * keeperSlack <= marginBlocks - 1 (the per-call
   keeper delay of the keeper transitions of its longest path) and
   keeperSlack <= sealBlocks - 2 while sealBlocks <= 255.

## Consequences

- A proof profile needs no verifier assignment; checkpoints still gate
  settlement and sealing.
- Each sale adds a posting (about one signature check and one new slot) and
  a match (one merkle path). Lists amortize the posting signature.
- The verifier contract is trusted to check the signed updates.
- A binding proof sent before the sampling value is taken; the client
  condition of rule A7 (b) is what keeps a buyer's decision after the value,
  and check 7 keeps a window after the value open.
- The profile check still asks a proof profile for the vote-profile judgment
  delay at creation (terms come later), which holds a proof seller's entries
  longer than L_F,P needs.
- WINDOWED inputs, counter proofs, several sources and the anchor carrying
  its matches are not implemented.
- The L1 share is an upper bound: the seller's share stays below c_key, and
  an honest seller pays only the rare input beyond the FastLZ bound and the
  floor of a later call. A later measured call of a transaction calls the
  oracle twice.
