// Package dataworker connects authenticated bundles to a local experimental
// comparison. Ledger and independent reference providers remain trusted adapters.
package dataworker

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
	"os/exec"
	"time"
)

var PolicyID = protocol.Bytes32(sha256.Sum256([]byte("fairbind/experimental/data-decimal-median/v1")))

type Field struct {
	Unit     string `json:"unit"`
	Absolute string `json:"absolute"`
	Relative string `json:"relative"`
	Spread   string `json:"reference_spread"`
}
type Policy struct {
	Sources       []string         `json:"source_ids"`
	Quorum        uint64           `json:"quorum"`
	ReferenceTime uint64           `json:"reference_time"`
	MaxSkew       uint64           `json:"max_skew"`
	Fields        map[string]Field `json:"fields"`
}
type SourceSet struct {
	Sources []string `json:"sources"`
}
type Observation struct {
	Source     string            `json:"source"`
	ObservedAt uint64            `json:"observed_at"`
	Values     map[string]string `json:"values"`
	Units      map[string]string `json:"units"`
}

// ReferenceProvider is trusted operator code, not a list or a validity flag from
// the seller. Implementations must authenticate each source and retain raw replay
// objects. Failure to retrieve any needed data must return an error.
type ReferenceProvider interface {
	Retrieve(context.Context, SourceSet, uint64) ([]Observation, error)
}
type Result struct {
	Verdict  string            `json:"verdict"`
	Reason   string            `json:"reason"`
	PolicyID string            `json:"policyId"`
	Sources  []string          `json:"sources"`
	Medians  map[string]string `json:"medians"`
}
type Worker struct {
	Signature          verifier.CastVerifier
	Python, Comparator string
	References         ReferenceProvider
}

// CanonicalObject supports only the experiment's ASCII keys/string values and
// nonnegative safe integers. It is not a general-purpose RFC 8785 serializer.
func CanonicalObject(value any) ([]byte, error) {
	raw, e := json.Marshal(value)
	if e != nil {
		return nil, e
	}
	var v any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if e = d.Decode(&v); e != nil {
		return nil, e
	}
	var check func(any) bool
	ascii := func(s string) bool {
		for _, r := range s {
			if r < 32 || r > 126 || r == '<' || r == '>' || r == '&' {
				return false
			}
		}
		return true
	}
	check = func(x any) bool {
		switch t := x.(type) {
		case map[string]any:
			for k, v := range t {
				if !ascii(k) || !check(v) {
					return false
				}
			}
		case []any:
			for _, v := range t {
				if !check(v) {
					return false
				}
			}
		case string:
			return ascii(t)
		case json.Number:
			n, e := t.Int64()
			return e == nil && n >= 0 && n < 1<<53
		default:
			return false
		}
		return true
	}
	if !check(v) {
		return nil, fmt.Errorf("unsupported experiment JSON")
	}
	return json.Marshal(v)
}
func ObjectHash(value any) (protocol.Bytes32, error) {
	b, e := CanonicalObject(value)
	if e != nil {
		return protocol.Bytes32{}, e
	}
	return protocol.Keccak256(b), nil
}
func (w Worker) Evaluate(ctx context.Context, s verifier.Snapshot, b verifier.Bundle, p Policy, set SourceSet) Result {
	inc := func(reason string) Result { return Result{Verdict: "INCONCLUSIVE", Reason: reason} }
	if s.ClassID != 1 || s.PredicateID != PolicyID {
		return inc("unsupported_experiment_profile")
	}
	gate := verifier.Check(ctx, s, b, w.Signature)
	if gate.Status != verifier.Ready {
		return Result{Verdict: string(gate.Status), Reason: gate.Reason}
	}
	ph, e := ObjectHash(p)
	if e != nil || ph != s.TolerancePolicyHash {
		return inc("policy_binding")
	}
	sh, e := ObjectHash(set)
	if e != nil || sh != s.SourceSetHash {
		return inc("source_set_binding")
	}
	if p.ReferenceTime != b.Preimage.ReferenceTime || len(p.Sources) == 0 || len(p.Sources) > 64 || len(p.Sources) != len(set.Sources) || len(p.Fields) == 0 || len(p.Fields) > 64 || p.Quorum == 0 || p.Quorum > uint64(len(p.Sources)) {
		return inc("policy_configuration")
	}
	seen := map[string]bool{}
	for i, id := range p.Sources {
		if id == "" || seen[id] || id != set.Sources[i] {
			return inc("source_set_policy_mismatch")
		}
		seen[id] = true
	}
	if w.References == nil {
		return inc("references_unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	obs, e := w.References.Retrieve(ctx, set, p.ReferenceTime)
	if e != nil || len(obs) > 64 {
		return inc("references_unavailable")
	}
	payload, e := json.Marshal(map[string]any{"policyId": fmt.Sprintf("0x%x", PolicyID), "policy": p, "responseBase64": b.Response, "observations": obs})
	if e != nil || len(payload) > 1048576 {
		return inc("comparison_input_limit")
	}
	if w.Python == "" || w.Comparator == "" {
		return inc("comparison_unavailable")
	}
	cmd := exec.CommandContext(ctx, w.Python, w.Comparator)
	cmd.Stdin = bytes.NewReader(payload)
	out, e := cmd.Output()
	if e != nil || len(out) > 1048576 {
		return inc("comparison_failed")
	}
	result, e := decodeResult(out)
	if e != nil || result.PolicyID != fmt.Sprintf("0x%x", PolicyID) || (result.Verdict != "PASS" && result.Verdict != "FAIL" && result.Verdict != "INCONCLUSIVE") {
		return inc("invalid_comparison_result")
	}
	return result
}

// The controlled Python codec emits sorted compact ASCII JSON plus one newline.
// Exact re-encoding rejects duplicate members and trailing content before decoding.
func decodeResult(raw []byte) (Result, error) {
	var result Result
	var value map[string]any
	if e := json.Unmarshal(raw, &value); e != nil {
		return result, e
	}
	canonical, e := json.Marshal(value)
	if e != nil || !bytes.Equal(bytes.TrimSpace(raw), canonical) {
		return result, fmt.Errorf("noncanonical result")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	e = d.Decode(&result)
	return result, e
}
