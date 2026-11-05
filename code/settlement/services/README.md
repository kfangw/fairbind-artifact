# Services

Separate Go processes for the FairBind roles. Shared wire and cryptographic
logic belongs in `protocol/`; x402-specific translation belongs in
`adapters/` and, for the service processes, `services/internal/x402`.

| Directory | Process |
| --- | --- |
| `seller/` | resource server: 402 offers, receipts, retention, epoch anchors, serve and publication |
| `buyer/` | buyer: authorizations, receipts, inclusion proofs, disputes, refunds |
| `facilitator/` | x402 facilitator calling FairBind `settle` idempotently |
| `internal/x402/` | shared wire types, digests, receipt trees, serve bundles |
| `internal/x402/chain/` | contract interface, JSON-RPC client, in-memory fake |
| `internal/x402/ethkey/` | secp256k1 digest signing and recovery |
| `internal/x402/fsstore/` | crash-safe JSON record store |
| `verifier/` | assigned verifier: redelivery, gate, predicate, signed verdict through the outbox |
| `keeper/` | public executor calling deadline transitions from the finalized ledger |
| `internal/e2e/` | tests that run the three services together on the fake chain |
| `internal/integration/` | tests that run all service binaries against Anvil (`make integration-check`, see `deploy/README.md`) |
| `internal/directive/` | scenario directive files: the worst-path and keeper delay blocks each role carries out |
| `internal/casepath/`, `casepath/cmd/` | per-case path columns (`case_path_blocks`, `keeper_delay_sum_blocks`, `case_path_minus_keeper`, `worst_path_case_blocks`) from the chain and the keeper log |

Each service keeps its state in JSON files under its data directory and
resumes from them after a restart; each README documents its file layout.
