# FairBind review artifact

This bundle holds the code, inputs and recorded outputs behind the implementation, model-checking, replay and
cost-model results of the manuscript. It was assembled from five commits of one code repository and from the
measurement scripts of the study; `SOURCES.tsv` gives the source of every file and `ANONYMIZATION.md` lists every
edit made while assembling it. Raw chain data are not included (about 1.1 GB); `data-manifests/` holds the
queries, per-file manifests and checksums needed to fetch and check them again.

The recorded runs used Foundry 1.7.1 (forge, anvil, cast) with solc 0.8.24 and Node 22 (`code/settlement/logs/*/commands.txt`).
The checks of this bundle (section 3) were run on Linux x86-64 (4 cores, 15 GB RAM) with Python 3.13 (numpy 2.5,
matplotlib 3.11), Foundry 1.5.1, Go 1.25 and Node 22.

## 1. Contents

| Directory | What it is |
| --- | --- |
| `code/settlement/` | reference settlement contract and verification contracts (`contracts/test/sdk`, `contracts/test/g7`), Chainlink VRF v2.5 consumer and fork test (`contracts/test/sdk/vrf`), release units, anchor completion and pulls, load tests up to 5,000 sales, deployed-USDC fork tests (`contracts/test/sdk/usdcfork`), signing client and watchtower (`adapters/signing-client`, TypeScript, with the 15 end-to-end scenarios in `e2e/`), gas-fit scripts (`scripts/fit_*_gas.py`, `scripts/compare_usdc_gas.py`), the logs of the recorded runs (`logs/`), and the earlier full prototype (Solidity system under `contracts/src`, Go services and protocol library; no reported result depends on it) |
| `code/anchor-variants/` | anchor variants C1 and C1r of the reference contract, their generated test suites and the K13 gas rows (`contracts/test/sdk/variants`, `contracts/test/sdk/K13AnchorGas.t.sol`) |
| `code/judgment-formal/` | symbolic checks (halmos) and concrete cases of the tier 1a and tier 0 verification contracts and of the proof call (`contracts/test/g7`) |
| `code/replay/` | R11 and R12 replayers and the R12 aggregation (`experiments/replay`) |
| `code/model-check/mc1/` | MC1, explicit-state model check of the dispute state machine, with result files |
| `code/model-check/mc2/` | MC2, model check of release units, payout freezing and dispute slots, with result files |
| `measurement/` | cost-model and measurement scripts with their small inputs and recorded outputs, in the directory layout the scripts compute their paths from (section 3.5) |
| `replay-inputs/` | the small registered inputs of the R12 replay and the R12 registered parameter block |
| `data-manifests/` | extraction and checksum queries, per-file manifests of the raw daily settlement files, decoder, `verify_raw.py` |

`measurement/docs/11_journal/release-units/` is a byte-identical copy of `code/settlement/logs/` placed where the
cost-model scripts read the gas fits.

`measurement/docs/11_journal/C32/`, `C34/` and `C34_ASP-replay/` hold the later post hoc calculations: the
replay comparison of FairBind's payout with the bonds' uncovered revenue and the daily-sum check of the bond replay
(`C32/W3_replay`), the deterrence margin and the cost of a larger deduction (`C32/W4_deterrence`), the base-fee
filling cost (`C32/W6_basefee`), the out-of-window seller-epoch multiple and threshold sensitivity
(`C32/W7_out-of-window-k`), StableEnrich priced with the enclave-receipt proof call (`C34`), and the rolling reserve
of a published settlement profile on the bond replay (`C34_ASP-replay`). Each folder has a short `README.md`
(section 3.7).

## 2. Requirements

* Foundry 1.7.1 as recorded (`forge`, `anvil`, `cast`; 1.5.1 also builds and runs the tests of section 3.1); Foundry downloads solc 0.8.24.
* Python 3.13 with numpy (2.5) and matplotlib. The R12 replayer pins `numpy==2.5.4` and `scipy==1.18.1` for the
  full replay; its registration check and self-check run without scipy.
