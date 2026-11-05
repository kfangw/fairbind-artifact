package dataworker_test

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/verifier"
)

const refTime = 1790000000

var (
	coinbaseID = refsource.CoinbaseTicker{Product: "BTC-USD"}.ID()
	krakenID   = refsource.KrakenTicker{Pair: "XBTUSD"}.ID()
	synthetic  = refsource.VerifyOptions{AllowSynthetic: true}
)

// counting wraps a ReplaySource and counts collections, so tests can show that
// a bundle rejected by the gate never reaches reference retrieval.
type counting struct {
	inner dataworker.ReplaySource
	calls *int
}

func (c counting) Collect(ctx context.Context, set dataworker.SourceSet, t uint64) (dataworker.Collection, error) {
	*c.calls++
	return c.inner.Collect(ctx, set, t)
}

type fixture struct {
	pipe  dataworker.Pipeline
	prof  dataworker.Profile
	b     verifier.Bundle
	calls *int
}

func testPolicy() dataworker.Policy {
	return dataworker.Policy{
		Sources: []string{coinbaseID, krakenID}, Quorum: 2, ReferenceTime: refTime, MaxSkew: 30,
		Fields: map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "5", Relative: "0.001", Spread: "50"}},
	}
}

func loadReplay(t *testing.T, drop string) refsource.Replay {
	t.Helper()
	r, err := refsource.LoadReplay("testdata/refsource/replay", synthetic)
	if err != nil {
		t.Fatal(err)
	}
	var kept []*refsource.RawObject
	for _, o := range r.Objects {
		if o.SourceID != drop {
			kept = append(kept, o)
		}
	}
	r.Objects = kept
	return r
}

func signReceipt(t *testing.T, s verifier.Snapshot, b *verifier.Bundle) {
	t.Helper()
	digest := protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)
	out, err := exec.Command("cast", "wallet", "sign", "--no-hash", "--private-key", "0x"+strings.Repeat("0", 63)+"1", fmt.Sprintf("0x%x", digest)).Output()
	if err != nil {
		t.Fatal("public-fixture signing unavailable: ", err)
	}
	if b.Signature, err = hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x")); err != nil {
		t.Fatal(err)
	}
}

// newFixture builds a signed class-1 bundle bound to the replay fixture policy.
func newFixture(t *testing.T, response string, drop string) fixture {
	t.Helper()
	p := testPolicy()
	set := dataworker.SourceSet{Sources: p.Sources}
	ph, err := dataworker.ObjectHash(p)
	if err != nil {
		t.Fatal(err)
	}
	sh, _ := dataworker.ObjectHash(set)
	keyraw, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	key, _ := protocol.ParseAddress(keyraw)
	s := verifier.Snapshot{ChainID: 31337, Contract: protocol.Address{1}, Buyer: protocol.Address{2}, SellerKey: key, SellerID: 7, ProfileID: 4, ClassID: 1,
		PredicateID: dataworker.PolicyID, CanonID: protocol.Keccak256([]byte("fairbind/http-canon/v1")), SourceSetHash: sh, TolerancePolicyHash: ph,
		MaxRequestBytes: 65536, MaxResponseBytes: 65536, MaxClaimsBytes: 65536}
	claims, _ := dataworker.CanonicalObject(map[string]any{"version": 1, "classId": 1, "predicateId": fmt.Sprintf("0x%x", dataworker.PolicyID), "sourceSetHash": fmt.Sprintf("0x%x", sh), "tolerancePolicyHash": fmt.Sprintf("0x%x", ph)})
	s.ClaimsHash = protocol.Keccak256(claims)
	b := verifier.Bundle{Key: protocol.Bytes16{5}, Claims: claims, Response: []byte(response),
		Request:  verifier.CanonicalRequest{Method: []byte("GET"), Path: []byte("/v1/price"), Query: []byte("pair=BTC-USD")},
		Preimage: verifier.Preimage{ReferenceTime: refTime, SourceSetHash: sh, TolerancePolicyHash: ph}}
	s.RequestHash = verifier.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash,
		ResponseHash: protocol.ResponseHash(b.Response), ClaimsHash: s.ClaimsHash, PredicateCommitment: verifier.Commitment(1, b.Preimage), IssuedAt: refTime}
	signReceipt(t, s, &b)
	calls := new(int)
	provider := refsource.Provider{Registry: refsource.DefaultRegistry(), Retriever: loadReplay(t, drop), Verify: synthetic}
	pipe := dataworker.Pipeline{References: counting{provider, calls}, Decoder: refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: synthetic}}
	return fixture{pipe: pipe, prof: dataworker.Profile{Snapshot: s, Policy: p, Sources: set}, b: b, calls: calls}
}

