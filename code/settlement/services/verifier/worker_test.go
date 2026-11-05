package verifier

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
)

// testKeySigner signs with the well-known private key 1 through cast. The same
// key signs seller receipts and verdicts in these fixtures.
type testKeySigner struct{}

func (testKeySigner) SignDigest(ctx context.Context, h protocol.Bytes32) ([]byte, error) {
	out, err := exec.CommandContext(ctx, "cast", "wallet", "sign", "--no-hash", "--private-key", "0x"+strings.Repeat("0", 63)+"1", fmt.Sprintf("0x%x", h)).Output()
	if err != nil {
		return nil, err
	}
	return hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x"))
}

// fakeSource emulates the finalized ledger adapter: manifest bindings are
// copied from the caller, as ledger.Client.Read does.
type fakeSource struct {
	mu      sync.Mutex
	a       ledger.Assignment
	reads   int
	crashAt int // simulate a process crash on this read (1-based)
}

func (s *fakeSource) set(f func(*ledger.Assignment)) { s.mu.Lock(); f(&s.a); s.mu.Unlock() }

func (s *fakeSource) Read(_ context.Context, nonce protocol.Bytes32, m ledger.ManifestBindings) (ledger.Assignment, error) {
	s.mu.Lock()
	s.reads++
	n, a, crash := s.reads, s.a, s.crashAt
	s.mu.Unlock()
	if crash > 0 && n == crash {
		runtime.Goexit()
	}
	if nonce != a.Snapshot.Nonce {
		return ledger.Assignment{}, fmt.Errorf("unknown purchase")
	}
	a.Snapshot.SourceSetHash, a.Snapshot.TolerancePolicyHash, a.Snapshot.ModelHash, a.Snapshot.ConfigHash = m.SourceSetHash, m.TolerancePolicyHash, m.ModelHash, m.ConfigHash
	return a, nil
}

type fakeChain struct {
	mu       sync.Mutex
	head     uint64
	fin      uint64
	assigned []protocol.Bytes32
	recorded bool
	tx       map[protocol.Bytes32]TxStatus
	scans    [][2]uint64
}

func (c *fakeChain) BlockNumber(context.Context) (uint64, error)    { return c.head, nil }
func (c *fakeChain) FinalizedBlock(context.Context) (uint64, error) { return c.fin, nil }
func (c *fakeChain) AssignedNonces(_ context.Context, _ uint32, from, to uint64) ([]protocol.Bytes32, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.scans = append(c.scans, [2]uint64{from, to})
	return c.assigned, nil
}
func (c *fakeChain) VerdictRecorded(context.Context, protocol.Bytes32, uint32, uint8, protocol.Bytes32, uint64, uint64) (bool, error) {
	return c.recorded, nil
}
func (c *fakeChain) TxStatus(_ context.Context, tx protocol.Bytes32) (TxStatus, error) {
	return c.tx[tx], nil
}

type fakeSeller struct {
	b      gate.Bundle
	proof  protocol.ReceiptProof
	calls  int
	tamper bool
}

func (s *fakeSeller) Redeliver(context.Context, ledger.Assignment) (gate.Bundle, protocol.ReceiptProof, error) {
	s.calls++
	b := s.b
	if s.tamper {
		b.Response = []byte(`{"price":"999"}`)
	}
	return b, s.proof, nil
}

// fakePredicate stands in for the class pipelines: it stores its reference
// and comparison objects and returns a fixed envelope.
type fakePredicate struct {
	store *evidence.Store
	env   evidence.Envelope
	objs  []string
	calls int
	gates []gate.Status
}

func (p *fakePredicate) Evaluate(_ context.Context, _ ledger.Assignment, _ gate.Bundle, g gate.Result) (evidence.Envelope, error) {
	p.calls++
	p.gates = append(p.gates, g.Status)
	for _, o := range p.objs {
		if _, err := p.store.Put([]byte(o)); err != nil {
			return evidence.Envelope{}, err
		}
	}
	return p.env, nil
}

const (
	sendOK = iota
	sendLost
	sendCrashBefore
	sendCrashAfter
)

type fakeSender struct {
	mu    sync.Mutex
	mode  int
	calls int
}

