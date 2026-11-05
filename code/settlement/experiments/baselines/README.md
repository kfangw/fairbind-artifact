# Baseline arm configs

One JSON file per baseline arm. The controller loads them
(`experiments/controller/baselines.py`), resolves every `op:<expression>` and
`rate:<name>` value against the shared operating point
(`experiments/operating-point.json`) and attaches the resolved config to each
plan entry whose `arm` names it. No arm runs yet: each needs a policy adapter
outside the contracts, so the plan marks those runs blocked and records the
config it would use.

| id | Represents | D (hold) | Bond |
| --- | --- | --- | --- |
| B0a | Rail authorization flow, no recourse | 0 | none |
| B0b | Rail upfront flow, no recourse | 0 | none |
| B1 | Sampled re-execution, arbitration assumed exact | 0 | `g/pi` (sensitivity 1x, 3x, 10x) |
| B2 | Escrow with one designated evaluator | `L` (release on expiry) | none |
| B4 | Full collateral over the period, session settlement | session window | daily ceiling x 10 days |
| B6 | Tiered daily caps, exposure ceiling, rolling reserve | reserve 30% for 60 days, settlement delay 24 h | none |
| B7a | Open-exposure bond, E_open read as the balance at the check | 0 | `E_open + P_max`, `P_max = v` |
| B7b | Open-exposure bond, E_open read as everything inside the window | 0 | `E_open + P_max`, `P_max = v` |

B3 (hardware-attested atomic exchange) has no executable config; it is compared
on its properties only.

## What changed when the configs moved to the shared operating point

The earlier shared constants used `g = v = 1 USDC`, `L = 5,400` blocks,
`p = 0.0731` and a one-day rate sample of 348 sellers (top mean 107.5 per hour).
All of these conflicted with the profile and are gone; `operating-point.json`
lists them under `replaced_values`. Every config records its own edits in
`changes_from_source`.

| Arm | Changed |
| --- | --- |
| B0a, B0b | nothing numeric (no hold, no bond, no window) |
| B1 | `retentionBlocks` 5400 -> `op:L`; bond and penalty 100 USDC -> `op:g/pi` (its own `p = pi`), with a 1x/3x/10x list; `samplePpm` and `effectivePpm` -> `op:pi*1000000` |
| B2 | `deferBlocks`, `deferExpiryBlocks`, `retentionBlocks` 5400 -> `op:L` (an expiry shorter than `L` would release unjudged purchases because of the parameter) |
| B4 | nothing from the operating point; the 100 USDC daily ceiling and 10-day duration are the design's own constants; a session length list of 1, 6 and 24 hours was added |
| B6 | refund window (30 days) added beside the 60-day reserve, with both window readings (`challenge_window`, `refund_window`); `E_max` swept over `g/p`, `10 g/p` and the 500 USDC default; complaint policy fixed |
| B7a, B7b | split from one config into two readings of `E_open`; `retentionBlocks` and the window 5400 -> `op:L`; `P_max` 100 USDC -> `op:v`; complaint policy fixed |

## Shared rules for every arm

- Arms without a judging party (B0a, B0b, B4, B6, B7a, B7b) get verdicts
  injected from the controller's ground truth; the result must mark them
  injected and must not report them as a measured detection rate.
- A metric that the arm has no carrier for is recorded as undefined with a
  reason, never as zero.
- B6, B7a and B7b detect a fault only through a complaint. All three use the
  same `complaintPolicy`, `buyer_complains_when_verdict_known`: the controller
  files the complaint at the block where the ground-truth verdict becomes
  known to the buyer (settlement block plus `L`). A run with no complaint is
  reported as undetected by construction.
- B6 and B7a/B7b are implemented at their best: the exposure register is
  recomputed at every admission and updated atomically with capture and
  release, so a leak comes from the rule, not from a lazy adapter.

The main run list (`experiments/scenarios/run-list.json`) names the arms each
scenario runs against; B7a and B7b are in it.
