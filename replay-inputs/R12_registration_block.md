# R12 registered block

The machine-readable block of the R12 pre-registration, extracted unchanged except for the path and name
translations listed in ANONYMIZATION.md. `r12_compute.py` requires exactly one such block in the file passed
as `--registration`. SHA-256 of the full original registration document: f01f8f753b97faf7bb80d626b50582a1a3c3719831414f8c408bd5609dfbe3f7.

```json r12-registered
{
 "registration": "R12",
 "windows": [
  "median",
  "busy"
 ],
 "lists": {
  "median": {
   "file": "median/settlements_base_2026-07-24_2026-08-13.csv",
   "sha256": "091476280d744b7cd932c06beabf35d3d96d382ecb0d69bfb0383200a709052a"
  },
  "busy": {
   "file": "busy/settlements_base_2026-06-09_2026-06-29.csv",
   "sha256": "91412e264212412afcd4ecdd21e7ca7d98ce7ab8522572fdabef756e6fa10133"
  }
 },
 "prior_lists": {
  "median": {
   "file": "median/settlements_base_prior_2026-07-10_2026-07-23.csv",
   "sha256": "5f701f738aae2cbcb935443e1545aa61d470325bcfceff2a2520f06bac2d9486",
   "rows": 5648702,
   "first_date": "2026-07-10",
   "last_date": "2026-07-23"
  },
  "busy": {
   "file": "busy/settlements_base_prior_2026-05-26_2026-06-08.csv",
   "sha256": "617c9a753bdd331b0c5f2e4f83565cf8789f486fe4105ca3bc00551f0e2e4e21",
   "rows": 1178201,
   "first_date": "2026-05-26",
   "last_date": "2026-06-08"
  }
 },
 "addresses": 415,
 "inputs": {
  "raw_dirs": {
   "median": {
    "window": "S1b_median-window",
    "prior": "S1b_prior14_median-window"
   },
   "busy": {
    "window": "S1b_busy-window",
    "prior": "S1c_busy-window-prior14"
   }
  },
  "manifests": {
   "S1b_median-window": "1f48d314055fa8bf0e92cb8e118975287d55f4ab7ac0a917e0e1104922e84923",
   "S1b_busy-window": "90371183d2bfcad691db4ab7d886754010f876eda4e794f72ca0ff55bc72d7e1",
   "S1b_prior14_median-window": "de6d3c313f1937db69474573ea5a3afa1c127600d4b684ae3af39d73c5262941",
   "S1c_busy-window-prior14": "e5d68f67636a831cbfc161403a25201b5e9b4b74cee509c261a4af73f7d17f4d"
  },
  "conditions": {
   "median": {
    "path": "05_run-evidence/design2/median-period/in/conditions_base_median.json",
    "sha256": "5e58da679e9dcf8d04ab0f750d955cde95156a66900b910e614f42840ac56e8c"
   },
   "busy": {
    "path": "11_journal/J9/in/conditions_base_busy.json",
    "sha256": "b55539d65c52addd93a79e994c041ad4370a626f506423f91d4017d5a3481936"
   }
  },
  "reference_dir": "11_journal/J9/in/ref",
  "reference": {
   "sellers_dune_top400.csv": "3f255ef8174bf502cbc1f7d14e6ec84a011f6d5e8599779b11cd04e5c9bcae91",
   "sellers_dune_all4400.csv": "bb7ee6f57f87b990b665fb65739b1bae32c14cc98b5852b079dd625d9d53b124"
  },
  "d2_config": {
   "path": "11_journal/J13a/in/design2_vmax05.json",
   "sha256": "76cf20c6423a108c555b80b70c8d1ddcf05c336bd14eeb5ef5631d8132a77caf"
  }
 },
 "environment": {
  "numpy": "2.5.4",
  "scipy": "1.18.1"
 },
 "V_atomic": 1000000,
 "b_atomic": 1000000,
 "ks": [
  1,
  2,
  4,
  8,
  16,
  32
 ],
 "epoch_blocks": 300,
 "seconds_per_block": 2,
 "blocks_per_day": 43200,
 "avg_offset_blocks": 31073,
 "history_days": 14,
 "history_margin": 2,
 "release10": {
  "cost": {
   "mode": "fixed10",
   "anchor_delay": 120,
   "vrf_response": 10,
   "vrf_slack": 20,
   "proof_window": 1800,
   "dispute_window": 1800,
   "bind_window": 1800,
   "proof_delay": null,
   "keeper_delay": 0,
   "accept_ppm": 0,
   "unsigned_ppm": 0,
   "accept_over_cap": true,
   "seller_epoch_k": "k",
   "dispute_from": "anchor"
  },
  "bridge": {
   "mode": "fixed10",
   "anchor_delay": 120,
   "vrf_response": 100,
   "vrf_slack": 50,
   "proof_window": 1800,
   "dispute_window": 1800,
   "bind_window": 300,
   "proof_delay": null,
   "keeper_delay": 0,
   "accept_ppm": 0,
   "unsigned_ppm": 0,
   "accept_over_cap": true,
   "seller_epoch_k": 1,
   "dispute_from": "anchor"
  }
 },
 "replay_flags": {
  "common": [
   "--qx",
   "137",
   "--conditions",
   "1",
   "--repetitions",
   "1",
   "--design",
   "2",
   "--vmax",
   "1",
   "--sales-cap",
   "none",
   "--chain",
   "base",
   "--draws",
   "1",
   "--k-w",
   "0.015",
   "--preset",
   "r11-main",
   "--r10-anchor-delay",
   "120"
  ],
  "cost": [
   "--r10-vrf-response",
   "10",
   "--r10-vrf-slack",
   "20",
   "--r10-bind-window",
   "1800"
  ],
  "bridge": []
 },
 "run_dirs": {
  "cost": "{window}_r12cost/k{k}",
  "bridge": "{window}_r12bridge/k1"
 },
 "bridge_expect": {
  "median": {
   "addresses_observed_sha256": "0e20b271c23961fb84cc1ab7efcfea8144f51369368306d299b8aff20cc28b7f",
   "sales_npz_sha256": "15510c7920b219a4014c682c35701fc1c5abe4eccde95af2b3344ef2f892a9c5"
  },
  "busy": {
   "addresses_observed_sha256": "e0ce0c192195de70400e7e379c047913cc9b96ebc3ee6a1b8c5681ad37935988",
   "sales_npz_sha256": "116d0352a75c746c5617c34c5b5436eee048bc61d6fbcda15b35843e78bc0dfe"
  },
  "r11_file": "11_journal/R11/results/r11_addr_main_{window}_v1.csv"
 },
 "run_record": {
  "meta/design2/vmax_atomic": 1000000,
  "meta/design2/k_w": "0.015",
  "env/design": "design-2",
  "env/parameters/draws": 1,
  "env/parameters/qX": 137,
  "meta/condition": 1,
  "meta/block_seconds": "2"
 },
 "k_choice": {
  "release_gas": 114624,
  "release_l1_wei": "945606403.8667",
  "gas_price_gwei": "0.010",
  "eth_usd": "2401.44",
  "capital_rate": "0.10",
  "seconds_per_year": 31536000
 },
 "reserve": {
  "usd_per_open_purchase": "0.851522",
  "usd_per_open_purchase_low": "0.013778",
  "k11_open_blocks": 2250
 },
 "sets": [
  "S1r",
  "S1",
  "S2"
 ],
 "judgement_set": "S1r",
 "lags": {
  "own": "k_star",
  "k1": 1
 },
 "verdict_suffix": {
  "own": "",
  "k1": "d"
 },
 "S1r_counts": {
  "median": 289,
  "busy": 178
 },
 "thresholds": {
  "JL12_ratio_max": "1.2"
 },
 "verdict_paths": [
  "verdicts/JL12/holds",
  "verdicts/JEH12/holds",
  "verdicts/JER12/holds",
  "verdicts/JL12d/holds",
  "verdicts/JEH12d/holds",
  "verdicts/JER12d/holds"
 ],
 "outputs": [
  "r12_results.json",
  "r12_tables.md",
  "r12_addr_median.csv",
  "r12_addr_busy.csv",
  "r12_k_median.csv",
  "r12_k_busy.csv",
  "r12_sales_sha256.txt"
 ]
}
```