* Go 1.25 for the Go module of the earlier prototype (`code/settlement`, module path `example.org/fairbind`).
* Node >= 22.18 and network access for the signing client (`npm ci`) and the end-to-end run on a Base fork.
* Memory: each Foundry profile below compiles only its own test directory. Building the default profile of
  `code/settlement` (the whole earlier contract system with `via_ir`) needs 15 GB or more and is not needed here.

## 3. Reproducing the results

Commands run from the bundle root unless a `cd` is shown.

### 3.1 Reference settlement contract (`code/settlement`)

```sh
cd code/settlement
FOUNDRY_PROFILE=sdk forge test --threads 2
```

Expected (Foundry 1.5.1, first build about 26 min on 4 cores, 5 GB memory): `Ran 23 test suites ...: 259 tests
passed, 0 failed, 12 skipped (271 total tests)`. The skipped tests are the fork tests without a fork URL and the
two 5,000-sale loads, which need a raised gas budget (`--isolate --gas-limit 9223372036854775807`, see
`logs/anchor-units/commands.txt`).

The run recorded at the source commit is `logs/anchor-units/forge-sdk-all.log` (and the fork tests,
`forge-sdk-fork.log`). Fork tests (VRF coordinator, deployed USDC, ERC-1271) need `BASE_RPC_URL` (see each file
header) and are skipped without it. `logs/*/commands.txt` give the exact commands of every recorded run, including
the release and anchor load tests and the deployed-USDC runs.

Gas fits from the recorded logs:

```sh
python3 scripts/fit_release_gas.py logs/anchor-units/forge-release-gas-load.log logs/release-units/old-contract/forge-old-release.log
python3 scripts/fit_anchor_gas.py logs/anchor-units/forge-anchor-load.log
python3 scripts/compare_usdc_gas.py   # see logs/usdc-fork/commands.txt for the arguments
```

Signing client and watchtower (unit tests; end-to-end run on a local anvil fork of Base at block 52977000):

```sh
cd code/settlement/adapters/signing-client
npm ci && npm test
E2E_K=1 ./run_e2e.sh     # and E2E_K=2; writes e2e-out/result.json
```

Recorded results: `logs/anchor-units/e2e-k1-result.json`, `e2e-k2-result.json` (15/15 scenarios as expected).

Go module of the earlier prototype: `go build ./... && go test ./...` (24 packages; the tests that compare with
`cast` need Foundry 1.7.1 on `PATH`, section 5).

### 3.2 Anchor variants C1 and C1r (`code/anchor-variants`)

```sh
cd code/anchor-variants
FOUNDRY_PROFILE=sdk forge test --threads 2 --match-path 'contracts/test/sdk/variants/*'
```

Expected: `Ran 14 test suites ...: 364 tests passed, 0 failed, 0 skipped` (first build about 29 min).

The K13 gas rows come from `K13AnchorGas.t.sol`; the recorded logs and the tables built from them are in
`measurement/docs/11_journal/K13/logs/` (`python3 -I measurement/docs/11_journal/K13/k13_tsv.py DIR` rebuilds the
two tables from copies of the logs).

### 3.3 Verification contracts (`code/judgment-formal`)

```sh
cd code/judgment-formal
FOUNDRY_PROFILE=g7 forge test --threads 1 --match-contract 'ConcreteCasesTest|ProveCallHevmTest' --fuzz-runs 10000
```

Expected: `9 tests passed, 0 failed, 0 skipped (9 total tests)`.

The full symbolic run `contracts/test/g7/run_g7.sh` needs halmos 0.3.3, hevm 0.55.1 and z3 and takes hours.

### 3.4 Model checks

