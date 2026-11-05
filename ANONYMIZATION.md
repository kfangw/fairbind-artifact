# Anonymization and edits

The files of this bundle are copies of five code commits and of the study's measurement files. `SOURCES.tsv` gives,
for every file, its origin and the SHA-256 of the source file and of the shipped file; the two hashes differ for the
238 files edited as described below and are equal for every other file. Every "original SHA-256" or fingerprint
printed inside a recorded output refers to the source file, not to the shipped copy.

## 1. Identity, tool and path edits

* The author's name in every `LICENSE` and in `code/settlement/NOTICE`, the upstream repository URLs in `NOTICE`,
  `README.md` and `UPSTREAMS.lock.json`, and the repository named in one decision record are as in the source
  commits (they were withheld in the copy submitted for review).
* The Go module path is `example.org/fairbind` (in `go.mod` and every import). `go build ./...` and `go vet ./...`
  pass; `go test ./...` gives the same per-test results as the source commit (see README, section 5).
* Two Go tests located `cast` at a fixed path in the authors' tool directory; they now take `cast` from `PATH`
  (`exec.LookPath`) and are skipped when it is absent, as before.
* Branch prefixes of the form `<name>/` were removed from branch names in logs, scripts and notes (for example
  `release-units`, `vrf`, `mc1`).
* Absolute local paths were replaced: default directories of `run_r11.sh` and `run_r12.sh` are `./research-clone`,
  `./scratch` and `./raw-data`; the R10 list directory of `k11b.py` and `k12.py` is `$R10_LISTS` (default
  `./r10-lists`; when absent, as for the recorded outputs, the scripts use the per-epoch aggregates);
  usage examples name `$RAW` and `$REPLAYER`; two recorded run logs name `[research-root]`; a temporary path in a
  recorded fork log reads `$TMPDIR/vrf-proof`; example output directories in the controller read `./runs/i6`;
  the default code repository URL in the run scripts is `https://example.org/fairbind-code.git`.
* The header line of the three K13 gas logs (`measurement/docs/11_journal/K13/logs/*.log.gz`) names
  `[code repository] branch c1-anchor`; the logs were decompressed, edited in that line only and recompressed
  (`k13_tsv.py` rebuilds the same two tables from them).
* Two Unicode test values (a rejected non-ASCII JSON value and a rejected non-ASCII request path, in
  `runtime/dataworker/worker_test.go`, `adapters/httpcanon/canonical_test.go` and `test-vectors/canonicalization-v1.json`)
  were replaced by other non-ASCII strings; the tests still check that they are rejected.

## 2. Translation

Comments, docstrings, printed labels and table headings of the measurement scripts and of their recorded outputs were
written in the authors' working language. They were translated word by word with one fixed glossary, applied in the
same way to the scripts, their inputs and their recorded outputs, so that a rerun prints the same strings as the
recorded files (section 4). The English of these strings is therefore rough. No number, identifier, code path or
control flow was changed by the translation: line counts are unchanged, and the scripts that check source lines by
number still pass. Path components were renamed in the same pass:

| Original component (gloss) | Shipped name |
| --- | --- |
| journal edition (study folder) | `11_journal` |
| run evidence | `05_run-evidence` |
| design 2, median period | `design2`, `median-period` |
| results, check, logs | `results`, `check`, `logs`, `logs_b`, `logs_c`, `logs_d` |
| post hoc study folders | `P1_posthoc`, `P2_posthoc`, `P3_posthoc`, `P4_posthoc`, `P6_posthoc`, `P8_posthoc`, `P9_posthoc`, `P11_posthoc` |
| later calculations, replay, deterrence, out-of-window k | `C32`, `C34`, `W3_replay`, `C34_ASP-replay`, `W4_deterrence`, `W7_out-of-window-k` |
| fixed-delay replay, duty-cost share | `C35_fixed-delay-replay`, `C35_duty-cost-share` |
| fit conditions, deployed USDC | `P10_fit-conditions`, `P10u_real-USDC` |
| release units and their run logs | `release-units`, `run-logs`, `run-logs_anchor`, `run-logs_USDC` |
| gas studies | `G10_gas`, `G11_gas` |
| data review, loss re-implementation | `F/data-review`, `F/I4_loss-reimpl` |
| raw-data folder names expected by the replayer | `S1b_median-window`, `S1b_prior14_median-window`, `S1b_busy-window`, `S1c_busy-window-prior14` |

