# Open-weights execution binding

This package binds a model run to the receipt's class-specific commitment for
`OPEN_WEIGHTS_TOPLOC_V1` and checks it by re-execution. It is the comparison
step after the authenticated input gate (`runtime/verifier.Check`); it does not
poll a ledger, verify seller signatures, sign verdicts or store evidence.

| File | Role |
| --- | --- |
| `encoding.py` | Keccak-256, the narrow JCS subset, and the class-2 `predicateCommitment` encoding |
| `model.py` | local checkpoint loading, int8 weight rounding, greedy generation with activation capture, verifier prefill, synthetic checkpoint writer |
| `binding.py` | configuration manifest, seller `commit`/`serve`, verifier `verify` |
| `evaluate.py` | predicate pipeline after the gate: commitment opening, re-execution, comparison, evidence |
| `pipeline.go` | Go glue: `verifier.Check`, then `evaluate.py` as a subprocess |
| `binding_test.go` | checks that the Go gate opens the Python-built fixture in `testdata/` |

## Commitment

The seller runs greedy decoding without a KV cache and records the final hidden
state: the prefill block `[prompt_len, hidden]`, then one `[hidden]` row per decode
step. Rows are cast to bfloat16 and passed to TOPLOC `build_proofs_bytes` at the
revision pinned in `UPSTREAMS.lock.json`. Then:

```text
toplocCommitment    = keccak256(UTF8(JCS(trace)))
modelHash           = keccak256(UTF8(JCS(weightManifest)))
configHash          = keccak256(UTF8(JCS(config)))
predicateCommitment = keccak256(abi.encode(keccak256("fairbind/open-weights-commitment/v1"),
                                           toplocCommitment, modelHash, configHash))
```

Only the last line is normative (`docs/spec/predicate-interface-v1.md` section 4,
vector `test-vectors/predicate-v1.json`). The three object layouts are
experimental and carry their own format strings:

- `trace`: `fairbind/experimental/toploc-trace/v1`, with `topk`,
  `decodeBatchingSize`, `skipPrefill` and the proof blocks as hex strings.
- `weightManifest`: `fairbind/experimental/weight-manifest/v1`, the SHA-256 of
  every `.json`, `.safetensors`, `.model`, `.txt` and `.jinja` file in the model
  directory (weights, model config and tokenizer).
- `config`: `fairbind/experimental/open-weights-config/v1`, with tokenizer mode,
  prompt template, precision, quantization, batch size, decoding, kernel
  settings, runtime versions, accelerator class and the TOPLOC parameters and
  tolerance. Tolerances are decimal strings.

## Verifier decision

`verify` returns `PASS`, `FAIL` or `INCONCLUSIVE` with metrics, evidence
`details` in the `openWeightsDetails` shape, and a comparison record whose hash
is `traceHash`.

| Condition | Result |
| --- | --- |
| receipt commitment is zero | FAIL |
| preimage does not open the receipt commitment | INCONCLUSIVE |
| preimage `modelHash`/`configHash` differ from the authenticated claims | FAIL |
| preimage missing, trace missing, or trace does not hash to `toplocCommitment` | INCONCLUSIVE |
| configuration unavailable, noncanonical or unsupported; runtime versions or accelerator differ from the verifier | INCONCLUSIVE |
| verifier has no weights hashing to `modelHash` | INCONCLUSIVE |
| reproduced activations are within the committed tolerance | PASS |
| reproduced activations exceed the committed tolerance | FAIL |

A trace that fails to open its commitment is INCONCLUSIVE because the trace is
not itself covered by the seller signature here. If a later bundle format puts
the trace inside the signed response bytes, that case becomes a seller violation.

## Predicate pipeline

`Pipeline.Evaluate(ctx, bundle, profile) (Verdict, Evidence, error)` runs
`verifier.Check` first. A bundle the gate does not report `READY` or `FAIL`
returns `ErrNotJudged` and no subprocess is started. Otherwise it sends the
gate result, claims, preimage, receipt commitment and the request and response
bodies to `evaluate.py` (`evaluate(bundle, profile)`), with the configuration
manifests and local weight directories the operator holds, keyed by hash.
Python and script paths are operator configuration.

Bodies use experimental canonical layouts:

- request body `{"format":"fairbind/experimental/inference-request/v1","version":1,"promptIds":[...]}`
- response body `{"format":"fairbind/experimental/inference-response/v1","version":1,"outputIds":[...],"trace":"<canonical trace JSON>"}`

Because the trace is inside the seller-signed response, a signed response
without a trace, or with a trace that does not open `toplocCommitment`, is
`FAIL` here (the "later bundle format" case above). Gate `FAIL` and a zero
commitment are `FAIL` without re-execution. A missing configuration manifest,
missing weights or missing runtime is `INCONCLUSIVE`. Otherwise `binding.verify`
re-executes on CPU and applies the committed TOPLOC tolerance.

The evidence object (`fairbind/experimental/inference-evidence/v1`, canonical
JSON, Keccak-256 hash) contains `inputHash` (request body), `responseBodyHash`,
`modelHash`, `configHash`, `toplocCommitment`, `reproducedCommitment`,
`sellerOutputHash` and `reexecutedOutputHash` (keccak of `{"tokenIds":[...]}`;
the re-executed tokens are the greedy choices of the same prefill), the
comparison result (verdict, reason, metrics, record hash) and the comparison
record. The token comparison is recorded, not an extra decision rule. The Go
side checks canonical encoding, the hash, and that the evidence binds the
authenticated nonce, commitment, preimage and bodies.

