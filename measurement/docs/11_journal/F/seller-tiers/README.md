# Seller tiers of the classified Base sellers

`seller_tiers.csv` is the tier assignment of the thirteen classified Base sellers, one row per seller and endpoint
family (17 rows; Exa, CoinStats and Bitrefill are split by value bin, `split_by_value_bucket` = `yes`). The
assignment is a judgment from each seller's documentation and public pages; no new data was collected for it.
Columns:

| Column | Content |
| --- | --- |
| `seller`, `address` | seller name and Base receiving address |
| `family`, `tier`, `alt_tier` | endpoint family, assigned tier (T0, T1a, T1b, T1c, T2, OUT) and an alternative reading |
| `reason`, `evidence`, `confidence`, `basis` | why, the documentation or listing used, confidence (low, medium, high), and what is documented versus judged |
| `<window>_sales`, `_usdc`, `_payers`, `_top1_payer_share` | per window: busy and median from source s1b (CDP settlements), quiet from source s1c (every facilitator); payer columns are empty for split rows |

The windows are busy 2026-06-09 to 06-29, median 2026-07-24 to 08-13 and quiet 2026-09-08 to 09-22. Three further
attributed sellers (Tavily, Allium, Browserbase) have no rows in any window and are not listed; proxyllm has rows in
the median and quiet windows only, Arkham in the median and quiet windows only.

`tier_shares.py` recomputes every row's sales and value from `../data-review/target_sellers_all_summary.csv` and
`../data-review/target_sellers_values.csv`, checks them against the CSV, and prints the tier shares with and without
BlockRun for the three windows:

```sh
cd measurement/docs/11_journal/F/seller-tiers
python3 -I tier_shares.py > /tmp/tier_shares.md      # under 1 s, exit status 0 when every row matches
```

Recorded output: `results/tier_shares.md`; a rerun gives the same bytes. The median-window columns are the tier
table of the article's supplement (3,415,086 sales and 129,841.73 USDC with BlockRun; 95,812 and 1,941.07 without).

The seller-level fingerprint lists of `K11/k11b.py` and `K12/k12.py` name the study's copy of this table under
another path and record `absent` for it; the table was added here, at a separate path, so that their recorded
outputs stay unchanged.