The R12 registered parameter block (`replay-inputs/R12_registration_block.md`) is the block of the original
registration with the same translations; `r12_compute.py` carries the same translated block, so
`check-registration` passes. The block file is new; the registration document itself is not included.

Edited files per directory:

| Directory | Files |
| --- | --- |
| `code/anchor-variants` | 3 |
| `code/judgment-formal` | 3 |
| `code/model-check` | 8 |
| `code/replay` | 12 |
| `code/settlement` | 127 |
| `data-manifests/decode_dune_results.py` | 1 |
| `measurement/docs/11_journal/BASE1` | 2 |
| `measurement/docs/11_journal/C32/W3_replay` | 4 |
| `measurement/docs/11_journal/C32/W4_deterrence` | 3 |
| `measurement/docs/11_journal/C32/W6_basefee` | 1 |
| `measurement/docs/11_journal/C32/W7_out-of-window-k` | 3 |
| `measurement/docs/11_journal/C34` | 3 |
| `measurement/docs/11_journal/C34_ASP-replay` | 1 |
| `measurement/docs/11_journal/C35_duty-cost-share` | 3 |
| `measurement/docs/11_journal/C35_fixed-delay-replay` | 2 |
| `measurement/docs/11_journal/D3` | 2 |
| `measurement/docs/11_journal/F/seller-tiers` | 1 |
| `measurement/docs/11_journal/K11` | 3 |
| `measurement/docs/11_journal/K12` | 2 |
| `measurement/docs/11_journal/K13` | 10 |
| `measurement/docs/11_journal/K14` | 5 |
| `measurement/docs/11_journal/P10_fit-conditions` | 3 |
| `measurement/docs/11_journal/P10u_real-USDC` | 3 |
| `measurement/docs/11_journal/P11_posthoc` | 5 |
| `measurement/docs/11_journal/P1_posthoc` | 4 |
| `measurement/docs/11_journal/P3_posthoc` | 6 |
| `measurement/docs/11_journal/P4_posthoc` | 2 |
| `measurement/docs/11_journal/P6_posthoc` | 3 |
| `measurement/docs/11_journal/P8_posthoc` | 1 |
| `measurement/docs/11_journal/P9_posthoc` | 5 |
| `measurement/docs/11_journal/R13` | 2 |
| `measurement/docs/11_journal/R14` | 1 |
| `measurement/docs/11_journal/VRF` | 1 |
| `measurement/docs/11_journal/WF1` | 2 |
| `measurement/docs/11_journal/release-units` | 9 |
| `measurement/docs/figures/fig_fit_redraw.py` | 1 |

## 3. Files left out and the edits that follow from it

Working records of the study (registration and settings documents, result and check write-ups, plans, the
manuscript) are not included; neither are the repository instruction file of the code repository, its contribution
guide and CI workflow, or the MC1 plan document. Scripts that print SHA-256 fingerprints of such files now print
`absent` for them (`k11b.py`, `k12.py`, `k13_cost.py`, `k13_cost_s1.py`; `p11.py` already skipped a missing file).
Tests that compared text in those documents or in the manuscript skip those comparisons when the files are absent
(`test_p9.py`: three source-line checks; `test_p11.py`: the independent-check document and the manuscript text).
`r14_compute.py` checks the SHA-256 of its inputs; the entry for the D3 registration document was removed, and the
registered hashes of four inputs that the edits above changed were set to the shipped files:

| Input of `r14_compute.py` | Original SHA-256 | Shipped SHA-256 |
| --- | --- | --- |
| `R13/r13_sim.py` | `6c02913d69462779fa86c1212867cc6d8b4a1a1aee662c5e7b29f89d68170d51` | `4bdb86c2c413ad678211ce7cd3b7ca5249d5ce2edf33468dc7c51c190564ad10` |
| `D3/out/d3_results.json` | `1e3560beacc2a6640fb57099863f1a5dbb5b7234ca20c3e34a3e24797b111a5e` | `0e0bc05f07fdee18abcfdbd3fb5b8957ec29d3da8ac5024d22eb46124dd04758` |
| `D3/d3_concentration.py` | `bbde56b4fb41bde894f1908eb5da38db63b12b1046feb489e0a9f399fe944e55` | `6647eeba321c0933ef756be03c49d5a0582a6d86a87bac2daeea667b85e352f0` |
| `P1_posthoc/results/p1_results.json` | `9040c71b217d42082bdbbda13d0f98d081c7fde9a755096ab1045475da469244` | `a085801c2954b9fb948ffac4a45fa2935bf4522d78517371e62820dec5bdab41` |

