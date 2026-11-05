package verifier

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/inference"
	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
)

const pipelineRefTime = 1790000000

var (
	coinbaseSource = refsource.CoinbaseTicker{Product: "BTC-USD"}.ID()
	krakenSource   = refsource.KrakenTicker{Pair: "XBTUSD"}.ID()
	syntheticOK    = refsource.VerifyOptions{AllowSynthetic: true}
	normativeData  = mustParse32("0xb1659e2eda6c17f24434be64972e5ce19d44b5b4154752bbe83418276831812f")
)

func mustParse32(s string) protocol.Bytes32 {
	h, err := parse32(s)
	if err != nil {
		panic(err)
	}
	return h
}

type pipelineEnv struct {
	*env
	manifests DataManifests
}

// newPipelineEnv builds a data-API purchase whose manifests select the two
// replayed ticker sources, and a seller that redelivers the serve bundle after
// a round trip through the serve-bundle wire format.
func newPipelineEnv(t *testing.T, response string, predicate protocol.Bytes32) *pipelineEnv {
	t.Helper()
	e := newEnv(t)
	policy := dataworker.Policy{Sources: []string{coinbaseSource, krakenSource}, Quorum: 2, ReferenceTime: pipelineRefTime, MaxSkew: 30,
		Fields: map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "5", Relative: "0.001", Spread: "50"}}}
	set := dataworker.SourceSet{Sources: policy.Sources}
	ph, _ := dataworker.ObjectHash(policy)
	sh, _ := dataworker.ObjectHash(set)
	s := e.a.Snapshot
	s.PredicateID = predicate
	claims, _ := json.Marshal(map[string]any{"version": 1, "classId": 1, "predicateId": hx(predicate), "sourceSetHash": hx(sh), "tolerancePolicyHash": hx(ph)})
	b := gate.Bundle{Key: protocol.Bytes16{5}, Claims: claims, Response: []byte(response),
		Request:  gate.CanonicalRequest{Method: []byte("GET"), Path: []byte("/v1/price"), Query: []byte("pair=BTC-USD")},
		Preimage: gate.Preimage{ReferenceTime: pipelineRefTime, SourceSetHash: sh, TolerancePolicyHash: ph}}
	s.ClaimsHash = protocol.Keccak256(claims)
	s.RequestHash = gate.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash,
		ResponseHash: protocol.ResponseHash(b.Response), ClaimsHash: s.ClaimsHash, PredicateCommitment: gate.Commitment(1, b.Preimage), IssuedAt: pipelineRefTime}
	var err error
	if b.Signature, err = (testKeySigner{}).SignDigest(context.Background(), protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)); err != nil {
		t.Fatal(err)
	}
	wire, err := EncodeBundle(s.ChainID, s.Contract, b, nil)
	if err != nil {
		t.Fatal(err)
	}
	decoded, _, err := DecodeBundle(wire, s.ChainID, s.Contract)
	if err != nil {
		t.Fatal(err)
	}
	decoded.Claims = claims // claims are fetched separately from the seller
	e.a.Snapshot = s
	e.src = &fakeSource{a: e.a}
	e.chain.assigned = []protocol.Bytes32{s.Nonce}
	e.seller = &fakeSeller{b: decoded}
	e.binding = ledger.ManifestBindings{SourceSetHash: sh, TolerancePolicyHash: ph}
	return &pipelineEnv{env: e, manifests: DataManifests{Policy: policy, Sources: set}}
}

func (e *pipelineEnv) dataPredicate(t *testing.T) DataPredicate {
	t.Helper()
	replay, err := refsource.LoadReplay("../../runtime/dataworker/testdata/refsource/replay", syntheticOK)
	if err != nil {
		t.Fatal(err)
	}
	return DataPredicate{
		Pipeline: dataworker.Pipeline{
			References: refsource.Provider{Registry: refsource.DefaultRegistry(), Retriever: replay, Verify: syntheticOK},
			Decoder:    refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: syntheticOK},
		},
		Profiles: map[uint32]DataManifests{e.a.Snapshot.ProfileID: e.manifests},
		Objects:  e.objects, Revision: "test",
	}
}