func (f fixture) run(t *testing.T) (dataworker.Verdict, dataworker.Evidence) {
	t.Helper()
	v, ev, err := f.pipe.Evaluate(context.Background(), f.b, f.prof)
	if err != nil {
		t.Fatal(err)
	}
	if string(v) != ev.Verdict || ev.Comparison.Verdict != ev.Verdict {
		t.Fatalf("verdict %s disagrees with evidence %+v", v, ev)
	}
	return v, ev
}

func TestPipelinePassKeepsReplayObjects(t *testing.T) {
	f := newFixture(t, `{"price":"64230.10"}`, "")
	v, ev := f.run(t)
	if v != dataworker.Pass || *f.calls != 1 {
		t.Fatalf("%s %+v", v, ev.Comparison)
	}
	if ev.PolicyID != fmt.Sprintf("0x%x", dataworker.PolicyID) || ev.TolerancePolicyHash != fmt.Sprintf("0x%x", f.prof.Snapshot.TolerancePolicyHash) {
		t.Fatal("policy identifiers missing from evidence")
	}
	// Median of 64231.57 and 64229.8, written as an exact decimal.
	if ev.Comparison.Medians["price"] != "64230.685" || strings.Join(ev.Comparison.Sources, ",") != coinbaseID+","+krakenID {
		t.Fatalf("%+v", ev.Comparison)
	}
	if len(ev.References.Objects) != 2 || len(ev.References.Unavailable) != 0 {
		t.Fatalf("%+v", ev.References)
	}
	for _, o := range ev.References.Objects {
		raw, err := refsource.Decode(o.Raw)
		if err != nil || raw.SourceID != o.Source || !raw.Capture.Synthetic {
			t.Fatal("evidence does not carry the raw replay object", err)
		}
	}
	rh, _ := dataworker.ObjectHash(ev.References)
	if ev.ReferenceSetHash != fmt.Sprintf("0x%x", rh) || ev.Comparison.ReferenceSetHash != ev.ReferenceSetHash {
		t.Fatal("reference set hash")
	}
	got, err := dataworker.Rederive(ev, f.b.Response, refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: synthetic})
	if err != nil || got != dataworker.Pass {
		t.Fatal("second verifier could not re-derive", got, err)
	}
}

func TestPipelineFailToleranceExceeded(t *testing.T) {
	f := newFixture(t, `{"price":"64500"}`, "")
	v, ev := f.run(t)
	if v != dataworker.Fail || ev.Reason != "tolerance exceeded" || ev.Comparison.Medians["price"] != "64230.685" {
		t.Fatalf("%s %+v", v, ev.Comparison)
	}
	if got, err := dataworker.Rederive(ev, f.b.Response, refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: synthetic}); err != nil || got != dataworker.Fail {
		t.Fatal(got, err)
	}
}