```sh
cd code/model-check/mc1 && python3 -m unittest test_model && python3 run.py E5_rdl 2
cd code/model-check/mc2 && python3 coverage.py && python3 report.py
python3 run_grids.py mut reading honest   # about 2 min (main: about 2 h); skips a grid whose results/<name>.json exists,
                                           # so move the recorded files aside first to rerun them
```

`results/` of each directory holds the recorded result files; `mc1/results/MANIFEST.md` lists the commit each MC1
run imported.

### 3.5 Cost model (`measurement/`)

The scripts compute their input paths from their own location, so run each from its directory. All of the
following need only the files in the bundle and are deterministic; the run times are those on the machine above.

```sh
cd measurement/docs/11_journal
(cd K11 && python3 -I k11b.py)                 #  9 s, rewrites k11b_output.md
(cd K12 && python3 -I k12.py)                  #  4 s, rewrites k12_output.md
(cd K13 && python3 -I k13_cost_s1.py --gas logs/k13_gas.tsv --out /tmp/k13_output.md && python3 -I test_k13.py)
(cd K14 && python3 -I k14.py --out /tmp/k14 && python3 -I test_k14.py)
(cd P3_posthoc && python3 -I p3.py --out /tmp/p3 && python3 -I p3_tables.py /tmp/p3 && python3 -I p3_check.py /tmp/p3)
(cd P9_posthoc && python3 -I p9.py --out /tmp/p9 && python3 -I test_p9.py)
(cd P10_fit-conditions && python3 -I p10.py --out /tmp/p10)              # 50 s
(cd P11_posthoc && python3 -I p11.py --out /tmp/p11 && python3 -I test_p11.py)   # 80 s
(cd P10u_real-USDC && python3 -I p10u.py --out /tmp/p10u)                # 110 s
```

Expected: every table file (`*_tables.md`) and every PNG figure equals the recorded one in `results/` byte for
byte, and `p3.json`, `p3_supp.json`, `p3_check.json` and `k13_results.json` are equal as well. The other JSON outputs
differ from the recorded ones only in the SHA-256 fingerprints of the scripts they record (the scripts were edited
for the bundle, see `ANONYMIZATION.md`), and `p10.json` also in the field `closed_form[*].b` and `Re`: the recorded
`p10.json` predates a correction of `b` in `p10.py`, which `p10u.py` takes into account. PDF figures differ only in
their creation dates. P9, K14, P3, P6 and P11 each check that their in-memory rerun of `k11b.py` reproduces
`K11/k11b_output.md` byte for byte and print the result.

Scripts that need the raw settlement files or the replay outputs (not included): `P1_posthoc/p1_compute.py`,
`p1_check.py`, `R13/r13_sim.py run`, `R14/r14_compute.py`. Their recorded outputs are in their `results/`
directories; `R13/test_r13.py` and `r13_sim.py selfcheck --out DIR --reps 2000` run on synthetic data. The figure
of the manuscript is drawn by `measurement/docs/figures/fig_fit_redraw.py` from `P10_fit-conditions/results/p10.json`
(and by `p10u.py` for the deployed-USDC constants).

WF1 and BASE1 (availability gaps of signed price feeds; Base batch-posting gaps) read public RPC endpoints and
archives; they were not rerun for this bundle. `WF1/check/wf1_check.py selftest` runs on synthetic data, and
`WF1/results/analyze_output.txt` is the recorded analysis.

### 3.6 R12 replay (`code/replay`)

```sh
cd code/replay/experiments/replay
REG=../../../../replay-inputs/R12_registration_block.md
python3 -I r12_compute.py check-registration --registration $REG
python3 -I r12_compute.py selfcheck --registration $REG --work /tmp/r12-selfcheck      # about 80 s
```

`check-registration` prints the SHA-256 of the block file and exits 0 when the registered block equals the
constant in the code; `selfcheck` ends with a JSON line in which `verdict_paths_present`, `outputs_present`,
`g3_records_equal` and `flags_as_registered` are `true`. The full replay (`run_r12.sh`, about 5 GB per window)
needs the raw data of section 4; its recorded aggregation is `measurement/docs/11_journal/R12/results/`.

