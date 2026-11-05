package dataworker

import (
	"context"
	"encoding/hex"
	"fmt"
	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

type references struct {
	rows  []Observation
	calls *int
	err   error
}

func (r references) Retrieve(context.Context, SourceSet, uint64) ([]Observation, error) {
	*r.calls++
	return r.rows, r.err
}
func fixture(t *testing.T) (Worker, verifier.Snapshot, verifier.Bundle, Policy, SourceSet, *int) {
	t.Helper()
	p := Policy{[]string{"a", "b"}, 2, 100, 2, map[string]Field{"price": {"USD", "1", "0", "0"}}}
	set := SourceSet{p.Sources}
	ph, e := ObjectHash(p)
	if e != nil {
		t.Fatal(e)
	}
	sh, _ := ObjectHash(set)
	keyraw, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	key, _ := protocol.ParseAddress(keyraw)
	s := verifier.Snapshot{ChainID: 31337, Contract: protocol.Address{1}, Buyer: protocol.Address{2}, SellerKey: key, SellerID: 7, ProfileID: 4, ClassID: 1, PredicateID: PolicyID, CanonID: protocol.Keccak256([]byte("fairbind/http-canon/v1")), SourceSetHash: sh, TolerancePolicyHash: ph, MaxRequestBytes: 65536, MaxResponseBytes: 65536, MaxClaimsBytes: 65536}
	claims, _ := CanonicalObject(map[string]any{"version": 1, "classId": 1, "predicateId": fmt.Sprintf("0x%x", PolicyID), "sourceSetHash": fmt.Sprintf("0x%x", sh), "tolerancePolicyHash": fmt.Sprintf("0x%x", ph)})
	s.ClaimsHash = protocol.Keccak256(claims)
	b := verifier.Bundle{Claims: claims, Response: []byte(`{"price":"100"}`), Request: verifier.CanonicalRequest{Method: []byte("GET"), Path: []byte("/")}, Preimage: verifier.Preimage{ReferenceTime: 100, SourceSetHash: sh, TolerancePolicyHash: ph}}
	s.RequestHash = verifier.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash, ResponseHash: protocol.ResponseHash(b.Response), ClaimsHash: s.ClaimsHash, PredicateCommitment: verifier.Commitment(1, b.Preimage)}
	sign(t, s, &b)
	calls := new(int)
	path, _ := filepath.Abs("../predicates/data_experiment.py")
	w := Worker{Python: "python3", Comparator: path, References: references{[]Observation{{"a", 100, map[string]string{"price": "100"}, map[string]string{"price": "USD"}}, {"b", 100, map[string]string{"price": "100"}, map[string]string{"price": "USD"}}}, calls, nil}}
	return w, s, b, p, set, calls
}
func sign(t *testing.T, s verifier.Snapshot, b *verifier.Bundle) {
	t.Helper()
	digest := protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)
	out, e := exec.Command("cast", "wallet", "sign", "--no-hash", "--private-key", "0x"+strings.Repeat("0", 63)+"1", fmt.Sprintf("0x%x", digest)).Output()
	if e != nil {
		t.Fatal("public-fixture signing unavailable", e)
	}
	sig, e := hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x"))
	if e != nil {
		t.Fatal(e)
	}
	b.Signature = sig
}
func TestAuthenticatedComparisonAndTampering(t *testing.T) {
	w, s, b, p, set, calls := fixture(t)
	r := w.Evaluate(context.Background(), s, b, p, set)
	if r.Verdict != "PASS" || *calls != 1 {
		t.Fatalf("%+v", r)
	}
	b.Response = []byte(`{"price":"102"}`)
	r = w.Evaluate(context.Background(), s, b, p, set)
	if r.Verdict != "INCONCLUSIVE" || *calls != 1 {
		t.Fatal("unauthenticated bytes reached comparison", r)
	}
	b.Receipt.ResponseHash = protocol.ResponseHash(b.Response)
	sign(t, s, &b)
	r = w.Evaluate(context.Background(), s, b, p, set)
	if r.Verdict != "FAIL" || *calls != 2 {
		t.Fatal(r)
	}
}
func TestMissingReferenceAndChangedPolicy(t *testing.T) {
	w, s, b, p, set, calls := fixture(t)
	p.MaxSkew++
	if r := w.Evaluate(context.Background(), s, b, p, set); r.Verdict != "INCONCLUSIVE" || *calls != 0 {
		t.Fatal(r)
	}
	p.MaxSkew--
	w.References = nil
	if r := w.Evaluate(context.Background(), s, b, p, set); r.Verdict != "INCONCLUSIVE" {
		t.Fatal(r)
	}
}
func TestNoAliasToNormativePredicate(t *testing.T) {
	w, s, b, p, set, calls := fixture(t)
	s.PredicateID = protocol.Bytes32{}
	if r := w.Evaluate(context.Background(), s, b, p, set); r.Verdict != "INCONCLUSIVE" || *calls != 0 {
		t.Fatal(r)
	}
	for _, v := range []any{map[string]any{"x": 1.5}, map[string]any{"x": true}, map[string]any{"x": "été"}, map[string]any{"x": "<"}, map[string]any{"x": uint64(1 << 53)}} {
		if _, e := CanonicalObject(v); e == nil {
			t.Fatal("unsupported canonical JSON")
		}
	}
}

func TestStrictComparisonResult(t *testing.T) {
	for _, raw := range []string{`{"verdict":"FAIL","verdict":"PASS"}`, `{"verdict":"PASS"} {}`, `{"unknown":true}`, `{"verdict":"PASS"}garbage`} {
		if _, e := decodeResult([]byte(raw)); e == nil {
			t.Fatal("accepted malformed comparison", raw)
		}
	}
}
