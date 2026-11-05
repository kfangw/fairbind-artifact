// Package evidence encodes the frozen v1 evidence envelope and retains immutable
// content-addressed objects. It neither authenticates their authors nor evaluates
// predicates; those checks belong to the verifier pipeline.
package evidence

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"

	"example.org/fairbind/protocol"
)

// MaxEnvelopeBytes bounds parsing independent of the selected profile, whose
// smaller maxEvidenceBytes must also be enforced by the caller.
const MaxEnvelopeBytes = 1 << 20

type Envelope struct {
	Version             int               `json:"version"`
	ClassID             int               `json:"classId"`
	PredicateID         string            `json:"predicateId"`
	Nonce               string            `json:"nonce"`
	ResponseHash        string            `json:"responseHash"`
	PredicateCommitment string            `json:"predicateCommitment"`
	Verdict             string            `json:"verdict"`
	ImplementationHash  string            `json:"implementationHash"`
	ObservedAt          string            `json:"observedAt"`
	Details             map[string]string `json:"details"`
}

var uintString = regexp.MustCompile(`^(0|[1-9][0-9]*)$`)

func hashString(s string) bool {
	if len(s) != 66 || s[:2] != "0x" {
		return false
	}
	_, err := hex.DecodeString(s[2:])
	return err == nil
}

func validate(e Envelope) error {
	if e.Version != 1 || (e.ClassID != 1 && e.ClassID != 2) {
		return fmt.Errorf("unsupported evidence version or class")
	}
	if e.Verdict != "PASS" && e.Verdict != "FAIL" && e.Verdict != "INCONCLUSIVE" {
		return fmt.Errorf("invalid verdict")
	}
	for _, s := range []string{e.PredicateID, e.Nonce, e.ResponseHash, e.PredicateCommitment, e.ImplementationHash} {
		if !hashString(s) {
			return fmt.Errorf("invalid envelope bytes32")
		}
	}
	if !uintString.MatchString(e.ObservedAt) {
		return fmt.Errorf("invalid observedAt")
	}
	var fields []string
	if e.ClassID == 1 {
		if e.Details["kind"] != "data-api" || !uintString.MatchString(e.Details["referenceTime"]) {
			return fmt.Errorf("invalid data-api details")
		}
		fields = []string{"sourceSetHash", "tolerancePolicyHash", "referenceResponsesHash", "comparisonHash"}
		if len(e.Details) != 6 {
			return fmt.Errorf("unexpected data-api fields")
		}
	} else {
		if e.Details["kind"] != "open-weights-inference" {
			return fmt.Errorf("invalid inference details")
		}
		fields = []string{"toplocCommitment", "reproducedCommitment", "modelHash", "configHash", "traceHash"}
		if len(e.Details) != 6 {
			return fmt.Errorf("unexpected inference fields")
		}
	}
	for _, field := range fields {
		if !hashString(e.Details[field]) {
			return fmt.Errorf("invalid details field %s", field)
		}
	}
	return nil
}

// Build returns exact JCS bytes and their Keccak-256 hash. The closed schema
// contains only ASCII strings and small fixed integers, so sorted encoding/json
// maps implement its JCS subset exactly. Hash spelling (including hex case) is
// preserved, as required for a commitment to exact JSON bytes. Zero hashes are
// schema-valid; their semantic availability is checked by the predicate gate.
func Build(e Envelope) ([]byte, protocol.Bytes32, error) {
	var zero protocol.Bytes32
	if err := validate(e); err != nil {
		return nil, zero, err
	}
	m := map[string]any{"version": e.Version, "classId": e.ClassID, "predicateId": e.PredicateID, "nonce": e.Nonce, "responseHash": e.ResponseHash, "predicateCommitment": e.PredicateCommitment, "verdict": e.Verdict, "implementationHash": e.ImplementationHash, "observedAt": e.ObservedAt, "details": e.Details}
	raw, err := json.Marshal(m)
	if err != nil {
		return nil, zero, err
	}
	if len(raw) > MaxEnvelopeBytes {
		return nil, zero, fmt.Errorf("evidence exceeds local envelope limit")
	}
	return raw, protocol.Keccak256(raw), nil
}

// Parse accepts only exact canonical bytes: duplicate or unknown members,
// insignificant whitespace, alternative escapes and trailing input are rejected.
func Parse(raw []byte) (Envelope, error) {
	var e Envelope
	if len(raw) > MaxEnvelopeBytes {
		return e, fmt.Errorf("evidence exceeds local envelope limit")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if err := d.Decode(&e); err != nil {
		return Envelope{}, err
	}
	canonical, _, err := Build(e)
	if err != nil {
		return Envelope{}, err
	}
	if !bytes.Equal(raw, canonical) {
		return Envelope{}, fmt.Errorf("noncanonical evidence")
	}
	return e, nil
}
