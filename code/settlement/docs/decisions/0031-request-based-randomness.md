# ADR 0031: Request-based randomness behind IRandomness

Status: Accepted 2026-10-19. Amends ADR 0028 (the redraw value) and the
randomness source of the sampling module in `contract-interface-v1.md` ("ADR
0031 request-based randomness") and `traceability.md`. Changes the behavior
of `setRandomness`, `seal` and `assignVerifier` on a waiting case only when
the source in force is request based; adds four keeper calls, three views,
two events, a source contract and its interfaces; appends storage in the
sampling store only.

This record implements design 2 rule D2-23 (a) to (d) for the SAMPLE value
and the redraw's AUX value, and rule D2-20 (b). The ASSIGN value of a
batch, the AUX values of review assignment and of audits, and their exits
belong to the batch and slot rules and are not part of this record.

## Decision

1. **Source.** `FairBindVrf` implements `IVrfRandomness`, an extension of
   `IRandomness`. A deployment fixes the consumer (the FairBind router), a
   proof verifier (`IVrfVerifier`), the provider's public key and the bounds
   D_V (`responseBlocks`) and T_V (`deadlineSlackBlocks`). `delayBlocks()` is
   D_S = D_V + 1. `setRandomness` marks a source as request based when it
   answers `responseBlocks()`.
2. **Requests.** A request is identified by (kind, input), kind SAMPLE = 1,
   ASSIGN = 2, AUX = 3. Its VRF input is
   `abi.encode("FairBind/vrf/v1", chain id, consumer, kind, input)`, stored at
   the first request; a block hash never enters it. Only the consumer may
   request; a repeated request keeps the stored input. A response is stored
   once, only if the verifier accepts its proof for the stored input and key,
   and only by the request's deadline when it has one.
3. **SAMPLE.** `requestSampleValue(profileId, epoch)` asks for the value of
   input (profileId, A), A the anchor deadline of the epoch. It reverts
   `RequestTooEarly` through A and `DeadlinePassed` after M = A + D_S + T_V;
   M is the request's deadline. `seal` of an epoch anchored under the source
   takes this value when it was stored by M, and reverts
   `InvalidRandomnessWindow` otherwise: a value stored after M is refused by
   the source and, if a source stored one, by the contract. The epoch then
   stays `ANCHORED` and releases nothing (ADR 0029).
4. **Redraw.** A waiting case (ADR 0028) is redrawn with the AUX value of a
   registered use. `registerRedraw(nonce)` registers it once the checkpoint
   the redraw searches (the first written after the case's last search) is
   on chain; the block of the call is t. `requestRedrawValue(nonce)` asks,
   from block t + 1, for input (redraw use, nonce, initial stage, redraw
   ordinal, t); a repeated call asks again. `assignVerifier` on the waiting
   case reverts `NotRegistered` without a registered use and
   `DeadlineNotReached` until the value is stored, then searches that
   checkpoint with the value as before. On the block-hash path nothing
   changes.
5. **Redraw exit.** When the value is not stored by the first request block
   + D_V + T_V, `timeoutRedrawValue(nonce)` ends the case from the next
   block: no verdict (`INCONCLUSIVE`), the case leaves the wait, the
   purchase becomes an unencumbered entry, and the account is suspended and
   frozen from the purchase's settlement block with its claim window opened
   as for a confirmed failure (ADR 0030), but the failure is not counted and
   nothing is deducted. A value stored later is never used.
6. **Packaging.** `seal`, `timeoutSeal` and `timeoutAnchor` move from the
   sampling module to the publication module and `setRandomness` to the
   registry module, so that the sampling module stays below the size limit.
   Their selectors and behavior on the router do not change.
7. **Keeper calls.** `requestSampleValue`, `registerRedraw`,
   `requestRedrawValue` and `timeoutRedrawValue` take no caller restriction.

## Consequences

- The sampling and redraw values no longer depend on block hashes when the
  source is request based; their unpredictability rests on the provider's key
  and on the provider answering only registered requests.
- An unanswered SAMPLE request leaves its epoch held for good, as an
  unavailable value did under ADR 0029.
- The release clock does not yet pause for a SAMPLE or AUX value later than
  its normal bound; requests of ASSIGN values and the other AUX uses, the
  profile admission checks for D_V and T_V, and the provider's verifier are
  open.

## Tests

`VrfRandomness.t.sol`: the request rule and stored input, no block hash in
the input (with a mutation adapter that adds one), consumer binding, proof
and second-response refusal, a timely late value that seals, a value after
the deadline refused by the source and by the contract (with a mutation
sampling module that takes it), an unanswered request, the redraw with its
registered AUX value, and the redraw exit.
