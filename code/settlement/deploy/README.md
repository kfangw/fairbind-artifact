# Deployment

Deployment material will cover a one-command local network and a public testnet
profile. Every experiment deployment records the fields in
[`../schemas/deployment-manifest-v1.schema.json`](../schemas/deployment-manifest-v1.schema.json).
No mainnet deployment belongs in the repository until contract review,
invariant testing, and testnet acceptance are complete.

## Local network

```sh
forge build                                   # artifacts in out/
make deploy-local                             # or: scripts/deploy-local.sh [PROFILE_DOCUMENT] [RUN_DIR]
make deploy-local PROFILE=path/to/derived.json RUN_DIR=/tmp/run1
```

`scripts/deploy-local.sh` starts Anvil on `FAIRBIND_ANVIL_PORT` (default 8545)
and leaves it running (its pid is in `RUN_DIR/anvil.pid`), or attaches to the
loopback Anvil named by `FAIRBIND_RPC_URL`. The Anvil must use the default test
mnemonic. The script then:

1. checks the router ABI and storage layout of the artifacts against
   `test-vectors/deployment` (`scripts/check_modules.py`);
2. deploys the mock EIP-3009 token, the nine modules and the router
   (`scripts/local_deploy.py --rpc-url`), and checks that the deployed code
   equals the artifacts. The production build is the default;
   `FAIRBIND_ADMISSION_OVERRIDE=1`, or `"admissionOverride": true` in the
   profile document, deploys the test build
   `contracts/test/AdmissionOverrideRegistry.sol`;
