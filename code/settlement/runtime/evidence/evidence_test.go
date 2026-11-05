package evidence

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
)

func vector(t *testing.T) (Envelope, string) {
	t.Helper()
	raw, err := os.ReadFile("../../test-vectors/predicate-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var v struct {
		Evidence struct {
			Value Envelope `json:"value"`
			Hash  string   `json:"canonicalHash"`
		} `json:"evidence"`
	}
	if err = json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	return v.Evidence.Value, v.Evidence.Hash
}

func TestNormativeEvidenceVector(t *testing.T) {
	e, want := vector(t)
	raw, hash, err := Build(e)
	if err != nil {
		t.Fatal(err)
	}
	if fmt.Sprintf("0x%x", hash) != want {
		t.Fatalf("hash %x != %s", hash, want)
	}
	decoded, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	again, _, err := Build(decoded)
	if err != nil || !bytes.Equal(raw, again) {
		t.Fatal("roundtrip changed evidence", err)
	}
}

func TestBothEvidenceClasses(t *testing.T) {
	e, _ := vector(t)
	h := "0x" + strings.Repeat("aB", 32)
	e.ClassID = 2
	e.Details = map[string]string{"kind": "open-weights-inference", "toplocCommitment": h, "reproducedCommitment": h, "modelHash": h, "configHash": h, "traceHash": h}
	for _, verdict := range []string{"PASS", "FAIL", "INCONCLUSIVE"} {
		e.Verdict = verdict
		raw, _, err := Build(e)
		if err != nil {
			t.Fatal(err)
		}
		out, err := Parse(raw)
		if err != nil || out.ClassID != 2 || out.Details["traceHash"] != h {
			t.Fatal("inference roundtrip", err)
		}
	}
	e.PredicateCommitment = "0x" + strings.Repeat("0", 64)
	if _, _, err := Build(e); err != nil {
		t.Fatal("schema-valid zero hash rejected", err)
	}
}

func TestRejectInvalidEnvelopes(t *testing.T) {
	cases := map[string]func(*Envelope){
		"version":        func(e *Envelope) { e.Version = 2 },
		"class":          func(e *Envelope) { e.ClassID = 3 },
		"class-details":  func(e *Envelope) { e.ClassID = 2 },
		"verdict":        func(e *Envelope) { e.Verdict = "READY" },
		"hash":           func(e *Envelope) { e.Nonce = "0xdead" },
		"time":           func(e *Envelope) { e.ObservedAt = "01" },
		"negative":       func(e *Envelope) { e.ObservedAt = "-1" },
		"reference-time": func(e *Envelope) { e.Details["referenceTime"] = "1e9" },
		"missing":        func(e *Envelope) { delete(e.Details, "comparisonHash") },
		"extra":          func(e *Envelope) { e.Details["extra"] = "x" },
		"substitute":     func(e *Envelope) { delete(e.Details, "comparisonHash"); e.Details["extra"] = "x" },
		"nil-details":    func(e *Envelope) { e.Details = nil },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			e, _ := vector(t)
			mutate(&e)
			if _, _, err := Build(e); err == nil {
				t.Fatal("accepted invalid evidence")
			}
		})
	}
}

func TestRejectNoncanonicalJSON(t *testing.T) {
	e, _ := vector(t)
	raw, _, err := Build(e)
	if err != nil {
		t.Fatal(err)
	}
	s := string(raw)
	cases := []string{
		s + "\n", " " + s, s + "{}",
		strings.Replace(s, `"version":1`, `"version":1,"version":1`, 1),
		strings.Replace(s, `"kind":"data-api"`, `"kind":"data-api","kind":"data-api"`, 1),
		strings.Replace(s, `"version":1`, `"version":1,"unknown":true`, 1),
		strings.Replace(s, `"verdict":"PASS"`, `"verdict":"\u0050ASS"`, 1),
		strings.Replace(s, `"version":1`, `"Version":1`, 1),
		strings.Replace(s, `"observedAt":"1725400010"`, `"observedAt":1725400010`, 1),
		strings.Replace(s, `"classId":1`, `"classId":1.0`, 1),
		strings.Replace(s, `"version":1`, `"version":null`, 1),
	}
	for i, bad := range cases {
		if _, err := Parse([]byte(bad)); err == nil {
			t.Fatalf("accepted mutation %d", i)
		}
	}
	if _, err := Parse(bytes.Repeat([]byte(" "), MaxEnvelopeBytes+1)); err == nil {
		t.Fatal("accepted oversized evidence")
	}
}