func (s *fakeSender) Send(context.Context, protocol.Address, []byte) (protocol.Bytes32, error) {
	s.mu.Lock()
	mode := s.mode
	if mode == sendCrashBefore {
		s.mu.Unlock()
		runtime.Goexit()
	}
	s.calls++
	s.mu.Unlock()
	switch mode {
	case sendLost:
		return protocol.Bytes32{}, fmt.Errorf("connection reset")
	case sendCrashAfter:
		runtime.Goexit()
	}
	return protocol.Bytes32{9}, nil
}

type env struct {
	dir     string
	objects *evidence.Store
	a       ledger.Assignment
	src     *fakeSource
	chain   *fakeChain
	seller  *fakeSeller
	pred    *fakePredicate
	sender  *fakeSender
	binding ledger.ManifestBindings
}

func hx(h protocol.Bytes32) string { return fmt.Sprintf("0x%x", h) }

func newEnv(t *testing.T) *env {
	t.Helper()
	if _, err := exec.LookPath("cast"); err != nil {
		t.Fatal("cast (foundry 1.7.1) must be on PATH")
	}
	dir := t.TempDir()
	objects, err := evidence.NewStore(filepath.Join(dir, "objects"), 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	// Manifest objects are local configuration, present before any assignment.
	sh, _ := objects.Put([]byte(`{"sources":["a"]}`))
	ph, _ := objects.Put([]byte(`{"absolute":"1"}`))
	objs := []string{`{"source":"a","value":"100"}`, `{"verdict":"PASS"}`, `{"implementation":"fixture"}`}
	rh, ch, ih := protocol.Keccak256([]byte(objs[0])), protocol.Keccak256([]byte(objs[1])), protocol.Keccak256([]byte(objs[2]))
	kb, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	key, _ := protocol.ParseAddress(kb)
	s := gate.Snapshot{ChainID: 31337, Contract: protocol.Address{1}, Buyer: protocol.Address{2}, SellerKey: key, SellerID: 7, ProfileID: 4, ClassID: 1, PredicateID: gate.ExperimentalDataPredicate, CanonID: protocol.Keccak256([]byte("fairbind/http-canon/v1")), MaxRequestBytes: 65536, MaxResponseBytes: 65536, MaxClaimsBytes: 65536}
	claims, _ := json.Marshal(map[string]any{"version": 1, "classId": 1, "predicateId": hx(s.PredicateID), "sourceSetHash": hx(sh), "tolerancePolicyHash": hx(ph)})
	b := gate.Bundle{Key: protocol.Bytes16{5}, Claims: claims, Response: []byte(`{"price":"100"}`), Request: gate.CanonicalRequest{Method: []byte("GET"), Path: []byte("/")}, Preimage: gate.Preimage{ReferenceTime: 100, SourceSetHash: sh, TolerancePolicyHash: ph}}
	s.ClaimsHash = protocol.Keccak256(claims)
	s.RequestHash = gate.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash, ResponseHash: protocol.ResponseHash(b.Response), ClaimsHash: s.ClaimsHash, PredicateCommitment: gate.Commitment(1, b.Preimage), IssuedAt: 1}
	if b.Signature, err = (testKeySigner{}).SignDigest(context.Background(), protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)); err != nil {
		t.Fatal(err)
	}
	a := ledger.Assignment{Snapshot: s, BlockNumber: 10, BlockHash: protocol.Bytes32{8}, Stage: 1, Attempt: 0, CaseState: 5, VerifierID: 3, VerifierKey: key, JudgeDue: 100, Trigger: 2, MaxEvidenceBytes: 65536}
	envl := evidence.Envelope{Version: 1, ClassID: 1, PredicateID: hx(s.PredicateID), Nonce: hx(s.Nonce), ResponseHash: hx(b.Receipt.ResponseHash), PredicateCommitment: hx(b.Receipt.PredicateCommitment), Verdict: "PASS", ImplementationHash: hx(ih), ObservedAt: "100", Details: map[string]string{"kind": "data-api", "referenceTime": "100", "sourceSetHash": hx(sh), "tolerancePolicyHash": hx(ph), "referenceResponsesHash": hx(rh), "comparisonHash": hx(ch)}}
	return &env{
		dir: dir, objects: objects, a: a,
		src:     &fakeSource{a: a},
		chain:   &fakeChain{head: 20, fin: 10, assigned: []protocol.Bytes32{s.Nonce}, tx: map[protocol.Bytes32]TxStatus{}},
		seller:  &fakeSeller{b: b},
		pred:    &fakePredicate{store: objects, env: envl, objs: objs},
		sender:  &fakeSender{},
		binding: ledger.ManifestBindings{SourceSetHash: sh, TolerancePolicyHash: ph},
	}
}

