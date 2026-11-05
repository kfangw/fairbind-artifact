# ADR 0033: Proportional appeal deposit

Status: Accepted 2026-10-19. Amends the appeal deposit of a buyer's appeal of
an initial PASS for profiles with batch terms whose `depositPpm` is not zero
(`contract-interface-v1.md`, "ADR 0033 proportional appeal deposit"). Every
other appeal and the dispute deposit are unchanged.

## Decision

1. **Held total and marks.** The held total of a bond account is its deferred
   balance. Each settlement updates the account's marks: the highest value of
   the current fixed window of `deferBlocks` blocks, that of the previous
   window, and the value after the change. The first settlement of a block
   first keeps the high mark as it stood at the end of the previous block.
2. **Deposit.** `appealWithLimit(nonce, maxDeposit)` is the buyer's appeal of
   an initial PASS. The deposit is `max(d0, ceil(depositPpm * H / 1e6))`, `d0`
   the profile's `appealDeposit` and `H` the high mark at the end of the
   block before the appeal; a settlement earlier in the appeal's block does
   not change it. The call reverts `DepositAboveLimit` when the deposit
   exceeds `maxDeposit`. The fixed `appeal` reverts for a buyer's appeal of a
   PASS under such a profile; the seller's appeal of a FAIL keeps the fixed
   deposit.
3. **Resolution.** A failed appeal pays the seller `d0` and locks the rest in
   `lockedForfeit`; an appeal that wins, or ends inconclusive, returns the
   whole deposit to the buyer.

## Consequences

- The held total counts frozen entries and refunds due until they leave the
  deferred balance; the mark after the last settlement stands for the value
  carried into a later window. Both make the deposit an upper bound.
- `settle` of such a profile writes up to two more slots.

## Tests

`AppealDeposit.t.sol`: a same-block settlement does not raise the deposit
(with a mutation that reads the current mark), the limit and the fixed
paths, a failed appeal's split, a won appeal's refund, and the mark keeping
the window's peak after the total falls.
