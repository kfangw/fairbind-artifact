# C34: StableEnrich priced with the enclave-receipt proof call

Post hoc calculation; it has no registered decision rule. `c34.py` prices StableEnrich's proof call at the
36,440-gas enclave-receipt sketch (with its L1 fee, as BlockRun is priced) instead of the measured tier-1a call of
86,824 gas, and compares FairBind with full inspection (FI) in the three windows, for the lower, upper and
facilitator-gas estimates and for the same and own proof calls. It imports `P11_posthoc/p11.py` for its functions
and the measured-gas cost base V1u, and checks that the unchanged cells equal `P11_posthoc/results/p11.json` and the
cost table of the manuscript.

```sh
cd measurement/docs/11_journal/C34
python3 -I c34.py --out /tmp/c34      # 7 s
```

Recorded outputs: `results/c34.json`, `results/c34_tables.md`. The calculation document the script fingerprints
(`calc-rules.md`) is not included, and a rerun records `absent` for it.