func TestPipelineInconclusiveBelowQuorum(t *testing.T) {
	// The Kraken object is unavailable; one source cannot meet quorum 2.
	f := newFixture(t, `{"price":"1"}`, krakenID)
	v, ev := f.run(t)
	if v != dataworker.Inconclusive || ev.Reason != "reference quorum unavailable" {
		t.Fatalf("%s %+v", v, ev.Comparison)
	}
	if len(ev.References.Objects) != 1 || len(ev.References.Unavailable) != 1 || ev.References.Unavailable[0].Source != krakenID {
		t.Fatalf("%+v", ev.References)
	}
	if got, err := dataworker.Rederive(ev, f.b.Response, refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: synthetic}); err != nil || got != dataworker.Inconclusive {
		t.Fatal(got, err)
	}
	// No reference source configured at all.
	f = newFixture(t, `{"price":"64230.10"}`, "")
	f.pipe.References = nil
	if v, ev = f.run(t); v != dataworker.Inconclusive || ev.Reason != "references_unavailable" {
		t.Fatalf("%s %+v", v, ev)
	}
	// Raw objects that no longer verify are kept as evidence but excluded.
	f = newFixture(t, `{"price":"64230.10"}`, "")
	f.pipe.Decoder = refsource.Decoder{Registry: refsource.DefaultRegistry()}
	if v, ev = f.run(t); v != dataworker.Inconclusive || len(ev.References.Objects) != 2 || len(ev.Comparison.Excluded) != 2 {
		t.Fatalf("%s %+v", v, ev.Comparison)
	}
}

func TestPipelineMissingCommitmentFails(t *testing.T) {
	f := newFixture(t, `{"price":"64230.10"}`, "")
	f.b.Receipt.PredicateCommitment = protocol.Bytes32{}
	signReceipt(t, f.prof.Snapshot, &f.b)
	v, ev := f.run(t)
	if v != dataworker.Fail || ev.Reason != "empty_predicate_commitment" || *f.calls != 0 {
		t.Fatalf("%s %+v calls=%d", v, ev, *f.calls)
	}
	if got, err := dataworker.Rederive(ev, f.b.Response, nil); err != nil || got != dataworker.Fail {
		t.Fatal(got, err)
	}
}

func TestPipelineGateFailureIsNotJudged(t *testing.T) {
	f := newFixture(t, `{"price":"64230.10"}`, "")
	f.b.Response = []byte(`{"price":"64231"}`) // not covered by the signed receipt
	v, ev, err := f.pipe.Evaluate(context.Background(), f.b, f.prof)
	if !errors.Is(err, dataworker.ErrNotJudged) || v != "" || ev.Verdict != "" || *f.calls != 0 {
		t.Fatal(v, err, *f.calls)
	}
	f = newFixture(t, `{"price":"64230.10"}`, "")
	f.b.Signature[10] ^= 1
	if _, _, err = f.pipe.Evaluate(context.Background(), f.b, f.prof); !errors.Is(err, dataworker.ErrNotJudged) || *f.calls != 0 {
		t.Fatal(err)
	}
}

func TestPipelineSellerResponseDefectsFail(t *testing.T) {
	for response, reason := range map[string]string{
		`{"size":"1"}`:                     "required field absent",
		`{"price":64230.1}`:                "response value is not a decimal string",
		`{"price":"6.4e4"}`:                "response value is not a decimal string",
		`["price"]`:                        "response is not a JSON object",
		`{"price":"1","price":"64230.10"}`: "response is not a JSON object",
	} {
		f := newFixture(t, response, "")
		if v, ev := f.run(t); v != dataworker.Fail || ev.Reason != reason {
			t.Fatalf("%s: %s %s", response, v, ev.Reason)
		}
	}
}

