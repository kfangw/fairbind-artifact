.PHONY: check spec-check go-check solidity-check collector-check module-check predicate-check inference-check analysis-check controller-check deploy-local integration-check

SPEC_FILES := \
	docs/spec/README.md \
	docs/spec/fairbind-v1.md \
	docs/spec/canonicalization-v1.md \
	docs/spec/cryptography-v1.md \
	docs/spec/merkle-v1.md \
	docs/spec/contract-interface-v1.md \
	docs/spec/lifecycle-v1.md \
	docs/spec/predicate-interface-v1.md \
	docs/spec/sortition-v1.md \
	docs/spec/profile-v1.md \
	docs/spec/governance-v1.md \
	docs/spec/x402-v2-integration.md \
	docs/spec/traceability.md \
	docs/architecture.md \
	docs/threat-model.md \
	docs/implementation-plan.md \
	UPSTREAMS.lock.json \
	schemas/fairbind-extension-v1.schema.json \
	schemas/fairbind-settlement-v1.schema.json \
	schemas/fairbind-receipt-v1.schema.json \
	schemas/fairbind-evidence-v1.schema.json \
	schemas/fairbind-claims-v1.schema.json \
	schemas/fairbind-serve-bundle-v1.schema.json \
	schemas/service-profiles-v1.schema.json \
	schemas/epoch-publication-v1.schema.json \
	schemas/deployment-manifest-v1.schema.json

check: spec-check go-check solidity-check collector-check module-check predicate-check inference-check analysis-check controller-check

spec-check:
	@for file in $(SPEC_FILES); do test -s "$$file"; done
	@find schemas profiles test-vectors -type f -name '*.json' -exec python3 -m json.tool {} \; >/dev/null
	python3 scripts/check_spec.py

go-check:
	go test ./...

solidity-check:
	forge test --threads 1

collector-check:
	python3 -m unittest discover -s experiments -p "test_collect_public.py" -v
	python3 -m unittest discover -s experiments/c1collect -p "test_*.py" -v

module-check: solidity-check
	python3 scripts/check_modules.py

predicate-check:
	python3 -m unittest discover -s runtime/predicates -p "test_*.py" -v

inference-check:
	python3 -m unittest discover -s runtime/inference -p "test_*.py" -v
	go test -count=1 -v ./runtime/inference

analysis-check:
	python3 -m unittest discover -s experiments -p "test_analysis.py" -v
	python3 -m unittest discover -s experiments/replay -p "test_*.py" -v
	python3 -m unittest discover -s experiments -p "test_verifier_count.py" -v
	python3 -m unittest discover -s experiments -p "test_case_paths.py" -v

controller-check:
	python3 -m unittest discover -s experiments -p "test_controller.py" -v

# Local deployment: starts Anvil (or attaches to FAIRBIND_RPC_URL) and writes a run
# directory with deployment.json and service configurations. See deploy/README.md.
PROFILE ?= profiles/local-evaluation-v1.json
RUN_DIR ?=
deploy-local:
	scripts/deploy-local.sh $(PROFILE) $(RUN_DIR)

# Six-process tests against Anvil (services/internal/integration). Not part of check.
integration-check:
	FAIRBIND_INTEGRATION=1 go test -count=1 -v -timeout 60m ./services/internal/integration/

# Settlement replay tests (conditions, bucket arithmetic, injection, input checks, decision rules);
# no chain needed.
.PHONY: replay-check
check: replay-check
replay-check:
	python3 -m unittest discover -s experiments/replay -p "test_*.py" -v

# Hold-period harness (I6) tests: every test_i6_*.py under experiments (packages included) and scripts.
.PHONY: i6-check
check: i6-check
i6-check:
	python3 -m unittest discover -s experiments -p "test_i6_*.py" -v
	@if ls scripts/test_i6_*.py >/dev/null 2>&1; then python3 -m unittest discover -s scripts -p "test_i6_*.py" -v; fi

# End-to-end I6 harness runs on Anvil 1.5.1 (FAIRBIND_ANVIL_151): minutes to an hour of wall time,
# so not part of `check`. I6_INTEGRATION_OUT must lie outside the repository; I6_INTEGRATION_ARGS
# passes --only, --parallel, --port-base or --allow-dirty.
.PHONY: i6-integration-check
i6-integration-check:
	@test -n "$(I6_INTEGRATION_OUT)" || { echo "set I6_INTEGRATION_OUT to a directory outside the repository" >&2; exit 2; }
	python3 experiments/controller/i6_integration.py --output "$(I6_INTEGRATION_OUT)" $(I6_INTEGRATION_ARGS)