## Synthetic model

Tests and the offline run use `write_synthetic_checkpoint`: a Llama-architecture
checkpoint with seeded random weights (hidden size 576, 9 heads, 3 KV heads,
intermediate size 1536 as in SmolLM2-135M; 4 layers and a 4096-token vocabulary
to keep tests fast). No tokenizer is included; requests are token IDs. It is used
because the test environment has no accelerator and no network path to a public
weight host. The checkpoint is written and loaded through the same
`from_pretrained`/`save_pretrained` code as a public model, so loading,
forward pass, activation capture, hashing and comparison are real. The model's
outputs are meaningless, and results on it say nothing about a trained model.

Observed on the synthetic checkpoint at the exact-repeat tolerance (0, 0, 0):
identical re-run PASS, different weights FAIL (all 16 top-k exponents differ),
int8 weight rounding FAIL (mantissa error mean about 0.9, generated tokens
unchanged), missing trace INCONCLUSIVE. Under the looser illustrative tolerance
(4, 8, 8) the int8 run passes and the swapped model still fails. Which
tolerance a real profile needs is a calibration question that these tests do
not answer.

## Tests

```sh
python3 -m unittest discover -s runtime/inference -p 'test_*.py' -v
go test ./runtime/inference
```

`make inference-check` runs both. `test_evaluate.py` and `pipeline_test.go`
cover PASS, FAIL (tampered output tokens signed by the seller), INCONCLUSIVE
(weights unavailable), zero commitment FAIL and gate-rejected bundles not
judged. The Go PASS/FAIL test writes a synthetic checkpoint through
`testdata/serve_synthetic.py` and is skipped without the pinned environment.

Binding tests need the environment in `experiments/requirements-toploc-cpu.txt`
plus TOPLOC installed from the pinned revision (see `runtime/predicates/README.md`);
without it they are skipped and only the encoding tests run.

`encoding.keccak256` pads inputs of length 135 mod 136 with the single byte
`0x81`, matching standard Keccak-256; `protocol.Keccak256` and
`scripts/check_spec.py` agree (fixed in 92e68b2). The known-answer test still
covers these lengths separately.

## Real run

`experiments/inference_binding_run.py` performs, for three fixed prompts: honest
serve and verify, missing trace, int8 rounding under an unquantized commitment,
and (with `--swap-model-dir`) a different checkpoint declared under the claimed
model hash. It records revisions, versions, weight manifests, configuration,
preimages, proofs, activation digests, metrics and timings in `manifest.json`.

Offline smoke run on the synthetic checkpoint (about 15 s on one CPU thread):

```sh
python3 experiments/inference_binding_run.py --synthetic-seed 11 --output /tmp/new-inference-run
```

Run for an 8B-class model:

1. Hardware: one NVIDIA GPU with 80 GB (A100 80GB or H100). The script keeps the
   claimed, int8-rounded and swapped models loaded at once in bfloat16, about
   16 GB each, plus activations for short prompts. A 40-48 GB GPU works when the
   swap case is run separately. Host memory of at least 64 GB for loading.
   Seller and verifier runs must use the same accelerator class; it is committed
   in `config.accelerator` as `cuda:<device name>`.
2. Environment: Python 3.12, `pip install -r experiments/requirements-toploc-cpu.txt`
   (the PyPI `torch==2.8.0` Linux wheel includes CUDA 12.8), then TOPLOC at the
   pinned revision with `pip install --no-build-isolation`.
3. Choose the model, add it to `UPSTREAMS.lock.json` with repository, revision and
   licence, and commit. Choose a swap model with the same tokenizer and
   architecture (for example the instruction-tuned variant of the same base).
4. Download only config, tokenizer and safetensors files at the locked revisions:
   `huggingface-cli download ORG/MODEL --revision REV --include '*.json' '*.safetensors' 'tokenizer*' --local-dir MODEL_DIR`,
   and likewise into `SWAP_DIR`.
5. From a clean checkout:
   `python experiments/inference_binding_run.py --model-dir MODEL_DIR --swap-model-dir SWAP_DIR --precision bfloat16 --max-new-tokens 16 --output NEW_DIRECTORY`.
   `CUBLAS_WORKSPACE_CONFIG=:4096:8` is set by the script for deterministic cuBLAS.
6. Expected on one machine: `exact_repeat` PASS, `missing_trace` INCONCLUSIVE,
   `int8_under_unquantized_claim` and `swapped_model` FAIL. A PASS for the int8
   case at zero tolerance means the rounding did not change any compared bfloat16
   value and must be reported, not rerun.

This run repeats execution on one machine. It does not measure cross-machine or
cross-GPU nondeterminism, false rejection or false acceptance rates; those set
the tolerance of a real profile.

## Not covered

- A normative definition of the trace, weight-manifest and configuration layouts.
- A decision rule on generated tokens: the greedy choice of the reproduced logits
  is recorded in evidence (`reexecutedOutputHash`) but does not change the verdict.
- Tolerance calibration, sampling-based decoding, batch sizes above one, KV-cache
  kernels and prompt templates.
- The declared TOPLOC revision is compared with the lock file, not with the
  installed build.
