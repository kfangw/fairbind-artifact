# Predicate calibration (C1): configuration

`c1-config.json` fixes the rules of the C1 predicate study before any sample
is collected. The data-API collector (`experiments/c1collect`) reads its
`data_api` and `collection` sections; no inference calibration code exists
yet. Values are recorded before the main sample.

## Inference tolerance: one joint calibration

A response fails when any of the three comparison metrics (`expMismatches`,
`mantissaMean`, `mantissaMedian`) exceeds its tolerance. Calibrating each
metric separately at its own calibration maximum puts the false-rejection
rate between 1/301 and 3/301, depending on how the metrics correlate, and
at 3/301 the upper bound on alpha over 1,500 responses exceeds 0.01 almost
surely: the check would measure the rule's multiplicity, not the predicate.

The tolerance is therefore calibrated once, on a joint score:

1. Scale sample (first 100 prompts): `m_j = max(max x_j, epsilon_j)` with
   `epsilon` 1 for `expMismatches` and 0.01 for the mantissa metrics.
2. Joint score of a response: `u = max_j (x_j / m_j)`.
3. Calibration sample (next 300 prompts): `u* = max u`. Under
   exchangeability a new response exceeds `u*` with probability at most
   1/301.
4. Tolerances `t_j = u* * m_j`, rounded outward (integer floor for
   `expMismatches`, two-decimal ceiling for the others). Any metric above
   its `t_j` is exactly `u > u*`, so the implemented per-metric comparison is
   unchanged.

Neither sample is used to estimate alpha or beta.

## Data API wrong answers and collection

Each wrong answer is made from one real seller-role capture, and one capture
gives at most one wrong answer. The unit is the type (one stratum): D-perturb
(`m` 1.5 / 3 / 10, 84 / 83 / 83), D-near (`m` 1.05 / 1.1 / 1.25, 150 each),
D-stale (1 h / 24 h, 75 each), D-unit (60), all in the decision beta, whose
value is the largest per-type upper bound. D-near samples are labelled wrong
only against the truth reference (Bitfinex trades near the grid time), which
never enters a judgment. D-adaptive (150) is descriptive, D-format (25 + 25)
a code check. `collection` fixes the grid, the seeded lists, the instance
schedule, the 429 rule and the truth-lookup retries that
`experiments/c1collect` implements.

## Intervals

The data API alpha, inconclusive rate and pairwise ratios pool the two
seller-role responses of one cell, which are not independent. Besides the
Clopper-Pearson and day-block bounds, a cell-cluster bootstrap (10,000
resamples of cells) gives a third one-sided 95 percent bound; the decision
table uses the largest upper and the smallest lower bound of the three. A day
block is a UTC date with at least 72 complete cells; shorter dates join the
previous block. Wrong-answer generators make one wrong answer per capture and
get no cluster correction; a per-type cell-cluster upper bound is descriptive.