func TestPipelineManifestAndPolicyChecks(t *testing.T) {
	f := newFixture(t, `{"price":"64230.10"}`, "")
	f.prof.Policy.MaxSkew++ // the operator holds a manifest other than the committed one
	if v, ev := f.run(t); v != dataworker.Inconclusive || ev.Reason != "tolerance_policy_unavailable" || *f.calls != 0 {
		t.Fatal(v, ev.Reason)
	}
	f = newFixture(t, `{"price":"64230.10"}`, "")
	f.prof.Sources = dataworker.SourceSet{Sources: []string{krakenID, coinbaseID}}
	if v, ev := f.run(t); v != dataworker.Inconclusive || ev.Reason != "source_set_unavailable" {
		t.Fatal(v, ev.Reason)
	}
	// A signed preimage naming another reference time contradicts the
	// seller's own registered policy.
	f = newFixture(t, `{"price":"64230.10"}`, "")
	f.b.Preimage.ReferenceTime++
	f.b.Receipt.PredicateCommitment = verifier.Commitment(1, f.b.Preimage)
	signReceipt(t, f.prof.Snapshot, &f.b)
	if v, ev := f.run(t); v != dataworker.Fail || ev.Reason != "reference_time_contradicts_policy" || *f.calls != 0 {
		t.Fatal(v, ev.Reason)
	}
}

func TestRederiveRejectsAlteredEvidence(t *testing.T) {
	f := newFixture(t, `{"price":"64230.10"}`, "")
	_, ev := f.run(t)
	dec := refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: synthetic}
	alter := map[string]func(*dataworker.Evidence){
		"raw byte": func(e *dataworker.Evidence) {
			o := &e.References.Objects[0]
			o.Raw = bytes.Replace(append([]byte(nil), o.Raw...), []byte("hand-built"), []byte("hand-bulit"), 1)
		},
		"verdict": func(e *dataworker.Evidence) { e.Verdict = "FAIL" },
		"median":  func(e *dataworker.Evidence) { e.Comparison.Medians["price"] = "64230.68" },
		"policy":  func(e *dataworker.Evidence) { e.Policy.MaxSkew = 3600 },
	}
	for name, change := range alter {
		var copyEv dataworker.Evidence
		raw, _, _ := ev.Encode()
		if err := json.Unmarshal(raw, &copyEv); err != nil {
			t.Fatal(err)
		}
		change(&copyEv)
		if _, err := dataworker.Rederive(copyEv, f.b.Response, dec); err == nil {
			t.Fatal("altered evidence accepted:", name)
		}
	}
	if _, err := dataworker.Rederive(ev, []byte(`{"price":"64230.11"}`), dec); err == nil {
		t.Fatal("other response accepted")
	}
}

