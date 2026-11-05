package verifier

import (
	"context"
	"errors"
	"fmt"
	"strconv"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/inference"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
)

// ImplementationFormat identifies the implementation object that every
// envelope's implementationHash references.
const ImplementationFormat = "fairbind/experimental/implementation/v1"

// FallbackFormat identifies the record stored for a predicate identifier that
// has no registered pipeline.
const FallbackFormat = "fairbind/experimental/unsupported-predicate/v1"

// PredicateRouter dispatches by the profile's predicate identifier. An
// identifier the gate accepts but no pipeline is registered for (for example
// the normative DATA_API_REFERENCE_V1, whose decision procedure is not
// implemented here) yields an INCONCLUSIVE envelope, or FAIL when the gate
// already proved a seller violation. The fallback stores its own record; the
// manifest objects its envelope references must already be in Objects, or
// Outbox.Prepare refuses the envelope and the assignment is retried.
type PredicateRouter struct {
	ByID     map[protocol.Bytes32]Predicate
	Objects  *evidence.Store
	Revision string
}

func (r PredicateRouter) Evaluate(ctx context.Context, a ledger.Assignment, b gate.Bundle, g gate.Result) (evidence.Envelope, error) {
	if p, ok := r.ByID[a.Snapshot.PredicateID]; ok {
		return p.Evaluate(ctx, a, b, g)
	}
	verdict, reason := "INCONCLUSIVE", "no pipeline for predicate"
	if g.Status == gate.Fail {
		verdict, reason = "FAIL", g.Reason
	}
	record, err := put(r.Objects, map[string]any{"format": FallbackFormat, "predicateId": hex32(a.Snapshot.PredicateID), "verdict": verdict, "reason": reason, "gate": g.Reason})
	if err != nil {
		return evidence.Envelope{}, err
	}
	impl, err := implementation(r.Objects, "services/verifier/fallback", r.Revision)
	if err != nil {
		return evidence.Envelope{}, err
	}
	env := baseEnvelope(a, b, verdict, impl)
	if a.Snapshot.ClassID == 1 {
		env.ObservedAt = strconv.FormatUint(b.Preimage.ReferenceTime, 10)
		env.Details = dataDetails(b, hex32(record), hex32(record))
	} else {
		env.Details = inferenceDetails(b, hex32(protocol.Bytes32{}), hex32(record))
	}
	return env, nil
}

// DataManifests are the operator's copies of the source set and tolerance
// policy for one profile. They are used only if they hash to the committed
// values.
type DataManifests struct {
	Policy  dataworker.Policy
	Sources dataworker.SourceSet
}

// DataPredicate runs the class-1 data pipeline and stores every object its
// envelope references: source set, tolerance policy, reference set (raw
// replay objects), comparison, the full evidence object and the
// implementation object.
type DataPredicate struct {
	Pipeline dataworker.Pipeline
	Profiles map[uint32]DataManifests
	Objects  *evidence.Store
	Revision string
}

func (d DataPredicate) Evaluate(ctx context.Context, a ledger.Assignment, b gate.Bundle, g gate.Result) (evidence.Envelope, error) {
	m, ok := d.Profiles[a.Snapshot.ProfileID]
	if !ok {
		return evidence.Envelope{}, fmt.Errorf("no data manifests for profile %d", a.Snapshot.ProfileID)
	}
	v, ev, err := d.Pipeline.Evaluate(ctx, b, dataworker.Profile{Snapshot: a.Snapshot, Policy: m.Policy, Sources: m.Sources})
	if err != nil {
		return evidence.Envelope{}, err
	}
	if g.Status == gate.Fail && v != dataworker.Fail {
		return evidence.Envelope{}, errors.New("gate FAIL must yield FAIL")
	}
	for _, obj := range []any{m.Sources, m.Policy, ev.References, ev.Comparison, ev} {
		if _, err = put(d.Objects, obj); err != nil {
			return evidence.Envelope{}, err
		}
	}
	impl, err := implementation(d.Objects, "runtime/dataworker", d.Revision)
	if err != nil {
		return evidence.Envelope{}, err
	}
	env := baseEnvelope(a, b, string(v), impl)
	env.ObservedAt = strconv.FormatUint(b.Preimage.ReferenceTime, 10)
	env.Details = dataDetails(b, ev.ReferenceSetHash, ev.ComparisonHash)
	return env, nil
}