Hashes of the three K13 gas logs edited in section 1:

| K13 log | Original SHA-256 | Shipped SHA-256 |
| --- | --- | --- |
| `k13_gas_run1.log.gz` | `850ec66e754ddd461ea0c6d5747be3e5912bc15caf912f33b0ecbdff4667bd35` | `be95ca585bca712b0fc16e35d3eb6cb0af8ede5184ee0ba179e413d82e51faed` |
| `k13_gas_run2.log.gz` | `e7226bc2915fe07d402e38764b39514d06903ffe13a6c4eae9022a4d0da4a91c` | `12fddd027c83f1910b5afdc4ba41ff97afdd6d4423cbb9ef2748fabbde570ee8` |
| `k13_gas_run3.log.gz` | `0c744f16d24cebe047edefa4ac26369d16df6cccb7d82a32597fb6d66693bfc8` | `39e9d01b31862400f9aa6e60a4c074fe2cdeb33d4c6c63e74aedcfa5abb1345f` |

## 4. Later calculations (C32, C34, C35) and the seller tiers

The folders `C32/W3_replay`, `C32/W4_deterrence`, `C32/W6_basefee`, `C32/W7_out-of-window-k`, `C34` and
`C34_ASP-replay` were added after the first version of the bundle, with the inputs they read that were not yet in it
(`P2_posthoc/results/p2_c.json`, `P8_posthoc/results/p8.json`, and the prior-period day tables
`days_busy_prior14.csv.gz`, `days_median_prior14.csv.gz` of `data/processed/agg_2026-10-21`). They were edited in
the same way as the rest of the bundle:

* Comments, labels, table headings and recorded outputs were translated with the glossary of section 2, extended by
  35 words that occur only in these files; scripts and recorded outputs were translated alike, so a rerun prints the
  same tables.
* Absolute local paths in usage examples read `$RAW`, `$REPLAYER` and `$RAWDATA`.
* `w4.py`, `w7.py` and `c34.py` record the SHA-256 of their calculation documents, which are not included; they now
  record `absent` for a missing file (one expression each, line counts unchanged).
* The working documents of these calculations (calculation rules and result write-ups) are not included; the short
  `README.md` of each folder replaces them.
* `C32/W6_basefee/results/w6_stdout.txt` is new: the study kept the output of `w6.py` only in a working document, so
  the standard output of the source script was recorded for the bundle (a rerun of the shipped script gives the same
  bytes).
* The `SHA256SUMS.txt` files in `results/` list the hashes of the source outputs, as elsewhere in the bundle.
* `C35_fixed-delay-replay` and `C35_duty-cost-share` were added later in the same way: their scripts and recorded
  outputs were translated with the glossary (extended only by the two folder names), and usage examples read `$RAW` and
  `$REPLAYER`. Unlike the earlier folders, each ships its calculation rules as `calc-rules.md`, translated by hand
  from the study's document, with references to internal working documents and review records left out; the
  results write-up is replaced by the folder's `README.md`. Neither script fingerprints its rules document.
* `F/seller-tiers/seller_tiers.csv` is the study's seller tier table with its text columns (family, alternative
  tier, reason, evidence, confidence, basis) translated by hand; the numeric columns are unchanged. References to
  internal working documents in the evidence column were removed, and one third-party listing URL was replaced by
  the name of the service list it shows. `tier_shares.py`, `results/tier_shares.md` and the `README.md` were written
  for the bundle. The table is shipped at a new path, so the `absent` fingerprint lines of `k11b.py` and `k12.py`,
  which name the study path, are unchanged.

## 5. Regenerated and recorded outputs

`K11/k11b_output.md` and `K12/k12_output.md` were regenerated in the bundle after the edits, because several
scripts compare their own rerun of `k11b.py` with `k11b_output.md` byte for byte. They differ from the translated
recorded files only in the fingerprint lines (input hashes, `absent` for files left out). Every other output is the
recorded output with the translation of section 2. A rerun of the cost-model chain in the bundle (README,
section 3.5) reproduces every table and PNG figure byte for byte; JSON outputs differ only in the recorded script
fingerprints (and `p10.json` in `closed_form[*].b`, `Re`, which the recorded file predates).
