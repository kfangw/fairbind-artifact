# ADR 0035: Side-gain deposit and the repeated sampling request

Status: Accepted 2026-10-19. Adds the side-gain profile: a profile with batch
terms whose `sideGainPpm` (eta) is not zero (`contract-interface-v1.md`,
"ADR 0035 side-gain deposit"). Amends `settle` and `seal` for such profiles.

## Decision

1. **Opening count.** `recordEpochOpenCount(profile, e)` records, once, from
   the first block of epoch e, the number of verifiers eligible by state (ADR
   0032) at the block before it. A settlement of the epoch reverts
   `ServiceClassUnavailable` unless the count is at least `minVerifiers`.
2. **Deposit.** The account keeps a side-gain deposit apart from its bond
   (`depositSideGain`). A settlement needs `deposit >= u (open + 1)`, `u =
   ceil(eta V / p0)` at the account's recent cap `V`, and `open` the number
   of its sales whose sampling is undecided or whose sample case is open. A
   sale leaves `open` when its sample case ends, or by `clearSideGain` once
   it is not sampled, its epoch failed or it ended. A sample case's
   confirmed failure (final FAIL or UNSERVED) locks one unit from the
   deposit. The deposit leaves only while `open` is zero
   (`withdrawSideGain`).
3. **Repeated request.** Past `M = A + D_S + T_V` without a SAMPLE value,
   `rerequestSampleValue` asks for input `(profileId, A, 1)` without a
   deadline, and `seal` takes that value. The first request's late value is
   still refused.

## Consequences

- An honest seller's capital grows with its open sales times `eta V / p0`.
- An epoch whose repeated request is never answered keeps its sales held.

## Tests

`SideGain.t.sol`: the opening count and the deposit per open sale, a
verifier's exit before the epoch, the unit locked on a sample failure, the
clearing of an unsampled sale, the repeated request and its seal, and the
refusal for other profiles.
