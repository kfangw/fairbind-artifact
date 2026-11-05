# C34: rolling reserve on the bond replay

Post hoc calculation; it has no registered decision rule. `c34_asp.py` applies the rolling reserve of the Agentic
Settlement Protocol (reserve share rho, settlement delay D, exposure cap E_max; arXiv 2609.02208v1, section 4.6 and
appendix E.3) to the sale lists of the R12 bond replay. For every grid cell (rho 5, 10, 20%; reserve horizon from
Delta_f to 30 days; the escrow example with D = 7 days) it computes the uncovered revenue at the end of the lag (worst
moment and time average), the money it locks and the sales its exposure cap refuses, and sets them against
FairBind's matched payout from `C32/W3_replay/results/`. It also reproduces the R12 history bond and unbonded rate
cap per seller.

```sh
cd measurement/docs/11_journal/C34_ASP-replay
python3 -I c34_asp.py --replayer ../../../../code/replay --lists $RAW/lists --out /tmp/asp
```

`$RAW/lists` holds the registered R12 sale lists (about 4.8 GB, written by `run_r12.sh` from the raw data of
README section 4; not included). Recorded outputs: `results/c34_asp.json`, `results/c34_sellers_<window>.csv`.
