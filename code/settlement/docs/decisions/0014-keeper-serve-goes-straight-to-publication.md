# ADR 0014: A keeper serve request goes straight to publication

Status: Accepted 2026-09-26. Revises the keeper serve fallback added with
ADR 0013 in `lifecycle-v1.md` section 4 and `fairbind-v1.md` section 21.1.

## Problem

A sampled case whose initial stage cannot complete (every assigned verifier
timed out, or the assignment search is exhausted) and in which the seller has
not served falls back to a serve request with requester role `KEEPER`. The
case enters `SERVE_WAIT`, and the seller answers with `served(nonce,
bundleHash)`, which moves it to `SERVE_CONFIRM`. After the challenge window,
`finalizeServed` ends the case as protocol `INCONCLUSIVE`.

`served` accepts any nonzero `bundleHash`
(`contracts/src/modules/FairBindDelivery.sol`, `served`). In the buyer and
verifier serve paths that is sound, because the requester fetches the bundle
off chain, compares it against the committed hash and escalates to on-chain
publication if it does not match. In the keeper path nobody plays that role:

- `escalate` is restricted to the requester, and a keeper has no discretion
  over results, so the keeper process never escalates;
- the seller's serve endpoint authenticates only the `BUYER` and `VERIFIER`
  roles (`cryptography-v1.md`, `FairBindServeAuthorization`), so a keeper
  cannot even retrieve the bundle it would have to check.

A seller can therefore answer a keeper serve request with an arbitrary hash,
wait out the challenge window, and obtain a protocol `INCONCLUSIVE`, which
changes no counter and no seller state. The `UNSERVED` outcome, which the
fallback exists to preserve, is avoided without producing the sampled
response.

## Decision

A `KEEPER`-role serve request skips the off-chain redelivery step and requires
on-chain publication directly.

1. When the fallback applies, the case enters `PUBLISHING` with requester role
   `KEEPER` and `publishDue = block.number + serveBlocks`, the same deadline a
   keeper `SERVE_WAIT` had. The contract emits `ServeRequested` and
   `ServeEscalated` in the same transaction.
2. The seller publishes the response with `publish`, or with
   `beginPublication`, `publishChunk` and `finalizePublication`. The contract
   checks the published request against the purchase and the published
   response against the seller-signed receipt, exactly as for an escalated
   buyer or verifier serve.
3. A valid publication ends the case as protocol `INCONCLUSIVE`, as delivery
   did before: no counter changes, the seller state is unchanged, and the
   purchase becomes releasable subject to its other conditions.
4. `timeoutServe` after `publishDue` with no valid final publication ends the
   case `UNSERVED`, a seller failure.
5. `served` reverts for a `KEEPER`-role case. `acceptServe`, `finalizeServed`
   and `escalate` never apply to it, because the case never enters
   `SERVE_CONFIRM`.

The fallback still applies only to the initial stage of a sampled case whose
seller has not served in that case, and still at most once per case.

## Consequences

- The seller can no longer leave a keeper serve request with an unverified
  hash. The only exits are a publication the contract verifies against the
  signed receipt, or `UNSERVED`.
- The keeper needs no new role, endpoint or signature format. The keeper
  process already calls `timeoutServe` for an expired `PUBLISHING` case, and the
  seller process already publishes whenever a case of its own is in
  `PUBLISHING`.
- The seller pays publication gas for up to `maxResponseBytes` on this path.
  The path is reached only after every assigned verifier failed to act, so it
  is rare by construction, and `serveBlocks` already budgets one block per
  chunk plus two.
- The case horizon of `profile-v1.md` section 3 budgets a serve, a challenge
  and a publication window for each serve procedure. The keeper path now uses
  only the publication window, so the bound still holds. The judgment delay
  `L` never included this path.
- The router ABI is unchanged. The case record reuses the existing
  `publishDue` field.

## Properties

- P1: unchanged. No identifier, signature or encoding changes.
- P2: strengthened. On the keeper path the committed response either becomes
  publicly available and verified on chain, or the purchase becomes refundable
  through `UNSERVED`. Funds are held until one of the two happens, within
  `serveBlocks`.
- P3: unchanged for honest sellers, who can always publish the response they
  signed. A seller that cannot publish the signed response is counted as
  failed, which is the outcome the fallback was meant to have.
- P4: unchanged. No verdict, assignment or verifier penalty depends on this
  path.

## Regression

`contracts/test/FairBindBond.t.sol` covers the new behaviour: a keeper case
enters `PUBLISHING`; a valid publication ends it protocol `INCONCLUSIVE`
without counters; a publication timeout ends it `UNSERVED`; and `served` with
an arbitrary hash reverts, where the old behaviour accepted it and let the case
end without a seller failure.
