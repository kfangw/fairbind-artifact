package judgment

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/ledger"
	"example.org/fairbind/runtime/verifier"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

type publicSigner struct{}

func (publicSigner) SignDigest(ctx context.Context, h protocol.Bytes32) ([]byte, error) {
	out, e := exec.CommandContext(ctx, "cast", "wallet", "sign", "--no-hash", "--private-key", "0x"+strings.Repeat("0", 63)+"1", fmt.Sprintf("0x%x", h)).Output()
	if e != nil {
		return nil, e
	}
	return hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x"))
}

type source struct{ a ledger.Assignment }

func (s source) Read(context.Context, protocol.Bytes32, ledger.ManifestBindings) (ledger.Assignment, error) {
	return s.a, nil
}

type sender struct {
	calls *int
	fail  bool
}

func (s sender) Send(context.Context, protocol.Address, []byte) (protocol.Bytes32, error) {
	*s.calls++
	if s.fail {
		return protocol.Bytes32{}, fmt.Errorf("response lost")
	}
	return protocol.Bytes32{9}, nil
}
func fixture(t *testing.T) (Outbox, ledger.Assignment, verifier.Bundle, evidence.Envelope) {
	t.Helper()
	dir := t.TempDir()
	store, e := evidence.NewStore(filepath.Join(dir, "objects"), 1<<20)
	if e != nil {
		t.Fatal(e)
	}
	put := func(s string) protocol.Bytes32 {
		h, e := store.Put([]byte(s))
		if e != nil {
			t.Fatal(e)
		}
		return h
	}
	sh := put(`{"sources":["a"]}`)
	ph := put(`{"absolute":"1"}`)
	rh := put(`{"source":"a","value":"100"}`)
	ch := put(`{"verdict":"PASS"}`)
	ih := put(`{"implementation":"fixture"}`)
	hx := func(h protocol.Bytes32) string { return fmt.Sprintf("0x%x", h) }
	kb, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	addr, _ := protocol.ParseAddress(kb)
	s := verifier.Snapshot{ChainID: 31337, Contract: protocol.Address{1}, Buyer: protocol.Address{2}, SellerKey: addr, SellerID: 7, ProfileID: 4, ClassID: 1, PredicateID: verifier.ExperimentalDataPredicate, CanonID: protocol.Keccak256([]byte("fairbind/http-canon/v1")), SourceSetHash: sh, TolerancePolicyHash: ph, MaxRequestBytes: 65536, MaxResponseBytes: 65536, MaxClaimsBytes: 65536}
	claims, _ := json.Marshal(map[string]any{"version": 1, "classId": 1, "predicateId": hx(s.PredicateID), "sourceSetHash": hx(sh), "tolerancePolicyHash": hx(ph)})
	b := verifier.Bundle{Claims: claims, Response: []byte(`{"price":"100"}`), Request: verifier.CanonicalRequest{Method: []byte("GET"), Path: []byte("/")}, Preimage: verifier.Preimage{ReferenceTime: 100, SourceSetHash: sh, TolerancePolicyHash: ph}}
	s.ClaimsHash = protocol.Keccak256(claims)
	s.RequestHash = verifier.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash, ResponseHash: protocol.ResponseHash(b.Response), ClaimsHash: s.ClaimsHash, PredicateCommitment: verifier.Commitment(1, b.Preimage)}
	b.Signature, e = (publicSigner{}).SignDigest(context.Background(), protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt))
	if e != nil {
		t.Fatal(e)
	}
	a := ledger.Assignment{Snapshot: s, BlockNumber: 10, BlockHash: protocol.Bytes32{8}, Stage: 1, Attempt: 0, CaseState: 5, VerifierID: 1, VerifierKey: addr, JudgeDue: 100, Trigger: 2, MaxEvidenceBytes: 65536}
	env := evidence.Envelope{Version: 1, ClassID: 1, PredicateID: hx(s.PredicateID), Nonce: hx(s.Nonce), ResponseHash: hx(b.Receipt.ResponseHash), PredicateCommitment: hx(b.Receipt.PredicateCommitment), Verdict: "PASS", ImplementationHash: hx(ih), ObservedAt: "100", Details: map[string]string{"kind": "data-api", "referenceTime": "100", "sourceSetHash": hx(sh), "tolerancePolicyHash": hx(ph), "referenceResponsesHash": hx(rh), "comparisonHash": hx(ch)}}
	return Outbox{Dir: filepath.Join(dir, "outbox"), Objects: store}, a, b, env
}
func prepare(t *testing.T, o Outbox, a ledger.Assignment, b verifier.Bundle, e evidence.Envelope) Prepared {
	t.Helper()
	p, err := o.Prepare(context.Background(), a, b, e, protocol.ReceiptProof{}, publicSigner{})
	if err != nil {
		t.Fatal(err)
	}
	return p
}
func TestDurablePrepareAndSingleSubmit(t *testing.T) {
	o, a, b, e := fixture(t)
	p := prepare(t, o, a, b, e)
	again := prepare(t, o, a, b, e)
	if string(p.CallData) != string(again.CallData) {
		t.Fatal("retry changed calldata")
	}
	calls := 0
	tx, err := o.Submit(context.Background(), p, source{a}, sender{&calls, false})
	if err != nil || tx == (protocol.Bytes32{}) || calls != 1 {
		t.Fatal(tx, err, calls)
	}
	if _, err = o.Submit(context.Background(), p, source{a}, sender{&calls, false}); err == nil || calls != 1 {
		t.Fatal("duplicate broadcast")
	}
}
func TestUncertainBroadcastSurvivesReopen(t *testing.T) {
	o, a, b, e := fixture(t)
	p := prepare(t, o, a, b, e)
	calls := 0
	if _, err := o.Submit(context.Background(), p, source{a}, sender{&calls, true}); err == nil {
		t.Fatal("lost ack")
	}
	reopen := Outbox{Dir: o.Dir, Objects: o.Objects}
	if _, err := reopen.Submit(context.Background(), p, source{a}, sender{&calls, false}); err == nil || calls != 1 {
		t.Fatal("uncertain resubmitted")
	}
}
func TestChangedAssignmentAndTamperedPrepared(t *testing.T) {
	o, a, b, e := fixture(t)
	p := prepare(t, o, a, b, e)
	calls := 0
	other := a
	other.Attempt++
	if _, err := o.Submit(context.Background(), p, source{other}, sender{&calls, false}); err == nil {
		t.Fatal("changed attempt")
	}
	p.CallData[5] ^= 1
	if _, err := o.Submit(context.Background(), p, source{a}, sender{&calls, false}); err == nil || calls != 0 {
		t.Fatal("tampered prepared")
	}
}
func TestRefusalBeforeSigningAndConflictingDecision(t *testing.T) {
	o, a, b, e := fixture(t)
	bad := b
	bad.Response = []byte("tamper")
	if _, err := o.Prepare(context.Background(), a, bad, e, protocol.ReceiptProof{}, publicSigner{}); err == nil {
		t.Fatal("unbound body")
	}
	p := prepare(t, o, a, b, e)
	e.Verdict = "FAIL"
	if _, err := o.Prepare(context.Background(), a, b, e, protocol.ReceiptProof{}, publicSigner{}); err == nil {
		t.Fatal("conflicting decision")
	}
	if err := os.WriteFile(filepath.Join(o.Dir, key(a)+".attempt"), []byte("crashed before send"), 0600); err != nil {
		t.Fatal(err)
	}
	calls := 0
	if _, err := o.Submit(context.Background(), p, source{a}, sender{&calls, false}); err == nil || calls != 0 {
		t.Fatal("pre-send crash retry")
	}
}
func TestSampleProofAndEvidenceAvailability(t *testing.T) {
	o, a, b, e := fixture(t)
	a.Trigger = 1
	a.AnchorCount = 1
	a.AnchorRoot = protocol.ReceiptEntryHash(protocol.ReceiptEntry{Nonce: a.Snapshot.Nonce, ReceiptLeaf: protocol.ReceiptDigest(a.Snapshot.ChainID, a.Snapshot.Contract, b.Receipt)})
	if _, err := o.Prepare(context.Background(), a, b, e, protocol.ReceiptProof{}, publicSigner{}); err == nil {
		t.Fatal("empty sample proof")
	}
	if _, err := o.Prepare(context.Background(), a, b, e, protocol.ReceiptProof{Count: 1}, publicSigner{}); err != nil {
		t.Fatal(err)
	}
	a.Attempt++
	a.MaxEvidenceBytes = 1
	if _, err := o.Prepare(context.Background(), a, b, e, protocol.ReceiptProof{Count: 1}, publicSigner{}); err == nil {
		t.Fatal("oversize evidence")
	}
	a.MaxEvidenceBytes = 65536
	e.ImplementationHash = "0x" + strings.Repeat("9", 64)
	if _, err := o.Prepare(context.Background(), a, b, e, protocol.ReceiptProof{Count: 1}, publicSigner{}); err == nil {
		t.Fatal("missing implementation object")
	}
}
func TestCalldataMatchesCastABI(t *testing.T) {
	o, a, b, e := fixture(t)
	p := prepare(t, o, a, b, e)
	v := p.Verdict
	r := p.Receipt
	hx := func(h protocol.Bytes32) string { return fmt.Sprintf("0x%x", h) }
	vs := fmt.Sprintf("(%d,%s,%d,%d,%d,%d,%s)", v.Version, hx(v.Nonce), v.Stage, v.Attempt, v.VerifierID, v.Verdict, hx(v.EvidenceHash))
	rs := fmt.Sprintf("(%d,%d,%d,%s,%s,%s,%s,%s,%d,%d)", r.Version, r.SellerID, r.ProfileID, hx(r.Nonce), hx(r.RequestHash), hx(r.ResponseHash), hx(r.ClaimsHash), hx(r.PredicateCommitment), r.Epoch, r.IssuedAt)
	out, err := exec.Command("cast", "calldata", JudgeSignature, vs, "0x"+hex.EncodeToString(p.VerdictSignature), rs, "0x"+hex.EncodeToString(b.Signature), "(0,0,[])").Output()
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(out)) != "0x"+hex.EncodeToString(p.CallData) {
		t.Fatal("ABI mismatch")
	}
}
func TestPreparedReferencesRecheckedBeforeSend(t *testing.T) {
	o, a, b, e := fixture(t)
	p := prepare(t, o, a, b, e)
	var h protocol.Bytes32
	raw, _ := hex.DecodeString(e.Details["comparisonHash"][2:])
	copy(h[:], raw) // Store names are the hexadecimal content hash.
	objectPath := filepath.Join(filepath.Dir(o.Dir), "objects", fmt.Sprintf("%x", h))
	if err := os.Chmod(objectPath, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(objectPath, []byte("changed"), 0600); err != nil {
		t.Fatal(err)
	}
	calls := 0
	if _, err := o.Submit(context.Background(), p, source{a}, sender{&calls, false}); err == nil || calls != 0 {
		t.Fatal("changed referenced bytes submitted")
	}
}

type evaluator struct {
	e     evidence.Envelope
	calls *int
}

func (v evaluator) Evaluate(context.Context, ledger.Assignment, verifier.Bundle) (evidence.Envelope, error) {
	*v.calls++
	return v.e, nil
}
func TestRunOnceAndReload(t *testing.T) {
	o, a, b, e := fixture(t)
	calls, evals := 0, 0
	if _, err := o.RunOnce(context.Background(), a.Snapshot.Nonce, ledger.ManifestBindings{}, b, protocol.ReceiptProof{}, source{a}, evaluator{e, &evals}, publicSigner{}, sender{&calls, false}); err != nil || calls != 1 || evals != 1 {
		t.Fatal(err, calls, evals)
	}
	p, attempted, err := o.Load(context.Background(), a)
	if err != nil || !attempted || p.Verdict.Nonce != a.Snapshot.Nonce {
		t.Fatal(err, attempted)
	}
	b.Response = []byte("tampered")
	if _, err = o.RunOnce(context.Background(), a.Snapshot.Nonce, ledger.ManifestBindings{}, b, protocol.ReceiptProof{}, source{a}, evaluator{e, &evals}, publicSigner{}, sender{&calls, false}); err == nil || evals != 1 {
		t.Fatal("unbound inputs evaluated")
	}
}