// InferencePredicate runs the class-2 re-execution pipeline. traceHash in the
// envelope references the canonical inference evidence object.
type InferencePredicate struct {
	Pipeline inference.Pipeline
	Configs  map[protocol.Bytes32][]byte
	Models   map[protocol.Bytes32]string
	Objects  *evidence.Store
	Revision string
}

func (p InferencePredicate) Evaluate(ctx context.Context, a ledger.Assignment, b gate.Bundle, g gate.Result) (evidence.Envelope, error) {
	v, ev, err := p.Pipeline.Evaluate(ctx, b, inference.Profile{Snapshot: a.Snapshot, Configs: p.Configs, Models: p.Models})
	if err != nil {
		return evidence.Envelope{}, err
	}
	if g.Status == gate.Fail && v != inference.Fail {
		return evidence.Envelope{}, errors.New("gate FAIL must yield FAIL")
	}
	if _, err = p.Objects.Put(ev.Raw); err != nil {
		return evidence.Envelope{}, err
	}
	if c, ok := p.Configs[b.Preimage.ConfigHash]; ok && protocol.Keccak256(c) == b.Preimage.ConfigHash {
		if _, err = p.Objects.Put(c); err != nil {
			return evidence.Envelope{}, err
		}
	}
	impl, err := implementation(p.Objects, "runtime/inference", p.Revision)
	if err != nil {
		return evidence.Envelope{}, err
	}
	env := baseEnvelope(a, b, string(v), impl)
	env.Details = inferenceDetails(b, ev.ReproducedCommitment, hex32(ev.Hash))
	return env, nil
}

func put(store *evidence.Store, obj any) (protocol.Bytes32, error) {
	raw, err := dataworker.CanonicalObject(obj)
	if err != nil {
		return protocol.Bytes32{}, err
	}
	return store.Put(raw)
}

func implementation(store *evidence.Store, component, revision string) (protocol.Bytes32, error) {
	return put(store, map[string]any{"format": ImplementationFormat, "component": component, "revision": revision})
}

func baseEnvelope(a ledger.Assignment, b gate.Bundle, verdict string, impl protocol.Bytes32) evidence.Envelope {
	return evidence.Envelope{Version: 1, ClassID: int(a.Snapshot.ClassID), PredicateID: hex32(a.Snapshot.PredicateID), Nonce: hex32(a.Snapshot.Nonce),
		ResponseHash: hex32(b.Receipt.ResponseHash), PredicateCommitment: hex32(b.Receipt.PredicateCommitment), Verdict: verdict,
		ImplementationHash: hex32(impl), ObservedAt: strconv.FormatUint(b.Receipt.IssuedAt, 10)}
}

func dataDetails(b gate.Bundle, references, comparison string) map[string]string {
	return map[string]string{"kind": "data-api", "referenceTime": strconv.FormatUint(b.Preimage.ReferenceTime, 10),
		"sourceSetHash": hex32(b.Preimage.SourceSetHash), "tolerancePolicyHash": hex32(b.Preimage.TolerancePolicyHash),
		"referenceResponsesHash": references, "comparisonHash": comparison}
}

func inferenceDetails(b gate.Bundle, reproduced, trace string) map[string]string {
	return map[string]string{"kind": "open-weights-inference", "toplocCommitment": hex32(b.Preimage.ToplocCommitment),
		"reproducedCommitment": reproduced, "modelHash": hex32(b.Preimage.ModelHash), "configHash": hex32(b.Preimage.ConfigHash), "traceHash": trace}
}