3. mines up to the largest `epochOrigin`, then creates one deadline
   configuration (with the profile's id) and one service profile per entry of
   the profile document, with `parameterHash` recomputed as keccak256 of the
   canonical JSON of `parameters`; a document whose recorded hash differs is
   reported in `deployment.json` (`parameterHashRecomputed`);
4. registers verifiers (`FAIRBIND_VERIFIERS`, default the largest
   `minVerifiers` of the document, 14 for `local-evaluation-v1.json`: a profile
   is unavailable, and no seller can register, with fewer, so a smaller
   `FAIRBIND_VERIFIERS` is refused; admission requires `minVerifiers >= 3 *
   maxAssignments + 5`, ADR 0023), checkpoints the
   verifier tree and activates each profile;
5. registers a bond account of one `sellerPenalty` and one seller under the
   first data-api profile, with a claims document in the canonical form the
   verifier gate accepts;
6. mints tokens to both buyers and approves the contract for their dispute
   deposits (the buyer service sends no approvals);
7. writes the run directory.

| File in `RUN_DIR` | Content |
| --- | --- |
| `deploy-report.json` | `local_deploy.py` report: revision, dirty flag, tool versions, per-contract gas and code hashes |
| `deployment.json` | chain id, RPC URL, router, token, modules, profiles (ids, hashes), bond, seller, verifiers, the address and private key of each role, service configuration paths and URLs |
| `manifest.json` | the fields of `deployment-manifest-v1` |
| `services/keeper/keeper.json` | keeper configuration and state file |
| `services/facilitator/facilitator.json` | facilitator configuration |
| `services/seller/seller.json`, `claims.json`, `quote.json`, `seller.key` | seller configuration, registered claims, resource body, receipt key |
| `services/buyer/`, `services/buyer2/` | two buyer configurations and keys |
| `services/verifier/<id>/verifier.json` | one configuration and keystore per registered verifier (password in `services/verifier/password`) |
| `services/verifier/data/policy.json`, `sources.json` | tolerance policy and source set of the data predicate, shared by every verifier |

Every key is an Anvil default test key from the mnemonic
`test test test test test test test test test test test junk`:

| Index | Role |
| --- | --- |
| 0 | governance and deployer |
| 1 | guardian |
| 2 | penalty treasury |
| 3 | verifier reward pool |
| 4 | facilitator |
| 5 | keeper |
| 6 | seller owner and receipt signer |
| 7 | buyer |
| 8 | verifier owner and verdict relay |
| 9 | second buyer |
| 10 and up | verifier signing keys |

### Predicates in the local run

For a data-api seller the claims commit to the canonical hashes of
`services/verifier/data/sources.json` (the two ticker sources of the synthetic
replay fixtures in `runtime/dataworker/testdata/refsource/replay`) and
`policy.json` (quorum 2, reference time 1790000000, the fixtures' time, a
`max_skew` of 30 s, and a price tolerance of 5 + 0.001 times the median, with a
reference spread of 50). The seller's route preimage uses the same reference
time. Every verifier configuration registers the data pipeline with the replay
provider over the fixture directory, so judging needs no network. The seller
serves `quote.json` = `{"price":"64230.68","symbol":"BTC-USD"}`: the fixtures
give Coinbase 64231.57 and Kraken 64229.8, median 64230.685, bound about 69.2,
so the data pipeline judges it PASS. The pipeline runs only for profiles whose
`predicateId` is the experimental decimal-median predicate
(`0x1a320b64...f3ddd7`); `local-evaluation-v1.json` keeps the normative
`DATA_API_REFERENCE_V1`, which the verifiers answer with an INCONCLUSIVE
envelope. The integration test of the normal path derives a profile with the
experimental predicate.

The inference predicate is off unless `FAIRBIND_INFERENCE_MODEL_DIR` names a
local checkpoint directory; `FAIRBIND_INFERENCE_CONFIG_DIR` then names the
configuration manifests (default: the model directory). See
`services/verifier/README.md` for the configuration fields.

Service listeners use loopback ports from `FAIRBIND_BASE_PORT` (default
18400): facilitator, seller, buyer, second buyer. `local_deploy.py` refuses a
dirty tree unless `FAIRBIND_ALLOW_DIRTY=1`, which is recorded in the reports.

A started Anvil runs with `--prune-history 256`: mining the 60,000-block
deferral and claim windows of the local-evaluation profile otherwise writes
several gigabytes of state snapshots under `~/.foundry/anvil/tmp`.
`FAIRBIND_ANVIL` selects the Anvil binary. With Anvil 1.7.1 the time
`anvil_mine` spends per block grows with the chain length (about 20 seconds per
2,000 blocks at height 10,000), so mining one such window takes about half an
hour; Anvil 1.5.1 mines 60,000 blocks in about 80 seconds.

## Evaluation-setting deployment

The evaluation setting deployment installs the extension modules and calls
`requireExchangeTerms()` (governance, once) before it activates any profile,
so that no profile, and in particular no vote profile, activates without
exchange terms (ADR 0037). Each vote profile it runs has `setExchangeTerms`
called first, with receipt signatures unless the profile is the optional
signature-free one. Activation of a profile with exchange terms also needs
the chain's `GasPriceOracle.getL1FeeUpperBound` (OP Stack Fjord or later) to
answer. The local deployment above runs the base rules and does
not set this; neither do the existing tests.

`contracts/script/DeployEvalSetting.s.sol` is that deployment: the router,
its ten modules, the seven extension modules, the request-based source
(`FairBindVrf`, D_V = 10, T_V = 20), `requireExchangeTerms()`, and two
profiles with the timing of `data-api-design2-v1`: profile 5, the default
vote profile (batched, receipt signatures, F_max = 30,008) and profile 7, a
proof profile of the UNIQUE kind (T_p = 300, F_max = 1,911), with fourteen
verifiers checkpointed for both. Exchange-term prices and gas bounds are
placeholders until measured.

```sh
forge build
forge script contracts/script/DeployEvalSetting.s.sol -vv       # in-process chain 31337, test mocks
FAIRBIND_RPC_URL=... FAIRBIND_DEPLOYER_KEY=... FAIRBIND_TOKEN=... \
FAIRBIND_VRF_VERIFIER=... FAIRBIND_VRF_PUBLIC_KEY=0x... FAIRBIND_PRICE_VERIFIER=... \
FAIRBIND_FEED_ID=0x... FAIRBIND_GUARDIAN=... FAIRBIND_TREASURY=... FAIRBIND_REWARD_POOL=... \
FAIRBIND_VERIFIER_SIGNER_0=... (through _13) \
forge script contracts/script/DeployEvalSetting.s.sol --rpc-url "$FAIRBIND_RPC_URL" --broadcast
```

On chain 31337 a missing variable falls back to a test mock or a default test
key, and the L1 fee oracle is etched at its predeploy, which only an
in-process run can do; on any other chain every variable is required and the
chain must serve `GasPriceOracle.getL1FeeUpperBound`.

## Integration tests

`make integration-check` runs `services/internal/integration` with
`FAIRBIND_INTEGRATION=1`. Each test deploys with `scripts/deploy-local.sh` on
its own Anvil (`--slots-in-an-epoch 1`, so the finalized block is two blocks
behind the head), starts the keeper, every verifier, the facilitator, the
seller and the buyer as subprocesses, and asserts each transition on chain and
in the services' state files. Without the variable, `go test ./...` skips
them.

- `TestNormalPathSampledPass` uses the data-api profile with `samplePpm` set to
  1,000,000, so the purchase is always sampled, `recheckPpm` set to 0, so a
  PASS is not rechecked, and `predicateId` set to the experimental
  decimal-median predicate, so the verifier's data pipeline judges the seller's
  quote against the replay fixtures; all three are admitted by the production
  registry. It
  runs purchase, receipt, anchor, inclusion proof, seal, `openSample`,
  assignment, the verifier's redelivery and verdict, the appeal window, the
  deferral and the keeper's release.
- `TestNonDeliveryUnservedRefundAndForfeit` uses the unmodified profile. A
  second buyer receives purchase A and stops; a proxy withholds the response
  to purchase B and the seller stops. The buyer opens a `NON_DELIVERY` case,
  the serve deadline passes (`UNSERVED`), the buyer is refunded, the bond
  account is frozen with an open claim window, the missed anchor fails the
  epoch (a second confirmed failure, which moves the frozen window to its
  block and extends the claim window, ADR 0021), and after the window the
  keeper forfeits A, split by `forfeitVerifierPpm` between the verifier
  reward pool and the treasury; each of the two failures deducts one share of
  the seller penalty.