// TestEvidenceVector fixes the canonical evidence encoding. The vector is a
// local regression vector for this experimental layout, not a normative one.
func TestEvidenceVector(t *testing.T) {
	raw, err := os.ReadFile("testdata/data-evidence-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var vec struct {
		Response, Verdict, Median                      string
		ReferenceSetHash, ComparisonHash, EvidenceHash string
		EvidenceSHA256, ComparisonCanonical, PolicyID  string
		ReplayObjectIDs                                []string
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	if err = dec.Decode(&vec); err != nil {
		t.Fatal(err)
	}
	f := newFixture(t, vec.Response, "")
	_, ev := f.run(t)
	enc1, h1, err := ev.Encode()
	if err != nil {
		t.Fatal(err)
	}
	// A second evaluation and a decode/re-encode round trip give the same bytes.
	_, ev2 := newFixture(t, vec.Response, "").run(t)
	enc2, h2, _ := ev2.Encode()
	var back dataworker.Evidence
	if err = json.Unmarshal(enc1, &back); err != nil {
		t.Fatal(err)
	}
	enc3, _, _ := back.Encode()
	if !bytes.Equal(enc1, enc2) || h1 != h2 || !bytes.Equal(enc1, enc3) {
		t.Fatal("evidence encoding is not deterministic")
	}
	cmp, _ := dataworker.CanonicalObject(ev.Comparison)
	ids := []string{}
	for _, o := range ev.References.Objects {
		ids = append(ids, o.ObjectID)
	}
	got := map[string]string{
		"verdict": ev.Verdict, "median": ev.Comparison.Medians["price"], "policyId": ev.PolicyID,
		"referenceSetHash": ev.ReferenceSetHash, "comparisonHash": ev.ComparisonHash,
		"evidenceHash": fmt.Sprintf("0x%x", h1), "evidenceSha256": hexSHA256(enc1),
		"comparisonCanonical": string(cmp), "replayObjectIds": strings.Join(ids, ","),
	}
	want := map[string]string{
		"verdict": vec.Verdict, "median": vec.Median, "policyId": vec.PolicyID,
		"referenceSetHash": vec.ReferenceSetHash, "comparisonHash": vec.ComparisonHash,
		"evidenceHash": vec.EvidenceHash, "evidenceSha256": vec.EvidenceSHA256,
		"comparisonCanonical": vec.ComparisonCanonical, "replayObjectIds": strings.Join(vec.ReplayObjectIDs, ","),
	}
	for k := range want {
		if got[k] != want[k] {
			t.Errorf("%s:\n got %s\nwant %s", k, got[k], want[k])
		}
	}
	if fmt.Sprintf("0x%x", protocol.Keccak256(cmp)) != ev.ComparisonHash {
		t.Error("comparison hash is not keccak256 of its canonical bytes")
	}
}

func hexSHA256(b []byte) string { return refsource.SHA256Hex(b) }

// TestCompareMatchesPythonKernel checks that the Go comparison agrees with the
// existing exact kernel in runtime/predicates on the cases both define.
func TestCompareMatchesPythonKernel(t *testing.T) {
	py, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 unavailable")
	}
	comparator, _ := filepath.Abs("../predicates/data_experiment.py")
	coin := dataworker.Observation{Source: coinbaseID, ObservedAt: refTime, Values: map[string]string{"price": "64231.57"}, Units: map[string]string{"price": "USD"}}
	krak := dataworker.Observation{Source: krakenID, ObservedAt: refTime + 1, Values: map[string]string{"price": "64229.8"}, Units: map[string]string{"price": "USD"}}
	stale := krak
	stale.ObservedAt = refTime + 31
	tight := testPolicy()
	tight.Fields = map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "5", Relative: "0.001", Spread: "1"}}
	cases := []struct {
		p        dataworker.Policy
		response string
		obs      []dataworker.Observation
	}{
		{testPolicy(), `{"price":"64230.10"}`, []dataworker.Observation{coin, krak}},
		{testPolicy(), `{"price":"64295"}`, []dataworker.Observation{coin, krak}},
		{testPolicy(), `{"price":"64500"}`, []dataworker.Observation{coin, krak}},
		{testPolicy(), `{"size":"1"}`, []dataworker.Observation{coin, krak}},
		{testPolicy(), `{"price":"64230.10"}`, []dataworker.Observation{coin, stale}},
		{testPolicy(), `{"price":"64230.10"}`, []dataworker.Observation{coin}},
		{tight, `{"price":"64230.10"}`, []dataworker.Observation{coin, krak}},
		{testPolicy(), `{"price":"64230.10"}`, []dataworker.Observation{coin, coin}},
	}
	for i, c := range cases {
		payload, _ := json.Marshal(map[string]any{"policyId": fmt.Sprintf("0x%x", dataworker.PolicyID), "policy": c.p, "responseBase64": []byte(c.response), "observations": c.obs})
		cmd := exec.Command(py, comparator)
		cmd.Stdin = bytes.NewReader(payload)
		out, err := cmd.Output()
		if err != nil {
			t.Fatal(err)
		}
		var r dataworker.Result
		if err = json.Unmarshal(out, &r); err != nil {
			t.Fatal(err)
		}
		g := dataworker.Compare(c.p, []byte(c.response), c.obs, nil)
		if g.Verdict != r.Verdict || g.Reason != r.Reason {
			t.Fatalf("case %d: go %s/%s python %s/%s", i, g.Verdict, g.Reason, r.Verdict, r.Reason)
		}
		for k, m := range r.Medians {
			a, _ := new(big.Rat).SetString(m)
			b, ok := new(big.Rat).SetString(g.Medians[k])
			if !ok || a.Cmp(b) != 0 {
				t.Fatalf("case %d: median %s go %s python %s", i, k, g.Medians[k], m)
			}
		}
	}
}