func (e *pipelineEnv) pipelineWorker(t *testing.T, router PredicateRouter) *Worker {
	t.Helper()
	st, err := OpenStore(filepath.Join(e.dir, "state"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return &Worker{
		Opts:   Options{VerifierID: 3, Bindings: map[uint32]ledger.ManifestBindings{e.a.Snapshot.ProfileID: e.binding}, SubmitMarginBlocks: 2},
		Source: e.src, Chain: e.chain, Seller: e.seller, Predicate: router,
		Outbox: judgment.Outbox{Dir: filepath.Join(e.dir, "outbox"), Objects: e.objects},
		Signer: testKeySigner{}, Sender: e.sender, State: st,
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

// submitted runs one pass and returns the stored, parsed evidence envelope of
// the single submitted verdict.
func (e *pipelineEnv) submitted(t *testing.T, w *Worker) (evidence.Envelope, judgment.Prepared) {
	t.Helper()
	if !tick(t, w) {
		t.Fatal("tick did not complete")
	}
	if e.sender.calls != 1 || e.seller.calls != 1 {
		t.Fatal("calls", e.sender.calls, e.seller.calls)
	}
	bound := e.a
	bound.Snapshot.SourceSetHash, bound.Snapshot.TolerancePolicyHash = e.binding.SourceSetHash, e.binding.TolerancePolicyHash
	p, attempted, err := w.Outbox.Load(context.Background(), bound)
	if err != nil || !attempted {
		t.Fatal("no attempted outbox record", err)
	}
	raw, err := e.objects.Get(p.Verdict.EvidenceHash)
	if err != nil {
		t.Fatal(err)
	}
	env, err := evidence.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if protocol.VerdictCode(env.Verdict) != p.Verdict.Verdict {
		t.Fatal("verdict code differs from envelope")
	}
	return env, p
}

func (e *pipelineEnv) object(t *testing.T, ref string, into any) {
	t.Helper()
	raw, err := e.objects.Get(mustParse32(ref))
	if err != nil {
		t.Fatal("referenced object missing: ", ref, err)
	}
	if into != nil {
		if err = json.Unmarshal(raw, into); err != nil {
			t.Fatal(err)
		}
	}
}

// TestDataPipelineEndToEnd runs the worker with the data pipeline registered
// under the experimental predicate: redelivery, gate, replayed references,
// comparison, evidence storage, signing and submission. A second verifier then
// re-derives the verdict from the stored objects the envelope references.
func TestDataPipelineEndToEnd(t *testing.T) {
	for _, c := range []struct {
		response, verdict string
		code              uint8
	}{
		{`{"price":"64230.10"}`, "PASS", protocol.VerdictPass},
		{`{"price":"64500"}`, "FAIL", protocol.VerdictFail},
	} {
		t.Run(c.verdict, func(t *testing.T) {
			e := newPipelineEnv(t, c.response, gate.ExperimentalDataPredicate)
			router := PredicateRouter{ByID: map[protocol.Bytes32]Predicate{gate.ExperimentalDataPredicate: e.dataPredicate(t)}, Objects: e.objects}
			w := e.pipelineWorker(t, router)
			env, p := e.submitted(t, w)
			if env.Verdict != c.verdict || p.Verdict.Verdict != c.code || e.entry(t, w).Verdict != c.code {
				t.Fatalf("%+v", env)
			}
			var refs dataworker.ReferenceSet
			var cmp dataworker.Comparison
			var pol dataworker.Policy
			var set dataworker.SourceSet
			e.object(t, env.Details["referenceResponsesHash"], &refs)
			e.object(t, env.Details["comparisonHash"], &cmp)
			e.object(t, env.Details["tolerancePolicyHash"], &pol)
			e.object(t, env.Details["sourceSetHash"], &set)
			e.object(t, env.ImplementationHash, nil)
			if len(refs.Objects) != 2 || cmp.Medians["price"] != "64230.685" || cmp.Verdict != c.verdict || cmp.ReferenceSetHash != env.Details["referenceResponsesHash"] {
				t.Fatalf("%+v %+v", refs, cmp)
			}
			ev := dataworker.Evidence{Format: dataworker.EvidenceFormat, PolicyID: hx(dataworker.PolicyID), ResponseHash: env.ResponseHash,
				SourceSetHash: env.Details["sourceSetHash"], TolerancePolicyHash: env.Details["tolerancePolicyHash"], SourceSet: set, Policy: pol,
				References: refs, ReferenceSetHash: env.Details["referenceResponsesHash"], Comparison: cmp, ComparisonHash: env.Details["comparisonHash"], Verdict: cmp.Verdict}
			v, err := dataworker.Rederive(ev, e.seller.b.Response, refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: syntheticOK})
			if err != nil || string(v) != c.verdict {
				t.Fatal("re-derivation from stored objects failed", v, err)
			}
		})
	}
}

type countingRefs struct {
	inner dataworker.ReplaySource
	calls *int
}

func (c countingRefs) Collect(ctx context.Context, s dataworker.SourceSet, t uint64) (dataworker.Collection, error) {
	*c.calls++
	return c.inner.Collect(ctx, s, t)
}

// A redelivered bundle that fails the gate never reaches the pipeline and no
// verdict is prepared.
func TestDataPipelineUnauthenticatedRedelivery(t *testing.T) {
	e := newPipelineEnv(t, `{"price":"64230.10"}`, gate.ExperimentalDataPredicate)
	e.seller.tamper = true
	calls := new(int)
	dp := e.dataPredicate(t)
	dp.Pipeline.References = countingRefs{dp.Pipeline.References, calls}
	w := e.pipelineWorker(t, PredicateRouter{ByID: map[protocol.Bytes32]Predicate{gate.ExperimentalDataPredicate: dp}, Objects: e.objects})
	tick(t, w)
	if e.sender.calls != 0 || *calls != 0 || e.entry(t, w).Status == StatusPrepared {
		t.Fatal("unauthenticated redelivery was judged", e.sender.calls, *calls)
	}
}

// A gate-accepted predicate identifier without a registered pipeline keeps the
// INCONCLUSIVE fallback.
func TestUnregisteredPredicateFallsBackToInconclusive(t *testing.T) {
	e := newPipelineEnv(t, `{"price":"64230.10"}`, normativeData)
	// The operator's manifests are local configuration, present in the store.
	for _, m := range []any{e.manifests.Sources, e.manifests.Policy} {
		if _, err := put(e.objects, m); err != nil {
			t.Fatal(err)
		}
	}
	router := PredicateRouter{ByID: map[protocol.Bytes32]Predicate{gate.ExperimentalDataPredicate: e.dataPredicate(t)}, Objects: e.objects}
	w := e.pipelineWorker(t, router)
	env, p := e.submitted(t, w)
	if env.Verdict != "INCONCLUSIVE" || p.Verdict.Verdict != protocol.VerdictInconclusive || env.PredicateID != hx(normativeData) {
		t.Fatalf("%+v", env)
	}
	var rec map[string]string
	e.object(t, env.Details["comparisonHash"], &rec)
	if rec["reason"] != "no pipeline for predicate" || rec["format"] != FallbackFormat {
		t.Fatal(rec)
	}
}

// The inference adapter stores the evidence object and configuration its
// envelope references. With no local weights the verdict is INCONCLUSIVE.
func TestInferencePredicateEnvelope(t *testing.T) {
	raw, err := os.ReadFile("../../runtime/inference/testdata/binding-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		Config, Trace string
		Preimage      map[string]string
	}
	if err = json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	e := newEnv(t)
	pre := gate.Preimage{ToplocCommitment: mustParse32(fx.Preimage["toplocCommitment"]), ModelHash: mustParse32(fx.Preimage["modelHash"]), ConfigHash: mustParse32(fx.Preimage["configHash"])}
	s := e.a.Snapshot
	s.ClassID, s.PredicateID, s.ModelHash, s.ConfigHash = 2, inference.PredicateID, pre.ModelHash, pre.ConfigHash
	claims, _ := json.Marshal(map[string]any{"version": 1, "classId": 2, "predicateId": hx(s.PredicateID), "modelHash": hx(pre.ModelHash), "configHash": hx(pre.ConfigHash)})
	req, _ := json.Marshal(map[string]any{"format": "fairbind/experimental/inference-request/v1", "version": 1, "promptIds": []int{1, 17, 300}})
	resp, _ := json.Marshal(map[string]any{"format": "fairbind/experimental/inference-response/v1", "version": 1, "outputIds": []int{5, 6}, "trace": fx.Trace})
	b := gate.Bundle{Key: protocol.Bytes16{5}, Claims: claims, Response: resp, Preimage: pre,
		Request: gate.CanonicalRequest{Method: []byte("POST"), Path: []byte("/v1/generate"), Body: req}}
	s.ClaimsHash = protocol.Keccak256(claims)
	s.RequestHash = gate.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash,
		ResponseHash: protocol.ResponseHash(resp), ClaimsHash: s.ClaimsHash, PredicateCommitment: gate.Commitment(2, pre), IssuedAt: 7}
	if b.Signature, err = (testKeySigner{}).SignDigest(context.Background(), protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)); err != nil {
		t.Fatal(err)
	}
	a := e.a
	a.Snapshot = s
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal("python3 is required")
	}
	script, _ := filepath.Abs("../../runtime/inference/evaluate.py")
	p := InferencePredicate{Pipeline: inference.Pipeline{Python: python, Script: script}, Configs: map[protocol.Bytes32][]byte{pre.ConfigHash: []byte(fx.Config)}, Objects: e.objects}
	env, err := PredicateRouter{ByID: map[protocol.Bytes32]Predicate{inference.PredicateID: p}}.Evaluate(context.Background(), a, b, gate.Result{Status: gate.Ready})
	if err != nil || env.Verdict != "INCONCLUSIVE" {
		t.Fatal(env.Verdict, err)
	}
	if _, _, err = evidence.Build(env); err != nil {
		t.Fatal(err)
	}
	for _, ref := range []string{env.Details["traceHash"], env.Details["configHash"], env.ImplementationHash} {
		(&pipelineEnv{env: e}).object(t, ref, nil)
	}
}