// worker opens a fresh worker over the environment's directories, as a
// restarted process would.
func (e *env) worker(t *testing.T) *Worker {
	t.Helper()
	st, err := OpenStore(filepath.Join(e.dir, "state"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return &Worker{
		Opts:      Options{VerifierID: 3, Bindings: map[uint32]ledger.ManifestBindings{4: e.binding}, SubmitMarginBlocks: 2},
		Source:    e.src,
		Chain:     e.chain,
		Seller:    e.seller,
		Predicate: e.pred,
		Outbox:    judgment.Outbox{Dir: filepath.Join(e.dir, "outbox"), Objects: e.objects},
		Signer:    testKeySigner{},
		Sender:    e.sender,
		State:     st,
		Log:       slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

// tick runs one pass on its own goroutine so a simulated crash (Goexit) ends
// only that pass. It reports whether the pass completed.
func tick(t *testing.T, w *Worker) bool {
	t.Helper()
	done := make(chan struct{})
	completed := false
	go func() {
		defer close(done)
		if err := w.Tick(context.Background()); err != nil {
			t.Error(err)
		}
		completed = true
	}()
	<-done
	return completed
}

// bound returns the snapshot as the ledger adapter reports it with the
// configured manifest bindings.
func (e *env) bound() gate.Snapshot {
	s := e.a.Snapshot
	s.SourceSetHash, s.TolerancePolicyHash = e.binding.SourceSetHash, e.binding.TolerancePolicyHash
	return s
}

func (e *env) entry(t *testing.T, w *Worker) *Entry {
	t.Helper()
	got := w.State.S.Entries[assignmentKey(e.a)]
	if got == nil {
		t.Fatal("no entry for assignment")
	}
	return got
}

// crash drops a worker as a process exit would: the lock is released and
// nothing after the crash point was persisted.
func crash(w *Worker) { w.State.Close() }

func TestHappyPathSubmitsOnceThenConfirms(t *testing.T) {
	e := newEnv(t)
	w := e.worker(t)
	if !tick(t, w) {
		t.Fatal("tick did not complete")
	}
	if e.sender.calls != 1 || e.pred.calls != 1 || e.seller.calls != 1 {
		t.Fatal("calls", e.sender.calls, e.pred.calls, e.seller.calls)
	}
	en := e.entry(t, w)
	if en.Status != StatusSubmitted || en.Tx != hx(protocol.Bytes32{9}) || en.Verdict != protocol.VerdictPass {
		t.Fatalf("entry %+v", en)
	}
	if e.pred.gates[0] != gate.Ready {
		t.Fatal("predicate did not receive gate result")
	}
	// Not yet finalized: stays submitted, no resend.
	tick(t, w)
	if e.sender.calls != 1 || e.entry(t, w).Status != StatusSubmitted {
		t.Fatal("resent or resolved early")
	}
	// Finalized ledger shows the verdict and the case moved on.
	e.chain.recorded = true
	e.src.set(func(a *ledger.Assignment) { a.CaseState = 6; a.BlockNumber = 30 })
	tick(t, w)
	if e.entry(t, w).Status != StatusConfirmed || e.sender.calls != 1 {
		t.Fatal("not confirmed")
	}
	tick(t, w)
	if len(w.State.S.Watch) != 0 {
		t.Fatal("nonce still watched", w.State.S.Watch)
	}
}

func TestCrashBetweenPrepareAndSubmitSendsOnce(t *testing.T) {
	e := newEnv(t)
	// Reads: 1 unbound, 2 bound, 3 is Submit's fresh read -> crash there,
	// after the prepared record is durable and before the attempt marker.
	e.src.crashAt = 3
	w := e.worker(t)
	if tick(t, w) {
		t.Fatal("expected simulated crash")
	}
	crash(w)
	if e.sender.calls != 0 {
		t.Fatal("sent before crash")
	}
	w2 := e.worker(t)
	if !tick(t, w2) {
		t.Fatal("restart tick did not complete")
	}
	if e.sender.calls != 1 {
		t.Fatal("expected exactly one broadcast, got", e.sender.calls)
	}
	// The saved record is reused: no second redelivery, evaluation or signature.
	if e.seller.calls != 1 || e.pred.calls != 1 {
		t.Fatal("re-evaluated after restart", e.seller.calls, e.pred.calls)
	}
	tick(t, w2)
	if e.sender.calls != 1 {
		t.Fatal("double submission")
	}
}

func TestCrashAfterAttemptMarkerNeverResends(t *testing.T) {
	e := newEnv(t)
	e.sender.mode = sendCrashBefore
	w := e.worker(t)
	if tick(t, w) {
		t.Fatal("expected simulated crash")
	}
	crash(w)
	e.sender.mode = sendOK
	w2 := e.worker(t)
	tick(t, w2)
	tick(t, w2)
	if e.sender.calls != 0 {
		t.Fatal("resent after an attempted broadcast")
	}
	if st := e.entry(t, w2).Status; st != StatusUncertain {
		t.Fatal("status", st)
	}
	// The case times out and is reassigned to someone else: missed, not resent.
	e.src.set(func(a *ledger.Assignment) { a.CaseState = 5; a.Attempt = 1; a.VerifierID = 8; a.BlockNumber = 40 })
	tick(t, w2)
	if st := e.entry(t, w2).Status; st != StatusMissed || e.sender.calls != 0 {
		t.Fatal("status", st, e.sender.calls)
	}
}

func TestCrashAfterBroadcastReconcilesToConfirmed(t *testing.T) {
	e := newEnv(t)
	e.sender.mode = sendCrashAfter
	w := e.worker(t)
	if tick(t, w) {
		t.Fatal("expected simulated crash")
	}
	crash(w)
	e.sender.mode = sendOK
	w2 := e.worker(t)
	tick(t, w2)
	if e.sender.calls != 1 || e.entry(t, w2).Status != StatusUncertain {
		t.Fatal("resent or wrong status", e.sender.calls, e.entry(t, w2).Status)
	}
	e.chain.recorded = true
	e.src.set(func(a *ledger.Assignment) { a.CaseState = 6; a.BlockNumber = 30 })
	tick(t, w2)
	if e.entry(t, w2).Status != StatusConfirmed || e.sender.calls != 1 {
		t.Fatal("not reconciled")
	}
}

func TestLostAcknowledgementIsUncertain(t *testing.T) {
	e := newEnv(t)
	e.sender.mode = sendLost
	w := e.worker(t)
	tick(t, w)
	e.sender.mode = sendOK
	tick(t, w)
	if e.sender.calls != 1 || e.entry(t, w).Status != StatusUncertain {
		t.Fatal("lost ack resent", e.sender.calls)
	}
}

func TestRevertedTransaction(t *testing.T) {
	e := newEnv(t)
	w := e.worker(t)
	tick(t, w)
	e.chain.tx[protocol.Bytes32{9}] = TxStatus{Found: true, Success: false, Block: 12}
	e.src.set(func(a *ledger.Assignment) { a.BlockNumber = 15 })
	tick(t, w)
	if e.entry(t, w).Status != StatusReverted || e.sender.calls != 1 {
		t.Fatal("status", e.entry(t, w).Status)
	}
}

func TestDeadlineBeforePrepare(t *testing.T) {
	e := newEnv(t)
	e.chain.head = 98 // 98 + 1 + margin 2 > judgeDue 100
	w := e.worker(t)
	tick(t, w)
	if e.seller.calls != 0 || e.pred.calls != 0 || e.sender.calls != 0 {
		t.Fatal("worked past the deadline")
	}
	if e.entry(t, w).Status != StatusExpired {
		t.Fatal("status", e.entry(t, w).Status)
	}
}

func TestDeadlineAfterPrepareDoesNotSubmit(t *testing.T) {
	e := newEnv(t)
	e.src.crashAt = 3
	w := e.worker(t)
	tick(t, w)
	crash(w)
	e.chain.head = 99
	w2 := e.worker(t)
	tick(t, w2)
	if e.sender.calls != 0 || e.entry(t, w2).Status != StatusExpired {
		t.Fatal("submitted after deadline", e.sender.calls, e.entry(t, w2).Status)
	}
	// Reassignment then releases the nonce.
	e.src.set(func(a *ledger.Assignment) { a.Attempt = 1; a.VerifierID = 8 })
	tick(t, w2)
	if len(w2.State.S.Watch) != 0 {
		t.Fatal("still watching")
	}
}

func TestPreparedRecordOutlivedByAssignment(t *testing.T) {
	e := newEnv(t)
	e.src.crashAt = 3
	w := e.worker(t)
	tick(t, w)
	crash(w)
	e.src.set(func(a *ledger.Assignment) { a.Attempt = 1; a.VerifierID = 8 })
	w2 := e.worker(t)
	tick(t, w2)
	if e.sender.calls != 0 || e.entry(t, w2).Status != StatusExpired {
		t.Fatal("status", e.entry(t, w2).Status)
	}
}

func TestUnauthenticatedRedeliveryIsNotEvaluated(t *testing.T) {
	e := newEnv(t)
	e.seller.tamper = true
	w := e.worker(t)
	tick(t, w)
	if e.pred.calls != 0 || e.sender.calls != 0 {
		t.Fatal("evaluated unauthenticated bundle")
	}
	e.seller.tamper = false
	tick(t, w)
	if e.pred.calls != 1 || e.sender.calls != 1 {
		t.Fatal("did not retry after a valid redelivery", e.pred.calls, e.sender.calls)
	}
}

func TestUnknownVerdictNameRejected(t *testing.T) {
	e := newEnv(t)
	e.pred.env.Verdict = "MAYBE"
	w := e.worker(t)
	tick(t, w)
	if e.sender.calls != 0 || e.entry(t, w).Status != "" {
		t.Fatal("accepted unknown verdict")
	}
}

func TestOtherVerifierAndUnknownProfile(t *testing.T) {
	e := newEnv(t)
	e.src.set(func(a *ledger.Assignment) { a.VerifierID = 8 })
	w := e.worker(t)
	tick(t, w)
	if e.seller.calls != 0 || len(w.State.S.Watch) != 0 {
		t.Fatal("worked on another verifier's assignment")
	}
	e2 := newEnv(t)
	w2 := e2.worker(t)
	w2.Opts.Bindings = nil
	tick(t, w2)
	if e2.seller.calls != 0 || e2.entry(t, w2).Status != StatusSkipped {
		t.Fatal("unknown profile not skipped")
	}
}

func TestCursorAdvancesAndPersists(t *testing.T) {
	e := newEnv(t)
	w := e.worker(t)
	w.Opts.StartBlock = 5
	tick(t, w)
	e.chain.fin = 12
	tick(t, w)
	crash(w)
	w2 := e.worker(t)
	tick(t, w2)
	want := [][2]uint64{{5, 10}, {11, 12}}
	if len(e.chain.scans) != 2 || e.chain.scans[0] != want[0] || e.chain.scans[1] != want[1] || w2.State.S.Cursor != 13 {
		t.Fatal("scans", e.chain.scans, w2.State.S.Cursor)
	}
}

func TestStateDirectoryIsExclusive(t *testing.T) {
	dir := t.TempDir()
	s, err := OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = OpenStore(dir); err == nil {
		t.Fatal("second worker opened the same state")
	}
	s.S.Cursor = 7
	if err = s.Save(); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s, err = OpenStore(dir)
	if err != nil || s.S.Cursor != 7 {
		t.Fatal(err)
	}
	s.Close()
}

func TestRegistryDispatchesByClass(t *testing.T) {
	e := newEnv(t)
	r := Registry{1: e.pred}
	if _, err := r.Evaluate(context.Background(), e.a, gate.Bundle{}, gate.Result{Status: gate.Ready}); err != nil || e.pred.calls != 1 {
		t.Fatal(err)
	}
	a := e.a
	a.Snapshot.ClassID = 2
	if _, err := r.Evaluate(context.Background(), a, gate.Bundle{}, gate.Result{}); err == nil {
		t.Fatal("dispatched to missing class")
	}
}