### 3.7 Replay comparisons, cost sensitivities and the rolling-reserve replay

```sh
cd measurement/docs/11_journal
(cd C32/W4_deterrence && python3 -I w4.py --out /tmp/w4)                 #  8 s
(cd C32/W6_basefee && python3 -I w6.py > /tmp/w6_stdout.txt)               #  1 s
(cd C32/W7_out-of-window-k && python3 -I w7.py --out /tmp/w7)            # 11 s
(cd C34 && python3 -I c34.py --out /tmp/c34)                             #  7 s
```

Expected: `w4_tables.md`, `w7_tables.md`, `c34_tables.md` and `w6_stdout.txt` equal the recorded files in each
`results/` byte for byte; `w4.json`, `w7.json` and `c34.json` differ from the recorded ones only in the SHA-256
fingerprints of the scripts and of the calculation documents (`absent`, not included). Each script first checks that
its in-memory rerun of `k11b.py` and its unchanged cells reproduce `K11/k11b_output.md`, `P11_posthoc/results/p11.json`
(and `P8_posthoc/results/p8.json`, `P10u_real-USDC/results/p10u.json`) and prints the result; `w6.py --check` checks
the base-fee rule against two on-chain block pairs and the eight cells of the margin table.

`C32/W3_replay/w3_compare.py`, `w3_daily.py` and `C34_ASP-replay/c34_asp.py` need the R12 replay outputs and sale
lists or the raw daily files (section 4), whose commands are in the folders' `README.md`. With them, `w3_compare.json`,
`w3_sellers_<window>.csv`, `w3_daily_<window>.json`, `c34_asp.json` and `c34_sellers_<window>.csv` are reproduced;
the JSON files differ only in the recorded script fingerprints and in the numpy version they record.

## 4. Raw data

The replay input is the set of daily files of USDC `transferWithAuthorization` settlements on Base through 20
facilitator addresses, for four date ranges (about 1.1 GB compressed). They derive from public Base logs and were
extracted from an indexer (Dune) with the queries in `data-manifests/queries/`; an indexer account is needed.

| Folder | Dates (UTC) | Files | Extraction query | Checksum query |
| --- | --- | --- | --- | --- |
| `median/` | 2026-07-24 to 2026-08-13 | 21 | 8903737 | 8903740 |
| `median_prior14/` | 2026-07-10 to 2026-07-23 | 14 | 8907656 | 8907658 |
| `busy/` | 2026-06-09 to 2026-06-29 | 21 | 8903737 | 8903740 |
| `busy_prior14/` | 2026-05-26 to 2026-06-08 | 14 | 8907656 | 8907658 |

Decode a downloaded result with `data-manifests/decode_dune_results.py` and check a folder with
`python3 data-manifests/verify_raw.py data-manifests/busy/manifest.jsonl RAW/<folder>`. The replayer expects the
folders under the names `S1b_median-window`, `S1b_prior14_median-window`, `S1b_busy-window` and
`S1c_busy-window-prior14` next to each other.

## 5. Known limits

* Not rerun for this bundle: the full R12 replay, R13 and R14 on the replay outputs, P1, the MC1 and MC2 full grids,
  the halmos and hevm runs, the Base-fork runs, and the WF1 and BASE1 live measurements.
* The Go tests of the earlier prototype that call `cast` expect `cast` from Foundry 1.7.1 on `PATH`; with it all 24
  packages pass. With `cast` 1.5.1, 40 top-level tests in six packages fail, identically at the source commit.
* Comments, labels and table headings of the measurement scripts were translated word by word from the authors'
  working language; the English of those strings is rough. Numbers, code paths and logic are unchanged
  (`ANONYMIZATION.md`).
