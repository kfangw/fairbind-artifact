# Settlement replay (R20): injection model and scale rules

The replayer that drives recorded x402 settlements through a local deployment
is not written yet. This directory fixes, as reviewed and tested code, the
rules its results will be computed with. `injection.py` holds them;
`test_injection.py` checks them (`make analysis-check` runs both).

## Scale assignment

| Rule | Role | Scale of a receiving address |
| --- | --- | --- |
| `nF` | main condition | `max(1, ceil(rbar / r_fill))` |
| `nR` | secondary condition | `max(1, ceil(rbar / r_max))` |
| `n1` | control | 1 |

`rbar` is the address's mean settlement count per block over the replay period
(settlements over 604,800 blocks for 14 days of two-second blocks); `r_fill`
and `r_max` are the operating-point values (`refillPpmPerBlock` and
`maxRatePpmPerBlock` over `PPM`). A bucket's sustained capacity is `n *
r_fill`, so only `nF` admits the mean rate of every address: `nR` divides by
`r_max` and leaves an address whose mean exceeds `n * r_fill` rejected for
good (`under_assigned`). `nR` is reported beside `nF` to show what that
under-assignment does to rejections and to `H`; its under-assigned addresses
are reported apart.

## Burst capacity `qX`

`qX` is the p99 (nearest rank) over every receiving address of that
address's highest one-hour settlement count within a seven-day window
(`qx_statistic`). The population is every receiving address in the window,
not the replayed top 400. The same seven-day window is used on the period
before the replay and on each half of a cross-fit, so the two paths compute
the same statistic.

With the cross-fit, the two half replays feed only the rejection columns
(`rejected_count`, `rejection_rate`) and the checks that read them (R20-F3,
R20-M1). `H`, sample and epoch counts, windows below `n_min` and every
injection column come from one replay of the whole 14 days, run with the
larger of the two half values of `q` (`full_replay_q`, `column_source`).

## Input check

The extracted settlement list is compared with the aggregate query before the
replay starts (`input_check`). It is within tolerance when the row count
differs from the aggregate total by at most 0.1 percent and every address's
count differs from its aggregate by at most `max(1, 0.5 percent)`. The report
carries every per-address difference, their sum and their maximum. Outside
tolerance, the extraction is repeated once after checking the period
boundaries; if it is still outside, the new list becomes the reference and
ranks, groups and scales are recomputed from it before the replay. The check
looks at the extraction only, never at replay results.

## Injection model

The replay's verifier passes every sampled case, so no freeze happens in the
replay itself. Wrongful confirmed failures are injected afterwards, offline,
per seller (`draw_failures`, `seller_loss`, `injection_row`):

1. Each sampled case becomes a wrongful confirmed failure with probability
   `w`, confirmed at its opening block plus `judgmentHorizon + appealHorizon
   + 1`.
2. At a confirmed failure `f` the account freezes. The **new** principal loss
   is the value of every accepted entry settled after the previous freeze
   block and at or before `f` that is still unreleased at `f` (`settled +
   T_hold > f`). A later failure moves `freezeBlock` but creates no new pool,
   so an entry is lost at most once. The first failure counts every
   unreleased entry.
3. Each failure also deducts `B / k` (the per-failure share).
4. The seller is suspended from `f` and re-enters at `f + 1 + tau_re`; `tau_re`
   is an injected setting (0 and 1,800 blocks). A settlement in between is
   rejected and reported as lost sales, not as loss.
5. R20-C3: the principal loss of a seller never exceeds its accepted revenue;
   a draw that breaks this is an implementation error.

Every injection row carries the per-seller formula value

```text
1 - exp(-s * w * rbar_acc * T_hold) + s * w * B / (k * vbar)
```

(`formula_value`), with `rbar_acc` the number of the seller's accepted
settlements divided by the 14-day replay window (604,800 blocks), not by the
span from its first to its last settlement, and `vbar` the mean value of the
accepted settlements; both are pooled over the draws. The first term is the frozen share of
settlements, the second the share the `B / k` deduction adds; only the second
can take loss over revenue above one. R20-D1 compares the Monte Carlo mean of
loss over revenue with this value seller by seller (`ratio_to_formula`). At
the data API bucket rate (0.05 per block) the first term is 0.758.
