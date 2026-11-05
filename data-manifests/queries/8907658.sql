-- Dune query 8907658
-- name: FairBind S1-b per-date checksums v2 (facilitator 20, params d1 d2 t_after t_before)
-- parameters: d1=2026-07-24, d2=2026-07-24, t_after=2000-01-01 00:00:00
WITH fac(a, i) AS (VALUES
 (0x14fda13953fc30428938e6bf950d036e77214e52, 0),(0x2a89407a98a0732b7fd578c4e156b7166540eb5a, 1),(0x42dd53906b49c202e8e934b059dc019e04634b00, 2),(0x4c934c63c786157fefd990945b25ea60a0fb0205, 3),(0x59b7ebc67a3d627fabaf06768c818638452ae704, 4),
 (0x625d8a65134079f8faaac39a7947c73d93c6ac39, 5),(0x64cc42b1ce598e3abcfbb64df4688521ddbf1f0a, 6),(0x67b9ce703d9ce658d7c4ac3c289cea112fe662af, 7),(0x68a96f41ff1e9f2e7b591a931a4ad224e7c07863, 8),(0x68efafe862d89ce66dd3d7b07d5a3747a0871164, 9),
 (0x772003a2e9c2ccc8af956870a37a66f64f8cec38, 10),(0x8cda367232d78c067116e3260da881d2da8ffa39, 11),(0x8f5cb67b49555e614892b7233cfddebfb746e531, 12),(0x93f6601151ccb08f333ab4b1cccfb1e188c0be44, 13),(0x97acce27d5069544480bde0f04d9f47d7422a016, 14),
 (0xa32ccda98ba7529705a059bd2d213da8de10d101, 15),(0xb87e1a2cc2b4643f2892768e80e41167f17c5860, 16),(0xca5e87f82b3fa093800e6ad67d621a427d79c70d, 17),(0xe72f0af4cf41356d433723547f1412ca27fbb1b8, 18),(0xe74817f4cdc15844314812b2271276e64e890fae, 19))
SELECT cast(t.call_block_date as varchar) AS d, count(*) AS n, cast(sum(t.value) as varchar) AS sv,
  sum(t.call_block_number) AS s_bn, sum(t.call_tx_index) AS s_ti, sum(cast(to_unixtime(t.call_block_time) as bigint)) AS s_t,
  sum(bytearray_to_bigint(bytearray_substring(t.call_tx_hash, 1, 4))) AS s_h,
  sum(bytearray_to_bigint(bytearray_substring(t."to", 1, 4))) AS s_r,
  sum(bytearray_to_bigint(bytearray_substring(t."from", 1, 4))) AS s_p,
  sum(f.i) AS s_f, sum(cardinality(t.call_trace_address)) AS s_tr
FROM base_usdc_base.fiattokenv2_1_call_transferwithauthorization t JOIN fac f ON t.call_tx_from = f.a
WHERE t.call_block_date >= DATE '{{d1}}' AND t.call_block_date <= DATE '{{d2}}' AND t.call_success = true
  AND t.call_block_time > TIMESTAMP '{{t_after}} UTC' AND t.call_block_time <= TIMESTAMP '{{t_before}} UTC'
GROUP BY 1 ORDER BY 1
